# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for memory calibration (spec 9)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.eval.calibration import (  # noqa: E402
    _temporal_split,
    calibration_report,
)
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def test_calibration_abstains_without_reviews():
    col = getEmptyCol()
    import_seed_deck(col)
    report = calibration_report(col)
    assert report.gave_up is True
    col.close()


def test_calibration_after_reviews():
    col = getEmptyCol()
    col.set_config("fsrs", True)
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    while True:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)
    report = calibration_report(col, min_held_out=5)
    assert report.gave_up is False, report.reason
    assert report.brier is not None
    assert report.log_loss is not None
    assert 0 <= report.brier <= 1
    col.close()


def test_temporal_split_reserves_training_reviews():
    # A healthy set: the later 30% is held out, the earlier 70% trains.
    pairs = [(0.9, 1)] * 100
    train, held = _temporal_split(pairs, min_held_out=10, holdout_fraction=0.3)
    assert len(held) == 30
    assert len(train) == 70
    # The held-out slice is the LATER portion (order preserved).
    assert held == pairs[70:]
    # Tiny data still keeps at least one training review rather than "all held out".
    train2, held2 = _temporal_split(
        [(0.9, 1), (0.8, 0)], min_held_out=10, holdout_fraction=0.3
    )
    assert len(train2) >= 1
    # A single review cannot be split -> nothing held out.
    train3, held3 = _temporal_split([(0.5, 1)], min_held_out=1, holdout_fraction=0.3)
    assert held3 == []


def test_calibration_is_a_real_holdout_not_all_reviews():
    col = getEmptyCol()
    col.set_config("fsrs", True)
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    while True:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)
    report = calibration_report(col, min_held_out=5)
    assert report.gave_up is False, report.reason
    # Honest held-out: some reviews train, the rest are the held-out slice, and
    # the two partition the full set (not the old "all reviews are held out").
    assert report.n_train > 0
    assert 0 < report.n_held_out < report.n_total
    assert report.n_train + report.n_held_out == report.n_total
    expected_holdout = min(max(round(report.n_total * 0.3), 5), report.n_total - 1)
    assert report.n_held_out == expected_holdout
    col.close()
