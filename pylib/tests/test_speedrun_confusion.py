# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for confusion-pair interleaving.

Interleaving helps for *confusable* schemas, so we interleave the pairs the
student actually mixes up (cold-open / fork mislabels), seeded by a curated
prior. Guidance only; never feeds the scores.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.cold_open import record_cold_open_result  # noqa: E402
from speedrun.confusion import (  # noqa: E402
    build_confusion_graph,
    confusion_pairs,
    interleave_sequence,
    prior_pairs,
    render_confusion_report_html,
)
from speedrun.fork_trainer import record_fork_result  # noqa: E402
from speedrun.session_logger import SessionLogger  # noqa: E402
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def test_prior_pairs_include_known_confusables():
    pp = prior_pairs()
    assert ("flaw.conditional.mistaken_reversal", "flaw.conditional.nec_suff_confusion") in pp \
        or ("flaw.conditional.nec_suff_confusion", "flaw.conditional.mistaken_reversal") in pp
    # every prior pair is a 2-tuple of distinct schemas
    assert all(len(p) == 2 and p[0] != p[1] for p in pp)


def test_build_confusion_graph_from_coldopen_and_fork(tmp_path):
    log = tmp_path / "s.jsonl"
    logger = SessionLogger(log_path=log)
    # cold-open: predicted correlation, actually common-cause (a mislabel)
    record_cold_open_result(logger, {
        "item_id": "lr-x", "predicted_schema": "flaw.causal.correlation_causation",
        "actual_schema": "flaw.causal.common_cause", "schema_correct": False,
        "answer_choice": "A", "answer_correct": False,
    })
    # a correct cold-open must NOT create a confusion edge
    record_cold_open_result(logger, {
        "item_id": "lr-y", "predicted_schema": "flaw.causal.post_hoc",
        "actual_schema": "flaw.causal.post_hoc", "schema_correct": True,
        "answer_choice": "A", "answer_correct": True,
    })
    # fork: named too_strong, actually opposite (a trap mislabel)
    record_fork_result(logger, {
        "item_id": "lr-0001", "picked": "A", "fork_correct": True,
        "trap_pick": "trap.too_strong_extreme", "actual_trap": "trap.opposite",
        "trap_correct": False, "latency_ms": 30000, "budget_ms": 84000, "over_budget": False,
    })
    g = build_confusion_graph(log_path=log)
    assert g[("flaw.causal.common_cause", "flaw.causal.correlation_causation")] == 1
    assert g[("trap.opposite", "trap.too_strong_extreme")] == 1
    # the correct cold-open created no edge
    assert all("post_hoc" not in a and "post_hoc" not in b for (a, b) in g)


def test_observed_confusions_outrank_prior_only(tmp_path):
    log = tmp_path / "s.jsonl"
    logger = SessionLogger(log_path=log)
    for _ in range(3):
        record_cold_open_result(logger, {
            "item_id": "lr-x", "predicted_schema": "flaw.scope.part_whole",
            "actual_schema": "flaw.structure.circular", "schema_correct": False,
            "answer_choice": "A", "answer_correct": False,
        })
    pairs = confusion_pairs(log_path=log)
    top = pairs[0]
    assert top.observed == 3
    assert {top.a, top.b} == {"flaw.scope.part_whole", "flaw.structure.circular"}
    # prior-only pairs still present but rank below the observed one
    assert any(p.prior and p.observed == 0 for p in pairs)
    assert pairs == sorted(pairs, key=lambda p: (-p.score, p.a_label, p.b_label))


def test_interleave_alternates_and_is_bounded(tmp_path):
    log = tmp_path / "s.jsonl"
    col = getEmptyCol()
    import_seed_deck(col)
    seq = interleave_sequence(col, limit=8, log_path=log)  # cold-start -> prior clusters
    assert 0 < len(seq) <= 8
    # no card repeats
    ids = [c.card_id for c in seq]
    assert len(ids) == len(set(ids))
    # every interleaved card names the confusion pair it drills
    assert all(c.pair for c in seq)
    # cards are drawn from confusable flaw schemas (or the labelled fallback)
    assert all(c.schema.startswith("flaw.") or "fallback" in c.pair for c in seq)
    col.close()


def test_interleave_deterministic(tmp_path):
    log = tmp_path / "s.jsonl"
    col = getEmptyCol()
    import_seed_deck(col)
    a = interleave_sequence(col, limit=10, log_path=log)
    b = interleave_sequence(col, limit=10, log_path=log)
    assert [c.card_id for c in a] == [c.card_id for c in b]
    col.close()


def test_render_report(tmp_path):
    log = tmp_path / "s.jsonl"
    col = getEmptyCol()
    import_seed_deck(col)
    full = render_confusion_report_html(col, log_path=log)
    assert full.strip().startswith("<!DOCTYPE html>")
    assert "Confusion-pair interleaving" in full
    assert "Interleaved plan" in full
    embed = render_confusion_report_html(col, embed=True, log_path=log)
    assert "<!DOCTYPE html>" not in embed and 'class="sr-dash"' in embed
    col.close()
