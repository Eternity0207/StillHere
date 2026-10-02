import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Isolated DB, no network: an empty Gemma key forces the hand-written fallbacks, an empty bot token disables Telegram.
_tmp = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"
os.environ["GEMMA_API_KEY"] = ""
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ADMIN_KEY"] = "test-admin"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from stillhere import db, telegram  # noqa: E402


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 5, 0, 0)  # a Monday, 00:00 UTC = 05:30 in Asia/Kolkata

    def __call__(self):
        return self.now

    def set_local(self, hh: int, mm: int = 0, day: int = 5):
        """Set the clock using Ben's local time (Asia/Kolkata is UTC+5:30)."""
        total = hh * 60 + mm - 330
        d = day + total // (24 * 60)
        total %= 24 * 60
        self.now = datetime(2026, 10, d, total // 60, total % 60)


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(db, "utcnow", c)
    return c


@pytest.fixture
def sent(monkeypatch):
    """Every Telegram message the app tries to send, as (chat_id, text)."""
    out: list[tuple[int, str]] = []
    monkeypatch.setattr(telegram, "send", lambda chat_id, text, **kw: out.append((chat_id, text)) or {})
    monkeypatch.setattr(telegram, "typing", lambda chat_id: None)
    return out


@pytest.fixture(autouse=True)
def fresh_db():
    db.md.drop_all(db.engine)
    db.init()
    yield
