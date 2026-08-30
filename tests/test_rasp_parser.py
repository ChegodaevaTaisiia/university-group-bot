from datetime import time

from bot.services.rasp.rea import _clean_room, _parse_card, selection_from_url

_CARD = """
<input type="hidden" id="weekNum" value="1" />
<div class="row">
  <div class="col-lg-6 col-12"><div class="container">
    <table class="table table-light">
      <thead class="thead-dark">
        <tr><th class="dayh" colspan="3"><h5>ЧЕТВЕРГ, 03.09.2026</h5></th></tr>
      </thead>
      <tr class="slot load-empty"><td><span class="pcap">1 пара</span></td><td></td></tr>
      <tr class="slot load-seminar-2">
        <td><span class="pcap">3 пара</span><br />11:50<br />13:20</td>
        <td>
          <a href='#' class='task' onclick="updateTimeslotInfo( &#39;03.09.2026&#39;, &#39;3&#39; )">
            Иностранный язык профессионального общения<br />
            <i>Практическое занятие</i><br />
            3 корпус - 623 , пл. Основная
          </a>
        </td>
      </tr>
    </table>
  </div></div>
</div>
"""


def test_selection_from_url():
    assert selection_from_url("https://rasp.rea.ru/?q=15.27д-ивт01/24б") == "15.27д-ивт01/24б"
    assert selection_from_url("15.27д-ивт01/24б") == "15.27д-ивт01/24б"


def test_clean_room():
    assert _clean_room("3 корпус - 623 , пл. Основная") == "623, 3 корпус"
    assert _clean_room("4 корпус - с/з №4 , пл. Основная") == "с/з №4, 4 корпус"
    assert _clean_room("") is None


def test_parse_card():
    lessons = _parse_card(_CARD, week=1)
    assert len(lessons) == 1
    les = lessons[0]
    assert les.week == 1
    assert les.weekday == 3  # четверг
    assert les.pair_no == 3
    assert les.starts_at == time(11, 50)
    assert les.ends_at == time(13, 20)
    assert les.subject == "Иностранный язык профессионального общения"
    assert les.kind == "Практическое занятие"
    assert les.room == "623, 3 корпус"
    assert les.on_date == "03.09.2026"
