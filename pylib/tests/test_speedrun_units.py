# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the additive course grouping (unit / lesson / order) data model."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.tools.assign_units import (  # noqa: E402
    UNIT_IDS,
    UNITS,
    assign_all,
    assign_unit,
    build_manifest,
    lesson_key,
    validate_manifest,
)
from speedrun.tools.import_seed_deck import build_tags, import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402

SEED = REPO_ROOT / "speedrun" / "data" / "seed_deck.json"


def _load_items():
    return json.loads(SEED.read_text(encoding="utf-8"))["items"]


def test_seed_items_all_assigned_and_manifest_valid():
    items = _load_items()
    for it in items:
        assert it.get("unit") in UNIT_IDS, it["id"]
        assert isinstance(it.get("lesson"), int) and it["lesson"] >= 1, it["id"]
        assert isinstance(it.get("order"), int) and it["order"] >= 10, it["id"]
    manifest = build_manifest(items)
    validate_manifest(items, manifest)
    assert {u["id"] for u in manifest} == UNIT_IDS


def test_assign_unit_routing_rules():
    causal_weaken = {
        "section": "LR",
        "stem_type": "qt.weaken",
        "schemas": ["flaw.causal.correlation_causation", "qt.weaken"],
    }
    assert assign_unit(causal_weaken) == "m3-causal"
    plain_weaken = {
        "section": "LR",
        "stem_type": "qt.weaken",
        "schemas": ["flaw.gap.unwarranted_assumption", "qt.weaken"],
    }
    assert assign_unit(plain_weaken) == "m5-impact"
    conditional_flaw = {
        "section": "LR",
        "stem_type": "qt.flaw",
        "schemas": ["flaw.conditional.mistaken_negation", "qt.flaw"],
    }
    assert assign_unit(conditional_flaw) == "m4-conditional"
    rc_item = {"section": "RC", "stem_type": "rc.main_point", "schemas": ["rc.main_point"]}
    assert assign_unit(rc_item) == "m8-rc"
    inference = {
        "section": "LR",
        "stem_type": "qt.inference_must_be_true",
        "schemas": ["qt.inference_must_be_true"],
    }
    assert assign_unit(inference) == "m6-inference"


def test_lesson_key_never_a_trap():
    # An item whose first schema is a trap must theme its lesson on the stem.
    item = {
        "section": "LR",
        "stem_type": "qt.strengthen",
        "schemas": ["trap.could_be_true", "qt.strengthen"],
    }
    assert lesson_key(item) == "qt.strengthen"


def test_assign_all_is_deterministic_and_idempotent():
    items = copy.deepcopy(_load_items())
    for it in items:  # wipe existing assignment
        it.pop("unit", None)
        it.pop("lesson", None)
        it.pop("order", None)
    a = copy.deepcopy(items)
    b = copy.deepcopy(items)
    assign_all(a)
    assign_all(b)
    a_map = {it["id"]: (it["unit"], it["lesson"], it["order"]) for it in a}
    b_map = {it["id"]: (it["unit"], it["lesson"], it["order"]) for it in b}
    assert a_map == b_map
    # Second pass changes nothing.
    assert assign_all(a) == 0


def test_assign_all_overwrite_false_preserves_hand_authored_unit():
    items = copy.deepcopy(_load_items())
    for it in items:
        it.pop("unit", None)
        it.pop("lesson", None)
        it.pop("order", None)
    items[0]["unit"] = "m8-rc"  # pretend a hand-authored assignment
    assign_all(items, overwrite=False)
    assert items[0]["unit"] == "m8-rc"
    # lesson/order still stamped consistently
    assert items[0]["lesson"] >= 1
    manifest = build_manifest(items)
    validate_manifest(items, manifest)


def test_build_tags_emits_unit_lesson_tags():
    item = {
        "section": "LR",
        "stem_type": "qt.weaken",
        "schemas": ["flaw.causal.correlation_causation", "qt.weaken"],
        "choices": [{"id": "A", "trap": "trap.out_of_scope"}],
        "unit": "m3-causal",
        "lesson": 1,
        "order": 20,
    }
    tags = build_tags(item)
    assert "sr:unit:m3-causal" in tags
    assert "sr:lesson:m3-causal:1" in tags
    assert "sr:order:20" in tags
    assert "LSAT::Unit::m3_causal" in tags
    assert "LSAT::Unit::m3_causal::L1" in tags
    assert all(" " not in t for t in tags)


def test_build_tags_backward_compatible_without_unit():
    item = {
        "section": "LR",
        "stem_type": "qt.weaken",
        "schemas": ["flaw.causal.correlation_causation", "qt.weaken"],
        "choices": [{"id": "A", "trap": "trap.out_of_scope"}],
    }
    tags = build_tags(item)
    assert not any(t.startswith("sr:unit:") for t in tags)
    assert not any(t.startswith("LSAT::Unit::") for t in tags)


def test_unit_tags_round_trip_through_import():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    # Every module should have at least one note discoverable by its unit tag.
    for u in UNITS:
        found = col.find_notes(f'"note:LSAT Speedrun" "tag:sr:unit:{u["id"]}"')
        assert found, u["id"]
    # A specific lesson tag is queryable.
    lesson_notes = col.find_notes('"note:LSAT Speedrun" "tag:sr:lesson:m8-rc:1"')
    assert lesson_notes
    col.close()


def test_optional_item_without_unit_still_imports():
    col = getEmptyCol()
    data = json.loads(SEED.read_text(encoding="utf-8"))
    trimmed = copy.deepcopy(data)
    # Drop grouping fields from one item -> must still import cleanly.
    trimmed["items"] = [copy.deepcopy(data["items"][0])]
    for k in ("unit", "lesson", "order"):
        trimmed["items"][0].pop(k, None)
    tmp = Path(col.path).with_name("trimmed_seed.json")
    tmp.write_text(json.dumps(trimmed), encoding="utf-8")
    result = import_seed_deck(col, deck_json=tmp, backup=False)
    assert result.added == 1
    col.close()
