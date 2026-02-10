"""Configuration module for Notion RAG service.

Load environment variables and define model settings, pricing, and cost calculation.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# ── Settings Loader ──
_SETTINGS_FILE = Path(__file__).resolve().parent.parent / "settings.json"

def _load_settings() -> dict:
    """Load settings from settings.json if it exists.

    Returns: dict of settings, or empty dict if file doesn't exist.
    """
    if _SETTINGS_FILE.exists():
        return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    return {}

_settings = _load_settings()

# ── Database Registry ──
DATABASES: dict[str, str] = _settings.get("databases", {})

# ── Model Settings ──
_models = _settings.get("models", {})
DEFAULT_QUERY_MODEL = _models.get("query", _settings.get("default_query_model", "gemini-2.5-flash-lite"))
EMBEDDING_MODEL = _models.get("embedding", _settings.get("embedding_model", "gemini-embedding-001"))
IMAGE_VISION_MODEL = _models.get("image_vision", _settings.get("image_vision_model", "gemini-3-flash-preview"))

# ── Sync Settings ──
SYNC_DAYS = _settings.get("sync_days", 2)
INDEX_WAIT_SEC = _settings.get("index_wait_sec", 5)

# ── Server Settings ──
SERVER_HOST = _settings.get("server_host", "127.0.0.1")
SERVER_PORT = _settings.get("server_port", 8000)

# ── Pricing per 1M tokens (USD) ──
# https://ai.google.dev/gemini-api/docs/pricing
PRICING = {
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-3-flash-preview": (0.15, 0.60),
    "gemini-3-pro-preview": (2.00, 12.00),
    "gemini-embedding-001": (0.15, 0.00),
}


def resolve_db(name: str | None = None) -> tuple[str, str]:
    """Resolve a database label to its label and URL.

    Arguments:
    name -- The database label registered in settings.json (optional).
            If None, auto-selects when exactly one database is registered. String or None.

    Returns: tuple of (label, database URL).

    Raises:
    ValueError -- If the label is not found, or auto-select fails.
    """
    if name is not None:
        if name in DATABASES:
            return name, DATABASES[name]
        available = ", ".join(sorted(DATABASES.keys())) if DATABASES else "(none)"
        raise ValueError(
            f"Unknown database label '{name}'. Available labels: {available}"
        )

    # Auto-select when name is omitted
    if len(DATABASES) == 1:
        label = next(iter(DATABASES))
        return label, DATABASES[label]
    if not DATABASES:
        raise ValueError("No databases registered. Run 'init <name> <url>' first.")
    available = ", ".join(sorted(DATABASES.keys()))
    raise ValueError(
        f"Multiple databases registered. Specify one: {available}"
    )


def save_database(label: str, db_url: str) -> None:
    """Save a database label-URL mapping to settings.json and update in-memory registry.

    Arguments:
    label -- The label to register for this database. String.
    db_url -- The Notion database URL. String.

    Returns: None.
    """
    settings = _load_settings()
    if "databases" not in settings:
        settings["databases"] = {}
    settings["databases"][label] = db_url
    _SETTINGS_FILE.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    DATABASES[label] = db_url


def calc_cost(model: str, input_tokens: int, output_tokens: int = 0) -> float:
    """Calculate USD cost for a Gemini API call.

    Arguments:
    model -- The Gemini model name (e.g., "gemini-2.5-flash-lite"). String.
    input_tokens -- Number of input tokens consumed. Integer.
    output_tokens -- Number of output tokens generated (default: 0). Integer.

    Returns: cost in USD as a float.
    """
    rate = PRICING.get(model, (0.0, 0.0))
    return (input_tokens / 1_000_000 * rate[0]) + (output_tokens / 1_000_000 * rate[1])
