# -*- coding: utf-8 -*-
"""Тесты импорта получателей массовой рассылки (2.7.0).

Файл называется test_worker_importer.py, а не test_importer.py, специально:
pytest собирает файлы по алфавиту, а существующий test_regressions.py должен
выполняться первым (он рассчитывает, что первый зарегистрированный пользователь
станет администратором). Все новые файлы 2.7.0 названы test_worker_*, чтобы
идти после старых.

Файлы создаются реально: .xlsx - через openpyxl, .csv - через csv, .xls -
готовый бинарный фикстур (xlrd 2.x умеет только читать .xls, записывать не может).
"""
import csv
import os

import openpyxl
import pytest

import importer
import models
from database import SessionLocal

# Импорт main создаёт таблицы и применяет миграции к временной БД из conftest.
# Нужен, когда файл запускают отдельно (в полном прогоне main уже импортирован).
import main  # noqa: F401

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
XLS_FIXTURE = os.path.join(FIXTURES_DIR, "recipients.xls")

HEADER = ["E-mail", "Обращение", "Компания", "Должность", "Город"]
DATA = [
    ["a@example.ru", "Иван", "ООО «АСТ»", "Директор", "Краснодар"],
    ["A@Example.RU", "Дубль", "", "", ""],
    ["b@example.ru", "", "Ромашка", "Бухгалтер", "Сочи"],
    ["мусор", "", "", "", ""],
]


def _write_csv(directory, name, rows, encoding="utf-8-sig", delimiter=";"):
    path = os.path.join(str(directory), name)
    with open(path, "w", encoding=encoding, newline="") as target:
        writer = csv.writer(target, delimiter=delimiter)
        for row in rows:
            writer.writerow(row)
    return path


def test_normalize_email():
    """Нормализация: обрезка, lowercase домена, IDN, отсев мусора и списков."""
    assert importer.normalize_email("  User@Example.RU ") == "user@example.ru"
    # email_validator нормализует IDN-домен в Unicode-форму (пример.рф).
    assert importer.normalize_email("user@ПРИМЕР.РФ") == "user@пример.рф"
    assert importer.normalize_email("нет email") is None
    assert importer.normalize_email("a@b.ru; c@d.ru") is None
    assert importer.normalize_email("a@b.ru, c@d.ru") is None
    assert importer.normalize_email("") is None
    assert importer.normalize_email(None) is None


def test_parse_csv_detects_columns_and_counts(tmp_path):
    path = _write_csv(tmp_path, "recipients.csv", [HEADER] + DATA)
    result = importer.parse_recipients_file(path, ".csv", "recipients.csv")

    assert result["columns"][0] == "E-mail"
    assert result["mapping"]["email"] == "E-mail"
    assert result["mapping"]["greeting"] == "Обращение"
    assert result["mapping"]["company"] == "Компания"
    assert result["mapping"]["position"] == "Должность"
    assert result["mapping"]["extra"] == ["Город"]

    assert result["counts"] == {
        "total": 4, "valid": 2, "duplicates": 1, "invalid": 1, "unsubscribed": 0,
    }
    assert [row["status"] for row in result["preview"]] == [
        "ok", "duplicate", "ok", "invalid",
    ]
    # В превью номер строки - «человеческий» номер строки файла (заголовок = 1).
    assert [row["row"] for row in result["preview"]] == [2, 3, 4, 5]

    assert len(result["recipients"]) == 2
    first = result["recipients"][0]
    assert first["email"] == "a@example.ru"
    assert first["normalized_email"] == "a@example.ru"
    assert first["greeting"] == "Иван"
    assert first["fields"]["company"] == "ООО «АСТ»"
    assert first["fields"]["position"] == "Директор"
    assert first["fields"]["field_1"] == "Краснодар"
    assert first["status"] == "pending"


def test_parse_csv_cp1251(tmp_path):
    """Типичная выгрузка из 1С/русского Excel в cp1251."""
    path = _write_csv(tmp_path, "cp1251.csv", [HEADER] + DATA[:1], encoding="cp1251")
    result = importer.parse_recipients_file(path, ".csv", "cp1251.csv")
    assert result["mapping"]["email"] == "E-mail"
    assert result["recipients"][0]["greeting"] == "Иван"
    assert result["recipients"][0]["fields"]["company"] == "ООО «АСТ»"
    assert result["counts"]["valid"] == 1


def test_parse_csv_utf16_bom(tmp_path):
    path = _write_csv(tmp_path, "utf16.csv", [HEADER] + DATA[:1], encoding="utf-16")
    result = importer.parse_recipients_file(path, ".csv", "utf16.csv")
    assert result["mapping"]["email"] == "E-mail"
    assert result["counts"]["valid"] == 1


