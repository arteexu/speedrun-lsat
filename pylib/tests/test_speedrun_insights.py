# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for insights: mastery map, wrong patterns, latency, trajectory."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.insights import (  # noqa: E402
    explain_schema,
    latency_histogram,
    readiness_trajectory,
    schema_mastery_map,
    wrong_answer_patterns,
)
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def test_mastery_map_lists_schemas():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    items = schema_mastery_map(col)
    assert items
    assert all(m.status in ("untested", "learning", "solid", "weak") for m in items)
    col.close()


def test_wrong_patterns_empty_without_again():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    assert wrong_answer_patterns(col) == []
    col.close()


def test_explain_schema_known():
    text = explain_schema("flaw.causal.correlation_causation")
    assert "correlation" in text.lower() or "caus" in text.lower()


def test_latency_histogram_after_review():
    col = getEmptyCol()
    result = import_seed_deck(col, backup=False)
    col.decks.select(result.deck_id)
    col.reset()
    card = col.sched.getCard()
    col.sched.answerCard(card, 3)
    buckets = latency_histogram(col, section="LR")
    assert buckets
    assert sum(b.count for b in buckets) >= 1
    col.close()


def test_readiness_trajectory_empty_without_data():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    assert readiness_trajectory(col) == []
    col.close()
