from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum, Boolean
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
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
