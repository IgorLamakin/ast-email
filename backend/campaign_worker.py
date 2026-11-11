# -*- coding: utf-8 -*-
"""Фоновый воркер массовых рассылок (2.7.0).

Как это работает:
- один поток-демон на процесс; за раз обрабатывается одна активная кампания;
- всё состояние очереди (статусы, попытки, время следующей попытки, дневной
  счётчик) лежит в SQLite - никакого in-memory состояния, поэтому после
  перезапуска приложения кампанию можно продолжить, а «подвисшие» отправки
  становятся unknown и повторно НЕ отправляются;
- письма уходят строго по одному на адрес, SMTP-соединение открывается и
  закрывается на каждое письмо (main._send_via_smtp);
- темп, пачки, рабочие часы и дневной лимит 300 писем/сутки - от блокировки
  SMTP-ящика провайдером (см. PLAN-mass-mailing.md).

Циклический импорт: main.py импортирует этот модуль, поэтому все хелперы из main
(_render_template_html, _inline_local_images, _send_via_smtp, get_smtp_settings)
импортируются ВНУТРИ функций. Так модуль можно безопасно импортировать откуда
угодно (в т.ч. в тестах).
"""
import datetime
import email.utils
import logging
import random
import re
import smtplib
import threading
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy import func, or_

import importer
import mail_text
import models
from database import SessionLocal

logger = logging.getLogger(__name__)

# Жёсткий предел Яндекса: 300 писем в сутки с одного ящика. При превышении -
# блокировка отправки на 24 часа, поэтому выше этого значения настройку не пускаем.
HARD_DAILY_LIMIT = 300

# Темп отправки: пауза между письмами + пауза после каждой пачки.
PACE_CONFIG = {
    "careful": {"delay": 60, "batch": 30, "batch_pause": 15 * 60},
    "safe": {"delay": 20, "batch": 25, "batch_pause": 5 * 60},
    "fast": {"delay": 8, "batch": 50, "batch_pause": 2 * 60},
}
DEFAULT_PACE = "safe"

MAX_ATTEMPTS = 3
RETRY_DELAYS_MINUTES = (5, 15, 60)
WORK_HOURS_START = 9
WORK_HOURS_END = 18
LIMIT_PAUSE_MINUTES = 30
# Максимальный «кусок» ожидания рабочих часов за одну итерацию: чтобы пауза
# пользователя срабатывала не позже чем через 6 часов, а не «через сутки».
WORK_HOURS_MAX_WAIT_SECONDS = 6 * 60 * 60
# Предохранитель от зависания: если воркер долго только «ждёт» (повторная
# попытка/рабочие часы) и ничего не отправляет, кампания ставится на паузу с
# понятной причиной. В реальной работе при настоящем sleep это недостижимо
# (200 итераций по 5 минут = ~17 часов ожидания), но защищает от бесконечного
# цикла, если sleep подменён в тестах.
MAX_IDLE_ITERATIONS = 200

_worker_thread = None
_worker_lock = threading.Lock()
_wake_event = threading.Event()


def _sleep(seconds):
    """Пауза воркера.

    Отдельная функция, чтобы в тестах подменить её на «ничего не делать» -
    иначе каждый тест ждал бы реальные минуты.
    """
    if seconds and seconds > 0:
        time.sleep(seconds)


# ========== ДАТЫ И ДНЕВНАЯ КВОТА ЯЩИКА ==========
def now_utc():
    """Текущее время UTC (в этой базе все DateTime - naive UTC)."""
    return datetime.datetime.utcnow()


def local_today():
    """Локальная дата "YYYY-MM-DD" для дневного счётчика.

    Сутки у провайдера - это сутки пользователя, а не UTC: поэтому ключ
    SendQuota.day считается по локальным часам компьютера.
    """
    return datetime.date.today().isoformat()


def _next_local_midnight(now=None):
    now = now or datetime.datetime.now()
    return datetime.datetime.combine(
        now.date() + datetime.timedelta(days=1), datetime.time.min
    )


def get_quota(db, day=None):
    """Получить (создать при необходимости) дневной счётчик. Не коммитит."""
    day = day or local_today()
    quota = db.query(models.SendQuota).filter(models.SendQuota.day == day).first()
    if quota is None:
        quota = models.SendQuota(day=day, count=0)
        db.add(quota)
        db.flush()
    return quota


