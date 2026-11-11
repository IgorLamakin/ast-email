# -*- coding: utf-8 -*-
"""Тесты фонового воркера массовой рассылки (2.7.0).

Файл назван test_worker_*, чтобы идти после test_regressions.py (см. пояснение
в test_worker_importer.py). SMTP всегда мокается - в сеть ничего не уходит;
паузы воркера подменяются, чтобы тесты не ждали реальные минуты.
"""
import datetime
import smtplib

import pytest
from fastapi.testclient import TestClient

import campaign_worker
import main
import models
from database import SessionLocal

API = "/api"
ADMIN_EMAIL = "admin@ast-qa.ru"
ADMIN_PASSWORD = "AdminPass123"
SMTP_CFG = {
    "host": "smtp.example.ru",
    "port": 465,
    "user": "robot@example.ru",
    "password": "SuperSecret",
    "from": "robot@example.ru",
}


@pytest.fixture(scope="session")
def client():
    with TestClient(main.root_app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def admin_headers(client):
    response = client.post(
        f"{API}/auth/login",
        data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    if response.status_code == 200:
        return {"Authorization": "Bearer " + response.json()["access_token"]}
    registered = client.post(
        f"{API}/auth/register",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "full_name": "QA Worker Admin"},
    )
    assert registered.status_code == 200, registered.text
    token = registered.json()["access_token"]
    me = client.get(f"{API}/auth/me", headers={"Authorization": "Bearer " + token}).json()
    assert me["role"] == "admin"
    return {"Authorization": "Bearer " + token}


@pytest.fixture(autouse=True)
def no_worker_thread(monkeypatch):
    """Никаких фоновых потоков: тесты сами вызывают run_campaign_loop синхронно."""
    monkeypatch.setattr(campaign_worker, "start_worker", lambda: False)


@pytest.fixture
def no_sleep(monkeypatch):
    """Темп рассылки не выдерживаем - тесты не должны ждать минуты."""
    sleeps = []
    monkeypatch.setattr(campaign_worker, "_sleep", lambda seconds: sleeps.append(seconds))
    return sleeps


class FakeClock:
    """Виртуальные часы: sleep двигает время, теперь-UTC читается из них."""

    def __init__(self):
        self.current = datetime.datetime.utcnow()
        self.sleeps = []

    def now(self):
        return self.current

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        if seconds and seconds > 0:
            self.current += datetime.timedelta(seconds=float(seconds))


@pytest.fixture
def fake_clock(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(campaign_worker, "now_utc", clock.now)
    monkeypatch.setattr(campaign_worker, "_sleep", clock.sleep)
    return clock


@pytest.fixture
def reset_quota():
    session = SessionLocal()
    try:
        session.query(models.SendQuota).delete()
        session.commit()
    finally:
        session.close()


def _smtp(monkeypatch, handler):
    """SMTP «настроен», отправка делегируется в handler."""
    monkeypatch.setattr(main, "get_smtp_settings", lambda db: dict(SMTP_CFG))
    monkeypatch.setattr(main, "_send_via_smtp", handler)


def _template(client, headers, title="QA worker template", html=None):
    html = html or (
        "<p>Привет, {{ greeting }}!</p>"
        "<p>{{ name }} - {{ company }} - {{ position }} - {{ field_1 }}</p>"
        '<p><a href="mailto:robot@example.ru">Отписаться</a></p>'
    )
    response = client.post(
        f"{API}/templates", headers=headers,
        json={"title": title, "html_content": html},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _campaign(client, headers, template_id, title="QA worker campaign", greeting=None,
              send_mode="now", daily_limit=None):
    payload = {"title": title, "template_id": template_id, "sender_email": "sales@ast-qa.ru"}
    if greeting is not None:
        payload["greeting"] = greeting
    response = client.post(f"{API}/campaigns", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    campaign_id = response.json()["id"]
    update = {"send_mode": send_mode}
    if daily_limit is not None:
        update["daily_limit"] = daily_limit
    updated = client.put(f"{API}/campaigns/{campaign_id}", headers=headers, json=update)
    assert updated.status_code == 200, updated.text
    return campaign_id


def _add_recipients(client, headers, campaign_id, emails, greeting="Друг"):
    ids = []
    for email in emails:
        response = client.post(
            f"{API}/campaigns/{campaign_id}/recipients", headers=headers,
            json={"email": email, "greeting": greeting},
        )
        assert response.status_code == 200, response.text
        ids.append(response.json()["id"])
    return ids


def _set_campaign_status(campaign_id, status):
    session = SessionLocal()
    try:
        campaign = session.query(models.Campaign).filter(
            models.Campaign.id == campaign_id
        ).first()
        campaign.status = status
        session.commit()
    finally:
        session.close()


def _delete_campaign(client, headers, campaign_id):
    _set_campaign_status(campaign_id, models.CampaignStatus.DRAFT)
    response = client.delete(f"{API}/campaigns/{campaign_id}", headers=headers)
    assert response.status_code == 200, response.text


def _campaign_card(client, headers, campaign_id):
    response = client.get(f"{API}/campaigns/{campaign_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _recipients(campaign_id, status=None):
    session = SessionLocal()
    try:
        query = session.query(models.CampaignRecipient).filter(
            models.CampaignRecipient.campaign_id == campaign_id
        )
        if status is not None:
            query = query.filter(models.CampaignRecipient.status == status)
        return query.order_by(models.CampaignRecipient.id.asc()).all()
    finally:
        session.close()


def _start(client, headers, campaign_id):
    response = client.post(
        f"{API}/campaigns/{campaign_id}/start", headers=headers,
        json={"consent": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ========== КОНСТАНТЫ, РАБОЧИЕ ЧАСЫ И КВОТА ==========
def test_pace_config_matches_contract():
    """Темп/пачки из контракта: careful 60с/30шт/15мин, safe 20с/25шт/5мин, fast 8с/50шт/2мин."""
    assert campaign_worker.HARD_DAILY_LIMIT == 300
    assert campaign_worker.PACE_CONFIG == {
        "careful": {"delay": 60, "batch": 30, "batch_pause": 900},
        "safe": {"delay": 20, "batch": 25, "batch_pause": 300},
        "fast": {"delay": 8, "batch": 50, "batch_pause": 120},
    }
    assert campaign_worker.DEFAULT_PACE == "safe"
    assert campaign_worker.RETRY_DELAYS_MINUTES == (5, 15, 60)
    assert campaign_worker.MAX_ATTEMPTS == 3
    assert campaign_worker.WORK_HOURS_START == 9
    assert campaign_worker.WORK_HOURS_END == 18


def test_work_hours_helpers():
    monday = datetime.datetime(2026, 11, 9, 8, 59)
    assert campaign_worker.is_work_hours(monday) is False
    assert campaign_worker.is_work_hours(datetime.datetime(2026, 11, 9, 9, 0)) is True
    assert campaign_worker.is_work_hours(datetime.datetime(2026, 11, 9, 17, 59)) is True
    assert campaign_worker.is_work_hours(datetime.datetime(2026, 11, 9, 18, 0)) is False
    saturday = datetime.datetime(2026, 11, 14, 10, 0)
    assert campaign_worker.is_work_hours(saturday) is False
    expected = (datetime.datetime(2026, 11, 16, 9, 0) - saturday).total_seconds()
    assert campaign_worker.seconds_until_work_hours(saturday) == expected
    assert campaign_worker.seconds_until_work_hours(
        datetime.datetime(2026, 11, 9, 12, 0)
    ) == 0.0
    # В пятницу вечером ждём до понедельника, а не до субботы.
    friday_evening = datetime.datetime(2026, 11, 13, 19, 0)
    expected_friday = (datetime.datetime(2026, 11, 16, 9, 0) - friday_evening).total_seconds()
    assert campaign_worker.seconds_until_work_hours(friday_evening) == expected_friday


def test_quota_helpers(client, admin_headers, reset_quota):
    session = SessionLocal()
    try:
        assert campaign_worker.used_today(session) == 0
        assert campaign_worker.increment_quota(session) == 1
        session.commit()
        assert campaign_worker.used_today(session) == 1
        limit = campaign_worker.global_daily_limit(session)
        assert 1 <= limit <= 300
        assert campaign_worker.remaining_today(session) == limit - 1
        # Ключ квоты - локальная дата.
        quota = session.query(models.SendQuota).first()
        assert quota.day == datetime.date.today().isoformat()
    finally:
        session.close()


def test_daily_limit_never_exceeds_provider_cap(client, admin_headers):
    """Жёсткий потолок 300 писем/сутки: его не поднимают ни настройки, ни кампания."""
    session = SessionLocal()
    try:
        campaign = _transient_campaign(daily_limit=999)
        assert campaign_worker.global_daily_limit(session) <= 300
        assert campaign_worker.effective_daily_limit(session, campaign) <= 300
        assert campaign_worker.HARD_DAILY_LIMIT == 300
    finally:
        session.close()


# ========== СБОРКА ПИСЬМА ==========
def _transient_campaign(**overrides):
    values = dict(
        id=1, owner_id=1, title="QA кампания", template_title="QA тема",
        sender_email="sales@ast-qa.ru", greeting=None, attach_pdf=False,
        pace="safe", daily_limit=250, send_mode="now",
    )
    values.update(overrides)
    return models.Campaign(**values)


def _transient_template(**overrides):
    values = dict(id=1, title="QA тема", html_content="<p>Привет, {{ greeting }}!</p>")
    values.update(overrides)
    return models.Template(**values)


def _transient_owner(**overrides):
    values = dict(
        id=1, email="owner@example.ru", full_name="Пётр Петров",
        company="ООО «АСТ»", position="Менеджер", website="ast.ru",
    )
    values.update(overrides)
    return models.User(**values)


def test_build_message_headers_plain_text_and_escaping():
    from email import message_from_string
    from email.header import decode_header, make_header

    template = _transient_template(
        title="Тема кампании",
        html_content=(
            "<p>{{ greeting }} {{ name }}</p>"
            "<p>{{ field_1 }}</p>"
            "<p>Отписаться от рассылки можно ответным письмом.</p>"
        ),
    )
    campaign = _transient_campaign(greeting="Здравствуйте!")
    recipient = models.CampaignRecipient(
        campaign_id=1,
        email="client@example.ru",
        normalized_email="client@example.ru",
        greeting="Иван",
        fields='{"name": "Иван <b>", "field_1": "<script>alert(1)</script>"}',
    )
    info = campaign_worker.build_message(
        campaign, template, recipient, _transient_owner(), dict(SMTP_CFG)
    )
    message = message_from_string(info["msg_string"])

    assert info["from_addr"] == "robot@example.ru"
    assert info["to_addr"] == "client@example.ru"
    # Тема письма с кириллицей кодируется по RFC 2047 - декодируем для проверки.
    assert str(make_header(decode_header(message["Subject"]))) == "Тема кампании"
    assert message["From"] == "robot@example.ru"
    assert message["To"] == "client@example.ru"
    assert message["Reply-To"] == "robot@example.ru"
    assert message["Precedence"] == "bulk"
    assert message["List-Unsubscribe"] == "<mailto:robot@example.ru?subject=unsubscribe>"
    assert message["Message-ID"].startswith("<")
    assert message["Date"]

    content_types = [part.get_content_type() for part in message.walk()]
    assert content_types.count("text/plain") == 1
    assert content_types.count("text/html") == 1

    plain_part = next(p for p in message.walk() if p.get_content_type() == "text/plain")
    plain_text = plain_part.get_payload(decode=True).decode("utf-8")
    assert "Иван" in plain_text
    assert "Отписаться" in plain_text
    assert "{{" not in plain_text

    html_part = next(p for p in message.walk() if p.get_content_type() == "text/html")
    html_body = html_part.get_payload(decode=True).decode("utf-8")
    # Поля из таблицы экранируются: никакого исполнения HTML.
    assert "&lt;script&gt;" in html_body
    assert "<script>" not in html_body
    assert "{{" not in html_body


def test_personalization_prefers_recipient_and_falls_back_to_profile():
    from email import message_from_string

    template = _transient_template(
        html_content=(
            "<p>{{ greeting }}</p><p>{{ company }}</p>"
            "<p>{{ position }}</p><p>{{ name }}</p>"
        ),
    )
    campaign = _transient_campaign(greeting="Здравствуйте!")
    owner = _transient_owner()

    empty_recipient = models.CampaignRecipient(
        campaign_id=1, email="empty@example.ru", normalized_email="empty@example.ru",
        greeting=None, fields=None,
    )
    info = campaign_worker.build_message(
        campaign, template, empty_recipient, owner, dict(SMTP_CFG)
    )
    html_part = next(
        part for part in message_from_string(info["msg_string"]).walk()
        if part.get_content_type() == "text/html"
    )
    html_body = html_part.get_payload(decode=True).decode("utf-8")
    # Обращение - из кампании, компания/должность - из профиля отправителя.
    assert "Здравствуйте!" in html_body
    assert "ООО «АСТ»" in html_body
    assert "Менеджер" in html_body

    personal_recipient = models.CampaignRecipient(
        campaign_id=1, email="client@example.ru", normalized_email="client@example.ru",
        greeting="Уважаемый Иван!", fields='{"company": "Ромашка", "position": "Директор"}',
    )
    info = campaign_worker.build_message(
        campaign, template, personal_recipient, owner, dict(SMTP_CFG)
    )
    html_part = next(
        part for part in message_from_string(info["msg_string"]).walk()
        if part.get_content_type() == "text/html"
    )
    html_body = html_part.get_payload(decode=True).decode("utf-8")
    assert "Уважаемый Иван!" in html_body
    assert "Ромашка" in html_body
    assert "Директор" in html_body


# ========== ОТПРАВКА ОЧЕРЕДИ ==========
def test_worker_sends_all_recipients_in_order(client, admin_headers, monkeypatch,
                                              reset_quota, no_sleep):
    sent = []
    _smtp(monkeypatch, lambda cfg, sender, recipient, msg: sent.append(recipient))
    template_id = _template(client, admin_headers, title="QA worker send")
    campaign_id = _campaign(client, admin_headers, template_id, title="QA worker send")
    try:
        emails = ["w1@example.ru", "w2@example.ru", "w3@example.ru"]
        _add_recipients(client, admin_headers, campaign_id, emails)
        _start(client, admin_headers, campaign_id)

        assert campaign_worker.run_campaign_loop(campaign_id) == "completed"
        assert sent == emails

        card = _campaign_card(client, admin_headers, campaign_id)
        assert card["status"] == "completed"
        assert card["total_count"] == 3
        assert card["sent_count"] == 3
        assert card["failed_count"] == 0
        assert card["finished_at"] is not None

        recipients = _recipients(campaign_id)
        assert len(recipients) == 3
        assert all(item.status == models.RecipientStatus.SENT for item in recipients)
        assert all(item.sent_at is not None for item in recipients)
        assert all(item.message_id for item in recipients)

        session = SessionLocal()
        try:
            sent_logs = session.query(models.EmailLog).filter(
                models.EmailLog.template_id == template_id,
                models.EmailLog.status == "sent",
            ).count()
            assert sent_logs == 3
            assert campaign_worker.used_today(session) == 3
        finally:
            session.close()
    finally:
        _delete_campaign(client, admin_headers, campaign_id)


def test_worker_pauses_when_daily_limit_reached(client, admin_headers, monkeypatch,
                                                reset_quota, no_sleep):
    sent = []
    _smtp(monkeypatch, lambda cfg, sender, recipient, msg: sent.append(recipient))
    template_id = _template(client, admin_headers, title="QA worker limit")
    campaign_id = _campaign(
        client, admin_headers, template_id, title="QA worker limit", daily_limit=2
    )
    try:
        _add_recipients(client, admin_headers, campaign_id,
                        ["limit1@example.ru", "limit2@example.ru", "limit3@example.ru"])
        session = SessionLocal()
        try:
            # Две отправки уже израсходованы (например, одиночными письмами).
            campaign_worker.increment_quota(session)
            campaign_worker.increment_quota(session)
            session.commit()
            campaign = session.query(models.Campaign).filter(
                models.Campaign.id == campaign_id
            ).first()
            assert campaign_worker.effective_daily_limit(session, campaign) == 2
        finally:
            session.close()

        _start(client, admin_headers, campaign_id)
        assert campaign_worker.run_campaign_loop(campaign_id) == "paused"
        assert sent == []

        card = _campaign_card(client, admin_headers, campaign_id)
        assert card["status"] == "paused"
        assert card["pause_until"] is not None
        assert "лимит" in (card["last_error"] or "").lower()
        assert card["sent_count"] == 0

        session = SessionLocal()
        try:
            assert campaign_worker.used_today(session) == 2
        finally:
            session.close()
    finally:
        _delete_campaign(client, admin_headers, campaign_id)


def test_worker_pauses_when_provider_reports_limit(client, admin_headers, monkeypatch,
                                                   no_sleep):
    def handler(cfg, sender, recipient, msg):
        raise smtplib.SMTPDataError(451, b"4.7.0 too many messages, try later")

    _smtp(monkeypatch, handler)
    template_id = _template(client, admin_headers, title="QA worker provider limit")
    campaign_id = _campaign(client, admin_headers, template_id, title="QA provider limit")
    try:
        _add_recipients(client, admin_headers, campaign_id, ["slow@example.ru"])
        _start(client, admin_headers, campaign_id)
        assert campaign_worker.run_campaign_loop(campaign_id) == "paused"

        card = _campaign_card(client, admin_headers, campaign_id)
        assert card["status"] == "paused"
        assert card["pause_until"] is not None
        assert "ограничении" in card["last_error"]
        # pause_until - примерно через 30 минут.
        pause_until = datetime.datetime.fromisoformat(card["pause_until"])
        minutes = (pause_until - datetime.datetime.utcnow()).total_seconds() / 60
        assert 25 <= minutes <= 35, minutes

        recipient = _recipients(campaign_id)[0]
        assert recipient.status == models.RecipientStatus.PENDING
        assert recipient.in_flight is False
        # Ошибка сервера, а не адреса: попытка получателю не засчитана.
        assert recipient.attempts == 0
    finally:
        _delete_campaign(client, admin_headers, campaign_id)


def test_worker_retries_transient_error_then_succeeds(client, admin_headers, monkeypatch,
                                                      reset_quota, fake_clock):
    calls = []
    sent = []

    def handler(cfg, sender, recipient, msg):
        calls.append(recipient)
        if len(calls) == 1:
            raise smtplib.SMTPServerDisconnected("connection lost")
        sent.append(recipient)

    _smtp(monkeypatch, handler)
    template_id = _template(client, admin_headers, title="QA worker retry")
    campaign_id = _campaign(client, admin_headers, template_id, title="QA worker retry")
    try:
        _add_recipients(client, admin_headers, campaign_id, ["retry@example.ru"])
        _start(client, admin_headers, campaign_id)
        assert campaign_worker.run_campaign_loop(campaign_id) == "completed"
        assert sent == ["retry@example.ru"]

        recipient = _recipients(campaign_id)[0]
        assert recipient.status == models.RecipientStatus.SENT
        assert recipient.attempts == 2
        assert recipient.next_attempt_at is None

        card = _campaign_card(client, admin_headers, campaign_id)
        assert card["status"] == "completed"
        assert card["sent_count"] == 1
        assert card["failed_count"] == 0
        # Между попытками воркер действительно ждал (backoff ~5 минут).
        assert any(seconds >= 240 for seconds in fake_clock.sleeps), fake_clock.sleeps
    finally:
        _delete_campaign(client, admin_headers, campaign_id)


def test_worker_fails_after_max_attempts(client, admin_headers, monkeypatch,
                                         reset_quota, fake_clock):
    def handler(cfg, sender, recipient, msg):
        raise smtplib.SMTPServerDisconnected("smtp drop")

    _smtp(monkeypatch, handler)
    template_id = _template(client, admin_headers, title="QA worker max attempts")
    campaign_id = _campaign(client, admin_headers, template_id, title="QA max attempts")
    try:
        _add_recipients(client, admin_headers, campaign_id, ["dead@example.ru"])
        _start(client, admin_headers, campaign_id)
        assert campaign_worker.run_campaign_loop(campaign_id) == "completed"

        recipient = _recipients(campaign_id)[0]
        assert recipient.status == models.RecipientStatus.FAILED
        assert recipient.attempts == campaign_worker.MAX_ATTEMPTS
        assert recipient.error_text
        assert recipient.next_attempt_at is None

        card = _campaign_card(client, admin_headers, campaign_id)
        assert card["status"] == "completed"
        assert card["failed_count"] == 1
        assert card["sent_count"] == 0

        session = SessionLocal()
        try:
            not_sent = session.query(models.EmailLog).filter(
                models.EmailLog.template_id == template_id,
                models.EmailLog.status == "not_sent",
            ).count()
            assert not_sent == 1
            assert campaign_worker.used_today(session) == 0
        finally:
            session.close()
    finally:
        _delete_campaign(client, admin_headers, campaign_id)


def test_worker_permanent_5xx_fails_immediately(client, admin_headers, monkeypatch,
                                                reset_quota, no_sleep):
    def handler(cfg, sender, recipient, msg):
        raise smtplib.SMTPDataError(554, b"5.7.1 message rejected as spam")

    _smtp(monkeypatch, handler)
    template_id = _template(client, admin_headers, title="QA worker 5xx")
    campaign_id = _campaign(client, admin_headers, template_id, title="QA worker 5xx")
    try:
        _add_recipients(client, admin_headers, campaign_id, ["rejected@example.ru"])
        _start(client, admin_headers, campaign_id)
        assert campaign_worker.run_campaign_loop(campaign_id) == "completed"
        recipient = _recipients(campaign_id)[0]
        assert recipient.status == models.RecipientStatus.FAILED
        # Постоянная ошибка: повторов не было.
        assert recipient.attempts == 1
        card = _campaign_card(client, admin_headers, campaign_id)
        assert card["failed_count"] == 1
    finally:
        _delete_campaign(client, admin_headers, campaign_id)


def test_worker_550_user_unknown_adds_to_stop_list(client, admin_headers, monkeypatch,
                                                   reset_quota, no_sleep):
    email = "unknown-user-mm@example.ru"

    def handler(cfg, sender, recipient, msg):
        raise smtplib.SMTPRecipientsRefused({recipient: (550, b"5.1.1 user unknown")})

    _smtp(monkeypatch, handler)
    template_id = _template(client, admin_headers, title="QA worker 550")
    campaign_id = _campaign(client, admin_headers, template_id, title="QA worker 550")
    session = SessionLocal()
    session.query(models.Unsubscribe).filter(
        models.Unsubscribe.normalized_email == email
    ).delete()
    session.commit()
    session.close()
    try:
        _add_recipients(client, admin_headers, campaign_id, [email])
        _start(client, admin_headers, campaign_id)
        assert campaign_worker.run_campaign_loop(campaign_id) == "completed"

        recipient = _recipients(campaign_id)[0]
        assert recipient.status == models.RecipientStatus.FAILED
        assert recipient.attempts == 1

        session = SessionLocal()
        try:
            record = session.query(models.Unsubscribe).filter(
                models.Unsubscribe.normalized_email == email
            ).first()
            assert record is not None, "550 user unknown должен пополнять стоп-лист"
            assert record.source == "bounce"
        finally:
            session.close()
    finally:
        session = SessionLocal()
        session.query(models.Unsubscribe).filter(
            models.Unsubscribe.normalized_email == email
        ).delete()
        session.commit()
        session.close()
        _delete_campaign(client, admin_headers, campaign_id)


def test_worker_auth_error_stops_campaign(client, admin_headers, monkeypatch,
                                          reset_quota, no_sleep):
    def handler(cfg, sender, recipient, msg):
        raise smtplib.SMTPAuthenticationError(535, b"5.7.8 bad credentials")

    _smtp(monkeypatch, handler)
    template_id = _template(client, admin_headers, title="QA worker auth")
    campaign_id = _campaign(client, admin_headers, template_id, title="QA worker auth")
    try:
        _add_recipients(client, admin_headers, campaign_id,
                        ["auth1@example.ru", "auth2@example.ru"])
        _start(client, admin_headers, campaign_id)
        assert campaign_worker.run_campaign_loop(campaign_id) == "stopped"

        card = _campaign_card(client, admin_headers, campaign_id)
        assert card["status"] == "stopped"
        assert "аутентификац" in card["last_error"].lower()
        # После исправления пароля кампанию можно продолжить: получатели не failed.
        recipients = _recipients(campaign_id)
        assert all(item.status == models.RecipientStatus.PENDING for item in recipients)
        assert all(item.attempts == 0 for item in recipients)
    finally:
        _delete_campaign(client, admin_headers, campaign_id)


def test_worker_skips_address_unsubscribed_after_import(client, admin_headers, monkeypatch,
                                                        reset_quota, no_sleep):
    email = "late-unsub-mm@example.ru"
    sent = []
    _smtp(monkeypatch, lambda cfg, sender, recipient, msg: sent.append(recipient))
    template_id = _template(client, admin_headers, title="QA worker stoplist")
    campaign_id = _campaign(client, admin_headers, template_id, title="QA worker stoplist")
    created = client.post(
        f"{API}/unsubscribes", headers=admin_headers,
        json={"email": email, "reason": "QA поздняя отписка"},
    )
    unsubscribe_id = created.json()["id"]
    try:
        _add_recipients(client, admin_headers, campaign_id,
                        ["still-subscribed-mm@example.ru"])
        # Получатель добавился до отписки - имитируем это в БД.
        session = SessionLocal()
        try:
            session.add(models.CampaignRecipient(
                campaign_id=campaign_id,
                email=email,
                normalized_email=email,
                status=models.RecipientStatus.PENDING,
                attempts=0,
            ))
            campaign = session.query(models.Campaign).filter(
                models.Campaign.id == campaign_id
            ).first()
            campaign.total_count = int(campaign.total_count or 0) + 1
            session.commit()
        finally:
            session.close()

        _start(client, admin_headers, campaign_id)
        assert campaign_worker.run_campaign_loop(campaign_id) == "completed"
        assert sent == ["still-subscribed-mm@example.ru"]

        statuses = {item.normalized_email: item.status for item in _recipients(campaign_id)}
        assert statuses[email] == models.RecipientStatus.SKIPPED
        card = _campaign_card(client, admin_headers, campaign_id)
        assert card["skipped_count"] == 1
        assert card["sent_count"] == 1
    finally:
        client.delete(f"{API}/unsubscribes/{unsubscribe_id}", headers=admin_headers)
        _delete_campaign(client, admin_headers, campaign_id)


def test_recovery_after_restart_marks_unknown(client, admin_headers):
    template_id = _template(client, admin_headers, title="QA worker recovery")
    campaign_id = _campaign(client, admin_headers, template_id, title="QA worker recovery")
    try:
        _add_recipients(client, admin_headers, campaign_id, ["crash@example.ru"])
        session = SessionLocal()
        try:
            campaign = session.query(models.Campaign).filter(
                models.Campaign.id == campaign_id
            ).first()
            campaign.status = models.CampaignStatus.RUNNING
            recipient = session.query(models.CampaignRecipient).filter(
                models.CampaignRecipient.campaign_id == campaign_id
            ).first()
            recipient.in_flight = True
            recipient.status = models.RecipientStatus.SENDING
            session.commit()
        finally:
            session.close()

        result = campaign_worker.recover_after_restart()
        assert result["paused_campaigns"] >= 1
        assert result["unknown_recipients"] >= 1

        session = SessionLocal()
        try:
            campaign = session.query(models.Campaign).filter(
                models.Campaign.id == campaign_id
            ).first()
            assert campaign.status == models.CampaignStatus.PAUSED
            assert "закрыто" in campaign.last_error.lower()
            recipient = session.query(models.CampaignRecipient).filter(
                models.CampaignRecipient.campaign_id == campaign_id
            ).first()
            assert recipient.in_flight is False
            assert recipient.status == models.RecipientStatus.UNKNOWN
        finally:
            session.close()
    finally:
        _delete_campaign(client, admin_headers, campaign_id)


def test_resume_continues_only_remaining_recipients(client, admin_headers, monkeypatch,
                                                    reset_quota, no_sleep):
    sent = []
    _smtp(monkeypatch, lambda cfg, sender, recipient, msg: sent.append(recipient))
    template_id = _template(client, admin_headers, title="QA worker resume")
    campaign_id = _campaign(client, admin_headers, template_id, title="QA worker resume")
    try:
        _add_recipients(client, admin_headers, campaign_id,
                        ["resume1@example.ru", "resume2@example.ru", "resume3@example.ru"])
        # Имитируем паузу после первого успешно отправленного письма.
        session = SessionLocal()
        try:
            recipient = session.query(models.CampaignRecipient).filter(
                models.CampaignRecipient.campaign_id == campaign_id
            ).order_by(models.CampaignRecipient.id.asc()).first()
            recipient.status = models.RecipientStatus.SENT
            recipient.sent_at = datetime.datetime.utcnow()
            campaign = session.query(models.Campaign).filter(
                models.Campaign.id == campaign_id
            ).first()
            campaign.status = models.CampaignStatus.PAUSED
            campaign.sent_count = 1
            session.commit()
        finally:
            session.close()

        resumed = client.post(
            f"{API}/campaigns/{campaign_id}/resume", headers=admin_headers
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["status"] == "running"

        assert campaign_worker.run_campaign_loop(campaign_id) == "completed"
        # Первое письмо повторно не отправлялось.
        assert sent == ["resume2@example.ru", "resume3@example.ru"]
        card = _campaign_card(client, admin_headers, campaign_id)
        assert card["sent_count"] == 3
        assert card["status"] == "completed"
    finally:
        _delete_campaign(client, admin_headers, campaign_id)



