#!/usr/bin/env python3
"""Health check for Speedrun LSAT: DB, scores, queue RPC, config.

Usage:
    python speedrun/tools/health_check.py --base ~/.ankidata
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.config import load_config  # noqa: E402
from speedrun.config import validate_config  # noqa: E402
from speedrun.scoring.memory import memory_score  # noqa: E402
from speedrun.scoring.performance import performance_score  # noqa: E402
from speedrun.scoring.queue import ordered_cards  # noqa: E402
from speedrun.scoring.readiness import readiness_score  # noqa: E402


def run_checks(col) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    try:
        col.db.scalar("SELECT 1")
        results.append(("database", True, "ok"))
    except Exception as exc:
        results.append(("database", False, str(exc)))
        return results

    cfg_errors = validate_config(load_config())
    results.append(
        ("config", len(cfg_errors) == 0, "ok" if not cfg_errors else "; ".join(cfg_errors))
    )

    for name, fn in (
        ("memory_score", memory_score),
        ("performance_score", performance_score),
        ("readiness_score", readiness_score),
    ):
        try:
            fn(col)
            results.append((name, True, "computable"))
        except Exception as exc:
            results.append((name, False, str(exc)))

    try:
        cards = ordered_cards(col, limit=5)
        results.append(("queue_rpc", True, f"{len(cards)} card(s) returned"))
    except Exception as exc:
        results.append(("queue_rpc", False, str(exc)))

    return results


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--col", help="path to collection.anki2")
    ap.add_argument("--base", help="ANKI_BASE profile dir")
    args = ap.parse_args(argv)

    from speedrun.tools.import_seed_deck import _open_collection

    col = _open_collection(args)
    try:
        results = run_checks(col)
    finally:
        col.close()

    ok = True
    for name, passed, detail in results:
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {name}: {detail}")
        ok = ok and passed
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
