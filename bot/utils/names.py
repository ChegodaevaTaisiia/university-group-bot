"""Нормализация ФИО для сопоставления записей списка группы с аккаунтами."""

from __future__ import annotations

import re


def normalize_name(name: str) -> str:
    name = name.lower().replace("ё", "е")
    name = re.sub(r"[^а-яa-z\s-]", " ", name)
    return " ".join(name.split())
