from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
from models import UserRole, TemplateStatus

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
