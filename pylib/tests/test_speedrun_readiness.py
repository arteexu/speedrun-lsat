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
    MIN_ATTEMPTS,
    MIN_COVERAGE,
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


def test_readiness_gives_up_below_attempts_floor():
    """Give-up rule, ATTEMPTS gate: even with the coverage requirement satisfied,
    fewer than MIN_ATTEMPTS graded attempts must abstain (no honest number yet).

    We cap the number of graded answers well under the 200-attempt floor (but far
    above the 10-attempt performance floor), and disable the coverage requirement
    (min_coverage=0.0) so the ONLY thing that can trigger give-up is the attempts
    floor. A produced expected_fraction proves data exists; give-up is the rule
    firing, not missing data.
    """
    col = getEmptyCol()
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    # Cap answers below the readiness attempts floor. Each answered card writes one
    # revlog row (== one graded attempt), so this keeps n_attempts under MIN_ATTEMPTS.
    cap = MIN_ATTEMPTS // 2
    answered = 0
    while answered < cap:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)
        answered += 1
    scores = readiness_score(col, min_coverage=0.0)
    # Enough for performance overall (>= 10), but below the readiness floor (< 200).
    assert 10 <= scores.n_attempts < MIN_ATTEMPTS
    assert scores.expected_fraction is not None  # data exists; the gate, not lack of data, abstains
    assert scores.gave_up is True
    assert scores.point is None
    assert "graded attempts" in scores.reason
    col.close()


def test_readiness_gives_up_below_coverage_floor():
    """Give-up rule, COVERAGE gate: even with the attempts requirement satisfied,
    too little exam-weight/pattern coverage must abstain.

    We answer the whole deck (comfortably past the 200-attempt floor) but require
    full coverage (min_coverage=1.0), which the partial deck cannot reach, so the
    ONLY thing that can trigger give-up is the coverage floor.
    """
    col = getEmptyCol()
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    while True:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)
    scores = readiness_score(col, min_coverage=1.0)
    # Attempts requirement is met; only coverage is short.
    assert scores.n_attempts >= MIN_ATTEMPTS
    assert scores.coverage < 1.0
    assert scores.gave_up is True
    assert scores.point is None
    assert "coverage" in scores.reason
    col.close()


def test_readiness_scores_only_when_both_thresholds_met():
    """The give-up rule scores ONLY when BOTH gates pass. Answer the whole deck
    (attempts satisfied) and lower the coverage requirement to what the deck
    supplies; now a number is produced."""
    col = getEmptyCol()
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    while True:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)
    scores = readiness_score(col, min_coverage=MIN_COVERAGE)
    assert scores.n_attempts >= MIN_ATTEMPTS
    assert scores.coverage >= MIN_COVERAGE
    assert scores.gave_up is False, scores.reason
    assert scores.point is not None
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
