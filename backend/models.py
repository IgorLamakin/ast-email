from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship
from database import Base
import datetime
import enum

class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"

class TemplateStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    sender_email = Column(String, nullable=True)
    role = Column(Enum(UserRole), default=UserRole.USER, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    position = Column(String, nullable=True)
    company = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    website = Column(String, nullable=True)

    contacts = relationship("Contact", back_populates="owner", cascade="all, delete-orphan")
    templates = relationship("Template", back_populates="owner", cascade="all, delete-orphan")
    email_logs = relationship("EmailLog", back_populates="sender", cascade="all, delete-orphan")
    files = relationship("UploadedFile", back_populates="owner", cascade="all, delete-orphan")
    # Сессия «запомнить вход» (2.6.0). При удалении пользователя его refresh-токены
    # удаляем вместе с ним: иначе в базе оставались бы «висячие» записи, по которым
    # всё равно нельзя войти (пользователя уже нет), но которые надо было бы
    # отдельно подчищать.
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    # История адресов отправителя для автоподстановки в форме отправки письма (2.6.0).
    sender_addresses = relationship("SenderAddress", back_populates="owner", cascade="all, delete-orphan")

class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, nullable=False)
    greeting = Column(String, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    owner = relationship("User", back_populates="contacts")

class Template(Base):
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    html_content = Column(Text, nullable=False)
    status = Column(Enum(TemplateStatus), default=TemplateStatus.DRAFT, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    owner = relationship("User", back_populates="templates")
    email_logs = relationship("EmailLog", back_populates="template")
    blocks = Column(Text, nullable=True)  # JSON array of blocks
    # Стабильный идентификатор стандартного шаблона ("general", "supplies", ...).
    # Нужен, чтобы auto_seed_templates() находил стандартное письмо даже после
    # переименования/снятия с публикации и не создавал дубликат. У пользовательских
    # шаблонов остаётся NULL.
    seed_key = Column(String, nullable=True, index=True)
    # Если включено - при отправке письма к нему автоматически прикладывается
    # PDF-версия содержимого (без кнопок - см. send_email в main.py).
    attach_pdf = Column(Boolean, default=False)

class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    original_name = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    file_path = Column(String, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    owner = relationship("User", back_populates="files")

class EmailLog(Base):
    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sender_email = Column(String, nullable=False)
    recipient_email = Column(String, nullable=False)
    greeting = Column(String, nullable=True)
    # nullable=True: шаблон можно удалить, даже если по нему уже отправлялись письма -
    # запись в логе не должна из-за этого ломаться (см. template_title ниже).
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=True)
    # Снимок названия шаблона на момент отправки. Раньше название бралось "на лету"
    # через log.template.title - если шаблон потом удаляли или переименовывали,
    # это либо падало с ошибкой (аналитика переставала открываться целиком),
    # либо показывало неверное название. Теперь название сохраняется один раз,
    # в момент отправки, и не зависит от текущего состояния шаблона.
    template_title = Column(String, nullable=True)
    html_content = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="sent")  # "sent" | "not_sent" (SMTP не настроен)
    sent_at = Column(DateTime, default=datetime.datetime.utcnow)

    sender = relationship("User", back_populates="email_logs")
    template = relationship("Template", back_populates="email_logs")

class AppSettings(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, index=True)
    smtp_host = Column(String, nullable=True)
    smtp_port = Column(Integer, default=587)
    smtp_user = Column(String, nullable=True)
    smtp_password = Column(String, nullable=True)
    smtp_from = Column(String, nullable=True)
    # Версия стандартных шаблонов, с которой они были синхронизированы в БД
    # (см. TEMPLATE_SEED_VERSION и auto_seed_templates в main.py).
    seed_template_version = Column(String, nullable=True)
    # Отдельная версия шаблона «Презентация компании»: нужна, чтобы один раз
    # обновить его HTML в 2.5.4 (контакты/CTA/кнопки скачивания), не трогая
    # остальные стандартные шаблоны и не затирая их правки при каждом старте.
    presentation_seed_version = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class RefreshToken(Base):
    """Долгоживущий refresh-токен для функции «запомнить вход» (2.6.0).

    Это НЕ JWT, а случайная строка (secrets.token_urlsafe), которая проверяется
    по базе. В базе лежит только SHA-256-хеш от неё: если файл базы унесут или
    скопируют, по его содержимому нельзя будет войти под пользователем (пароли
    хранятся хешами по той же причине). Токен одноразовый: при обмене на новую
    пару (POST /auth/refresh) старый помечается revoked_at и повторно не работает.

    Не путать с access-токеном: тот по-прежнему JWT и живёт ACCESS_TOKEN_EXPIRE_MINUTES.
    Refresh-токен нужен только для получения новой пары, ничего другого им сделать нельзя.
    """

    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # Хеш, а не сам токен: при утечке базы восстановить исходную строку нельзя.
    # unique - у двух пользователей не может оказаться одинакового токена, а поиск
    # при /auth/refresh идёт именно по этому полю.
    token_hash = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    # Пометка «токен больше не действует» (ротация, logout). Не удаляем строку сразу,
    # чтобы повторная попытка старым токеном однозначно получала 401, а не «не найден».
    revoked_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="refresh_tokens")


class SenderAddress(Base):
    """История адресов отправителя (2.6.0).

    Чтобы в форме отправки можно было предложить недавно использованные адреса.
    Пара (owner_id, email) уникальна: повторная отправка с того же адреса
    увеличивает use_count, а не плодит дубликаты строк в списке подсказок.
    """

    __tablename__ = "sender_addresses"
    __table_args__ = (UniqueConstraint("owner_id", "email"),)

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    use_count = Column(Integer, default=1)
    last_used_at = Column(DateTime, default=datetime.datetime.utcnow)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    owner = relationship("User", back_populates="sender_addresses")
