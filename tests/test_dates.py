from datetime import datetime
from zoneinfo import ZoneInfo

from bot.utils.dates import parse_when

TZ = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=TZ)  # четверг


def test_relative_hours():
    got = parse_when("через 2 часа", TZ, now=NOW)
    assert got is not None
    assert got.astimezone(TZ).hour == 14


def test_relative_minutes():
    got = parse_when("напомни через 30 минут", TZ, now=NOW)
    assert got.astimezone(TZ).strftime("%H:%M") == "12:30"


def test_tomorrow_with_time():
    got = parse_when("завтра 9:30", TZ, now=NOW).astimezone(TZ)
    assert (got.day, got.hour, got.minute) == (11, 9, 30)


def test_month_name():
    got = parse_when("пересдача 15 сентября 10:00", TZ, now=NOW).astimezone(TZ)
    assert (got.month, got.day, got.hour) == (9, 15, 10)


def test_month_name_rolls_to_next_year():
    got = parse_when("1 марта", TZ, now=NOW).astimezone(TZ)
    assert (got.year, got.month, got.day) == (2027, 3, 1)


def test_weekday():
    got = parse_when("в понедельник 8:00", TZ, now=NOW).astimezone(TZ)
    assert got.weekday() == 0
    assert got > NOW


def test_dmy_numeric():
    got = parse_when("18.09.2026 14:00", TZ, now=NOW).astimezone(TZ)
    assert (got.month, got.day, got.hour) == (9, 18, 14)


def test_time_only_moves_to_tomorrow_if_past():
    got = parse_when("8:00", TZ, now=NOW).astimezone(TZ)
    assert got.day == 11 and got.hour == 8


def test_garbage_returns_none():
    assert parse_when("когда-нибудь потом", TZ, now=NOW) is None
