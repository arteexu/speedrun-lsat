#!/usr/bin/env python3
"""Benchmark key Speedrun actions — p50/p95/worst (spec 7g).

Usage:
    python speedrun/tools/bench.py
    just bench
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.dashboard import render_dashboard_html  # noqa: E402
from speedrun.scoring.memory import memory_score  # noqa: E402
from speedrun.scoring.performance import performance_score  # noqa: E402
from speedrun.scoring.queue import ordered_cards  # noqa: E402
from speedrun.scoring.readiness import readiness_score  # noqa: E402
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402


def _percentiles(samples: list[float]) -> dict[str, float]:
    s = sorted(samples)
    n = len(s)
    return {
        "p50": s[n // 2],
        "p95": s[int(n * 0.95)],
        "worst": s[-1],
    }


def _bench(name: str, fn, *, n: int = 20) -> dict:
    times: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    stats = _percentiles(times)
    return {"action": name, "n": n, **stats}


def main() -> int:
    from anki.collection import Collection
    from tests.shared import getEmptyCol

    col = getEmptyCol()
    import_seed_deck(col)
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    while True:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)

    benches = [
        _bench("memory_score", lambda: memory_score(col)),
        _bench("performance_score", lambda: performance_score(col)),
        _bench("readiness_score", lambda: readiness_score(col)),
        _bench("ordered_cards", lambda: ordered_cards(col, limit=50)),
        _bench("render_dashboard", lambda: render_dashboard_html(col)),
    ]
    col.close()

    print("Speedrun benchmarks (seconds)")
    print("=" * 60)
    for b in benches:
        print(
            f"{b['action']:<22} p50={b['p50']:.4f}s  "
            f"p95={b['p95']:.4f}s  worst={b['worst']:.4f}s  (n={b['n']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
