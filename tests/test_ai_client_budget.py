import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot.config import get_settings
from bot.db.base import Base
from bot.db.models import AiQueryLog
from bot.services.ai.client import AiClient, BudgetExceeded, estimate_cost


def test_estimate_cost_haiku():
    # 1M input @ $1, 1M output @ $5
    assert estimate_cost("claude-haiku-4-5", 1_000_000, 1_000_000) == pytest.approx(6.0)


@pytest.fixture
async def sm():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_budget_blocks_when_exceeded(sm):
    settings = get_settings()
    settings.ai_monthly_budget_usd = 1.0
    client = AiClient(settings)
    async with sm() as session:
        session.add(AiQueryLog(kind="assistant", cost_usd=1.5, model="x"))
        await session.commit()
        with pytest.raises(BudgetExceeded):
            await client.check_budget(session)


async def test_budget_ok_when_under(sm):
    settings = get_settings()
    settings.ai_monthly_budget_usd = 10.0
    client = AiClient(settings)
    async with sm() as session:
        session.add(AiQueryLog(kind="assistant", cost_usd=1.5, model="x"))
        await session.commit()
        await client.check_budget(session)  # не бросает
