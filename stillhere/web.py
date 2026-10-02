"""The Render web service: Telegram webhook, dashboards, landing page and the public demo."""
from __future__ import annotations

import hashlib
import hmac
import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import available_timezones

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import bot, config, db, demo, gemma, heartbeat, links, telegram, timeutil, views

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("stillhere.web")
HERE = Path(__file__).parent
TIMEZONES = sorted(tz for tz in available_timezones() if "/" in tz and not tz.startswith(("Etc/", "SystemV/")))


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    if config.PUBLIC_URL.startswith("https://"):
        db.set_setting("public_url", config.PUBLIC_URL)
        if config.TELEGRAM_BOT_TOKEN:
            telegram.set_webhook(f"{config.PUBLIC_URL}/telegram/{links.webhook_secret()}", links.webhook_secret())
            telegram.set_commands()
            log.info("telegram webhook registered at %s", config.PUBLIC_URL)
    yield


app = FastAPI(title="Still Here", lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.globals["repo_url"] = config.REPO_URL


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, name, ctx)


def back(url: str, flash: str = "") -> RedirectResponse:
    return RedirectResponse(f"{url}?saved={flash}" if flash else url, status_code=303)


# ---------------- public ----------------

@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return render(request, "landing.html", v=views.build(demo.snapshot()))


@app.get("/demo", response_class=HTMLResponse)
def demo_buddy(request: Request):
    return render(request, "dashboard.html", v=views.build(demo.snapshot()), viewer="Sam", demo=True, token="")


@app.get("/demo/me", response_class=HTMLResponse)
def demo_friend(request: Request):
    return render(request, "me.html", v=views.build(demo.snapshot()), demo=True, token="",
                  timezones=TIMEZONES, buddies=[{"name": n, "chat_id": 0} for n in ("Sam", "Maya")])


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ---------------- telegram ----------------

@app.post("/telegram/{secret}")
async def telegram_webhook(secret: str, request: Request, tasks: BackgroundTasks):
    expected = links.webhook_secret()
    header = request.headers.get("x-telegram-bot-api-secret-token", "")
    if not (hmac.compare_digest(secret, expected) and hmac.compare_digest(header, expected)):
        raise HTTPException(403)
    # Answer Telegram immediately; Gemma can take a couple of seconds.
    tasks.add_task(_safe_handle, await request.json())
    return {"ok": True}


# ---------------- heartbeat trigger ----------------
# Same tick the Render Cron Job runs, exposed for a free scheduler (GitHub Actions) to call.
# Each call also wakes the free web service if it has spun down.

_beat_lock = threading.Lock()


@app.post("/heartbeat")
def heartbeat_trigger(request: Request, tasks: BackgroundTasks):
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, config.ADMIN_KEY):
        raise HTTPException(403)
    tasks.add_task(_safe_beat)
    return JSONResponse({"ok": True, "queued": True}, status_code=202)


def _safe_beat() -> None:
    if not _beat_lock.acquire(blocking=False):
        return  # a beat is already running; ticks are idempotent, so skipping is safe
    try:
        for line in heartbeat.tick():
            log.info("heartbeat: %s", line)
    except Exception:
        log.exception("heartbeat failed")
    finally:
        _beat_lock.release()


def _safe_handle(update: dict) -> None:
    try:
        bot.handle_update(update)
    except Exception:  # never let one bad update kill the worker
        log.exception("failed to handle update")


# ---------------- buddy dashboard ----------------

def _person(token: str, role: str) -> dict:
    p = links.verify_person(token)
    if not p or p["role"] != role:
        raise HTTPException(404)
    return p


@app.get("/d/{token}", response_class=HTMLResponse)
def buddy_dashboard(token: str, request: Request):
    p = _person(token, "buddy")
    return render(request, "dashboard.html", v=views.build(views.snapshot_from_db()), viewer=p["name"],
                  demo=False, token=token)


@app.post("/d/{token}/note")
def buddy_note(token: str, note: str = Form(...)):
    p = _person(token, "buddy")
    ok = bot.send_note(p["name"], note.strip()) if note.strip() else False
    return back(f"/d/{token}", "note" if ok else "")


# ---------------- friend's own page ----------------

@app.get("/me/{token}", response_class=HTMLResponse)
def friend_page(token: str, request: Request):
    _person(token, "friend")
    return render(request, "me.html", v=views.build(views.snapshot_from_db()), demo=False, token=token,
                  timezones=TIMEZONES, buddies=db.buddies())


@app.post("/me/{token}/rhythm")
def friend_rhythm(token: str, checkin_time: str = Form(...), timezone: str = Form(...)):
    _person(token, "friend")
    _save_rhythm(checkin_time, timezone)
    return back(f"/me/{token}", "rhythm")


