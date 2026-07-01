# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Load and save Speedrun configuration (latency budgets, study goals, toggles)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = REPO_ROOT / "config.json"

DEFAULT_BUDGET_MS = 90_000

DEFAULTS: dict[str, Any] = {
    "version": "0.3.0",
    "latency_budget_ms": {"default": DEFAULT_BUDGET_MS, "LR": 84_000, "RC": 96_000, "LG": 84_000},
    "daily_study_goal_cards": 20,
    "daily_study_goal_minutes": None,
    "interleaving_enabled": True,
    "ai_enabled": False,
    "section_filter": None,
    "schema_drill_count": 3,
    "show_schema_ids": False,
}


def _merge_defaults(raw: dict[str, Any]) -> dict[str, Any]:
    out = dict(DEFAULTS)
    out.update(raw)
    if "latency_budget_ms" in raw:
        budgets = dict(DEFAULTS["latency_budget_ms"])
        budgets.update(raw["latency_budget_ms"])
        out["latency_budget_ms"] = budgets
    return out


@lru_cache(maxsize=1)
def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    if not path.is_file():
        return dict(DEFAULTS)
    return _merge_defaults(json.loads(path.read_text(encoding="utf-8")))


def save_config(cfg: dict[str, Any], path: Path = DEFAULT_CONFIG) -> None:
    merged = _merge_defaults(cfg)
    path.write_text(json.dumps(merged, indent=4) + "\n", encoding="utf-8")
    load_config.cache_clear()


def validate_config(cfg: dict[str, Any] | None = None) -> list[str]:
    """Return a list of validation errors (empty if ok)."""
    cfg = _merge_defaults(cfg or load_config())
    errors: list[str] = []
    budgets = cfg.get("latency_budget_ms", {})
    if not isinstance(budgets, dict):
        errors.append("latency_budget_ms must be an object")
    else:
        for key, val in budgets.items():
            if not isinstance(val, (int, float)) or val <= 0:
                errors.append(f"latency_budget_ms.{key} must be a positive number")
    goal = cfg.get("daily_study_goal_cards")
    if not isinstance(goal, int) or goal < 1:
        errors.append("daily_study_goal_cards must be a positive integer")
    mins = cfg.get("daily_study_goal_minutes")
    if mins is not None and (not isinstance(mins, int) or mins < 1):
        errors.append("daily_study_goal_minutes must be null or a positive integer")
    section = cfg.get("section_filter")
    if section is not None and section not in ("LR", "RC", "LG"):
        errors.append("section_filter must be null, LR, RC, or LG")
    drill = cfg.get("schema_drill_count")
    if not isinstance(drill, int) or drill < 1:
        errors.append("schema_drill_count must be a positive integer")
    return errors


def latency_budget_ms(section: str | None = None, *, config: dict[str, Any] | None = None) -> int:
    """Return the per-item latency budget for a section (LR/RC/LG) or the default."""
    cfg = config or load_config()
    budgets = cfg.get("latency_budget_ms", {})
    if section and section in budgets:
        return int(budgets[section])
    return int(budgets.get("default", DEFAULT_BUDGET_MS))


def daily_study_goal(*, config: dict[str, Any] | None = None) -> int:
    cfg = config or load_config()
    return int(cfg.get("daily_study_goal_cards", 20))


def daily_study_goal_minutes(*, config: dict[str, Any] | None = None) -> int | None:
    cfg = config or load_config()
    val = cfg.get("daily_study_goal_minutes")
    return int(val) if val is not None else None


def interleaving_enabled(*, config: dict[str, Any] | None = None) -> bool:
    cfg = config or load_config()
    return bool(cfg.get("interleaving_enabled", True))


def ai_enabled(*, config: dict[str, Any] | None = None) -> bool:
    cfg = config or load_config()
    return bool(cfg.get("ai_enabled", False))


def section_filter(*, config: dict[str, Any] | None = None) -> str | None:
    cfg = config or load_config()
    val = cfg.get("section_filter")
    return str(val) if val else None


def schema_drill_count(*, config: dict[str, Any] | None = None) -> int:
    cfg = config or load_config()
    return int(cfg.get("schema_drill_count", 3))


def show_schema_ids(*, config: dict[str, Any] | None = None) -> bool:
    cfg = config or load_config()
    return bool(cfg.get("show_schema_ids", False))
