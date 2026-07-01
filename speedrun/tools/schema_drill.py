#!/usr/bin/env python3
"""Schema drill mode — queue/review cards from the user's weakest schemas.

Usage:
    python speedrun/tools/schema_drill.py --base ~/.ankidata
    python speedrun/tools/schema_drill.py --base ~/.ankidata --count 5 --limit 30
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.config import schema_drill_count  # noqa: E402
from speedrun.scoring.performance import performance_score  # noqa: E402
from speedrun.scoring.performance import weakness_map  # noqa: E402
from speedrun.scoring.queue import ordered_cards  # noqa: E402


def weakest_schemas(col, *, count: int | None = None) -> list[str]:
    count = count or schema_drill_count()
    perf = performance_score(col)
    weak = weakness_map(perf["per_schema"])
    if not weak:
        # fall back to all schemas with zero performance data — use taxonomy weights
        from speedrun.scoring.queue import load_schema_weights

        weights = load_schema_weights()
        return sorted(weights, key=lambda s: -weights[s])[:count]
    return sorted(weak, key=lambda s: -weak[s])[:count]


def drill_search(schemas: list[str]) -> str:
    tag_clauses = " OR ".join(f'tag:"sr:schema:{s}"' for s in schemas)
    return f'deck:"LSAT Speedrun" ({tag_clauses})'


def schema_drill_queue(col, *, count: int | None = None, limit: int = 25):
    schemas = weakest_schemas(col, count=count)
    search = drill_search(schemas)
    cards = ordered_cards(col, limit=limit, search=search)
    return schemas, cards


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--col", help="path to collection.anki2")
    ap.add_argument("--base", help="ANKI_BASE profile dir")
    ap.add_argument("--count", type=int, help="weakest N schemas (default from config)")
    ap.add_argument("--limit", type=int, default=25, help="max cards in queue")
    args = ap.parse_args(argv)

    from speedrun.tools.import_seed_deck import _open_collection

    col = _open_collection(args)
    try:
        schemas, cards = schema_drill_queue(col, count=args.count, limit=args.limit)
    finally:
        col.close()

    print(f"Weakest schemas ({len(schemas)}): {', '.join(schemas)}")
    print(f"Drill queue ({len(cards)} cards):")
    for c in cards:
        print(f"  {c.priority:.3f}  {c.schema}  (weak={c.weakness:.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
