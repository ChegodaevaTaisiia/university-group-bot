from bot.handlers.assistant import _nick_pattern


def test_nick_matches_various_separators():
    p = _nick_pattern("Биби")
    for text in ("Биби, что задали по матану?", "биби что там с расписанием",
                 "БИБИ: помоги", "Биби — когда пересдача"):
        m = p.match(text)
        assert m is not None
        assert len(m.group(1)) > 2


def test_nick_no_match_without_name():
    p = _nick_pattern("Биби")
    assert p.match("что задали по матану?") is None
    assert p.match("любимбиби") is None
