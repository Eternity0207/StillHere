---
title: I built my friend a heartbeat on Render
published: false
tags: devchallenge, weekendchallenge, hf26challenge, opensource
---

*This is a submission for the [Hacktoberfest Weekend Challenge: Build for a Friend](https://dev.to/challenges/hacktoberfest-2026-weekend)*

## What I Built

<!-- ✏️ Make this paragraph yours. One or two real details beat any polish. -->
Ben moved to a new city [for a job / for college / fill in] and lives alone now. We text, but texts are uneven: some weeks it's memes every hour, then nothing for four days. Usually nothing means busy. But I never actually *know*, and I don't want to be the friend who sends "you alive??" every morning.

So I built **Still Here**: a tiny check-in companion that lives in Ben's Telegram.

- Every morning it sends Ben **one small message**, written by Gemma, that remembers Ben's life: "how did the interview go?", not "How are you feeling today?"
- Ben replies with **anything**. A word, an emoji, a photo of lunch. That's it. Done for the day.
- If Ben goes quiet, it sends **one gentle nudge** a few hours later ("a 👍 is plenty").
- If the silence lasts about 10 hours, it quietly messages **me** (and anyone else Ben has as a buddy): *"Haven't heard from Ben since yesterday morning. Probably nothing, but a call would be lovely."*
- When Ben replies, I'm told right away, and we both go back to our day.

The part I care about most: **I never see Ben's messages.** Gemma turns each reply into a 1–5 mood score and one shareable line ("Busy week, tired but okay"). That's all buddies get. Ben has a private page showing *exactly* what I see, can `/pause` for a few days without explaining, and can `/forget` everything the bot has remembered.

## Demo

<!-- ✏️ Add your Render URL + a screen recording of the Telegram chat -->
- **Live dashboard (demo data):** `https://<your-app>.onrender.com/demo`
- **Ben's private view (demo data):** `https://<your-app>.onrender.com/demo/me`

The signature visual is the **pulse**: Ben's last 30 days drawn as a heartbeat. Taller beats are brighter days, a flat stretch is a day Ben went quiet, a shaded block is a pause. One glance tells me whether to call tonight.

<!-- screenshots: dashboard, Ben's page, Telegram conversation, a buddy alert -->

## Code

{% embed https://github.com/Eternity0207/StillHere %}

## How I Built It

**The stack:** Python + FastAPI, Telegram Bot API (raw HTTP, no SDK), Gemma 4 via Google AI Studio, Render (free web service + Postgres from one `render.yaml`), and a free GitHub Actions schedule as the heartbeat:

| Render piece | Job |
|---|---|
| **Web service** | Telegram webhook, buddy dashboard, Ben's private page |
| **`POST /heartbeat`** (called every 10 min by GitHub Actions) | The heartbeat: check-in → nudge → tell buddies → Sunday digest |
| **Postgres** | Check-ins, moods, memories |

### A heartbeat for the price of zero

I didn't have a card for a paid cron job, so the heartbeat is a GitHub Actions schedule that calls an authenticated `POST /heartbeat` on Render every 10 minutes. That also wakes the free instance. (The same code runs as a native Render Cron Job if you uncomment one block.) Each beat converts "now" into Ben's local time and runs a small state machine:

```python
if local.time() >= checkin_time and not db.checkin_for_day(today):
    send_checkin()
if ci.status == "waiting" and hours >= nudge_after and 8 <= local.hour < 22:
    nudge()
if ci.status in ("waiting", "nudged") and hours >= escalate_after:
    tell_buddies()
```

Every beat is **idempotent**. If a run is missed or runs twice, nothing breaks: it only ever looks at what's in Postgres and what time it is for Ben. That mattered because the scariest bug possible here is *sending me a "Ben's gone quiet" alert by mistake*. The test suite simulates whole days (a quiet day that escalates and resolves, a pause, a crisis message, Sunday's digest) by freezing the clock and capturing every Telegram message.

The web service also registers its own Telegram webhook on boot using the `RENDER_EXTERNAL_URL` Render injects, so deploying really is: paste two keys, click once.

### Gemma does four jobs

1. **Write the check-in.** It gets a short list of memories ("team offsite this week", "plays weekend football") and the last few mood words, so the message sounds like someone paying attention.
2. **Understand the reply.** A single JSON call returns the reply to Ben, a mood score, a one-word mood, a shareable line, an optional new memory, and a concern level.
3. **Nudge gently** when Ben is quiet.
4. **Write the Sunday note** for buddies from the week's shareable lines.

The shareable line has strict rules: no other people's names, no health or money details, nothing Ben asked to keep private. When I tested it with *"don't tell anyone but i got into a fight with my sister"*, Gemma replied kindly to Ben and wrote *"Ben's having a bit of a rough day"* for me. Exactly right.

### Things that went wrong

- **The hosted free tier flaked hard**: 500s, 503s, an 88-second response. Every call now alternates between `gemma-4-26b-a4b-it` (MoE, fast) and `gemma-4-31b-it` with backoff, and every Gemma job has a hand-written fallback. A model hiccup should never mean Ben gets silence.
- **Gemma 4 returns its reasoning as parts flagged `thought`.** I filter those, and `thinkingLevel: "minimal"` took replies from ~7s to ~1.5s.
- **Safety can't depend on a model's mood.** Alongside Gemma's `concern` field, a plain regex catches crisis language. If it fires, Ben gets helpline info and buddies are alerted immediately, no matter what the model said.
- **The model guessed pronouns** in an early digest. All prompts now use Ben's name or "they".

## Why open innovation matters here

This project is about someone's loneliness, and that changed what I was willing to build on.

- **Open weights mean I'm not locked in.** Ben's words go to Gemma. Today Google AI Studio serves it for free, but `gemma.py` is one small file. If the terms change or I get a GPU box, I move to vLLM or Ollama by changing one URL. With a closed model, the provider decides where this data goes forever.
- **One instance per friend.** There's no Still Here company with a database of people's bad days. Each person deploys their own copy from one `render.yaml`, and the data sits in a Postgres that *they* own.
- **Readable rules.** The exact moment I get an alert about Ben is a number in a file Ben can read. That kind of trust is hard to get from a black-box app.
- **It costs nothing:** a free Render web service and Postgres, a free GitHub Actions heartbeat, and free Gemma inference. No card needed.

## What Ben said

<!-- ✏️ The judges explicitly want this. Hand it over, then write 2–4 honest sentences:
     what Ben's first reply to the bot was, what made them laugh or wince, what they asked you to change. -->
[Ben's reaction goes here.]

## What's next

- Voice notes, transcribed by an open speech model, for days when typing is too much
- Running Gemma on a small GPU instance so nothing leaves our own infrastructure
- A "buddy rota" so alerts go to whoever is awake in their time zone
