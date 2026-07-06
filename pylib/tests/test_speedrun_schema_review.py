# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The Speedrun-native review session (§9/§11 blocker).

Proves the live desktop review path grades cards in *schema-weighted priority
order* through the shared Rust scheduler (not native scheduler order), that undo
works after grading via the new path (§9.3), and that the number of revlog rows
written equals the number of cards graded (no lost / double-counted reviews).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.scoring.queue import (  # noqa: E402
    DUE_STATE_FILTER,
    SchemaWeightedReview,
    ordered_card_ids,
    restrict_to_due,
)
from speedrun.tools.import_seed_deck import DECK_NAME, import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def _import_exam_deck(col):
    result = import_seed_deck(col, backup=False)
    col.decks.select(result.deck_id)
    col.reset()
    return result


def _revlog_count(col) -> int:
    return int(col.db.scalar("select count() from revlog"))


# --------------------------------------------------------------------------- #
# Gap 1: schema-weighted graded order + undo + no double-count
# --------------------------------------------------------------------------- #


def test_review_session_orders_by_schema_priority():
    col = getEmptyCol()
    _import_exam_deck(col)
    # All-default weakness (1.0) so priority == exam_weight: a fully deterministic,
    # taxonomy-driven order that does not depend on prior attempts.
    session = SchemaWeightedReview(
        col,
        limit=100,
        use_performance_weakness=False,
        weaknesses={},
        time_pressured=[],
        time_pressure_factor=1.0,
    )
    prios = session.priority_order()
    assert prios, "the exam deck should produce a schema-weighted queue"
    # The queue is sorted by points-at-stake, highest first (the Rust guarantee).
    assert prios == sorted(prios, reverse=True)
    assert prios[0] == max(prios)
    col.close()


def test_graded_order_follows_queue_and_no_double_count():
    col = getEmptyCol()
    col.set_config("fsrs", True)
    _import_exam_deck(col)

    session = SchemaWeightedReview(
        col,
        limit=15,
        use_performance_weakness=False,
        weaknesses={},
        time_pressured=[],
        time_pressure_factor=1.0,
    )
    intended = session.schema_order()
    intended_prios = session.priority_order()
    assert len(intended) >= 5

    before = _revlog_count(col)
    graded = 0
    while True:
        card = session.current_card()
        if card is None:
            break
        session.answer(card, 3, latency_ms=4200)  # Good, 4.2s
        graded += 1
    after = _revlog_count(col)

    # Every card graded exactly once -> one revlog row each, none lost/doubled.
    assert graded == len(intended)
    assert after - before == graded
    # The graded order is exactly the schema-weighted priority order.
    graded_schemas = [g["schema"] for g in session.graded]
    assert graded_schemas == intended
    # Highest-priority schema was graded first.
    assert intended_prios[0] == max(intended_prios)
    # Distinct cards only (no card graded twice).
    graded_ids = [g["card_id"] for g in session.graded]
    assert len(graded_ids) == len(set(graded_ids))
    # Latency was recorded per attempt on the shared engine (SPOV4).
    recorded = col.db.list("select time from revlog order by id desc limit ?", graded)
    assert all(t > 0 for t in recorded)
    col.close()


def test_undo_after_new_review_path_reverts_exactly_one_review():
    col = getEmptyCol()
    col.set_config("fsrs", True)
    _import_exam_deck(col)

    session = SchemaWeightedReview(col, limit=10, use_performance_weakness=False)
    before = _revlog_count(col)

    n = 0
    while n < 4:
        card = session.current_card()
        if card is None:
            break
        session.answer(card, 3)
        n += 1
    assert n == 4
    assert _revlog_count(col) == before + 4

    # §9.3: undo works after grading through the new path.
    assert col.undo_status().undo, "an undo checkpoint should exist after answering"
    assert session.undo() is True
    assert _revlog_count(col) == before + 3
    assert len(session.graded) == 3
    # The reverted card is presented again (cursor stepped back).
    assert session.remaining == 10 - 3
    col.close()


def test_ordered_card_ids_matches_session_order():
    col = getEmptyCol()
    _import_exam_deck(col)
    ids = ordered_card_ids(col, limit=12, use_performance_weakness=False)
    session = SchemaWeightedReview(col, limit=12, use_performance_weakness=False)
    assert ids == session.card_ids()
    col.close()


# --------------------------------------------------------------------------- #
# Gap 2: due-card filtering
# --------------------------------------------------------------------------- #


def test_restrict_to_due_wraps_with_due_state_filter():
    out = restrict_to_due('deck:"LSAT Speedrun"')
    assert out == f'(deck:"LSAT Speedrun") {DUE_STATE_FILTER}'
    assert "is:due" in out and "is:new" in out


def test_queue_ranks_only_studyable_cards():
    col = getEmptyCol()
    col.set_config("fsrs", True)
    _import_exam_deck(col)

    # Fresh deck: all cards are new (studyable), so the queue is non-empty even
    # though nothing is `is:due` yet.
    fresh = SchemaWeightedReview(col, limit=200, use_performance_weakness=False)
    assert fresh.total > 0

    # Grade some cards Easy so they graduate to a multi-day interval (scheduled to
    # the future, not due, not new). The due-filtered queue must then exclude them.
    reviewed_ids = []
    for _ in range(6):
        card = fresh.current_card()
        if card is None:
            break
        reviewed_ids.append(card.id)
        fresh.answer(card, 4)
    # Confirm they really left the studyable pool before asserting on the queue.
    graduated = [
        cid
        for cid in reviewed_ids
        if not col.find_cards(f"cid:{cid} (is:due OR is:new)")
    ]
    assert graduated, "Easy should graduate at least one card out of the due/new pool"

    requeued = SchemaWeightedReview(col, limit=500, use_performance_weakness=False)
    requeued_ids = set(requeued.card_ids())
    # The graduated (now future-scheduled) cards are no longer ranked.
    assert not (set(graduated) & requeued_ids)
    # Sanity: without the due filter, those cards WOULD still be ranked.
    all_ranked = set(ordered_card_ids(col, limit=500, use_performance_weakness=False, due_only=False))
    assert set(graduated) & all_ranked
    col.close()
