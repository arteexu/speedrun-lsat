# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for schema drill, health check, queue section/interleaving."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.scoring.queue import (  # noqa: E402
    build_search,
    ordered_cards,
    plain_due_cards,
)
from speedrun.tools.health_check import run_checks  # noqa: E402
from speedrun.tools.import_seed_deck import (  # noqa: E402
    DECK_CONFIG_NAME,
    DEFAULT_DECK_CONF_ID,
    HIGH_NEW_PER_DAY,
    HIGH_REV_PER_DAY,
    build_tags,
    ensure_deck_daily_limits,
    ensure_friendly_tags,
    import_seed_deck,
)
from speedrun.tools.schema_drill import (
    drill_search,
    schema_drill_queue,
    weakest_schemas,
)  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def test_build_search_section():
    s = build_search(section="LR")
    assert "sr:section:LR" in s


def test_drill_search_includes_schemas():
    q = drill_search(["flaw.causal.correlation_causation", "qt.weaken"])
    assert "sr:schema:flaw.causal.correlation_causation" in q


def test_build_tags_keeps_machine_and_adds_friendly():
    item = {
        "section": "LR",
        "stem_type": "qt.weaken",
        "schemas": ["flaw.causal.correlation_causation", "qt.weaken"],
        "choices": [{"id": "A", "trap": "trap.too_strong_extreme"}],
    }
    tags = build_tags(item)
    # Machine tags (engine keys) must be present and unchanged.
    assert "sr:schema:flaw.causal.correlation_causation" in tags
    assert "sr:trap:trap.too_strong_extreme" in tags
    assert "sr:section:LR" in tags
    # Friendly, hierarchical companions for the Browse sidebar.
    assert "LSAT::Section::Logical_Reasoning" in tags
    assert "LSAT::Traps::Too_strong_extreme" in tags
    assert any(t.startswith("LSAT::Flaws::") for t in tags)
    # No tag contains a space (Anki splits tags on whitespace).
    assert all(" " not in t for t in tags)


def test_ensure_friendly_tags_backfills_legacy_notes():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    # Simulate a legacy note that only has machine sr: tags (pre-friendly-tags).
    nid = col.find_notes('note:"LSAT Speedrun"')[0]
    note = col.get_note(nid)
    note.tags = [t for t in note.tags if t.startswith("sr:")]
    col.update_note(note)
    assert not any(t.startswith("LSAT::") for t in col.get_note(nid).tags)
    # Backfill adds friendly companions; second run is a no-op (idempotent).
    changed = ensure_friendly_tags(col)
    assert changed >= 1
    assert ensure_friendly_tags(col) == 0
    healed = col.get_note(nid).tags
    assert any(t.startswith("LSAT::") for t in healed)
    assert any(t.startswith("sr:") for t in healed)  # machine tags preserved
    col.close()


def test_weakest_schemas_returns_list():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    schemas = weakest_schemas(col, count=3)
    assert len(schemas) <= 3
    col.close()


def test_plain_due_cards():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    cards = plain_due_cards(col, limit=5)
    assert cards
    col.close()


def test_interleaving_off_mode():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    cards = ordered_cards(col, limit=5, interleaving=False)
    assert cards
    col.close()


def test_health_check_passes():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    results = run_checks(col)
    assert all(ok for _, ok, _ in results)
    col.close()


def test_schema_drill_queue():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    schemas, cards = schema_drill_queue(col, count=2, limit=10)
    assert schemas
    col.close()


# --------------------------------------------------------------------------- #
# Deck daily-limit config (uncapped study)
# --------------------------------------------------------------------------- #


def test_import_sets_high_daily_limits_scoped_to_speedrun_deck():
    col = getEmptyCol()
    # Snapshot the global Default options group before import.
    default_before = col.decks.get_config(DEFAULT_DECK_CONF_ID)
    new_before = default_before["new"]["perDay"]
    rev_before = default_before["rev"]["perDay"]

    result = import_seed_deck(col, backup=False)
    assert result.limits_applied is True

    deck = col.decks.get(result.deck_id, default=False)
    conf = col.decks.config_dict_for_deck_id(result.deck_id)
    # The Speedrun deck has its OWN dedicated options group, not the global one.
    assert int(deck["conf"]) != DEFAULT_DECK_CONF_ID
    assert conf["name"] == DECK_CONFIG_NAME
    assert conf["new"]["perDay"] == HIGH_NEW_PER_DAY
    assert conf["rev"]["perDay"] == HIGH_REV_PER_DAY

    # The global Default config is untouched (no global side effects).
    default_after = col.decks.get_config(DEFAULT_DECK_CONF_ID)
    assert default_after["new"]["perDay"] == new_before
    assert default_after["rev"]["perDay"] == rev_before
    col.close()


def test_ensure_deck_daily_limits_is_idempotent():
    col = getEmptyCol()
    result = import_seed_deck(col, backup=False)
    # Import already applied the limits; a re-run changes nothing.
    assert ensure_deck_daily_limits(col, result.deck_id) is False
    conf = col.decks.config_dict_for_deck_id(result.deck_id)
    assert conf["new"]["perDay"] == HIGH_NEW_PER_DAY
    assert conf["rev"]["perDay"] == HIGH_REV_PER_DAY
    col.close()


def test_ensure_deck_daily_limits_respects_deliberate_user_change():
    col = getEmptyCol()
    result = import_seed_deck(col, backup=False)
    # Student deliberately lowers New cards/day on the Speedrun group.
    conf = col.decks.config_dict_for_deck_id(result.deck_id)
    conf["new"]["perDay"] = 42
    col.decks.update_config(conf)
    # A subsequent import must NOT clobber that deliberate change.
    ensure_deck_daily_limits(col, result.deck_id)
    conf2 = col.decks.config_dict_for_deck_id(result.deck_id)
    assert conf2["new"]["perDay"] == 42
    col.close()
