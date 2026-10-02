"""Minimal Telegram Bot API client over httpx: only the calls this app needs."""
from __future__ import annotations

import base64
import logging
from functools import lru_cache

import httpx

from . import config

log = logging.getLogger(__name__)


def _url(method: str) -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"


def call(method: str, **params) -> dict:
    if not config.TELEGRAM_BOT_TOKEN:
        log.info("[telegram disabled] %s %s", method, params)
        return {}
    r = httpx.post(_url(method), json=params, timeout=30)
    data = r.json()
    if not data.get("ok"):
        log.warning("telegram %s failed: %s", method, data)
    return data.get("result") or {}


def send(chat_id: int, text: str, **extra) -> dict:
    return call("sendMessage", chat_id=chat_id, text=text, disable_web_page_preview=True, **extra)


def typing(chat_id: int) -> None:
    call("sendChatAction", chat_id=chat_id, action="typing")


@lru_cache(maxsize=1)
def bot_username() -> str:
    return (call("getMe") or {}).get("username", "")


def download_photo(file_id: str) -> tuple[str, str] | None:
    """Return (mime, base64) for a Telegram photo so Gemma can look at it."""
    info = call("getFile", file_id=file_id)
    path = info.get("file_path")
    if not path:
        return None
    r = httpx.get(f"https://api.telegram.org/file/bot{config.TELEGRAM_BOT_TOKEN}/{path}", timeout=30)
    if r.status_code != 200:
        return None
    mime = "image/png" if path.endswith(".png") else "image/jpeg"
    return mime, base64.b64encode(r.content).decode()


def set_webhook(url: str, secret: str) -> dict:
    return call("setWebhook", url=url, secret_token=secret, allowed_updates=["message"], drop_pending_updates=False)


def webhook_info() -> dict:
    return call("getWebhookInfo")


def set_commands() -> None:
    call("setMyCommands", commands=[
        {"command": "pause", "description": "Pause check-ins (e.g. /pause 3 for three days)"},
        {"command": "resume", "description": "Resume check-ins"},
        {"command": "time", "description": "Change check-in time, e.g. /time 08:45"},
        {"command": "privacy", "description": "See exactly what your buddies can see"},
        {"command": "forget", "description": "Wipe everything I remember about you"},
        {"command": "status", "description": "Buddies: how is your friend doing?"},
        {"command": "note", "description": "Buddies: send a little note, e.g. /note proud of you"},
        {"command": "help", "description": "How this works"},
    ])
