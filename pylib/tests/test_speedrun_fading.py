# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the adaptive mastery-ordered fading engine (SPOV3).

The engine puts each schema on a rung from objective evidence and fades the
worked-example scaffold hardest-step-last, with the two-answer fork as the
terminal scaffold and a timed pressure mode at the top. Rung decisions are
guidance only and must never feed the scores (honesty rule).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.config import fading_config, validate_config  # noqa: E402
from speedrun.fading import (  # noqa: E402
    PARTS,
    RUNG_FORK,
    RUNG_GENERATION,
    RUNG_NOVICE,
    RUNG_RECOGNITION,
    SchemaEvidence,
    build_worked_example,
    fade_plan,
    faded_explanation_html,
    fork_accuracy_by_schema,
    plans_for_collection,
    render_mastery_ladder_html,
    rung_for,
    schema_evidence_from_collection,
)
from speedrun.fork_trainer import record_fork_result  # noqa: E402
from speedrun.session_logger import SessionLogger  # noqa: E402
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402

CFG = fading_config()


# ------------------------------ rung logic ---------------------------------


def test_novice_until_min_attempts_even_with_perfect_accuracy():
    # A lucky small sample must not promote the student.
    ev = SchemaEvidence("flaw.causal.post_hoc", attempts=9, raw_accuracy=1.0)
    assert rung_for(ev, CFG) == RUNG_NOVICE


def test_recognition_at_min_attempts_below_accuracy_gate():
    ev = SchemaEvidence("flaw.causal.post_hoc", attempts=10, raw_accuracy=0.60)
    assert rung_for(ev, CFG) == RUNG_RECOGNITION


def test_generation_at_recognition_gate():
    gate = CFG["recognition_gate"]
    at = SchemaEvidence("flaw.causal.post_hoc", attempts=12, raw_accuracy=gate)
    below = SchemaEvidence("flaw.causal.post_hoc", attempts=12, raw_accuracy=gate - 0.01)
    assert rung_for(at, CFG) == RUNG_GENERATION
    assert rung_for(below, CFG) == RUNG_RECOGNITION


def test_fork_mastery_requires_fork_gate_and_min_attempts():
    ok = SchemaEvidence(
        "flaw.causal.post_hoc", attempts=20, raw_accuracy=0.9,
        fork_attempts=10, fork_accuracy=0.90,
    )
    assert rung_for(ok, CFG) == RUNG_FORK
    # High fork accuracy but too few fork attempts -> not yet fork rung.
    thin = SchemaEvidence(
        "flaw.causal.post_hoc", attempts=20, raw_accuracy=0.9,
        fork_attempts=5, fork_accuracy=1.0,
    )
    assert rung_for(thin, CFG) == RUNG_GENERATION


def test_fork_data_alone_can_reach_top_rung():
    # Practiced only in the fork drill (no revlog attempts).
    ev = SchemaEvidence("flaw.causal.post_hoc", fork_attempts=12, fork_accuracy=0.95)
    assert rung_for(ev, CFG) == RUNG_FORK


# ------------------------------ fade plan ----------------------------------


def test_fork_rationale_is_the_last_scaffold_to_fade():
    """SPOV3: the fork explanation is visible at every rung except the top."""
    for rung, ev in [
        (RUNG_NOVICE, SchemaEvidence("flaw.causal.post_hoc", attempts=0)),
        (RUNG_RECOGNITION, SchemaEvidence("flaw.causal.post_hoc", attempts=10, raw_accuracy=0.5)),
        (RUNG_GENERATION, SchemaEvidence("flaw.causal.post_hoc", attempts=10, raw_accuracy=0.8)),
    ]:
        plan = fade_plan(ev, CFG)
        assert plan.rung == rung
        assert "fork_rationale" in plan.visible_parts
        assert "fork_rationale" not in plan.hidden_parts
    top = fade_plan(
        SchemaEvidence("flaw.causal.post_hoc", fork_attempts=10, fork_accuracy=0.95), CFG
    )
    assert top.rung == RUNG_FORK
    assert "fork_rationale" in top.hidden_parts


def test_more_fades_as_rung_increases():
    novice = fade_plan(SchemaEvidence("flaw.causal.post_hoc", attempts=0), CFG)
    recog = fade_plan(SchemaEvidence("flaw.causal.post_hoc", attempts=10, raw_accuracy=0.5), CFG)
    gen = fade_plan(SchemaEvidence("flaw.causal.post_hoc", attempts=10, raw_accuracy=0.8), CFG)
    fork = fade_plan(SchemaEvidence("flaw.causal.post_hoc", fork_attempts=10, fork_accuracy=0.95), CFG)
    counts = [len(p.hidden_parts) for p in (novice, recog, gen, fork)]
    assert counts == sorted(counts)
    assert counts[0] == 0 and counts[-1] == len(PARTS)


