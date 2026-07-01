# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the readiness model (120-180 projection with give-up rule)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.scoring.readiness import (  # noqa: E402
    readiness_score,
    scaled_from_fraction,
)
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def test_scaled_from_fraction_bounds():
    assert scaled_from_fraction(0.0) == 120.0
    assert scaled_from_fraction(1.0) == 180.0
    assert scaled_from_fraction(0.5) == 150.0
    # clamps out-of-range inputs
    assert scaled_from_fraction(-0.1) == 120.0
    assert scaled_from_fraction(1.5) == 180.0


def test_readiness_gives_up_without_enough_data():
    col = getEmptyCol()
    import_seed_deck(col)
    result = readiness_score(col)
    assert result.gave_up is True
    assert result.point is None
    assert result.n_attempts == 0
    assert "No score yet" in result.reason
    col.close()


def test_readiness_gives_up_after_reviews_but_below_threshold():
    col = getEmptyCol()
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    while True:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)
    # enough for performance overall, but not readiness (200 attempts / 50% coverage)
    scores = readiness_score(col)
    assert scores.gave_up is True
    assert scores.n_attempts >= 10
    col.close()


def test_readiness_computes_with_lowered_thresholds():
    col = getEmptyCol()
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    while True:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)
    scores = readiness_score(
        col,
        min_attempts=10,
        min_coverage=0.01,
        min_attempts_per_schema=1,
        min_attempts_overall=10,
    )
    assert scores.gave_up is False, scores.reason
    assert scores.point is not None
    assert 120.0 <= scores.low <= scores.point <= scores.high <= 180.0
    assert scores.expected_fraction is not None
    assert scores.best_next_step is not None
    col.close()
