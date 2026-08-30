"""ORM-модели. Одна таблица — один класс, все в одном модуле для простоты миграций."""

from __future__ import annotations

import enum
from datetime import date, datetime, time

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.db.base import Base, TimestampMixin, utcnow


class Role(enum.StrEnum):
    student = "student"
    admin = "admin"


class WeekParity(enum.StrEnum):
    any = "any"      # каждую неделю
    odd = "odd"      # числитель / нечётная
    even = "even"    # знаменатель / чётная


class HomeworkStatus(enum.StrEnum):
    unconfirmed = "unconfirmed"
    confirmed = "confirmed"


class ReminderRepeat(enum.StrEnum):
    none = "none"
    daily = "daily"
    weekly = "weekly"
    before_each_lesson = "before_each_lesson"
    evening_digest = "evening_digest"


class KbCategory(enum.StrEnum):
    teacher = "teacher"
    department = "department"
    process = "process"
    general = "general"


# ─────────────────────────────── Люди ────────────────────────────────────


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL — запись из списка группы, человек ещё не активировал бота (/start)
    tg_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(200))
    full_name_norm: Mapped[str] = mapped_column(String(200), default="", index=True)
    role: Mapped[Role] = mapped_column(String(16), default=Role.student)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    birthday_day: Mapped[int | None] = mapped_column(Integer)
    birthday_month: Mapped[int | None] = mapped_column(Integer)
    birthday_year: Mapped[int | None] = mapped_column(Integer)

    reminders: Mapped[list[Reminder]] = relationship(back_populates="user")
    prefs: Mapped[UserReminderPrefs | None] = relationship(
        back_populates="user", uselist=False
    )

    @property
    def is_admin(self) -> bool:
        return self.role == Role.admin


# ─────────────────────────── Учебная часть ───────────────────────────────