def test_pressure_only_at_top_and_scales_with_budget():
    gen = fade_plan(SchemaEvidence("flaw.causal.post_hoc", attempts=10, raw_accuracy=0.8), CFG)
    assert gen.pressure is None
    lr = fade_plan(SchemaEvidence("flaw.causal.post_hoc", fork_attempts=10, fork_accuracy=0.95), CFG)
    rc = fade_plan(SchemaEvidence("rc.main_point", fork_attempts=10, fork_accuracy=0.95), CFG)
    assert lr.pressure is not None and rc.pressure is not None
    assert lr.response_mode == "pressure"
    # penalty starts at budget + grace
    assert lr.pressure.speed_penalty_start_ms == lr.pressure.budget_ms + CFG["pressure_speed_grace_ms"]
    # RC gets a larger budget than LR (96s vs 84s by default)
    assert rc.pressure.budget_ms >= lr.pressure.budget_ms


def test_next_gate_message_reflects_rung():
    novice = fade_plan(SchemaEvidence("flaw.causal.post_hoc", attempts=3), CFG)
    assert "more attempt" in novice.next_gate
    top = fade_plan(SchemaEvidence("flaw.causal.post_hoc", fork_attempts=10, fork_accuracy=0.95), CFG)
    assert "Top rung" in top.next_gate


# ------------------------------ adapters -----------------------------------


def test_schema_evidence_from_collection_after_reviews():
    col = getEmptyCol()
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    answered = 0
    while answered < 40:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)
        answered += 1

    ev = schema_evidence_from_collection(col)
    assert ev, "should derive evidence for practiced schemas"
    assert any(e.attempts > 0 for e in ev.values())
    # every evidence row yields a valid plan
    for e in ev.values():
        plan = fade_plan(e, CFG)
        assert plan.rung in (RUNG_NOVICE, RUNG_RECOGNITION, RUNG_GENERATION, RUNG_FORK)
    col.close()


def test_fork_accuracy_by_schema_maps_items_to_flaws(tmp_path):
    log = tmp_path / "sessions.jsonl"
    logger = SessionLogger(log_path=log)
    # lr-0001 is a correlation/causation item in the seed deck.
    for correct in (True, True, False):
        record_fork_result(
            logger,
            {
                "item_id": "lr-0001",
                "picked": "A",
                "fork_correct": correct,
                "trap_pick": "trap.too_weak",
                "actual_trap": "trap.too_weak",
                "trap_correct": True,
                "latency_ms": 30000,
                "budget_ms": 84000,
                "over_budget": False,
            },
        )
    by_schema = fork_accuracy_by_schema(log_path=log)
    assert "flaw.causal.correlation_causation" in by_schema
    attempts, acc = by_schema["flaw.causal.correlation_causation"]
    assert attempts == 3
    assert abs(acc - 2 / 3) < 1e-9


# ------------------------------ rendering ----------------------------------


def test_faded_explanation_hides_fork_only_at_top():
    from speedrun.contrasting import _load_taxonomy_meta, load_seed_items

    meta = _load_taxonomy_meta()
    item = next(i for i in load_seed_items() if i["id"] == "lr-0001")

    recog = fade_plan(SchemaEvidence(item["schemas"][0], attempts=10, raw_accuracy=0.5), CFG)
    html_recog = faded_explanation_html(item, recog, meta)
    # fork rationale is shown (not behind a recall/generate prompt) at recognition
    assert "Why the runner-up loses (the two-answer fork).</b>" in html_recog
    assert "Recall: Why the runner-up loses" not in html_recog

    top = fade_plan(SchemaEvidence(item["schemas"][0], fork_attempts=10, fork_accuracy=0.95), CFG)
    html_top = faded_explanation_html(item, top, meta)
    # at the top rung the fork rationale is withheld behind a generate/recall prompt
    assert "Generate: Why the runner-up loses" in html_top or "Recall: Why the runner-up loses" in html_top


def test_render_mastery_ladder_empty_and_populated(tmp_path):
    isolated_log = tmp_path / "sessions.jsonl"  # isolate from the real fork log
    col = getEmptyCol()
    empty = render_mastery_ladder_html(col, log_path=isolated_log)
    assert "No practiced schemas" in empty
    assert empty.strip().startswith("<!DOCTYPE html>")

    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    for _ in range(30):
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)
    full = render_mastery_ladder_html(col, log_path=isolated_log)
    assert "Mastery ladder" in full
    for token in ("faded:", "still shown:", "Next:"):
        assert token in full
    embed = render_mastery_ladder_html(col, embed=True)
    assert "<!DOCTYPE html>" not in embed and 'class="sr-dash"' in embed
    col.close()


def test_plans_sorted_hardest_rung_first():
    col = getEmptyCol()
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    for _ in range(20):
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)
    plans = plans_for_collection(col)
    rungs = [p.rung for p in plans]
    assert rungs == sorted(rungs, reverse=True)
    col.close()


# ------------------------------- config ------------------------------------


def test_config_accessor_and_validation():
    cfg = fading_config()
    assert 0 < cfg["recognition_gate"] < 1
    assert cfg["min_attempts"] >= 1
    assert validate_config() == []
    assert any("fading.min_attempts" in e for e in validate_config({"fading": {"min_attempts": 0}}))
    assert any("fading.fork_gate" in e for e in validate_config({"fading": {"fork_gate": 1.5}}))
