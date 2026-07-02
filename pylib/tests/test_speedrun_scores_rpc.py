# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Parity: the Rust ComputeSpeedrunScores RPC matches the Python scoring.

This is the honesty guarantee for sharing one implementation across desktop and
phone: the Rust engine's scores must equal the Python source of truth on the same
collection. Memory and performance are compared numerically; readiness (which
needs 200 attempts) abstains on both on the exam deck.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.scoring.memory import memory_score  # noqa: E402
from speedrun.scoring.performance import performance_score  # noqa: E402
from speedrun.scoring.queue import load_schema_weights  # noqa: E402
from speedrun.scoring.readiness import readiness_score  # noqa: E402
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402

TOL = 1e-3


def _reviewed_col(n: int = 40):
    col = getEmptyCol()
    col.set_config("fsrs", True)
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    answered = 0
    while answered < n:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)
        answered += 1
    return col


def _rpc(col):
    return col._backend.compute_speedrun_scores(
        schema_tag_prefix="sr:schema:",
        schema_weight=load_schema_weights(),
        lr_budget_ms=84000,
        rc_budget_ms=96000,
        min_reviewed_overall=5,
        min_attempts_overall=10,
        readiness_min_attempts=200,
        readiness_min_coverage=0.5,
    )


def test_rust_memory_matches_python():
    col = _reviewed_col()
    py = memory_score(col)["overall"]
    rs = _rpc(col).memory
    assert py.gave_up == rs.gave_up
    if not py.gave_up:
        assert abs(py.point - rs.point) < TOL
        assert abs(py.low - rs.low) < TOL
        assert abs(py.high - rs.high) < TOL
        assert py.n_reviewed == rs.n
    col.close()


def test_rust_performance_matches_python():
    col = _reviewed_col()
    py = performance_score(col)["overall"]
    rs = _rpc(col).performance
    assert py.gave_up == rs.gave_up
    if not py.gave_up:
        assert abs(py.point - rs.point) < TOL
        assert abs(py.low - rs.low) < TOL
        assert abs(py.high - rs.high) < TOL
        assert py.n_attempts == rs.n
    col.close()


def test_rust_readiness_matches_python_giveup():
    col = _reviewed_col()
    py = readiness_score(col)  # needs 200 attempts -> abstains
    rs = _rpc(col).readiness
    assert py.gave_up == rs.gave_up
    col.close()


def test_scores_available_over_ffi_service_13_method_40():
    # Smoke: the RPC returns all three sub-scores.
    col = _reviewed_col()
    resp = _rpc(col)
    assert resp.HasField("memory")
    assert resp.HasField("performance")
    assert resp.HasField("readiness")
    col.close()
