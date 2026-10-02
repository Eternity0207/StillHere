"""Schema and small data helpers. Works on SQLite locally and Render Postgres in production.

All timestamps are stored as naive UTC.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Integer, MetaData, String, Table, Text,
    create_engine, delete, insert, select, update,
)

from . import config

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, future=True)
md = MetaData()

people = Table(
    "people", md,
    Column("id", Integer, primary_key=True),
    Column("chat_id", BigInteger, unique=True, nullable=False),
    Column("role", String(16), nullable=False),  # friend | buddy
    Column("name", String(80), nullable=False),
    Column("joined_at", DateTime, nullable=False),
)

settings = Table(
    "settings", md,
    Column("key", String(64), primary_key=True),
    Column("value", Text, nullable=False),
)

checkins = Table(
    "checkins", md,
    Column("id", Integer, primary_key=True),
    Column("day", Date, unique=True, nullable=False),  # the friend's local date
    Column("sent_at", DateTime, nullable=False),
    Column("message", Text, nullable=False),
    Column("status", String(16), nullable=False),  # waiting | nudged | escalated | answered | paused
    Column("nudged_at", DateTime),
    Column("escalated_at", DateTime),
    Column("answered_at", DateTime),
)

# Raw conversation. Private to the friend; never shown to buddies.
messages = Table(
    "messages", md,
    Column("id", Integer, primary_key=True),
    Column("at", DateTime, nullable=False),
    Column("sender", String(16), nullable=False),  # friend | bot
    Column("text", Text, nullable=False),
)

# What buddies are allowed to see: a score, a word, and a one-line summary the model writes to be shareable.
moods = Table(
    "moods", md,
    Column("id", Integer, primary_key=True),
    Column("at", DateTime, nullable=False),
    Column("checkin_id", Integer, ForeignKey("checkins.id")),
    Column("score", Integer, nullable=False),  # 1..5
    Column("word", String(40), nullable=False),
    Column("share_line", Text, nullable=False),
)

memories = Table(
    "memories", md,
    Column("id", Integer, primary_key=True),
    Column("at", DateTime, nullable=False),
    Column("text", Text, nullable=False),
    Column("active", Boolean, nullable=False, default=True),
)

events = Table(
    "events", md,
    Column("id", Integer, primary_key=True),
    Column("at", DateTime, nullable=False),
    Column("kind", String(32), nullable=False),
    Column("detail", Text, nullable=False, default=""),
)

DEFAULTS = {
    "friend_name": config.FRIEND_NAME,
    "timezone": config.DEFAULT_TIMEZONE,
    "checkin_time": "09:30",
    "nudge_after_h": "4",
    "escalate_after_h": "10",
    "digest_weekday": "6",  # Sunday (Mon=0)
    "digest_time": "19:00",
    "paused_until": "",
    "last_heartbeat": "",
    "public_url": config.PUBLIC_URL,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def init() -> None:
    md.create_all(engine)
    with engine.begin() as c:
        have = {r.key for r in c.execute(select(settings.c.key))}
        for k, v in DEFAULTS.items():
            if k not in have:
                c.execute(insert(settings).values(key=k, value=v))


# ---------- settings ----------

def get_settings() -> dict[str, str]:
    with engine.connect() as c:
        out = dict(DEFAULTS)
        out.update({r.key: r.value for r in c.execute(select(settings))})
        return out


def set_setting(key: str, value: str) -> None:
    with engine.begin() as c:
        if c.execute(update(settings).where(settings.c.key == key).values(value=value)).rowcount == 0:
            c.execute(insert(settings).values(key=key, value=value))


def paused_until() -> datetime | None:
    raw = get_settings()["paused_until"]
    if not raw:
        return None
    until = datetime.fromisoformat(raw)
    return until if until > utcnow() else None


# ---------- people ----------

def friend() -> dict | None:
    with engine.connect() as c:
        r = c.execute(select(people).where(people.c.role == "friend")).mappings().first()
        return dict(r) if r else None


def buddies() -> list[dict]:
    with engine.connect() as c:
        return [dict(r) for r in c.execute(select(people).where(people.c.role == "buddy")).mappings()]


def person_by_chat(chat_id: int) -> dict | None:
    with engine.connect() as c:
        r = c.execute(select(people).where(people.c.chat_id == chat_id)).mappings().first()
        return dict(r) if r else None


def add_person(chat_id: int, role: str, name: str) -> dict:
    with engine.begin() as c:
        c.execute(delete(people).where(people.c.chat_id == chat_id))
        c.execute(insert(people).values(chat_id=chat_id, role=role, name=name[:80], joined_at=utcnow()))
    return person_by_chat(chat_id)


def remove_person(chat_id: int) -> None:
    with engine.begin() as c:
        c.execute(delete(people).where(people.c.chat_id == chat_id))


# ---------- conversation & memory ----------

def log_message(sender: str, text: str) -> None:
    with engine.begin() as c:
        c.execute(insert(messages).values(at=utcnow(), sender=sender, text=text))


def recent_messages(limit: int = 14) -> list[dict]:
    with engine.connect() as c:
        rows = c.execute(select(messages).order_by(messages.c.id.desc()).limit(limit)).mappings()
        return [dict(r) for r in rows][::-1]


def last_friend_message_at() -> datetime | None:
    with engine.connect() as c:
        return c.execute(
            select(messages.c.at).where(messages.c.sender == "friend").order_by(messages.c.id.desc()).limit(1)
        ).scalar()


def active_memories(limit: int = 30) -> list[dict]:
    with engine.connect() as c:
        rows = c.execute(
            select(memories).where(memories.c.active.is_(True)).order_by(memories.c.id.desc()).limit(limit)
        ).mappings()
        return [dict(r) for r in rows]


def add_memory(text: str) -> None:
    text = text.strip()
    if not text:
        return
    with engine.begin() as c:
        known = {r.lower().strip(" .") for r in c.execute(select(memories.c.text).where(memories.c.active.is_(True))).scalars()}
        if text.lower().strip(" .") not in known:
            c.execute(insert(memories).values(at=utcnow(), text=text[:300], active=True))


def forget_memory(memory_id: int | None = None) -> None:
    with engine.begin() as c:
        q = update(memories).values(active=False)
        if memory_id is not None:
            q = q.where(memories.c.id == memory_id)
        c.execute(q)


# ---------- check-ins & moods ----------

def checkin_for_day(day) -> dict | None:
    with engine.connect() as c:
        r = c.execute(select(checkins).where(checkins.c.day == day)).mappings().first()
        return dict(r) if r else None


def open_checkin() -> dict | None:
    """The most recent check-in still waiting on a reply."""
    with engine.connect() as c:
        r = c.execute(
            select(checkins).where(checkins.c.status.in_(("waiting", "nudged", "escalated")))
            .order_by(checkins.c.sent_at.desc()).limit(1)
        ).mappings().first()
        return dict(r) if r else None


def create_checkin(day, message: str, status: str = "waiting") -> dict:
    with engine.begin() as c:
        c.execute(insert(checkins).values(day=day, sent_at=utcnow(), message=message, status=status))
    return checkin_for_day(day)


def update_checkin(checkin_id: int, **values) -> None:
    with engine.begin() as c:
        c.execute(update(checkins).where(checkins.c.id == checkin_id).values(**values))


def add_mood(score: int, word: str, share_line: str, checkin_id: int | None) -> None:
    with engine.begin() as c:
        c.execute(insert(moods).values(
            at=utcnow(), checkin_id=checkin_id, score=max(1, min(5, int(score))),
            word=word[:40], share_line=share_line[:280],
        ))


def checkins_since(since: datetime) -> list[dict]:
    with engine.connect() as c:
        rows = c.execute(select(checkins).where(checkins.c.sent_at >= since).order_by(checkins.c.day)).mappings()
        return [dict(r) for r in rows]


def moods_since(since: datetime) -> list[dict]:
    with engine.connect() as c:
        rows = c.execute(select(moods).where(moods.c.at >= since).order_by(moods.c.at)).mappings()
        return [dict(r) for r in rows]


# ---------- events ----------

def log_event(kind: str, detail: str = "") -> None:
    with engine.begin() as c:
        c.execute(insert(events).values(at=utcnow(), kind=kind, detail=detail))


def events_since(since: datetime, kinds: tuple[str, ...] | None = None) -> list[dict]:
    with engine.connect() as c:
        q = select(events).where(events.c.at >= since)
        if kinds:
            q = q.where(events.c.kind.in_(kinds))
        return [dict(r) for r in c.execute(q.order_by(events.c.at)).mappings()]


def has_event_since(kind: str, since: datetime) -> bool:
    return bool(events_since(since, (kind,)))


def window(days: int) -> datetime:
    return utcnow() - timedelta(days=days)
