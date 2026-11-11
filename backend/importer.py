# -*- coding: utf-8 -*-
"""Импорт получателей массовой рассылки из Excel/CSV (2.7.0).

Поддерживаемые форматы: .xlsx (openpyxl), .xls (xlrd), .csv/.txt (с
автоопределением кодировки: UTF-8 (с BOM и без), cp1251, UTF-16).

Почему не pandas: он тянет numpy и раздувает установщик приложения на десятки
мегабайт, а нужен нам только простой разбор таблицы.

Общая идея:
1) прочитать файл в список строк (каждая строка - список значений-строк);
2) первая непустая строка считается заголовком, по нему (и по содержимому)
   автоматически определяется, где email, обращение, имя, компания, должность,
   а все остальные колонки попадают в «доп. поля» (field_1..field_N);
3) привести адреса к нормальному виду, проверить валидность, убрать дубли и
   адреса из стоп-листа;
4) отдать результат для превью/сохранения в БД.

Ошибки пользователю отдаются через ImportFileError с понятным текстом.
"""
import csv
import io
import logging
import os
import re

from database import SessionLocal
import models

logger = logging.getLogger(__name__)

# Ограничения (контракт): файл не больше 10 МБ и не больше 50 000 строк данных.
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_ROWS = 50000
PREVIEW_LIMIT = 20
ALLOWED_EXTS = {".xlsx", ".xls", ".csv", ".txt"}

# Сколько первых строк смотреть при автоопределении колонки email по доле
# валидных адресов.
_DETECT_SAMPLE_ROWS = 200
# Минимальная доля валидных адресов, при которой колонка считается «почтовой».
_MIN_EMAIL_RATIO = 0.3
# При такой доле колонка считается почтовой даже если её заголовок похож на
# что-то другое (например, колонка «Контакт» в выгрузке 1С с адресами).
_STRONG_EMAIL_RATIO = 0.6


class ImportFileError(Exception):
    """Понятная пользователю ошибка импорта (битый/слишком большой файл и т.п.)."""


