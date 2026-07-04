#!/usr/bin/env python3
"""Seed a *rich, backdated demo review history* so every Speedrun analytics
feature renders with real data — for a live demo of a fresh dev profile.

Why this exists
---------------
A brand-new dev profile has almost no graded reviews, so every analytics surface
is empty: the three scores say "No score yet", the mistake graph has no edges, and
the recommender / focused-study "weakest areas" have nothing to rank. This tool
fabricates a realistic, spread-over-time history on the *existing* seed deck so
ALL of them populate at once:

* **Performance** (``speedrun/scoring/performance.py``) — needs graded attempts
  (``ease==1`` miss, ``ease>=2`` hit, ``time`` = latency). ``point`` is the
  latency-adjusted (on-budget) hit rate, so hits must come in under the per-section
  budget to count. Gives up under 10 attempts overall / 3 per schema.
* **Readiness** (``speedrun/scoring/readiness.py``) — by design needs **>=200**
  graded attempts AND **>=50%** exam-weight coverage across LR and RC (PRD §10.3).
* **Memory** (``speedrun/scoring/memory.py``) — reads each card's FSRS
  retrievability from the engine (``extract_fsrs_retrievability`` over ``c.data``).
  A card only has memory state after real review scheduling, so we set FSRS memory
  state (stability/difficulty + interval + last-review) directly on the cards,
  spread so retrievability lands in a realistic band.
* **Evidence gate** (``speedrun/scoring/guardrail.py``) — the dashboard withholds
  ALL three scores until the gate opens: enough distinct flashcards read plus broad
  flaw/trap/pattern coverage. The seed deck has fewer cards than the stock
  ``min_cards_read`` default, so we review every card (100% coverage) and relax
  ``min_cards_read`` in ``speedrun/config.json`` to fit the deck (restored on
  ``--clear``). See ``--no-guardrail`` to skip.
* **Mistake graph** (``speedrun/mistake_graph.py``) — a mistake is a missed review;
  edges need a schema PAIR co-missed across **>=2 day-buckets** with positive phi.
  We study a handful of chronic-weak schemas in shared sittings so correlated pairs
  co-miss on several days while other schemas miss on different days (so phi > 0).
* **Recommender / focused study** (``speedrun/ai/recommender.py``,
  ``speedrun/focus.py``) — need VARIED per-schema transfer weakness. We give a few
  schemas a chronic-weak profile, several a learning/shaky one, and most a strong
  one, so weak areas clearly surface and "study my weakest areas" returns targets.

Designed performance profile
----------------------------
Each primary schema is assigned a category that shapes its hit-rate, speed, ease
mix, and FSRS memory band:

* **chronic**  — ~42% raw accuracy, mostly slow-ish → transfer well under 50%
  (dashboard red / recommender top pick / "chronic" mistake node).
* **slow**     — accurate (~86%) but frequently over budget → ``speed_flag`` set.
* **learning** — ~66% accuracy → amber "learning" status.
* **strong**   — ~90% accuracy, fast → green "strong" status (most schemas).

Safety / idempotency (mirrors ``seed_sample_reviews.py``)
---------------------------------------------------------
* **No default target.** You MUST pass ``--col PATH`` or ``--base PROFILE_DIR``; it
  never touches real user data unless you point it there. Close the desktop app
  first (it locks the collection).
* **Backs up first** (unless ``--no-backup``).
* **Idempotent.** Synthetic revlog rows carry a sentinel ``factor``
  (``SENTINEL_FACTOR``); a sidecar file records each modified card's original state
  and the config change. Re-running restores then re-applies; ``--clear`` restores
  everything (revlog rows, card FSRS state, config threshold) and removes the
  sidecar. Only ever removes rows carrying the sentinel — real reviews are safe.

Usage
-----
    # against a COPY first (safest): cp the collection somewhere and target it
    PYTHONPATH=out/pylib out/pyenv/bin/python \
        speedrun/tools/seed_demo_stats.py --col /tmp/demo/collection.anki2

    # against the real dev profile (QUIT Anki first so the db isn't locked)
    PYTHONPATH=out/pylib out/pyenv/bin/python \
        speedrun/tools/seed_demo_stats.py \
        --col "$HOME/dev/speedrun-lsat/.ankidata/User 1/collection.anki2"

    # undo everything this tool did
    PYTHONPATH=out/pylib out/pyenv/bin/python \
        speedrun/tools/seed_demo_stats.py --col /path/to/collection.anki2 --clear
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.concept_graph import _schema_ids_from_tags  # noqa: E402
from speedrun.scoring.performance import _schema_from_tags  # noqa: E402
from speedrun.tools.import_seed_deck import (  # noqa: E402
    import_seed_deck,
    is_seed_deck_imported,
)

# Every synthetic revlog row carries this as its `factor` (ease-factor) field. Real
# reviews never store this value, so we can find + delete only our own rows while
# leaving the `time` column free for a realistic per-attempt latency.
SENTINEL_FACTOR = 424242

DAY_MS = 86_400_000
SPAN_DAYS = 45  # backdate reviews across ~6 weeks of "sittings"

# Config knob we relax so the evidence gate can open on the small seed deck.
CONFIG_PATH = REPO_ROOT / "speedrun" / "config.json"


# --------------------------------------------------------------------------- #
# Per-schema performance/memory profile
# --------------------------------------------------------------------------- #

# raw_acc: fraction of attempts that are hits (miss rate = 1 - raw_acc).
# fast:    fraction of hits that come in under the section budget (on-budget).
# ease:    ease values sampled for a hit (2=Hard, 3=Good, 4=Easy).
# n:       attempts-per-schema band (before the "cover every card" floor).
# stab:    FSRS stability band (days) -> higher = stronger memory.
# diff:    FSRS difficulty band (1-10).
# elapsed: days since last review band -> memory decays with elapsed/stability.
CATEGORIES: dict[str, dict] = {
    "chronic": dict(
        raw_acc=0.42, fast=0.72, ease=[2, 3], n=(20, 26),
        stab=(6.0, 14.0), diff=(7.0, 9.0), elapsed=(12, 22),
    ),
    "slow": dict(
        raw_acc=0.86, fast=0.42, ease=[3, 4], n=(14, 18),
        stab=(28.0, 44.0), diff=(5.0, 6.5), elapsed=(10, 18),
    ),
    "learning": dict(
        raw_acc=0.66, fast=0.90, ease=[2, 3, 3], n=(14, 18),
        stab=(20.0, 34.0), diff=(5.0, 7.0), elapsed=(12, 20),
    ),
    "strong": dict(
        raw_acc=0.90, fast=0.95, ease=[3, 3, 4], n=(12, 16),
        stab=(45.0, 70.0), diff=(3.0, 5.0), elapsed=(5, 14),
    ),
}

# Hand-picked chronic-weak schemas (red on the dashboard, top of the recommender).
# The two causal + two conditional schemas form the correlated mistake pairs.
CHRONIC_SCHEMAS = [
    "flaw.causal.correlation_causation",
    "flaw.causal.post_hoc",
    "flaw.conditional.nec_suff_confusion",
    "flaw.conditional.mistaken_reversal",
    "qt.parallel_reasoning",
    "rc.comparative_relationship",
]
# Accurate-but-slow schemas (trigger the speed_flag on Performance/Readiness).
SLOW_SCHEMAS = [
    "qt.method_of_reasoning",
    "flaw.scope.equivocation",
]
# Correlated pairs: each pair shares its study days so they co-miss across days.
CORRELATED_PAIRS = [
    ("flaw.causal.correlation_causation", "flaw.causal.post_hoc"),
    ("flaw.conditional.nec_suff_confusion", "flaw.conditional.mistaken_reversal"),
]


def _sidecar_path(col) -> Path:
    p = Path(col.path)
    return p.with_name(p.name + ".speedrun-demo-seed.json")


def _card_rows(col) -> list[tuple[int, str]]:
    """(card_id, tags) for every schema-tagged card, ordered for determinism."""
    return [
        (int(cid), tags)
        for cid, tags in col.db.all(
            """
            SELECT c.id, n.tags
            FROM cards c JOIN notes n ON c.nid = n.id
            WHERE n.tags LIKE '%sr:%'
            ORDER BY c.id
            """
        )
    ]


def _primary_schema(tags: str) -> str | None:
    return _schema_from_tags(tags)


def _section_of(schema: str) -> str:
    return "RC" if schema.startswith("rc.") else "LR"


def _budget_ms(schema: str) -> int:
    from speedrun.config import latency_budget_ms

    return latency_budget_ms(_section_of(schema))


def _assign_categories(schemas: list[str], rng: random.Random) -> dict[str, str]:
    """Deterministically label every primary schema with a profile category."""
    cats: dict[str, str] = {}
    for s in schemas:
        if s in CHRONIC_SCHEMAS:
            cats[s] = "chronic"
        elif s in SLOW_SCHEMAS:
            cats[s] = "slow"
    # Split the remainder: ~1 in 3 "learning", the rest "strong" (mostly green).
    remaining = [s for s in schemas if s not in cats]
    for i, s in enumerate(sorted(remaining)):
        cats[s] = "learning" if (i % 3 == 0) else "strong"
    return cats


def clear_synthetic(col) -> int:
    """Delete only the synthetic revlog rows this tool created."""
    n = col.db.scalar(
        "SELECT count(*) FROM revlog WHERE factor = ?", SENTINEL_FACTOR
    )
    col.db.execute("DELETE FROM revlog WHERE factor = ?", SENTINEL_FACTOR)
    return int(n or 0)


# --------------------------------------------------------------------------- #
# Card FSRS memory state (so the Memory score has data)
# --------------------------------------------------------------------------- #


def _snapshot_cards(col, card_ids: list[int]) -> list[dict]:
    """Capture the pre-seed scheduling + FSRS fields we are about to overwrite.

    We snapshot via the Card object (not the raw ``data`` blob) because Anki's DB
    proxy can't round-trip blob params. ``FsrsMemoryState`` is fully described by
    its stability/difficulty, so capturing those restores memory exactly."""
    snap: list[dict] = []
    for cid in card_ids:
        c = col.get_card(cid)
        mem = None
        if c.memory_state is not None:
            mem = {
                "stability": c.memory_state.stability,
                "difficulty": c.memory_state.difficulty,
            }
        snap.append(
            {
                "id": int(cid),
                "type": int(c.type),
                "queue": int(c.queue),
                "due": int(c.due),
                "ivl": int(c.ivl),
                "odue": int(c.odue),
                "odid": int(c.odid),
                "memory_state": mem,
                "last_review_time": c.last_review_time,
                "desired_retention": c.desired_retention,
                "decay": c.decay,
            }
        )
    return snap


def _restore_cards(col, snap: list[dict]) -> int:
    """Restore card scheduling + FSRS fields from a snapshot."""
    from anki.cards import FSRSMemoryState

    n = 0
    for s in snap:
        c = col.get_card(s["id"])
        c.type = s["type"]
        c.queue = s["queue"]
        c.due = s["due"]
        c.ivl = s["ivl"]
        c.odue = s["odue"]
        c.odid = s.get("odid", 0)
        mem = s.get("memory_state")
        c.memory_state = (
            FSRSMemoryState(stability=mem["stability"], difficulty=mem["difficulty"])
            if mem
            else None
        )
        c.last_review_time = s.get("last_review_time")
        c.desired_retention = s.get("desired_retention")
        c.decay = s.get("decay")
        col.update_card(c, skip_undo_entry=True)
        n += 1
    return n


def _apply_memory_state(
    col, by_card: dict[int, str], rng: random.Random
) -> int:
    """Give every reviewed card real FSRS memory state so Memory renders.

    ``by_card`` maps card id -> profile category. We set stability/difficulty and a
    consistent interval/last-review so ``extract_fsrs_retrievability`` returns a
    realistic recall probability in the category's band."""
    from anki.cards import FSRSMemoryState

    timing = col._backend.sched_timing_today()
    today = timing.days_elapsed
    now_s = int(time.time())

    n = 0
    for cid, cat in by_card.items():
        spec = CATEGORIES[cat]
        stability = round(rng.uniform(*spec["stab"]), 2)
        difficulty = round(rng.uniform(*spec["diff"]), 2)
        elapsed = rng.randint(*spec["elapsed"])
        ivl = max(1, int(round(stability)))
        card = col.get_card(cid)
        card.type = 2  # review
        card.queue = 2  # review
        card.ivl = ivl
        # last review = due - ivl (in days); we want it `elapsed` days ago.
        card.due = today - elapsed + ivl
        card.odue = 0
        card.odid = 0
        card.memory_state = FSRSMemoryState(
            stability=stability, difficulty=difficulty
        )
        card.last_review_time = now_s - elapsed * 86_400
        col.update_card(card, skip_undo_entry=True)
        n += 1
    return n


