# -*- coding: utf-8 -*-
"""Регрессионные тесты для критичных дефектов версии 2.5.x.

Покрывают:
- сохранение загруженного файла на диск (P0 в 2.5.0/2.5.1);
- отсутствие дубликатов стандартных шаблонов после unpublish/rename;
- счётчик «отправлено» не учитывает неудачные попытки.
"""
import base64
import os
import smtplib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main

API = "/api"

ADMIN_EMAIL = "admin@ast-qa.ru"
ADMIN_PASSWORD = "AdminPass123"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@pytest.fixture(scope="session")
def client():
    with TestClient(main.root_app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def admin_token(client):
    response = client.post(
        f"{API}/auth/register",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "full_name": "QA Admin"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _templates(client, headers):
    response = client.get(f"{API}/templates", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_upload_persists_file_bytes(client, auth_headers):
    """P0: загруженный файл должен иметь тот же размер, что и отправленный."""
    response = client.post(
        f"{API}/upload",
        headers=auth_headers,
        files={"file": ("pic.png", PNG, "image/png")},
    )
    assert response.status_code == 200, response.text
    url = response.json()["url"]
    filename = url.rsplit("/", 1)[-1]

    disk_path = Path(os.environ["APP_UPLOAD_DIR"]) / filename
    assert disk_path.exists()
    assert disk_path.stat().st_size == len(PNG)
    assert disk_path.read_bytes() == PNG

    served = client.get(f"{API}{url}")
    assert served.status_code == 200
    assert served.content == PNG


def test_upload_rejects_executable(client, auth_headers):
    response = client.post(
        f"{API}/upload",
        headers=auth_headers,
        files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
    )
    assert response.status_code == 400, response.text


def test_unpublished_standard_template_is_not_duplicated(client, auth_headers):
    """P1: снятый с публикации стандартный шаблон не должен воскресать копией."""
    templates = _templates(client, auth_headers)
    assert len(templates) == 6, templates
    seed = templates[0]

    response = client.post(f"{API}/templates/{seed['id']}/unpublish", headers=auth_headers)
    assert response.status_code == 200, response.text

    main.auto_seed_templates()

    same_title = [t for t in _templates(client, auth_headers) if t["title"] == seed["title"]]
    assert len(same_title) == 1, f"дубликат стандартного шаблона: {same_title}"
    assert same_title[0]["status"] == "draft"


def test_renamed_standard_template_is_not_recreated(client, auth_headers):
    """P1: переименованный стандартный шаблон не должен создаваться заново."""
    templates = _templates(client, auth_headers)
    seed = next(t for t in templates if t["status"] == "published")
    old_title = seed["title"]
    new_title = "Переименованный стандартный шаблон (QA)"
    total_before = len(templates)

    response = client.put(
        f"{API}/templates/{seed['id']}",
        headers=auth_headers,
        json={"title": new_title},
    )
    assert response.status_code == 200, response.text

    main.auto_seed_templates()

    after = _templates(client, auth_headers)
    assert len(after) == total_before, after
    assert not any(t["title"] == old_title for t in after), after


def test_presentation_template_renders_profile_data(client, auth_headers):
    """Новый шаблон «Презентация компании» есть в БД и подставляет контакты."""
    templates = _templates(client, auth_headers)
    titles = [t["title"] for t in templates]
    assert "АСТ — Презентация компании" in titles, titles
    template = next(t for t in templates if t["title"] == "АСТ — Презентация компании")

    me = client.get(f"{API}/auth/me", headers=auth_headers).json()
    profile = {
        "full_name": "Иванов Иван Иванович",
        "position": "Руководитель отдела продаж",
        "company": "ООО «АСТ»",
        "phone": "+7 (927) 101-28-16",
        "address": "350901, Россия, Краснодарский край, г. Краснодар, ул. Российская, 208/1",
        "website": "astkip.ru",
    }
    response = client.put(f"{API}/users/{me['id']}", headers=auth_headers, json=profile)
    assert response.status_code == 200, response.text

    preview = client.post(
        f"{API}/templates/{template['id']}/preview",
        headers=auth_headers,
        json={
            "sender_email": "sender@ast-qa.ru",
            "recipient_email": "client@client-qa.ru",
            "greeting": "Уважаемый Иван Иванович!",
            "template_id": template["id"],
        },
    )
    assert preview.status_code == 200, preview.text
    html = preview.json()["html_preview"]
    assert "{{" not in html, "в письме остались неподставленные плейсхолдеры"
    for value in ("Иванов Иван Иванович", "Руководитель отдела продаж", "ООО «АСТ»",
                  "+7 (927) 101-28-16", "350901", "https://astkip.ru",
                  "sender@ast-qa.ru", "Уважаемый Иван Иванович!"):
        assert value in html, value
    assert "localhost" not in html
    assert "raw.githubusercontent.com" in html
    for label in ("Скачать реквизиты", "Скачать презентацию",
                  "Получить консультацию", "Запросить коммерческое предложение",
                  "Отправить заявку", "Перейти на сайт"):
        assert label in html, label
    assert "releases/download/v2.5.4/AST-Requisites.docx" in html
    assert "releases/download/v2.5.4/AST-Presentation.pdf" in html
    assert "mailto:sender@ast-qa.ru" in html
    assert "tel:+7 (927) 101-28-16" in html
    assert 'href="#"' not in html
    assert ">Позвонить<" not in html


def test_analytics_counts_only_successful_sends(client, auth_headers, monkeypatch):
    """P2: total_sent/emails_sent_count не должны учитывать not_sent."""
    settings = {
        "smtp_host": "smtp.ast-qa.ru",
        "smtp_port": 465,
        "smtp_user": "robot@ast-qa.ru",
        "smtp_password": "SuperSecret",
        "smtp_from": "sales@ast-qa.ru",
    }
    response = client.post(f"{API}/settings", headers=auth_headers, json=settings)
    assert response.status_code == 200, response.text

    template = client.post(
        f"{API}/templates",
        headers=auth_headers,
        json={"title": "QA send test", "html_content": "<p>Hi {{ greeting }}</p>"},
    )
    assert template.status_code == 200, template.text
    template_id = template.json()["id"]

    before = client.get(f"{API}/analytics", headers=auth_headers).json()["total_sent"]

    def fail_smtp(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    monkeypatch.setattr(main, "_send_via_smtp", fail_smtp)
    payload = {
        "sender_email": "admin@ast-qa.ru",
        "recipient_email": "client@client-qa.ru",
        "greeting": "Иван",
        "template_id": template_id,
    }
    failed = client.post(f"{API}/email/send", headers=auth_headers, json=payload)
    assert failed.status_code == 500, failed.text

    after_fail = client.get(f"{API}/analytics", headers=auth_headers).json()["total_sent"]
    assert after_fail == before, "неудачная отправка попала в total_sent"

    monkeypatch.setattr(main, "_send_via_smtp", lambda *args, **kwargs: None)
    sent = client.post(f"{API}/email/send", headers=auth_headers, json=payload)
    assert sent.status_code == 200, sent.text

    after_ok = client.get(f"{API}/analytics", headers=auth_headers).json()["total_sent"]
    assert after_ok == before + 1

    accounts = client.get(f"{API}/admin/accounts", headers=auth_headers)
    assert accounts.status_code == 200, accounts.text
    admin_account = next(a for a in accounts.json()["accounts"] if a["email"] == ADMIN_EMAIL)
    assert admin_account["emails_sent_count"] == after_ok
