"""Точка входа: поднимает БД, бота, планировщик и запускает long polling."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import get_settings
from bot.db.session import get_sessionmaker, init_engine
from bot.handlers import build_router
from bot.middlewares import DbSessionMiddleware, UserMiddleware
from bot.services.ai.client import AiClient
from bot.services.scheduler import build_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("bot")


def _run_migrations(db_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "bot" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")


async def main() -> None:
    settings = get_settings()
    settings.ensure_dirs()

    init_engine(settings.db_url)
    _run_migrations(settings.db_url)
    sessionmaker = get_sessionmaker()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # middlewares
    dp.update.middleware(DbSessionMiddleware(sessionmaker))
    dp.update.middleware(UserMiddleware())

    # общие зависимости хендлеров
    dp["ai"] = AiClient(settings)

    dp.include_router(build_router())

    scheduler = build_scheduler(bot, sessionmaker)
    scheduler.start()

    me = await bot.get_me()
    log.info("Запущен как @%s. AI: %s", me.username, "on" if settings.ai_enabled else "off")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
