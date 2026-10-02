"""Environment-driven configuration. Everything has a sensible local default."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _db_url() -> str:
    url = os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'stillhere.db'}")
    # Render hands out postgres:// or postgresql:// URLs; SQLAlchemy wants the psycopg3 driver named.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL = _db_url()

GEMMA_API_KEY = os.getenv("GEMMA_API_KEY", "")
GEMMA_MODEL = os.getenv("GEMMA_MODEL", "gemma-4-26b-a4b-it")
GEMMA_FALLBACK_MODEL = os.getenv("GEMMA_FALLBACK_MODEL", "gemma-4-31b-it")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Signs dashboard links and the Telegram webhook path. Render generates one in render.yaml.
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-not-secret")
# Unlocks /setup, where invite links live before anyone has joined.
ADMIN_KEY = os.getenv("ADMIN_KEY", "dev-admin")

# Render sets RENDER_EXTERNAL_URL on web services automatically.
PUBLIC_URL = (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "http://localhost:8000").rstrip("/")

# Defaults for the friend; all of these are editable later from the dashboard.
FRIEND_NAME = os.getenv("FRIEND_NAME", "Ben")
DEFAULT_TIMEZONE = os.getenv("FRIEND_TIMEZONE", "Asia/Kolkata")
HELPLINE_TEXT = os.getenv(
    "HELPLINE_TEXT",
    "If you're in danger right now, please call your local emergency number. "
    "You can find a free, confidential helpline near you at https://findahelpline.com",
)

# Where the source lives; powers the "Deploy to Render" button on the landing page.
REPO_URL = os.getenv("REPO_URL", "https://github.com/Eternity0207/StillHere")
