#!/usr/bin/env python3
# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Benchmark key Speedrun actions on the shared 50,000-card deck (PRD §17 7h / §18).

Builds (or reuses) a ~50k-card "LSAT Speedrun" collection by replicating the seed
deck (see ``speedrun.tools.make_big_deck``), warms it with some graded reviews so
the three scores produce real numbers, then times each action and reports
**p50 / p95 / worst** with a **PASS / FAIL** against the §18 targets:

    button press acknowledged (answerCard)        p95 < 50 ms
    next card after grading (answerCard+getCard)   p95 < 100 ms
    dashboard first load (cold render)             p95 < 1 s
    dashboard refresh (warm render)                p95 < 500 ms
    cold start (open the 50k collection)           < 5 s

Sync is skipped (needs a live server); it is noted in the output.

Usage:
    python -m speedrun.tools.bench                 # default 50,000 cards
    python -m speedrun.tools.bench --cards 50000
    SPEEDRUN_BENCH_CARDS=50000 just bench
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# Default location for the cached pristine 50k build, so the (slow) replication
# pass runs once and every later `just bench` reuses it. Override with --cache.
DEFAULT_CACHE = REPO_ROOT / "out" / "speedrun-bigdeck"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.dashboard import render_dashboard_html  # noqa: E402
from speedrun.scoring.memory import memory_score  # noqa: E402
from speedrun.scoring.performance import performance_score  # noqa: E402
from speedrun.scoring.queue import ordered_cards  # noqa: E402
from speedrun.scoring.readiness import readiness_score  # noqa: E402
from speedrun.tools.make_big_deck import (  # noqa: E402
    DEFAULT_TARGET_CARDS,
    build_big_collection,
)

# §18 targets, in seconds. ``None`` means "measured/reported but no hard target".
TARGETS: dict[str, float | None] = {
    "button_press": 0.050,
    "next_card": 0.100,
    "dashboard_first_load": 1.0,
    "dashboard_refresh": 0.500,
    "cold_start": 5.0,
    # Kept from the original bench; no dedicated §18 target of their own.
    "memory_score": None,
    "performance_score": None,
    "readiness_score": None,
    "ordered_cards": None,
}


