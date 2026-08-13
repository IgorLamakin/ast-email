from typing import Optional, List
from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from jinja2 import Template as JinjaTemplate
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
        conn.commit()


_migrate_sqlite_schema()

# ========== AUTO-SEED TEMPLATES ==========
def auto_seed_templates():
    """Добавляет 5 стандартных шаблонов, если их ещё нет.

    Важно: проверяем наличие КАЖДОГО шаблона по отдельности (по title), а не только
    общее количество опубликованных шаблонов. Иначе при удалении администратором
    одного из стандартных шаблонов следующий перезапуск бэкенда (а он перезапускается
    при каждом старте десктоп-приложения) заново добавлял бы ВСЕ 5 шаблонов, создавая
    дубликаты уже существующих.
    """
    db = next(database.get_db())
    try:
        existing_titles = {t.title for t in db.query(models.Template).filter(models.Template.status == models.TemplateStatus.PUBLISHED).all()}
        admin = db.query(models.User).filter(models.User.role == models.UserRole.ADMIN).first()
        if not admin:
            return
        import os
        template_dir = os.path.join(os.path.dirname(__file__), "email_templates")
        templates = [
            ("АСТ — Общий обзор компании", "template_1_general.html"),
            ("АСТ — Поставка компонентов КИПиА и АСУТП", "template_2_supplies.html"),
            ("АСТ — Производство и сборка шкафов", "template_3_cabinets.html"),
            ("АСТ — Инжиниринг и разработка ПО", "template_4_engineering.html"),
            ("АСТ — Реализованные проекты", "template_5_cases.html"),
        ]
        added_any = False
        for title, filename in templates:
            if title in existing_titles:
                continue
            filepath = os.path.join(template_dir, filename)
            if not os.path.exists(filepath):
                continue
            with open(filepath, "r", encoding="utf-8") as f:
                html = f.read()
            t = models.Template(
                title=title,
                html_content=html,
                status=models.TemplateStatus.PUBLISHED,
                owner_id=admin.id
            )
            db.add(t)
            added_any = True
        if added_any:
            db.commit()
    finally:
        db.close()

auto_seed_templates()

app = FastAPI(title="Email Template API", version="2.0.0")

# Root app with /api prefix for production compatibility
root_app = FastAPI(title="Email Template API Root", version="2.0.0")
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

    access_token = create_access_token(data={"sub": str(db_user.id)})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/auth/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    access_token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer"}

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
    jinja_template = JinjaTemplate(template.html_content)
    rendered_html = jinja_template.render(
        greeting=request.greeting or "",
        recipient_email=request.recipient_email,
        sender_email=request.sender_email,
        full_name=current_user.full_name or "",
        position=current_user.position or "",
        company=current_user.company or "",
        phone=current_user.phone or "",
        address=current_user.address or "",
        website=current_user.website or ""
    )
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

    jinja_template = JinjaTemplate(template.html_content)
    rendered_html = jinja_template.render(
        greeting=request.greeting or "",
        recipient_email=request.recipient_email,
        sender_email=request.sender_email,
        full_name=current_user.full_name or "",
        position=current_user.position or "",
        company=current_user.company or "",
        phone=current_user.phone or "",
        address=current_user.address or "",
        website=current_user.website or ""
    )
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
        msg['From'] = request.sender_email
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

        _send_via_smtp(smtp_cfg, request.sender_email, request.recipient_email, msg.as_string())
    except smtplib.SMTPAuthenticationError as e:
        smtp_error = f"Ошибка аутентификации SMTP. Проверьте пароль приложения. ({e.smtp_code})"
    except smtplib.SMTPConnectError as e:
        smtp_error = f"Ошибка подключения к SMTP серверу {smtp_cfg['host']}:{smtp_cfg['port']}. Проверьте настройки."
    except Exception as e:
        smtp_error = f"Ошибка отправки: {str(e)}"

    # Сохраняем лог - статус явно отражает, действительно ли письмо ушло.
    log = models.EmailLog(
        sender_id=current_user.id,
        sender_email=request.sender_email,
        recipient_email=request.recipient_email,
        greeting=request.greeting,
        template_id=template.id,
        template_title=template.title,
        html_content=rendered_html,
        status="not_sent" if smtp_error else "sent"
    )
    db.add(log)
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
    ext = os.path.splitext(file.filename)[1]
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)
    with open(file_path, "wb") as f:
        f.write(file.file.read())
    
    db_file = models.UploadedFile(
        filename=unique_name,
        original_name=file.filename,
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
        "original_name": file.filename,
        "content_type": file.content_type
    }

@app.get("/uploads/{filename}")
def serve_file(filename: str):
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)

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


@app.get("/settings", response_model=schemas.AppSettingsResponse)
def get_settings(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_admin)):
    settings = db.query(models.AppSettings).first()
    if not settings:
        settings = models.AppSettings(id=1)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    # response_model сам уберёт поле smtp_password (его больше нет в схеме ответа),
    # а вот smtp_password_set нужно посчитать явно - в модели БД такого поля нет.
    return schemas.AppSettingsResponse(
        id=settings.id,
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_user=settings.smtp_user,
        smtp_from=settings.smtp_from,
        smtp_password_set=bool(settings.smtp_password),
        updated_at=settings.updated_at,
    )

@app.post("/settings", response_model=schemas.AppSettingsResponse)
def save_settings(request: schemas.AppSettingsCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_admin)):
    settings = db.query(models.AppSettings).first()
    if not settings:
        settings = models.AppSettings(id=1)
        db.add(settings)
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
    db.commit()
    db.refresh(settings)
    return schemas.AppSettingsResponse(
        id=settings.id,
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_user=settings.smtp_user,
        smtp_from=settings.smtp_from,
        smtp_password_set=bool(settings.smtp_password),
        updated_at=settings.updated_at,
    )

# ========== ANALYTICS ==========
@app.get("/analytics", response_model=schemas.AnalyticsResponse)
def get_analytics(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_admin)):
    logs = db.query(models.EmailLog).order_by(models.EmailLog.sent_at.desc()).all()
    return schemas.AnalyticsResponse(
        total_sent=len(logs),
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
            emails_sent_count=len(logs),
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
    uvicorn.run(root_app, host="0.0.0.0", port=8000)
