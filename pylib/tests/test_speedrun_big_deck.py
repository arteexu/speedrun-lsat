# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the big-deck generator used by the §18 latency benchmark.

The benchmark replicates the ~504-item seed deck up to ~50k cards. These tests
run a small replication (fast, offline) and assert the properties the benchmark
relies on: exact card count, unique ids, preserved schema tags (so the
schema-weighted queue still works), determinism, and cache reuse.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.scoring.queue import ordered_cards  # noqa: E402
from speedrun.tools.make_big_deck import build_big_collection  # noqa: E402

# Bigger than the ~504 seed items so replica passes wrap at least once, which is
# where id-uniqueness across passes actually matters.
SMALL_TARGET = 700


def test_build_big_collection_hits_exact_count_with_unique_ids(tmp_path):
    col, path = build_big_collection(
        target_cards=SMALL_TARGET, seed=1234, col_path=tmp_path / "big.anki2"
    )
    try:
        assert col.card_count() == SMALL_TARGET
        assert col.note_count() == SMALL_TARGET
        item_ids = [col.get_note(nid)["ItemId"] for nid in col.find_notes("")]
        # Every replica carries a distinct ItemId (…-r0000, …-r0001, …).
        assert len(set(item_ids)) == SMALL_TARGET
    finally:
        col.close()


def test_replicas_preserve_schema_tags(tmp_path):
    col, _ = build_big_collection(
        target_cards=SMALL_TARGET, seed=1234, col_path=tmp_path / "big.anki2"
    )
    try:
        # Preserving sr:schema: tags is what keeps the schema-weighted queue and
        # the three scores working on the replicated deck.
        tagged = col.find_notes("tag:sr:schema:*")
        assert len(tagged) == SMALL_TARGET
        # The schema-weighted queue must return cards on the big deck.
        assert ordered_cards(col, limit=25)
    finally:
        col.close()


def test_build_is_deterministic_for_a_given_seed(tmp_path):
    col_a, _ = build_big_collection(
        target_cards=SMALL_TARGET, seed=7, col_path=tmp_path / "a.anki2"
    )
    ids_a = sorted(col_a.get_note(nid)["ItemId"] for nid in col_a.find_notes(""))
    col_a.close()

    col_b, _ = build_big_collection(
        target_cards=SMALL_TARGET, seed=7, col_path=tmp_path / "b.anki2"
    )
    ids_b = sorted(col_b.get_note(nid)["ItemId"] for nid in col_b.find_notes(""))
    col_b.close()

    assert ids_a == ids_b


def test_reuse_skips_rebuild_when_cache_is_big_enough(tmp_path):
    cache = tmp_path / "cache.anki2"
    col1, _ = build_big_collection(
        target_cards=SMALL_TARGET, seed=1234, col_path=cache
    )
    col1.close()

    # Reusing asks for fewer cards than the cache holds -> reuse, do not rebuild.
    col2, path2 = build_big_collection(
        target_cards=SMALL_TARGET - 100, seed=1234, col_path=cache, reuse=True
    )
    try:
        assert path2 == cache
        assert col2.card_count() == SMALL_TARGET  # untouched, not rebuilt smaller
    finally:
        col2.close()