def used_today(db):
    quota = db.query(models.SendQuota).filter(models.SendQuota.day == local_today()).first()
    return int(quota.count or 0) if quota is not None else 0


def global_daily_limit(db):
    """Дневной лимит ящика из настроек, но не выше 300 (жёсткий предел провайдера)."""
    settings = db.query(models.AppSettings).order_by(models.AppSettings.id).first()
    limit = settings.mass_mailing_daily_limit if settings is not None else None
    try:
        limit = int(limit) if limit else 250
    except (TypeError, ValueError):
        limit = 250
    return max(1, min(limit, HARD_DAILY_LIMIT))


def effective_daily_limit(db, campaign=None):
    """Лимит для конкретной кампании: меньшее из лимита кампании и лимита ящика."""
    base = global_daily_limit(db)
    if campaign is not None and campaign.daily_limit:
        try:
            return max(1, min(int(campaign.daily_limit), base))
        except (TypeError, ValueError):
            return base
    return base


def increment_quota(db, amount=1):
    """Увеличить счётчик отправок ящика за сегодня. НЕ коммитит (см. вызовы)."""
    quota = get_quota(db)
    quota.count = int(quota.count or 0) + amount
    db.add(quota)
    return quota.count


def remaining_today(db):
    return max(0, global_daily_limit(db) - used_today(db))


# ========== СТОП-ЛИСТ (ОТПИСКИ) ==========
def is_unsubscribed(db, normalized_email):
    if not normalized_email:
        return False
    return db.query(models.Unsubscribe).filter(
        models.Unsubscribe.normalized_email == normalized_email
    ).first() is not None


def add_unsubscribe(db, email, normalized_email, reason=None, source="manual"):
    """Добавить адрес в стоп-лист (идемпотентно, НЕ коммитит)."""
    if not normalized_email:
        return None
    existing = db.query(models.Unsubscribe).filter(
        models.Unsubscribe.normalized_email == normalized_email
    ).first()
    if existing is not None:
        return existing
    record = models.Unsubscribe(
        normalized_email=normalized_email,
        email_raw=email or normalized_email,
        reason=reason,
        source=source,
    )
    db.add(record)
    return record


# ========== ВОССТАНОВЛЕНИЕ ПОСЛЕ ПЕРЕЗАПУСКА ПРИЛОЖЕНИЯ ==========
RECOVERY_MESSAGE = "Приложение было закрыто во время отправки"


def recover_after_restart(db=None):
    """Привести БД в согласованное состояние после аварийного завершения.

    - кампании, которые были в running, ставим на paused (иначе UI показывал бы
      «идёт отправка», а никакого воркера уже нет);
    - получатели, которые в момент закрытия были in_flight, получают статус
      unknown и повторно НЕ отправляются (лучше потерять одно письмо, чем
      отправить двум людям дважды).
    """
    own_session = db is None
    session = db or SessionLocal()
    paused = 0
    unknown = 0
    try:
        running = session.query(models.Campaign).filter(
            models.Campaign.status == models.CampaignStatus.RUNNING
        ).all()
        for campaign in running:
            campaign.status = models.CampaignStatus.PAUSED
            campaign.last_error = RECOVERY_MESSAGE
            campaign.pause_until = None
            campaign.updated_at = now_utc()
            paused += 1
        in_flight = session.query(models.CampaignRecipient).filter(
            models.CampaignRecipient.in_flight.is_(True)
        ).all()
        for recipient in in_flight:
            recipient.in_flight = False
            if recipient.status in (
                models.RecipientStatus.SENDING,
                models.RecipientStatus.PENDING,
            ):
                recipient.status = models.RecipientStatus.UNKNOWN
                recipient.error_code = "unconfirmed"
                recipient.error_text = (
                    "Отправка не подтверждена: приложение было закрыто в момент "
                    "отправки. Адрес не переотправляется автоматически."
                )
            unknown += 1
        session.commit()
        if paused or unknown:
            logger.info(
                "Восстановление после перезапуска: %s кампаний на паузе, "
                "%s «подвисших» получателей помечены unknown", paused, unknown
            )
        return {"paused_campaigns": paused, "unknown_recipients": unknown}
    except Exception:
        logger.exception("Не удалось восстановить состояние кампаний после перезапуска")
        session.rollback()
        return {"paused_campaigns": 0, "unknown_recipients": 0}
    finally:
        if own_session:
            session.close()


