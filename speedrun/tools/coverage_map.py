#!/usr/bin/env python3
"""Coverage map for the LSAT Speedrun deck.

Reads the schema taxonomy and a seed deck, validates that every item references
real schemas, and reports how much of the exam the deck covers -- overall, per
axis, and weighted by exam_weight. Coverage gates the readiness give-up rule
(PRD section 10): below the configured line, the app abstains from a score.

Usage:
    python speedrun/tools/coverage_map.py
    python speedrun/tools/coverage_map.py --json
    python speedrun/tools/coverage_map.py --taxonomy PATH --deck PATH

Exit code is non-zero if the deck references unknown schema ids (a data error),
so this can double as a CI check.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TAXONOMY = REPO_ROOT / "speedrun" / "taxonomy" / "lsat_taxonomy.json"
DEFAULT_DECK = REPO_ROOT / "speedrun" / "data" / "seed_deck.json"

# Give-up thresholds (mirror the readiness model defaults in the PRD).
MIN_COVERAGE_PER_SECTION = 0.50  # >= 50% schema coverage across LR and RC


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def normalize_weights(schemas: list[dict]) -> dict[str, float]:
    """Return per-schema weight normalized so each axis sums to 1.0."""
    axis_totals: dict[str, float] = defaultdict(float)
    for s in schemas:
        axis_totals[s["axis"]] += float(s.get("exam_weight", 0.0))
    norm: dict[str, float] = {}
    for s in schemas:
        total = axis_totals[s["axis"]] or 1.0
        norm[s["id"]] = float(s.get("exam_weight", 0.0)) / total
    return norm


def item_schemas(item: dict) -> list[str]:
    """All schema ids an item touches: item-level tags plus trap tags on choices."""
    ids = list(item.get("schemas", []))
    for choice in item.get("choices", []):
        trap = choice.get("trap")
        if trap:
            ids.append(trap)
    return ids


def build_report(taxonomy: dict, deck: dict) -> dict:
    schemas = taxonomy["schemas"]
    by_id = {s["id"]: s for s in schemas}
    norm = normalize_weights(schemas)

    # Which schemas does the deck touch, and how many items per schema.
    items_per_schema: dict[str, int] = defaultdict(int)
    unknown_refs: list[tuple[str, str]] = []
    for item in deck["items"]:
        for sid in item_schemas(item):
            if sid not in by_id:
                unknown_refs.append((item["id"], sid))
                continue
            items_per_schema[sid] += 1

    # Per-axis coverage: fraction of schemas covered, and weighted coverage.
    axes = sorted({s["axis"] for s in schemas})
    per_axis = {}
    for axis in axes:
        axis_schemas = [s for s in schemas if s["axis"] == axis]
        covered = [s for s in axis_schemas if items_per_schema.get(s["id"], 0) > 0]
        weighted_covered = sum(norm[s["id"]] for s in covered)
        per_axis[axis] = {
            "schemas_total": len(axis_schemas),
            "schemas_covered": len(covered),
            "count_coverage": len(covered) / len(axis_schemas) if axis_schemas else 0.0,
            "weighted_coverage": weighted_covered,
            "missing": [s["id"] for s in axis_schemas if items_per_schema.get(s["id"], 0) == 0],
        }

    # Section-level coverage (LR ~ flaw+question_type+trap; RC ~ rc_structure + rc traps).
    section_axes = {"LR": ["flaw", "question_type", "trap"], "RC": ["rc_structure"]}
    per_section = {}
    for section, ax_list in section_axes.items():
        totals = sum(per_axis[a]["schemas_total"] for a in ax_list if a in per_axis)
        cov = sum(per_axis[a]["schemas_covered"] for a in ax_list if a in per_axis)
        per_section[section] = {
            "schemas_total": totals,
            "schemas_covered": cov,
            "count_coverage": cov / totals if totals else 0.0,
        }

    total_schemas = len(schemas)
    total_covered = sum(1 for s in schemas if items_per_schema.get(s["id"], 0) > 0)

    gate_ok = all(
        per_section[s]["count_coverage"] >= MIN_COVERAGE_PER_SECTION for s in per_section
    )

    return {
        "taxonomy_version": taxonomy.get("version"),
        "deck": deck.get("deck"),
        "items": len(deck["items"]),
        "schemas_total": total_schemas,
        "schemas_covered": total_covered,
        "overall_count_coverage": total_covered / total_schemas if total_schemas else 0.0,
        "per_axis": per_axis,
        "per_section": per_section,
        "unknown_refs": unknown_refs,
        "give_up": {
            "min_coverage_per_section": MIN_COVERAGE_PER_SECTION,
            "readiness_gate_open": gate_ok,
            "explanation": (
                "Readiness abstains until each section reaches the coverage line."
                if not gate_ok
                else "Coverage line met for all sections."
            ),
        },
    }


def print_report(r: dict) -> None:
    print(f"Deck: {r['deck']}  (taxonomy v{r['taxonomy_version']})")
    print(f"Items: {r['items']}   Schemas covered: {r['schemas_covered']}/{r['schemas_total']} "
          f"({r['overall_count_coverage']:.0%})")
    print()
    print(f"{'axis':<14}{'covered':>10}{'count%':>9}{'weighted%':>11}")
    print("-" * 44)
    for axis, a in r["per_axis"].items():
        print(f"{axis:<14}{a['schemas_covered']:>4}/{a['schemas_total']:<4}"
              f"{a['count_coverage']:>8.0%}{a['weighted_coverage']:>11.0%}")
    print()
    print("Section coverage (gates readiness):")
    for section, s in r["per_section"].items():
        flag = "OK" if s["count_coverage"] >= r["give_up"]["min_coverage_per_section"] else "BELOW LINE"
        print(f"  {section}: {s['schemas_covered']}/{s['schemas_total']} "
              f"({s['count_coverage']:.0%})  [{flag}]")
    print()
    gate = r["give_up"]
    state = "OPEN — readiness may show" if gate["readiness_gate_open"] else "CLOSED — readiness ABSTAINS"
    print(f"Readiness gate: {state}")
    print(f"  {gate['explanation']} (line: {gate['min_coverage_per_section']:.0%} per section)")
    if r["unknown_refs"]:
        print()
        print("ERROR: deck references unknown schema ids:")
        for item_id, sid in r["unknown_refs"]:
            print(f"  {item_id} -> {sid}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    ap.add_argument("--deck", type=Path, default=DEFAULT_DECK)
    ap.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = ap.parse_args(argv)

    taxonomy = load_json(args.taxonomy)
    deck = load_json(args.deck)
    report = build_report(taxonomy, deck)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)

    return 1 if report["unknown_refs"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
