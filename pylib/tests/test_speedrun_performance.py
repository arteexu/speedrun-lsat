# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the performance model (transfer bridge, latency-aware)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.scoring.performance import (  # noqa: E402
    Attempt,
    performance_score,
    score_from_attempts,
    weakness_map,
    wilson_interval,
)
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def test_wilson_shrinks_small_samples():
    # 1/1 should not read as 100%
    center, low, high = wilson_interval(1, 1)
    assert center < 1.0
    assert 0.0 <= low <= center <= high <= 1.0


def test_gives_up_below_threshold():
    s = score_from_attempts([Attempt("x", True, 1000)], label="x", min_attempts=3)
    assert s.gave_up
    assert s.point is None


def test_latency_penalizes_accurate_but_slow():
    # all correct, but all far over a 5s budget
    attempts = [Attempt("x", True, 60_000) for _ in range(10)]
    s = score_from_attempts(attempts, label="x", budget_ms=5_000, min_attempts=3)
    assert s.raw_accuracy == 1.0
    assert s.on_budget_rate == 0.0
    assert s.point < 0.5  # transfer estimate discounted for being slow
    assert s.speed_flag is True


def test_on_budget_hits_score_high():
    attempts = [Attempt("x", True, 1_000) for _ in range(10)]
    s = score_from_attempts(attempts, label="x", budget_ms=90_000, min_attempts=3)
    assert s.point > 0.7
    assert s.speed_flag is False
    wm = weakness_map({"x": s})
    assert abs(wm["x"] - (1 - s.point)) < 1e-9


def test_performance_from_revlog():
    col = getEmptyCol()
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    answered = 0
    while True:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)  # Good == hit
        answered += 1
    assert answered >= 10

    scores = performance_score(col)
    overall = scores["overall"]
    assert overall.gave_up is False, overall.reason
    assert overall.n_attempts >= 10
    assert overall.raw_accuracy == 1.0  # all answered Good
    assert 0.0 <= overall.low <= overall.point <= overall.high <= 1.0
    col.close()
