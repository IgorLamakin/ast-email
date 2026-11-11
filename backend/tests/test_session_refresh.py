# -*- coding: utf-8 -*-
"""Тесты сессии «запомнить вход» (refresh-токены) для версии 2.6.0.

Покрывают контракт:
- /auth/register и /auth/login отдают полную пару (access + refresh + expires_in);
- /auth/refresh меняет refresh-токен на новую пару и ротирует старый (одноразовость);
- просроченный/неизвестный/отозванный refresh-токен получает 401;
- /auth/logout отзывает токен и идемпотентен;
- в базе лежит только SHA-256-хеш refresh-токена, самого токена там нет.

ПОЧЕМУ ФАЙЛ НАЗЫВАЕТСЯ test_session_refresh.py, а не test_auth_refresh.py:
pytest собирает файлы в алфавитном порядке, и test_auth_refresh.py выполнялся бы
ДО существующего test_regressions.py. Тот рассчитывает, что самый первый
зарегистрированный в сессии пользователь становится администратором (и только
после этого появляются 6 стандартных шаблонов), поэтому регистрация чужого
пользователя раньше времени сломала бы 6 существующих тестов. Имя выбрано так,
чтобы новый файл шёл после test_regressions.py.
"""
import hashlib
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import main
import models
from database import SessionLocal

API = "/api"
EMAIL = "refresh-qa@ast-qa.ru"
PASSWORD = "RefreshPass123"


@pytest.fixture(scope="session")
def client():
    with TestClient(main.root_app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def session_user(client):
    """Единственный пользователь этого модуля: регистрируемся через API один раз."""
    response = client.post(
        f"{API}/auth/register",
        json={"email": EMAIL, "password": PASSWORD, "full_name": "QA Refresh"},
    )
    assert response.status_code == 200, response.text
    tokens = response.json()
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200, me.text
    return {"tokens": tokens, "user": me.json()}


def _login(client) -> dict:
    response = client.post(
        f"{API}/auth/login",
        data={"username": EMAIL, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _refresh(client, refresh_token: str):
    return client.post(f"{API}/auth/refresh", json={"refresh_token": refresh_token})


def test_register_returns_full_token_pair(client, session_user):
    """Регистрация должна сразу отдавать refresh-токен - иначе «запомнить вход»
    не работает для только что созданного аккаунта."""
    tokens = session_user["tokens"]
    assert tokens["token_type"] == "bearer"
    assert tokens["access_token"]
    assert tokens["refresh_token"]
    assert tokens["expires_in"] == main.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def test_login_returns_full_token_pair(client, session_user):
    tokens = _login(client)
    assert tokens["access_token"]
    assert tokens["refresh_token"]
    assert tokens["expires_in"] == main.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    # access-токен по-прежнему рабочий (семантика get_current_user не изменилась)
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200, me.text
    assert me.json()["email"] == EMAIL


def test_refresh_rotates_token(client, session_user):
    """Обмен refresh-токена: новая пара, новый access работает, старый - 401."""
    tokens = _login(client)
    response = _refresh(client, tokens["refresh_token"])
    assert response.status_code == 200, response.text
    new_tokens = response.json()

    assert new_tokens["refresh_token"] != tokens["refresh_token"]
    assert new_tokens["access_token"]
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {new_tokens['access_token']}"})
    assert me.status_code == 200, me.text

    # Ротация: старый refresh-токен одноразовый и больше не принимается.
    stale = _refresh(client, tokens["refresh_token"])
    assert stale.status_code == 401, stale.text
    assert stale.json()["detail"] == "Invalid refresh token"

    # Новый refresh тоже рабочий (и тоже станет одноразовым при следующем обмене).
    again = _refresh(client, new_tokens["refresh_token"])
    assert again.status_code == 200, again.text


def test_expired_refresh_token_rejected(client, session_user):
    """Просроченный refresh-токен не должен давать новую пару."""
    db = SessionLocal()
    try:
        expired_pair = main._issue_token_pair(
            db, session_user["user"]["id"], expires_delta=-timedelta(days=1)
        )
    finally:
        db.close()

    response = _refresh(client, expired_pair["refresh_token"])
    assert response.status_code == 401, response.text
    assert response.json()["detail"] == "Invalid refresh token"


def test_logout_revokes_and_is_idempotent(client, session_user):
    """logout отзывает токен; повторный logout (и logout неизвестного токена) - 200."""
    tokens = _login(client)

    first = client.post(f"{API}/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert first.status_code == 200, first.text
    assert first.json() == {"message": "Logged out"}

    # После выхода обменять токен нельзя.
    assert _refresh(client, tokens["refresh_token"]).status_code == 401

    # Идемпотентность: повторный выход - тот же 200, а не 401/500.
    second = client.post(f"{API}/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert second.status_code == 200, second.text
    assert second.json() == {"message": "Logged out"}

    unknown = client.post(f"{API}/auth/logout", json={"refresh_token": "nonsense-token"})
    assert unknown.status_code == 200, unknown.text


def test_refresh_token_is_stored_hashed(client, session_user):
    """В базе должен лежать хеш refresh-токена, а не он сам."""
    tokens = _login(client)
    raw = tokens["refresh_token"]
    db = SessionLocal()
    try:
        row = db.query(models.RefreshToken).filter(
            models.RefreshToken.token_hash == hashlib.sha256(raw.encode("utf-8")).hexdigest()
        ).first()
        assert row is not None, "refresh-токен не сохранён по хешу"
        assert row.user_id == session_user["user"]["id"]
        assert row.revoked_at is None
        assert row.last_used_at is None
        # Срок жизни - REFRESH_TOKEN_EXPIRE_DAYS от создания.
        lifetime = row.expires_at - row.created_at
        assert timedelta(days=main.REFRESH_TOKEN_EXPIRE_DAYS - 1) < lifetime <= timedelta(days=main.REFRESH_TOKEN_EXPIRE_DAYS)

        # Строка «сырого» токена в базе не встречается.
        as_is = db.query(models.RefreshToken).filter(
            models.RefreshToken.token_hash == raw
        ).first()
        assert as_is is None
    finally:
        db.close()


def test_refresh_token_is_not_a_jwt(client, session_user):
    """refresh-токен - случайная строка, а не JWT: подделать подписью нельзя."""
    tokens = _login(client)
    # У JWT всегда три сегмента, разделённые точкой.
    assert len(tokens["refresh_token"].split(".")) != 3


def test_me_with_invalid_access_token_still_401(client):
    """Семантика /auth/me не изменилась: невалидный access - 401."""
    response = client.get(f"{API}/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401