class Subject(Base, TimestampMixin):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    short_name: Mapped[str | None] = mapped_column(String(60))
    thread_id: Mapped[int | None] = mapped_column(BigInteger)  # топик супергруппы
    teacher_kb_id: Mapped[int | None] = mapped_column(ForeignKey("kb_entries.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    lessons: Mapped[list[Lesson]] = relationship(back_populates="subject")


class Lesson(Base, TimestampMixin):
    """Шаблон одной пары в недельной сетке."""

    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    weekday: Mapped[int] = mapped_column(Integer)  # 0 = понедельник
    pair_no: Mapped[int] = mapped_column(Integer)
    starts_at: Mapped[time] = mapped_column(Time)
    ends_at: Mapped[time | None] = mapped_column(Time)
    week_parity: Mapped[WeekParity] = mapped_column(String(8), default=WeekParity.any)
    kind: Mapped[str | None] = mapped_column(String(32))  # лекция / практика / лаб
    room: Mapped[str | None] = mapped_column(String(64))
    teacher: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(String(300))

    subject: Mapped[Subject] = relationship(back_populates="lessons")


class Homework(Base, TimestampMixin):
    __tablename__ = "homework"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    due_date: Mapped[date] = mapped_column(Date, index=True)
    text: Mapped[str] = mapped_column(Text)
    text_norm: Mapped[str] = mapped_column(Text, default="")
    ai_parsed: Mapped[dict | None] = mapped_column(JSON)
    attachments: Mapped[list] = mapped_column(JSON, default=list)  # list[file_id]
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[HomeworkStatus] = mapped_column(
        String(16), default=HomeworkStatus.unconfirmed
    )
    confirmations: Mapped[int] = mapped_column(Integer, default=1)
    confirmed_by: Mapped[list] = mapped_column(JSON, default=list)  # list[user_id]
    published_at: Mapped[datetime | None] = mapped_column()

    subject: Mapped[Subject] = relationship()


# ──────────────────────────── Напоминания ────────────────────────────────


class Reminder(Base, TimestampMixin):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(400))
    fire_at: Mapped[datetime] = mapped_column(index=True)  # UTC
    lead_minutes: Mapped[int] = mapped_column(Integer, default=0)
    repeat: Mapped[ReminderRepeat] = mapped_column(
        String(24), default=ReminderRepeat.none
    )
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fired_at: Mapped[datetime | None] = mapped_column()

    user: Mapped[User | None] = relationship(back_populates="reminders")


class UserReminderPrefs(Base, TimestampMixin):
    __tablename__ = "user_reminder_prefs"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    lesson_lead_minutes: Mapped[int | None] = mapped_column(Integer)  # None = выкл
    evening_digest_time: Mapped[time | None] = mapped_column(Time)
    dnd_start: Mapped[time | None] = mapped_column(Time)
    dnd_end: Mapped[time | None] = mapped_column(Time)

    user: Mapped[User] = relationship(back_populates="prefs")


# ────────────────────────────── ИИ / KB ──────────────────────────────────


class KbEntry(Base, TimestampMixin):
    __tablename__ = "kb_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[KbCategory] = mapped_column(String(16), default=KbCategory.general)
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    attrs: Mapped[dict] = mapped_column(JSON, default=dict)
    source_url: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual / parsed
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (UniqueConstraint("source_url", "title", name="kb_source_title"),)


class AiQueryLog(Base):
    __tablename__ = "ai_query_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(16))  # assistant / homework / selftest
    question: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class EscalatedQuestion(Base, TimestampMixin):
    """Вопрос, который ИИ не смог закрыть — переслан старосте."""

    __tablename__ = "escalated_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    answered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)


# ─────────────────────────────── ЧаВо ────────────────────────────────────


class FaqEntry(Base, TimestampMixin):
    __tablename__ = "faq_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(String(400))
    answer: Mapped[str] = mapped_column(Text)
    keywords: Mapped[str] = mapped_column(String(400), default="")
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Holiday(Base, TimestampMixin):
    """Праздник — бот поздравляет группу в этот день утром."""

    __tablename__ = "holidays"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    month: Mapped[int] = mapped_column(Integer)
    day: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class MediaItem(Base, TimestampMixin):
    """Картинка, загруженная старостой: для поздравлений с ДР или для «мема дня»."""

    __tablename__ = "media_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # birthday / meme
    file_id: Mapped[str] = mapped_column(String(300))
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


# ───────────────── Заготовки под следующие этапы ─────────────────────────


class AbsenceRecord(Base, TimestampMixin):
    __tablename__ = "absence_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    on_date: Mapped[date] = mapped_column(Date, index=True)
    pair_no: Mapped[int | None] = mapped_column(Integer)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"))
    reason: Mapped[str | None] = mapped_column(String(300))
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    marked_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    is_excused: Mapped[bool] = mapped_column(Boolean, default=False)


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    doc_type: Mapped[str] = mapped_column(String(64))
    comment: Mapped[str | None] = mapped_column(String(500))
    file_id: Mapped[str] = mapped_column(String(300))
    file_unique_id: Mapped[str | None] = mapped_column(String(120))
    mime: Mapped[str | None] = mapped_column(String(120))
    request_id: Mapped[int | None] = mapped_column(ForeignKey("document_requests.id"))


class DocumentRequest(Base, TimestampMixin):
    __tablename__ = "document_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    doc_type: Mapped[str] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(String(500))
    deadline: Mapped[date | None] = mapped_column(Date)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    fulfilled_at: Mapped[datetime | None] = mapped_column()


class DefenseEvent(Base, TimestampMixin):
    __tablename__ = "defense_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"))
    on_date: Mapped[date | None] = mapped_column(Date)
    starts_at: Mapped[time | None] = mapped_column(Time)
    location: Mapped[str | None] = mapped_column(String(200))
    slots_open: Mapped[bool] = mapped_column(Boolean, default=False)


class DefenseSlot(Base, TimestampMixin):
    __tablename__ = "defense_slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("defense_events.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    position: Mapped[int] = mapped_column(Integer)
    at_time: Mapped[time | None] = mapped_column(Time)
