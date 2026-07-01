# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for speedrun config loading and validation."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.config import (  # noqa: E402
    daily_study_goal,
    interleaving_enabled,
    load_config,
    save_config,
    validate_config,
)


def test_load_config_defaults():
    cfg = load_config(Path("/nonexistent/config.json"))
    assert cfg["daily_study_goal_cards"] == 20
    assert interleaving_enabled(config=cfg)


def test_save_and_reload_config():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        save_config({"daily_study_goal_cards": 15, "interleaving_enabled": False}, path)
        cfg = load_config(path)
        assert daily_study_goal(config=cfg) == 15
        assert not interleaving_enabled(config=cfg)


def test_validate_config_ok():
    assert validate_config(load_config(REPO_ROOT / "speedrun" / "config.json")) == []


def test_validate_config_catches_bad_section():
    errors = validate_config({"section_filter": "INVALID"})
    assert any("section_filter" in e for e in errors)