# ========== ФОРМИРОВАНИЕ ПИСЬМА ==========
_EXTRA_PLACEHOLDER_RE = re.compile(r"\{\{\s*field_(\d+)\s*\}\}")


def _apply_extra_fields(html_content, fields):
    """Подставить {{ field_1 }}...{{ field_N }} из доп. колонок файла.

    Дополнительные поля приходят из произвольных колонок Excel, поэтому
    подставляем их сами (main._render_template_html знает только фиксированный
    белый список), но с обязательным HTML-экранированием - никакого исполнения
    шаблонного кода и никакой XSS от данных таблицы.
    """
    if not html_content or not fields:
        return html_content
    import html as html_module

    def _replace(match):
        value = fields.get("field_" + match.group(1))
        if value is None:
            return ""
        return html_module.escape(str(value), quote=True)

    return _EXTRA_PLACEHOLDER_RE.sub(_replace, html_content)


def _owner_value(owner, attribute):
    return getattr(owner, attribute, None) or ""


def _personalization_context(campaign, recipient, owner, fields):
    """Контекст подстановки для main._render_template_html.

    Персональные поля получателя (company/position/name) имеют приоритет, а если
    в файле их не было - берём данные профиля отправителя, чтобы письмо не
    оставалось с пустыми местами.
    """
    import main

    return {
        "greeting": (getattr(recipient, "greeting", None) if recipient is not None else None)
                    or campaign.greeting or "",
        "recipient_email": (getattr(recipient, "email", "") if recipient is not None else ""),
        "sender_email": campaign.sender_email or _owner_value(owner, "sender_email")
                        or _owner_value(owner, "email"),
        "name": fields.get("name", ""),
        "company": fields.get("company", "") or _owner_value(owner, "company"),
        "position": fields.get("position", "") or _owner_value(owner, "position"),
        "full_name": _owner_value(owner, "full_name"),
        "address": _owner_value(owner, "address"),
        "phone": _owner_value(owner, "phone"),
        "website": main._normalize_website(_owner_value(owner, "website")),
    }


def build_message(campaign, template, recipient, owner, smtp_cfg):
    """Собрать MIME-письмо для получателя. SMTP здесь НЕ вызывается.

    Возвращает словарь:
    {msg_string, from_addr, to_addr, message_id, html, plain_text}. Это удобно
    и для отправки, и для тестов (можно проверить заголовки/текст, не отправляя).
    """
    import main

    fields = importer.fields_from_json(recipient.fields) if recipient is not None else {}
    html_content = _apply_extra_fields(template.html_content or "", fields)
    context = _personalization_context(campaign, recipient, owner, fields)
    rendered_html = main._render_template_html(html_content, context)
    # Ссылки на localhost-картинки получателю недоступны - встраиваем их в письмо.
    rendered_html = main._inline_local_images(rendered_html)
    plain_text = mail_text.html_to_text(rendered_html)

    from_addr = (
        smtp_cfg.get("from")
        or smtp_cfg.get("user")
        or campaign.sender_email
        or _owner_value(owner, "email")
    )
    to_addr = getattr(recipient, "email", "") if recipient is not None else ""
    domain = from_addr.split("@")[-1] if "@" in (from_addr or "") else None
    message_id = email.utils.make_msgid(domain=domain)

    body = MIMEMultipart("alternative")
    body.attach(MIMEText(plain_text, "plain", "utf-8"))
    body.attach(MIMEText(rendered_html, "html", "utf-8"))

    if campaign.attach_pdf:
        # PDF - необязательный бонус; если не собрался, письмо всё равно уйдёт.
        msg = MIMEMultipart("mixed")
        msg.attach(body)
        try:
            pdf_bytes = main._html_to_pdf_bytes(main._strip_pdf_excluded(rendered_html))
        except Exception as exc:
            logger.warning("Не удалось сформировать PDF для получателя %s: %s", to_addr, exc)
            pdf_bytes = None
        if pdf_bytes:
            pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
            safe_name = re.sub(r"[^\w\-. ]", "_", template.title or "letter") or "letter"
            pdf_part.add_header(
                "Content-Disposition", "attachment", filename=safe_name + ".pdf"
            )
            msg.attach(pdf_part)
    else:
        msg = body

    msg["Subject"] = template.title or campaign.template_title or campaign.title
    msg["From"] = from_addr
    msg["To"] = to_addr
    # Reply-To - реальный ящик: на массовые письма люди часто отвечают, и ответ
    # должен уходить в обычную почту, а не в «noreply».
    msg["Reply-To"] = from_addr
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = message_id
    # List-Unsubscribe понимают Яндекс/Mail.ru/Gmail - обязательный признак
    # легальной рассылки; mailto: работает без собственного сервера.
    msg["List-Unsubscribe"] = "<mailto:" + from_addr + "?subject=unsubscribe>"
    msg["Precedence"] = "bulk"

    return {
        "msg_string": msg.as_string(),
        "from_addr": from_addr,
        "to_addr": to_addr,
        "message_id": message_id,
        "html": rendered_html,
        "plain_text": plain_text,
    }