def test_parse_xlsx(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in [HEADER] + DATA:
        sheet.append(row)
    path = os.path.join(str(tmp_path), "recipients.xlsx")
    workbook.save(path)
    result = importer.parse_recipients_file(path, ".xlsx", "recipients.xlsx")
    assert result["mapping"]["email"] == "E-mail"
    assert result["mapping"]["greeting"] == "Обращение"
    assert result["counts"]["total"] == 4
    assert result["counts"]["valid"] == 2
    assert result["counts"]["duplicates"] == 1
    assert result["counts"]["invalid"] == 1


def test_parse_xls_legacy_fixture():
    """Реальный .xls (BIFF): читается через xlrd 2.x."""
    assert os.path.exists(XLS_FIXTURE), "нет фикстуры backend/tests/fixtures/recipients.xls"
    result = importer.parse_recipients_file(XLS_FIXTURE, ".xls", "recipients.xls")
    assert result["mapping"]["email"] == "E-mail"
    assert result["mapping"]["company"] == "Компания"
    assert result["counts"]["total"] == 3
    assert result["counts"]["valid"] == 2
    assert result["counts"]["invalid"] == 1
    assert result["recipients"][0]["email"] == "xls-first@example.ru"
    assert result["recipients"][1]["email"].lower() == "xls-second@example.ru"
    assert result["recipients"][0]["greeting"] == "Иван Иванович"


def test_email_column_found_by_valid_ratio(tmp_path):
    """Если заголовки незнакомые - колонка email ищется по доле валидных адресов."""
    path = _write_csv(tmp_path, "unnamed.csv", [
        ["col1", "col2", "col3"],
        ["Иван", "a@example.ru", "Краснодар"],
        ["Пётр", "b@example.ru", "Сочи"],
        ["Анна", "c@example.ru", "Анапа"],
    ])
    result = importer.parse_recipients_file(path, ".csv", "unnamed.csv")
    assert result["mapping"]["email"] == "col2"
    assert result["counts"]["valid"] == 3
    # Остальные колонки уходят в доп. поля (field_1, field_2).
    assert result["recipients"][0]["fields"]["field_1"] == "Иван"
    assert result["recipients"][0]["fields"]["field_2"] == "Краснодар"


def test_no_email_column_returns_mapping_none(tmp_path):
    path = _write_csv(tmp_path, "no-email.csv", [
        ["Имя", "Город"],
        ["Иван", "Краснодар"],
        ["Пётр", "Сочи"],
    ])
    result = importer.parse_recipients_file(path, ".csv", "no-email.csv")
    assert result["mapping"]["email"] is None
    assert result["recipients"] == []
    assert result["preview"] == []
    assert result["counts"]["total"] == 2


def test_stop_list_marks_unsubscribed(tmp_path):
    """Адреса из стоп-листа не попадают в очередь (status=skipped)."""
    blocked = "blocked-mm@example.ru"
    session = SessionLocal()
    try:
        if session.query(models.Unsubscribe).filter(
            models.Unsubscribe.normalized_email == blocked
        ).first() is None:
            session.add(models.Unsubscribe(
                normalized_email=blocked, email_raw=blocked, source="manual",
            ))
            session.commit()
    finally:
        session.close()

    path = _write_csv(tmp_path, "stop.csv", [
        ["E-mail"],
        [blocked],
        ["free-mm@example.ru"],
    ])
    result = importer.parse_recipients_file(path, ".csv", "stop.csv")
    assert result["counts"]["valid"] == 1
    assert result["counts"]["unsubscribed"] == 1
    statuses = {(item["email"], item["status"]) for item in result["recipients"]}
    assert (blocked, "skipped") in statuses
    assert ("free-mm@example.ru", "pending") in statuses
    assert [row["status"] for row in result["preview"]] == ["unsubscribed", "ok"]


def test_max_rows_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "MAX_ROWS", 2)
    path = _write_csv(tmp_path, "big.csv", [
        ["E-mail"],
        ["a@example.ru"],
        ["b@example.ru"],
        ["c@example.ru"],
    ])
    with pytest.raises(importer.ImportFileError) as excinfo:
        importer.parse_recipients_file(path, ".csv", "big.csv")
    assert "строк" in str(excinfo.value)


def test_max_file_size_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "MAX_FILE_BYTES", 10)
    path = os.path.join(str(tmp_path), "huge.csv")
    with open(path, "w", encoding="utf-8") as target:
        target.write("E-mail\n" + "a@example.ru\n" * 10)
    with pytest.raises(importer.ImportFileError) as excinfo:
        importer.parse_recipients_file(path, ".csv", "huge.csv")
    assert "большой" in str(excinfo.value)


def test_unsupported_extension(tmp_path):
    path = os.path.join(str(tmp_path), "file.pdf")
    with open(path, "wb") as target:
        target.write(b"%PDF-1.4")
    with pytest.raises(importer.ImportFileError):
        importer.read_table(path)


def test_explicit_mapping_overrides_auto_detection(tmp_path):
    """Явное сопоставление колонок (используется в /import/remap)."""
    path = _write_csv(tmp_path, "explicit.csv", [
        ["Почта", "Контакт", "Город"],
        ["a@example.ru", "Иван", "Краснодар"],
    ])
    result = importer.parse_recipients_file(
        path, ".csv", "explicit.csv",
        mapping={"email": "Почта", "name": "Контакт", "extra": ["Город"]},
    )
    assert result["mapping"]["email"] == "Почта"
    assert result["mapping"]["name"] == "Контакт"
    assert result["mapping"]["greeting"] is None
    item = result["recipients"][0]
    assert item["greeting"] is None
    assert item["fields"]["name"] == "Иван"
    assert item["fields"]["field_1"] == "Краснодар"


def test_explicit_mapping_unknown_column_raises(tmp_path):
    path = _write_csv(tmp_path, "bad-mapping.csv", [["E-mail"], ["a@example.ru"]])
    with pytest.raises(importer.ImportFileError):
        importer.parse_recipients_file(
            path, ".csv", "bad-mapping.csv",
            mapping={"email": "Нет такой колонки"},
        )
