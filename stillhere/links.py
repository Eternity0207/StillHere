"""Signed, unguessable links: invites, per-person dashboards, and the webhook path."""
from __future__ import annotations

import hashlib
import hmac

from . import config, db, telegram


def _sig(msg: str, n: int = 16) -> str:
    return hmac.new(config.SECRET_KEY.encode(), msg.encode(), hashlib.sha256).hexdigest()[:n]


def invite_code(role: str) -> str:
    return f"{role}-{_sig('invite:' + role, 12)}"


def parse_invite(code: str) -> str | None:
    for role in ("friend", "buddy"):
        if hmac.compare_digest(code.strip(), invite_code(role)):
            return role
    return None


def invite_link(role: str) -> str:
    username = telegram.bot_username() or "your_bot"
    return f"https://t.me/{username}?start={invite_code(role)}"


def person_token(chat_id: int) -> str:
    return f"{chat_id}.{_sig(f'person:{chat_id}')}"


def verify_person(token: str) -> dict | None:
    chat_id, _, sig = token.partition(".")
    try:
        cid = int(chat_id)
    except ValueError:
        return None
    if not hmac.compare_digest(sig, _sig(f"person:{cid}")):
        return None
    return db.person_by_chat(cid)


def base_url() -> str:
    # The cron job has no RENDER_EXTERNAL_URL of its own, so the web service records it in settings.
    return (db.get_settings().get("public_url") or config.PUBLIC_URL).rstrip("/")


def dashboard_url(person: dict) -> str:
    page = "me" if person["role"] == "friend" else "d"
    return f"{base_url()}/{page}/{person_token(person['chat_id'])}"


def webhook_secret() -> str:
    return _sig("webhook", 32)