@app.post("/me/{token}/pause")
def friend_pause(token: str, days: int = Form(...)):
    p = _person(token, "friend")
    days = max(0, min(days, 30))
    if days == 0:
        db.set_setting("paused_until", "")
        db.log_event("resumed")
    else:
        db.set_setting("paused_until", (db.utcnow() + timedelta(days=days)).isoformat())
        db.log_event("paused", f"{days} day(s)")
        for b in db.buddies():
            telegram.send(b["chat_id"], f"{p['name']} paused check-ins for {days} day{'s' if days > 1 else ''}.")
    return back(f"/me/{token}", "pause")


@app.post("/me/{token}/forget")
def friend_forget(token: str, memory_id: int | None = Form(None)):
    _person(token, "friend")
    db.forget_memory(memory_id)
    return back(f"/me/{token}", "forget")


@app.post("/me/{token}/remove-buddy")
def friend_remove_buddy(token: str, chat_id: int = Form(...)):
    p = _person(token, "friend")
    b = db.person_by_chat(chat_id)
    if b and b["role"] == "buddy":
        db.remove_person(chat_id)
        telegram.send(chat_id, f"{p['name']} has removed you as a buddy. Thanks for looking out for them 🫶")
    return back(f"/me/{token}", "buddy")


def _save_rhythm(checkin_time: str, tzname: str) -> None:
    t = timeutil.parse_hhmm(checkin_time, default=None)
    if t:
        db.set_setting("checkin_time", f"{t:%H:%M}")
    if tzname in TIMEZONES or tzname == "UTC":
        db.set_setting("timezone", tzname)


# ---------------- setup (for whoever deploys it) ----------------

def _admin_cookie() -> str:
    return hashlib.sha256(f"admin:{config.ADMIN_KEY}:{config.SECRET_KEY}".encode()).hexdigest()


def _require_admin(request: Request) -> None:
    if not hmac.compare_digest(request.cookies.get("sh_admin", ""), _admin_cookie()):
        raise HTTPException(404)


@app.get("/setup", response_class=HTMLResponse)
def setup(request: Request, key: str = ""):
    if key:
        if not hmac.compare_digest(key, config.ADMIN_KEY):
            raise HTTPException(404)
        resp = RedirectResponse("/setup", status_code=303)
        resp.set_cookie("sh_admin", _admin_cookie(), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 90,
                        secure=config.PUBLIC_URL.startswith("https://"))
        return resp
    _require_admin(request)
    s = db.get_settings()
    hook = telegram.webhook_info() if config.TELEGRAM_BOT_TOKEN else {}
    friend = db.friend()
    checks = [
        ("Gemma API key", bool(config.GEMMA_API_KEY), config.GEMMA_MODEL),
        ("Telegram bot token", bool(config.TELEGRAM_BOT_TOKEN),
         f"@{telegram.bot_username()}" if config.TELEGRAM_BOT_TOKEN else "add TELEGRAM_BOT_TOKEN"),
        ("Webhook", bool(hook.get("url")), hook.get("last_error_message") or ("registered" if hook.get("url") else "not set yet")),
        ("Heartbeat", bool(s["last_heartbeat"]),
         f"last beat {timeutil.ago(datetime.fromisoformat(s['last_heartbeat']))}" if s["last_heartbeat"] else "hasn't run yet"),
        ("Database", True, "Postgres" if config.DATABASE_URL.startswith("postgresql") else "SQLite (local)"),
    ]
    return render(request, "setup.html", s=s, checks=checks, friend=friend, buddies=db.buddies(),
                  friend_link=links.invite_link("friend"), buddy_link=links.invite_link("buddy"),
                  friend_page=links.dashboard_url(friend) if friend else None,
                  timezones=TIMEZONES, v=views.build(views.snapshot_from_db()))


@app.post("/setup/settings")
def setup_settings(request: Request, friend_name: str = Form(...), checkin_time: str = Form(...),
                   timezone: str = Form(...), nudge_after_h: float = Form(...), escalate_after_h: float = Form(...)):
    _require_admin(request)
    db.set_setting("friend_name", friend_name.strip()[:40] or "Ben")
    _save_rhythm(checkin_time, timezone)
    nudge = max(1.0, min(nudge_after_h, 12.0))
    db.set_setting("nudge_after_h", f"{nudge:g}")
    db.set_setting("escalate_after_h", f"{max(nudge + 1, min(escalate_after_h, 20.0)):g}")
    if (f := db.friend()) and friend_name.strip():
        with db.engine.begin() as c:
            c.execute(db.people.update().where(db.people.c.id == f["id"]).values(name=friend_name.strip()[:40]))
    return back("/setup", "settings")


@app.post("/setup/beat")
def setup_beat(request: Request):
    _require_admin(request)
    result = heartbeat.tick()
    return back("/setup", "beat:" + " · ".join(result)[:180])


@app.get("/setup/gemma")
def setup_gemma(request: Request):
    _require_admin(request)
    try:
        return JSONResponse({"ok": True, "sample": gemma.generate("Be brief.", "Say hi to Ben in five words.")})
    except gemma.GemmaError as e:
        return JSONResponse({"ok": False, "error": str(e)[:300]})
