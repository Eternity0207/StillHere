"""Everything Still Here asks Gemma to do, plus hand-written fallbacks so a model hiccup never means silence."""
from __future__ import annotations

import logging
import random
import re
from datetime import datetime

from . import config, gemma

log = logging.getLogger(__name__)

VOICE = """You are "Still Here", a tiny daily check-in companion that lives in {name}'s Telegram.
A friend who cares about {name} set you up so {name} never goes too long without someone noticing.

How you talk:
- Like a warm, slightly funny friend texting. Lowercase-casual is fine. 1-3 short sentences.
- Ask at most one question. Never lecture, never guilt-trip, never sound like a wellness app.
- Use what you remember about {name} naturally, the way a friend would ("how did the dentist go?").
- At most one emoji, and only if it fits.
- Refer to {name} by name or as "you"; never guess their pronouns.
- You are not a therapist. If {name} is struggling, be kind and present, and gently encourage talking to a real person.
"""

# Deterministic safety net, applied regardless of what the model says.
CRISIS = re.compile(
    r"\b(kill myself|killing myself|suicid\w*|end it all|end my life|want to die|don'?t want to (be alive|live|wake up)"
    r"|self[- ]?harm|hurt myself|no reason to live|better off without me)\b",
    re.I,
)

FALLBACK_CHECKINS = [
    "morning {name} ☀️ how's today looking?",
    "hey {name}, just checking in. how are you doing today?",
    "good morning! what's one thing on your plate today, {name}?",
    "hi {name} 👋 how did you sleep?",
    "morning {name}. quick pulse check: how are you feeling, 1 to 5?",
]
FALLBACK_NUDGES = [
    "no pressure, {name}. even a single emoji tells me you're okay 🙂",
    "just a gentle tap on the shoulder. a 👍 is plenty, {name}.",
    "still here whenever you are. one word is enough.",
]


def _fmt_memories(memories: list[dict]) -> str:
    return "\n".join(f"- {m['text']}" for m in memories) or "- (nothing yet)"


def _fmt_history(history: list[dict], name: str) -> str:
    lines = []
    for m in history:
        who = name if m["sender"] == "friend" else "you"
        lines.append(f"{who}: {m['text']}")
    return "\n".join(lines) or "(no messages yet)"


def write_checkin(name: str, memories: list[dict], recent_words: list[str], local_now: datetime) -> str:
    prompt = f"""Write today's morning check-in message to {name}.
It is {local_now:%A, %d %B} and {local_now:%H:%M} for {name}.
What you remember about {name}:
{_fmt_memories(memories)}
{name}'s mood words over the last few days (oldest first): {", ".join(recent_words) or "unknown"}

If a remembered thing is clearly happening around now, ask about it. Otherwise keep it simple and varied.
If the last few days looked low, be a bit softer. Output only the message text."""
    try:
        text = gemma.generate(VOICE.format(name=name), prompt, temperature=0.95)
        return text.strip().strip('"') or random.choice(FALLBACK_CHECKINS).format(name=name)
    except gemma.GemmaError as e:
        log.warning("checkin fallback: %s", e)
        return random.choice(FALLBACK_CHECKINS).format(name=name)


def write_nudge(name: str, checkin_message: str) -> str:
    prompt = f"""This morning you sent {name}: "{checkin_message}"
They haven't replied in a few hours. Send ONE gentle, low-effort follow-up that makes replying feel tiny
(an emoji is enough). Absolutely no guilt. Output only the message text."""
    try:
        return gemma.generate(VOICE.format(name=name), prompt, temperature=0.9).strip().strip('"')
    except gemma.GemmaError:
        return random.choice(FALLBACK_NUDGES).format(name=name)


