# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for memory calibration (spec 9)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.eval.calibration import calibration_report  # noqa: E402
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
