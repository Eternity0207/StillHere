from fastapi.testclient import TestClient

from stillhere import bot, db, heartbeat, links

BEN, SAM = 111, 222


def msg(chat_id, text, name="Ben"):
    return {"update_id": 1, "message": {"chat": {"id": chat_id, "type": "private"}, "from": {"first_name": name}, "text": text}}


def join(sent, clock):
    """Everyone joins the afternoon before the test day, and Ben answers the welcome."""
    clock.set_local(15, 0, day=4)
    bot.handle_update(msg(BEN, f"/start {links.invite_code('friend')}"))
    bot.handle_update(msg(SAM, f"/start {links.invite_code('buddy')}", name="Sam"))
    bot.handle_update(msg(BEN, "hi! nervous about this"))
    clock.set_local(0, 30)
    sent.clear()


def test_welcome_counts_as_todays_checkin(clock, sent):
    clock.set_local(15, 0)
    bot.handle_update(msg(BEN, f"/start {links.invite_code('friend')}"))
    sent.clear()
    clock.set_local(15, 5)
    heartbeat.tick()
    assert to(sent, BEN) == []


def to(sent, chat_id):
    return [t for c, t in sent if c == chat_id]


def test_invites_are_checked(clock, sent):
    bot.handle_update(msg(BEN, "/start friend-wrongcode"))
    assert db.friend() is None
    bot.handle_update(msg(BEN, f"/start {links.invite_code('friend')}"))
    assert db.friend()["chat_id"] == BEN
    # A second person can't take over as the friend.
    bot.handle_update(msg(999, f"/start {links.invite_code('friend')}", name="Eve"))
    assert db.friend()["chat_id"] == BEN
    # Ben is told when a buddy joins.
    bot.handle_update(msg(SAM, f"/start {links.invite_code('buddy')}", name="Sam"))
    assert any("Sam is now one of your buddies" in t for t in to(sent, BEN))


def test_a_quiet_day_escalates_then_resolves(clock, sent):
    join(sent, clock)
    clock.set_local(8, 0)
    assert heartbeat.tick() == ["all quiet"]

    clock.set_local(9, 30)
    heartbeat.tick()
    assert len(to(sent, BEN)) == 1 and db.open_checkin()["status"] == "waiting"
    heartbeat.tick()  # idempotent: no second check-in
    assert len(to(sent, BEN)) == 1

    clock.set_local(13, 45)
    heartbeat.tick()
    assert db.open_checkin()["status"] == "nudged" and len(to(sent, BEN)) == 2
    assert to(sent, SAM) == []

    clock.set_local(19, 45)
    heartbeat.tick()
    assert db.open_checkin()["status"] == "escalated"
    assert "hasn't answered today's check-in" in to(sent, SAM)[0]
    heartbeat.tick()
    assert len(to(sent, SAM)) == 1  # told once, not every 15 minutes

    clock.set_local(20, 10)
    bot.handle_update(msg(BEN, "sorry phone died, all good"))
    assert db.open_checkin() is None
    assert "just checked in" in to(sent, SAM)[-1]
    assert db.moods_since(db.window(1))


def test_reply_closes_checkin_without_alerts(clock, sent):
    join(sent, clock)
    clock.set_local(9, 30)
    heartbeat.tick()
    clock.set_local(10, 0)
    bot.handle_update(msg(BEN, "tired but fine"))
    clock.set_local(23, 0)
    heartbeat.tick()
    assert to(sent, SAM) == []
    assert db.checkin_for_day(clock.now.date())["status"] == "answered"


def test_no_checkin_when_already_chatting(clock, sent):
    join(sent, clock)
    clock.set_local(8, 0)
    bot.handle_update(msg(BEN, "up early today"))
    sent.clear()
    clock.set_local(9, 30)
    heartbeat.tick()
    assert to(sent, BEN) == []


def test_pause_means_no_checkins_and_no_alerts(clock, sent):
    join(sent, clock)
    clock.set_local(8, 0)
    bot.handle_update(msg(BEN, "/pause 2"))
    assert any("paused" in t for t in to(sent, SAM))
    sent.clear()
    for hh in (9, 12, 15, 20):
        clock.set_local(hh, 45)
        heartbeat.tick()
    assert sent == []


def test_crisis_alerts_buddies_immediately(clock, sent):
    join(sent, clock)
    clock.set_local(11, 0)
    bot.handle_update(msg(BEN, "honestly i want to die"))
    assert "findahelpline.com" in to(sent, BEN)[-1]
    assert "really hard time" in to(sent, SAM)[-1]
    assert db.moods_since(db.window(1))[-1]["score"] == 1


def test_buddies_never_see_raw_messages(clock, sent):
    join(sent, clock)
    clock.set_local(10, 0)
    bot.handle_update(msg(BEN, "my secret password is hunter2"))
    bot.handle_update(msg(SAM, "/status", name="Sam"))
    assert all("hunter2" not in t for t in to(sent, SAM))
    assert all("hunter2" not in m["share_line"] for m in db.moods_since(db.window(1)))


def test_sunday_digest_once(clock, sent):
    join(sent, clock)
    clock.set_local(19, 15, day=11)  # Sunday 11 Oct
    heartbeat.tick()
    heartbeat.tick()
    digests = [t for t in to(sent, SAM) if "week" in t]
    assert len(digests) == 1


def test_web_guards(clock, sent):
    join(sent, clock)
    from stillhere.web import app
    with TestClient(app) as c:
        assert c.post("/telegram/nope", json={}).status_code == 403
        ok = links.webhook_secret()
        assert c.post(f"/telegram/{ok}", json={}, headers={"x-telegram-bot-api-secret-token": "bad"}).status_code == 403
        assert c.post(f"/telegram/{ok}", json={}, headers={"x-telegram-bot-api-secret-token": ok}).status_code == 200

        sam = links.person_token(SAM)
        assert c.get(f"/d/{sam}").status_code == 200
        assert c.get(f"/d/{sam[:-1]}x").status_code == 404
        assert c.get(f"/me/{sam}").status_code == 404  # a buddy can't open Ben's private page
        assert c.get(f"/me/{links.person_token(BEN)}").status_code == 200
        assert c.post("/heartbeat").status_code == 403
        assert c.post("/heartbeat", headers={"authorization": "Bearer nope"}).status_code == 403
        assert c.post("/heartbeat", headers={"authorization": "Bearer test-admin"}).status_code == 202
        assert db.get_settings()["last_heartbeat"]  # the queued tick ran
        assert c.get("/setup").status_code == 404
        assert c.get("/setup?key=wrong").status_code == 404
        for page in ("/", "/demo", "/demo/me", "/healthz"):
            assert c.get(page).status_code == 200
