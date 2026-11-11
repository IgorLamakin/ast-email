# -*- coding: utf-8 -*-
"""REST API массовой рассылки (2.7.0).

Подключается в main.py через app.include_router(campaigns.router), поэтому все
пути доступны под /api (root_app монтирует app по этому префиксу).

Права:
- администратор может всё и видит все кампании;
- обычный пользователь - только если администратор включил массовые рассылки
  в настройках (AppSettings.mass_mailing_enabled) и только свои кампании.

Про циклические импорты: модуль НЕ импортирует main на уровне модуля. Хелперы
main (_render_template_html, get_smtp_settings, UPLOAD_DIR и т.п.) берутся
локально внутри функций. Зависимости авторизации - тонкие обёртки, которые
вызывают main.get_current_user уже во время запроса.
"""
import csv
import datetime
import io
import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import func
from sqlalchemy.orm import Session

import campaign_worker
import importer
import mail_text
import models
import schemas
from database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# Подпапка в UPLOAD_DIR, где лежат загруженные файлы получателей.
CAMPAIGN_IMPORT_SUBDIR = "campaign_imports"
MAX_LIST_LIMIT = 500

# Слова-триггеры для предупреждения в preflight (не блокируют запуск, но
# администратору полезно знать, что письмо выглядит рекламно).
TRIGGER_WORDS = (
    "бесплатно", "акция", "скидка", "распродажа", "только сегодня", "срочно",
    "гарантия", "кредит", "займ", "выигрыш", "приз", "доход", "заработок",
    "инвестиции", "без предоплаты", "100%", "дешево", "уникальное предложение",
    "коммерческое предложение", "купить", "заказать", "успейте",
    "ограниченное предложение",
)


# ========== ЗАВИСИМОСТИ АВТОРИЗАЦИИ ==========
def get_current_user(token: str = Depends(_oauth2_scheme), db: Session = Depends(get_db)):
    """Та же проверка, что main.get_current_user (JWT + пользователь в БД)."""
    import main
    return main.get_current_user(token=token, db=db)


def get_current_admin(user: models.User = Depends(get_current_user)):
    if user.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ========== ОБЩИЕ ХЕЛПЕРЫ ==========
def _now():
    return datetime.datetime.utcnow()


def _get_settings(db: Session):
    return db.query(models.AppSettings).order_by(models.AppSettings.id).first()


def _is_admin(user) -> bool:
    return getattr(user, "role", None) == models.UserRole.ADMIN


def _mass_mailing_allowed(db: Session, user) -> bool:
    if _is_admin(user):
        return True
    settings = _get_settings(db)
    return bool(settings is not None and settings.mass_mailing_enabled)


def _require_mass_mailing(db: Session, user) -> None:
    if not _mass_mailing_allowed(db, user):
        raise HTTPException(
            status_code=403,
            detail="Массовые рассылки недоступны. Попросите администратора включить их в настройках.",
        )


def _get_campaign(db: Session, campaign_id: int, user) -> models.Campaign:
    """Кампания, доступная пользователю: своя или любая для администратора."""
    campaign = db.query(models.Campaign).filter(models.Campaign.id == campaign_id).first()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Кампания не найдена")
    if campaign.owner_id != user.id and not _is_admin(user):
        # Не раскрываем существование чужой кампании.
        raise HTTPException(status_code=404, detail="Кампания не найдена")
    return campaign


def _require_draft(campaign: models.Campaign) -> None:
    if campaign.status != models.CampaignStatus.DRAFT:
        raise HTTPException(
            status_code=400,
            detail="Изменять можно только черновик рассылки. Поставьте кампанию на паузу/остановите её.",
        )


def _get_accessible_template(db: Session, template_id: int, user) -> models.Template:
    template = db.query(models.Template).filter(
        (models.Template.id == template_id)
        & (
            (models.Template.owner_id == user.id)
            | (models.Template.status == models.TemplateStatus.PUBLISHED)
        )
    ).first()
    if template is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    return template


def _campaign_payload(campaign: models.Campaign) -> dict:
    """Словарь для CampaignResponse: плоские поля + settings + синонимы счётчиков."""
    total = int(campaign.total_count or 0)
    sent = int(campaign.sent_count or 0)
    failed = int(campaign.failed_count or 0)
    skipped = int(campaign.skipped_count or 0)
    pace = campaign.pace or campaign_worker.DEFAULT_PACE
    daily_limit = int(campaign.daily_limit or 250)
    send_mode = campaign.send_mode or "work_hours"
    return {
        "id": campaign.id,
        "owner_id": campaign.owner_id,
        "title": campaign.title,
        "template_id": campaign.template_id,
        "template_title": campaign.template_title,
        "sender_email": campaign.sender_email,
        "greeting": campaign.greeting,
        "status": campaign.status,
        "total_count": total,
        "sent_count": sent,
        "failed_count": failed,
        "skipped_count": skipped,
        "total": total,
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
        "pace": pace,
        "daily_limit": daily_limit,
        "send_mode": send_mode,
        "attach_pdf": bool(campaign.attach_pdf),
        "consent_confirmed": bool(campaign.consent_confirmed),
        "consent_confirmed_at": campaign.consent_confirmed_at,
        "test_sent_at": campaign.test_sent_at,
        "import_file_path": campaign.import_file_path,
        "last_error": campaign.last_error,
        "pause_until": campaign.pause_until,
        "created_at": campaign.created_at,
        "started_at": campaign.started_at,
        "finished_at": campaign.finished_at,
        "updated_at": campaign.updated_at,
        "settings": {
            "pace": pace,
            "daily_limit": daily_limit,
            "send_mode": send_mode,
            "attach_pdf": bool(campaign.attach_pdf),
        },
        "can_start": campaign.status in (
            models.CampaignStatus.DRAFT,
            models.CampaignStatus.PAUSED,
        ),
    }


