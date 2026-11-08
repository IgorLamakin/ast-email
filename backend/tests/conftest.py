# -*- coding: utf-8 -*-
"""Общая настройка pytest для регрессионных тестов бэкенда.

Переменные окружения должны быть выставлены ДО импорта main.py, иначе
приложение откроет рабочую БД пользователя вместо временной.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

_TMP_DIR = Path(tempfile.mkdtemp(prefix="ast-email-tests-"))
(_TMP_DIR / "uploads").mkdir(parents=True, exist_ok=True)
(_TMP_DIR / "appdata").mkdir(parents=True, exist_ok=True)

os.environ.update({
    "APP_DB_PATH": str(_TMP_DIR / "test.db"),
    "APP_UPLOAD_DIR": str(_TMP_DIR / "uploads"),
    "APPDATA": str(_TMP_DIR / "appdata"),
    "SECRET_KEY": "pytest-secret-key",
    "SMTP_HOST": "",
    "SMTP_PORT": "587",
    "SMTP_USER": "",
    "SMTP_PASSWORD": "",
    "SMTP_FROM": "",
})


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP_DIR, ignore_errors=True)
