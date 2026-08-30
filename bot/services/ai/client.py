"""Тонкая обёртка над Anthropic SDK: вызовы Claude, учёт токенов и стоимости, лимит бюджета.

ИИ-функции опциональны: если ключ не задан — `AiClient.enabled` False и вызывать не нужно.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db.models import AiQueryLog

log = logging.getLogger(__name__)

# $/1M токенов (input, output). Обновлять при смене цен.
PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5": (5.0, 25.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    inp, out = PRICING.get(model, (1.0, 5.0))
    return input_tokens / 1_000_000 * inp + output_tokens / 1_000_000 * out


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class AiResult:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str


class AiClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.ai_model
        self._client = None
        if settings.ai_enabled:
            from anthropic import AsyncAnthropic

            kwargs: dict = {"api_key": settings.anthropic_api_key}
            if settings.anthropic_base_url:
                kwargs["base_url"] = settings.anthropic_base_url.rstrip("/")
            self._client = AsyncAnthropic(**kwargs)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def month_spend_usd(self, session: AsyncSession) -> float:
        start = datetime.now(UTC).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        total = await session.scalar(
            select(func.coalesce(func.sum(AiQueryLog.cost_usd), 0.0)).where(
                AiQueryLog.created_at >= start
            )
        )
        return float(total or 0.0)

    async def check_budget(self, session: AsyncSession) -> None:
        if await self.month_spend_usd(session) >= self.settings.ai_monthly_budget_usd:
            raise BudgetExceeded

    async def complete(
        self,
        *,
        session: AsyncSession,
        system: str,
        user_content: list | str,
        kind: str,
        user_id: int | None = None,
        max_tokens: int = 700,
        question_for_log: str = "",
        record: bool = True,
    ) -> AiResult:
        if not self.enabled:
            raise RuntimeError("AI выключен")
        await self.check_budget(session)

        resp = await self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_content}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        cost = estimate_cost(self.model, resp.usage.input_tokens, resp.usage.output_tokens)
        result = AiResult(
            text=text,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            cost_usd=cost,
            model=self.model,
        )
        if record:
            session.add(
                AiQueryLog(
                    user_id=user_id,
                    kind=kind,
                    question=question_for_log[:4000],
                    answer=text[:4000],
                    model=self.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cost_usd=cost,
                )
            )
            await session.commit()
        return result
