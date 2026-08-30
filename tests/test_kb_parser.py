from bot.services.kb_import.university_site import (
    discover_staff_urls,
    parse_school_contacts,
    parse_staff_page,
)

_UNITS = """
<html><body>
<a href="/structure/hs/xx/subordinateunits/kafedra-informatiki">Кафедра информатики</a>
<a href="/structure/hs/xx/subordinateunits/kafedra-statistiki#section-1">Кафедра статистики</a>
<a href="/structure/hs/xx/subordinateunits/uchebnaya-laboratoriya">Учебная лаборатория</a>
<a href="/structure/hs/xx/abiturientu">Абитуриенту</a>
</body></html>
"""

_N1 = '<a href="/~person/abc123" class="cl-white">Иванов Иван Иванович</a>'
_N2 = '<a href="/~person/def456">Петрова Анна Сергеевна</a>'
_STAFF = f"""
<html><body>
<h1>Кафедра информатики</h1>
<div class="inner-page-teachers-item-descr-bg">
  <div class="inner-page-teachers-name">{_N1}</div>
  <div class="inner-page-teachers-text">Заведующий кафедрой, д.н., "доцент"</div>
</div>
<div class="inner-page-teachers-item-descr-bg">
  <div class="inner-page-teachers-name">{_N2}</div>
  <div class="inner-page-teachers-text">Старший преподаватель</div>
</div>
</body></html>
"""

_SCHOOL = """
<html><body>
<h2>Контакты</h2>
<div><p>Адрес дирекции: Москва, Стремянный 36</p><p>Приёмные часы: пн-пт 9-17</p>
<p>e-mail: fmesi@rea.ru</p></div>
</body></html>
"""


def test_discover_staff_urls_filters_to_kafedra():
    got = discover_staff_urls(_UNITS)
    assert got == [
        ("https://www.rea.ru/structure/hs/xx/subordinateunits/kafedra-informatiki/sotrudniki",
         "Кафедра информатики"),
        ("https://www.rea.ru/structure/hs/xx/subordinateunits/kafedra-statistiki/sotrudniki",
         "Кафедра статистики"),
    ]


def test_parse_staff_page():
    got = parse_staff_page(_STAFF, "запасное имя")
    assert len(got) == 2
    assert got[0]["name"] == "Иванов Иван Иванович"
    assert got[0]["kafedra"] == "Кафедра информатики"
    assert "доцент" in got[0]["position"] and '"' not in got[0]["position"]
    assert got[0]["person_url"] == "https://www.rea.ru/~person/abc123"
    assert got[1]["position"] == "Старший преподаватель"


def test_parse_school_contacts():
    got = parse_school_contacts(_SCHOOL, "https://x")
    assert got is not None
    assert "Стремянный" in got["body"]
    assert got["source_url"] == "https://x"
