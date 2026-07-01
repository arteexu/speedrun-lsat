# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Coverage gap report: untested schemas with suggested next items."""
from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from speedrun.scoring.memory import SCHEMA_TAG
from speedrun.scoring.memory import _schema_from_tags
from speedrun.scoring.performance import performance_score
from speedrun.tools.coverage_map import build_report
from speedrun.tools.coverage_map import DEFAULT_DECK
from speedrun.tools.coverage_map import DEFAULT_TAXONOMY

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class CoverageGap:
    schema: str
    axis: str
    exam_weight: float
    deck_items: int
    n_attempts: int
    suggestion: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tested_schemas(col) -> dict[str, int]:
    perf = performance_score(col, min_attempts_per_schema=1, min_attempts_overall=1)
    out: dict[str, int] = {}
    for schema, score in perf["per_schema"].items():
        out[schema] = score.n_attempts
    # also count cards present but never reviewed
    rows = col.db.all("SELECT tags FROM notes")
    for (tags,) in rows:
        schema = _schema_from_tags(tags, SCHEMA_TAG)
        if schema and schema not in out:
            out.setdefault(schema, 0)
    return out


def coverage_gap_report(
    col,
    *,
    taxonomy_path: Path = DEFAULT_TAXONOMY,
    deck_path: Path = DEFAULT_DECK,
    top_n: int = 20,
) -> list[CoverageGap]:
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    deck = json.loads(deck_path.read_text(encoding="utf-8"))
    deck_report = build_report(taxonomy, deck)
    items_per_schema: dict[str, int] = {}
    for item in deck["items"]:
        for sid in item.get("schemas", []):
            items_per_schema[sid] = items_per_schema.get(sid, 0) + 1

    tested = _tested_schemas(col)
    by_id = {s["id"]: s for s in taxonomy["schemas"]}
    gaps: list[CoverageGap] = []

    for sid, meta in sorted(by_id.items(), key=lambda x: -float(x[1].get("exam_weight", 0))):
        if not sid.startswith(("flaw.", "rc.", "qt.")):
            continue
        attempts = tested.get(sid, 0)
        deck_count = items_per_schema.get(sid, 0)
        if attempts >= 3 and deck_count >= 1:
            continue
        if attempts == 0:
            suggestion = (
                f"Add 1–2 original items tagged {sid}"
                if deck_count == 0
                else f"Review existing {deck_count} seed item(s) for {sid}"
            )
        else:
            suggestion = f"Need more attempts ({attempts}/3) on {sid}"
        gaps.append(
            CoverageGap(
                schema=sid,
                axis=meta.get("axis", ""),
                exam_weight=float(meta.get("exam_weight", 0)),
                deck_items=deck_count,
                n_attempts=attempts,
                suggestion=suggestion,
            )
        )

    gaps.sort(key=lambda g: (-g.exam_weight, g.n_attempts, -g.deck_items))
    return gaps[:top_n]


def format_gap_report(gaps: list[CoverageGap]) -> str:
    if not gaps:
        return "All primary schemas have sufficient coverage and attempts."
    lines = [f"{'schema':<40}{'weight':>8}{'deck':>6}{'att':>5}  suggestion", "-" * 90]
    for g in gaps:
        lines.append(
            f"{g.schema:<40}{g.exam_weight:>8.2f}{g.deck_items:>6}{g.n_attempts:>5}  {g.suggestion}"
        )
    return "\n".join(lines)
