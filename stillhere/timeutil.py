from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import db


def tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def to_local(utc_naive: datetime, tzname: str) -> datetime:
    return utc_naive.replace(tzinfo=timezone.utc).astimezone(tz(tzname))


def parse_hhmm(s: str, default: time = time(9, 30)) -> time:
    try:
        h, m = s.strip().split(":")
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        return default


def ago(then: datetime | None, now: datetime | None = None) -> str:
    if not then:
        return "never"
    secs = int(((now or db.utcnow()) - then).total_seconds())
    if secs < 60:
        return "just now"
    mins = secs // 60
    if mins < 60:
        return f"{mins} min ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return "yesterday" if days == 1 else f"{days} days ago"
