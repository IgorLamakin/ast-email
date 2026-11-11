from pydantic import BaseModel, EmailStr, Field
from typing import Any, Dict, Optional, List
from datetime import datetime
from models import UserRole, TemplateStatus, CampaignStatus, RecipientStatus

# ========== USER ==========
class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    sender_email: Optional[str] = None
    position: Optional[str] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    sender_email: Optional[str] = None
    position: Optional[str] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    # Менять роль может только администратор (проверяется в эндпоинте) и не себе самому.
    role: Optional[UserRole] = None

class UserResponse(UserBase):
    id: int
    role: UserRole
    created_at: datetime

    class Config:
        from_attributes = True

class Token(BaseModel):
    """Пара токенов, которую отдают /auth/register и /auth/login.

    refresh_token/expires_in необязательные (Optional) - обратная совместимость:
    старые клиенты и тесты читают только access_token, а если фронтенд ещё не
    обновился, лишние поля в JSON ему не мешают.
    """
    access_token: str
    token_type: str
    refresh_token: Optional[str] = None
    expires_in: Optional[int] = None

class RefreshRequest(BaseModel):
    """Тело POST /auth/refresh и POST /auth/logout - «сырой» refresh-токен.

    Передаётся в теле, а не в заголовке Authorization: access-токен может быть
    уже просрочен (именно за новой парой и приходят), поэтому Bearer-зависимость
    здесь не нужна и только мешала бы.
    """
    refresh_token: str

# ========== CONTACT ==========
class ContactBase(BaseModel):
    email: EmailStr
    greeting: Optional[str] = None

class ContactCreate(ContactBase):
    pass

class ContactResponse(ContactBase):
    id: int
    owner_id: int
    created_at: datetime

    class Config:
        from_attributes = True

# ========== SENDER ADDRESS (история адресов отправителя) ==========
class SenderAddressCreate(BaseModel):
    email: EmailStr

class SenderAddressResponse(BaseModel):
    id: int
    email: str
    use_count: int
    last_used_at: datetime

    class Config:
        from_attributes = True

# ========== TEMPLATE ==========
class TemplateBase(BaseModel):
    title: str
    html_content: str
    blocks: Optional[str] = None
    attach_pdf: Optional[bool] = False

class TemplateCreate(TemplateBase):
    pass

class TemplateUpdate(BaseModel):
    title: Optional[str] = None
    html_content: Optional[str] = None
    blocks: Optional[str] = None
    attach_pdf: Optional[bool] = None

class TemplateResponse(TemplateBase):
    id: int
    status: TemplateStatus
    owner_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class TemplatePublish(BaseModel):
    status: TemplateStatus = TemplateStatus.PUBLISHED

# ========== UPLOADED FILE ==========
class UploadedFileResponse(BaseModel):
    id: int
    url: str
    original_name: str
    content_type: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True

# ========== EMAIL SEND ==========
class EmailSendRequest(BaseModel):
    sender_email: EmailStr
    recipient_email: EmailStr
    greeting: Optional[str] = None
    template_id: int

class EmailSendResponse(BaseModel):
    message: str
    recipient_email: str
    html_preview: str

# ========== EMAIL LOG / ANALYTICS ==========
class EmailLogResponse(BaseModel):
    id: int
    sender_email: str
    recipient_email: str
    greeting: Optional[str]
    template_title: Optional[str] = None
    status: str = "sent"
    sent_at: datetime

    class Config:
        from_attributes = True

class AnalyticsResponse(BaseModel):
    total_sent: int
    logs: List[EmailLogResponse]

# ========== APP SETTINGS ==========
class AppSettingsCreate(BaseModel):
    smtp_host: str
    smtp_port: int = 587
    smtp_user: str
    # Пусто/не передано = "не менять пароль" (см. save_settings в main.py) - так
    # страница настроек может показывать поле пароля пустым/замаскированным, не
    # обязывая администратора вводить его заново при каждом сохранении.
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    # Массовая рассылка (2.7.0). Необязательные: старые клиенты их не присылают -
    # тогда существующие значения не меняются (см. save_settings).
    mass_mailing_enabled: Optional[bool] = None
    mass_mailing_daily_limit: Optional[int] = Field(None, ge=1, le=300)


class AppSettingsUpdate(BaseModel):
    """Частичное обновление настроек (PUT /settings, 2.7.0).

    Все поля необязательны: страница настроек может менять только блок массовой
    рассылки, не перезаписывая SMTP-настройки, и наоборот.
    """
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    mass_mailing_enabled: Optional[bool] = None
    mass_mailing_daily_limit: Optional[int] = Field(None, ge=1, le=300)

class AppSettingsResponse(BaseModel):
    id: int
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_from: Optional[str] = None
    # Реальный пароль сюда никогда не попадает (см. get_settings в main.py) -
    # только признак того, что он вообще задан, чтобы фронтенд мог показать
    # "пароль сохранён" вместо пустого поля, не раскрывая сам пароль по сети.
    smtp_password_set: bool = False
    # Массовая рассылка (2.7.0)
    mass_mailing_enabled: bool = False
    mass_mailing_daily_limit: int = 250
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# ========== ADMIN: ACCOUNTS OVERVIEW ==========
class AdminTemplateInfo(BaseModel):
    id: int
    title: str
    status: TemplateStatus
    created_at: datetime

    class Config:
        from_attributes = True

