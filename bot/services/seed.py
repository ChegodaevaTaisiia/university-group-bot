"""Тестовые данные для проверки бота: предметы, расписание на неделю, пара ДЗ, ЧаВо."""

from __future__ import annotations

from datetime import date, time, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import (
    FaqEntry,
    Homework,
    HomeworkStatus,
    Lesson,
    Subject,
    WeekParity,
)

SUBJECTS = ["Матанализ", "Физика", "История", "Программирование"]

# (предмет, день недели 0-4, № пары, час, чётность)
LESSONS = [
    ("Матанализ", 0, 1, 9, WeekParity.any),
    ("Физика", 0, 2, 11, WeekParity.any),
    ("История", 1, 1, 9, WeekParity.odd),
    ("Программирование", 1, 2, 11, WeekParity.any),
    ("Матанализ", 2, 1, 9, WeekParity.any),
    ("Программирование", 3, 3, 13, WeekParity.any),
    ("Физика", 4, 1, 9, WeekParity.even),
]

FAQ = [
    ("Где смотреть расписание?", "В боте: кнопка «📅 Расписание» → сегодня / завтра / неделя."),
    ("Как добавить домашку?", "Кнопка «📚 Домашка» → «Добавить задание». Можно текстом или фото доски."),
    ("Что с числителем-знаменателем?", "Бот считает автоматически от даты начала семестра."),
]


async def seed_demo(session: AsyncSession) -> str:
    await session.execute(delete(Lesson))
    await session.execute(delete(Homework))

    subjects: dict[str, Subject] = {
        s.name: s for s in await session.scalars(select(Subject))
    }
    for name in SUBJECTS:
        if name not in subjects:
            s = Subject(name=name)
            session.add(s)
            await session.flush()
            subjects[name] = s

    for name, wd, pair, hour, parity in LESSONS:
        session.add(
            Lesson(
                subject_id=subjects[name].id,
                weekday=wd,
                pair_no=pair,
                starts_at=time(hour, 0),
                ends_at=time(hour + 1, 30),
                week_parity=parity,
                kind="лекция" if pair == 1 else "практика",
                room=str(200 + pair),
            )
        )

    tomorrow = date.today() + timedelta(days=1)
    session.add(
        Homework(
            subject_id=subjects["Матанализ"].id,
            due_date=tomorrow,
            text="Прочитать §5, решить № 12–18",
            text_norm="прочитать 5 решить 12 18",
            created_by=1,
            confirmed_by=[1, 2],
            confirmations=2,
            status=HomeworkStatus.confirmed,
        )
    )
    session.add(
        Homework(
            subject_id=subjects["История"].id,
            due_date=tomorrow + timedelta(days=2),
            text="Эссе про реформы Петра I, 2 страницы",
            text_norm="эссе про реформы петра i 2 страницы",
            created_by=1,
            confirmed_by=[1],
        )
    )

    if not await session.scalar(select(FaqEntry).limit(1)):
        for q, a in FAQ:
            session.add(FaqEntry(question=q, answer=a))

    await session.commit()
    return (
        f"Набила тестовые данные: {len(SUBJECTS)} предмета, "
        f"{len(LESSONS)} пар в расписании, 2 задания, {len(FAQ)} записи в ЧаВо."
    )


async def wipe_demo(session: AsyncSession) -> str:
    await session.execute(delete(Lesson))
    await session.execute(delete(Homework))
    await session.execute(delete(FaqEntry))
    await session.commit()
    return "Расписание, домашка и ЧаВо очищены. Предметы оставила."
