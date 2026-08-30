from datetime import UTC, datetime, timedelta

from bot.db.models import ReminderRepeat
from bot.services.reminders import _advance


def test_none_repeat_returns_none():
    assert _advance(datetime.now(UTC), ReminderRepeat.none) is None


def test_daily_advances_past_now():
    past = datetime.now(UTC) - timedelta(days=3, hours=1)
    nxt = _advance(past, ReminderRepeat.daily)
    assert nxt > datetime.now(UTC)
    assert (nxt - past).total_seconds() % 86400 < 1


def test_weekly_advances_one_week_when_future():
    fut = datetime.now(UTC) + timedelta(days=1)
    nxt = _advance(fut, ReminderRepeat.weekly)
    assert (nxt - fut) == timedelta(weeks=1)
