"""The heartbeat. A Render Cron Job runs `python -m stillhere.heartbeat` every 15 minutes.

Each beat decides, from the friend's local clock, whether it's time to:
  1. send the morning check-in,
  2. nudge gently if there's no reply,
  3. quietly alert buddies if the silence lasts,
  4. send buddies the Sunday digest.
Every beat is stateless and idempotent, so a missed or doubled run is harmless.
"""
from __future__ import annotations

import logging
import sys
from datetime import timedelta

from . import brain, db, telegram, timeutil

log = logging.getLogger("stillhere.heartbeat")


def tick() -> list[str]:
    db.init()
    s = db.get_settings()
    now = db.utcnow()
    local = timeutil.to_local(now, s["timezone"])
    db.set_setting("last_heartbeat", now.isoformat())
    done: list[str] = []

    friend = db.friend()
    if not friend:
        return ["waiting for the friend to join"]
    name = friend["name"]
    paused = db.paused_until()

    # 1. Morning check-in
    today = local.date()
    if local.time() >= timeutil.parse_hhmm(s["checkin_time"]) and not db.checkin_for_day(today):
        last_heard = db.last_friend_message_at()
        if paused:
            db.create_checkin(today, "(paused)", status="paused")
            done.append("check-in skipped: paused")
        elif local.hour >= 22:
            db.create_checkin(today, "(too late to check in)", status="paused")
            done.append("check-in skipped: too late locally")
        elif last_heard and now - last_heard < timedelta(hours=3):
            ci = db.create_checkin(today, "(already chatting)", status="answered")
            db.update_checkin(ci["id"], answered_at=last_heard)
            done.append("check-in not needed: they messaged recently")
        else:
            recent = [m["word"] for m in db.moods_since(db.window(4))][-5:]
            text = brain.write_checkin(name, db.active_memories(), recent, local)
            telegram.send(friend["chat_id"], text)
            db.log_message("bot", text)
            db.create_checkin(today, text)
            done.append(f"check-in sent: {text!r}")

    # 2 & 3. Follow up on silence
    ci = db.open_checkin()
    if ci and not paused:
        hours = (now - ci["sent_at"]).total_seconds() / 3600
        nudge_after = float(s["nudge_after_h"])
        escalate_after = float(s["escalate_after_h"])
        if ci["status"] == "waiting" and hours >= nudge_after and 8 <= local.hour < 22:
            text = brain.write_nudge(name, ci["message"])
            telegram.send(friend["chat_id"], text)
            db.log_message("bot", text)
            db.update_checkin(ci["id"], status="nudged", nudged_at=now)
            done.append("nudged")
        if ci["status"] in ("waiting", "nudged") and hours >= escalate_after:
            last_seen = timeutil.ago(db.last_friend_message_at(), now)
            buddies = db.buddies()
            for b in buddies:
                telegram.send(b["chat_id"], brain.escalation_text(name, b["name"], int(hours), last_seen))
            db.update_checkin(ci["id"], status="escalated", escalated_at=now)
            db.log_event("escalated", f"{int(hours)}h quiet, {len(buddies)} buddies told")
            done.append(f"escalated to {len(buddies)} buddies")

    # 4. Sunday digest
    if (local.weekday() == int(s["digest_weekday"])
            and local.time() >= timeutil.parse_hhmm(s["digest_time"])
            and not db.has_event_since("digest", now - timedelta(hours=20))):
        buddies = db.buddies()
        if buddies:
            days = week_summary(s["timezone"])
            for b in buddies:
                telegram.send(b["chat_id"], brain.write_digest(name, b["name"], days))
            done.append(f"digest sent to {len(buddies)}")
        db.log_event("digest", f"{len(buddies)} buddies")

    return done or ["all quiet"]


def week_summary(tzname: str) -> list[dict]:
    cis = {c["id"]: c for c in db.checkins_since(db.window(7))}
    by_day: dict = {}
    for c in cis.values():
        by_day[c["day"]] = {"day": f"{c['day']:%a}", "status": c["status"]}
    for m in db.moods_since(db.window(7)):
        day = timeutil.to_local(m["at"], tzname).date()
        entry = by_day.setdefault(day, {"day": f"{day:%a}", "status": "answered"})
        entry.update(score=m["score"], word=m["word"], line=m["share_line"])  # latest mood of the day wins
    return [by_day[d] for d in sorted(by_day)]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for line in tick():
        log.info(line)


if __name__ == "__main__":
    sys.exit(main())
