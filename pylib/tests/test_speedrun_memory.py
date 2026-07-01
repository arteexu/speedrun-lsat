# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the seed-deck importer and the honest FSRS memory score."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import json  # noqa: E402

SEED_ITEM_COUNT = len(
    json.loads(
        (REPO_ROOT / "speedrun/data/seed_deck.json").read_text(encoding="utf-8")
    )["items"]
)

from speedrun.scoring.memory import (  # noqa: E402
    mean_ci,
    memory_score,
    score_from_retrievabilities,
)
from speedrun.tools.import_seed_deck import (  # noqa: E402
    DECK_NAME,
    NOTETYPE_NAME,
    SCHEMA_TAG,
    import_seed_deck,
)
from tests.shared import getEmptyCol  # noqa: E402

# ----------------------------- pure functions ------------------------------


def test_mean_ci_basic():
    point, low, high = mean_ci([0.8, 0.8, 0.8])
    assert abs(point - 0.8) < 1e-9
    assert low <= point <= high
    # identical values -> zero-width interval
    assert abs(high - low) < 1e-9


def test_score_gives_up_below_threshold():
    s = score_from_retrievabilities([0.9], label="x", min_reviewed=2)
    assert s.gave_up is True
    assert s.point is None
    assert "Not enough data" in s.reason


def test_score_reports_range_above_threshold():
    s = score_from_retrievabilities([0.9, 0.8, 0.7, None], label="x", min_reviewed=2)
    assert s.gave_up is False
    assert s.n_reviewed == 3
    assert s.n_cards == 4
    assert 0.0 <= s.low <= s.point <= s.high <= 1.0


# ------------------------------- importer ----------------------------------


def test_importer_creates_notetype_deck_and_tags():
    col = getEmptyCol()
    result = import_seed_deck(col)

    assert result.notetype_created is True
    assert result.added == SEED_ITEM_COUNT
    assert col.models.by_name(NOTETYPE_NAME) is not None
    assert DECK_NAME in [d.name for d in col.decks.all_names_and_ids()]

    # every imported note carries a schema tag the queue can read
    nids = col.find_notes(f'"note:{NOTETYPE_NAME}"')
    assert len(nids) == SEED_ITEM_COUNT
    note = col.get_note(nids[0])
    assert any(t.startswith(SCHEMA_TAG) for t in note.tags)

    # idempotent: importing again adds nothing
    again = import_seed_deck(col)
    assert again.added == 0
    assert again.skipped == SEED_ITEM_COUNT
    col.close()


# --------------------------- memory score ----------------------------------


def test_memory_abstains_without_reviews():
    col = getEmptyCol()
    import_seed_deck(col)
    result = memory_score(col)
    assert result["overall"].gave_up is True
    assert result["overall"].point is None
    assert result["overall"].n_reviewed == 0
    col.close()


def test_memory_score_after_fsrs_reviews():
    col = getEmptyCol()
    col.set_config("fsrs", True)
    result = import_seed_deck(col)

    # study the imported deck, not the default one
    col.decks.select(result.deck_id)
    col.reset()

    answered = 0
    while answered < 8:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)  # Good
        answered += 1
    assert answered >= 5, "need enough reviews to clear the give-up threshold"

    scores = memory_score(col)
    overall = scores["overall"]
    assert overall.gave_up is False, overall.reason
    assert overall.n_reviewed >= 5
    assert 0.0 < overall.point <= 1.0
    assert overall.low <= overall.point <= overall.high
    col.close()