class AdminAccountInfo(BaseModel):
    id: int
    email: str
    full_name: Optional[str] = None
    role: UserRole
    created_at: datetime
    templates: List[AdminTemplateInfo] = []
    emails_sent_count: int = 0
    recent_logs: List[EmailLogResponse] = []

class AdminAccountsResponse(BaseModel):
    accounts: List[AdminAccountInfo]

# ========== MASS MAILING / КАМПАНИИ (2.7.0) ==========
class CampaignCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    template_id: Optional[int] = None
    sender_email: EmailStr
    # Обращение по умолчанию для получателей, у которых в файле не было колонки
    # «обращение» (см. Campaign.greeting).
    greeting: Optional[str] = None


class CampaignUpdate(BaseModel):
    """Изменение черновика кампании (PUT /campaigns/{id}, только draft).

    Вместе с основными полями принимает настройки отправки (шаг 4 мастера):
    фронтенд сохраняет их тем же запросом перед запуском.
    """
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    template_id: Optional[int] = None
    sender_email: Optional[EmailStr] = None
    greeting: Optional[str] = None
    pace: Optional[str] = None
    daily_limit: Optional[int] = Field(None, ge=1, le=300)
    send_mode: Optional[str] = None
    attach_pdf: Optional[bool] = None


class CampaignSettingsUpdate(BaseModel):
    pace: Optional[str] = None
    daily_limit: Optional[int] = Field(None, ge=1, le=300)
    send_mode: Optional[str] = None
    attach_pdf: Optional[bool] = None


class CampaignSettingsInfo(BaseModel):
    pace: str
    daily_limit: int
    send_mode: str
    attach_pdf: bool


class CampaignResponse(BaseModel):
    id: int
    owner_id: int
    title: str
    template_id: Optional[int] = None
    template_title: Optional[str] = None
    sender_email: str
    greeting: Optional[str] = None
    status: CampaignStatus
    total_count: int = 0
    sent_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    # Синонимы счётчиков: список кампаний по контракту отдаёт total_count/...,
    # а карточка кампании упоминает ещё и total/sent/failed/skipped. Отдаём оба
    # варианта, чтобы не заставлять фронтенд угадывать.
    total: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    pace: str = "safe"
    daily_limit: int = 250
    send_mode: str = "work_hours"
    attach_pdf: bool = False
    consent_confirmed: bool = False
    consent_confirmed_at: Optional[datetime] = None
    test_sent_at: Optional[datetime] = None
    import_file_path: Optional[str] = None
    last_error: Optional[str] = None
    pause_until: Optional[datetime] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Дублирование настроек отдельным объектом (settings) - контракт фронтенда
    # читает campaign.settings.pace и т.п.
    settings: CampaignSettingsInfo
    can_start: bool = False


class RecipientResponse(BaseModel):
    id: int
    campaign_id: int
    email: str
    normalized_email: str
    greeting: Optional[str] = None
    # JSON-строка (как хранится в БД). Фронтенду для таблицы отправок не нужна.
    fields: Optional[str] = None
    status: RecipientStatus
    attempts: int = 0
    next_attempt_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_text: Optional[str] = None
    message_id: Optional[str] = None
    sent_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class RecipientCreate(BaseModel):
    email: EmailStr
    greeting: Optional[str] = None
    # Свободные поля персонализации: {"name": ..., "company": ..., "field_1": ...}
    fields: Optional[Dict[str, Any]] = None


class ImportMapping(BaseModel):
    email: Optional[str] = None
    greeting: Optional[str] = None
    name: Optional[str] = None
    company: Optional[str] = None
    position: Optional[str] = None
    extra: List[str] = []


class ImportCounts(BaseModel):
    total: int = 0
    valid: int = 0
    duplicates: int = 0
    invalid: int = 0
    unsubscribed: int = 0


class ImportResponse(BaseModel):
    columns: List[str] = []
    mapping: ImportMapping
    counts: ImportCounts
    # До 20 строк: {row, email, greeting, company, status: ok|duplicate|invalid|unsubscribed}
    preview: List[Dict[str, Any]] = []


class CampaignStartRequest(BaseModel):
    """Тело POST /campaigns/{id}/start: юридическое подтверждение согласия."""
    consent: bool = False


class PreflightCheck(BaseModel):
    id: str
    level: str  # ok | warn | fail
    title: str
    detail: str = ""


class PreflightResponse(BaseModel):
    checks: List[PreflightCheck] = []
    can_start: bool = False
    remaining_today: int = 0
    total_to_send: int = 0


class UnsubscribeCreate(BaseModel):
    email: EmailStr
    reason: Optional[str] = None


class UnsubscribeResponse(BaseModel):
    id: int
    normalized_email: str
    email_raw: str
    reason: Optional[str] = None
    source: str = "manual"
    created_at: datetime

    class Config:
        from_attributes = True


class CapabilitiesResponse(BaseModel):
    allowed: bool
    daily_limit: int
    remaining_today: int
    is_admin: bool


class EmailQuotaResponse(BaseModel):
    used_today: int
    limit: int
    remaining: int


class TestSendResponse(BaseModel):
    message: str
    to: str


class CampaignReportResponse(BaseModel):
    campaign: CampaignResponse
    counts: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    errors: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    remaining_today: int = 0
