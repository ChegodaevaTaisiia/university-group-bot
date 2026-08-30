from datetime import date, time

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot.db.base import Base
from bot.db.models import Lesson, Subject, WeekParity
from bot.services.schedule_repo import lessons_for_day, week_parity

SEMESTER_START = date(2026, 9, 1)  # вторник — неделя с Пн 31.08


def test_first_week_is_odd():
    assert week_parity(date(2026, 9, 2), SEMESTER_START) == WeekParity.odd


def test_second_week_is_even():
    assert week_parity(date(2026, 9, 9), SEMESTER_START) == WeekParity.even


def test_third_week_is_odd_again():
    assert week_parity(date(2026, 9, 16), SEMESTER_START) == WeekParity.odd


def test_same_week_before_start_still_odd():
    # 31.08 — тот же понедельник недели старта
    assert week_parity(date(2026, 8, 31), SEMESTER_START) == WeekParity.odd


@pytest.fixture
async def sm():
    e = create_async_engine("sqlite+aiosqlite://")
    async with e.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(e, expire_on_commit=False)
    await e.dispose()


async def test_no_lessons_before_semester_start(sm):
    async with sm() as s:
        subj = Subject(name="Матан")
        s.add(subj)
        await s.flush()
        s.add(Lesson(subject_id=subj.id, weekday=3, pair_no=1,
                     starts_at=time(9, 0), week_parity=WeekParity.odd))
        await s.commit()
        # четверг до старта семестра — пусто, хотя чётность совпадает
        before = await lessons_for_day(s, date(2026, 8, 27), SEMESTER_START)
        after = await lessons_for_day(s, date(2026, 9, 3), SEMESTER_START)
    assert before.lessons == []
    assert len(after.lessons) == 1
