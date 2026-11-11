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
    # Кампании массовой рассылки (2.7.0). Удаление пользователя не предусмотрено API,
    # но связь с cascade нужна, чтобы не оставлять «висячие» кампании при чистке БД.
    campaigns = relationship("Campaign", back_populates="owner", cascade="all, delete-orphan")

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
    # Массовая рассылка (2.7.0). По умолчанию доступна только администратору;
    # переключатель в настройках разрешает её и обычным сотрудникам. Дневной
    # лимит - «мягкий» порог (жёсткий потолок 300 проверяется в коде), чтобы
    # администратор мог уменьшить расход общего SMTP-ящика.
    mass_mailing_enabled = Column(Boolean, default=False)
    mass_mailing_daily_limit = Column(Integer, default=250)
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

class CampaignStatus(str, enum.Enum):
    """Статусы кампании массовой рассылки.

    draft     - черновик: можно менять шаблон/получателей/настройки;
    running   - воркер отправляет очередь;
    paused    - приостановлена пользователем или из-за лимита/ошибки;
    completed - все получатели обработаны (успешно или окончательно с ошибкой);
    stopped   - остановлена вручную/из-за ошибки аутентификации SMTP.
    """
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"


class RecipientStatus(str, enum.Enum):
    """Статус одного получателя в очереди кампании.

    unknown - отправка была в процессе, когда приложение закрылось. Повторно НЕ
              отправляем: лучше потерять одно письмо, чем отправить дважды.
    """
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    UNKNOWN = "unknown"
    SKIPPED = "skipped"


class Campaign(Base):
    """Кампания массовой рассылки (2.7.0).

    Одна кампания = один шаблон + один список получателей + настройки темпа.
    Письма уходят по одному на адрес (BCC не используется: он ломает
    персонализацию, отписку и является спам-признаком).
    """
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    # Шаблон может быть удалён после создания кампании: отправка тогда невозможна,
    # а снимок названия (template_title) остаётся для истории/отчёта.
    template_id = Column(Integer, ForeignKey("templates.id", ondelete="SET NULL"), nullable=True)
    template_title = Column(String, nullable=True)
    sender_email = Column(String, nullable=False)
    # Обращение по умолчанию: подставляется получателям, у которых в файле не было
    # колонки «обращение». (Небольшое расширение контракта: колонка нужна, чтобы
    # параметр greeting из POST /campaigns не терялся.)
    greeting = Column(String, nullable=True)
    status = Column(Enum(CampaignStatus), default=CampaignStatus.DRAFT, nullable=False, index=True)
    total_count = Column(Integer, default=0)
    sent_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)
    # Темп: careful | safe | fast (см. PACE_CONFIG в campaign_worker.py).
    pace = Column(String, default="safe")
    # Дневной лимит кампании (жёсткий потолок ящика - 300 писем/сутки).
    daily_limit = Column(Integer, default=250)
    # work_hours - отправлять только 09:00-18:00 Пн-Пт; любое другое значение - сразу.
    send_mode = Column(String, default="work_hours")
    attach_pdf = Column(Boolean, default=False)
    consent_confirmed = Column(Boolean, default=False)
    consent_confirmed_at = Column(DateTime, nullable=True)
    test_sent_at = Column(DateTime, nullable=True)
    import_file_path = Column(String, nullable=True)
    last_error = Column(Text, nullable=True)
    # Если кампания поставлена на паузу из-за дневного лимита - до какого момента
    # она ждёт (полночь локального дня).
    pause_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    owner = relationship("User", back_populates="campaigns")
    recipients = relationship(
        "CampaignRecipient", back_populates="campaign", cascade="all, delete-orphan"
    )


class CampaignRecipient(Base):
    """Получатель кампании и его состояние в очереди."""
    __tablename__ = "campaign_recipients"
    __table_args__ = (
        UniqueConstraint("campaign_id", "normalized_email", name="uq_campaign_recipient"),
    )

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(
        Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email = Column(String, nullable=False)
    # Приведённый к нижнему регистру адрес (в т.ч. домен в punycode) - ключ
    # дедупликации внутри кампании и проверки стоп-листа.
    normalized_email = Column(String, nullable=False, index=True)
    greeting = Column(String, nullable=True)
    # JSON-словарь полей персонализации: name/company/position + field_1..field_N
    # (дополнительные колонки файла). Храним строкой JSON, чтобы не тащить
    # отдельные колонки под произвольный набор полей.
    fields = Column(Text, nullable=True)
    status = Column(Enum(RecipientStatus), default=RecipientStatus.PENDING, nullable=False, index=True)
    attempts = Column(Integer, default=0)
    next_attempt_at = Column(DateTime, nullable=True)
    error_code = Column(String, nullable=True)
    error_text = Column(Text, nullable=True)
    message_id = Column(String, nullable=True)
    # True на время сетевой отправки. Если приложение упало в этот момент - при
    # следующем старте строка станет unknown и НЕ будет отправлена повторно.
    in_flight = Column(Boolean, default=False)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    campaign = relationship("Campaign", back_populates="recipients")


class Unsubscribe(Base):
    """Глобальный стоп-лист отписавшихся адресов (2.7.0).

    Адрес, попавший сюда, больше никогда не получает массовых писем.
    source: manual (добавил администратор), mailto (отписка письмом),
    bounce (жёсткий отказ 550 user unknown).
    """
    __tablename__ = "unsubscribes"

    id = Column(Integer, primary_key=True, index=True)
    normalized_email = Column(String, unique=True, nullable=False, index=True)
    email_raw = Column(String, nullable=False)
    reason = Column(String, nullable=True)
    source = Column(String, default="manual")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class SendQuota(Base):
    """Дневной счётчик отправок с одного почтового ящика (2.7.0).

    Ключ - ЛОКАЛЬНАЯ дата "YYYY-MM-DD". Считаем и одиночные отправки
    (POST /email/send), и массовые: у Яндекса лимит общий на ящик (300/сутки),
    а не на кампанию. Часовой пояс берём локальный, потому что «сутки» для
    провайдера - это сутки пользователя, а не UTC.
    """
    __tablename__ = "send_quota"

    day = Column(String, primary_key=True)
    count = Column(Integer, default=0)