# --------------------------------------------------------------------------- #
# Evidence-gate threshold (so the dashboard opens on the small seed deck)
# --------------------------------------------------------------------------- #


def _relax_guardrail(col) -> dict | None:
    """Relax evidence-gate thresholds in config.json to what THIS deck can reach.

    The stock ``min_cards_read`` (250) exceeds the seed deck's card count, and
    pattern coverage is structurally capped (~6 question-types only ever appear as
    ``sr:qtype:`` tags, never as a card's primary ``sr:schema:``, so the gate can't
    count them). We lower only the thresholds the deck cannot satisfy, down to the
    achieved value with a small margin, and leave the rest alone. Returns a record
    describing the change (for restore) or None if nothing needed relaxing."""
    from speedrun.config import guardrail_thresholds, load_config
    from speedrun.scoring.guardrail import _taxonomy_totals, collection_evidence

    load_config.cache_clear()
    defaults = guardrail_thresholds()
    ev = collection_evidence(col)
    totals = _taxonomy_totals()

    def frac(seen: int, total: int) -> float:
        return (seen / total) if total else 0.0

    achieved = {
        "min_cards_read": ev["cards_read"],
        "min_concept_coverage": frac(ev["concepts_seen"], totals["concepts"]),
        "min_flaw_coverage": frac(ev["flaws_seen"], totals["flaws"]),
        "min_trap_coverage": frac(ev["traps_seen"], totals["traps"]),
        "min_pattern_coverage": frac(ev["patterns_seen"], totals["patterns"]),
    }

    changes: dict[str, Any] = {}
    for key, have in achieved.items():
        need = defaults[key]
        if have >= need:
            continue  # already satisfiable — don't touch it
        if key == "min_cards_read":
            changes[key] = max(1, int(have * 0.9))
        else:
            changes[key] = max(0.0, round(have - 0.02, 2))

    if not changes:
        return None

    raw = (
        json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if CONFIG_PATH.is_file()
        else {}
    )
    prev_guardrail = raw.get("guardrail")
    guardrail = dict(prev_guardrail) if isinstance(prev_guardrail, dict) else {}
    guardrail.update(changes)
    raw["guardrail"] = guardrail
    CONFIG_PATH.write_text(json.dumps(raw, indent=4) + "\n", encoding="utf-8")
    load_config.cache_clear()
    return {
        "path": str(CONFIG_PATH),
        "had_guardrail": prev_guardrail is not None,
        "prev_guardrail": prev_guardrail,
        "changes": changes,
    }


