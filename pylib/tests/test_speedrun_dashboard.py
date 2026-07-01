# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the queue client helper and the (Qt-free) dashboard HTML renderer."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.dashboard import (  # noqa: E402
    render_dashboard_html,
    render_study_list_html,
)
from speedrun.scoring.queue import load_schema_weights, ordered_cards  # noqa: E402
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def test_load_schema_weights():
    weights = load_schema_weights()
    assert weights["flaw.causal.correlation_causation"] == 0.12
    assert weights["qt.necessary_assumption"] == 0.12
    # all values are non-negative floats
    assert all(isinstance(v, float) and v >= 0 for v in weights.values())


def test_ordered_cards_sorted_by_priority():
    col = getEmptyCol()
    import_seed_deck(col)
    cards = ordered_cards(col, limit=50)
    assert cards, "expected the imported deck to yield cards"
    priorities = [c.priority for c in cards]
    assert priorities == sorted(priorities, reverse=True)
    # every card resolved a schema and a positive weight (all seed schemas exist)
    assert all(c.schema for c in cards)
    assert cards[0].priority > 0
    col.close()


def test_dashboard_html_abstains_without_reviews():
    col = getEmptyCol()
    import_seed_deck(col)
    html = render_dashboard_html(col)
    assert "Memory" in html
    assert "Performance" in html
    assert "Readiness" in html
    # memory abstains (no reviews) and the honest wording is present
    assert "No score" in html
    col.close()


def test_study_list_html_lists_cards():
    col = getEmptyCol()
    import_seed_deck(col)
    html = render_study_list_html(col, limit=5)
    assert "priority" in html
    assert "sr:schema" not in html  # tags are stripped to bare schema ids
    assert "flaw." in html or "qt." in html or "rc." in html
    col.close()
