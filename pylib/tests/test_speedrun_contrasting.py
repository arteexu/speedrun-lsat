# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the contrasting-pairs drill (SPOV1 / Insight 3).

Comparison of two same-structure items is what produces transfer, so the drill
pairs items flaw-first (same flaw, different topic) and falls back to same-family
pairs for discrimination. Self-ratings are training signal only and must never
feed the scores (honesty rule).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.config import (
    contrasting_pairs_count,  # noqa: E402
    validate_config,  # noqa: E402
)
from speedrun.contrasting import (  # noqa: E402
    ContrastSet,
    build_contrasting_pairs,
    contrasting_practice_summary,
    record_contrast_result,
    render_contrasting_drill_html,
)
from speedrun.session_logger import SessionLogger  # noqa: E402
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def test_pairs_have_no_self_pairs_and_are_deterministic():
    a = build_contrasting_pairs(count=8)
    b = build_contrasting_pairs(count=8)
    assert a.stats["n_pairs"] > 0
    seq_a = [(p.item_a.id, p.item_b.id) for p in a.pairs]
    seq_b = [(p.item_a.id, p.item_b.id) for p in b.pairs]
    assert seq_a == seq_b  # deterministic
    for p in a.pairs:
        assert p.item_a.id != p.item_b.id


def test_same_flaw_pairs_are_preferred_when_available():
    cset = build_contrasting_pairs(count=50)
    same_flaw = [p for p in cset.pairs if p.relation == "same_flaw"]
    # The seed deck has at least one flaw with two items.
    assert same_flaw, "expected at least one same-flaw pair from the seed deck"
    for p in same_flaw:
        assert p.item_a.flaw_id == p.item_b.flaw_id
        assert p.shared_schema == p.item_a.flaw_id


def test_same_category_fallback_pairs_distinct_flaws():
    cset = build_contrasting_pairs(count=50)
    same_cat = [p for p in cset.pairs if p.relation == "same_category"]
    assert same_cat, "expected same-category fallback pairs"
    for p in same_cat:
        assert p.item_a.flaw_id != p.item_b.flaw_id
        assert p.shared_schema is None


def test_count_is_respected():
    assert len(build_contrasting_pairs(count=3).pairs) <= 3
    assert len(build_contrasting_pairs(count=0).pairs) == 0


def test_no_pairs_when_no_flaw_items(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(
        json.dumps(
            {
                "deck": "t",
                "items": [
                    {
                        "id": "x1",
                        "section": "LR",
                        "schemas": ["qt.weaken"],
                        "choices": [],
                    },
                    {
                        "id": "x2",
                        "section": "RC",
                        "schemas": ["rc.main_point"],
                        "choices": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    cset = build_contrasting_pairs(count=5, seed_path=seed)
    assert cset.pairs == []


def test_weakness_ordering_never_demotes_a_weak_family():
    # Baseline order without a collection (exam-weight order).
    baseline = build_contrasting_pairs(col=None, count=50)
    base_cats = [p.category for p in baseline.pairs]

    col = getEmptyCol()
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    # Answer each due card once (Good) so there is a collection with reviews; the
    # weakness path must run without crashing and stay deterministic. Bounded to
    # avoid any scheduler re-show loop.
    for _ in range(500):
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)
    with_col = build_contrasting_pairs(col=col, count=50)
    assert with_col.stats["n_pairs"] == baseline.stats["n_pairs"]
    # Ordering stays deterministic and returns the same set of categories.
    assert set(p.category for p in with_col.pairs) == set(base_cats)
    again = build_contrasting_pairs(col=col, count=50)
    assert [p.item_a.id for p in again.pairs] == [p.item_a.id for p in with_col.pairs]
    col.close()


def test_render_full_and_embed_and_empty():
    cset = build_contrasting_pairs(count=4)
    full = render_contrasting_drill_html(cset)
    assert full.strip().startswith("<!DOCTYPE html>")
    for token in ("sr-drill-data", "Reveal shared structure", "sr-cd-stage", "data-r"):
        assert token in full
    embed = render_contrasting_drill_html(cset, embed=True)
    assert "<!DOCTYPE html>" not in embed
    assert 'class="sr-dash"' in embed
    assert "sr-drill-data" in embed
    empty = render_contrasting_drill_html(ContrastSet(pairs=[], stats={}))
    assert "No contrasting pairs" in empty


def test_record_and_summary(tmp_path):
    log = tmp_path / "sessions.jsonl"
    logger = SessionLogger(log_path=log)
    record_contrast_result(
        logger,
        {
            "pair_a": "lr-0001",
            "pair_b": "lr-0004",
            "category": "causal",
            "relation": "same_category",
            "shared_schema": None,
            "rating": "got_it",
        },
    )
    record_contrast_result(
        logger,
        {
            "pair_a": "lr-0007",
            "pair_b": "lr-0008",
            "category": "scope",
            "relation": "same_category",
            "shared_schema": None,
            "rating": "partial",
        },
    )
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    contrast_events = [x for x in lines if x.get("type") == "contrast"]
    assert len(contrast_events) == 2
    assert contrast_events[0]["extra"]["rating"] == "got_it"
    assert logger._current is not None and logger._current.mode == "contrasting"

    summary = contrasting_practice_summary(log_path=log)
    assert summary["n"] == 2
    assert summary["got_it"] == 1 and summary["partial"] == 1
    # transfer = (1 + 0.5) / 2 = 0.75
    assert abs(summary["transfer"] - 0.75) < 1e-9


def test_summary_empty_when_no_log(tmp_path):
    summary = contrasting_practice_summary(log_path=tmp_path / "none.jsonl")
    assert summary == {"n": 0, "got_it": 0, "partial": 0, "missed": 0, "transfer": None}


def test_config_accessor_and_validation():
    assert contrasting_pairs_count() >= 1
    assert validate_config() == []
    errors = validate_config({"contrasting_pairs_count": 0})
    assert any("contrasting_pairs_count" in e for e in errors)