def send_one(campaign, template, recipient, owner, smtp_cfg):
    """Собрать и отправить ОДНО письмо. Возвращает словарь из build_message().

    Точка подмены для тестов: main._send_via_smtp monkeypatch-ится, а сборку
    письма можно проверить через build_message().
    """
    import main

    info = build_message(campaign, template, recipient, owner, smtp_cfg)
    main._send_via_smtp(smtp_cfg, info["from_addr"], info["to_addr"], info["msg_string"])
    return info


# ========== КЛАССИФИКАЦИЯ SMTP-ОШИБОК ==========
_LIMIT_MARKERS = ("limit", "too many", "421", "451", "458")
_USER_UNKNOWN_MARKERS = (
    "user unknown", "unknown user", "unknown recipient", "no such user",
    "user not found", "mailbox unavailable", "mailbox not found",
    "does not exist", "doesn't exist", "recipient address rejected",
)


def _error_text(exc):
    text = str(exc or "")
    smtp_error = getattr(exc, "smtp_error", None)
    if smtp_error:
        if isinstance(smtp_error, (bytes, bytearray)):
            try:
                smtp_error = smtp_error.decode("utf-8", errors="replace")
            except Exception:
                smtp_error = ""
        if smtp_error:
            text = (text + " " + str(smtp_error)).strip()
    return text


def _looks_like_unknown_user(text):
    low = (text or "").lower()
    return any(marker in low for marker in _USER_UNKNOWN_MARKERS)


def _looks_like_limit(text):
    low = (text or "").lower()
    return any(marker in low for marker in _LIMIT_MARKERS)


def classify_smtp_error(exc):
    """Разобрать SMTP-исключение в понятный план действий.

    Возвращает словарь:
    retry         - временная ошибка, повторить с задержкой;
    permanent     - постоянная ошибка (повторов нет);
    stop_campaign - ошибка аутентификации, останавливаем всю кампанию;
    pause_minutes - сервер сообщил о лимите, пауза на N минут;
    unsubscribe   - добавить адрес в стоп-лист (550 user unknown);
    code/text     - сохранить в CampaignRecipient.
    """
    text = _error_text(exc)
    plan = {
        "retry": False,
        "permanent": False,
        "stop_campaign": False,
        "pause_minutes": 0,
        "unsubscribe": False,
        "code": None,
        "text": text.strip()[:1000],
    }
    smtp_code = getattr(exc, "smtp_code", None)
    if smtp_code is not None:
        try:
            plan["code"] = str(int(smtp_code))
        except (TypeError, ValueError):
            plan["code"] = str(smtp_code)

    if isinstance(exc, smtplib.SMTPAuthenticationError):
        plan["stop_campaign"] = True
        return plan

    # Сообщение про лимит - пауза 30 минут независимо от кода ответа (Яндекс
    # умеет отдавать и 421/451, и 550 с текстом про limit).
    if _looks_like_limit(text):
        plan["pause_minutes"] = LIMIT_PAUSE_MINUTES
        return plan

    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        refused = getattr(exc, "recipients", {}) or {}
        codes = []
        for value in refused.values():
            try:
                codes.append(int(value[0]))
            except (TypeError, ValueError, IndexError):
                continue
        if codes:
            plan["code"] = str(codes[0])
        if any(500 <= code < 600 for code in codes):
            plan["permanent"] = True
            plan["unsubscribe"] = (
                any(code == 550 for code in codes) and _looks_like_unknown_user(text)
            )
        else:
            plan["retry"] = True
        return plan

    if isinstance(exc, smtplib.SMTPResponseException):
        try:
            code = int(exc.smtp_code)
        except (TypeError, ValueError):
            code = None
        if code is not None and 500 <= code < 600:
            plan["permanent"] = True
            plan["unsubscribe"] = code == 550 and _looks_like_unknown_user(text)
        else:
            plan["retry"] = True
        return plan

    if isinstance(
        exc,
        (
            smtplib.SMTPServerDisconnected,
            smtplib.SMTPConnectError,
            smtplib.SMTPHeloError,
            smtplib.SMTPException,
            OSError,
        ),
    ):
        plan["retry"] = True
        return plan

    # Неизвестное исключение (например, слишком большие картинки): даём шанс
    # повторить, после MAX_ATTEMPTS адрес уйдёт в failed.
    plan["retry"] = True
    return plan


