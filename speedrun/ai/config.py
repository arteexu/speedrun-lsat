# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""AI configuration — single off switch for all model calls.

Kept UI-free / importable headless (no Qt). The on/off decision has a clear
precedence so both automated tests / CI and the in-app "AI Settings…" dialog
work without stepping on each other:

1. If ``SPEEDRUN_AI_OFF`` is *explicitly* set in the environment, it wins
   (preserves the existing test + power-user + CI override).
2. Otherwise the device-local stored setting (``ai_enabled``) decides.
3. Default: OFF (safety).

The store is read via :mod:`speedrun.ai.settings`, a pure-Python helper that
never raises; if it can't be read (headless/tests) we fall back to env-only.
"""
from __future__ import annotations

import os

_OFF_VALUES = ("1", "true", "yes", "on")


def _env_off_explicit() -> bool | None:
    """Return the env decision (True=enabled, False=disabled) or None if unset."""
    raw = os.environ.get("SPEEDRUN_AI_OFF")
    if raw is None:
        return None
    return raw.strip().lower() not in _OFF_VALUES


def ai_enabled() -> bool:
    """True when AI model calls are allowed. See module docstring for precedence."""
    # 1. Explicit env var wins (tests / CI / power users).
    env = _env_off_explicit()
    if env is not None:
        return env
    # 2. Device-local stored setting (in-app AI Settings dialog).
    try:
        from speedrun.ai.settings import settings_ai_enabled

        return settings_ai_enabled()
    except Exception:
        # 3. Store unreadable (headless/tests) -> default OFF.
        return False


def require_ai() -> None:
    if not ai_enabled():
        raise RuntimeError(
            "AI is disabled. Enable it in LSAT Speedrun → AI Settings…, or set "
            "SPEEDRUN_AI_OFF=0 in the environment."
        )
