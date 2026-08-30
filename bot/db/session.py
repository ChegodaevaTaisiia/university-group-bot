"""Async engine + session factory. Инициализируется один раз в main."""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(db_url: str, *, echo: bool = False) -> AsyncEngine:
    global _engine, _sessionmaker

    _engine = create_async_engine(db_url, echo=echo, future=True)

    @event.listens_for(_engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("engine не инициализирован — вызови init_engine()")
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("sessionmaker не инициализирован — вызови init_engine()")
    return _sessionmaker
