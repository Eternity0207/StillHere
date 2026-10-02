"""Handles one incoming Telegram update (from the webhook on Render, or from local polling)."""
from __future__ import annotations

import logging
from datetime import timedelta

from . import brain, db, links, telegram, timeutil

log = logging.getLogger(__name__)


def handle_update(update: dict) -> None:
    msg = update.get("message")
    if not msg or msg.get("chat", {}).get("type") != "private":
        return
    chat_id = msg["chat"]["id"]
    sender_name = (msg.get("from") or {}).get("first_name") or "friend"
    text = (msg.get("text") or msg.get("caption") or "").strip()

    if text.startswith("/start"):
        return _start(chat_id, sender_name, text.partition(" ")[2])

    person = db.person_by_chat(chat_id)
    if not person:
        telegram.send(chat_id, "Hi! I'm a private check-in bot. If someone shared an invite link with you, "
                               "please open that link to join.")
        return
    if person["role"] == "friend":
        _from_friend(person, msg, text)
    else:
        _from_buddy(person, text)


def _start(chat_id: int, name: str, code: str) -> None:
    role = links.parse_invite(code) if code else None
    existing = db.person_by_chat(chat_id)
    if not role:
        if existing:
            help_text = brain.HELP_FRIEND if existing["role"] == "friend" else brain.HELP_BUDDY
            telegram.send(chat_id, help_text)
        else:
            telegram.send(chat_id, "Hi! I'm a private check-in bot. Please use the invite link you were sent to join.")
        return

    if role == "friend":
        current = db.friend()
        if current and current["chat_id"] != chat_id:
            telegram.send(chat_id, "This Still Here already has someone it checks in on. "
                                   "Ask whoever set it up to make you a buddy instead.")
            return
        s = db.get_settings()
        person = db.add_person(chat_id, "friend", s["friend_name"] or name)
        db.log_event("joined", f"{person['name']} joined")
        welcome = brain.onboarding_friend(person["name"], [b["name"] for b in db.buddies()])
        telegram.send(chat_id, welcome)
        db.log_message("bot", welcome)
        # The welcome ends with a question, so it counts as today's check-in (no second message this afternoon).
        today = timeutil.to_local(db.utcnow(), s["timezone"]).date()
        if not db.checkin_for_day(today):
            db.create_checkin(today, welcome)
        for b in db.buddies():
            telegram.send(b["chat_id"], f"{person['name']} just joined Still Here 🎉 You'll hear from me if they go quiet.")
    else:
        if (f := db.friend()) and f["chat_id"] == chat_id:
            telegram.send(chat_id, "You're the one I check in on, so you can't be your own buddy 🙂")
            return
        person = db.add_person(chat_id, "buddy", name)
        db.log_event("buddy_joined", name)
        friend = db.friend()
        fname = friend["name"] if friend else db.get_settings()["friend_name"]
        telegram.send(chat_id, f"You're now one of {fname}'s buddies 🫶\n\n{brain.HELP_BUDDY}\n\n"
                               f"Your dashboard: {links.dashboard_url(person)}")
        if friend:
            # Transparency: the friend always knows who can see their check-ins.
            telegram.send(friend["chat_id"], f"heads up: {name} is now one of your buddies. "
                                             f"they'll see your daily mood line, never your messages. /privacy for details.")


# ---------------- friend ----------------

