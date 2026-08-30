from datetime import date

from bot.db.models import WeekParity
from bot.services.schedule_repo import week_parity

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
