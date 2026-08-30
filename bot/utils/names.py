"""Нормализация ФИО для сопоставления записей списка группы с аккаунтами."""

from __future__ import annotations

import re


def normalize_name(name: str) -> str:
    name = name.lower().replace("ё", "е")
    name = re.sub(r"[^а-яa-z\s-]", " ", name)
    return " ".join(name.split())


def first_name(full_name: str) -> str:
    """ФИО в порядке «Фамилия Имя Отчество» → Имя (второе слово)."""
    parts = full_name.split()
    if len(parts) >= 2:
        return parts[1]
    return parts[0] if parts else ""