def _percentiles(samples: list[float]) -> dict[str, float]:
    s = sorted(samples)
    n = len(s)
    return {
        "p50": s[n // 2],
        "p95": s[min(n - 1, int(n * 0.95))],
        "worst": s[-1],
    }


def _summarize(name: str, times: list[float]) -> dict:
    return {"action": name, "n": len(times), **_percentiles(times)}


def _bench(name: str, fn, *, n: int = 20) -> dict:
    times: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return _summarize(name, times)


def _grade_loop(col, *, n: int) -> tuple[list[float], list[float]]:
    """Grade up to ``n`` cards, timing answerCard (button press) and the full
    answerCard+getCard round trip (next card after grading)."""
    press: list[float] = []
    nxt: list[float] = []
    for _ in range(n):
        card = col.sched.getCard()
        if card is None:
            break
        t0 = time.perf_counter()
        col.sched.answerCard(card, 3)
        press_dt = time.perf_counter() - t0
        t1 = time.perf_counter()
        col.sched.getCard()
        get_dt = time.perf_counter() - t1
        press.append(press_dt)
        nxt.append(press_dt + get_dt)
    return press, nxt


def _warm(col, *, grades: int) -> int:
    """Grade some cards so memory/performance/readiness have data to report."""
    graded = 0
    for _ in range(grades):
        card = col.sched.getCard()
        if card is None:
            break
        # Mix in some misses so performance/mistake analytics have signal.
        ease = 1 if graded % 5 == 0 else 3
        col.sched.answerCard(card, ease)
        graded += 1
    return graded


def _peak_rss_mb() -> float | None:
    try:
        import resource

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except Exception:
        return None
    # Linux reports KiB, macOS reports bytes.
    if sys.platform == "darwin":
        return rss / (1024 * 1024)
    return rss / 1024


def _bench_cold_start(path: Path, *, n: int = 5) -> tuple[dict, "object"]:
    """Time opening the on-disk 50k collection. Returns stats + an open handle to
    the last-opened collection (reused for the rest of the benches)."""
    from anki.collection import Collection

    times: list[float] = []
    col = None
    for _ in range(n):
        if col is not None:
            col.close()
        t0 = time.perf_counter()
        col = Collection(str(path))
        times.append(time.perf_counter() - t0)
    return _summarize("cold_start", times), col


def _bench_first_load(path: Path, *, n: int = 5) -> dict:
    """First dashboard render on a freshly opened collection (cold), n reopens."""
    from anki.collection import Collection

    times: list[float] = []
    for _ in range(n):
        col = Collection(str(path))
        t0 = time.perf_counter()
        render_dashboard_html(col)
        times.append(time.perf_counter() - t0)
        col.close()
    return _summarize("dashboard_first_load", times)


def _print_row(b: dict) -> None:
    target = TARGETS.get(b["action"])
    if target is None:
        verdict = "  —  "
    else:
        # Button press / next card / dashboard targets are p95; cold start is worst.
        metric = b["worst"] if b["action"] == "cold_start" else b["p95"]
        verdict = "PASS " if metric <= target else "FAIL "
    tgt_txt = "" if target is None else f"  (target {target * 1000:.0f} ms)"
    print(
        f"{verdict} {b['action']:<22} "
        f"p50={b['p50'] * 1000:8.2f}ms  "
        f"p95={b['p95'] * 1000:8.2f}ms  "
        f"worst={b['worst'] * 1000:8.2f}ms  (n={b['n']}){tgt_txt}"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    default_cards = int(os.environ.get("SPEEDRUN_BENCH_CARDS", DEFAULT_TARGET_CARDS))
    ap.add_argument(
        "--target",
        "--cards",
        dest="target",
        type=int,
        default=default_cards,
        help="deck size to benchmark on (default 50000 / $SPEEDRUN_BENCH_CARDS)",
    )
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument(
        "--warm-grades",
        type=int,
        default=2000,
        help="cards to pre-grade so the scores have data (default 2000)",
    )
    ap.add_argument(
        "--cache",
        type=Path,
        default=DEFAULT_CACHE,
        help=(
            "dir holding the cached pristine build, reused across runs "
            f"(default {DEFAULT_CACHE})"
        ),
    )
    ap.add_argument(
        "--rebuild",
        action="store_true",
        help="ignore the cache and rebuild the deck from scratch",
    )
    args = ap.parse_args(argv)

    # Build (or reuse) a pristine cached deck, then copy it to a throwaway working
    # file so warming never mutates the cache and each run starts from the same
    # deterministic state.
    cache_path = args.cache / f"pristine-{args.target}-seed{args.seed}.anki2"
    reuse = not args.rebuild
    if reuse and cache_path.exists():
        print(f"Reusing cached {args.target:,}-card deck at {cache_path}...")
    else:
        print(
            f"Building the shared {args.target:,}-card deck "
            "(replicating the seed deck)..."
        )
    t_build = time.perf_counter()
    cache_col, cache_path = build_big_collection(
        target_cards=args.target,
        seed=args.seed,
        col_path=cache_path,
        reuse=reuse,
        verbose=True,
    )
    build_secs = time.perf_counter() - t_build
    card_count = cache_col.card_count()
    cache_col.close()
    print(f"Deck ready: {card_count:,} cards ({build_secs:.1f}s) at {cache_path}")

    work_dir = Path(tempfile.mkdtemp(prefix="speedrun-bench-"))
    path = work_dir / "collection.anki2"
    shutil.copy2(cache_path, path)

    from anki.collection import Collection

    col = Collection(str(path))
    col.decks.select(col.decks.id("LSAT Speedrun"))
    warm = _warm(col, grades=min(args.warm_grades, card_count))
    print(f"Warmed with {warm:,} graded reviews.")
    # Persist the graded state to disk so the cold-start reopen sees the same deck.
    col.close()

    # Cold start (open the on-disk collection) + keep the last handle open.
    cold, col = _bench_cold_start(path, n=5)
    col.decks.select(col.decks.id("LSAT Speedrun"))

    # Review-loop actions (button press + next card).
    press, nxt = _grade_loop(col, n=50)
    button = _summarize("button_press", press)
    next_card = _summarize("next_card", nxt)

    # Dashboard first load is measured with fresh reopens above via _bench_first_load
    # (below); refresh is repeated warm renders on this handle.
    refresh = _bench("dashboard_refresh", lambda: render_dashboard_html(col), n=20)

    # Remaining scoring actions (kept from the original bench).
    others = [
        _bench("memory_score", lambda: memory_score(col)),
        _bench("performance_score", lambda: performance_score(col)),
        _bench("readiness_score", lambda: readiness_score(col)),
        _bench("ordered_cards", lambda: ordered_cards(col, limit=50)),
    ]
    col.close()

    first_load = _bench_first_load(path, n=5)

    peak = _peak_rss_mb()

    print()
    print("=" * 78)
    print(f"Speedrun latency benchmark — deck size used: {card_count:,} cards")
    print(f"Build time: {build_secs:.1f}s" + (f"  ·  peak RSS: {peak:,.0f} MB" if peak else ""))
    print("=" * 78)

    ordered = [
        button,
        next_card,
        first_load,
        refresh,
        cold,
        *others,
    ]
    for b in ordered:
        _print_row(b)

    # PASS/FAIL summary against §18.
    graded_targets = [b for b in ordered if TARGETS.get(b["action"]) is not None]
    fails = []
    for b in graded_targets:
        target = TARGETS[b["action"]]
        metric = b["worst"] if b["action"] == "cold_start" else b["p95"]
        if metric > target:
            fails.append(b["action"])
    print("=" * 78)
    print("Sync of a normal session: SKIPPED (needs a live sync server).")
    if fails:
        print(f"RESULT: FAIL — {len(fails)} target(s) missed: {', '.join(fails)}")
    else:
        print(f"RESULT: PASS — all {len(graded_targets)} §18 targets met on {card_count:,} cards.")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
