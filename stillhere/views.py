"""Turns raw rows into what the dashboards render. Pure functions, so the public demo uses the same code."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import db, timeutil

DAYS_SHOWN = 30


@dataclass
class Snapshot:
    friend_name: str
    tzname: str
    now: datetime
    checkins: list[dict]
    moods: list[dict]
    last_heard: datetime | None
    paused_until: datetime | None
    last_heartbeat: datetime | None
    buddies: list[str]
    checkin_time: str
    joined: bool = True
    memories: list[dict] = field(default_factory=list)


def snapshot_from_db() -> Snapshot:
    s = db.get_settings()
    friend = db.friend()
    since = db.window(DAYS_SHOWN + 1)
    hb = s.get("last_heartbeat")
    return Snapshot(
        friend_name=friend["name"] if friend else s["friend_name"],
        tzname=s["timezone"],
        now=db.utcnow(),
        checkins=db.checkins_since(since),
        moods=db.moods_since(since),
        last_heard=db.last_friend_message_at(),
        paused_until=db.paused_until(),
        last_heartbeat=datetime.fromisoformat(hb) if hb else None,
        buddies=[b["name"] for b in db.buddies()],
        checkin_time=s["checkin_time"],
        joined=friend is not None,
        memories=db.active_memories(),
    )


def _days(snap: Snapshot) -> list[dict]:
    today = timeutil.to_local(snap.now, snap.tzname).date()
    by_day: dict[date, dict] = {}
    for i in range(DAYS_SHOWN):
        d = today - timedelta(days=DAYS_SHOWN - 1 - i)
        by_day[d] = {"date": d, "status": "none", "score": None, "word": None, "line": None, "is_today": d == today}
    for c in snap.checkins:
        if c["day"] in by_day:
            by_day[c["day"]]["status"] = c["status"]
    for m in snap.moods:
        d = timeutil.to_local(m["at"], snap.tzname).date()
        if d in by_day:
            by_day[d].update(score=m["score"], word=m["word"], line=m["share_line"], status="answered")
    out = []
    for d, e in by_day.items():
        st = e["status"]
        e["kind"] = {
            "answered": "ok", "waiting": "waiting", "nudged": "waiting",
            "escalated": "quiet", "paused": "paused", "none": "none",
        }.get(st, "none")
        if e["kind"] == "waiting" and not e["is_today"]:
            e["kind"] = "quiet"
        e["label"] = "Today" if e["is_today"] else ("Yesterday" if d == today - timedelta(days=1) else f"{d:%a %d %b}")
        out.append(e)
    return out


def pulse(days: list[dict], width: int = 600, height: int = 132) -> dict:
    """An ECG-style line: one beat per day, taller for brighter days, flat when quiet."""
    step = width / len(days)
    base = height * 0.62
    # Days before Ben joined aren't "quiet" days, so the line starts at the first real one.
    start = next((i for i, d in enumerate(days) if d["kind"] != "none"), len(days) - 1)
    path, paused_segments, points = [f"M{start * step:.1f} {base:.1f}"], [], []
    for i, d in enumerate(days):
        if i < start:
            continue
        x = i * step
        if d["kind"] == "ok" and d["score"]:
            amp = 14 + d["score"] * 13
            seq = [(0.18, 0), (0.32, 6), (0.48, -amp), (0.62, 12), (0.76, 0), (1.0, 0)]
            for fx, dy in seq:
                path.append(f"L{x + fx * step:.1f} {base + dy:.1f}")
            points.append({"x": round(x + 0.48 * step, 1), "y": round(base - amp, 1), **_pt(d)})
        else:
            path.append(f"L{x + step:.1f} {base:.1f}")
            if d["kind"] == "paused":
                paused_segments.append((round(x, 1), round(x + step, 1)))
            if d["kind"] in ("quiet", "waiting"):
                points.append({"x": round(x + 0.5 * step, 1), "y": round(base, 1), **_pt(d)})
    return {"d": " ".join(path), "points": points, "paused": paused_segments,
            "width": width, "height": height, "base": round(base, 1)}


def _pt(d: dict) -> dict:
    return {"kind": d["kind"], "score": d["score"], "word": d["word"], "label": d["label"], "line": d["line"]}


def build(snap: Snapshot) -> dict:
    days = _days(snap)
    today = days[-1]
    last7 = days[-7:]
    answered7 = [d for d in last7 if d["kind"] == "ok"]
    streak = 0
    for d in reversed(days):
        if d["kind"] == "ok":
            streak += 1
        elif d["is_today"] and d["kind"] in ("waiting", "none"):
            continue
        else:
            break

    first = snap.friend_name
    if not snap.joined:
        state = ("new", f"Waiting for {first} to join", "Send them their invite link to get started.")
    elif snap.paused_until:
        until = timeutil.to_local(snap.paused_until, snap.tzname)
        state = ("paused", f"{first} is taking a break", f"Check-ins are paused until {until:%a %d %b, %H:%M}. No alerts until then.")
    elif today["kind"] == "ok":
        state = ("ok", f"{first} checked in today", f"Feeling {today['word']} · {today['score']}/5. “{today['line']}”")
    elif today["kind"] == "quiet":
        state = ("quiet", f"{first} has been quiet today",
                 f"Last heard {timeutil.ago(snap.last_heard, snap.now)}. Buddies have been told. A quick call would be lovely.")
    elif today["kind"] == "waiting":
        state = ("waiting", f"Waiting on today's reply", f"Check-in sent. Last heard from {first} {timeutil.ago(snap.last_heard, snap.now)}.")
    else:
        state = ("waiting", f"Today's check-in is at {snap.checkin_time}",
                 f"Last heard from {first} {timeutil.ago(snap.last_heard, snap.now)}.")

    hb_ok = bool(snap.last_heartbeat and snap.now - snap.last_heartbeat < timedelta(minutes=75))
    avg = round(sum(d["score"] for d in answered7) / len(answered7), 1) if answered7 else None
    return {
        "friend_name": first,
        "state": {"kind": state[0], "headline": state[1], "detail": state[2]},
        "last_heard": timeutil.ago(snap.last_heard, snap.now),
        "streak": streak,
        "answered7": len(answered7),
        "avg7": avg,
        "pulse": pulse(days),
        "days": list(reversed([d for d in days if d["kind"] != "none"]))[:14],
        "heartbeat": {"ok": hb_ok, "ago": timeutil.ago(snap.last_heartbeat, snap.now)},
        "buddies": snap.buddies,
        "checkin_time": snap.checkin_time,
        "tzname": snap.tzname,
        "memories": snap.memories,
        "paused": bool(snap.paused_until),
    }
