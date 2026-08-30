"""Alembic environment. Синхронный движок (SQLite) — этого достаточно для миграций."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from bot.config import get_settings
from bot.db import models  # noqa: F401  (регистрирует таблицы в метаданных)
from bot.db.base import Base

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False — иначе alembic глушит логгер бота при старте
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

if not config.get_main_option("sqlalchemy.url"):
    url = get_settings().db_url.replace("+aiosqlite", "")
    config.set_main_option("sqlalchemy.url", url)
else:
    config.set_main_option(
        "sqlalchemy.url", config.get_main_option("sqlalchemy.url").replace("+aiosqlite", "")
    )


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite: ALTER через пересоздание таблиц
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