def understand(name: str, memories: list[dict], history: list[dict], text: str,
               image: tuple[str, str] | None = None) -> dict:
    """Reply to the friend and extract what buddies may see. Returns a normalised dict."""
    prompt = f"""What you remember about {name}:
{_fmt_memories(memories)}

Recent conversation (oldest first):
{_fmt_history(history, name)}

{name} just sent: {text or "(a photo)"}

Respond with a JSON object with exactly these keys:
- "reply": your text back to {name} (1-3 short sentences, in your voice).
- "mood_score": integer 1-5 (1 = really struggling, 3 = okay, 5 = great). Judge from tone, not just words.
- "mood_word": one lowercase word for their mood (e.g. "tired", "bright", "stressed", "okay").
- "share_line": a one-line, third-person summary for {name}'s buddies, max 14 words. Keep it general and kind.
  NEVER include secrets, other people's names, health/medical details, money, or anything {name} asked to keep private.
  If in doubt, write something like "Checked in, sounds okay."
- "memory": one short NEW fact worth remembering for future check-ins (an upcoming event, a goal, a hobby) that is
  not already in the list above, or null. Write it without pronouns, e.g. "Second-round interview next week".
- "concern": "none", "low", or "high". Use "high" only for signs of self-harm, suicide, or immediate danger."""
    try:
        data = gemma.generate_json(VOICE.format(name=name), prompt, image=image, temperature=0.7)
    except gemma.GemmaError as e:
        log.warning("understand fallback: %s", e)
        data = {}
    out = {
        "reply": str(data.get("reply") or "got it 💛 thanks for checking in."),
        "mood_score": _clamp_score(data.get("mood_score")),
        "mood_word": (str(data.get("mood_word") or "").lower().split() or ["okay"])[0][:30],
        "share_line": str(data.get("share_line") or "Checked in.")[:200],
        "memory": data.get("memory") if isinstance(data.get("memory"), str) else None,
        "concern": data.get("concern") if data.get("concern") in ("none", "low", "high") else "none",
    }
    if CRISIS.search(text or ""):
        out["concern"] = "high"
    if out["concern"] == "high":
        out["mood_score"] = 1
        out["share_line"] = "Is having a really hard time and could use you right now."
    return out


def _clamp_score(v) -> int:
    try:
        return max(1, min(5, int(v)))
    except (TypeError, ValueError):
        return 3


def crisis_reply(name: str) -> str:
    return (f"{name}, I'm really glad you told me. You don't have to carry this alone, and I've let your buddies "
            f"know you could use someone right now. {config.HELPLINE_TEXT}")


def escalation_text(friend_name: str, buddy_name: str, hours: int, last_seen: str) -> str:
    return (f"Hey {buddy_name}, quick heads-up from Still Here 🫶\n\n"
            f"{friend_name} hasn't answered today's check-in ({hours}h now) and I last heard from them {last_seen}. "
            f"It's probably nothing (dead phone, busy day) but a quick call or text from you would be lovely.\n\n"
            f"I'll let you know as soon as they reply.")


def crisis_alert_text(friend_name: str, buddy_name: str) -> str:
    return (f"{buddy_name}, {friend_name} just told me they're having a really hard time. "
            f"Please reach out to them directly as soon as you can, a call is best. "
            f"(I've shared support resources with them too.)")


def back_text(friend_name: str, line: str) -> str:
    return f"Good news: {friend_name} just checked in 💛\n“{line}”"


def write_digest(friend_name: str, buddy_name: str, days: list[dict]) -> str:
    """days: [{"day": "Mon", "status": "answered", "word": "tired", "score": 3, "line": "..."}]"""
    rows = "\n".join(
        f"- {d['day']}: {d['status']}" + (f", mood {d['score']}/5 ({d['word']}): {d['line']}" if d.get("score") else "")
        for d in days
    )
    answered = sum(1 for d in days if d.get("score"))
    prompt = f"""Write a short Sunday note to {buddy_name} about how {friend_name}'s week went, based ONLY on this:
{rows}

4-6 sentences max, warm and plain. Mention the overall shape of the week and anything worth following up on
in a call. If something looks low, suggest one small kind thing {buddy_name} could do. No headings, no bullet points.
Refer to {friend_name} by name or as "they"; never guess pronouns.
Output only the message."""
    try:
        body = gemma.generate(
            "You write short, warm weekly notes to someone who cares about a friend. Never invent details.",
            prompt, temperature=0.7,
        ).strip()
    except gemma.GemmaError:
        body = f"{friend_name} checked in on {answered} of {len(days)} days this week."
    return f"🗓 {friend_name}'s week\n\n{body}"


def onboarding_friend(name: str, buddy_names: list[str]) -> str:
    who = ", ".join(buddy_names) if buddy_names else "your buddy (once they join)"
    return (f"hi {name} 👋 i'm Still Here.\n\n"
            f"every morning i'll send you one small message. reply with anything at all (a word, an emoji, a photo) "
            f"and that's it. if you go quiet for a long while, i'll quietly ask {who} to check on you.\n\n"
            f"what they see: a mood score and one short line a day. never your actual messages.\n"
            f"/privacy shows you exactly what's shared · /pause when you need a break · /forget wipes my memory.\n\n"
            f"so, to start: how are you today?")


HELP_FRIEND = ("I send one small check-in each morning. Reply with anything and you're done.\n\n"
               "/pause 3: pause for 3 days\n/resume: turn check-ins back on\n/time 08:45: change the time\n"
               "/privacy: see exactly what your buddies see\n/forget: wipe everything I remember")
HELP_BUDDY = ("You're a buddy 🫶 I'll message you if your friend goes quiet, plus a short note every Sunday.\n\n"
              "/status: how are they doing?\n/note <text>: send them a little note through me\n"
              "/dashboard: open your dashboard\n/leave: stop being a buddy")
