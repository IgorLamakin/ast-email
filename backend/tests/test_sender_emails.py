# -*- coding: utf-8 -*-
"""Тесты истории адресов отправителя (2.6.0).

Покрывают контракт:
- GET /sender-emails для чистого пользователя отдаёт [];
- успешная отправка письма (POST /email/send) автоматически запоминает адрес;
- повторная отправка увеличивает use_count, список отсортирован по last_used_at;
- POST /sender-emails делает upsert;
- DELETE /sender-emails/{id} удаляет только свою запись, чужую - 404;
- валидационные отказы (SMTP не настроен, шаблон не найден) адрес НЕ запоминают.

SMTP не поднимаем: get_smtp_settings подменяется, а _send_via_smtp - заглушкой,
поэтому в сеть ничего не уходит (как в существующем
test_analytics_counts_only_successful_sends).
"""
import pytest
from fastapi.testclient import TestClient

import main

API = "/api"
PASSWORD = "SenderPass123"
EMAIL_A = "sender-history-a@ast-qa.ru"
EMAIL_B = "sender-history-b@ast-qa.ru"


@pytest.fixture(scope="session")
def client():
    with TestClient(main.root_app) as test_client:
        yield test_client


def _register(client, email: str) -> str:
    response = client.post(
        f"{API}/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "QA Sender History"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture(scope="session")
def user_a_headers(client):
    return {"Authorization": f"Bearer {_register(client, EMAIL_A)}"}


@pytest.fixture(scope="session")
def user_b_headers(client):
    return {"Authorization": f"Bearer {_register(client, EMAIL_B)}"}


@pytest.fixture(scope="session")
def template_id(client, user_a_headers):
    """Свой шаблон, чтобы тесты не зависели от стандартных."""
    response = client.post(
        f"{API}/templates",
        headers=user_a_headers,
        json={"title": "QA sender history", "html_content": "<p>Привет, {{ greeting }}</p>"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


@pytest.fixture
def smtp_configured(monkeypatch):
    """«SMTP настроен»: возвращаем конфиг и глушим реальную отправку."""
    monkeypatch.setattr(main, "get_smtp_settings", lambda db: {
        "host": "smtp.ast-qa.ru",
        "port": 465,
        "user": "robot@ast-qa.ru",
        "password": "SuperSecret",
        "from": "robot@ast-qa.ru",
    })
    monkeypatch.setattr(main, "_send_via_smtp", lambda *args, **kwargs: None)


def _emails(client, headers) -> list:
    response = client.get(f"{API}/sender-emails", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _send(client, headers, template_id, sender_email, recipient_email="client@client-qa.ru"):
    return client.post(
        f"{API}/email/send",
        headers=headers,
        json={
            "sender_email": sender_email,
            "recipient_email": recipient_email,
            "greeting": "Иван",
            "template_id": template_id,
        },
    )


def test_sender_emails_requires_auth(client):
    response = client.get(f"{API}/sender-emails")
    assert response.status_code == 401


def test_sender_emails_empty_for_new_user(client, user_b_headers):
    """У нового пользователя истории нет - пустой список, а не ошибка/404."""
    response = client.get(f"{API}/sender-emails", headers=user_b_headers)
    assert response.status_code == 200, response.text
    assert response.json() == []


def test_send_remembers_sender_address(client, user_a_headers, template_id, smtp_configured):
    sender = "history-once@ast-qa.ru"
    response = _send(client, user_a_headers, template_id, sender)
    assert response.status_code == 200, response.text

    records = _emails(client, user_a_headers)
    record = next((r for r in records if r["email"] == sender), None)
    assert record is not None, records
    assert record["use_count"] == 1
    assert record["last_used_at"]


def test_repeated_send_increments_use_count_and_sorts(client, user_a_headers, template_id, smtp_configured):
    first_addr = "history-first@ast-qa.ru"
    second_addr = "history-second@ast-qa.ru"

    assert _send(client, user_a_headers, template_id, first_addr).status_code == 200
    assert _send(client, user_a_headers, template_id, second_addr).status_code == 200
    # Повторная отправка с первого адреса - он должен «подняться» наверх.
    assert _send(client, user_a_headers, template_id, first_addr).status_code == 200

    records = _emails(client, user_a_headers)
    by_email = {r["email"]: r for r in records}
    assert by_email[first_addr]["use_count"] == 2
    assert by_email[second_addr]["use_count"] == 1
    assert records.index(by_email[first_addr]) < records.index(by_email[second_addr])

    # Сортировка по last_used_at desc (ISO-строки одного формата сравнимы лексикографически).
    timestamps = [r["last_used_at"] for r in records]
    assert timestamps == sorted(timestamps, reverse=True)


def test_post_sender_email_upserts(client, user_a_headers):
    email = "manual-upsert@ast-qa.ru"
    first = client.post(f"{API}/sender-emails", headers=user_a_headers, json={"email": email})
    assert first.status_code == 200, first.text
    created = first.json()
    assert created["email"] == email
    assert created["use_count"] == 1

    second = client.post(f"{API}/sender-emails", headers=user_a_headers, json={"email": email})
    assert second.status_code == 200, second.text
    assert second.json()["id"] == created["id"], "upsert создал дубликат вместо обновления"
    assert second.json()["use_count"] == 2


def test_other_user_cannot_see_or_delete(client, user_a_headers, user_b_headers):
    """История у каждого своя: чужой пользователь её не видит и не удаляет."""
    a_records = _emails(client, user_a_headers)
    assert a_records, "у user_a должна быть история из предыдущих тестов"
    # user_b ничего не отправлял - его история пуста, записи user_a в неё не попадают.
    assert _emails(client, user_b_headers) == []

    victim_id = a_records[0]["id"]
    forbidden = client.delete(f"{API}/sender-emails/{victim_id}", headers=user_b_headers)
    assert forbidden.status_code == 404, forbidden.text

    # Чужая попытка удаления запись не тронула.
    assert any(r["id"] == victim_id for r in _emails(client, user_a_headers))


def test_delete_own_sender_email(client, user_a_headers):
    email = "delete-me@ast-qa.ru"
    created = client.post(f"{API}/sender-emails", headers=user_a_headers, json={"email": email}).json()

    response = client.delete(f"{API}/sender-emails/{created['id']}", headers=user_a_headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"message": "Sender email deleted"}
    assert all(r["id"] != created["id"] for r in _emails(client, user_a_headers))

    # Повторное удаление уже удалённой записи - 404.
    again = client.delete(f"{API}/sender-emails/{created['id']}", headers=user_a_headers)
    assert again.status_code == 404


def test_send_without_smtp_does_not_remember(client, user_a_headers, template_id, monkeypatch):
    """Валидационный отказ (SMTP не настроен) не должен попадать в историю."""
    sender = "no-smtp@ast-qa.ru"
    monkeypatch.setattr(main, "get_smtp_settings", lambda db: None)

    response = _send(client, user_a_headers, template_id, sender)
    assert response.status_code == 400, response.text
    assert all(r["email"] != sender for r in _emails(client, user_a_headers))


def test_send_with_missing_template_does_not_remember(client, user_a_headers, template_id, smtp_configured):
    """Шаблон не найден (404) - адрес тоже не запоминаем."""
    sender = "no-template@ast-qa.ru"
    response = _send(client, user_a_headers, 999999, sender)
    assert response.status_code == 404, response.text
    assert all(r["email"] != sender for r in _emails(client, user_a_headers))


def test_failed_smtp_still_remembers_address(client, user_a_headers, template_id, monkeypatch):
    """Ошибка SMTP (500) - адрес всё равно запоминается: человек им пользуется."""
    import smtplib

    sender = "smtp-error@ast-qa.ru"
    monkeypatch.setattr(main, "get_smtp_settings", lambda db: {
        "host": "smtp.ast-qa.ru",
        "port": 465,
        "user": "robot@ast-qa.ru",
        "password": "SuperSecret",
        "from": "robot@ast-qa.ru",
    })

    def fail_smtp(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    monkeypatch.setattr(main, "_send_via_smtp", fail_smtp)
    response = _send(client, user_a_headers, template_id, sender)
    assert response.status_code == 500, response.text
    assert any(r["email"] == sender for r in _emails(client, user_a_headers))