def _recipients_count(db: Session, campaign_id: int, status=None) -> int:
    query = db.query(func.count(models.CampaignRecipient.id)).filter(
        models.CampaignRecipient.campaign_id == campaign_id
    )
    if status is not None:
        query = query.filter(models.CampaignRecipient.status == status)
    return int(query.scalar() or 0)


def _list_limit(value: int, default: int = 100, maximum: int = MAX_LIST_LIMIT) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


# ========== ВОЗМОЖНОСТИ И СПИСОК КАМПАНИЙ ==========
# ВАЖНО: /campaigns/capabilities объявлен ДО /campaigns/{campaign_id}, иначе
# FastAPI попытается преобразовать строку "capabilities" в int и вернёт 422.
@router.get("/campaigns/capabilities", response_model=schemas.CapabilitiesResponse)
def get_capabilities(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    is_admin = _is_admin(current_user)
    return {
        "allowed": _mass_mailing_allowed(db, current_user),
        "daily_limit": campaign_worker.global_daily_limit(db),
        "remaining_today": campaign_worker.remaining_today(db),
        "is_admin": is_admin,
    }


@router.get("/campaigns", response_model=List[schemas.CampaignResponse])
def list_campaigns(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Список кампаний: свои (администратор - все), сначала новые."""
    _require_mass_mailing(db, current_user)
    query = db.query(models.Campaign)
    if not _is_admin(current_user):
        query = query.filter(models.Campaign.owner_id == current_user.id)
    campaigns = query.order_by(
        models.Campaign.created_at.desc(), models.Campaign.id.desc()
    ).offset(max(0, int(offset))).limit(_list_limit(limit, default=50)).all()
    return [_campaign_payload(campaign) for campaign in campaigns]


@router.post("/campaigns", response_model=schemas.CampaignResponse)
def create_campaign(
    payload: schemas.CampaignCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Создать черновик кампании (шаг 1 мастера)."""
    _require_mass_mailing(db, current_user)
    template = None
    if payload.template_id is not None:
        template = _get_accessible_template(db, payload.template_id, current_user)
    campaign = models.Campaign(
        owner_id=current_user.id,
        title=(payload.title or "").strip(),
        template_id=template.id if template is not None else None,
        template_title=template.title if template is not None else None,
        sender_email=str(payload.sender_email),
        greeting=payload.greeting,
        status=models.CampaignStatus.DRAFT,
        total_count=0,
        sent_count=0,
        failed_count=0,
        skipped_count=0,
        pace=campaign_worker.DEFAULT_PACE,
        daily_limit=campaign_worker.global_daily_limit(db),
        send_mode="work_hours",
        attach_pdf=False,
    )
    if not campaign.title:
        raise HTTPException(status_code=400, detail="Укажите название рассылки")
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    logger.info("Создана кампания %s (%s) пользователем %s", campaign.id, campaign.title, current_user.id)
    return _campaign_payload(campaign)


@router.get("/campaigns/{campaign_id}", response_model=schemas.CampaignResponse)
def get_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_mass_mailing(db, current_user)
    campaign = _get_campaign(db, campaign_id, current_user)
    return _campaign_payload(campaign)


@router.put("/campaigns/{campaign_id}", response_model=schemas.CampaignResponse)
def update_campaign(
    campaign_id: int,
    payload: schemas.CampaignUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Изменить черновик (включая настройки темпа/лимита/режима отправки)."""
    _require_mass_mailing(db, current_user)
    campaign = _get_campaign(db, campaign_id, current_user)
    _require_draft(campaign)
    data = payload.model_dump(exclude_unset=True)

    if "template_id" in data:
        template_id = data.pop("template_id")
        if template_id is None:
            campaign.template_id = None
            campaign.template_title = None
        else:
            template = _get_accessible_template(db, int(template_id), current_user)
            campaign.template_id = template.id
            campaign.template_title = template.title
    if "title" in data:
        title = (data.pop("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="Укажите название рассылки")
        campaign.title = title
    if "sender_email" in data:
        campaign.sender_email = str(data.pop("sender_email"))
    if "greeting" in data:
        campaign.greeting = data.pop("greeting")
    if "pace" in data:
        pace = data.pop("pace")
        if pace not in campaign_worker.PACE_CONFIG:
            raise HTTPException(status_code=400, detail="Неизвестный темп отправки")
        campaign.pace = pace
    if "daily_limit" in data:
        campaign.daily_limit = int(data.pop("daily_limit"))
    if "send_mode" in data:
        campaign.send_mode = data.pop("send_mode") or "work_hours"
    if "attach_pdf" in data:
        campaign.attach_pdf = bool(data.pop("attach_pdf"))
    campaign.updated_at = _now()
    db.commit()
    db.refresh(campaign)
    return _campaign_payload(campaign)


@router.put("/campaigns/{campaign_id}/settings", response_model=schemas.CampaignResponse)
def update_campaign_settings(
    campaign_id: int,
    payload: schemas.CampaignSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Отдельная точка сохранения настроек отправки (шаг 4 мастера).

    Разрешена для черновика и приостановленной кампании: темп/лимит можно
    поменять перед продолжением отправки.
    """
    _require_mass_mailing(db, current_user)
    campaign = _get_campaign(db, campaign_id, current_user)
    if campaign.status not in (models.CampaignStatus.DRAFT, models.CampaignStatus.PAUSED):
        raise HTTPException(
            status_code=400,
            detail="Настройки можно менять только у черновика или приостановленной кампании",
        )
    data = payload.model_dump(exclude_unset=True)
    if "pace" in data:
        if data["pace"] not in campaign_worker.PACE_CONFIG:
            raise HTTPException(status_code=400, detail="Неизвестный темп отправки")
        campaign.pace = data["pace"]
    if "daily_limit" in data:
        campaign.daily_limit = int(data["daily_limit"])
    if "send_mode" in data:
        campaign.send_mode = data["send_mode"] or "work_hours"
    if "attach_pdf" in data:
        campaign.attach_pdf = bool(data["attach_pdf"])
    campaign.updated_at = _now()
    db.commit()
    db.refresh(campaign)
    return _campaign_payload(campaign)


@router.delete("/campaigns/{campaign_id}")
def delete_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Удалить кампанию можно только в статусе черновика."""
    _require_mass_mailing(db, current_user)
    campaign = _get_campaign(db, campaign_id, current_user)
    _require_draft(campaign)
    file_path = campaign.import_file_path
    db.query(models.CampaignRecipient).filter(
        models.CampaignRecipient.campaign_id == campaign.id
    ).delete(synchronize_session=False)
    db.delete(campaign)
    db.commit()
    if file_path:
        _remove_file_quietly(file_path)
    return {"message": "Кампания удалена", "id": campaign_id}


# ========== ИМПОРТ ПОЛУЧАТЕЛЕЙ ==========
def _upload_dir() -> str:
    import main
    return main.UPLOAD_DIR


def _remove_file_quietly(path) -> None:
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        logger.warning("Не удалось удалить файл импорта %s", path)


def _save_import_file(file: UploadFile, campaign_id: int) -> str:
    """Сохранить загруженный файл в UPLOAD_DIR/campaign_imports/.

    Читаем кусками, чтобы не держать 10 МБ в памяти и успеть отреагировать на
    слишком большой файл (413).
    """
    safe_name = (file.filename or "").replace("\\", "/").split("/")[-1]
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in importer.ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail="Поддерживаются только файлы .xlsx, .xls, .csv и .txt",
        )
    directory = os.path.join(_upload_dir(), CAMPAIGN_IMPORT_SUBDIR)
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Не удалось создать папку импорта: {exc}")
    unique_name = f"campaign-{campaign_id}-{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(directory, unique_name)
    total = 0
    try:
        with open(file_path, "wb") as target:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > importer.MAX_FILE_BYTES:
                    target.close()
                    _remove_file_quietly(file_path)
                    raise HTTPException(
                        status_code=413, detail="Файл слишком большой (лимит 10 МБ)."
                    )
                target.write(chunk)
    except HTTPException:
        raise
    except OSError as exc:
        _remove_file_quietly(file_path)
        raise HTTPException(status_code=500, detail=f"Не удалось сохранить файл: {exc}")
    return file_path


def _import_response(parsed: dict) -> dict:
    return {
        "columns": parsed.get("columns") or [],
        "mapping": parsed.get("mapping") or {},
        "counts": parsed.get("counts") or {},
        "preview": parsed.get("preview") or [],
    }


def _replace_recipients(db: Session, campaign: models.Campaign, parsed: dict) -> None:
    """Заменить получателей кампании результатом разбора файла.

    В БД попадают только адреса с валидным синтаксисом: дубликаты и мусор
    сохранять нельзя (UniqueConstraint на campaign_id+normalized_email), они
    видны во counts/preview. Отписавшиеся сохраняются со статусом skipped и в
    очередь не попадают.
    """
    db.query(models.CampaignRecipient).filter(
        models.CampaignRecipient.campaign_id == campaign.id
    ).delete(synchronize_session=False)
    pending = 0
    skipped = 0
    for item in parsed.get("recipients") or []:
        is_skipped = item.get("status") == "skipped"
        recipient = models.CampaignRecipient(
            campaign_id=campaign.id,
            email=item.get("email") or item.get("normalized_email"),
            normalized_email=item.get("normalized_email"),
            greeting=item.get("greeting") or None,
            fields=importer.recipients_to_fields_json(item.get("fields")),
            status=(
                models.RecipientStatus.SKIPPED
                if is_skipped
                else models.RecipientStatus.PENDING
            ),
            attempts=0,
            error_code="unsubscribed" if item.get("skip_reason") == "unsubscribed" else None,
            error_text=(
                "Адрес в стоп-листе: получатель отписался от рассылок."
                if item.get("skip_reason") == "unsubscribed"
                else None
            ),
        )
        db.add(recipient)
        if is_skipped:
            skipped += 1
        else:
            pending += 1
    campaign.total_count = pending + skipped
    campaign.sent_count = 0
    campaign.failed_count = 0
    campaign.skipped_count = skipped
    campaign.updated_at = _now()


@router.post("/campaigns/{campaign_id}/import", response_model=schemas.ImportResponse)
def import_recipients(
    campaign_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Загрузить Excel/CSV со списком получателей (шаг 2 мастера)."""
    _require_mass_mailing(db, current_user)
    campaign = _get_campaign(db, campaign_id, current_user)
    _require_draft(campaign)
    file_path = _save_import_file(file, campaign.id)
    try:
        parsed = importer.parse_recipients_file(
            file_path,
            ext=os.path.splitext(file_path)[1].lower(),
            original_name=file.filename,
        )
    except importer.ImportFileError as exc:
        _remove_file_quietly(file_path)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _remove_file_quietly(file_path)
        logger.exception("Не удалось разобрать файл получателей")
        raise HTTPException(status_code=400, detail=f"Не удалось разобрать файл: {exc}")

    old_path = campaign.import_file_path
    _replace_recipients(db, campaign, parsed)
    campaign.import_file_path = file_path
    campaign.updated_at = _now()
    db.commit()
    if old_path and old_path != file_path:
        _remove_file_quietly(old_path)
    db.refresh(campaign)
    logger.info(
        "Кампания %s: импортировано получателей (valid=%s, skipped=%s)",
        campaign.id, _valid_count(parsed), campaign.skipped_count,
    )
    return _import_response(parsed)


def _valid_count(parsed: dict) -> int:
    try:
        return int((parsed.get("counts") or {}).get("valid") or 0)
    except (TypeError, ValueError):
        return 0


@router.post("/campaigns/{campaign_id}/import/remap", response_model=schemas.ImportResponse)
def remap_import(
    campaign_id: int,
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Перечитать сохранённый файл с другим сопоставлением колонок.

    Принимаем обе формы тела: сам объект-сопоставление ({email, greeting, ...})
    и обёртку {"mapping": {...}} - чтобы не зависеть от того, как его соберёт UI.
    """
    raw_mapping = payload
    if isinstance(payload, dict) and isinstance(payload.get("mapping"), dict):
        raw_mapping = payload["mapping"]
    payload = schemas.ImportMapping(**raw_mapping)
    _require_mass_mailing(db, current_user)
    campaign = _get_campaign(db, campaign_id, current_user)
    _require_draft(campaign)
    file_path = campaign.import_file_path
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(
            status_code=400,
            detail="Файл импорта не найден. Загрузите файл получателей заново.",
        )
    try:
        parsed = importer.parse_recipients_file(file_path, mapping=payload)
    except importer.ImportFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Не удалось повторно разобрать файл получателей")
        raise HTTPException(status_code=400, detail=f"Не удалось разобрать файл: {exc}")
    _replace_recipients(db, campaign, parsed)
    campaign.updated_at = _now()
    db.commit()
    db.refresh(campaign)
    return _import_response(parsed)


# ========== ПОЛУЧАТЕЛИ: ПРОСМОТР/РУЧНОЕ ДОБАВЛЕНИЕ ==========
@router.get("/campaigns/{campaign_id}/recipients", response_model=List[schemas.RecipientResponse])
def list_recipients(
    campaign_id: int,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_mass_mailing(db, current_user)
    campaign = _get_campaign(db, campaign_id, current_user)
    query = db.query(models.CampaignRecipient).filter(
        models.CampaignRecipient.campaign_id == campaign.id
    )
    status_enum = None
    if status:
        try:
            status_enum = models.RecipientStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail="Неизвестный статус получателя")
        query = query.filter(models.CampaignRecipient.status == status_enum)
    if status_enum in (models.RecipientStatus.SENT, models.RecipientStatus.FAILED):
        # «Последние отправки» в UI - сначала свежие.
        query = query.order_by(
            models.CampaignRecipient.sent_at.desc(),
            models.CampaignRecipient.id.desc(),
        )
    else:
        query = query.order_by(models.CampaignRecipient.id.asc())
    recipients = query.offset(max(0, int(offset))).limit(_list_limit(limit)).all()
    return recipients


@router.post("/campaigns/{campaign_id}/recipients", response_model=schemas.RecipientResponse)
def add_recipient(
    campaign_id: int,
    payload: schemas.RecipientCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Добавить адрес вручную (только черновик)."""
    _require_mass_mailing(db, current_user)
    campaign = _get_campaign(db, campaign_id, current_user)
    _require_draft(campaign)
    raw_email = str(payload.email).strip()
    normalized = importer.normalize_email(raw_email)
    if not normalized:
        raise HTTPException(status_code=400, detail="Некорректный адрес электронной почты")
    if campaign_worker.is_unsubscribed(db, normalized):
        raise HTTPException(
            status_code=400,
            detail="Адрес находится в стоп-листе отписавшихся и не может получать рассылки",
        )
    existing = db.query(models.CampaignRecipient).filter(
        models.CampaignRecipient.campaign_id == campaign.id,
        models.CampaignRecipient.normalized_email == normalized,
    ).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="Этот адрес уже есть в списке получателей")
    recipient = models.CampaignRecipient(
        campaign_id=campaign.id,
        email=raw_email,
        normalized_email=normalized,
        greeting=payload.greeting,
        fields=json.dumps(payload.fields, ensure_ascii=False) if payload.fields else None,
        status=models.RecipientStatus.PENDING,
        attempts=0,
    )
    db.add(recipient)
    campaign.total_count = int(campaign.total_count or 0) + 1
    campaign.updated_at = _now()
    db.commit()
    db.refresh(recipient)
    return recipient


@router.delete("/campaigns/{campaign_id}/recipients/{recipient_id}")
def delete_recipient(
    campaign_id: int,
    recipient_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_mass_mailing(db, current_user)
    campaign = _get_campaign(db, campaign_id, current_user)
    _require_draft(campaign)
    recipient = db.query(models.CampaignRecipient).filter(
        models.CampaignRecipient.id == recipient_id,
        models.CampaignRecipient.campaign_id == campaign.id,
    ).first()
    if recipient is None:
        raise HTTPException(status_code=404, detail="Получатель не найден")
    was_skipped = recipient.status == models.RecipientStatus.SKIPPED
    db.delete(recipient)
    campaign.total_count = max(0, int(campaign.total_count or 0) - 1)
    if was_skipped:
        campaign.skipped_count = max(0, int(campaign.skipped_count or 0) - 1)
    campaign.updated_at = _now()
    db.commit()
    return {"message": "Получатель удалён", "id": recipient_id}


# ========== PREFLIGHT: ПРОВЕРКИ ПЕРЕД ЗАПУСКОМ ==========
def is_valid_dkim_record(value: str) -> bool:
    """Похоже ли TXT-значение на настоящий DKIM-публичный ключ.

    Раньше «DKIM найден» означало «на селекторе существует любой TXT»: wildcard
    вида `v=DKIM1; p=` (пустой ключ) проходил проверку, и preflight показывал
    «найдены SPF, DKIM и DMARC», хотя ключа нет. Теперь требуем и версию
    v=DKIM1, и непустое значение p= (сам публичный ключ).
    """
    text = str(value or "").strip().strip('"')
    if "v=dkim1" not in text.lower():
        return False
    for part in text.split(";"):
        key, _, val = part.partition("=")
        if key.strip().lower() == "p":
            return len(val.strip().strip('"')) >= 16
    return False


def _check_dns_records(domain: str) -> dict:
    """Проверить SPF/DKIM/DMARC домена отправителя через dnspython.

    Возвращает {"spf": bool, "dkim": bool, "dmarc": bool} либо {"error": текст},
    если DNS недоступен/библиотеки нет. Отдельная функция - тесты подменяют её,
    чтобы не ходить в сеть.
    """
    try:
        import dns.resolver
    except ImportError:
        return {"error": "dnspython не установлен - DNS-проверка недоступна"}
    result = {"spf": False, "dkim": False, "dmarc": False}
    try:
        resolver = dns.resolver.Resolver()
        resolver.timeout = 2.0
        resolver.lifetime = 2.0

        def _txt(name: str) -> list:
            try:
                answers = resolver.resolve(name, "TXT")
            except Exception:
                return []
            values = []
            for record in answers:
                try:
                    chunks = getattr(record, "strings", None)
                    if chunks:
                        values.append(b"".join(chunks).decode("utf-8", "replace"))
                    else:
                        values.append(record.to_text())
                except Exception:
                    values.append(str(record))
            return values

        def _has_prefix(records, prefix: str) -> bool:
            for value in records:
                if value.strip().strip('"').upper().startswith(prefix.upper()):
                    return True
            return False

        result["spf"] = _has_prefix(_txt(domain), "v=spf1")
        result["dmarc"] = _has_prefix(_txt("_dmarc." + domain), "v=DMARC1")
        for selector in ("default", "selector1", "selector2", "yandex", "mail"):
            records = _txt(selector + "._domainkey." + domain)
            if any(is_valid_dkim_record(value) for value in records):
                result["dkim"] = True
                break
        return result
    except Exception as exc:
        return {"error": str(exc)}


def _spam_warnings(subject: str, body_text: str, html_content: str) -> list:
    """Предупреждения антиспам-проверки темы и текста (не блокируют запуск)."""
    warnings = []
    subject = subject or ""
    body_text = body_text or ""
    html_content = html_content or ""
    letters = [ch for ch in subject if ch.isalpha()]
    if len(letters) >= 10:
        caps = sum(1 for ch in letters if ch.isupper())
        if caps / len(letters) > 0.5:
            warnings.append("Тема больше чем наполовину состоит из заглавных букв.")
    if "!!!" in subject or "!!!" in body_text:
        warnings.append("Много восклицательных знаков («!!!»).")
    haystack = (subject + " " + body_text).lower()
    found = [word for word in TRIGGER_WORDS if word in haystack]
    if found:
        warnings.append("Спам-триггеры в тексте: " + ", ".join(found[:8]) + ".")
    links = len(re.findall(r"https?://", html_content, re.IGNORECASE))
    if links > 5:
        warnings.append("Слишком много ссылок в письме (" + str(links) + "); рекомендуется 2-5.")
    images = len(re.findall(r"<img\b", html_content, re.IGNORECASE))
    if images > 10 and len(body_text) < 300:
        warnings.append("Много картинок и мало текста - фильтры это не любят.")
    return warnings


def _build_preflight(db: Session, campaign: models.Campaign, consent_given: bool = False) -> dict:
    import main

    checks = []

    def add(check_id, level, title, detail=""):
        checks.append({"id": check_id, "level": level, "title": title, "detail": detail})

    # 1) SMTP настроен, From не пустой.
    smtp_cfg = main.get_smtp_settings(db)
    from_addr = ""
    if smtp_cfg:
        from_addr = (smtp_cfg.get("from") or smtp_cfg.get("user") or "").strip()
    if not smtp_cfg:
        add("smtp", "fail", "SMTP настроен",
            "Укажите почтовый сервер, логин и пароль приложения в «Настройках».")
    elif not from_addr:
        add("smtp", "fail", "SMTP настроен", "Не задан адрес отправителя (From).")
    else:
        add("smtp", "ok", "SMTP настроен",
            "Отправка через " + str(smtp_cfg.get("host")) + ":" + str(smtp_cfg.get("port")))

    # 2) From совпадает с логином SMTP (иначе провайдер легко отвечает 550 SPF).
    if smtp_cfg and from_addr:
        smtp_user = (smtp_cfg.get("user") or "").strip().lower()
        if not smtp_user or from_addr.strip().lower() == smtp_user:
            add("from", "ok", "Адрес отправителя",
                "From = " + from_addr + " (совпадает с логином SMTP).")
        else:
            add("from", "warn", "Адрес отправителя",
                "From (" + from_addr + ") не совпадает с логином SMTP (" + smtp_user
                + "). Убедитесь, что домен разрешён в SPF, иначе провайдер отклонит письма.")
    elif smtp_cfg:
        add("from", "fail", "Адрес отправителя", "Адрес From пуст.")

    # 3) DNS SPF/DKIM/DMARC.
    domain = from_addr.split("@")[-1].strip().lower() if "@" in from_addr else ""
    if not domain:
        add("dns", "warn", "Доменные записи (SPF/DKIM/DMARC)",
            "Не удалось определить домен отправителя - проверка пропущена.")
    else:
        dns_info = _check_dns_records(domain)
        if dns_info.get("error"):
            add("dns", "warn", "Доменные записи (SPF/DKIM/DMARC)",
                "Не удалось проверить DNS (" + str(dns_info["error"])[:200]
                + "). Это не блокирует отправку.")
        else:
            missing = [name.upper() for name in ("spf", "dkim", "dmarc") if not dns_info.get(name)]
            if missing:
                add("dns", "warn", "Доменные записи (SPF/DKIM/DMARC)",
                    "Для " + domain + " не найдены: " + ", ".join(missing)
                    + ". Письма будут уходить, но риск попадания в спам выше.")
            else:
                add("dns", "ok", "Доменные записи (SPF/DKIM/DMARC)",
                    "Для " + domain + " найдены SPF, DKIM и DMARC.")

    # 4) Шаблон: выбран, в нём есть отписка, plain-text генерируется всегда.
    template = None
    if campaign.template_id is not None:
        template = db.query(models.Template).filter(
            models.Template.id == campaign.template_id
        ).first()
    if template is None:
        add("template", "fail", "Шаблон письма",
            "Шаблон не найден - выберите шаблон заново в черновике.")
        html_content = ""
        subject = campaign.template_title or campaign.title
    else:
        html_content = template.html_content or ""
        subject = template.title or campaign.title
        add("template", "ok", "Шаблон письма", template.title)

    if "отпис" in html_content.lower():
        add("unsubscribe", "ok", "Возможность отписки",
            "В тексте есть упоминание отписки; заголовок List-Unsubscribe добавляется автоматически.")
    else:
        add("unsubscribe", "warn", "Возможность отписки",
            "В тексте нет слова «отписаться». Заголовок List-Unsubscribe будет добавлен, "
            "но дополнительная строка отписки в шаблоне снижает риск спама.")

    add("plain_text", "ok", "Текстовая версия письма",
        "Plain-text версия генерируется автоматически для каждого письма.")

    # 5) Антиспам-скан темы и текста.
    body_text = mail_text.html_to_text(html_content)
    warnings = _spam_warnings(subject, body_text, html_content)
    if warnings:
        add("spam", "warn", "Антиспам-проверка темы и текста", " ".join(warnings))
    else:
        add("spam", "ok", "Антиспам-проверка темы и текста",
            "Заглавных букв, «!!!», спам-слов и лишних ссылок не найдено.")

    # 6) Тестовое письмо (не блокирует запуск).
    if campaign.test_sent_at:
        add("test_send", "ok", "Тестовое письмо",
            "Отправлено " + str(campaign.test_sent_at)[:19] + " UTC.")
    else:
        add("test_send", "warn", "Тестовое письмо",
            "Тестовое письмо ещё не отправлялось. Рекомендуется проверить внешний вид.")

    # 7) Получатели и согласие.
    pending = campaign_worker.pending_count(db, campaign)
    if pending <= 0:
        add("recipients", "fail", "Получатели",
            "В кампании нет адресов для отправки - импортируйте файл получателей.")
    else:
        add("recipients", "ok", "Получатели", "К отправке: " + str(pending))
    if campaign.failed_count:
        add("recipients_errors", "warn", "Не доставлено в прошлых попытках",
            "Адресов с ошибками: " + str(campaign.failed_count)
            + ". Они останутся в отчёте и не будут отправлены повторно.")
    consent_ok = bool(campaign.consent_confirmed) or bool(consent_given)
    if consent_ok:
        add("consent", "ok", "Согласие получателей",
            "Подтверждено, что у получателей есть согласие на рассылку (38-ФЗ).")
    else:
        add("consent", "fail", "Согласие получателей",
            "Отметьте, что у получателей есть согласие на получение рекламных "
            "сообщений (требование 38-ФЗ).")

    can_start = not any(check["level"] == "fail" for check in checks)
    return {
        "checks": checks,
        "can_start": can_start,
        "remaining_today": campaign_worker.remaining_today(db),
        "total_to_send": pending,
    }


@router.get("/campaigns/{campaign_id}/preflight", response_model=schemas.PreflightResponse)
def get_preflight(
    campaign_id: int,
    consent: bool = False,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Чек-лист перед запуском.

    consent=true можно передать, когда на шаге проверки уже отмечен чекбокс
    согласия: иначе пункт «Согласие получателей» будет fail (по контракту он
    обязателен), а фактическое подтверждение фиксируется при POST /start.
    """
    _require_mass_mailing(db, current_user)
    campaign = _get_campaign(db, campaign_id, current_user)
    return _build_preflight(db, campaign, consent_given=consent)


# ========== ТЕСТОВОЕ ПИСЬМО И УПРАВЛЕНИЕ ОТПРАВКОЙ ==========
def _campaign_template(db: Session, campaign: models.Campaign):
    if campaign.template_id is None:
        return None
    return db.query(models.Template).filter(
        models.Template.id == campaign.template_id
    ).first()


@router.post("/campaigns/{campaign_id}/test-send", response_model=schemas.TestSendResponse)
def send_test_email(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Отправить тестовое письмо на адрес текущего пользователя.

    Персонализация берётся у первого получателя (если список уже импортирован),
    чтобы было видно, как письмо выглядит с реальными данными.
    Считается в дневной лимит ящика: это настоящая отправка.
    """
    import main

    _require_mass_mailing(db, current_user)
    campaign = _get_campaign(db, campaign_id, current_user)
    if campaign.status == models.CampaignStatus.RUNNING:
        raise HTTPException(
            status_code=400,
            detail="Сначала поставьте кампанию на паузу, чтобы не мешать реальной отправке",
        )
    template = _campaign_template(db, campaign)
    if template is None:
        raise HTTPException(status_code=400, detail="Шаблон кампании не найден")
    smtp_cfg = main.get_smtp_settings(db)
    if not smtp_cfg:
        raise HTTPException(status_code=400, detail="SMTP не настроен - заполните настройки почтового сервера")
    owner = db.query(models.User).filter(models.User.id == campaign.owner_id).first()
    if owner is None:
        raise HTTPException(status_code=400, detail="Владелец кампании не найден")
    first_recipient = db.query(models.CampaignRecipient).filter(
        models.CampaignRecipient.campaign_id == campaign.id,
        models.CampaignRecipient.status == models.RecipientStatus.PENDING,
    ).order_by(models.CampaignRecipient.id.asc()).first()
    # Персонализация - от первого получателя, но конверт/To - свой адрес.
    preview_recipient = models.CampaignRecipient(
        campaign_id=campaign.id,
        email=current_user.email,
        normalized_email=importer.normalize_email(current_user.email) or current_user.email.lower(),
        greeting=first_recipient.greeting if first_recipient is not None else campaign.greeting,
        fields=first_recipient.fields if first_recipient is not None else None,
    )
    try:
        info = campaign_worker.build_message(campaign, template, preview_recipient, owner, smtp_cfg)
        main._send_via_smtp(smtp_cfg, info["from_addr"], current_user.email, info["msg_string"])
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Кампания %s: тестовое письмо не отправлено: %s", campaign.id, exc)
        raise HTTPException(
            status_code=500,
            detail="Не удалось отправить тестовое письмо: " + str(exc)[:300],
        )
    now = _now()
    campaign.test_sent_at = now
    campaign.updated_at = now
    campaign_worker._log_email(
        db, campaign, template, preview_recipient, "sent",
        info["from_addr"], info["html"],
    )
    campaign_worker.increment_quota(db)
    db.commit()
    db.refresh(campaign)
    return {
        "message": "Тестовое письмо отправлено на " + str(current_user.email),
        "to": str(current_user.email),
    }


@router.post("/campaigns/{campaign_id}/start", response_model=schemas.CampaignResponse)
def start_campaign(
    campaign_id: int,
    payload: schemas.CampaignStartRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Запустить отправку (шаг 4 мастера). consent=true обязателен."""
    import main

    _require_mass_mailing(db, current_user)
    campaign = _get_campaign(db, campaign_id, current_user)
    if campaign.status == models.CampaignStatus.RUNNING:
        raise HTTPException(status_code=400, detail="Кампания уже выполняется")
    if campaign.status == models.CampaignStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Кампания уже завершена")
    if not payload.consent:
        raise HTTPException(
            status_code=400,
            detail="Необходимо подтвердить согласие получателей на получение рассылки (38-ФЗ)",
        )
    if _campaign_template(db, campaign) is None:
        raise HTTPException(status_code=400, detail="Шаблон кампании не найден - выберите шаблон заново")
    if not main.get_smtp_settings(db):
        raise HTTPException(status_code=400, detail="SMTP не настроен - заполните настройки почтового сервера")
    pending = campaign_worker.pending_count(db, campaign)
    if pending <= 0:
        raise HTTPException(status_code=400, detail="В кампании нет получателей для отправки")
    now = _now()
    campaign.consent_confirmed = True
    campaign.consent_confirmed_at = campaign.consent_confirmed_at or now
    campaign.status = models.CampaignStatus.RUNNING
    campaign.started_at = campaign.started_at or now
    campaign.finished_at = None
    campaign.pause_until = None
    campaign.last_error = None
    campaign.updated_at = now
    db.commit()
    db.refresh(campaign)
    campaign_worker.start_worker()
    logger.info("Кампания %s запущена пользователем %s", campaign.id, current_user.id)
    return _campaign_payload(campaign)


@router.post("/campaigns/{campaign_id}/pause", response_model=schemas.CampaignResponse)
def pause_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_mass_mailing(db, current_user)
    campaign = _get_campaign(db, campaign_id, current_user)
    if campaign.status != models.CampaignStatus.RUNNING:
        raise HTTPException(status_code=400, detail="Приостановить можно только идущую кампанию")
    campaign.status = models.CampaignStatus.PAUSED
    campaign.updated_at = _now()
    db.commit()
    db.refresh(campaign)
    return _campaign_payload(campaign)


@router.post("/campaigns/{campaign_id}/resume", response_model=schemas.CampaignResponse)
def resume_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    import main

    _require_mass_mailing(db, current_user)
    campaign = _get_campaign(db, campaign_id, current_user)
    if campaign.status != models.CampaignStatus.PAUSED:
        raise HTTPException(status_code=400, detail="Продолжить можно только приостановленную кампанию")
    if _campaign_template(db, campaign) is None:
        raise HTTPException(status_code=400, detail="Шаблон кампании не найден - выберите шаблон заново")
    if not main.get_smtp_settings(db):
        raise HTTPException(status_code=400, detail="SMTP не настроен - заполните настройки почтового сервера")
    if campaign_worker.pending_count(db, campaign) <= 0:
        raise HTTPException(status_code=400, detail="Не осталось получателей для продолжения отправки")
    campaign.status = models.CampaignStatus.RUNNING
    campaign.pause_until = None
    campaign.last_error = None
    campaign.updated_at = _now()
    db.commit()
    db.refresh(campaign)
    campaign_worker.start_worker()
    return _campaign_payload(campaign)


@router.post("/campaigns/{campaign_id}/stop", response_model=schemas.CampaignResponse)
def stop_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_mass_mailing(db, current_user)
    campaign = _get_campaign(db, campaign_id, current_user)
    if campaign.status not in (models.CampaignStatus.RUNNING, models.CampaignStatus.PAUSED):
        raise HTTPException(status_code=400, detail="Остановить можно только идущую или приостановленную кампанию")
    now = _now()
    campaign.status = models.CampaignStatus.STOPPED
    campaign.finished_at = now
    campaign.pause_until = None
    campaign.updated_at = now
    db.commit()
    db.refresh(campaign)
    return _campaign_payload(campaign)


# ========== ОТЧЁТ И ЭКСПОРТ ==========
@router.get("/campaigns/{campaign_id}/report", response_model=schemas.CampaignReportResponse)
def campaign_report(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_mass_mailing(db, current_user)
    campaign = _get_campaign(db, campaign_id, current_user)
    rows = db.query(
        models.CampaignRecipient.status,
        func.count(models.CampaignRecipient.id),
    ).filter(
        models.CampaignRecipient.campaign_id == campaign.id
    ).group_by(models.CampaignRecipient.status).all()
    by_status = {}
    for status_value, amount in rows:
        by_status[str(getattr(status_value, "value", status_value))] = int(amount)
    counts = {
        "total": sum(by_status.values()),
        "pending": int(by_status.get("pending", 0)) + int(by_status.get("sending", 0)),
        "sent": int(by_status.get("sent", 0)),
        "failed": int(by_status.get("failed", 0)),
        "skipped": int(by_status.get("skipped", 0)),
        "unknown": int(by_status.get("unknown", 0)),
    }
    errors = []
    failed_recipients = db.query(models.CampaignRecipient).filter(
        models.CampaignRecipient.campaign_id == campaign.id,
        models.CampaignRecipient.status.in_([
            models.RecipientStatus.FAILED,
            models.RecipientStatus.UNKNOWN,
        ]),
    ).order_by(models.CampaignRecipient.id.asc()).limit(500).all()
    for recipient in failed_recipients:
        errors.append({
            "email": recipient.email,
            "status": getattr(recipient.status, "value", recipient.status),
            "attempts": int(recipient.attempts or 0),
            "error_code": recipient.error_code,
            "error_text": recipient.error_text,
            "sent_at": recipient.sent_at.isoformat() if recipient.sent_at else None,
        })
    skipped_rows = db.query(models.CampaignRecipient).filter(
        models.CampaignRecipient.campaign_id == campaign.id,
        models.CampaignRecipient.status == models.RecipientStatus.SKIPPED,
    ).order_by(models.CampaignRecipient.id.asc()).limit(500).all()
    skipped = [
        {"email": recipient.email, "reason": recipient.error_text or "пропущен"}
        for recipient in skipped_rows
    ]
    return {
        "campaign": _campaign_payload(campaign),
        "counts": counts,
        "by_status": by_status,
        "errors": errors,
        "skipped": skipped,
        "remaining_today": campaign_worker.remaining_today(db),
    }


@router.get("/campaigns/{campaign_id}/export")
def export_campaign_csv(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Экспорт отчёта в CSV (UTF-8 с BOM, чтобы Excel открыл без «кракозябр»)."""
    _require_mass_mailing(db, current_user)
    campaign = _get_campaign(db, campaign_id, current_user)
    recipients = db.query(models.CampaignRecipient).filter(
        models.CampaignRecipient.campaign_id == campaign.id
    ).order_by(models.CampaignRecipient.id.asc()).all()
    buffer = io.StringIO()
    # «;» - разделитель, который ожидает русская локаль Excel по умолчанию.
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(["email", "greeting", "status", "attempts", "error", "sent_at"])
    for recipient in recipients:
        status_value = getattr(recipient.status, "value", recipient.status)
        writer.writerow([
            recipient.email,
            recipient.greeting or "",
            status_value,
            int(recipient.attempts or 0),
            recipient.error_text or "",
            recipient.sent_at.strftime("%Y-%m-%d %H:%M:%S") if recipient.sent_at else "",
        ])
    file_name = "campaign-" + str(campaign.id) + "-report.csv"
    return Response(
        content=("\ufeff" + buffer.getvalue()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=\"" + file_name + "\""},
    )


# ========== СТОП-ЛИСТ (ОТПИСКИ) ==========
@router.get("/unsubscribes", response_model=List[schemas.UnsubscribeResponse])
def list_unsubscribes(
    limit: int = 200,
    offset: int = 0,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin),
):
    """Глобальный стоп-лист (только администратор)."""
    query = db.query(models.Unsubscribe)
    if search:
        needle = "%" + search.strip().lower() + "%"
        query = query.filter(models.Unsubscribe.normalized_email.like(needle))
    records = query.order_by(
        models.Unsubscribe.created_at.desc(), models.Unsubscribe.id.desc()
    ).offset(max(0, int(offset))).limit(_list_limit(limit)).all()
    return records


@router.post("/unsubscribes", response_model=schemas.UnsubscribeResponse)
def create_unsubscribe(
    payload: schemas.UnsubscribeCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin),
):
    """Добавить адрес в стоп-лист вручную (идемпотентно)."""
    normalized = importer.normalize_email(payload.email)
    if not normalized:
        raise HTTPException(status_code=400, detail="Некорректный адрес электронной почты")
    record = campaign_worker.add_unsubscribe(
        db,
        str(payload.email),
        normalized,
        reason=payload.reason,
        source="manual",
    )
    db.commit()
    db.refresh(record)
    return record


@router.delete("/unsubscribes/{unsubscribe_id}")
def delete_unsubscribe(
    unsubscribe_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin),
):
    record = db.query(models.Unsubscribe).filter(
        models.Unsubscribe.id == unsubscribe_id
    ).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Адрес в стоп-листе не найден")
    db.delete(record)
    db.commit()
    return {"message": "Адрес удалён из стоп-листа", "id": unsubscribe_id}


# ========== ДНЕВНАЯ КВОТА ЯЩИКА ==========
@router.get("/email/quota", response_model=schemas.EmailQuotaResponse)
def email_quota(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Сколько писем уже отправлено сегодня (одиночные + массовые)."""
    limit = campaign_worker.global_daily_limit(db)
    used = campaign_worker.used_today(db)
    return {"used_today": used, "limit": limit, "remaining": max(0, limit - used)}