# ========== НОРМАЛИЗАЦИЯ EMAIL ==========
def normalize_email(value):
    """Вернуть нормализованный адрес (str) или None, если это не email.

    Нормализация: обрезка пробелов, проверка синтаксиса через email_validator,
    домен - в нижний регистр/punycode. Несколько адресов в одной ячейке и
    «нет email» считаются невалидными (не угадываем, какой из них основной).
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or len(raw) > 320:
        return None
    # Быстрый отсев очевидного мусора до обращения к валидатору.
    if "@" not in raw or raw.count("@") != 1:
        return None
    if any(ch in raw for ch in ",;<>()[] \t"):
        return None
    try:
        from email_validator import validate_email, EmailNotValidError
    except ImportError:  # pragma: no cover - зависимость есть в requirements
        logger.error("email-validator не установлен - проверить адреса нельзя")
        return None
    try:
        result = validate_email(raw, check_deliverability=False)
    except EmailNotValidError:
        return None
    except Exception:  # неожиданная ошибка валидатора не должна ронять импорт
        logger.exception("email_validator: не удалось проверить адрес %r", raw)
        return None
    normalized = (getattr(result, "normalized", "") or result.email).strip().lower()
    return normalized or None


def normalize_email_parts(value):
    """Вернуть (email_для_показа, normalized_email) или (None, None)."""
    normalized = normalize_email(value)
    if not normalized:
        return None, None
    try:
        from email_validator import validate_email
        result = validate_email(str(value).strip(), check_deliverability=False)
        display = (result.email or normalized).strip()
    except Exception:
        display = normalized
    return display, normalized


# ========== СТОП-ЛИСТ ==========
def load_stop_list(db=None):
    """Нормализованные адреса из таблицы Unsubscribe (глобальный стоп-лист)."""
    own_session = db is None
    session = db or SessionLocal()
    try:
        rows = session.query(models.Unsubscribe.normalized_email).all()
        return {row[0] for row in rows if row[0]}
    except Exception:
        # Стоп-лист - не повод ронять импорт: если БД ещё не готова/таблицы нет,
        # считаем его пустым.
        logger.exception("Не удалось прочитать стоп-лист отписавшихся")
        return set()
    finally:
        if own_session:
            session.close()


# ========== ЧТЕНИЕ ФАЙЛА ==========
def _cell_to_str(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _read_xlsx(path):
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise ImportFileError(
            "Для импорта .xlsx не установлена библиотека openpyxl. "
            "Установите её: pip install openpyxl"
        )
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise ImportFileError(f"Не удалось прочитать файл Excel: {exc}")
    try:
        sheet = workbook.active
        rows = []
        for row in sheet.iter_rows(values_only=True):
            rows.append([_cell_to_str(value) for value in row])
            if len(rows) > MAX_ROWS + 1000:
                raise ImportFileError(
                    "В файле больше " + f"{MAX_ROWS:,}".replace(",", " ")
                    + " строк - уменьшите список получателей."
                )
        return rows
    finally:
        try:
            workbook.close()
        except Exception:
            pass


def _read_xls(path):
    try:
        import xlrd
    except ImportError:
        raise ImportFileError(
            "Для импорта .xls не установлена библиотека xlrd. "
            "Установите её: pip install xlrd"
        )
    try:
        workbook = xlrd.open_workbook(path)
    except Exception as exc:
        raise ImportFileError(f"Не удалось прочитать файл Excel (.xls): {exc}")
    sheet = workbook.sheet_by_index(0)
    rows = []
    for row_index in range(sheet.nrows):
        values = sheet.row_values(row_index)
        rows.append([_cell_to_str(value) for value in values])
    return rows


def _decode_csv_bytes(raw):
    """Определить кодировку CSV по BOM и попыткам декодирования."""
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    # utf-8-sig сам снимает BOM, если он есть.
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "cp866", "koi8-r"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    # cp1251 декодирует почти любые байты - используем как последний рубеж,
    # чтобы файл всё-таки открылся (с возможными «кракозябрами» в тексте).
    return raw.decode("cp1251", errors="replace")


def _detect_delimiter(text, sample):
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        pass
    counts = {delim: sample.count(delim) for delim in (";", ",", "\t", "|")}
    best = max(counts, key=lambda key: counts[key])
    return best if counts[best] else ","


def _read_csv(path):
    try:
        with open(path, "rb") as source:
            raw = source.read()
    except OSError as exc:
        raise ImportFileError(f"Не удалось прочитать файл: {exc}")
    text = _decode_csv_bytes(raw)
    sample = text[:4096]
    delimiter = _detect_delimiter(text, sample)
    rows = []
    try:
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        for row in reader:
            rows.append([_cell_to_str(value) for value in row])
            if len(rows) > MAX_ROWS + 1000:
                raise ImportFileError(
                    "В файле больше " + f"{MAX_ROWS:,}".replace(",", " ")
                    + " строк - уменьшите список получателей."
                )
    except csv.Error as exc:
        raise ImportFileError(f"Не удалось разобрать CSV: {exc}")
    return rows


def read_table(path, ext=None):
    """Прочитать файл в список строк. Возвращает (rows, ext)."""
    ext = (ext or os.path.splitext(path)[1]).lower()
    if ext not in ALLOWED_EXTS:
        raise ImportFileError(
            f"Формат «{ext or 'без расширения'}» не поддерживается. "
            "Загрузите файл Excel (.xlsx/.xls) или CSV."
        )
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise ImportFileError(f"Не удалось открыть файл: {exc}")
    if size > MAX_FILE_BYTES:
        raise ImportFileError(
            f"Файл слишком большой ({size // (1024 * 1024)} МБ). "
            "Максимальный размер - 10 МБ."
        )
    if size == 0:
        raise ImportFileError("Файл пустой.")
    if ext == ".xlsx":
        return _read_xlsx(path), ext
    if ext == ".xls":
        return _read_xls(path), ext
    return _read_csv(path), ext


# ========== АВТООПРЕДЕЛЕНИЕ КОЛОНОК ==========
def _norm_header(value):
    return re.sub(r"[^0-9a-zа-яё]+", "", (value or "").strip().lower())


EMAIL_SYNONYMS = {
    "email", "emailадрес", "емейл", "мейл", "почта", "почтаполучателя",
    "почтовыйадрес", "электроннаяпочта", "элпочта", "электронныйадрес",
    "mail", "адресэлектроннойпочты", "emailполучателя", "адрес",
}
GREETING_SYNONYMS = {
    "обращение", "приветствие", "greeting", "salutation",
    "обращениепоимени", "формаобращения",
}
NAME_SYNONYMS = {
    "имя", "фио", "контакт", "контактноелицо", "name", "fullname",
    "получатель", "имяполучателя", "клиент", "представитель", "контактноеимя",
}
COMPANY_SYNONYMS = {
    "компания", "организация", "фирма", "company", "organization",
    "названиеорганизации", "наименованиеорганизации", "работодатель", "ооо",
}
POSITION_SYNONYMS = {
    "должность", "позиция", "position", "title", "профессия", "роль",
    "role", "jobtitle", "должностьполучателя",
}


def _find_by_synonyms(norm_headers, synonyms, used):
    for index, value in enumerate(norm_headers):
        if index in used or not value:
            continue
        if value in synonyms:
            used.add(index)
            return index
    # Частичное совпадение: «рабочая почта», «email получателя» и т.п.
    for index, value in enumerate(norm_headers):
        if index in used or not value:
            continue
        for synonym in synonyms:
            if len(synonym) >= 5 and (synonym in value or value in synonym):
                used.add(index)
                return index
    return None


def detect_mapping(columns, data_rows):
    """Определить индексы колонок: {"email": idx, "greeting": idx, ...}.

    email ищется сначала по словарю синонимов заголовка, затем - по максимальной
    доле валидных адресов в колонке (первая непустая строка файла уже считается
    заголовком). Остальные поля - по словарям синонимов.
    """
    norm_headers = [_norm_header(column) for column in columns]
    used = set()
    mapping = {}
    mapping["email"] = _find_by_synonyms(norm_headers, EMAIL_SYNONYMS, used)
    mapping["greeting"] = _find_by_synonyms(norm_headers, GREETING_SYNONYMS, used)
    mapping["name"] = _find_by_synonyms(norm_headers, NAME_SYNONYMS, used)
    mapping["company"] = _find_by_synonyms(norm_headers, COMPANY_SYNONYMS, used)
    mapping["position"] = _find_by_synonyms(norm_headers, POSITION_SYNONYMS, used)

    if mapping["email"] is None:
        sample = data_rows[:_DETECT_SAMPLE_ROWS]
        best_index = None
        best_ratio = 0.0
        for index in range(len(columns)):
            if index in used:
                continue
            values = [
                row[index] for row in sample
                if index < len(row) and str(row[index]).strip()
            ]
            if not values:
                continue
            valid = sum(1 for value in values if normalize_email(value))
            ratio = valid / len(values)
            if ratio > best_ratio:
                best_index, best_ratio = index, ratio
        if best_ratio >= _STRONG_EMAIL_RATIO:
            # Явно почтовая колонка, даже если её заголовок похож на другое поле.
            mapping["email"] = best_index
            used.add(best_index)
        elif best_ratio >= _MIN_EMAIL_RATIO:
            mapping["email"] = best_index
            used.add(best_index)

    mapping["extra"] = [index for index in range(len(columns)) if index not in used]
    return mapping


# ========== ОСНОВНАЯ ФУНКЦИЯ ==========
def _as_mapping_dict(mapping):
    if mapping is None:
        return None
    if hasattr(mapping, "model_dump"):
        return mapping.model_dump()
    if isinstance(mapping, dict):
        return dict(mapping)
    raise ImportFileError("Некорректное сопоставление колонок.")


def _column_index(columns, name):
    if not name:
        return None
    try:
        return columns.index(name)
    except ValueError:
        raise ImportFileError(f"Колонка «{name}» не найдена в файле.")


def _split_rows(rows):
    """Отделить заголовок (первая непустая строка) от данных.

    Возвращает (columns, data_rows, header_row_number), где header_row_number -
    номер строки заголовка в файле (1-based), чтобы в превью показывать
    «человеческие» номера строк.
    """
    header_index = None
    for index, row in enumerate(rows):
        if any(_cell_to_str(value) for value in row):
            header_index = index
            break
    if header_index is None:
        raise ImportFileError("Файл пустой: не найдено ни одной строки с данными.")
    header = rows[header_index]
    max_width = len(header)
    for row in rows[header_index + 1:]:
        max_width = max(max_width, len(row))
    columns = []
    for index in range(max_width):
        name = _cell_to_str(header[index]) if index < len(header) else ""
        columns.append(name or f"Колонка {index + 1}")
    data_rows = []
    for row in rows[header_index + 1:]:
        if not any(_cell_to_str(value) for value in row):
            continue
        padded = list(row) + [""] * (max_width - len(row))
        data_rows.append(padded[:max_width])
    if len(data_rows) > MAX_ROWS:
        raise ImportFileError(
            f"В файле {len(data_rows)} строк - больше допустимых {MAX_ROWS}. "
            "Разделите список на несколько кампаний."
        )
    return columns, data_rows, header_index + 1


def _row_value(row, index):
    if index is None or index >= len(row):
        return ""
    return _cell_to_str(row[index])


def parse_recipients_file(path, ext=None, original_name=None, mapping=None):
    """Разобрать файл получателей.

    Возвращает словарь:
    {
      "columns": [str, ...],
      "mapping": {"email": имя|None, "greeting": ..., "name": ..., "company": ...,
                  "position": ..., "extra": [имена колонок]},
      "counts": {"total", "valid", "duplicates", "invalid", "unsubscribed"},
      "preview": [{row, email, greeting, company, status}, ...] (до 20 строк),
      "recipients": [{email, normalized_email, greeting, fields, status,
                      skip_reason}, ...],
      "rows_total": общее число строк данных,
    }

    В recipients попадают только адреса с валидным синтаксисом: дубликаты и мусор
    сохранять в БД нельзя (UniqueConstraint(campaign_id, normalized_email)), они
    видны в counts/preview. Отписавшиеся попадают со status="skipped".

    mapping можно передать явно (повторный разбор /import/remap): словарь или
    schemas.ImportMapping. Если колонка email не найдена - mapping["email"] = None,
    recipients пустой, UI попросит выбрать колонку вручную.
    """
    rows, ext = read_table(path, ext=ext)
    columns, data_rows, header_row_number = _split_rows(rows)

    requested = _as_mapping_dict(mapping)
    if requested is not None:
        index_mapping = {
            "email": _column_index(columns, requested.get("email")),
            "greeting": _column_index(columns, requested.get("greeting")),
            "name": _column_index(columns, requested.get("name")),
            "company": _column_index(columns, requested.get("company")),
            "position": _column_index(columns, requested.get("position")),
        }
        extra_indices = []
        for name in requested.get("extra") or []:
            index = _column_index(columns, name)
            if index is not None and index not in extra_indices:
                extra_indices.append(index)
    else:
        detected = detect_mapping(columns, data_rows)
        index_mapping = {
            key: detected.get(key)
            for key in ("email", "greeting", "name", "company", "position")
        }
        extra_indices = list(detected.get("extra") or [])

    extra_names = [columns[index] for index in extra_indices]
    result_mapping = {
        "email": columns[index_mapping["email"]] if index_mapping["email"] is not None else None,
        "greeting": columns[index_mapping["greeting"]] if index_mapping["greeting"] is not None else None,
        "name": columns[index_mapping["name"]] if index_mapping["name"] is not None else None,
        "company": columns[index_mapping["company"]] if index_mapping["company"] is not None else None,
        "position": columns[index_mapping["position"]] if index_mapping["position"] is not None else None,
        "extra": extra_names,
    }

    counts = {
        "total": len(data_rows), "valid": 0, "duplicates": 0,
        "invalid": 0, "unsubscribed": 0,
    }
    preview = []
    recipients = []

    if index_mapping["email"] is None:
        # Колонка email не определена - вернуть только структуру файла.
        return {
            "columns": columns,
            "mapping": result_mapping,
            "counts": counts,
            "preview": preview,
            "recipients": recipients,
            "rows_total": len(data_rows),
        }

    stop_list = load_stop_list()
    seen = set()

    for data_index, row in enumerate(data_rows, start=1):
        row_number = header_row_number + data_index
        raw_email = _row_value(row, index_mapping["email"])
        display_email, normalized = normalize_email_parts(raw_email)
        greeting = _row_value(row, index_mapping["greeting"]) or None
        company = _row_value(row, index_mapping["company"]) or None
        name = _row_value(row, index_mapping["name"])
        position = _row_value(row, index_mapping["position"])
        fields = {}
        if name:
            fields["name"] = name
        if company:
            fields["company"] = company
        if position:
            fields["position"] = position
        for extra_number, extra_index in enumerate(extra_indices, start=1):
            value = _row_value(row, extra_index)
            if value:
                fields[f"field_{extra_number}"] = value

        status = "ok"
        skip_reason = None
        if not normalized:
            status = "invalid"
            counts["invalid"] += 1
        elif normalized in seen:
            status = "duplicate"
            counts["duplicates"] += 1
        elif normalized in stop_list:
            status = "unsubscribed"
            counts["unsubscribed"] += 1
            skip_reason = "unsubscribed"
            seen.add(normalized)
        else:
            counts["valid"] += 1
            seen.add(normalized)

        if status in ("ok", "unsubscribed"):
            recipients.append({
                "email": display_email or normalized,
                "normalized_email": normalized,
                "greeting": greeting,
                "fields": fields,
                "status": "pending" if status == "ok" else "skipped",
                "skip_reason": skip_reason,
            })

        if len(preview) < PREVIEW_LIMIT:
            preview.append({
                "row": row_number,
                "email": display_email or raw_email,
                "greeting": greeting,
                "company": company,
                "status": status,
            })

    return {
        "columns": columns,
        "mapping": result_mapping,
        "counts": counts,
        "preview": preview,
        "recipients": recipients,
        "rows_total": len(data_rows),
    }


def recipients_to_fields_json(fields):
    """Сериализовать поля персонализации в JSON-строку для БД."""
    import json
    if not fields:
        return None
    return json.dumps(fields, ensure_ascii=False)


def fields_from_json(value):
    """Разобрать JSON-строку полей персонализации обратно в словарь."""
    import json
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}



