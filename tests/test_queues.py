from datetime import date

from bot.services.queues import parse_slot_lines


def _next(month: int, day: int) -> date:
    today = date.today()
    d = date(today.year, month, day)
    return d if d >= today else date(today.year + 1, month, day)


def test_parse_basic():
    ok, bad = parse_slot_lines("10.10 3 пара\n10.10 4 пара x2\n15.10 2")
    assert bad == []
    assert ok[0] == {"date": _next(10, 10), "pair": 3, "count": 1}
    assert ok[1]["count"] == 2
    assert ok[2]["pair"] == 2


def test_parse_rejects_garbage():
    ok, bad = parse_slot_lines("завтра как-нибудь\n10.10 9 пара\nпросто текст")
    assert ok == []
    assert len(bad) == 3  # 9 пара недопустима


def test_parse_cyrillic_x():
    ok, _ = parse_slot_lines("20.11 1 пара х3")  # русская х
    assert ok and ok[0]["count"] == 3
