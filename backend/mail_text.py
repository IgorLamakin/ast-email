# -*- coding: utf-8 -*-
"""Конвертация HTML-письма в plain-text версию (2.7.0).

Зачем это нужно:
- письмо без текстовой части - устойчивый минус в антиспам-фильтрах, а Яндекс
  и Mail.ru прямо рекомендуют multipart/alternative;
- Gmail/Outlook в некоторых режимах показывают именно текстовую версию.

Конвертер намеренно простой и зависимый только от стандартной библиотеки:
тянуть html2text/BeautifulSoup ради одного письма не нужно (и это лишние
мегабайты в установщике). Задача - не идеальная вёрстка, а читаемый текст:
абзацы/переносы сохраняются, ссылки остаются ссылками.
"""
import html as _html
import re

# Блочные теги, после которых в тексте должен быть перенос строки.
_BLOCK_END_RE = re.compile(r"</\s*(p|div|tr|h[1-6]|li|ul|ol|table|blockquote|section|article|header|footer)\s*>", re.IGNORECASE)
_BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_LI_RE = re.compile(r"<\s*li[^>]*>", re.IGNORECASE)
_SCRIPT_STYLE_RE = re.compile(r"<\s*(script|style|head)[^>]*>.*?<\s*/\s*\1\s*>", re.IGNORECASE | re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACES_RE = re.compile(r"[ \t\u00a0\u200b]+")
_SPACE_NL_RE = re.compile(r" *\n *")
_MANY_NL_RE = re.compile(r"\n{3,}")


def html_to_text(html_content: str) -> str:
    """Грубое, но надёжное превращение HTML письма в читаемый plain-text."""
    if not html_content:
        return ""
    text = _COMMENT_RE.sub(" ", html_content)
    text = _SCRIPT_STYLE_RE.sub(" ", text)
    text = _BR_RE.sub("\n", text)
    text = _LI_RE.sub("- ", text)
    text = _BLOCK_END_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = _html.unescape(text)
    text = _SPACES_RE.sub(" ", text)
    text = _SPACE_NL_RE.sub("\n", text)
    text = _MANY_NL_RE.sub("\n\n", text)
    return text.strip()


def is_probably_html(value: str) -> bool:
    """Эвристика: похоже ли значение на HTML, а не на обычный текст."""
    if not value:
        return False
    return bool(re.search(r"<[a-zA-Z][^>]*>", value))
