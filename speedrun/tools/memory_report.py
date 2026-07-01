#!/usr/bin/env python3
"""Print the honest FSRS memory score for a collection (overall + per schema).

Usage:
    python speedrun/tools/memory_report.py --col /path/to/collection.anki2
    python speedrun/tools/memory_report.py --base ~/dev/speedrun-lsat/.ankidata
    python speedrun/tools/memory_report.py --col ... --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.scoring.memory import memory_score  # noqa: E402


def _fmt(score) -> str:
    if score.gave_up:
        return f"no score ({score.reason})"
    return (
        f"{score.point:.0%}  range {score.low:.0%}-{score.high:.0%}  "
        f"(n={score.n_reviewed}/{score.n_cards}, coverage {score.coverage:.0%})"
    )


def _open_collection(args):
    from anki.collection import Collection

    if args.col:
        return Collection(args.col)
    if args.base:
        matches = list(Path(args.base).expanduser().glob("**/collection.anki2"))
        if not matches:
            raise SystemExit(f"No collection.anki2 found under {args.base}")
        return Collection(str(matches[0]))
    raise SystemExit("Pass --col PATH or --base PROFILE_DIR")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--col")
    ap.add_argument("--base")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    col = _open_collection(args)
    try:
        result = memory_score(col)
    finally:
        col.close()

    if args.json:
        print(
            json.dumps(
                {
                    "overall": result["overall"].to_dict(),
                    "per_schema": {k: v.to_dict() for k, v in result["per_schema"].items()},
                },
                indent=2,
            )
        )
        return 0

    print("Memory score (FSRS recall)")
    print("=" * 40)
    print(f"Overall: {_fmt(result['overall'])}")
    print()
    print("Per schema:")
    for schema, score in result["per_schema"].items():
        print(f"  {schema:<40} {_fmt(score)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
