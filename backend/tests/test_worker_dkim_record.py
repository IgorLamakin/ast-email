# -*- coding: utf-8 -*-
"""Проверка DKIM-записей в preflight массовой рассылки (2.7.0).

Отдельный файл (а не часть test_worker_campaign_api.py), чтобы правку можно было
проверить без поднятия всего API. Имя test_worker_* сохраняет алфавитный порядок
pytest: test_regressions.py обязан идти первым (первый пользователь = админ).
"""
import campaigns
import main  # noqa: F401  (создаёт таблицы/миграции на временной БД из conftest)


VALID_KEY = "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC7"  # условный публичный ключ


def test_real_dkim_record_is_valid():
    assert campaigns.is_valid_dkim_record("v=DKIM1; k=rsa; p=" + VALID_KEY)
    assert campaigns.is_valid_dkim_record("v=DKIM1; p=" + VALID_KEY + "; s=email")
    # Яндекс/почтовики иногда отдают значение в кавычках и с пробелами
    assert campaigns.is_valid_dkim_record("  v=DKIM1; p=" + VALID_KEY + "  ")
    assert campaigns.is_valid_dkim_record('"v=DKIM1; p=' + VALID_KEY + '"')


def test_empty_key_is_not_valid():
    # Главный баг: wildcard-запись с пустым ключом выдавала «DKIM найден»
    assert not campaigns.is_valid_dkim_record("v=DKIM1; p=")
    assert not campaigns.is_valid_dkim_record("v=DKIM1; p=;")
    assert not campaigns.is_valid_dkim_record("v=DKIM1; k=rsa")


def test_ip_and_other_txt_are_not_dkim():
    assert not campaigns.is_valid_dkim_record("")
    assert not campaigns.is_valid_dkim_record(None)
    assert not campaigns.is_valid_dkim_record("v=spf1 include:_spf.yandex.ru ~all")
    assert not campaigns.is_valid_dkim_record("some random txt value")
    assert not campaigns.is_valid_dkim_record("v=DMARC1; p=none")


def test_short_placeholder_key_rejected():
    # «p=abc» - не публичный ключ, а заглушка
    assert not campaigns.is_valid_dkim_record("v=DKIM1; p=abc")
