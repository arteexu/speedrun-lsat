# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""AI configuration — single off switch for all model calls."""
from __future__ import annotations

import os


def ai_enabled() -> bool:
    """Return False when SPEEDRUN_AI_OFF=1/true/yes (default: AI off for safety)."""
    val = os.environ.get("SPEEDRUN_AI_OFF", "1").strip().lower()
    return val not in ("1", "true", "yes", "on")


def require_ai() -> None:
    if not ai_enabled():
        raise RuntimeError(
            "AI is disabled (SPEEDRUN_AI_OFF=1). Set SPEEDRUN_AI_OFF=0 to enable."
        )
