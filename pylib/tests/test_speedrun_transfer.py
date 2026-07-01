# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for transfer gap evaluation (spec 7d)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.eval.transfer_gap import (  # noqa: E402
    generate_reworded_variants,
    transfer_gap_report,
)
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def test_generate_reworded_variants():
    variants = generate_reworded_variants()
    assert len(variants) == 11 * 2  # seed deck × 2 variants
    assert (
        variants[0].stimulus != variants[1].stimulus or variants[0].variant_index != 1
    )


def test_transfer_gap_synthetic():
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
    report = transfer_gap_report(col, synthetic_transfer_penalty=0.15)
    assert report.gave_up is False, report.reason
    assert report.recall_point is not None
    assert report.reworded_point is not None
    assert report.gap is not None
    assert report.gap > 0  # recall should exceed transfer with penalty
    col.close()


def test_transfer_gap_abstains_without_reviews():
    col = getEmptyCol()
    import_seed_deck(col)
    report = transfer_gap_report(col)
    assert report.gave_up is True
    col.close()
