#!/usr/bin/env python3
"""Inject *synthetic graded reviews* into a collection so the Mistake graph renders
immediately — with deliberate correlated mistakes across a few schemas so real
edges (not just nodes) show up.

Why this exists
---------------
The Mistake graph (``speedrun/mistake_graph.py``) is built ONLY from missed reviews
(Anki ``ease == 1``). A brand-new dev profile has almost no graded LR reviews, so the
graph is empty or shows a handful of disconnected dots with zero correlation edges.
This script fabricates a realistic pattern of hits and misses on the seed deck so you
can see the graph "work" (nodes sized by miss count, coloured by miss-rate, and edges
linking schemas you miss together) without grinding through a study session.

How edges are made
------------------
``build_mistake_graph`` buckets misses by *study day* (when you've practised on >=2
distinct days) and draws an edge between two schemas when they are missed together in
>= ``MIN_CO_OCCUR`` (2) buckets AND their phi correlation is strictly positive. A phi
above zero needs buckets where the pair is *absent* too, so this script:

* misses a correlated PAIR of schemas together on several days (co-occurrence), and
* misses a different DISTRACTOR schema on other days (so the pair varies -> phi > 0),
* mixes in correct (ease==3) reviews so miss-rates are realistic and nodes get the
  chronic / shaky / occasional colours instead of all-red.

Safety
------
* No default target: you MUST pass ``--col PATH`` or ``--base PROFILE_DIR``. It will
  never touch real user data unless you point it there explicitly.
* Idempotent: every synthetic revlog row is stamped with a sentinel ``time`` value
  (``SENTINEL_TIME_MS``); re-running deletes prior synthetic rows first, so you can
  run it repeatedly without piling up duplicates. It only ever deletes rows carrying
  that sentinel — your real reviews are never removed.
* Makes a backup copy of the collection before writing (unless ``--no-backup``).

Usage
-----
    # against a specific collection file (safest — copy one first if unsure)
    PYTHONPATH=out/pylib out/pyenv/bin/python \
        speedrun/tools/seed_sample_reviews.py --col /path/to/collection.anki2

    # against a dev profile dir (CLOSE the app first so the db isn't locked)
    PYTHONPATH=out/pylib out/pyenv/bin/python \
        speedrun/tools/seed_sample_reviews.py --base ~/dev/speedrun-lsat/.ankidata

    # undo: remove only the synthetic rows this script created
    PYTHONPATH=out/pylib out/pyenv/bin/python \
        speedrun/tools/seed_sample_reviews.py --col /path/to/collection.anki2 --clear
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.concept_graph import _schema_ids_from_tags  # noqa: E402
from speedrun.mistake_graph import build_mistake_graph  # noqa: E402
from speedrun.tools.import_seed_deck import (  # noqa: E402
    import_seed_deck,
    is_seed_deck_imported,
)

# Every synthetic revlog row carries this as its `time` (ms-to-answer) field. Real
# reviews never take exactly this long, so we can find + delete only our own rows.
SENTINEL_TIME_MS = 424242

DAY_MS = 86_400_000


def _card_ids_by_schema(col) -> dict[str, list[int]]:
    """Map every schema id (from sr:schema:/sr:qtype:/sr:trap: tags) to its cards."""
    rows = col.db.all(
        """
        SELECT c.id, n.tags
        FROM cards c JOIN notes n ON c.nid = n.id
        WHERE n.tags LIKE '%sr:%'
        """
    )
    by_schema: dict[str, list[int]] = {}
    for cid, tags in rows:
        for sid in _schema_ids_from_tags(tags):
            by_schema.setdefault(sid, []).append(int(cid))
    return by_schema


def _pick_targets(by_schema: dict[str, list[int]]) -> tuple[str, str, str]:
    """Pick two schemas to correlate + one distractor, preferring *specific* axis
    ids (flaw.* / rc.* / qt.*) over pervasive trap.* tags so the pair can actually
    be absent from some buckets (a precondition for a positive phi correlation)."""
    def specific(sid: str) -> bool:
        return sid.startswith(("flaw.", "rc.", "qt."))

    ranked = sorted(
        (s for s in by_schema if specific(s)),
        key=lambda s: (-len(by_schema[s]), s),
    )
    if len(ranked) < 3:
        # Fall back to whatever exists if the deck is unusually small.
        ranked = sorted(by_schema, key=lambda s: (-len(by_schema[s]), s))
    if len(ranked) < 3:
        raise SystemExit(
            "Need at least 3 distinct schemas in the deck to synthesize correlated "
            "mistakes; is the seed deck imported?"
        )
    return ranked[0], ranked[1], ranked[2]


def clear_synthetic(col) -> int:
    n = col.db.scalar(
        "SELECT count(*) FROM revlog WHERE time = ?", SENTINEL_TIME_MS
    )
    col.db.execute("DELETE FROM revlog WHERE time = ?", SENTINEL_TIME_MS)
    return int(n or 0)


def _add_rev(col, rows: list[tuple], cid: int, ease: int, when_ms: int) -> None:
    # revlog: id, cid, usn, ease, ivl, lastIvl, factor, time, type
    # `id` must be a unique ms timestamp; the graph derives the study day from it.
    rows.append((when_ms, int(cid), -1, ease, 0, 0, 0, SENTINEL_TIME_MS, 1))


def seed_reviews(col, *, days: int = 4) -> dict:
    """Insert a synthetic hit/miss pattern that guarantees correlation edges.

    Returns a small summary dict (targets chosen, rows written)."""
    if not is_seed_deck_imported(col):
        import_seed_deck(col)

    by_schema = _card_ids_by_schema(col)
    pair_a, pair_b, distractor = _pick_targets(by_schema)

    now = int(time.time() * 1000)
    rows: list[tuple] = []
    # A monotonically increasing offset keeps every synthetic revlog id unique even
    # when several reviews land on the same simulated day.
    seq = 0

    def stamp(day_index: int) -> int:
        nonlocal seq
        seq += 1
        # Spread rows a few seconds apart within a day; keep them in the past.
        return now - (day_index * DAY_MS) + seq * 1000

    def miss(day_index: int, sid: str) -> None:
        for cid in by_schema.get(sid, [])[:1]:
            _add_rev(col, rows, cid, 1, stamp(day_index))

    def hit(day_index: int, sid: str, n: int = 2) -> None:
        for cid in by_schema.get(sid, [])[:n]:
            _add_rev(col, rows, cid, 3, stamp(day_index))

    days = max(days, 3)
    # First half of the days: miss the correlated PAIR together (co-occurrence).
    # Second half: miss only the DISTRACTOR (so the pair is absent -> phi > 0).
    pair_days = max(2, days // 2)
    for d in range(days):
        day_index = days - d  # older days first, today last
        if d < pair_days:
            miss(day_index, pair_a)
            miss(day_index, pair_b)
            hit(day_index, distractor)  # seen but not missed -> realistic miss-rate
        else:
            miss(day_index, distractor)
            hit(day_index, pair_a)
            hit(day_index, pair_b)

    col.db.executemany(
        "INSERT INTO revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    col.save()
    return {
        "pair": (pair_a, pair_b),
        "distractor": distractor,
        "rows_written": len(rows),
        "days": days,
    }


def _backup(col) -> Path | None:
    col_path = Path(col.path)
    if not col_path.is_file():
        return None
    try:
        col.db.execute("PRAGMA wal_checkpoint(FULL)")
    except Exception:
        pass
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = col_path.with_name(
        f"{col_path.stem}.sample-reviews-backup-{stamp}{col_path.suffix}"
    )
    shutil.copy2(col_path, dest)
    return dest


def _open_collection(args):
    from anki.collection import Collection

    if args.col:
        return Collection(args.col)
    if args.base:
        base = Path(args.base).expanduser()
        matches = list(base.glob("**/collection.anki2"))
        if not matches:
            raise SystemExit(f"No collection.anki2 found under {base}")
        return Collection(str(matches[0]))
    raise SystemExit(
        "Refusing to run without a target. Pass --col PATH or --base PROFILE_DIR "
        "(this never touches real user data by default)."
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--col", help="path to a collection.anki2 file")
    ap.add_argument("--base", help="an ANKI_BASE profile dir (close the app first)")
    ap.add_argument("--days", type=int, default=4, help="distinct study days to fake")
    ap.add_argument("--no-backup", action="store_true", help="skip auto-backup")
    ap.add_argument(
        "--clear",
        action="store_true",
        help="remove ONLY the synthetic rows this script created, then exit",
    )
    args = ap.parse_args(argv)

    col = _open_collection(args)
    try:
        if args.clear:
            removed = clear_synthetic(col)
            col.save()
            print(f"Removed {removed} synthetic review row(s).")
            return 0

        backup = None if args.no_backup else _backup(col)
        removed = clear_synthetic(col)  # idempotency: clear stale synthetic rows
        summary = seed_reviews(col, days=args.days)
        graph = build_mistake_graph(col)
        s = graph.stats
        print(
            f"Cleared {removed} stale synthetic row(s); wrote "
            f"{summary['rows_written']} new synthetic review(s) across "
            f"{summary['days']} day(s)."
        )
        print(
            f"Correlated pair: {summary['pair'][0]} <-> {summary['pair'][1]}; "
            f"distractor: {summary['distractor']}."
        )
        print(
            f"Mistake graph now: {s['n_nodes']} nodes, {s['n_edges']} edges "
            f"(bucket_mode={s['bucket_mode']}, buckets={s['n_buckets']}, "
            f"total_misses={s['total_misses']})."
        )
        if s["n_edges"] == 0:
            print(
                "WARNING: no edges formed — try a larger --days or verify the seed "
                "deck imported.",
                file=sys.stderr,
            )
        else:
            top = graph.edges[0]
            print(
                f"Strongest edge: {top.source} <-> {top.target} "
                f"(phi={top.weight}, co-missed in {top.co_miss} buckets)."
            )
        if backup:
            print(f"Backup: {backup}")
        return 0
    finally:
        col.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
