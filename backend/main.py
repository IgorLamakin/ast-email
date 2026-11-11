from typing import Optional, List
from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import html
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
import models, schemas, database
from database import get_db, engine
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import re
import os
import json
import traceback
import base64
import mimetypes
import hashlib

# ========== FILE LOGGING ==========
import logging
# Write logs to APPDATA, not Program Files (no write permissions there)
log_dir = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'ast-email-templates', 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'backend.log')
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logger.info("=" * 50)
logger.info("Backend starting up")
logger.info("=" * 50)

# SMTP Settings (set via environment variables or defaults for local testing)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")

# Upload settings
UPLOAD_DIR = os.getenv("APP_UPLOAD_DIR", os.path.join(os.path.dirname(__file__), "uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ========== SECRET KEY (для подписи JWT) ==========
# ВАЖНО: ключ больше не хранится в исходном коде (иначе он попадает в поставку приложения
# и позволяет подделать токен любого пользователя). Ключ можно передать через переменную
# окружения SECRET_KEY (это делает Electron из settings.json), а если её нет — ключ
# генерируется один раз и сохраняется в APPDATA, чтобы не менялся между запусками
# (иначе все выданные токены становились бы недействительными при каждом рестарте).
import secrets as _secrets
_app_data_dir = os.environ.get('APPDATA', os.path.expanduser('~'))
_secret_key_path = os.path.join(_app_data_dir, 'ast-email-templates', 'secret.key')


def _load_or_create_secret_key():
    env_secret = os.getenv("SECRET_KEY", "")
    if env_secret:
        return env_secret
    try:
        if os.path.exists(_secret_key_path):
            with open(_secret_key_path, "r", encoding="utf-8") as f:
                key = f.read().strip()
                if key:
                    return key
        os.makedirs(os.path.dirname(_secret_key_path), exist_ok=True)
        key = _secrets.token_hex(32)
        with open(_secret_key_path, "w", encoding="utf-8") as f:
            f.write(key)
        return key
    except OSError:
        # Если по какой-то причине нельзя писать на диск - используем ключ только
        # в рамках текущего запуска процесса (токены не переживут рестарт, но это
        # безопаснее, чем захардкоженный публичный ключ).
        return _secrets.token_hex(32)

# Отладочный вывод SMTP настроек при старте
logger.info("SMTP Configuration:")
logger.info(f"  HOST: {SMTP_HOST or '(not set)'}")
logger.info(f"  PORT: {SMTP_PORT}")
logger.info(f"  USER: {SMTP_USER or '(not set)'}")
logger.info(f"  PASS: {'*' * len(SMTP_PASSWORD) if SMTP_PASSWORD else '(not set)'}")
logger.info(f"  FROM: {SMTP_FROM or '(not set)'}")
if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
    logger.warning("SMTP not fully configured - emails will not be sent!")

# Создаем таблицы
models.Base.metadata.create_all(bind=engine)


def _migrate_sqlite_schema():
    """SQLAlchemy's create_all() создаёт только отсутствующие ТАБЛИЦЫ, но не добавляет
    новые колонки в уже существующие таблицы. Поскольку у пользователей уже может быть
    рабочая база данных с прошлой версии приложения, добавляем недостающие колонки
    вручную через ALTER TABLE (для SQLite этого достаточно, полноценный
    инструмент миграций здесь избыточен)."""
    with engine.connect() as conn:
        existing_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(email_logs)").fetchall()}
        if "template_title" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE email_logs ADD COLUMN template_title VARCHAR")
        if "status" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE email_logs ADD COLUMN status VARCHAR DEFAULT 'sent'")
        template_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(templates)").fetchall()}
        if "attach_pdf" not in template_cols:
            conn.exec_driver_sql("ALTER TABLE templates ADD COLUMN attach_pdf BOOLEAN DEFAULT 0")
        if "blocks" not in template_cols:
            conn.exec_driver_sql("ALTER TABLE templates ADD COLUMN blocks TEXT")
        if "seed_key" not in template_cols:
            conn.exec_driver_sql("ALTER TABLE templates ADD COLUMN seed_key VARCHAR")
        settings_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(app_settings)").fetchall()}
        if "seed_template_version" not in settings_cols:
            conn.exec_driver_sql("ALTER TABLE app_settings ADD COLUMN seed_template_version VARCHAR")
        if "presentation_seed_version" not in settings_cols:
            conn.exec_driver_sql("ALTER TABLE app_settings ADD COLUMN presentation_seed_version VARCHAR")
        # 2.7.0: массовая рассылка. Колонки добавляем через ALTER - у пользователей
        # уже есть рабочая база, create_all() новые колонки в существующую таблицу
        # не добавляет. Значения по умолчанию: выключено, 250 писем/сутки.
        if "mass_mailing_enabled" not in settings_cols:
            conn.exec_driver_sql("ALTER TABLE app_settings ADD COLUMN mass_mailing_enabled BOOLEAN DEFAULT 0")
        if "mass_mailing_daily_limit" not in settings_cols:
            conn.exec_driver_sql("ALTER TABLE app_settings ADD COLUMN mass_mailing_daily_limit INTEGER DEFAULT 250")
        conn.commit()


_migrate_sqlite_schema()

# ========== AUTO-SEED TEMPLATES ==========
# Версия «прошивки» стандартных шаблонов. При каждом обновлении приложения мы
# поднимаем её, и содержимое 5 стандартных писем один раз синхронизируется с
# файлами (дизайн, бренды, офферы). На повторных запусках той же версии
# пользовательские правки стандартных шаблонов НЕ затираются (в отличие от
# v2.4.0, где содержимое перезаписывалось при КАЖДОМ старте).
TEMPLATE_SEED_VERSION = "2026-09-08"
# Одноразовая версия обновления шаблона «Презентация компании» (2.5.4:
# контакты сверху, CTA и кнопки скачивания). Не меняет TEMPLATE_SEED_VERSION,
# чтобы не перезаписывать правки остальных стандартных шаблонов.
PRESENTATION_TEMPLATE_VERSION = "2026-11-08"

def auto_seed_templates():
    """Обеспечивает наличие и актуальность 5 стандартных шаблонов.

    Стандартный шаблон ищется по стабильному `seed_key`, а не только по
    названию/статусу. Это важно: администратор может переименовать стандартное
    письмо или снять его с публикации - раньше в обоих случаях при следующем
    запуске создавался дубликат. Для баз, созданных до 2.5.2, ключ при первом
    запуске проставляется существующим стандартным шаблонам по названию.

    С версии 2.5.0: обновление содержимого происходит только при смене версии
    (TEMPLATE_SEED_VERSION) - один раз после обновления приложения. Повторные
    запуски той же версии только досоздают отсутствующие шаблоны и не трогают
    уже существующие (даже если администратор их отредактировал).
    """
    db = next(database.get_db())
    try:
        admin = db.query(models.User).filter(models.User.role == models.UserRole.ADMIN).first()
        if not admin:
            return
        settings = db.query(models.AppSettings).order_by(models.AppSettings.id).first()
        seeded_version = (settings.seed_template_version if settings else None)
        should_resync = (seeded_version != TEMPLATE_SEED_VERSION)

        # Сначала ищем по стабильному ключу. Только для старых баз (ключ ещё не
        # проставлен) допускаем поиск по названию среди шаблонов администратора.
        existing_by_key = {
            t.seed_key: t for t in db.query(models.Template)
            .filter(models.Template.seed_key.isnot(None)).all()
        }
        existing_by_title = {
            t.title: t for t in db.query(models.Template)
            .filter(models.Template.seed_key.is_(None),
                    models.Template.owner_id == admin.id).all()
        }
        import os
        template_dir = os.path.join(os.path.dirname(__file__), "email_templates")
        templates = [
            ("general", "АСТ — Общий обзор компании", "template_1_general.html"),
            ("supplies", "АСТ — Поставка компонентов КИПиА и АСУТП", "template_2_supplies.html"),
            ("cabinets", "АСТ — Производство и сборка шкафов", "template_3_cabinets.html"),
            ("engineering", "АСТ — Инжиниринг и разработка ПО", "template_4_engineering.html"),
            ("cases", "АСТ — Реализованные проекты", "template_5_cases.html"),
            ("presentation", "АСТ — Презентация компании", "template_6_presentation.html"),
        ]
        changed = False
        for seed_key, title, filename in templates:
            filepath = os.path.join(template_dir, filename)
            if not os.path.exists(filepath):
                continue
            with open(filepath, "r", encoding="utf-8") as f:
                html = f.read()
            t = existing_by_key.get(seed_key)
            if t is None:
                # Миграция старой базы: стандартный шаблон уже есть, но без ключа.
                t = existing_by_title.get(title)
                if t is not None:
                    t.seed_key = seed_key
                    changed = True
            if t is None:
                nt = models.Template(
                    title=title,
                    html_content=html,
                    status=models.TemplateStatus.PUBLISHED,
                    owner_id=admin.id,
                    seed_key=seed_key,
                )
                db.add(nt)
                changed = True
            elif should_resync and t.html_content != html:
                # Версия «прошивки» сменилась - обновляем стандартные письма,
                # сохраняя текущее название и статус (администратор мог их изменить).
                t.html_content = html
                db.add(t)
                changed = True

        if should_resync:
            if settings is None:
                settings = models.AppSettings(id=1)
                db.add(settings)
            settings.seed_template_version = TEMPLATE_SEED_VERSION
            changed = True

        # 2.5.4: один раз обновляем HTML шаблона «Презентация компании»
        # (добавлены контакты вверху, CTA и кнопки скачивания). Отдельный
        # флаг не даёт перезаписывать шаблон при каждом следующем запуске.
        if settings is None:
            settings = models.AppSettings(id=1)
            db.add(settings)
            changed = True
        if settings.presentation_seed_version != PRESENTATION_TEMPLATE_VERSION:
            presentation_path = os.path.join(template_dir, "template_6_presentation.html")
            presentation = db.query(models.Template).filter(
                models.Template.seed_key == "presentation"
            ).first()
            if presentation is not None and os.path.exists(presentation_path):
                with open(presentation_path, "r", encoding="utf-8") as f:
                    presentation_html = f.read()
                if presentation.html_content != presentation_html:
                    presentation.html_content = presentation_html
                    db.add(presentation)
                    changed = True
            settings.presentation_seed_version = PRESENTATION_TEMPLATE_VERSION
            changed = True

        if changed:
            db.commit()
    finally:
        db.close()

auto_seed_templates()

app = FastAPI(title="Email Template API", version="2.7.1")

# Root app with /api prefix for production compatibility
root_app = FastAPI(title="Email Template API Root", version="2.7.1")
root_app.mount("/api", app)

# ========== SMTP SETTINGS HELPER ==========
def get_smtp_settings(db: Session):
    """Получить SMTP настройки из БД или переменных окружения"""
    settings = db.query(models.AppSettings).first()
    if settings and settings.smtp_host and settings.smtp_user and settings.smtp_password:
        port = int(settings.smtp_port) if settings.smtp_port else 587
        return {
            "host": settings.smtp_host,
            "port": port,
            "user": settings.smtp_user,
            "password": settings.smtp_password,
            "from": settings.smtp_from or settings.smtp_user,
        }
    # Fallback to environment variables
    if SMTP_HOST and SMTP_USER and SMTP_PASSWORD:
        return {
            "host": SMTP_HOST,
            "port": SMTP_PORT,
            "user": SMTP_USER,
            "password": SMTP_PASSWORD,
            "from": SMTP_FROM or SMTP_USER,
        }
    return None

# CORS
# Приложение авторизуется Bearer-токеном в заголовке (см. frontend/src/api.js),
# куки не используются - allow_credentials не нужен. Origin'ы ограничены
# реально используемыми: dev-сервер Vite и file:// окно собранного Electron-
# приложения (Chromium отправляет для file:// буквальный Origin: null).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "null"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check():
    return {"status": "ok"}

# Security
SECRET_KEY = _load_or_create_secret_key()
ALGORITHM = "HS256"
# Десктоп-инструмент для внутреннего использования - разумно не разлогинивать людей
# каждые 15 минут. Значение реально используется теперь (раньше константа была мёртвой).
ACCESS_TOKEN_EXPIRE_MINUTES = 12 * 60  # 12 часов
# Срок жизни refresh-токена («запомнить вход»). 180 дней - компромисс: приложение
# десктопное и личное, заставлять вводить пароль раз в 12 часов бессмысленно, но
# и вечная сессия не нужна: токен можно отозвать (logout) и он ограничен по времени.
REFRESH_TOKEN_EXPIRE_DAYS = 180

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# ========== HELPERS ==========
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def _hash_refresh_token(raw_token: str) -> str:
    """SHA-256 от «сырого» refresh-токена.

    В базе храним только хеш, как и для паролей: если база утечёт (или её просто
    скопируют вместе с папкой приложения), восстановить по хешу исходную строку
    нельзя, а значит нельзя и войти, используя украденный файл app.db.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _issue_token_pair(db: Session, user_id: int, expires_delta: Optional[timedelta] = None) -> dict:
    """Выдаёт новую пару access+refresh и сохраняет refresh-токен в базе.

    refresh-токен - случайная строка (secrets.token_urlsafe(48)), а не JWT: он
    проверяется по базе, поэтому его нельзя «подделать», даже зная SECRET_KEY.
    Одноразовость обеспечивает /auth/refresh: при обмене старый токен отзывается.

    expires_delta нужен для тестов (можно выпустить заведомо просроченный токен),
    в обычной работе не передаётся - срок берётся из REFRESH_TOKEN_EXPIRE_DAYS.

    Коммит делаем здесь, а не у вызывающего кода: refresh-токен бесполезен, пока
    не сохранён, и логин/регистрация не должны помнить о том, что пару надо ещё
    и записать в базу. Заодно этим коммитом сохраняются изменения, накопленные
    вызывающим кодом (например, отзыв старого токена при ротации).
    """
    raw_refresh_token = _secrets.token_urlsafe(48)
    now = datetime.utcnow()
    db.add(models.RefreshToken(
        user_id=user_id,
        token_hash=_hash_refresh_token(raw_refresh_token),
        created_at=now,
        # expires_delta может быть и отрицательным (для тестов) - проверяем именно
        # на None, а не на истинность: timedelta(0) в логическом смысле ложно.
        expires_at=now + (expires_delta if expires_delta is not None
                          else timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)),
    ))
    db.commit()
    return {
        "access_token": create_access_token(data={"sub": str(user_id)}),
        "token_type": "bearer",
        "refresh_token": raw_refresh_token,
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        user_id = int(user_id)
    except (JWTError, ValueError, TypeError):
        raise credentials_exception
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        raise credentials_exception
    return user

def get_current_admin(current_user: models.User = Depends(get_current_user)):
    if current_user.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

# ========== МАССОВАЯ РАССЫЛКА (2.7.0) ==========
# Роутер подключается здесь, а не в начале файла: campaigns.py в момент вызова
# использует get_current_user/get_smtp_settings и прочие хелперы этого модуля.
# Сам campaigns.py не импортирует main на уровне модуля (только внутри функций),
# поэтому циклического импорта нет.
import campaigns  # noqa: E402
import campaign_worker  # noqa: E402

app.include_router(campaigns.router)

# Восстановление состояния очереди после аварийного завершения приложения:
# кампании из running -> paused, «подвисшие» in_flight получатели -> unknown.
# Вызывается при старте backend (импорт main.py = старт приложения/тестов).
campaign_worker.recover_after_restart()

# ========== SAFE TEMPLATE RENDERING (SSTI-безопасно) ==========
# Шаблоны писем хранят HTML с плейсхолдерами вида {{ name }}. Раньше контент
# (в т.ч. вводимый пользователем в редакторе блоков) прогонялся через Jinja2
# с выключенным autoescape - это давало выполнение произвольного шаблонного кода
# на сервере (SSTI -> RCE): в текст блока достаточно было вписать что-то вроде
#   {{ cycler.__init__.__globals__.os.popen('calc.exe').read() }}
# Теперь поддерживается ТОЛЬКО конечный белый список плейсхолдеров, каждое
# значение HTML-экранируется, а любой другой код (в т.ч. {{ ... }} / {% ... %})
# на сервере НЕ исполняется и остаётся обычным текстом.
SAFE_PLACEHOLDERS = {
    "greeting", "recipient_email", "sender_email",
    "full_name", "position", "company", "address", "phone", "website",
    # 2.7.0: имя получателя из файла массовой рассылки ({{ name }}). В обычных
    # шаблонах этот плейсхолдер не используется, поведение старых писем не меняется.
    "name",
}
_PH_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def _safe_escape(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _normalize_website(value):
    """Приводит сайт к полному URL с префиксом https:// (если его нет), чтобы
    в шаблоне ссылка вида href=\"{{ website }}\" не превращалась в
    https://https://site.ru, когда пользователь указал сайт со схемой."""
    if not value:
        return ""
    v = str(value).strip()
    if v and not re.match(r"^https?://", v, re.IGNORECASE):
        v = "https://" + v
    return v


def _render_template_html(html_content: str, context: dict) -> str:
    """Безопасная подстановка плейсхолдеров без исполнения шаблонного кода."""
    def _repl(m):
        name = m.group(1)
        if name not in SAFE_PLACEHOLDERS:
            # Неизвестные плейсхолдеры/код оставляем как обычный текст.
            return m.group(0)
        return _safe_escape(context.get(name, ""))
    return _PH_RE.sub(_repl, html_content)


def _compact_email_snapshot(html_content: str, limit: int = 20000) -> str:
    """Компактный снимок письма для лога: убирает большие base64/data-URI и
    урезает длину, чтобы не раздувать SQLite на гигабайты. Нужен только для
    отладки (нигде в UI не показывается)."""
    stripped = re.sub(r'data:[^"\')\s]+', '[вложение]', html_content)
    stripped = re.sub(r'\s+', ' ', stripped).strip()
    if len(stripped) > limit:
        stripped = stripped[:limit] + '…[обрезано]'
    return stripped


# Загрузка файлов: максимальный размер и белый список расширений. Исполняемые,
# HTML/SVG и прочие «живые» форматы не принимаем - они могли бы стать вектором
# XSS при отдаче с localhost:8000 или при открытии получателем письма.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 МБ
ALLOWED_UPLOAD_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".rtf", ".csv", ".zip",
}


# ========== AUTH ==========
@app.post("/auth/register", response_model=schemas.Token)
def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == user.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    # Администратором автоматически становится только самый первый пользователь
    # в системе (обычно это тот, кто проходит мастер первоначальной настройки).
    # Все, кто регистрируется позже, получают обычную роль - иначе любой человек,
    # открывший приложение, мог бы сам выдать себе права администратора и увидеть
    # аналитику по всем отправленным письмам.
    is_first_user = db.query(models.User).count() == 0
    db_user = models.User(
        email=user.email,
        hashed_password=get_password_hash(user.password),
        full_name=user.full_name,
        role=models.UserRole.ADMIN if is_first_user else models.UserRole.USER
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    # Стандартные шаблоны заполняются автоматически при старте бэкенда (см.
    # auto_seed_templates() выше), но на самом первом запуске в этот момент в базе
    # ещё нет ни одного администратора - функция просто ничего не делает и молча
    # выходит. После того как первый пользователь регистрируется и становится
    # администратором, повторно эта функция раньше не вызывалась вообще, поэтому
    # шаблоны так и оставались пустыми до следующего перезапуска бэкенда. Теперь
    # вызываем её сразу после появления первого администратора - благодаря более
    # раннему исправлению дедупликации (проверка по названию) это безопасно
    # вызывать в любой момент, повторного добавления не произойдёт.
    if is_first_user:
        auto_seed_templates()

    # Вместе с access-токеном сразу выдаём refresh-токен: человек только что
    # зарегистрировался, и «запомнить вход» должно работать без повторного входа.
    return _issue_token_pair(db, db_user.id)

@app.post("/auth/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    # Housekeeping: каждый вход создаёт новую запись refresh-токена, а старые
    # (просроченные) уже никому не нужны - подчищаем их, чтобы таблица не росла
    # бесконечно на протяжении лет эксплуатации. Отдельный коммит не делаем:
    # _issue_token_pair ниже коммитит и это удаление, и новый токен.
    db.query(models.RefreshToken).filter(
        models.RefreshToken.expires_at < datetime.utcnow()
    ).delete(synchronize_session=False)
    return _issue_token_pair(db, user.id)

@app.post("/auth/refresh", response_model=schemas.Token)
def refresh_access_token(payload: schemas.RefreshRequest, db: Session = Depends(get_db)):
    """Обмен refresh-токена на новую пару access+refresh («запомнить вход»).

    Bearer-заголовок здесь не нужен: access-токен к этому моменту как раз может
    быть просрочен - за новым и приходят. Ротация обязательна: старый refresh
    отзывается, украденным (или перехваченным из лога) токеном можно
    воспользоваться только один раз, после чего он недействителен.
    """
    invalid_refresh = HTTPException(status_code=401, detail="Invalid refresh token")
    stored = db.query(models.RefreshToken).filter(
        models.RefreshToken.token_hash == _hash_refresh_token(payload.refresh_token)
    ).first()
    now = datetime.utcnow()
    # Неизвестный/просроченный/уже отозванный токен - один и тот же ответ 401 без
    # подробностей: не подсказываем, существует ли такой токен вообще.
    if stored is None or stored.revoked_at is not None or stored.expires_at <= now:
        raise invalid_refresh
    stored.revoked_at = now
    stored.last_used_at = now
    db.add(stored)
    # Новая пара выдаётся и коммитится внутри _issue_token_pair - вместе с
    # отзывом старого токена (одна транзакция, без «полуротации»).
    return _issue_token_pair(db, stored.user_id)

@app.post("/auth/logout")
def logout(payload: schemas.RefreshRequest, db: Session = Depends(get_db)):
    """Отзыв refresh-токена при выходе из приложения.

    Идемпотентно: даже если токен уже отозван/неизвестен/просрочен, отвечаем 200
    «Logged out». Выход не должен «падать» из-за того, что токена уже нет - иначе
    на фронтенде непонятно, разлогинили человека или нет.
    """
    stored = db.query(models.RefreshToken).filter(
        models.RefreshToken.token_hash == _hash_refresh_token(payload.refresh_token)
    ).first()
    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = datetime.utcnow()
        stored.last_used_at = stored.revoked_at
        db.add(stored)
        db.commit()
    return {"message": "Logged out"}

@app.get("/auth/me", response_model=schemas.UserResponse)
def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user

# ========== USERS ==========
@app.get("/users", response_model=List[schemas.UserResponse])
def list_users(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_admin)):
    return db.query(models.User).all()

@app.put("/users/{user_id}", response_model=schemas.UserResponse)
def update_user(user_id: int, user_update: schemas.UserUpdate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if current_user.id != user_id and current_user.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not allowed")
    update_data = user_update.dict(exclude_unset=True)
    # Роль может менять только администратор (и не самому себе - чтобы нельзя было
    # случайно/намеренно понизить единственного админа без возможности отмены).
    if "role" in update_data:
        if current_user.role != models.UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Only admins can change roles")
        if current_user.id == user_id:
            raise HTTPException(status_code=400, detail="Cannot change your own role")
    for field, value in update_data.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user

# ========== CONTACTS ==========
@app.get("/contacts", response_model=List[schemas.ContactResponse])
def list_contacts(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return db.query(models.Contact).filter(models.Contact.owner_id == current_user.id).all()

@app.post("/contacts", response_model=schemas.ContactResponse)
def create_contact(contact: schemas.ContactCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    existing = db.query(models.Contact).filter(
        models.Contact.email == contact.email,
        models.Contact.owner_id == current_user.id
    ).first()
    if existing:
        existing.greeting = contact.greeting
        db.commit()
        db.refresh(existing)
        return existing
    db_contact = models.Contact(**contact.dict(), owner_id=current_user.id)
    db.add(db_contact)
    db.commit()
    db.refresh(db_contact)
    return db_contact

@app.delete("/contacts/{contact_id}")
def delete_contact(contact_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    contact = db.query(models.Contact).filter(models.Contact.id == contact_id, models.Contact.owner_id == current_user.id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    db.delete(contact)
    db.commit()
    return {"message": "Contact deleted"}

# ========== SENDER ADDRESSES (история адресов отправителя) ==========
# Сколько адресов отдавать в подсказку формы отправки. Больше 25 в выпадающем
# списке всё равно бесполезно: искать в нём неудобно, а человек пользуется
# несколькими адресами, а не десятками.
SENDER_ADDRESS_LIST_LIMIT = 25


def _remember_sender_address(db: Session, user: models.User, email: str) -> models.SenderAddress:
    """Запомнить адрес отправителя в истории пользователя (upsert).

    Вызывается и из POST /sender-emails (явное добавление/повтор), и из
    POST /email/send (автоматически при отправке). Коммит НЕ делаем: вызывающий
    код коммитит сам - в /email/send это уже существующий единый commit, который
    сохраняет и контакт, и лог отправки, и адрес; лишний commit здесь означал бы
    отдельную транзакцию на каждое действие.
    """
    existing = db.query(models.SenderAddress).filter(
        models.SenderAddress.owner_id == user.id,
        models.SenderAddress.email == email
    ).first()
    now = datetime.utcnow()
    if existing:
        existing.use_count = (existing.use_count or 0) + 1
        existing.last_used_at = now
        return existing
    record = models.SenderAddress(
        owner_id=user.id,
        email=email,
        use_count=1,
        last_used_at=now,
        created_at=now,
    )
    db.add(record)
    return record


@app.get("/sender-emails", response_model=List[schemas.SenderAddressResponse])
def list_sender_emails(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    """История адресов отправителя текущего пользователя: сначала недавние."""
    return db.query(models.SenderAddress).filter(
        models.SenderAddress.owner_id == current_user.id
    ).order_by(
        models.SenderAddress.last_used_at.desc()
    ).limit(SENDER_ADDRESS_LIST_LIMIT).all()


@app.post("/sender-emails", response_model=schemas.SenderAddressResponse)
def upsert_sender_email(payload: schemas.SenderAddressCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    """Добавить адрес в историю вручную (или «поднять» уже известный наверх)."""
    record = _remember_sender_address(db, current_user, payload.email)
    db.commit()
    db.refresh(record)
    return record


@app.delete("/sender-emails/{sender_address_id}")
def delete_sender_email(sender_address_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    """Удалить адрес из истории. Только свой: чужую запись не видно и не удалить."""
    record = db.query(models.SenderAddress).filter(
        models.SenderAddress.id == sender_address_id,
        models.SenderAddress.owner_id == current_user.id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Sender email not found")
    db.delete(record)
    db.commit()
    return {"message": "Sender email deleted"}

# ========== TEMPLATES ==========
@app.get("/templates", response_model=List[schemas.TemplateResponse])
def list_templates(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return db.query(models.Template).filter(
        (models.Template.owner_id == current_user.id) | (models.Template.status == models.TemplateStatus.PUBLISHED)
    ).all()

@app.post("/templates", response_model=schemas.TemplateResponse)
def create_template(template: schemas.TemplateCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    db_template = models.Template(**template.dict(), owner_id=current_user.id)
    db.add(db_template)
    db.commit()
    db.refresh(db_template)
    return db_template

@app.get("/templates/{template_id}", response_model=schemas.TemplateResponse)
def get_template(template_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    template = db.query(models.Template).filter(
        (models.Template.id == template_id) &
        ((models.Template.owner_id == current_user.id) | (models.Template.status == models.TemplateStatus.PUBLISHED))
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template

@app.put("/templates/{template_id}", response_model=schemas.TemplateResponse)
def update_template(template_id: int, template_update: schemas.TemplateUpdate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    template = db.query(models.Template).filter(models.Template.id == template_id, models.Template.owner_id == current_user.id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    for field, value in template_update.dict(exclude_unset=True).items():
        setattr(template, field, value)
    db.commit()
    db.refresh(template)
    return template

@app.delete("/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    template = db.query(models.Template).filter(models.Template.id == template_id, models.Template.owner_id == current_user.id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    # Отвязываем логи отправок от удаляемого шаблона (название писем в истории уже
    # сохранено отдельно в EmailLog.template_title, так что аналитика не пострадает).
    # Раньше эта связь оставалась "висячей" и ломала всю страницу аналитики.
    db.query(models.EmailLog).filter(models.EmailLog.template_id == template_id).update(
        {models.EmailLog.template_id: None}
    )
    db.delete(template)
    db.commit()
    return {"message": "Template deleted"}

@app.post("/templates/{template_id}/publish", response_model=schemas.TemplateResponse)
def publish_template(template_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    # Администратор может опубликовать шаблон любого пользователя (нужно для
    # раздела "Аккаунты" - "сделать чужой шаблон доступным всем"), обычный
    # пользователь - только свой собственный.
    query = db.query(models.Template).filter(models.Template.id == template_id)
    if current_user.role != models.UserRole.ADMIN:
        query = query.filter(models.Template.owner_id == current_user.id)
    template = query.first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    template.status = models.TemplateStatus.PUBLISHED
    db.commit()
    db.refresh(template)
    return template

@app.post("/templates/{template_id}/unpublish", response_model=schemas.TemplateResponse)
def unpublish_template(template_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    query = db.query(models.Template).filter(models.Template.id == template_id)
    if current_user.role != models.UserRole.ADMIN:
        query = query.filter(models.Template.owner_id == current_user.id)
    template = query.first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    template.status = models.TemplateStatus.DRAFT
    db.commit()
    db.refresh(template)
    return template

@app.post("/templates/{template_id}/preview")
def preview_template(template_id: int, request: schemas.EmailSendRequest, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    template = db.query(models.Template).filter(
        (models.Template.id == template_id) &
        ((models.Template.owner_id == current_user.id) | (models.Template.status == models.TemplateStatus.PUBLISHED))
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    rendered_html = _render_template_html(template.html_content, {
        "greeting": request.greeting or "",
        "recipient_email": request.recipient_email,
        "sender_email": request.sender_email,
        "full_name": current_user.full_name or "",
        "position": current_user.position or "",
        "company": current_user.company or "",
        "phone": current_user.phone or "",
        "address": current_user.address or "",
        "website": _normalize_website(current_user.website or ""),
    })
    return {"html_preview": rendered_html, "template_title": template.title}

# ========== SMTP TEST ==========
def _test_smtp_connection(smtp_cfg):
    """Проверка подключения к SMTP (только connect + login, без отправки)."""
    host = smtp_cfg["host"]
    port = int(smtp_cfg.get("port", 587))
    user = smtp_cfg["user"]
    password = smtp_cfg["password"]

    logger.info(f"[_test_smtp_connection] host={host}, port={port}, user={user}, pass_len={len(password)}")

    if port == 465:
        logger.info("Using SMTP_SSL for port 465")
        with smtplib.SMTP_SSL(host, port, timeout=10) as server:
            server.login(user, password)
    else:
        logger.info(f"Using STARTTLS for port {port}")
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, password)

def _file_to_data_uri(filename: str) -> str | None:
    """Читает файл из папки загрузок и превращает в data:-URI. Возвращает None,
    если файла нет на диске или его не удалось прочитать - тогда исходная
    ссылка остаётся как есть (лучше оставить рабочую (для отправителя) ссылку,
    чем уронить отправку всего письма необработанным исключением)."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        return None
    try:
        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or 'application/octet-stream'
        with open(file_path, 'rb') as f:
            encoded = base64.b64encode(f.read()).decode('ascii')
        return f"data:{mime_type};base64,{encoded}"
    except OSError as e:
        logger.warning(f"Не удалось прочитать файл картинки {file_path} для встраивания в письмо: {e}")
        return None


# Суммарный лимит на встроенные (base64) картинки одного письма. Без лимита
# несколько крупных изображений могут раздуть итоговое MIME-письмо за пределы,
# которые принимает SMTP-сервер получателя, без предупреждения пользователю.
MAX_INLINE_IMAGES_BYTES = 15 * 1024 * 1024


def _inline_local_images(html: str) -> str:
    """Заменяет ссылки на картинки, загруженные через наш /api/uploads/...,
    на встроенные data:-URI прямо внутри HTML письма.

    Это обязательно для реальной отправки: адрес вида http://localhost:8000/...
    существует только на компьютере отправителя - получатель письма (не он)
    открывает почту на СВОЁМ устройстве и физически не может достучаться до
    чужого localhost. Без этой замены картинки в письме были бы битыми у всех,
    кроме самого отправителя."""
    total_size = {"bytes": 0}

    def replace_src(match):
        quote, filename = match.group(1), match.group(2)
        data_uri = _file_to_data_uri(filename)
        if not data_uri:
            return match.group(0)
        total_size["bytes"] += len(data_uri)
        return f'src={quote}{data_uri}{quote}'

    def replace_bg(match):
        quote, filename = match.group(1) or "", match.group(2)
        data_uri = _file_to_data_uri(filename)
        if not data_uri:
            return match.group(0)
        total_size["bytes"] += len(data_uri)
        return f"background-image:url({quote}{data_uri}{quote})"

    # Кавычки вокруг src/url(...) допускаются одинарные, двойные или (только
    # для url()) отсутствующие - генератор BlockEditor.jsx сейчас всегда
    # использует один конкретный вариант, но встраивание не должно молча
    # ломаться при любом другом валидном HTML.
    html = re.sub(r'src=(["\'])[^"\']*?/uploads/([a-zA-Z0-9_.\-]+)\1', replace_src, html)
    html = re.sub(r"background-image:url\((['\"]?)[^'\")]*?/uploads/([a-zA-Z0-9_.\-]+)\1\)", replace_bg, html)

    if total_size["bytes"] > MAX_INLINE_IMAGES_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Суммарный размер картинок в письме слишком большой "
                f"({total_size['bytes'] // (1024 * 1024)} МБ после кодирования) - "
                f"многие почтовые серверы отклонят такое письмо. Уменьшите "
                f"размер или количество изображений."
            ),
        )

    return html


def _strip_pdf_excluded(html: str) -> str:
    """Убирает из HTML те элементы, что помечены фронтендом как
    data-pdf-exclude="true" (сейчас это блоки-кнопки) - в статичном PDF-документе
    кликабельным кнопкам не место, они там всё равно не работают."""
    return re.sub(r'<div[^>]*data-pdf-exclude="true"[^>]*>.*?</div>', '', html, flags=re.DOTALL)


def _html_to_pdf_bytes(html: str) -> bytes:
    """Конвертирует HTML письма в PDF. Возвращает None и пишет в лог, если
    xhtml2pdf не установлен или конвертация не удалась - отправка самого письма
    из-за этого падать не должна, PDF-вложение необязательный бонус."""
    try:
        from xhtml2pdf import pisa
    except ImportError:
        logger.warning("xhtml2pdf не установлен - PDF-вложение пропущено. Установите: pip install xhtml2pdf")
        return None
    import io
    buffer = io.BytesIO()
    result = pisa.CreatePDF(html, dest=buffer, encoding='utf-8')
    if result.err:
        logger.error(f"xhtml2pdf вернул {result.err} ошибок при генерации PDF")
        return None
    return buffer.getvalue()

def _send_via_smtp(smtp_cfg, sender, recipient, msg_string):
    """Отправка письма с автовыбором SSL/STARTTLS по порту."""
    host = smtp_cfg["host"]
    port = int(smtp_cfg.get("port", 587))
    user = smtp_cfg["user"]
    password = smtp_cfg["password"]

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=10) as server:
            server.login(user, password)
            server.sendmail(sender, recipient, msg_string)
    else:
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, password)
            server.sendmail(sender, recipient, msg_string)

@app.post("/email/test-smtp")
def test_smtp(
    request: schemas.AppSettingsCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin)
):
    """Проверка конфигурации SMTP без отправки письма"""
    logger.info("=" * 50)
    logger.info("SMTP TEST endpoint called")
    logger.info(f"Request smtp_host: {request.smtp_host}")
    logger.info(f"Request smtp_port: {request.smtp_port} (type: {type(request.smtp_port).__name__})")
    logger.info(f"Request smtp_user: {request.smtp_user}")
    logger.info(f"Request smtp_password length: {len(request.smtp_password) if request.smtp_password else 0}")
    logger.info(f"Request smtp_from: {request.smtp_from}")

    # Use settings from request body if provided, otherwise from DB/env
    if request.smtp_host and request.smtp_user and request.smtp_password:
        smtp_cfg = {
            "host": request.smtp_host,
            "port": int(request.smtp_port) if request.smtp_port else 587,
            "user": request.smtp_user,
            "password": request.smtp_password,
            "from": request.smtp_from or request.smtp_user,
        }
        logger.info("Using settings from REQUEST body")
    else:
        smtp_cfg = get_smtp_settings(db)
        logger.info("Using settings from DB/ENV fallback")

    logger.info(f"Final smtp_cfg: host={smtp_cfg['host'] if smtp_cfg else None}, port={smtp_cfg['port'] if smtp_cfg else None}")

    result = {
        "configured": bool(smtp_cfg),
        "host": smtp_cfg["host"] if smtp_cfg else "(not set)",
        "port": smtp_cfg["port"] if smtp_cfg else 587,
        "user": smtp_cfg["user"] if smtp_cfg else "(not set)",
        "from": smtp_cfg["from"] if smtp_cfg else "(not set)",
        "password_set": bool(smtp_cfg and smtp_cfg.get("password")),
    }
    if not result["configured"]:
        result["error"] = "SMTP не настроен. Заполните настройки в мастере."
        logger.warning("SMTP not configured")
        return result

    try:
        _test_smtp_connection(smtp_cfg)
        result["auth_success"] = True
        result["message"] = "SMTP аутентификация прошла успешно!"
        logger.info("SMTP auth SUCCESS")
    except smtplib.SMTPAuthenticationError as e:
        result["auth_success"] = False
        result["error"] = f"Ошибка аутентификации. Проверьте пароль приложения. ({e.smtp_code})"
        logger.error(f"SMTP auth FAILED: SMTPAuthenticationError {e.smtp_code}")
        logger.error(f"Exception: {e}")
    except smtplib.SMTPConnectError as e:
        result["auth_success"] = False
        result["error"] = f"Ошибка подключения к SMTP серверу. Проверьте хост и порт."
        logger.error(f"SMTP connect FAILED: {e}")
    except Exception as e:
        result["auth_success"] = False
        result["error"] = f"Ошибка подключения: {str(e)}"
        logger.error(f"SMTP unexpected error: {e}")
        logger.error(traceback.format_exc())

    logger.info("=" * 50)
    return result

# ========== EMAIL SEND ==========
@app.post("/email/send", response_model=schemas.EmailSendResponse)
def send_email(request: schemas.EmailSendRequest, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    template = db.query(models.Template).filter(
        (models.Template.id == request.template_id) &
        ((models.Template.owner_id == current_user.id) | (models.Template.status == models.TemplateStatus.PUBLISHED))
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found or access denied")

    rendered_html = _render_template_html(template.html_content, {
        "greeting": request.greeting or "",
        "recipient_email": request.recipient_email,
        "sender_email": request.sender_email,
        "full_name": current_user.full_name or "",
        "position": current_user.position or "",
        "company": current_user.company or "",
        "phone": current_user.phone or "",
        "address": current_user.address or "",
        "website": _normalize_website(current_user.website or ""),
    })
    # Ссылки на загруженные картинки (background/image-блоки) указывают на
    # http://localhost:8000/... - это адрес ТОЛЬКО компьютера отправителя.
    # Получатель письма открывает его на своём устройстве и не сможет
    # достучаться до чужого localhost - картинки были бы у него битыми.
    # Встраиваем их прямо в письмо как data:-URI перед отправкой.
    rendered_html = _inline_local_images(rendered_html)

    # ВАЖНО: если SMTP не настроен вообще, дальше отправлять некуда - раньше в этом
    # случае функция молча "успешно завершалась", не отправив письмо, но всё равно
    # сохраняла лог и возвращала пользователю "Email sent successfully". Теперь мы
    # сразу и явно сообщаем об ошибке, ничего не сохраняя в лог как отправленное.
    smtp_cfg = get_smtp_settings(db)
    if not smtp_cfg:
        raise HTTPException(
            status_code=400,
            detail="SMTP не настроен. Откройте раздел «Настройки» и укажите почтовый сервер, прежде чем отправлять письма."
        )

    # Отправитель в заголовке письма и в SMTP-конверте берём ТОЛЬКО из настроек
    # (smtp_from) - почтовые серверы (Яндекс, Mail.ru, Gmail) часто отклоняют
    # письма, чей адрес From не совпадает с аутентифицированным ящиком.
    # Поле sender_email из формы остаётся только для подписи письма
    # (плейсхолдер {{ sender_email }} в теле письма).
    from_addr = smtp_cfg.get("from") or request.sender_email or (current_user.sender_email or current_user.email)

    # Запоминаем адрес отправителя в истории ДО попытки отправки: он должен
    # оказаться в подсказках формы, даже если SMTP отклонит письмо (человек этот
    # адрес реально использует). Все валидационные отказы (шаблон не найден,
    # SMTP не настроен, слишком большие картинки) уже позади - они в историю
    # ничего не пишут. Изменение сохранится существующим db.commit() ниже -
    # отдельный commit на адрес здесь не нужен.
    _remember_sender_address(db, current_user, request.sender_email)

    # Сохраняем или обновляем контакт
    contact = db.query(models.Contact).filter(
        models.Contact.email == request.recipient_email,
        models.Contact.owner_id == current_user.id
    ).first()
    if contact:
        contact.greeting = request.greeting
    else:
        contact = models.Contact(
            email=request.recipient_email,
            greeting=request.greeting,
            owner_id=current_user.id
        )
        db.add(contact)

    # Отправляем письмо через SMTP
    smtp_error = None
    try:
        # 'mixed' - потому что теперь возможны настоящие вложения (PDF), а не
        # только альтернативные представления одного и того же содержимого.
        msg = MIMEMultipart('mixed')
        msg['Subject'] = template.title
        msg['From'] = from_addr
        msg['To'] = request.recipient_email

        body = MIMEMultipart('alternative')
        body.attach(MIMEText(rendered_html, 'html', 'utf-8'))
        msg.attach(body)

        if template.attach_pdf:
            try:
                pdf_bytes = _html_to_pdf_bytes(_strip_pdf_excluded(rendered_html))
                if pdf_bytes:
                    pdf_part = MIMEApplication(pdf_bytes, _subtype='pdf')
                    safe_name = re.sub(r'[^\w\-. ]', '_', template.title) or 'letter'
                    pdf_part.add_header('Content-Disposition', 'attachment', filename=f"{safe_name}.pdf")
                    msg.attach(pdf_part)
            except Exception as pdf_err:
                # PDF - необязательный бонус к письму. Если он почему-то не
                # собрался, получатель всё равно должен получить само письмо,
                # а не остаться совсем без него из-за второстепенной функции.
                logger.error(f"Не удалось сформировать PDF-вложение: {pdf_err}")

        _send_via_smtp(smtp_cfg, from_addr, request.recipient_email, msg.as_string())
    except smtplib.SMTPAuthenticationError as e:
        smtp_error = f"Ошибка аутентификации SMTP. Проверьте пароль приложения. ({e.smtp_code})"
    except smtplib.SMTPConnectError as e:
        smtp_error = f"Ошибка подключения к SMTP серверу {smtp_cfg['host']}:{smtp_cfg['port']}. Проверьте настройки."
    except Exception as e:
        smtp_error = f"Ошибка отправки: {str(e)}"

    # Сохраняем лог - статус явно отражает, действительно ли письмо ушло.
    log = models.EmailLog(
        sender_id=current_user.id,
        sender_email=from_addr,
        recipient_email=request.recipient_email,
        greeting=request.greeting,
        template_id=template.id,
        template_title=template.title,
        # Компактный снимок (без base64) - полный HTML с data:-картинками не
        # храним, чтобы база не разрасталась на гигабайты.
        html_content=_compact_email_snapshot(rendered_html),
        status="not_sent" if smtp_error else "sent"
    )
    db.add(log)
    if not smtp_error:
        # 2.7.0: одиночная отправка тоже расходует дневной лимит почтового ящика
        # (у Яндекса он общий - 300 писем/сутки, независимо от того, массовая
        # это рассылка или обычное письмо). Счётчик увеличивается только при
        # реально ушедшем письме, в той же транзакции, что и лог.
        campaign_worker.increment_quota(db)
    db.commit()

    if smtp_error:
        raise HTTPException(status_code=500, detail=smtp_error)

    return schemas.EmailSendResponse(
        message="Письмо успешно отправлено",
        recipient_email=request.recipient_email,
        html_preview=rendered_html
    )

# ========== FILE UPLOADS ==========
@app.post("/upload")
def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    import uuid
    safe_name = (file.filename or "").replace("\\", "/").split("/")[-1]
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Расширение «{ext or 'без расширения'}» не разрешено. "
                   "Можно загружать изображения и офисные документы (png/jpg/pdf/doc/xls/txt/zip и т.п.)."
        )
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)
    total = 0
    # Читаем чанками и проверяем размер по мере записи, чтобы не держать файл в памяти.
    with open(file_path, "wb") as f:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                try:
                    f.close()
                    os.remove(file_path)
                except OSError:
                    pass
                raise HTTPException(status_code=413, detail="Файл слишком большой (лимит 20 МБ).")
            f.write(chunk)

    db_file = models.UploadedFile(
        filename=unique_name,
        original_name=safe_name,
        content_type=file.content_type,
        file_path=file_path,
        owner_id=current_user.id
    )
    db.add(db_file)
    db.commit()
    db.refresh(db_file)
    return {
        "id": db_file.id,
        "url": f"/uploads/{unique_name}",
        "original_name": safe_name,
        "content_type": file.content_type
    }

@app.get("/uploads/{filename}")
def serve_file(filename: str):
    # Защита от path traversal: только простое имя файла, итоговый путь обязан
    # лежать внутри папки загрузок (иначе через ../ можно было бы прочитать
    # secret.key, app.db и исходники бэкенда).
    if not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.\-]*", filename or ""):
        raise HTTPException(status_code=400, detail="Некорректное имя файла")
    file_path = os.path.join(UPLOAD_DIR, os.path.basename(filename))
    real_upload = os.path.realpath(UPLOAD_DIR)
    real_file = os.path.realpath(file_path)
    if real_file != real_upload and not real_file.startswith(real_upload + os.sep):
        raise HTTPException(status_code=400, detail="Доступ запрещён")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)

@app.delete("/files/{file_id}")
def delete_file(file_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    """Удаление загруженного файла (только своего). Убирает файл с диска и запись из БД."""
    up = db.query(models.UploadedFile).filter(
        models.UploadedFile.id == file_id,
        models.UploadedFile.owner_id == current_user.id
    ).first()
    if not up:
        raise HTTPException(status_code=404, detail="File not found")
    try:
        if up.file_path and os.path.exists(up.file_path):
            os.remove(up.file_path)
    except OSError:
        pass
    db.delete(up)
    db.commit()
    return {"ok": True, "id": file_id}

@app.get("/my-files")
def list_files(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    files = db.query(models.UploadedFile).filter(models.UploadedFile.owner_id == current_user.id).all()
    return [
        {
            "id": f.id,
            "url": f"/uploads/{f.filename}",
            "original_name": f.original_name,
            "content_type": f.content_type,
            "created_at": f.created_at.isoformat()
        }
        for f in files
    ]


def _app_settings_response(settings: models.AppSettings):
    """Единый ответ по настройкам (2.7.0: добавлены поля массовой рассылки).

    response_model сам уберёт пароль SMTP (его нет в схеме ответа), а
    smtp_password_set нужно посчитать явно - в модели БД такого поля нет.
    """
    return schemas.AppSettingsResponse(
        id=settings.id,
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_user=settings.smtp_user,
        smtp_from=settings.smtp_from,
        smtp_password_set=bool(settings.smtp_password),
        mass_mailing_enabled=bool(settings.mass_mailing_enabled),
        mass_mailing_daily_limit=int(settings.mass_mailing_daily_limit or 250),
        updated_at=settings.updated_at,
    )


def _ensure_settings(db: Session) -> models.AppSettings:
    settings = db.query(models.AppSettings).first()
    if not settings:
        settings = models.AppSettings(id=1)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


@app.get("/settings", response_model=schemas.AppSettingsResponse)
def get_settings(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_admin)):
    return _app_settings_response(_ensure_settings(db))

@app.post("/settings", response_model=schemas.AppSettingsResponse)
def save_settings(request: schemas.AppSettingsCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_admin)):
    settings = _ensure_settings(db)
    settings.smtp_host = request.smtp_host
    settings.smtp_port = int(request.smtp_port) if request.smtp_port else 587
    settings.smtp_user = request.smtp_user
    # Пустой/не переданный пароль означает "оставить как есть" - иначе при каждом
    # сохранении настроек (например, просто поменяли хост) пришлось бы заново
    # вводить пароль, а если забыть - он бы затёрся пустым значением и SMTP
    # перестал бы работать без явной причины.
    if request.smtp_password:
        settings.smtp_password = request.smtp_password
    settings.smtp_from = request.smtp_from or request.smtp_user
    # 2.7.0: необязательные поля массовой рассылки - старые клиенты их не
    # присылают, и тогда текущие значения не меняются.
    if request.mass_mailing_enabled is not None:
        settings.mass_mailing_enabled = bool(request.mass_mailing_enabled)
    if request.mass_mailing_daily_limit is not None:
        settings.mass_mailing_daily_limit = int(request.mass_mailing_daily_limit)
    db.commit()
    db.refresh(settings)
    return _app_settings_response(settings)


@app.put("/settings", response_model=schemas.AppSettingsResponse)
def update_settings(request: schemas.AppSettingsUpdate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_admin)):
    """Частичное обновление настроек (2.7.0).

    Добавлено для страницы настроек: блок «Массовая рассылка» может менять
    только свои поля (переключатель доступа и дневной лимит), не перезаписывая
    SMTP-настройки. Существующий POST /settings работает как раньше.
    """
    settings = _ensure_settings(db)
    data = request.model_dump(exclude_unset=True)
    if "smtp_host" in data:
        settings.smtp_host = data["smtp_host"]
    if "smtp_port" in data:
        settings.smtp_port = int(data["smtp_port"]) if data["smtp_port"] else 587
    if "smtp_user" in data:
        settings.smtp_user = data["smtp_user"]
    # Пустой пароль = «не менять» (как и в POST /settings).
    if data.get("smtp_password"):
        settings.smtp_password = data["smtp_password"]
    if "smtp_from" in data:
        settings.smtp_from = data["smtp_from"] or settings.smtp_user
    if "mass_mailing_enabled" in data:
        settings.mass_mailing_enabled = bool(data["mass_mailing_enabled"])
    if "mass_mailing_daily_limit" in data:
        settings.mass_mailing_daily_limit = int(data["mass_mailing_daily_limit"])
    db.commit()
    db.refresh(settings)
    return _app_settings_response(settings)

# ========== ANALYTICS ==========
@app.get("/analytics", response_model=schemas.AnalyticsResponse)
def get_analytics(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_admin)):
    logs = db.query(models.EmailLog).order_by(models.EmailLog.sent_at.desc()).all()
    # В логе есть и неудачные попытки (status="not_sent"): показываем их в
    # таблице, но счётчик «Всего отправлено» должен считать только реально
    # ушедшие письма, иначе цифра в аналитике вводит в заблуждение.
    sent_count = sum(1 for log in logs if (log.status or "sent") == "sent")
    return schemas.AnalyticsResponse(
        total_sent=sent_count,
        logs=[
            schemas.EmailLogResponse(
                id=log.id,
                sender_email=log.sender_email,
                recipient_email=log.recipient_email,
                greeting=log.greeting,
                # Берём сохранённый на момент отправки снимок названия - шаблон мог
                # быть удалён или переименован позже, но история должна остаться верной.
                template_title=log.template_title or (log.template.title if log.template else "(шаблон удалён)"),
                status=log.status or "sent",
                sent_at=log.sent_at
            )
            for log in logs
        ]
    )

# ========== ADMIN: ACCOUNTS OVERVIEW ==========
@app.get("/admin/accounts", response_model=schemas.AdminAccountsResponse)
def get_admin_accounts(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_admin)):
    """Единый обзор для администратора: все пользователи, их шаблоны и статистика
    отправок - чтобы видеть, кто сколько и кому отправил писем, какими шаблонами
    пользуется, и иметь возможность сделать чужой шаблон общедоступным."""
    users = db.query(models.User).order_by(models.User.created_at.asc()).all()
    accounts = []
    for user in users:
        templates = db.query(models.Template).filter(
            models.Template.owner_id == user.id
        ).order_by(models.Template.created_at.desc()).all()

        logs = db.query(models.EmailLog).filter(
            models.EmailLog.sender_id == user.id
        ).order_by(models.EmailLog.sent_at.desc()).all()

        # emails_sent_count в интерфейсе подписан как «писем отправлено» -
        # неудачные попытки (not_sent) в него не включаем.
        sent_count = sum(1 for log in logs if (log.status or "sent") == "sent")

        accounts.append(schemas.AdminAccountInfo(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            created_at=user.created_at,
            templates=[
                schemas.AdminTemplateInfo(
                    id=t.id, title=t.title, status=t.status, created_at=t.created_at
                ) for t in templates
            ],
            emails_sent_count=sent_count,
            # Полную историю отдавать ни к чему - 20 последних вполне достаточно
            # для обзора, чтобы не раздувать ответ на каждого пользователя.
            recent_logs=[
                schemas.EmailLogResponse(
                    id=log.id,
                    sender_email=log.sender_email,
                    recipient_email=log.recipient_email,
                    greeting=log.greeting,
                    template_title=log.template_title or (log.template.title if log.template else "(шаблон удалён)"),
                    status=log.status or "sent",
                    sent_at=log.sent_at
                ) for log in logs[:20]
            ]
        ))
    return schemas.AdminAccountsResponse(accounts=accounts)

if __name__ == "__main__":
    import uvicorn
    # Только локальный интерфейс: API и /uploads не должны быть доступны в сети.
    uvicorn.run(root_app, host="127.0.0.1", port=8000)
