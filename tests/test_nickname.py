from bot.handlers.assistant import _nick_pattern


def test_nick_matches_various_separators():
    p = _nick_pattern("Плеша, Плеш")
    for text in (
        "Плеша, что задали по матану?",
        "плеша что там с расписанием",
        "ПЛЕША: помоги",
        "Плеша — когда пересдача",
        "Плеша. напомни про физику",
        "Плеш, ты тут?",
    ):
        m = p.match(text)
        assert m is not None, text
        assert len(m.group(1)) > 2


def test_nick_no_match_without_name():
    p = _nick_pattern("Плеша, Плеш")
    assert p.match("что задали по матану?") is None
    assert p.match("любимплеша скажи") is None


def test_longer_alias_wins():
    p = _nick_pattern("Плеш, Плеша")  # порядок в конфиге не важен
    m = p.match("Плеша, привет")
    assert m and m.group(1) == "привет"
