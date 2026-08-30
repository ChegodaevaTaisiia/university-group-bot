"""Синхронизация расписания с rasp.rea.ru: загрузка, сравнение, оповещение об изменениях."""

from __future__ import annotations

import logging

from aiogram import Bot
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import selectinload

from bot.config import get_settings
from bot.db.models import Lesson, Subject, WeekParity
from bot.services.rasp.rea import RaspLesson, ReaRaspClient, selection_from_url

log = logging.getLogger(__name__)

_WD = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
_PARITY_LABEL = {WeekParity.odd: "числитель", WeekParity.even: "знаменатель"}


def _parity(week: int) -> WeekParity:
    return WeekParity.odd if week == 1 else WeekParity.even


def _key(parity, weekday: int, pair_no: int) -> tuple:  # noqa: ANN001
    return (str(parity), weekday, pair_no)


def _fmt_time(t) -> str:  # noqa: ANN001
    return t.strftime("%H:%M") if t else "—"


def _diff_lesson(old: Lesson, new: RaspLesson) -> list[str]:
    changes: list[str] = []
    if (old.subject.name if old.subject else "") != new.subject:
        changes.append(f"предмет: {old.subject.name} → {new.subject}")
    if (old.teacher or "") != (new.teacher or ""):
        changes.append(f"преподаватель: {old.teacher or '—'} → {new.teacher or '—'}")
    if (old.room or "") != (new.room or ""):
        changes.append(f"аудитория: {old.room or '—'} → {new.room or '—'}")
    if (old.kind or "") != (new.kind or ""):
        changes.append(f"тип: {old.kind or '—'} → {new.kind or '—'}")
    if _fmt_time(old.starts_at) != _fmt_time(new.starts_at):
        changes.append(f"время: {_fmt_time(old.starts_at)} → {_fmt_time(new.starts_at)}")
    return changes


async def sync_schedule(sessionmaker: async_sessionmaker, bot: Bot | None = None) -> str:
    settings = get_settings()
    if not settings.rasp_url:
        return "Не задан RASP_URL — ссылка на расписание группы."

    client = ReaRaspClient(selection_from_url(settings.rasp_url))
    parsed = await client.fetch(weeks=(1, 2), with_teachers=True)
    if not parsed:
        return "С сайта расписания ничего не пришло. Попробуй позже."

    async with sessionmaker() as session:
        old_rows = list(
            await session.scalars(select(Lesson).options(selectinload(Lesson.subject)))
        )
        first_load = not old_rows
        old_by_key = {
            _key(row.week_parity, row.weekday, row.pair_no): row for row in old_rows
        }

        subjects = {s.name: s for s in await session.scalars(select(Subject))}
        new_by_key: dict[tuple, RaspLesson] = {}
        for pl in parsed:
            new_by_key[_key(_parity(pl.week), pl.weekday, pl.pair_no)] = pl

        added, removed, changed = [], [], []

        for k, pl in new_by_key.items():
            parity = _parity(pl.week)
            label = _PARITY_LABEL[parity]
            old = old_by_key.get(k)
            if old is None:
                added.append(
                    f"➕ {_WD[pl.weekday]}, {pl.pair_no} пара ({label}): "
                    f"{pl.subject}"
                    + (f", {pl.teacher}" if pl.teacher else "")
                    + (f", ауд. {pl.room}" if pl.room else "")
                )
            else:
                ch = _diff_lesson(old, pl)
                if ch:
                    changed.append(
                        f"✏️ {_WD[pl.weekday]}, {pl.pair_no} пара ({label}), "
                        f"{pl.subject}:\n   " + "\n   ".join(ch)
                    )

        for k, old in old_by_key.items():
            if k not in new_by_key:
                _, wd, pair = k
                label = _PARITY_LABEL.get(old.week_parity, "")
                subj = old.subject.name if old.subject else "пара"
                removed.append(f"➖ {_WD[wd]}, {pair} пара ({label}): убрали «{subj}»")

        # применяем
        await session.execute(delete(Lesson))
        for pl in parsed:
            subj = subjects.get(pl.subject)
            if subj is None:
                subj = Subject(name=pl.subject)
                session.add(subj)
                await session.flush()
                subjects[pl.subject] = subj
            session.add(
                Lesson(
                    subject_id=subj.id,
                    weekday=pl.weekday,
                    pair_no=pl.pair_no,
                    starts_at=pl.starts_at,
                    ends_at=pl.ends_at,
                    week_parity=_parity(pl.week),
                    kind=pl.kind,
                    room=pl.room,
                    teacher=pl.teacher,
                )
            )
        await session.commit()

    total_changes = len(added) + len(removed) + len(changed)
    if first_load:
        return f"Загрузила расписание с rasp.rea.ru: {len(parsed)} пар (2 недели)."
    if total_changes == 0:
        return "Проверила rasp.rea.ru — расписание не менялось."

    blocks = ["<b>📅 Расписание изменилось</b>", ""]
    blocks += changed + added + removed
    text = "\n".join(blocks)

    if bot and settings.supergroup_id:
        try:
            await bot.send_message(settings.supergroup_id, text)
        except Exception:  # noqa: BLE001
            log.exception("не смогла отправить изменения расписания в чат")
    return f"Расписание обновлено, изменений: {total_changes}. " + (
        "Оповестила группу." if bot and settings.supergroup_id else ""
    )
