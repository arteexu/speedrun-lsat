#!/usr/bin/env python3
# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Build a large throwaway "LSAT Speedrun" collection by replicating the seed deck.

The PRD (§17 7h / §18) requires the latency benchmark to run on a shared
**50,000-card** deck. The seed deck (`speedrun/data/seed_deck.json`) only has ~504
authored items, so this tool replicates those items ~100× into a fresh, temporary
collection until it holds the requested number of cards.

Every replica is a *distinct* note (fresh random guid, unique ItemId first field)
but preserves everything the engine keys off: the `sr:schema:` / `sr:trap:` /
`sr:section:` tags, section, difficulty, the two-answer-fork fields, and the card
template. So the schema-weighted queue, the three scores (memory / performance /
readiness), and the dashboard all work on the big deck exactly as on the seed deck.

This never touches the checked-in `speedrun/data/seed_deck.json`; it builds into a
temporary `.anki2` file (or a path you pass) and returns the open collection.

Usage:
    # standalone: build 50k cards and print where the collection landed
    python -m speedrun.tools.make_big_deck --cards 50000

    # reused programmatically (e.g. by the benchmark):
    from speedrun.tools.make_big_deck import build_big_collection
    col, path = build_big_collection(target_cards=50000, seed=1234)
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.tools.import_seed_deck import (  # noqa: E402
    DECK_NAME,
    DEFAULT_DECK_JSON,
    build_tags,
    ensure_deck_daily_limits,
    ensure_notetype,
    populate_note,
)

DEFAULT_TARGET_CARDS = 50_000


def _load_seed_items(deck_json: Path = DEFAULT_DECK_JSON) -> list[dict[str, Any]]:
    data = json.loads(Path(deck_json).read_text(encoding="utf-8"))
    return list(data["items"])


def _replica_item(item: dict[str, Any], replica: int) -> dict[str, Any]:
    """A deep copy of a seed item with a unique id for the replica.

    Only the ``id`` (which becomes the note's first field, ItemId) changes; every
    schema/trap/section field the engine reads is left untouched so the replica is
    scored and queued identically to its source item.
    """
    clone = copy.deepcopy(item)
    clone["id"] = f"{item['id']}-r{replica:04d}"
    return clone


def build_big_collection(
    target_cards: int = DEFAULT_TARGET_CARDS,
    *,
    seed: int = 1234,
    col_path: str | Path | None = None,
    deck_json: Path = DEFAULT_DECK_JSON,
    progress_every: int = 5_000,
    reuse: bool = False,
    verbose: bool = False,
) -> tuple[Any, Path]:
    """Create a fresh collection holding ~``target_cards`` LSAT Speedrun cards.

    Replicates the seed deck's items (one card per item) until at least
    ``target_cards`` cards exist, stopping mid-replica so the final count is
    exactly ``target_cards`` (when a whole number of items can't hit it exactly).

    ``seed`` makes the run deterministic (it seeds Anki's guid/id generator, so a
    given ``target_cards`` + ``seed`` yields a reproducible collection). Returns
    the OPEN collection and its on-disk path; the caller is responsible for
    ``col.close()``.

    When ``reuse`` is True and ``col_path`` already holds a collection with at
    least ``target_cards`` cards, it is opened and returned as-is instead of being
    rebuilt. This is what lets the benchmark cache the (slow) 50k build between
    runs — see ``speedrun.tools.bench``.
    """
    from anki.collection import Collection

    try:
        import anki.utils as _anki_utils

        # Deterministic ids/guids across runs so the big deck is reproducible.
        _anki_utils.random.seed(seed)
    except Exception:  # pragma: no cover - defensive; determinism is best-effort
        pass

    if col_path is None:
        tmpdir = Path(tempfile.mkdtemp(prefix="speedrun-bigdeck-"))
        col_path = tmpdir / "collection.anki2"
    col_path = Path(col_path)

    # Reuse a cached build if it already has enough cards (avoids a fresh ~50k
    # replication pass every run). Callers that want a pristine deck copy it.
    if reuse and col_path.exists():
        col = Collection(str(col_path))
        if col.card_count() >= target_cards:
            if verbose:
                print(
                    f"Reusing cached deck with {col.card_count():,} cards "
                    f"at {col_path}",
                    flush=True,
                )
            return col, col_path
        col.close()

    # Anki refuses to create over an existing file left by a prior run.
    if col_path.exists():
        col_path.unlink()
    col_path.parent.mkdir(parents=True, exist_ok=True)

    col = Collection(str(col_path))
    nt, _created = ensure_notetype(col)
    deck_id = col.decks.id(DECK_NAME)
    col.decks.select(deck_id)
    ensure_deck_daily_limits(col, deck_id)

    items = _load_seed_items(deck_json)
    if not items:
        raise SystemExit("Seed deck has no items to replicate")

    t0 = time.perf_counter()
    added = 0
    replica = 0
    # Bulk-insert inside a single DB transaction: committing per note would make a
    # 50k build take minutes. add_note appends to the open transaction; we flush
    # periodically to keep memory flat.
    while added < target_cards:
        for item in items:
            if added >= target_cards:
                break
            clone = _replica_item(item, replica)
            note = col.new_note(nt)
            populate_note(note, clone)
            col.add_note(note, deck_id)
            added += 1
            if verbose and progress_every and added % progress_every == 0:
                rate = added / (time.perf_counter() - t0)
                print(
                    f"  ... {added:,}/{target_cards:,} cards "
                    f"({rate:,.0f}/s)",
                    flush=True,
                )
        replica += 1

    elapsed = time.perf_counter() - t0
    if verbose:
        card_total = col.card_count()
        print(
            f"Built {card_total:,} cards ({replica} replica passes) in "
            f"{elapsed:.1f}s -> {col_path}",
            flush=True,
        )
    return col, col_path


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--target",
        "--cards",
        dest="target",
        type=int,
        default=DEFAULT_TARGET_CARDS,
        help="target number of cards to build (default 50000)",
    )
    ap.add_argument("--seed", type=int, default=1234, help="RNG seed (reproducible)")
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="path for the generated collection.anki2 (default: a temp dir)",
    )
    ap.add_argument(
        "--reuse",
        action="store_true",
        help="reuse the deck at --out if it already has enough cards",
    )
    ap.add_argument("--deck-json", type=Path, default=DEFAULT_DECK_JSON)
    args = ap.parse_args(argv)

    col, path = build_big_collection(
        target_cards=args.target,
        seed=args.seed,
        col_path=args.out,
        deck_json=args.deck_json,
        reuse=args.reuse,
        verbose=True,
    )
    n_notes = col.note_count()
    n_cards = col.card_count()
    col.close()
    print(
        f"Generated collection with {n_notes:,} notes / {n_cards:,} cards at:\n{path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
