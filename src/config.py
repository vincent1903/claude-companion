"""User-editable config for Claude Companion.

File: $XDG_CONFIG_HOME/claude-companion/config.json
"""
from __future__ import annotations

import json
import os
from pathlib import Path


CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "claude-companion"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULT_SYSTEM_PROMPT = "Sois concis et direct."
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_THEME = "system"  # system | light | dark
DEFAULT_LANGUAGE = "system"  # system | fr | en | de | es | it

# Models offered in the selector. First is the default. Keep id ↔ label in sync.
AVAILABLE_MODELS = [
    ("claude-haiku-4-5-20251001", "Claude Haiku 4.5 (rapide, économique)"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6 (équilibré)"),
    ("claude-opus-4-7", "Claude Opus 4.7 (le plus puissant)"),
]

# Languages offered in the selector. First is the system locale fallback.
AVAILABLE_LANGUAGES = [
    ("system", "Système"),
    ("fr", "Français"),
    ("en", "English"),
    ("de", "Deutsch"),
    ("es", "Español"),
    ("it", "Italiano"),
]

DEFAULTS = {
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    "model": DEFAULT_MODEL,
    "max_tokens": DEFAULT_MAX_TOKENS,
    "theme": DEFAULT_THEME,
    "language": DEFAULT_LANGUAGE,
}


def load() -> dict:
    if not CONFIG_PATH.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in data.items() if k in DEFAULTS})
    return merged


def save(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {k: config.get(k, DEFAULTS[k]) for k in DEFAULTS}
    CONFIG_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
