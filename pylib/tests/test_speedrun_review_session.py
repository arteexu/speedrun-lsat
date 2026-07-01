# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""End-to-end review loop on the exam deck through the shared Rust engine.

This is the desktop counterpart of the mobile requirement: load the exam deck,
order it with the *schema-weighted queue implemented in Rust* (called over the
backend FFI, not a Python reimplementation), and run a real review session,
proving that answering cards changes engine state (revlog + scheduling).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.scoring.queue import SCHEMA_TAG_PREFIX, ordered_cards  # noqa: E402
from speedrun.tools.import_seed_deck import (  # noqa: E402
    DECK_NAME,
    import_seed_deck,
)
from tests.shared import getEmptyCol  # noqa: E402


def _import_exam_deck(col):
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    return result


def test_exam_deck_orders_through_rust_schema_queue():
    col = getEmptyCol()
    _import_exam_deck(col)

    # Shared engine call: this reaches the Rust `build_schema_weighted_queue` RPC.
    # The generated wrapper unwraps the single repeated field, so the return value
    # is directly the list of scored cards.
    scored = col._backend.build_schema_weighted_queue(
        search=f'deck:"{DECK_NAME}"',
        limit=50,
        schema_tag_prefix=SCHEMA_TAG_PREFIX,
        schema_weight={},
        schema_weakness={},
        time_pressured_schemas=[],
        time_pressure_factor=1.0,
        default_weight=1.0,
        default_weakness=1.0,
    )
    cards = list(scored)
    assert cards, "the exam deck should produce a schema-weighted queue"
    # every queued card carries a schema (unit of mastery)
    assert all(c.schema for c in cards)
    # priorities are sorted descending (the Rust ordering guarantee)
    priorities = [c.priority for c in cards]
    assert priorities == sorted(priorities, reverse=True)
    col.close()


def test_ordered_cards_helper_uses_engine_ordering():
    col = getEmptyCol()
    _import_exam_deck(col)
    cards = ordered_cards(
        col, limit=20, interleaving=True, use_performance_weakness=False
    )
    assert cards
    assert all(getattr(c, "schema", "") for c in cards)
    pr = [c.priority for c in cards]
    assert pr == sorted(pr, reverse=True)
    col.close()


def test_real_review_session_changes_engine_state():
    col = getEmptyCol()
    col.set_config("fsrs", True)
    _import_exam_deck(col)

    revlog_before = col.db.scalar("select count() from revlog")

    answered = 0
    schemas_seen: set[str] = set()
    while answered < 10:
        card = col.sched.getCard()
        if card is None:
            break
        for tag in card.note().tags:
            if tag.startswith(SCHEMA_TAG_PREFIX):
                schemas_seen.add(tag[len(SCHEMA_TAG_PREFIX):])
                break
        col.sched.answerCard(card, 3)  # Good
        answered += 1

    assert answered >= 5, "a real session should review several cards"
    revlog_after = col.db.scalar("select count() from revlog")
    # every answer is persisted by the shared engine
    assert revlog_after - revlog_before == answered
    # the session touched multiple distinct schemas (schema-interleaved review)
    assert len(schemas_seen) >= 2
    col.close()


def test_queue_reflects_review_progress():
    """After reviewing, answered new cards graduate out of the `is:new` pool, so
    the live new-card count drops -- the engine tracked the session."""
    col = getEmptyCol()
    col.set_config("fsrs", True)
    _import_exam_deck(col)

    new_before = len(col.find_cards(f'deck:"{DECK_NAME}" is:new'))
    assert new_before > 0

    reviewed = 0
    while reviewed < 6:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)
        reviewed += 1

    new_after = len(col.find_cards(f'deck:"{DECK_NAME}" is:new'))
    assert new_after < new_before
    col.close()
