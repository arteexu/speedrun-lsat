# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for daily study goal and streak."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.study_goals import study_goal_report  # noqa: E402
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def test_study_goal_zero_before_reviews():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    report = study_goal_report(col)
    assert report.today.cards_reviewed == 0
    assert report.streak_days == 0
    col.close()


def test_study_goal_counts_reviews():
    col = getEmptyCol()
    result = import_seed_deck(col, backup=False)
    col.decks.select(result.deck_id)
    col.reset()
    card = col.sched.getCard()
    assert card
    col.sched.answerCard(card, 3)
    report = study_goal_report(col)
    assert report.today.cards_reviewed >= 1
    col.close()