# ========== ОБРАБОТКА ОДНОГО ПОЛУЧАТЕЛЯ ==========
def _log_email(db, campaign, template, recipient, status, from_addr=None, html=None):
    """Записать письмо в EmailLog (аналитика должна видеть и массовые отправки)."""
    import main

    db.add(models.EmailLog(
        sender_id=campaign.owner_id,
        sender_email=from_addr or campaign.sender_email or "",
        recipient_email=recipient.email,
        greeting=recipient.greeting,
        template_id=campaign.template_id,
        template_title=(
            campaign.template_title
            or (template.title if template is not None else None)
        ),
        html_content=main._compact_email_snapshot(html or ""),
        status=status,
    ))


def _mark_sent(db, campaign, template, recipient, info):
    now = now_utc()
    recipient.status = models.RecipientStatus.SENT
    recipient.in_flight = False
    recipient.sent_at = now
    recipient.message_id = info.get("message_id")
    recipient.next_attempt_at = None
    recipient.error_code = None
    recipient.error_text = None
    campaign.sent_count = int(campaign.sent_count or 0) + 1
    campaign.updated_at = now
    _log_email(db, campaign, template, recipient, "sent", info.get("from_addr"), info.get("html"))
    increment_quota(db)
    db.commit()
    return "sent"


def _handle_send_error(db, campaign, recipient, exc):
    """Разложить ошибку отправки по правилам контракта. Возвращает исход."""
    plan = classify_smtp_error(exc)
    now = now_utc()
    recipient.in_flight = False
    recipient.error_code = plan.get("code") or "smtp_error"
    recipient.error_text = plan.get("text")

    if plan["stop_campaign"]:
        # Проблема ящика, а не адреса: попытку получателю не «сжигаем».
        recipient.attempts = max(0, int(recipient.attempts or 1) - 1)
        recipient.status = models.RecipientStatus.PENDING
        recipient.next_attempt_at = None
        campaign.status = models.CampaignStatus.STOPPED
        campaign.pause_until = None
        campaign.last_error = (
            "Ошибка аутентификации SMTP - проверьте пароль приложения в настройках. "
            + (plan.get("text") or "")[:300]
        )
        campaign.updated_at = now
        db.commit()
        logger.error("Кампания %s: ошибка аутентификации SMTP, кампания остановлена", campaign.id)
        return "stopped"

    if plan["pause_minutes"]:
        recipient.attempts = max(0, int(recipient.attempts or 1) - 1)
        recipient.status = models.RecipientStatus.PENDING
        recipient.next_attempt_at = None
        campaign.status = models.CampaignStatus.PAUSED
        campaign.pause_until = now + datetime.timedelta(minutes=plan["pause_minutes"])
        campaign.last_error = (
            "Почтовый сервер сообщил об ограничении отправки. "
            "Отправка приостановлена на " + str(plan["pause_minutes"]) + " мин; "
            "продолжите кампанию позже."
        )
        campaign.updated_at = now
        db.commit()
        logger.warning("Кампания %s: сервер сообщил о лимите, пауза", campaign.id)
        return "paused"

    attempts = int(recipient.attempts or 0)
    if plan["retry"] and attempts < MAX_ATTEMPTS:
        delay_index = max(0, min(attempts - 1, len(RETRY_DELAYS_MINUTES) - 1))
        delay_minutes = RETRY_DELAYS_MINUTES[delay_index]
        recipient.status = models.RecipientStatus.PENDING
        recipient.next_attempt_at = now + datetime.timedelta(minutes=delay_minutes)
        campaign.updated_at = now
        db.commit()
        logger.info(
            "Кампания %s: временная ошибка для %s (попытка %s/%s), повтор через %s мин",
            campaign.id, recipient.email, attempts, MAX_ATTEMPTS, delay_minutes,
        )
        return "retry"

    # Постоянная ошибка или попытки исчерпаны.
    recipient.status = models.RecipientStatus.FAILED
    recipient.next_attempt_at = None
    campaign.failed_count = int(campaign.failed_count or 0) + 1
    campaign.updated_at = now
    if plan["unsubscribe"]:
        add_unsubscribe(
            db,
            recipient.email,
            recipient.normalized_email,
            reason=(plan.get("text") or "")[:500],
            source="bounce",
        )
        logger.info("Адрес %s добавлен в стоп-лист (550 user unknown)", recipient.email)
    _log_email(db, campaign, None, recipient, "not_sent")
    db.commit()
    return "failed"


