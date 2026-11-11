# -*- coding: utf-8 -*-
"""Тесты REST API массовой рассылки (2.7.0).

Название test_worker_campaign_api.py (а не test_campaigns.py) выбрано так, чтобы
файл шёл ПОСЛЕ существующего test_regressions.py: pytest собирает файлы по
алфавиту, а test_regressions.py рассчитывает, что первый зарегистрированный в
сессии пользователь станет администратором.

SMTP и DNS здесь всегда подменены: тесты полностью офлайновые, в сеть ничего
не уходит (даже если в БД остались настройки smtp.ast-qa.ru от старых тестов).
"""
import csv
import io
import os

import pytest
from fastapi.testclient import TestClient

import campaign_worker
import campaigns
import main
import models
from database import SessionLocal

API = "/api"
ADMIN_EMAIL = "admin@ast-qa.ru"
ADMIN_PASSWORD = "AdminPass123"
REGULAR_EMAIL = "mm-regular@ast-qa.ru"
REGULAR_PASSWORD = "RegularPass123"
OTHER_EMAIL = "mm-other@ast-qa.ru"
OTHER_PASSWORD = "OtherPass123"

SMTP_CFG = {
    "host": "smtp.example.ru",
    "port": 465,
    "user": "robot@example.ru",
    "password": "SuperSecret",
    "from": "robot@example.ru",
}

DEFAULT_HTML = (
    "<p>Привет, {{ greeting }}!</p>"
    "<p>{{ name }} - {{ company }} - {{ position }} - {{ field_1 }} - {{ field_2 }}</p>"
)


@pytest.fixture(scope="session")
def client():
    with TestClient(main.root_app) as test_client:
        yield test_client


def _login(client, email, password):
    return client.post(f"{API}/auth/login", data={"username": email, "password": password})


