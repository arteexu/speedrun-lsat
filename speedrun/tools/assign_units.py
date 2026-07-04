#!/usr/bin/env python3
"""Course grouping for the LSAT Speedrun deck (CONTENT-PLAN.md section 4 & 5).

This is the small, additive, backward-compatible data-model change spec'd in the
content plan. It layers a curriculum (module -> lesson -> order) on top of the
existing schema-tagged deck WITHOUT touching the scheduler or the schema-weighted
queue:

* Item-level optional fields ``unit`` / ``lesson`` / ``order`` are stamped onto
  every item deterministically from its ``stem_type`` and primary schema. All are
  optional -- items without them still import (see ``import_seed_deck``); absent
  means "unassigned".
* A deck-level ``units`` manifest (a new top-level key in ``seed_deck.json``)
  records the module ordering, each module's schema families, whether it ends in a
  checkpoint, and the concrete ordered lessons discovered in the data.

The assignment is a pure function of an item's schema/stem, so it is fully
deterministic and re-runnable (idempotent). Run it standalone to (re)stamp the
seed deck:

    PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/assign_units.py

``add_practice_items.py`` also calls :func:`assign_all` after appending a batch,
so freshly authored items are grouped automatically.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.tools.import_seed_deck import _primary_schema  # noqa: E402

SEED = REPO_ROOT / "speedrun" / "data" / "seed_deck.json"
TAXONOMY = REPO_ROOT / "speedrun" / "taxonomy" / "lsat_taxonomy.json"

# ---------------------------------------------------------------------------
# The 8-module curriculum (CONTENT-PLAN.md section 4). Module 0 (Diagnostic) is a
# cold-open *mode*, not a set of owned items, so it is intentionally not a unit
# here -- every graded item lands in exactly one of these eight.
# ---------------------------------------------------------------------------
UNITS: list[dict[str, Any]] = [
    {
        "id": "m1-foundations",
        "title": "Argument foundations",
        "schemas": [
            "qt.main_conclusion",
            "qt.role_of_statement",
            "qt.method_of_reasoning",
            "flaw.structure.*",
        ],
        "checkpoint": True,
    },
    {
        "id": "m2-assumption",
        "title": "Assumptions & gaps",
        "schemas": [
            "qt.necessary_assumption",
            "qt.sufficient_assumption",
            "flaw.gap.*",
            "flaw.scope.*",
            "flaw.sampling.*",
        ],
        "checkpoint": True,
    },
    {
        "id": "m3-causal",
        "title": "Causal reasoning",
        "schemas": ["flaw.causal.*"],
        "checkpoint": True,
    },
    {
        "id": "m4-conditional",
        "title": "Conditional logic",
        "schemas": ["flaw.conditional.*"],
        "checkpoint": True,
    },
    {
        "id": "m5-impact",
        "title": "Strengthen, Weaken & Paradox",
        "schemas": ["qt.strengthen", "qt.weaken", "qt.paradox", "qt.evaluate"],
        "checkpoint": True,
    },
    {
        "id": "m6-inference",
        "title": "Inference & principles",
        "schemas": [
            "qt.inference_must_be_true",
            "qt.most_strongly_supported",
            "qt.principle_identify",
            "qt.principle_apply",
        ],
        "checkpoint": True,
    },
    {
        "id": "m7-point-parallel",
        "title": "Point at issue & parallel",
        "schemas": ["qt.point_at_issue", "qt.parallel_reasoning", "qt.parallel_flaw"],
        "checkpoint": True,
    },
    {
        "id": "m8-rc",
        "title": "Reading comprehension",
        "schemas": ["rc.*"],
        "checkpoint": True,
    },
]

UNIT_IDS = {u["id"] for u in UNITS}

# Question types that a module owns outright (routed by the stem the item asks).
_QT_UNIT = {
    "qt.main_conclusion": "m1-foundations",
    "qt.role_of_statement": "m1-foundations",
    "qt.method_of_reasoning": "m1-foundations",
    "qt.necessary_assumption": "m2-assumption",
    "qt.sufficient_assumption": "m2-assumption",
    "qt.strengthen": "m5-impact",
    "qt.weaken": "m5-impact",
    "qt.paradox": "m5-impact",
    "qt.evaluate": "m5-impact",
    "qt.inference_must_be_true": "m6-inference",
    "qt.most_strongly_supported": "m6-inference",
    "qt.principle_identify": "m6-inference",
    "qt.principle_apply": "m6-inference",
    "qt.point_at_issue": "m7-point-parallel",
    "qt.parallel_reasoning": "m7-point-parallel",
    "qt.parallel_flaw": "m7-point-parallel",
}

# Flaw families routed to a module (used for qt.flaw items and as a causal
# override for impact questions).
_FLAW_CATEGORY_UNIT = {
    "causal": "m3-causal",
    "conditional": "m4-conditional",
    "gap": "m2-assumption",
    "sampling": "m2-assumption",
    "scope": "m2-assumption",
    "structure": "m1-foundations",
}


def _flaw_category(schema_id: str) -> str | None:
    if schema_id.startswith("flaw."):
        parts = schema_id.split(".")
        if len(parts) >= 2:
            return parts[1]
    return None


def assign_unit(item: dict[str, Any]) -> str:
    """Deterministically map an item to exactly one module id.

    Rules (first match wins):
    1. RC items -> ``m8-rc``.
    2. ``qt.flaw`` items -> the module owning the primary flaw's family.
    3. Strengthen/Weaken/Evaluate on a *causal* argument -> ``m3-causal``.
    4. Any other stem -> the module that owns that question type.
    5. Fallback -> ``m1-foundations``.
    """
    if item.get("section") == "RC":
        return "m8-rc"
    primary = _primary_schema(item)
    stem = item.get("stem_type", "")
    if stem == "qt.flaw":
        cat = _flaw_category(primary)
        return _FLAW_CATEGORY_UNIT.get(cat or "", "m1-foundations")
    if stem in {"qt.strengthen", "qt.weaken", "qt.evaluate"} and primary.startswith(
        "flaw.causal."
    ):
        return "m3-causal"
    return _QT_UNIT.get(stem, "m1-foundations")


def lesson_key(item: dict[str, Any]) -> str:
    """The schema that defines the item's lesson within its module.

    The primary flaw/rc schema when present, else the question-type stem. Items
    that share a lesson key share a lesson (same underlying schema, taught
    together). A trap is never a lesson theme (traps live on choices), so we skip
    to the stem when an item has no flaw/rc schema."""
    for sid in item.get("schemas", []):
        if sid.startswith(("flaw.", "rc.")):
            return sid
    stem = item.get("stem_type")
    if stem:
        return stem
    schemas = item.get("schemas") or []
    return schemas[0] if schemas else ""


def _taxonomy_order(path: Path = TAXONOMY) -> dict[str, int]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {s["id"]: i for i, s in enumerate(data["schemas"])}


def assign_all(
    items: list[dict[str, Any]],
    *,
    overwrite: bool = True,
    taxonomy_path: Path = TAXONOMY,
) -> int:
    """Stamp ``unit`` / ``lesson`` / ``order`` on items. Returns count changed.

    Deterministic and idempotent. ``lesson`` is the 1-based rank of the item's
    lesson_key within its module (schemas ordered as in the taxonomy). ``order``
    is a 10-spaced sort key within a lesson, ramping easy->hard (by difficulty,
    then id). With ``overwrite=False`` a pre-existing ``unit`` is preserved (so a
    hand-authored assignment survives), but ``lesson`` and ``order`` are always
    recomputed globally so the numbering stays consistent with the manifest.
    """
    tax_order = _taxonomy_order(taxonomy_path)
    before = {
        id(it): (it.get("unit"), it.get("lesson"), it.get("order")) for it in items
    }

    # Pass 1: assign a unit to every item (respecting a hand-authored one when
    # overwrite is off).
    for it in items:
        if overwrite or "unit" not in it:
            it["unit"] = assign_unit(it)

    # Ordered lesson keys per unit (across ALL items so numbering is global).
    keys_by_unit: dict[str, set[str]] = {}
    for it in items:
        unit = it.get("unit")
        if unit:
            keys_by_unit.setdefault(unit, set()).add(lesson_key(it))
    lesson_index: dict[str, dict[str, int]] = {}
    for unit, keys in keys_by_unit.items():
        ordered = sorted(keys, key=lambda k: (tax_order.get(k, 10_000), k))
        lesson_index[unit] = {k: i + 1 for i, k in enumerate(ordered)}

    # Lesson is always recomputed so it matches the (rebuilt) manifest.
    for it in items:
        unit = it.get("unit")
        if unit:
            it["lesson"] = lesson_index[unit][lesson_key(it)]

    # Pass 2: order within each (unit, lesson), easy -> hard.
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for it in items:
        if "unit" in it and "lesson" in it:
            groups.setdefault((it["unit"], it["lesson"]), []).append(it)
    for group in groups.values():
        group.sort(key=lambda it: (int(it.get("difficulty", 0)), it.get("id", "")))
        for i, it in enumerate(group):
            it["order"] = (i + 1) * 10
    changed = 0
    for it in items:
        after = (it.get("unit"), it.get("lesson"), it.get("order"))
        if before.get(id(it)) != after:
            changed += 1
    return changed


def build_manifest(
    items: list[dict[str, Any]], taxonomy_path: Path = TAXONOMY
) -> list[dict[str, Any]]:
    """Return the ``units`` manifest with concrete lessons discovered in the data."""
    from speedrun.taxonomy.labels import schema_label

    tax_order = _taxonomy_order(taxonomy_path)
    keys_by_unit: dict[str, set[str]] = {}
    counts: dict[tuple[str, str], int] = {}
    for it in items:
        unit = it.get("unit")
        if not unit:
            continue
        k = lesson_key(it)
        keys_by_unit.setdefault(unit, set()).add(k)
        counts[(unit, k)] = counts.get((unit, k), 0) + 1

    manifest: list[dict[str, Any]] = []
    for base in UNITS:
        unit = base["id"]
        ordered = sorted(
            keys_by_unit.get(unit, set()), key=lambda k: (tax_order.get(k, 10_000), k)
        )
        lessons = [
            {
                "lesson": i + 1,
                "schema": k,
                "title": schema_label(k),
                "items": counts.get((unit, k), 0),
            }
            for i, k in enumerate(ordered)
        ]
        manifest.append(
            {
                "id": unit,
                "title": base["title"],
                "schemas": base["schemas"],
                "checkpoint": base["checkpoint"],
                "n_items": sum(l["items"] for l in lessons),
                "lessons": lessons,
            }
        )
    return manifest


def validate_manifest(items: list[dict[str, Any]], manifest: list[dict[str, Any]]) -> None:
    """Raise AssertionError if any item's unit/lesson is not backed by the manifest."""
    by_id = {u["id"]: u for u in manifest}
    for it in items:
        unit = it.get("unit")
        if unit is None:
            continue  # optional: unassigned items are allowed
        assert unit in by_id, f"{it['id']} references unknown unit {unit}"
        assert unit in UNIT_IDS, f"{it['id']} unit {unit} not in UNITS"
        lesson = it.get("lesson")
        assert isinstance(lesson, int) and lesson >= 1, f"{it['id']} bad lesson {lesson}"
        valid_lessons = {l["lesson"] for l in by_id[unit]["lessons"]}
        assert lesson in valid_lessons, f"{it['id']} lesson {lesson} not in {unit}"


def apply(seed_path: Path = SEED) -> dict[str, Any]:
    """Load the seed deck, (re)assign units, write the manifest, and save."""
    data = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    changed = assign_all(data["items"])
    data["units"] = build_manifest(data["items"])
    validate_manifest(data["items"], data["units"])
    Path(seed_path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {"changed": changed, "items": len(data["items"]), "units": len(data["units"])}


def main() -> int:
    result = apply()
    print(
        f"Assigned units to {result['items']} items "
        f"({result['changed']} updated) across {result['units']} modules."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
