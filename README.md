# Still Here

**A daily check-in for the friend who lives far away.**

Still Here sends one person (Ben) one small message every morning on Telegram. Ben replies with anything (a word, an emoji, a photo) and gets on with the day. If Ben goes quiet for too long, it quietly asks Ben's buddies to call.

- **Gemma 4** (open weights) writes the check-ins, replies like a friend, and turns each reply into a mood score plus one *shareable* line. Buddies never see Ben's actual messages.
- **Render** is the heartbeat: a web service for the Telegram webhook and dashboards, a **cron job** that wakes every 15 minutes to decide who needs a message, and **Postgres** for memory.
- **Telegram** is the whole interface. Ben installs nothing.

```
            ┌───────────── Render ───────────────────────────────┐
 Ben ⇄ Telegram ⇄ web service (FastAPI)  ── dashboards for buddies & Ben
            │        │                                            │
            │     Postgres  ◀── cron job "heartbeat" (*/15 min)   │
            │        │           check-in → nudge → tell buddies   │
            └────────┼────────────────────────────────────────────┘
                     ▼
              Gemma 4 (open weights, via Google AI Studio)
```

## How a day works

| Ben's local time | What happens |
|---|---|
| 09:30 | Heartbeat sends a check-in Gemma wrote using what it remembers ("how did the interview go?") |
| any reply | Gemma replies, scores mood 1–5, writes a one-line share, maybe saves a memory |
| +4h, no reply | One gentle nudge ("a 👍 is plenty"), never during Ben's night |
| +10h, no reply | Each buddy gets a calm heads-up. When Ben replies, they're told right away |
| Sunday 19:00 | Buddies get a short note about Ben's week |

A deterministic safety net runs alongside the model: if Ben's message contains crisis language, Ben gets helpline info and buddies are alerted at once, whatever the model says.

## Privacy, by design

| Buddies see | Stays with Ben |
|---|---|
| Mood score, one word, one model-written line per day | Every message Ben sends |
| An alert after a long silence | What the bot remembers (Ben can delete any of it) |
| A Sunday digest | `/pause`, `/forget`, and a private page to remove any buddy |

Ben is told every time someone becomes a buddy.

## Deploy on Render (about 5 minutes)

1. Fork this repo.
2. Create a bot: message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
3. Get a free Gemma key: <https://aistudio.google.com/apikey>.
4. Click **New → Blueprint** on Render and pick your fork (or open `https://render.com/deploy?repo=<your fork>`). Paste the two keys when asked.
5. Open `https://<your-service>.onrender.com/setup?key=<ADMIN_KEY>` (find `ADMIN_KEY` in the service's Environment tab). Send Ben the friend link and yourself the buddy link.

The web service registers its own Telegram webhook on boot using the `RENDER_EXTERNAL_URL` that Render provides.

**Cost:** the web service and database have free plans. The cron job runs about 30 seconds every 15 minutes on the Starter plan, which is pennies a month (Hacktoberfest Render credits cover it). Free Postgres expires after 30 days; switch `plan: free` to `basic-256mb` in `render.yaml` to keep history.

## Run locally

```bash
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                             # add GEMMA_API_KEY and TELEGRAM_BOT_TOKEN
uvicorn stillhere.web:app --reload               # dashboards at http://localhost:8000 (/demo needs no setup)
python -m stillhere.poll                         # bot via long polling + a heartbeat every minute
pytest                                           # simulated days: check-in, nudge, escalation, pause, crisis, digest
```

## Project map

| File | Job |
|---|---|
| `stillhere/heartbeat.py` | The cron job: one idempotent state machine run every 15 min |
| `stillhere/bot.py` | Telegram updates: onboarding, replies, commands, buddy notes |
| `stillhere/brain.py` | Every prompt sent to Gemma, plus fallbacks and the crisis safety net |
| `stillhere/gemma.py` | Small Gemma client. Swap providers here |
| `stillhere/web.py` | Webhook, buddy dashboard, Ben's private page, setup, public demo |
| `stillhere/views.py` | Turns rows into the 30-day "pulse" line |

## Why open

- **Open weights:** Ben's words go to Gemma, not a closed model whose provider can change terms. Today it's served by Google AI Studio; moving it to a GPU box you own (vLLM, Ollama) means editing one file.
- **One instance per friend:** no company holds a database of people's loneliness. Everyone deploys their own copy.
- **Readable rules:** the timings, prompts and safety net are plain Python that Ben's friends can read.

Not an emergency service. If someone is in danger, contact local emergency services.
