# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for confidence calibration (Brier + overconfidence from fork decisions).

Reads the confidence a student attaches to each fork pick vs. whether it was
right. Training/diagnostic signal only; never feeds the scores.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.confidence_calibration import (  # noqa: E402
    calibration_summary,
    confidence_calibration,
    render_confidence_calibration_html,
)
from speedrun.fork_trainer import record_fork_result  # noqa: E402
from speedrun.session_logger import SessionLogger  # noqa: E402


def _log_forks(log, n, *, confidence, correct_count, item_id="lr-0001"):
    logger = SessionLogger(log_path=log)
    for i in range(n):
        record_fork_result(logger, {
            "item_id": item_id, "picked": "A", "fork_correct": i < correct_count,
            "trap_pick": "trap.too_weak", "actual_trap": "trap.too_weak", "trap_correct": True,
            "confidence": confidence,
            "latency_ms": 30000, "budget_ms": 84000, "over_budget": False,
        })


def test_gives_up_below_minimum(tmp_path):
    log = tmp_path / "s.jsonl"
    _log_forks(log, 5, confidence=0.95, correct_count=3)
    r = confidence_calibration(log_path=log)
    assert r.gave_up is True
    assert r.brier is None
    assert "Not enough" in r.reason


def test_brier_and_overconfidence_math(tmp_path):
    log = tmp_path / "s.jsonl"
    # 10 decisions, all "Certain" (0.95), but only 5 correct -> overconfident.
    _log_forks(log, 10, confidence=0.95, correct_count=5)
    r = confidence_calibration(log_path=log)
    assert r.gave_up is False
    assert r.n == 10
    assert abs(r.mean_confidence - 0.95) < 1e-9
    assert abs(r.accuracy - 0.5) < 1e-9
    assert abs(r.overconfidence - 0.45) < 1e-9
    # Brier = mean((0.95-1)^2 for 5, (0.95-0)^2 for 5) = (0.0025*5 + 0.9025*5)/10
    assert abs(r.brier - 0.4525) < 1e-6


def test_per_schema_and_most_overconfident(tmp_path):
    log = tmp_path / "s.jsonl"
    _log_forks(log, 12, confidence=0.95, correct_count=4)  # 33% right, 95% sure
    r = confidence_calibration(log_path=log)
    assert r.per_schema, "should attribute calibration per schema"
    top = r.most_overconfident
    assert top is not None
    assert top.schema == "flaw.causal.correlation_causation"
    assert top.overconfidence > 0


def test_well_calibrated_has_no_most_overconfident(tmp_path):
    log = tmp_path / "s.jsonl"
    # confidence 0.5, exactly 50% right -> perfectly calibrated, no overconfidence
    _log_forks(log, 10, confidence=0.5, correct_count=5)
    r = confidence_calibration(log_path=log)
    assert abs(r.overconfidence) < 1e-9
    assert r.most_overconfident is None


def test_summary_and_render(tmp_path):
    log = tmp_path / "s.jsonl"
    # give-up render path
    empty = render_confidence_calibration_html(None, log_path=tmp_path / "none.jsonl")
    assert "Not enough" in empty

    _log_forks(log, 12, confidence=0.95, correct_count=5)
    s = calibration_summary(log_path=log)
    assert s["n"] == 12 and s["gave_up"] is False and s["brier"] is not None

    full = render_confidence_calibration_html(None, log_path=log)
    assert full.strip().startswith("<!DOCTYPE html>")
    assert "Confidence calibration" in full and "Brier" in full
    embed = render_confidence_calibration_html(None, embed=True, log_path=log)
    assert "<!DOCTYPE html>" not in embed and 'class="sr-dash"' in embed
