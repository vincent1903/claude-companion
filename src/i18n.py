"""Gettext setup for Claude Companion.

Call ``i18n.setup(language)`` once at app startup, then use ``i18n._`` to
translate strings. The language argument may be ``"system"`` (use the env
locale) or a specific code like ``"fr"``, ``"en"``, ``"de"``, ``"es"``, ``"it"``.
"""
from __future__ import annotations

import gettext
import os
from pathlib import Path

DOMAIN = "claude-companion"

_current = gettext.NullTranslations()


def _localedir() -> str | None:
    """Find the directory containing compiled .mo files."""
    env = os.environ.get("CLAUDE_QUICK_LOCALE_DIR")
    candidates = []
    if env:
        candidates.append(env)
    candidates.extend([
        "/app/share/locale",                                 # Flatpak
        str(Path(__file__).resolve().parent.parent / "po" / "build"),  # dev
        "/usr/local/share/locale",
        "/usr/share/locale",
    ])
    for d in candidates:
        if Path(d, "fr", "LC_MESSAGES", f"{DOMAIN}.mo").exists():
            return d
    return None


def setup(language: str = "system") -> None:
    """Configure gettext for the rest of the process."""
    global _current
    localedir = _localedir()
    languages = None if language in (None, "", "system") else [language]
    try:
        _current = gettext.translation(
            DOMAIN, localedir=localedir, languages=languages, fallback=True
        )
    except Exception:
        _current = gettext.NullTranslations()


def _(message: str) -> str:
    return _current.gettext(message)
