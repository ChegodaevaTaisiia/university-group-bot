"""Ручной запуск обновления базы знаний с сайта универа.

    python -m scripts.import_kb
"""

from __future__ import annotations

import asyncio

from bot.config import get_settings
from bot.db.session import get_sessionmaker, init_engine
from bot.services.kb_import.university_site import refresh_from_site


async def main() -> None:
    settings = get_settings()
    settings.ensure_dirs()
    init_engine(settings.db_url)
    n = await refresh_from_site(get_sessionmaker())
    print(f"Обновлено записей: {n}")


if __name__ == "__main__":
    asyncio.run(main())
