# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Device-local AI settings store — pure Python, Qt-free, never synced.

The AI Tutor can be enabled and configured from the in-app "AI Settings…" dialog
instead of exporting env vars before each launch. Those settings (including the
OpenAI API key) live in a small JSON file *on this device only*:

* It is never written into the Anki collection (``col.set_config``), so the key
  is never uploaded to AnkiWeb / synced to other devices.
* It is not part of the git repo (``speedrun/config.json`` *is* tracked, so the
  secret deliberately does NOT go there).
* The key is never logged.

Resolution order for the file path (first match wins):

1. ``SPEEDRUN_AI_SETTINGS_PATH`` env var (tests set this to a temp file; the aqt
   layer points it at the active profile's base dir so the app and any headless
   code in the same process agree).
2. ``ANKI_BASE`` env var -> ``$ANKI_BASE/speedrun_ai_settings.json`` (the dev
   ``./run`` layout; that folder is git-ignored).
3. ``~/.speedrun-lsat/ai_settings.json`` fallback.

Reads never raise: a missing/unreadable/malformed file yields defaults, so
headless callers (config.py, client.py, CI) transparently fall back to env-only
behavior and existing tests keep passing.
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"

PATH_ENV = "SPEEDRUN_AI_SETTINGS_PATH"

# Keys stored on disk (order = UI order). Values here are the fallback defaults
# used when the file is missing a key or cannot be read at all.
DEFAULTS: dict[str, Any] = {
    "ai_enabled": False,
    "openai_api_key": "",
    "openai_model": DEFAULT_MODEL,
    "openai_base_url": DEFAULT_BASE_URL,
}

_SECRET_KEYS = frozenset({"openai_api_key"})


def settings_path() -> Path:
    """Device-local path to the AI settings file (see module docstring)."""
    override = os.environ.get(PATH_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    base = os.environ.get("ANKI_BASE", "").strip()
    if base:
        return Path(base).expanduser() / "speedrun_ai_settings.json"
    return Path.home() / ".speedrun-lsat" / "ai_settings.json"


def _read_raw() -> dict[str, Any]:
    """The dict actually present on disk (no defaults). ``{}`` if unreadable."""
    path = settings_path()
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        # Malformed / permission error / headless -> behave as if absent.
        pass
    return {}


def load_settings() -> dict[str, Any]:
    """Stored settings merged over :data:`DEFAULTS` (for the UI + enabled check)."""
    out = dict(DEFAULTS)
    for key, val in _read_raw().items():
        if key in DEFAULTS and val is not None:
            out[key] = val
    return out


def stored_overrides() -> dict[str, Any]:
    """Only the values a user has actually set (non-empty) on this device.

    Used by the client so that an *unset* field cleanly falls back to the env
    var rather than being shadowed by a baked-in default. ``ai_enabled`` is kept
    even when ``False`` because that is a meaningful stored choice.
    """
    out: dict[str, Any] = {}
    for key, val in _read_raw().items():
        if key not in DEFAULTS or val is None:
            continue
        if key == "ai_enabled":
            out[key] = bool(val)
        elif isinstance(val, str) and val.strip():
            out[key] = val.strip()
    return out


def settings_ai_enabled() -> bool:
    """Stored on/off choice (default ``False``). Env override is handled upstream
    in :func:`speedrun.ai.config.ai_enabled`, not here."""
    return bool(load_settings().get("ai_enabled", False))


def save_settings(values: Mapping[str, Any]) -> Path:
    """Persist the given keys to the device-local file, restrictively permissioned.

    Only recognized keys are written. The parent dir is created as needed. Writes
    are atomic (temp file + replace) so a crash cannot truncate the store.
    Returns the path written. NEVER writes to the Anki collection.
    """
    merged = load_settings()
    for key in DEFAULTS:
        if key in values:
            val = values[key]
            if key == "ai_enabled":
                merged[key] = bool(val)
            else:
                merged[key] = "" if val is None else str(val)

    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    # Best-effort: keep the secret readable only by the owner.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def masked_key_hint(key: str | None = None) -> str:
    """A safe, log-free hint for a stored key: ``••••1234`` (never the full key).

    Pass ``key`` to hint an arbitrary value; otherwise the stored key is used.
    Returns ``""`` when no key is set.
    """
    if key is None:
        key = str(load_settings().get("openai_api_key", ""))
    key = key.strip()
    if not key:
        return ""
    tail = key[-4:] if len(key) >= 4 else key
    return "\u2022" * 4 + tail
