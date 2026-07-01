# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the traversable concept map built from completed flashcards.

Encodes SPOV1 (schema-organised transfer) and SPOV2 (flaw-first mastery): nodes are
the schemas a student actually practiced, coloured by strength, and linked when they
appear on similar problems so the student can traverse strong -> weak regions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.concept_graph import (
    build_concept_graph,  # noqa: E402
    concept_graph_json,  # noqa: E402
)
from speedrun.dashboard import render_concept_map_html  # noqa: E402
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def _answer_all(col, deck_id, pattern=(3, 3, 1)):
    col.decks.select(deck_id)
    col.reset()
    i = 0
    while True:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, pattern[i % len(pattern)])
        i += 1
    return i


def test_empty_collection_has_no_nodes():
    col = getEmptyCol()
    g = build_concept_graph(col)
    assert g.nodes == []
    assert g.edges == []
    assert g.stats["n_nodes"] == 0
    col.close()


def test_nodes_appear_only_after_practice():
    col = getEmptyCol()
    result = import_seed_deck(col)
    # Importing alone (no reviews) should not populate the map.
    assert build_concept_graph(col).nodes == []
    answered = _answer_all(col, result.deck_id)
    assert answered > 0
    g = build_concept_graph(col)
    assert len(g.nodes) > 0
    # Nodes span multiple axes (flaws, question types, traps) => transfer view.
    axes = {n.axis for n in g.nodes}
    assert "flaw" in axes
    assert len(axes) >= 2
    col.close()


def test_similar_problems_are_linked_and_grouped():
    col = getEmptyCol()
    result = import_seed_deck(col)
    _answer_all(col, result.deck_id)
    g = build_concept_graph(col)
    # Co-occurrence edges connect schemas seen on the same card.
    assert any(e.kind == "shared" for e in g.edges)
    # Every edge references real nodes.
    ids = {n.id for n in g.nodes}
    for e in g.edges:
        assert e.source in ids and e.target in ids
    # Groups summarise families and are non-empty.
    assert g.groups
    assert sum(gr["count"] for gr in g.groups) == len(g.nodes)
    col.close()


def test_status_reflects_accuracy():
    col = getEmptyCol()
    result = import_seed_deck(col)
    # All correct => no node should be classified "weak".
    _answer_all(col, result.deck_id, pattern=(3,))
    g = build_concept_graph(col)
    assert all(n.status != "weak" for n in g.nodes)
    assert any(n.status in ("strong", "learning") for n in g.nodes)
    col.close()


def test_graph_is_json_serializable():
    col = getEmptyCol()
    result = import_seed_deck(col)
    _answer_all(col, result.deck_id)
    payload = concept_graph_json(col)
    text = json.dumps(payload)  # must not raise
    assert '"nodes"' in text and '"edges"' in text and '"groups"' in text
    node = payload["nodes"][0]
    for key in ("id", "label", "axis", "group", "status", "cards", "reviews"):
        assert key in node
    col.close()


def test_concept_map_html_renders():
    col = getEmptyCol()
    result = import_seed_deck(col)
    _answer_all(col, result.deck_id)
    html = render_concept_map_html(col)
    assert "sr-map-svg" in html
    assert "sr-concept-data" in html
    assert "srConceptMap" in html
    col.close()


def test_concept_map_html_empty_state():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    html = render_concept_map_html(col)
    assert "Complete some flashcards" in html
    col.close()