def _register_or_login(client, email, password, full_name="QA MM"):
    response = client.post(
        f"{API}/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    if response.status_code == 200:
        return response.json()["access_token"]
    assert response.status_code == 400, response.text
    login = _login(client, email, password)
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


@pytest.fixture(scope="session")
def admin_headers(client):
    """Администратор: в полном прогоне уже создан test_regressions.py."""
    login = _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    if login.status_code == 200:
        return {"Authorization": "Bearer " + login.json()["access_token"]}
    # Отдельный запуск модуля: в чистой БД первый пользователь = администратор.
    token = _register_or_login(client, ADMIN_EMAIL, ADMIN_PASSWORD, "QA Admin")
    me = client.get(f"{API}/auth/me", headers={"Authorization": "Bearer " + token}).json()
    assert me["role"] == "admin", "первый пользователь в чистой БД должен стать админом"
    return {"Authorization": "Bearer " + token}


@pytest.fixture(scope="session")
def regular_headers(client):
    token = _register_or_login(client, REGULAR_EMAIL, REGULAR_PASSWORD, "QA Regular")
    return {"Authorization": "Bearer " + token}


@pytest.fixture(scope="session")
def other_headers(client):
    token = _register_or_login(client, OTHER_EMAIL, OTHER_PASSWORD, "QA Other")
    return {"Authorization": "Bearer " + token}


@pytest.fixture
def smtp_mock(monkeypatch):
    """SMTP настроен, реальная отправка заменена на запись в список."""
    sent = []

    monkeypatch.setattr(main, "get_smtp_settings", lambda db: dict(SMTP_CFG))

    def _fake_send(cfg, sender, recipient, msg_string):
        sent.append({"from": sender, "to": recipient, "msg": msg_string})

    monkeypatch.setattr(main, "_send_via_smtp", _fake_send)
    return sent


@pytest.fixture
def dns_ok(monkeypatch):
    monkeypatch.setattr(
        campaigns, "_check_dns_records",
        lambda domain: {"spf": True, "dkim": True, "dmarc": True},
    )


@pytest.fixture
def reset_quota():
    session = SessionLocal()
    try:
        session.query(models.SendQuota).delete()
        session.commit()
    finally:
        session.close()


def _enable_mass_mailing(client, admin_headers, enabled=True, limit=None):
    payload = {"mass_mailing_enabled": enabled}
    if limit is not None:
        payload["mass_mailing_daily_limit"] = limit
    response = client.put(f"{API}/settings", headers=admin_headers, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _template(client, headers, title="QA MM template", html=DEFAULT_HTML):
    response = client.post(
        f"{API}/templates", headers=headers,
        json={"title": title, "html_content": html},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_campaign(client, headers, template_id, title="QA кампания",
                     sender="sales@ast-qa.ru", greeting=None):
    payload = {"title": title, "template_id": template_id, "sender_email": sender}
    if greeting is not None:
        payload["greeting"] = greeting
    return client.post(f"{API}/campaigns", headers=headers, json=payload)


def _upload_csv(client, headers, campaign_id, rows, name="recipients.csv",
                encoding="utf-8-sig", delimiter=";"):
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")
    for row in rows:
        writer.writerow(row)
    payload = buffer.getvalue().encode(encoding)
    return client.post(
        f"{API}/campaigns/{campaign_id}/import",
        headers=headers,
        files={"file": (name, payload, "text/csv")},
    )


def _import_default_recipients(client, headers, campaign_id):
    rows = [
        ["E-mail", "Обращение", "Компания", "Должность", "Город"],
        ["client1@example.ru", "Иван", "ООО «АСТ»", "Директор", "Краснодар"],
        ["CLIENT1@Example.RU", "Дубль", "", "", ""],
        ["client2@example.ru", "", "Ромашка", "Бухгалтер", "Сочи"],
        ["мусор", "", "", "", ""],
    ]
    response = _upload_csv(client, headers, campaign_id, rows)
    assert response.status_code == 200, response.text
    return response.json()


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
    client.delete(f"{API}/campaigns/{campaign_id}", headers=headers)


# ========== НАСТРОЙКИ И ПРАВА ==========
def test_settings_expose_mass_mailing_fields(client, admin_headers):
    before = client.get(f"{API}/settings", headers=admin_headers)
    assert before.status_code == 200, before.text
    data = before.json()
    assert "mass_mailing_enabled" in data
    assert isinstance(data["mass_mailing_daily_limit"], int)
    assert 1 <= data["mass_mailing_daily_limit"] <= 300

    updated = client.put(
        f"{API}/settings", headers=admin_headers,
        json={"mass_mailing_enabled": True, "mass_mailing_daily_limit": 200},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["mass_mailing_enabled"] is True
    assert body["mass_mailing_daily_limit"] == 200
    # PUT /settings частичный: SMTP-настройки, сохранённые ранее, не затёрты.
    assert body["smtp_host"] == data["smtp_host"]
    assert body["smtp_user"] == data["smtp_user"]

    # Валидация лимита: 0 и 301 недопустимы.
    assert client.put(
        f"{API}/settings", headers=admin_headers,
        json={"mass_mailing_daily_limit": 0},
    ).status_code == 422
    assert client.put(
        f"{API}/settings", headers=admin_headers,
        json={"mass_mailing_daily_limit": 301},
    ).status_code == 422

    _enable_mass_mailing(
        client, admin_headers, data["mass_mailing_enabled"],
        data["mass_mailing_daily_limit"],
    )


def test_settings_requires_admin(client, regular_headers):
    assert client.get(f"{API}/settings", headers=regular_headers).status_code == 403
    assert client.put(
        f"{API}/settings", headers=regular_headers,
        json={"mass_mailing_enabled": True},
    ).status_code == 403


def test_capabilities_admin_and_regular(client, admin_headers, regular_headers):
    _enable_mass_mailing(client, admin_headers, False)
    admin_caps = client.get(f"{API}/campaigns/capabilities", headers=admin_headers).json()
    assert admin_caps["is_admin"] is True
    assert admin_caps["allowed"] is True
    assert 1 <= admin_caps["daily_limit"] <= 300
    assert 0 <= admin_caps["remaining_today"] <= admin_caps["daily_limit"]

    regular_caps = client.get(f"{API}/campaigns/capabilities", headers=regular_headers).json()
    assert regular_caps["is_admin"] is False
    assert regular_caps["allowed"] is False

    _enable_mass_mailing(client, admin_headers, True)
    try:
        regular_caps = client.get(f"{API}/campaigns/capabilities", headers=regular_headers).json()
        assert regular_caps["allowed"] is True
    finally:
        _enable_mass_mailing(client, admin_headers, False)


def test_regular_user_blocked_until_flag(client, admin_headers, regular_headers):
    _enable_mass_mailing(client, admin_headers, False)
    template_id = _template(client, admin_headers, title="QA MM permission")
    blocked = _create_campaign(client, regular_headers, template_id, title="Чужая попытка")
    assert blocked.status_code == 403, blocked.text
    assert client.get(f"{API}/campaigns", headers=regular_headers).status_code == 403

    _enable_mass_mailing(client, admin_headers, True)
    try:
        # Обычному пользователю доступны только его шаблоны и опубликованные,
        # поэтому для корректной проверки создаём шаблон от его имени.
        regular_template_id = _template(client, regular_headers, title="QA MM regular template")
        created = _create_campaign(
            client, regular_headers, regular_template_id, title="QA regular campaign"
        )
        assert created.status_code == 200, created.text
        regular_campaign_id = created.json()["id"]
        own = client.get(f"{API}/campaigns/{regular_campaign_id}", headers=regular_headers)
        assert own.status_code == 200

        admin_campaign = _create_campaign(
            client, admin_headers, template_id, title="QA admin campaign"
        ).json()
        # Чужую кампанию обычный пользователь не видит (404, а не 403 - не палим).
        assert client.get(
            f"{API}/campaigns/{admin_campaign['id']}", headers=regular_headers
        ).status_code == 404
        # Администратор видит кампании всех пользователей.
        titles = [item["title"] for item in client.get(
            f"{API}/campaigns", headers=admin_headers
        ).json()]
        assert "QA regular campaign" in titles
        _delete_campaign(client, admin_headers, regular_campaign_id)
        _delete_campaign(client, admin_headers, admin_campaign["id"])
    finally:
        _enable_mass_mailing(client, admin_headers, False)


# ========== CRUD КАМПАНИЙ ==========
def test_campaign_crud_and_settings(client, admin_headers):
    template_id = _template(client, admin_headers, title="QA MM crud")
    created = _create_campaign(
        client, admin_headers, template_id, title="QA CRUD", greeting="Здравствуйте!"
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == "draft"
    assert body["can_start"] is True
    assert body["greeting"] == "Здравствуйте!"
    assert body["template_title"] == "QA MM crud"
    assert body["total_count"] == 0 and body["total"] == 0
    assert body["settings"]["pace"] == "safe"
    assert body["settings"]["send_mode"] == "work_hours"
    campaign_id = body["id"]

    updated = client.put(
        f"{API}/campaigns/{campaign_id}", headers=admin_headers,
        json={
            "title": "QA CRUD 2", "pace": "fast", "daily_limit": 100,
            "send_mode": "now", "attach_pdf": True,
        },
    )
    assert updated.status_code == 200, updated.text
    data = updated.json()
    assert data["title"] == "QA CRUD 2"
    assert data["settings"] == {
        "pace": "fast", "daily_limit": 100, "send_mode": "now", "attach_pdf": True,
    }
    assert data["attach_pdf"] is True

    settings_response = client.put(
        f"{API}/campaigns/{campaign_id}/settings", headers=admin_headers,
        json={"pace": "careful", "daily_limit": 50},
    )
    assert settings_response.status_code == 200, settings_response.text
    assert settings_response.json()["settings"]["pace"] == "careful"
    assert settings_response.json()["settings"]["daily_limit"] == 50

    assert client.put(
        f"{API}/campaigns/{campaign_id}", headers=admin_headers,
        json={"pace": "turbo"},
    ).status_code == 400
    assert client.put(
        f"{API}/campaigns/{campaign_id}", headers=admin_headers,
        json={"daily_limit": 500},
    ).status_code == 422

    items = client.get(f"{API}/campaigns", headers=admin_headers).json()
    assert any(item["id"] == campaign_id for item in items)

    deleted = client.delete(f"{API}/campaigns/{campaign_id}", headers=admin_headers)
    assert deleted.status_code == 200, deleted.text
    assert client.get(
        f"{API}/campaigns/{campaign_id}", headers=admin_headers
    ).status_code == 404


def test_non_draft_campaign_is_locked(client, admin_headers):
    template_id = _template(client, admin_headers, title="QA MM locked")
    campaign_id = _create_campaign(
        client, admin_headers, template_id, title="QA locked"
    ).json()["id"]
    _set_campaign_status(campaign_id, models.CampaignStatus.PAUSED)
    try:
        assert client.put(
            f"{API}/campaigns/{campaign_id}", headers=admin_headers,
            json={"title": "нельзя"},
        ).status_code == 400
        assert client.delete(
            f"{API}/campaigns/{campaign_id}", headers=admin_headers
        ).status_code == 400
        # Импорт тоже разрешён только для черновика.
        response = _upload_csv(
            client, admin_headers, campaign_id,
            [["E-mail"], ["locked@example.ru"]],
        )
        assert response.status_code == 400
    finally:
        _set_campaign_status(campaign_id, models.CampaignStatus.DRAFT)
        _delete_campaign(client, admin_headers, campaign_id)


def test_campaign_not_found(client, admin_headers):
    assert client.get(
        f"{API}/campaigns/999999", headers=admin_headers
    ).status_code == 404
    assert client.put(
        f"{API}/campaigns/999999", headers=admin_headers, json={"title": "x"}
    ).status_code == 404


# ========== ИМПОРТ ПОЛУЧАТЕЛЕЙ ==========
def test_import_csv_creates_recipients(client, admin_headers):
    template_id = _template(client, admin_headers, title="QA MM import")
    campaign_id = _create_campaign(
        client, admin_headers, template_id, title="QA import"
    ).json()["id"]
    data = _import_default_recipients(client, admin_headers, campaign_id)

    assert data["mapping"]["email"] == "E-mail"
    assert data["mapping"]["greeting"] == "Обращение"
    assert data["counts"] == {
        "total": 4, "valid": 2, "duplicates": 1, "invalid": 1, "unsubscribed": 0,
    }
    assert len(data["preview"]) == 4
    assert [row["status"] for row in data["preview"]] == [
        "ok", "duplicate", "ok", "invalid",
    ]

    recipients = client.get(
        f"{API}/campaigns/{campaign_id}/recipients", headers=admin_headers
    ).json()
    assert len(recipients) == 2
    assert {item["email"] for item in recipients} == {
        "client1@example.ru", "client2@example.ru",
    }
    assert all(item["status"] == "pending" for item in recipients)
    first = next(item for item in recipients if item["email"] == "client1@example.ru")
    assert first["greeting"] == "Иван"

    card = client.get(f"{API}/campaigns/{campaign_id}", headers=admin_headers).json()
    assert card["total_count"] == 2

    session = SessionLocal()
    try:
        campaign = session.query(models.Campaign).filter(
            models.Campaign.id == campaign_id
        ).first()
        saved_path = campaign.import_file_path
    finally:
        session.close()
    assert saved_path and os.path.exists(saved_path)
    assert "campaign_imports" in saved_path

    _delete_campaign(client, admin_headers, campaign_id)
    assert not os.path.exists(saved_path), "при удалении кампании файл импорта удаляется"


def test_import_remap_replaces_recipients(client, admin_headers):
    template_id = _template(client, admin_headers, title="QA MM remap")
    campaign_id = _create_campaign(
        client, admin_headers, template_id, title="QA remap"
    ).json()["id"]
    rows = [
        ["E-mail", "Контакт", "Город"],
        ["remap@example.ru", "Иван Петров", "Краснодар"],
    ]
    imported = _upload_csv(client, admin_headers, campaign_id, rows)
    assert imported.status_code == 200, imported.text
    # Автоопределение: «Контакт» - это имя, а не обращение.
    assert imported.json()["mapping"]["name"] == "Контакт"
    assert imported.json()["mapping"]["greeting"] is None

    remapped = client.post(
        f"{API}/campaigns/{campaign_id}/import/remap", headers=admin_headers,
        json={"mapping": {"email": "E-mail", "greeting": "Контакт", "extra": ["Город"]}},
    )
    assert remapped.status_code == 200, remapped.text
    body = remapped.json()
    assert body["mapping"]["greeting"] == "Контакт"
    assert body["mapping"]["name"] is None
    assert body["counts"]["valid"] == 1

    recipients = client.get(
        f"{API}/campaigns/{campaign_id}/recipients", headers=admin_headers
    ).json()
    assert len(recipients) == 1
    assert recipients[0]["greeting"] == "Иван Петров"
    assert "field_1" in (recipients[0]["fields"] or "")
    _delete_campaign(client, admin_headers, campaign_id)


def test_import_rejects_bad_files(client, admin_headers):
    template_id = _template(client, admin_headers, title="QA MM bad file")
    campaign_id = _create_campaign(
        client, admin_headers, template_id, title="QA bad file"
    ).json()["id"]
    try:
        wrong_type = client.post(
            f"{API}/campaigns/{campaign_id}/import", headers=admin_headers,
            files={"file": ("virus.exe", b"MZ", "application/octet-stream")},
        )
        assert wrong_type.status_code == 400
        broken = client.post(
            f"{API}/campaigns/{campaign_id}/import", headers=admin_headers,
            files={"file": ("broken.xlsx", b"this is not excel", "application/vnd.ms-excel")},
        )
        assert broken.status_code == 400
        assert "Не удалось" in broken.json()["detail"]
    finally:
        _delete_campaign(client, admin_headers, campaign_id)


def test_manual_add_and_delete_recipient(client, admin_headers):
    template_id = _template(client, admin_headers, title="QA MM manual")
    campaign_id = _create_campaign(
        client, admin_headers, template_id, title="QA manual"
    ).json()["id"]
    try:
        added = client.post(
            f"{API}/campaigns/{campaign_id}/recipients", headers=admin_headers,
            json={"email": "manual-mm@example.ru", "greeting": "Добрый день"},
        )
        assert added.status_code == 200, added.text
        recipient_id = added.json()["id"]
        assert added.json()["status"] == "pending"
        assert added.json()["normalized_email"] == "manual-mm@example.ru"

        duplicate = client.post(
            f"{API}/campaigns/{campaign_id}/recipients", headers=admin_headers,
            json={"email": "MANUAL-MM@example.ru"},
        )
        assert duplicate.status_code == 400

        invalid = client.post(
            f"{API}/campaigns/{campaign_id}/recipients", headers=admin_headers,
            json={"email": "не-адрес"},
        )
        assert invalid.status_code == 422

        card = client.get(f"{API}/campaigns/{campaign_id}", headers=admin_headers).json()
        assert card["total_count"] == 1

        removed = client.delete(
            f"{API}/campaigns/{campaign_id}/recipients/{recipient_id}",
            headers=admin_headers,
        )
        assert removed.status_code == 200
        assert client.delete(
            f"{API}/campaigns/{campaign_id}/recipients/{recipient_id}",
            headers=admin_headers,
        ).status_code == 404
        card = client.get(f"{API}/campaigns/{campaign_id}", headers=admin_headers).json()
        assert card["total_count"] == 0
    finally:
        _delete_campaign(client, admin_headers, campaign_id)


def test_import_marks_unsubscribed_as_skipped(client, admin_headers):
    blocked = "import-blocked@example.ru"
    created_unsub = client.post(
        f"{API}/unsubscribes", headers=admin_headers,
        json={"email": blocked, "reason": "QA"},
    )
    assert created_unsub.status_code == 200, created_unsub.text
    unsubscribe_id = created_unsub.json()["id"]
    template_id = _template(client, admin_headers, title="QA MM stoplist")
    campaign_id = _create_campaign(
        client, admin_headers, template_id, title="QA stoplist"
    ).json()["id"]
    try:
        response = _upload_csv(client, admin_headers, campaign_id, [
            ["E-mail"],
            [blocked],
            ["free-after-stop@example.ru"],
        ])
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["counts"]["valid"] == 1
        assert body["counts"]["unsubscribed"] == 1
        assert [row["status"] for row in body["preview"]] == ["unsubscribed", "ok"]

        recipients = client.get(
            f"{API}/campaigns/{campaign_id}/recipients", headers=admin_headers
        ).json()
        by_status = {item["status"] for item in recipients}
        assert by_status == {"pending", "skipped"}
        card = client.get(f"{API}/campaigns/{campaign_id}", headers=admin_headers).json()
        assert card["skipped_count"] == 1
        assert card["total_count"] == 2

        # Ручное добавление адреса из стоп-листа запрещено.
        assert client.post(
            f"{API}/campaigns/{campaign_id}/recipients", headers=admin_headers,
            json={"email": blocked},
        ).status_code == 400
    finally:
        _delete_campaign(client, admin_headers, campaign_id)
        client.delete(f"{API}/unsubscribes/{unsubscribe_id}", headers=admin_headers)


# ========== PREFLIGHT ==========
def test_preflight_fails_without_smtp_and_recipients(client, admin_headers, monkeypatch):
    monkeypatch.setattr(main, "get_smtp_settings", lambda db: None)
    monkeypatch.setattr(campaigns, "_check_dns_records", lambda domain: {"error": "нет сети"})
    template_id = _template(client, admin_headers, title="QA MM preflight fail")
    campaign_id = _create_campaign(
        client, admin_headers, template_id, title="QA preflight fail"
    ).json()["id"]
    try:
        response = client.get(
            f"{API}/campaigns/{campaign_id}/preflight", headers=admin_headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        checks = {check["id"]: check for check in body["checks"]}
        assert checks["smtp"]["level"] == "fail"
        assert checks["recipients"]["level"] == "fail"
        assert checks["consent"]["level"] == "fail"
        assert body["can_start"] is False
        assert body["total_to_send"] == 0
        assert body["remaining_today"] >= 0

        # С отмеченным чекбоксом согласия этот пункт больше не блокирует.
        consented = client.get(
            f"{API}/campaigns/{campaign_id}/preflight?consent=true", headers=admin_headers
        ).json()
        consented_checks = {check["id"]: check for check in consented["checks"]}
        assert consented_checks["consent"]["level"] == "ok"
        # Но SMTP и получатели всё ещё блокируют запуск.
        assert consented["can_start"] is False
    finally:
        _delete_campaign(client, admin_headers, campaign_id)


def test_preflight_ok_for_ready_campaign(client, admin_headers, smtp_mock, dns_ok):
    template_id = _template(client, admin_headers, title="QA MM preflight ok")
    campaign_id = _create_campaign(
        client, admin_headers, template_id, title="QA preflight ok"
    ).json()["id"]
    try:
        _import_default_recipients(client, admin_headers, campaign_id)
        body = client.get(
            f"{API}/campaigns/{campaign_id}/preflight?consent=true", headers=admin_headers
        ).json()
        checks = {check["id"]: check for check in body["checks"]}
        assert checks["smtp"]["level"] == "ok"
        assert checks["from"]["level"] == "ok"
        assert checks["dns"]["level"] == "ok"
        assert checks["template"]["level"] == "ok"
        assert checks["recipients"]["level"] == "ok"
        assert body["can_start"] is True
        assert body["total_to_send"] == 2
        # DNS-проверка мокается, поэтому в сеть тест не ходит.
    finally:
        _delete_campaign(client, admin_headers, campaign_id)


# ========== ТЕСТОВОЕ ПИСЬМО ==========
def test_test_send_builds_personalized_message(client, admin_headers, smtp_mock, reset_quota):
    from email import message_from_string

    template_id = _template(client, admin_headers, title="QA MM test send")
    campaign_id = _create_campaign(
        client, admin_headers, template_id, title="QA test send", greeting="Здравствуйте!"
    ).json()["id"]
    try:
        _import_default_recipients(client, admin_headers, campaign_id)
        response = client.post(
            f"{API}/campaigns/{campaign_id}/test-send", headers=admin_headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["to"] == ADMIN_EMAIL
        assert len(smtp_mock) == 1

        message = message_from_string(smtp_mock[0]["msg"])
        assert message["To"] == ADMIN_EMAIL
        assert message["Subject"] == "QA MM test send"
        assert message["From"] == SMTP_CFG["from"]
        assert message["Precedence"] == "bulk"
        assert message["List-Unsubscribe"].startswith("<mailto:")
        assert message["Reply-To"] == SMTP_CFG["from"]
        assert message["Message-ID"] and message["Date"]
        content_types = {part.get_content_type() for part in message.walk()}
        assert "text/plain" in content_types
        assert "text/html" in content_types
        plain_part = next(
            part for part in message.walk() if part.get_content_type() == "text/plain"
        )
        plain_text = plain_part.get_payload(decode=True).decode("utf-8")
        # Персонализация берётся у первого получателя (обращение «Иван»).
        assert "Иван" in plain_text

        card = client.get(f"{API}/campaigns/{campaign_id}", headers=admin_headers).json()
        assert card["test_sent_at"] is not None
        quota = client.get(f"{API}/email/quota", headers=admin_headers).json()
        assert quota["used_today"] == 1
    finally:
        _delete_campaign(client, admin_headers, campaign_id)


# ========== ЗАПУСК / ПАУЗА / ПРОДОЛЖЕНИЕ / СТОП ==========
def test_start_requires_consent_recipients_and_smtp(client, admin_headers, monkeypatch):
    template_id = _template(client, admin_headers, title="QA MM start checks")
    campaign_id = _create_campaign(
        client, admin_headers, template_id, title="QA start checks"
    ).json()["id"]
    monkeypatch.setattr(main, "get_smtp_settings", lambda db: None)
    try:
        _import_default_recipients(client, admin_headers, campaign_id)
        assert client.post(
            f"{API}/campaigns/{campaign_id}/start", headers=admin_headers,
            json={"consent": False},
        ).status_code == 400
        # Согласие есть, но SMTP не настроен.
        assert client.post(
            f"{API}/campaigns/{campaign_id}/start", headers=admin_headers,
            json={"consent": True},
        ).status_code == 400

        monkeypatch.setattr(main, "get_smtp_settings", lambda db: dict(SMTP_CFG))
        empty_campaign = _create_campaign(
            client, admin_headers, template_id, title="QA start empty"
        ).json()["id"]
        response = client.post(
            f"{API}/campaigns/{empty_campaign}/start", headers=admin_headers,
            json={"consent": True},
        )
        assert response.status_code == 400
        assert "получател" in response.json()["detail"]
        _delete_campaign(client, admin_headers, empty_campaign)
        # Ни одна из неудачных попыток не перевела кампанию в running.
        card = client.get(f"{API}/campaigns/{campaign_id}", headers=admin_headers).json()
        assert card["status"] == "draft"
    finally:
        _delete_campaign(client, admin_headers, campaign_id)


def test_start_pause_resume_stop_flow(client, admin_headers, smtp_mock, monkeypatch):
    worker_starts = []
    monkeypatch.setattr(
        campaign_worker, "start_worker",
        lambda: worker_starts.append(True) or False,
    )
    template_id = _template(client, admin_headers, title="QA MM flow")
    campaign_id = _create_campaign(
        client, admin_headers, template_id, title="QA flow"
    ).json()["id"]
    try:
        _import_default_recipients(client, admin_headers, campaign_id)
        started = client.post(
            f"{API}/campaigns/{campaign_id}/start", headers=admin_headers,
            json={"consent": True},
        )
        assert started.status_code == 200, started.text
        assert started.json()["status"] == "running"
        assert started.json()["consent_confirmed"] is True
        assert started.json()["consent_confirmed_at"] is not None
        assert started.json()["started_at"] is not None
        assert worker_starts, "старт кампании должен запускать воркер"

        assert client.post(
            f"{API}/campaigns/{campaign_id}/start", headers=admin_headers,
            json={"consent": True},
        ).status_code == 400

        paused = client.post(
            f"{API}/campaigns/{campaign_id}/pause", headers=admin_headers
        )
        assert paused.status_code == 200
        assert paused.json()["status"] == "paused"
        assert client.post(
            f"{API}/campaigns/{campaign_id}/pause", headers=admin_headers
        ).status_code == 400

        resumed = client.post(
            f"{API}/campaigns/{campaign_id}/resume", headers=admin_headers
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["status"] == "running"

        stopped = client.post(
            f"{API}/campaigns/{campaign_id}/stop", headers=admin_headers
        )
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "stopped"
        assert stopped.json()["finished_at"] is not None
        assert client.post(
            f"{API}/campaigns/{campaign_id}/stop", headers=admin_headers
        ).status_code == 400
    finally:
        _set_campaign_status(campaign_id, models.CampaignStatus.DRAFT)
        _delete_campaign(client, admin_headers, campaign_id)


# ========== ОТЧЁТ / ЭКСПОРТ ==========
def test_report_and_export_after_sending(client, admin_headers, smtp_mock, monkeypatch):
    monkeypatch.setattr(campaign_worker, "start_worker", lambda: False)
    monkeypatch.setattr(campaign_worker, "_sleep", lambda seconds: None)
    template_id = _template(client, admin_headers, title="QA MM report")
    campaign_id = _create_campaign(
        client, admin_headers, template_id, title="QA report"
    ).json()["id"]
    try:
        _import_default_recipients(client, admin_headers, campaign_id)
        started = client.post(
            f"{API}/campaigns/{campaign_id}/start", headers=admin_headers,
            json={"consent": True},
        )
        assert started.status_code == 200, started.text
        outcome = campaign_worker.run_campaign_loop(campaign_id)
        assert outcome == "completed"

        report = client.get(
            f"{API}/campaigns/{campaign_id}/report", headers=admin_headers
        )
        assert report.status_code == 200, report.text
        body = report.json()
        assert body["campaign"]["status"] == "completed"
        assert body["counts"]["sent"] == 2
        assert body["counts"]["failed"] == 0
        assert body["by_status"]["sent"] == 2
        assert body["errors"] == []

        exported = client.get(
            f"{API}/campaigns/{campaign_id}/export", headers=admin_headers
        )
        assert exported.status_code == 200
        text = exported.text
        assert text.startswith("\ufeff")
        assert "email;greeting;status;attempts;error;sent_at" in text
        assert "client1@example.ru" in text
        assert ";sent;" in text
    finally:
        _set_campaign_status(campaign_id, models.CampaignStatus.DRAFT)
        _delete_campaign(client, admin_headers, campaign_id)


# ========== СТОП-ЛИСТ ==========
def test_unsubscribes_admin_only_and_crud(client, admin_headers, regular_headers):
    assert client.get(f"{API}/unsubscribes", headers=regular_headers).status_code == 403
    assert client.post(
        f"{API}/unsubscribes", headers=regular_headers,
        json={"email": "spam@example.ru"},
    ).status_code == 403

    created = client.post(
        f"{API}/unsubscribes", headers=admin_headers,
        json={"email": "Unsub-QA@Example.RU", "reason": "жалоба"},
    )
    assert created.status_code == 200, created.text
    record = created.json()
    assert record["normalized_email"] == "unsub-qa@example.ru"
    assert record["source"] == "manual"
    assert record["reason"] == "жалоба"

    again = client.post(
        f"{API}/unsubscribes", headers=admin_headers,
        json={"email": "unsub-qa@example.ru"},
    )
    assert again.status_code == 200
    assert again.json()["id"] == record["id"], "повторное добавление не должно плодить дубликаты"

    listed = client.get(
        f"{API}/unsubscribes?search=unsub-qa", headers=admin_headers
    ).json()
    assert any(item["id"] == record["id"] for item in listed)

    assert client.delete(
        f"{API}/unsubscribes/{record['id']}", headers=admin_headers
    ).status_code == 200
    assert client.delete(
        f"{API}/unsubscribes/{record['id']}", headers=admin_headers
    ).status_code == 404


# ========== ДНЕВНАЯ КВОТА ==========
def test_quota_counts_single_and_mass_sends(client, admin_headers, smtp_mock, reset_quota):
    quota = client.get(f"{API}/email/quota", headers=admin_headers).json()
    assert quota["used_today"] == 0
    assert quota["remaining"] == quota["limit"]

    template_id = _template(client, admin_headers, title="QA MM quota")
    single = client.post(
        f"{API}/email/send", headers=admin_headers,
        json={
            "sender_email": "sales@ast-qa.ru",
            "recipient_email": "quota-client@example.ru",
            "greeting": "Иван",
            "template_id": template_id,
        },
    )
    assert single.status_code == 200, single.text
    assert client.get(f"{API}/email/quota", headers=admin_headers).json()["used_today"] == 1

    campaign_id = _create_campaign(
        client, admin_headers, template_id, title="QA quota campaign"
    ).json()["id"]
    try:
        _import_default_recipients(client, admin_headers, campaign_id)
        assert client.post(
            f"{API}/campaigns/{campaign_id}/test-send", headers=admin_headers
        ).status_code == 200
        quota = client.get(f"{API}/email/quota", headers=admin_headers).json()
        assert quota["used_today"] == 2
        assert quota["remaining"] == quota["limit"] - 2
    finally:
        _delete_campaign(client, admin_headers, campaign_id)



