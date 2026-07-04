# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Smoke test for the demo-stats seeder (``speedrun/tools/seed_demo_stats.py``).

Mirrors the mistake-graph test style: build an empty collection, import the seed
deck, seed a backdated demo history, and assert every analytics feature it targets
now has real data — plus that the synthetic rows are sentinel-tagged, idempotent,
and fully removable.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.mistake_graph import build_mistake_graph  # noqa: E402
from speedrun.scoring.memory import memory_score  # noqa: E402
from speedrun.scoring.performance import performance_score  # noqa: E402
from speedrun.scoring.readiness import readiness_score  # noqa: E402
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from speedrun.tools.seed_demo_stats import (  # noqa: E402
    SENTINEL_FACTOR,
    _restore_cards,
    clear_synthetic,
    seed_reviews,
)
from tests.shared import getEmptyCol  # noqa: E402


def _seeded_col():
    col = getEmptyCol()
    col.set_config("fsrs", True)
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    return col


def test_seed_populates_all_scores():
    col = _seeded_col()
    summary = seed_reviews(col, seed=7)

    # Volume: comfortably over the readiness give-up line (>=200 attempts).
    assert summary["rows_written"] >= 200

    perf = performance_score(col)["overall"]
    assert not perf.gave_up
    assert perf.n_attempts >= 200
    assert 0.0 < perf.point <= 1.0

    mem = memory_score(col)["overall"]
    assert not mem.gave_up, mem.reason
    assert 0.0 < mem.point <= 1.0
    assert mem.n_reviewed >= 5

    ready = readiness_score(col)
    assert not ready.gave_up, ready.reason
    assert 120 <= ready.point <= 180

    col.close()


def test_seed_builds_mistake_graph_with_edges():
    col = _seeded_col()
    seed_reviews(col, seed=7)
    graph = build_mistake_graph(col)
    assert graph.stats["n_nodes"] > 0
    assert graph.stats["n_edges"] >= 3
    assert graph.stats["bucket_mode"] == "day"
    # At least one designed correlated pair should form an edge.
    pairs = {frozenset((e.source, e.target)) for e in graph.edges}
    assert (
        frozenset(("flaw.causal.correlation_causation", "flaw.causal.post_hoc"))
        in pairs
    )
    col.close()


def test_seed_creates_varied_weakness():
    col = _seeded_col()
    seed_reviews(col, seed=7)
    per_schema = performance_score(col)["per_schema"]
    scored = [s for s in per_schema.values() if not s.gave_up]
    assert len(scored) >= 20
    weak = [s for s in scored if s.point < 0.5]
    strong = [s for s in scored if s.point >= 0.75]
    # A demo needs both clear weaknesses (to recommend) and clear strengths.
    assert weak, "expected some weak schemas"
    assert strong, "expected some strong schemas"
    col.close()


def test_synthetic_rows_are_sentinel_tagged_and_clearable():
    col = _seeded_col()
    seed_reviews(col, seed=7)
    total = col.db.scalar("SELECT count(*) FROM revlog")
    synthetic = col.db.scalar(
        "SELECT count(*) FROM revlog WHERE factor = ?", SENTINEL_FACTOR
    )
    assert synthetic > 0
    assert synthetic == total  # empty col: every row is ours

    removed = clear_synthetic(col)
    assert removed == synthetic
    assert (
        col.db.scalar("SELECT count(*) FROM revlog WHERE factor = ?", SENTINEL_FACTOR)
        == 0
    )
    col.close()


def test_seed_is_idempotent_after_clear():
    col = _seeded_col()
    first = seed_reviews(col, seed=7)["rows_written"]
    clear_synthetic(col)
    second = seed_reviews(col, seed=7)["rows_written"]
    assert first == second
    assert (
        col.db.scalar("SELECT count(*) FROM revlog WHERE factor = ?", SENTINEL_FACTOR)
        == second
    )
    col.close()


def test_card_memory_snapshot_restores():
    col = _seeded_col()
    summary = seed_reviews(col, seed=7)
    assert not memory_score(col)["overall"].gave_up

    # Restoring the captured snapshot reverts the FSRS memory edits.
    _restore_cards(col, summary["mem_snapshot"])
    clear_synthetic(col)
    assert memory_score(col)["overall"].gave_up
    col.close()
