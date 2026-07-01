# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the mistake-correlation graph (SPOV2 / Insight 8).

The graph is built only from missed reviews (Anki ease==1). Nodes are the schemas
you get wrong; edges link mistakes that co-occur more than chance (phi coefficient
over miss-buckets). It surfaces weakness *clusters* so a student can remediate a
whole cluster at once instead of one card at a time.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.dashboard import (  # noqa: E402
    render_mistake_graph_html,
)
from speedrun.mistake_graph import (  # noqa: E402
    MIN_CO_OCCUR,
    _build_edges,
    _bucket_mode,
    _miss_buckets,
    _phi,
    _status_from_miss_rate,
    build_mistake_graph,
    mistake_graph_json,
)
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def test_phi_coefficient_known_values():
    # Perfect positive correlation.
    assert abs(_phi(2, 0, 0, 2) - 1.0) < 1e-9
    # Perfect negative correlation.
    assert abs(_phi(0, 2, 2, 0) + 1.0) < 1e-9
    # Independence (each cell equal) -> 0.
    assert abs(_phi(1, 1, 1, 1)) < 1e-9
    # Degenerate (a variable never varies) -> 0, not a crash.
    assert _phi(4, 0, 0, 0) == 0.0


def test_status_from_miss_rate():
    assert _status_from_miss_rate(0.9) == "chronic"
    assert _status_from_miss_rate(0.5) == "chronic"
    assert _status_from_miss_rate(0.3) == "shaky"
    assert _status_from_miss_rate(0.1) == "occasional"


def test_build_edges_requires_min_co_occurrence():
    present = {"flaw.a", "flaw.b", "flaw.c"}
    # a & b co-occur in 2 buckets (positively); a & c only in 1.
    buckets = [
        {"flaw.a", "flaw.b"},
        {"flaw.a", "flaw.b"},
        {"flaw.a", "flaw.c"},
        {"flaw.c"},
    ]
    edges = _build_edges(buckets, present)
    pairs = {(e.source, e.target) for e in edges}
    assert ("flaw.a", "flaw.b") in pairs
    assert ("flaw.a", "flaw.c") not in pairs  # only 1 co-occurrence < MIN_CO_OCCUR
    assert MIN_CO_OCCUR == 2
    ab = next(e for e in edges if e.source == "flaw.a" and e.target == "flaw.b")
    assert ab.co_miss == 2
    assert 0.0 < ab.weight <= 1.0


def test_build_edges_drops_ubiquitous_zero_correlation():
    present = {"flaw.everywhere", "flaw.b"}
    # 'everywhere' is in every bucket -> it never varies -> phi 0 -> no edge.
    buckets = [
        {"flaw.everywhere", "flaw.b"},
        {"flaw.everywhere", "flaw.b"},
        {"flaw.everywhere"},
        {"flaw.everywhere"},
    ]
    edges = _build_edges(buckets, present)
    assert edges == []


def test_build_edges_needs_two_buckets():
    assert _build_edges([{"flaw.a", "flaw.b"}], {"flaw.a", "flaw.b"}) == []


def test_bucket_mode_and_miss_buckets():
    present = {"flaw.a", "flaw.b"}
    multi_day = [
        ("2026-01-01", {"flaw.a"}),
        ("2026-01-01", {"flaw.b"}),
        ("2026-01-02", {"flaw.a", "flaw.b"}),
    ]
    assert _bucket_mode(multi_day) == "day"
    day_buckets = _miss_buckets(multi_day, present)
    # Two days -> two buckets; day 1 merges a and b.
    assert len(day_buckets) == 2
    assert {"flaw.a", "flaw.b"} in day_buckets

    single_day = [
        ("2026-01-01", {"flaw.a"}),
        ("2026-01-01", {"flaw.b"}),
    ]
    assert _bucket_mode(single_day) == "event"
    event_buckets = _miss_buckets(single_day, present)
    assert len(event_buckets) == 2  # one bucket per missed review


def test_empty_collection_has_no_nodes():
    col = getEmptyCol()
    graph = build_mistake_graph(col)
    assert graph.nodes == []
    assert graph.edges == []
    assert graph.stats["n_nodes"] == 0
    col.close()


def test_nodes_appear_only_after_misses_and_json_serializable():
    col = getEmptyCol()
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()

    # Before any review: no misses, no nodes.
    assert build_mistake_graph(col).nodes == []

    # Miss a batch of cards (answer Again) to create mistakes.
    missed = 0
    for _ in range(400):
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 1)  # Again == miss
        missed += 1
        if missed >= 12:
            break
    assert missed > 0

    graph = build_mistake_graph(col)
    assert graph.nodes, "expected mistake nodes after misses"
    for n in graph.nodes:
        assert n.misses >= 1
        assert n.attempts >= n.misses
        assert 0.0 <= n.miss_rate <= 1.0
        assert n.status in ("chronic", "shaky", "occasional")
    # Same-sitting misses share traps/qtypes across cards -> correlation edges.
    assert graph.stats["total_misses"] >= missed
    # Round-trips through JSON (for HTML embedding / FFI).
    payload = mistake_graph_json(col)
    assert json.loads(json.dumps(payload))["stats"]["n_nodes"] == len(graph.nodes)
    col.close()


def test_render_full_and_empty():
    col = getEmptyCol()
    empty_html = render_mistake_graph_html(col)
    assert empty_html.strip().startswith("<!DOCTYPE html>")
    assert "No mistakes recorded yet" in empty_html

    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    for _ in range(12):
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 1)
    html = render_mistake_graph_html(col)
    assert html.strip().startswith("<!DOCTYPE html>")
    for token in ("sr-mistake-data", "Mistake graph", "Chronic"):
        assert token in html
    col.close()
