"""Точка входа: поднимает БД, бота, планировщик и запускает long polling."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
)

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


async def _setup_commands(bot: Bot, admin_ids: list[int]) -> None:
    """Меню команд Telegram (появляется по «/»)."""
    common = [
        BotCommand(command="menu", description="Главное меню"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="ball", description="🔮 Магический шар: /ball вопрос"),
        BotCommand(command="coin", description="🪙 Подбросить монетку"),
        BotCommand(command="dice", description="🎲 Бросить кубик"),
        BotCommand(command="who", description="🎯 Кого сегодня спросят"),
        BotCommand(command="meme", description="😎 Мем дня"),
    ]
    admin = [
        BotCommand(command="panel", description="Панель старосты"),
        *common,
        BotCommand(command="topic", description="Привязать тему к предмету (внутри темы)"),
        BotCommand(command="reply", description="Ответить на вопрос студента: /reply N текст"),
    ]
    try:
        await bot.set_my_commands(common, scope=BotCommandScopeDefault())
        for admin_id in admin_ids:
            await bot.set_my_commands(admin, scope=BotCommandScopeChat(chat_id=admin_id))
    except Exception:  # noqa: BLE001
        log.warning("не удалось выставить меню команд", exc_info=True)


def _force_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8", errors="replace")


async def main() -> None:
    _force_utf8_console()
    settings = get_settings()
    settings.ensure_dirs()

    init_engine(settings.db_url)
    _run_migrations(settings.db_url)
    sessionmaker = get_sessionmaker()

    from bot.services.greetings import seed_default_holidays

    async with sessionmaker() as session:
        await seed_default_holidays(session)

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

    await _setup_commands(bot, settings.admin_ids)

    me = await bot.get_me()
    print(
        f"\n  ✅ Бот запущен: @{me.username}   "
        f"(ИИ: {'вкл' if settings.ai_enabled else 'выкл'}, "
        f"группа: {'задана' if settings.supergroup_id else 'нет'})\n"
        f"  Напиши боту /start в Telegram. Остановить: Ctrl+C\n",
        flush=True,
    )
    log.info("polling started")

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
