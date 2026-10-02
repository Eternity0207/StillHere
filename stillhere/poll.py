"""Local development without a public URL: long-poll Telegram and run a heartbeat every minute.

    python -m stillhere.poll

On Render this file is unused; the webhook and the cron job take over.
"""
from __future__ import annotations

import logging
import time

import httpx

from . import bot, config, db, heartbeat, links, telegram

log = logging.getLogger("stillhere.poll")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env first (get one from @BotFather).")
    db.init()
    telegram.call("deleteWebhook")  # polling and webhooks can't both be active
    telegram.set_commands()
    log.info("Bot: @%s", telegram.bot_username())
    log.info("Friend invite: %s", links.invite_link("friend"))
    log.info("Buddy invite:  %s", links.invite_link("buddy"))

    offset, last_beat = 0, 0.0
    while True:
        if time.time() - last_beat > 60:
            for line in heartbeat.tick():
                log.info("heartbeat: %s", line)
            last_beat = time.time()
        try:
            r = httpx.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates",
                           json={"offset": offset, "timeout": 25, "allowed_updates": ["message"]}, timeout=35)
            updates = r.json().get("result", [])
        except httpx.HTTPError as e:
            log.warning("poll failed: %s", e)
            time.sleep(3)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            try:
                bot.handle_update(u)
            except Exception:
                log.exception("update failed")


if __name__ == "__main__":
    main()