# ========== РАБОЧИЕ ЧАСЫ ==========
def is_work_hours(now=None):
    """Пн-Пт 09:00-18:00 (локальное время)."""
    now = now or datetime.datetime.now()
    return now.weekday() < 5 and WORK_HOURS_START <= now.hour < WORK_HOURS_END


def seconds_until_work_hours(now=None):
    """Сколько секунд осталось до ближайшего рабочего окна (0 - уже можно)."""
    now = now or datetime.datetime.now()
    if is_work_hours(now):
        return 0.0
    target = now.replace(hour=WORK_HOURS_START, minute=0, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    while target.weekday() >= 5:
        target += datetime.timedelta(days=1)
    return max(0.0, (target - now).total_seconds())


# ========== ОЧЕРЕДЬ И ЦИКЛ ОТПРАВКИ ==========
def _get_campaign(db, campaign_id):
    return db.query(models.Campaign).filter(models.Campaign.id == campaign_id).first()


def _next_pending_recipient(db, campaign):
    """Следующий pending-получатель, для которого подошло время попытки."""
    now = now_utc()
    return db.query(models.CampaignRecipient).filter(
        models.CampaignRecipient.campaign_id == campaign.id,
        models.CampaignRecipient.status == models.RecipientStatus.PENDING,
        or_(
            models.CampaignRecipient.next_attempt_at.is_(None),
            models.CampaignRecipient.next_attempt_at <= now,
        ),
    ).order_by(models.CampaignRecipient.id.asc()).first()


def pending_count(db, campaign):
    return int(db.query(func.count(models.CampaignRecipient.id)).filter(
        models.CampaignRecipient.campaign_id == campaign.id,
        models.CampaignRecipient.status == models.RecipientStatus.PENDING,
    ).scalar() or 0)


def _next_retry_delay(db, campaign):
    """Сколько секунд до ближайшей отложенной повторной попытки (или None)."""
    now = now_utc()
    minimum = db.query(func.min(models.CampaignRecipient.next_attempt_at)).filter(
        models.CampaignRecipient.campaign_id == campaign.id,
        models.CampaignRecipient.status == models.RecipientStatus.PENDING,
        models.CampaignRecipient.next_attempt_at > now,
    ).scalar()
    if minimum is None:
        return None
    return max(1.0, (minimum - now).total_seconds())


def _stop_campaign(db, campaign, message):
    campaign.status = models.CampaignStatus.STOPPED
    campaign.last_error = message
    campaign.pause_until = None
    campaign.updated_at = now_utc()
    db.commit()
    logger.warning("Кампания %s остановлена: %s", campaign.id, message)


def _pause_campaign(db, campaign, message, pause_until=None):
    campaign.status = models.CampaignStatus.PAUSED
    campaign.last_error = message
    campaign.pause_until = pause_until
    campaign.updated_at = now_utc()
    db.commit()


def _pause_for_daily_limit(db, campaign, limit):
    message = (
        "Достигнут дневной лимит отправок (" + str(limit) + " писем в сутки). "
        "Отправка остановлена до следующего дня; продолжите кампанию после полуночи."
    )
    _pause_campaign(db, campaign, message, pause_until=_next_local_midnight())
    logger.warning("Кампания %s: дневной лимит %s достигнут", campaign.id, limit)


def _complete_campaign(db, campaign):
    """Все получатели обработаны: пересчитать счётчики и закрыть кампанию."""
    rows = db.query(
        models.CampaignRecipient.status,
        func.count(models.CampaignRecipient.id),
    ).filter(models.CampaignRecipient.campaign_id == campaign.id).group_by(
        models.CampaignRecipient.status
    ).all()
    counts = {}
    for status_value, amount in rows:
        key = getattr(status_value, "value", status_value)
        counts[str(key)] = int(amount)
    now = now_utc()
    campaign.total_count = sum(counts.values())
    campaign.sent_count = counts.get("sent", 0)
    campaign.failed_count = counts.get("failed", 0)
    # unknown - это «отправка не подтверждена»: в отчёте он виден отдельно
    # (by_status), а в общих счётчиках идёт как «пропущено», чтобы
    # sent+failed+skipped == total и прогресс-бар сходился.
    campaign.skipped_count = counts.get("skipped", 0) + counts.get("unknown", 0)
    campaign.status = models.CampaignStatus.COMPLETED
    campaign.finished_at = now
    campaign.pause_until = None
    campaign.updated_at = now
    db.commit()
    logger.info(
        "Кампания %s завершена: отправлено %s, ошибок %s, пропущено %s",
        campaign.id, campaign.sent_count, campaign.failed_count, campaign.skipped_count,
    )


def _run_campaign_loop(db, campaign_id):
    """Основной цикл обработки одной кампании. Возвращает строковый исход."""
    import main

    campaign = _get_campaign(db, campaign_id)
    if campaign is None or campaign.status != models.CampaignStatus.RUNNING:
        return "not_running"

    template = None
    if campaign.template_id is not None:
        template = db.query(models.Template).filter(
            models.Template.id == campaign.template_id
        ).first()
    if template is None:
        _stop_campaign(db, campaign, "Шаблон рассылки не найден. Выберите шаблон заново.")
        return "stopped"
    owner = db.query(models.User).filter(models.User.id == campaign.owner_id).first()
    if owner is None:
        _stop_campaign(db, campaign, "Владелец кампании не найден.")
        return "stopped"
    smtp_cfg = main.get_smtp_settings(db)
    if not smtp_cfg:
        _stop_campaign(
            db, campaign,
            "SMTP не настроен. Заполните настройки почтового сервера и запустите кампанию снова.",
        )
        return "stopped"

    pace_key = campaign.pace if campaign.pace in PACE_CONFIG else DEFAULT_PACE
    pace = PACE_CONFIG[pace_key]
    sent_in_batch = 0
    idle_iterations = 0

    while True:
        db.expire_all()
        campaign = _get_campaign(db, campaign_id)
        if campaign is None or campaign.status != models.CampaignStatus.RUNNING:
            return "not_running"

        # 1) Рабочие часы: ночью и в выходные не отправляем.
        if (campaign.send_mode or "").strip() == "work_hours":
            wait_seconds = seconds_until_work_hours()
            if wait_seconds > 0:
                idle_iterations += 1
                if idle_iterations > MAX_IDLE_ITERATIONS:
                    _pause_campaign(
                        db, campaign,
                        "Долгое ожидание рабочих часов (09:00-18:00 Пн-Пт). "
                        "Продолжите кампанию в рабочее время.",
                    )
                    return "paused"
                _sleep(min(wait_seconds, WORK_HOURS_MAX_WAIT_SECONDS))
                continue

        # 2) Дневной лимит ящика (300/сутки, с учётом одиночных отправок).
        limit = effective_daily_limit(db, campaign)
        if used_today(db) >= limit:
            _pause_for_daily_limit(db, campaign, limit)
            return "paused"

        # 3) Следующий получатель.
        recipient = _next_pending_recipient(db, campaign)
        if recipient is None:
            retry_delay = _next_retry_delay(db, campaign)
            if retry_delay is not None:
                idle_iterations += 1
                if idle_iterations > MAX_IDLE_ITERATIONS:
                    _pause_campaign(
                        db, campaign,
                        "Отправка приостановлена: ожидание повторной попытки занимает "
                        "слишком долго. Нажмите «Продолжить», чтобы возобновить.",
                    )
                    return "paused"
                _sleep(min(retry_delay, 300.0))
                continue
            _complete_campaign(db, campaign)
            return "completed"

        idle_iterations = 0

        # 4) Повторная проверка стоп-листа: адрес мог отписаться уже после импорта.
        if is_unsubscribed(db, recipient.normalized_email):
            recipient.status = models.RecipientStatus.SKIPPED
            recipient.in_flight = False
            recipient.error_code = "unsubscribed"
            recipient.error_text = "Адрес в стоп-листе: получатель отписался от рассылок."
            campaign.skipped_count = int(campaign.skipped_count or 0) + 1
            campaign.updated_at = now_utc()
            db.commit()
            continue

        # 5) Отправка одного письма. in_flight фиксируем ДО сети - если приложение
        #    упадёт во время отправки, при следующем старте адрес станет unknown.
        recipient.status = models.RecipientStatus.SENDING
        recipient.in_flight = True
        recipient.attempts = int(recipient.attempts or 0) + 1
        recipient.next_attempt_at = None
        db.commit()
        try:
            info = send_one(campaign, template, recipient, owner, smtp_cfg)
        except Exception as exc:
            logger.warning(
                "Кампания %s: ошибка отправки на %s: %s",
                campaign.id, recipient.email, _error_text(exc),
            )
            outcome = _handle_send_error(db, campaign, recipient, exc)
        else:
            outcome = _mark_sent(db, campaign, template, recipient, info)

        if outcome in ("paused", "stopped"):
            return outcome

        # 6) Темп: пауза между письмами (+/-30% джиттера) и паузы между пачками.
        _sleep(pace["delay"] * random.uniform(0.7, 1.3))
        if outcome == "sent":
            sent_in_batch += 1
            if pace["batch"] and sent_in_batch % pace["batch"] == 0:
                _sleep(pace["batch_pause"])


def run_campaign_loop(campaign_id):
    """Синхронно обработать очередь одной кампании.

    Используется фоновым потоком и тестами (тестам так проще: без гонок).
    """
    db = SessionLocal()
    try:
        outcome = _run_campaign_loop(db, campaign_id)
        logger.info("Кампания %s: воркер завершил работу (%s)", campaign_id, outcome)
        return outcome
    except Exception:
        logger.exception("Кампания %s: непредвиденная ошибка воркера", campaign_id)
        return "error"
    finally:
        db.close()


# ========== ФОНОВЫЙ ПОТОК ==========
def _next_running_campaign_id():
    db = SessionLocal()
    try:
        campaign = db.query(models.Campaign).filter(
            models.Campaign.status == models.CampaignStatus.RUNNING
        ).order_by(
            models.Campaign.started_at.asc(), models.Campaign.id.asc()
        ).first()
        return campaign.id if campaign is not None else None
    finally:
        db.close()


def _worker_main():
    global _worker_thread
    logger.info("Воркер массовых рассылок запущен")
    try:
        while True:
            _wake_event.clear()
            campaign_id = _next_running_campaign_id()
            if campaign_id is None:
                # Простаиваем; start/resume разбудят нас событием.
                _wake_event.wait(5.0)
                continue
            try:
                run_campaign_loop(campaign_id)
            except Exception:
                logger.exception("Воркер: ошибка обработки кампании %s", campaign_id)
    finally:
        with _worker_lock:
            _worker_thread = None
        logger.info("Воркер массовых рассылок остановлен")


def start_worker():
    """Запустить фоновый поток воркера, если он ещё не работает."""
    global _worker_thread
    with _worker_lock:
        _wake_event.set()
        if _worker_thread is not None and _worker_thread.is_alive():
            return False
        thread = threading.Thread(target=_worker_main, name="campaign-worker", daemon=True)
        _worker_thread = thread
        thread.start()
        return True


def is_worker_running():
    thread = _worker_thread
    return thread is not None and thread.is_alive()