def _restore_guardrail(record: dict | None) -> None:
    if not record:
        return
    path = Path(record["path"])
    if not path.is_file():
        return
    raw = json.loads(path.read_text(encoding="utf-8"))
    if record.get("had_guardrail"):
        raw["guardrail"] = record.get("prev_guardrail")
    else:
        raw.pop("guardrail", None)
    path.write_text(json.dumps(raw, indent=4) + "\n", encoding="utf-8")
    from speedrun.config import load_config

    load_config.cache_clear()


# --------------------------------------------------------------------------- #
# Revlog synthesis
# --------------------------------------------------------------------------- #


def _pick_active_days(rng: random.Random, k: int) -> list[int]:
    return sorted(rng.sample(range(1, SPAN_DAYS + 1), k), reverse=True)


def seed_reviews(col, *, profile: str = "demo", seed: int = 7) -> dict:
    """Insert the designed backdated revlog history. Returns a summary dict."""
    if not is_seed_deck_imported(col):
        import_seed_deck(col)

    rng = random.Random(seed)
    rows = _card_rows(col)

    # Group cards by their primary schema.
    cards_by_schema: dict[str, list[int]] = {}
    card_cat: dict[int, str] = {}
    for cid, tags in rows:
        prim = _primary_schema(tags)
        if prim is None:
            continue
        cards_by_schema.setdefault(prim, []).append(cid)
    schemas = sorted(cards_by_schema)
    cats = _assign_categories(schemas, rng)

    # Shared study-day sets for the correlated pairs.
    pair_days: dict[str, list[int]] = {}
    for a, b in CORRELATED_PAIRS:
        if a in cards_by_schema and b in cards_by_schema:
            days = _pick_active_days(rng, 8)
            pair_days[a] = days
            pair_days[b] = days

    now_ms = int(time.time() * 1000)
    revlog: list[tuple] = []
    g = 0  # global unique offset (ms), keeps every synthetic id distinct

    def make_id(day_offset: int) -> int:
        nonlocal g
        g += 1
        # Subtract the offset so ids stay within the same local calendar day.
        return (now_ms - day_offset * DAY_MS) - g

    cat_counts = {k: 0 for k in CATEGORIES}
    forced_miss_days: dict[tuple[str, str], set[int]] = {}

    for schema in schemas:
        cat = cats[schema]
        cat_counts[cat] += 1
        spec = CATEGORIES[cat]
        schema_cards = cards_by_schema[schema]
        budget = _budget_ms(schema)

        # Attempts: category band, floored so every card is reviewed at least once
        # (keeps evidence-gate cards_read / coverage maxed out).
        n_attempts = max(rng.randint(*spec["n"]), len(schema_cards) + 2)

        active_days = pair_days.get(schema) or _pick_active_days(
            rng, min(9, max(4, n_attempts // 3))
        )

        for i in range(n_attempts):
            card_id = schema_cards[i % len(schema_cards)]
            day = active_days[i % len(active_days)]

            correct = rng.random() < spec["raw_acc"]
            if correct:
                on_budget = rng.random() < spec["fast"]
                ease = rng.choice(spec["ease"])
                if on_budget:
                    latency = int(rng.uniform(0.35 * budget, 0.9 * budget))
                else:
                    latency = int(rng.uniform(1.05 * budget, 1.5 * budget))
            else:
                ease = 1
                latency = int(rng.uniform(0.5 * budget, 1.3 * budget))

            revlog.append(
                (
                    make_id(day),      # id (ms, encodes the day)
                    card_id,           # cid
                    -1,                # usn
                    ease,              # ease (1=miss)
                    0,                 # ivl
                    0,                 # lastIvl
                    SENTINEL_FACTOR,   # factor (our sentinel)
                    latency,           # time (realistic latency)
                    1,                 # type (review)
                )
            )

    # Guarantee correlated pairs co-miss on several shared days (positive phi):
    # force a miss on each member for the first few shared days.
    for a, b in CORRELATED_PAIRS:
        if a not in pair_days:
            continue
        shared = pair_days[a][:5]
        forced_miss_days[(a, b)] = set(shared)
        for schema in (a, b):
            card_id = cards_by_schema[schema][0]
            budget = _budget_ms(schema)
            for day in shared:
                revlog.append(
                    (
                        make_id(day),
                        card_id,
                        -1,
                        1,  # forced miss
                        0,
                        0,
                        SENTINEL_FACTOR,
                        int(rng.uniform(0.6 * budget, 1.2 * budget)),
                        1,
                    )
                )

    col.db.executemany(
        "INSERT INTO revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        revlog,
    )

    # FSRS memory state on every reviewed card.
    for cid, tags in rows:
        prim = _primary_schema(tags)
        if prim is not None:
            card_cat[cid] = cats[prim]
    mem_snapshot = _snapshot_cards(col, list(card_cat))
    n_mem = _apply_memory_state(col, card_cat, rng)

    col.save()

    return {
        "rows_written": len(revlog),
        "n_schemas": len(schemas),
        "cat_counts": cat_counts,
        "cards_with_memory": n_mem,
        "correlated_pairs": [p for p in CORRELATED_PAIRS if p[0] in pair_days],
        "mem_snapshot": mem_snapshot,
        "span_days": SPAN_DAYS,
    }


# --------------------------------------------------------------------------- #
# Backup / open / CLI
# --------------------------------------------------------------------------- #


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
        f"{col_path.stem}.demo-stats-backup-{stamp}{col_path.suffix}"
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


def _load_sidecar(col) -> dict | None:
    p = _sidecar_path(col)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _write_sidecar(col, record: dict) -> None:
    _sidecar_path(col).write_text(
        json.dumps(record), encoding="utf-8"
    )


def _restore_all(col, sidecar: dict) -> tuple[int, int]:
    """Restore card state + config from a sidecar. Returns (cards, revlog rows)."""
    n_cards = _restore_cards(col, sidecar.get("mem_snapshot", []))
    _restore_guardrail(sidecar.get("guardrail"))
    removed = clear_synthetic(col)
    col.save()
    return n_cards, removed


def _clear(col) -> None:
    sidecar = _load_sidecar(col)
    if sidecar:
        n_cards, removed = _restore_all(col, sidecar)
        _sidecar_path(col).unlink(missing_ok=True)
        print(
            f"Cleared demo data: removed {removed} synthetic review row(s), "
            f"restored {n_cards} card(s) to their pre-seed state, and reverted the "
            f"config threshold."
        )
    else:
        removed = clear_synthetic(col)
        col.save()
        print(
            f"Removed {removed} synthetic review row(s). "
            f"(No sidecar found — card FSRS state / config not restored; use the "
            f"backup file if you need an exact revert.)"
        )


def _verify(col) -> None:
    """Print a compact populated-state report."""
    from speedrun.ai.recommender import recommend
    from speedrun.focus import weakest_subjects
    from speedrun.mistake_graph import build_mistake_graph
    from speedrun.scoring.guardrail import evidence_gate
    from speedrun.scoring.memory import memory_score
    from speedrun.scoring.performance import performance_score
    from speedrun.scoring.readiness import readiness_score

    gate = evidence_gate(col)
    mem = memory_score(col, gate=gate)["overall"]
    perf = performance_score(col, gate=gate)["overall"]
    ready = readiness_score(col, gate=gate)
    graph = build_mistake_graph(col)
    rec = recommend(col, limit=5)

    print("\n--- demo state ---")
    print(f"evidence gate open: {gate.open}")
    m = "No score" if mem.gave_up else f"{mem.point:.0%} (n={mem.n_reviewed})"
    p = "No score" if perf.gave_up else f"{perf.point:.0%} (n={perf.n_attempts})"
    r = "No score" if ready.gave_up else f"{ready.point:.0f} ({ready.low:.0f}-{ready.high:.0f})"
    print(f"Memory: {m}")
    print(f"Performance: {p}")
    print(f"Readiness: {r}")
    s = graph.stats
    print(f"Mistake graph: {s['n_nodes']} nodes, {s['n_edges']} edges "
          f"(chronic={s['chronic']}, shaky={s['shaky']}, occasional={s['occasional']})")
    print("Top recommendations: "
          + ", ".join(f"{rc.label} ({rc.weakness:.0%} weak)" for rc in rec.recommendations[:3]))
    print("Weakest subjects: " + ", ".join(weakest_subjects(col)))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--col", help="path to a collection.anki2 file")
    ap.add_argument("--base", help="an ANKI_BASE profile dir (close the app first)")
    ap.add_argument("--profile", default="demo", help="seed profile preset (default: demo)")
    ap.add_argument("--seed", type=int, default=7, help="RNG seed (deterministic)")
    ap.add_argument("--no-backup", action="store_true", help="skip auto-backup")
    ap.add_argument(
        "--no-guardrail",
        action="store_true",
        help="do NOT relax the evidence-gate threshold in config.json",
    )
    ap.add_argument(
        "--clear",
        action="store_true",
        help="restore everything this tool changed, then exit",
    )
    args = ap.parse_args(argv)

    col = _open_collection(args)
    try:
        if args.clear:
            _clear(col)
            return 0

        col.set_config("fsrs", True)  # Memory reads FSRS retrievability

        # Idempotency: restore any prior demo state before re-seeding.
        prior = _load_sidecar(col)
        if prior:
            _restore_all(col, prior)
            _sidecar_path(col).unlink(missing_ok=True)

        backup = None if args.no_backup else _backup(col)

        summary = seed_reviews(col, profile=args.profile, seed=args.seed)

        # Relax the evidence gate AFTER seeding so it calibrates to the coverage the
        # deck actually achieved (some thresholds are structurally unreachable here).
        guardrail_record = None if args.no_guardrail else _relax_guardrail(col)

        # Persist restore info (card snapshot + config change) in the sidecar.
        _write_sidecar(
            col,
            {
                "mem_snapshot": summary.pop("mem_snapshot"),
                "guardrail": guardrail_record,
                "created": int(time.time()),
            },
        )

        print(
            f"Seeded {summary['rows_written']} synthetic review(s) across "
            f"{summary['span_days']} days over {summary['n_schemas']} schemas."
        )
        print(f"Profile mix: {summary['cat_counts']}")
        print(f"Set FSRS memory state on {summary['cards_with_memory']} card(s).")
        print(f"Correlated pairs: {summary['correlated_pairs']}")
        if guardrail_record:
            print(
                f"Relaxed evidence-gate thresholds in config.json (restored on "
                f"--clear): {guardrail_record['changes']}"
            )
        if backup:
            print(f"Backup: {backup}")

        _verify(col)
        return 0
    finally:
        col.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