def _from_friend(person: dict, msg: dict, text: str) -> None:
    chat_id, name = person["chat_id"], person["name"]
    cmd, _, arg = text.partition(" ")
    cmd = cmd.lower().split("@")[0]

    if cmd == "/pause":
        days = int(arg) if arg.strip().isdigit() else 1
        days = max(1, min(days, 30))
        until = db.utcnow() + timedelta(days=days)
        db.set_setting("paused_until", until.isoformat())
        db.log_event("paused", f"{days} day(s)")
        telegram.send(chat_id, f"paused for {days} day{'s' if days > 1 else ''}. take care of yourself 💛 /resume anytime.")
        for b in db.buddies():
            telegram.send(b["chat_id"], f"{name} paused check-ins for {days} day{'s' if days > 1 else ''}. "
                                        f"No alerts until then.")
        return
    if cmd == "/resume":
        db.set_setting("paused_until", "")
        db.log_event("resumed")
        telegram.send(chat_id, "welcome back 🙂 check-ins are on again.")
        return
    if cmd == "/time":
        t = timeutil.parse_hhmm(arg, default=None) if arg else None
        if not t:
            telegram.send(chat_id, f"send it like /time 08:45 (currently {db.get_settings()['checkin_time']})")
            return
        db.set_setting("checkin_time", f"{t:%H:%M}")
        telegram.send(chat_id, f"done, i'll check in at {t:%H:%M} from now on.")
        return
    if cmd == "/privacy":
        names = ", ".join(b["name"] for b in db.buddies()) or "nobody yet"
        telegram.send(chat_id, f"your buddies: {names}\n\nthey see a 1-5 mood score and one short line per day, "
                               f"plus an alert if you're quiet for a long time. they never see your messages.\n\n"
                               f"see (and edit) everything here: {links.dashboard_url(person)}")
        return
    if cmd == "/forget":
        db.forget_memory()
        db.log_event("forgot")
        telegram.send(chat_id, "done. i've forgotten everything i'd remembered about you. fresh start 🌱")
        return
    if cmd in ("/help", "/start"):
        telegram.send(chat_id, brain.HELP_FRIEND)
        return
    if cmd.startswith("/"):
        telegram.send(chat_id, brain.HELP_FRIEND)
        return

    image = None
    if msg.get("photo"):
        image = telegram.download_photo(msg["photo"][-1]["file_id"])
    if msg.get("voice") or msg.get("video_note"):
        text = text or "(sent a voice note)"
    if msg.get("sticker"):
        text = text or f"(sent a sticker {msg['sticker'].get('emoji', '')})"
    if not text and not image:
        text = "(sent something)"

    telegram.typing(chat_id)
    history = db.recent_messages()
    db.log_message("friend", text or "(photo)")

    # Any reply at all is a sign of life: close every open check-in.
    open_ci = db.open_checkin()
    was_escalated = False
    while open_ci:
        was_escalated = was_escalated or open_ci["status"] == "escalated"
        db.update_checkin(open_ci["id"], status="answered", answered_at=db.utcnow())
        open_ci = db.open_checkin()
    today_ci = db.checkin_for_day(timeutil.to_local(db.utcnow(), db.get_settings()["timezone"]).date())

    result = brain.understand(name, db.active_memories(), history, text, image=image)
    reply = brain.crisis_reply(name) if result["concern"] == "high" else result["reply"]
    telegram.send(chat_id, reply)
    db.log_message("bot", reply)

    db.add_mood(result["mood_score"], result["mood_word"], result["share_line"], today_ci["id"] if today_ci else None)
    if result["memory"]:
        db.add_memory(result["memory"])

    if result["concern"] == "high":
        db.log_event("crisis", "buddies alerted")
        for b in db.buddies():
            telegram.send(b["chat_id"], brain.crisis_alert_text(name, b["name"]))
    elif was_escalated:
        db.log_event("back", result["share_line"])
        for b in db.buddies():
            telegram.send(b["chat_id"], brain.back_text(name, result["share_line"]))


# ---------------- buddy ----------------

def _from_buddy(person: dict, text: str) -> None:
    chat_id = person["chat_id"]
    cmd, _, arg = text.partition(" ")
    cmd = cmd.lower().split("@")[0]
    friend = db.friend()

    if cmd == "/status":
        telegram.send(chat_id, status_line(friend))
    elif cmd == "/note":
        if not friend:
            telegram.send(chat_id, "They haven't joined yet. Send them the invite link from the dashboard.")
        elif not arg.strip():
            telegram.send(chat_id, "Write it like: /note thinking of you, good luck today!")
        else:
            send_note(person["name"], arg.strip())
            telegram.send(chat_id, "Delivered 💌")
    elif cmd == "/dashboard":
        telegram.send(chat_id, links.dashboard_url(person))
    elif cmd == "/leave":
        db.remove_person(chat_id)
        telegram.send(chat_id, "You've left. Thanks for looking out for them 🫶")
        if friend:
            telegram.send(friend["chat_id"], f"fyi: {person['name']} is no longer a buddy.")
    else:
        telegram.send(chat_id, brain.HELP_BUDDY)


def send_note(from_name: str, note: str) -> bool:
    friend = db.friend()
    if not friend:
        return False
    text = f"💌 a note from {from_name}:\n\n{note[:600]}"
    telegram.send(friend["chat_id"], text)
    db.log_message("bot", text)
    db.log_event("note", from_name)
    return True


def status_line(friend: dict | None) -> str:
    if not friend:
        return "Your friend hasn't joined yet."
    name = friend["name"]
    if db.paused_until():
        return f"{name} has paused check-ins for a bit."
    last = db.last_friend_message_at()
    moods = db.moods_since(db.window(2))
    ci = db.open_checkin()
    if ci:
        return f"{name} hasn't replied to today's check-in yet (sent {timeutil.ago(ci['sent_at'])}). Last heard: {timeutil.ago(last)}."
    if moods:
        m = moods[-1]
        return f"{name} checked in {timeutil.ago(m['at'])}: feeling {m['word']} ({m['score']}/5). “{m['share_line']}”"
    return f"Last heard from {name}: {timeutil.ago(last)}."
