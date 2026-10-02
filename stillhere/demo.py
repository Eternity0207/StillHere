"""A made-up month in Ben's life, so anyone can see the dashboards without a Telegram account.

Ben moved to a new city for a first job and lives alone. Nothing here is real data.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from . import db, timeutil
from .views import Snapshot

TZ = "Asia/Kolkata"

# (days_ago, status, score, word, share_line); None score = no mood that day
STORY = [
    (29, "answered", 4, "excited", "First week at the new job, nervous but excited."),
    (28, "answered", 3, "tired", "Long onboarding day, slept early."),
    (27, "answered", 4, "curious", "Found a good chai place near the flat."),
    (26, "answered", 3, "okay", "Quiet day, cooked dinner for the first time."),
    (25, "answered", 2, "lonely", "Weekend felt a bit empty in a new city."),
    (24, "answered", 3, "better", "Went for a long walk, feeling better."),
    (23, "answered", 4, "proud", "Shipped a first small fix at work."),
    (22, "answered", 3, "busy", "Busy, short reply, all fine."),
    (21, "escalated", None, None, None),
    (20, "answered", 4, "sheepish", "Phone died yesterday, all good, sorry for the scare."),
    (19, "answered", 4, "good", "Team lunch, starting to know people."),
    (18, "answered", 5, "bright", "Great day, joined a weekend football group."),
    (17, "answered", 4, "sore", "First football game, legs destroyed, very happy."),
    (16, "answered", 3, "okay", "Regular workday, nothing special."),
    (15, "paused", None, None, None),
    (14, "paused", None, None, None),
    (13, "answered", 3, "homesick", "Back from visiting family, a bit homesick."),
    (12, "answered", 2, "stressed", "Deadline week, stressed and sleeping badly."),
    (11, "answered", 2, "drained", "Long day, skipped dinner."),
    (10, "answered", 2, "low", "Feeling low, says it's mostly the deadline."),
    (9, "answered", 3, "relieved", "Deadline done, relieved."),
    (8, "answered", 3, "slow", "Slow morning, catching up on sleep."),
    (7, "answered", 4, "lighter", "Called home, feeling lighter."),
    (6, "answered", 4, "good", "Football again, scored a goal."),
    (5, "answered", 4, "steady", "Steady week so far."),
    (4, "answered", 3, "meh", "Rainy day, stayed in."),
    (3, "answered", 4, "happy", "Cooked for flatmates, it went well."),
    (2, "answered", 5, "great", "Got good feedback from the manager."),
    (1, "answered", 4, "chill", "Easy evening, laundry and a movie."),
    (0, "answered", 4, "hopeful", "Looking forward to the team offsite this week."),
]

MEMORIES = [
    "Moved to a new city for a first job",
    "Plays weekend football with a group from work",
    "Team offsite later this week",
    "Calls home on Sundays",
    "Trying to cook more instead of ordering in",
]


def snapshot() -> Snapshot:
    now = db.utcnow()
    tz = timeutil.tz(TZ)
    local_today = timeutil.to_local(now, TZ).date()
    checkins, moods = [], []
    for i, (ago, status, score, word, line) in enumerate(STORY):
        day = local_today - timedelta(days=ago)
        sent_local = datetime.combine(day, time(9, 30), tz)
        sent = sent_local.astimezone(timezone.utc).replace(tzinfo=None)
        if sent > now:  # today's check-in hasn't gone out yet in real time; pretend it went out early
            sent = now - timedelta(minutes=50)
        checkins.append({"id": i, "day": day, "sent_at": sent, "status": status})
        if score:
            moods.append({"at": min(sent + timedelta(minutes=40 + 7 * (i % 5)), now), "checkin_id": i,
                          "score": score, "word": word, "share_line": line})
    return Snapshot(
        friend_name="Ben",
        tzname=TZ,
        now=now,
        checkins=checkins,
        moods=moods,
        last_heard=moods[-1]["at"],
        paused_until=None,
        last_heartbeat=now - timedelta(minutes=6),
        buddies=["Sam", "Maya"],
        checkin_time="09:30",
        memories=[{"id": i, "text": t, "at": now - timedelta(days=20 - 4 * i)} for i, t in enumerate(MEMORIES)],
    )
