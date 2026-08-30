from datetime import date

from bot.services.fun import BALL_ANSWERS, flip_coin, magic_ball, roll_dice
from bot.services.greetings import _age, parse_birthday
from bot.utils.names import normalize_name


def test_parse_birthday_day_month():
    assert parse_birthday("15.09") == (15, 9, None)


def test_parse_birthday_full():
    assert parse_birthday("03.12.2005") == (3, 12, 2005)


def test_parse_birthday_rejects_garbage():
    assert parse_birthday("завтра") is None
    assert parse_birthday("40.13") is None
    assert parse_birthday("15.09.1900") is None


def test_age():
    class U:
        birthday_year = 2005

    assert _age(U(), date(2026, 6, 1)) == 21


def test_normalize_name():
    assert normalize_name("Иванова  Мария Петровна") == "иванова мария петровна"
    assert normalize_name("Пётр\tСоколов-Микитов") == "петр соколов-микитов"


def test_magic_ball_returns_known_answer():
    assert magic_ball("сдам ли матан")[2:] in BALL_ANSWERS


def test_coin_and_dice():
    assert flip_coin() in ("🪙 Орёл", "🪙 Решка")
    assert 1 <= int(roll_dice().split()[-1]) <= 6
