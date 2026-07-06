# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""chosen_trap_type as a first-class attempt field (§8.2 / SPOV2) and the
reasoning-evaluator wired into the two-answer fork explanation step (§14.2)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.ai.client import ScriptedLLMClient, StubLLMClient  # noqa: E402
from speedrun.ai.reasoning_evaluator import (  # noqa: E402
    grade_fork_explanation,
    record_reasoning_result,
    reasoning_weakness_summary,
)
from speedrun.fork_trainer import fork_summary, record_fork_result  # noqa: E402
from speedrun.insights import chosen_trap_profile  # noqa: E402
from speedrun.scoring.performance import Attempt, chosen_trap_counts  # noqa: E402
from speedrun.session_logger import SessionLogger  # noqa: E402


# --------------------------------------------------------------------------- #
# Gap 3: chosen_trap_type
# --------------------------------------------------------------------------- #


def test_attempt_chosen_trap_type_is_optional_and_defaults_none():
    a = Attempt(schema="flaw.causal", correct=True, latency_ms=1000)
    assert a.chosen_trap_type is None
    b = Attempt("flaw.causal", False, 2000, chosen_trap_type="trap.out_of_scope")
    assert b.chosen_trap_type == "trap.out_of_scope"


def test_chosen_trap_counts_only_counts_captured_picks():
    attempts = [
        Attempt("s", True, 1000),  # no pick captured (revlog-style) -> ignored
        Attempt("s", False, 2000, chosen_trap_type="trap.out_of_scope"),
        Attempt("s", False, 3000, chosen_trap_type="trap.out_of_scope"),
        Attempt("s", False, 4000, chosen_trap_type="trap.too_strong"),
    ]
    assert chosen_trap_counts(attempts) == {
        "trap.out_of_scope": 2,
        "trap.too_strong": 1,
    }


def test_fork_records_chosen_trap_only_when_runner_up_picked(tmp_path):
    log = tmp_path / "sessions.jsonl"
    logger = SessionLogger(log_path=log)
    # Fell for the trap: picked the runner-up (fork wrong) -> chosen trap captured.
    record_fork_result(
        logger,
        {
            "item_id": "lr-1",
            "picked": "B",
            "fork_correct": False,
            "trap_pick": "trap.out_of_scope",
            "actual_trap": "trap.too_strong",
            "trap_correct": False,
            "latency_ms": 20000,
            "budget_ms": 84000,
            "over_budget": False,
        },
    )
    # Won the fork: no trap fallen for -> chosen trap is None.
    record_fork_result(
        logger,
        {
            "item_id": "lr-2",
            "picked": "A",
            "fork_correct": True,
            "trap_pick": "trap.too_weak",
            "actual_trap": "trap.too_weak",
            "trap_correct": True,
            "latency_ms": 30000,
            "budget_ms": 84000,
            "over_budget": False,
        },
    )
    import json

    events = [
        json.loads(x)
        for x in log.read_text(encoding="utf-8").splitlines()
        if json.loads(x).get("type") == "fork"
    ]
    assert events[0]["extra"]["chosen_trap_type"] == "trap.too_strong"
    assert events[1]["extra"]["chosen_trap_type"] is None

    # The summary surfaces the habitual chosen trap (distinct from missed_traps).
    s = fork_summary(log_path=log)
    assert s["chosen_traps"][0]["trap"] == "trap.too_strong"
    assert s["chosen_traps"][0]["count"] == 1


def test_chosen_trap_profile_surfaces_habitual_fallen_for_traps(tmp_path):
    log = tmp_path / "sessions.jsonl"
    logger = SessionLogger(log_path=log)
    for actual in ("trap.out_of_scope", "trap.out_of_scope", "trap.opposite"):
        record_fork_result(
            logger,
            {
                "item_id": "lr-x",
                "picked": "B",
                "fork_correct": False,  # fell for the trap
                "trap_pick": "trap.too_weak",
                "actual_trap": actual,
                "trap_correct": False,
                "latency_ms": 20000,
                "budget_ms": 84000,
                "over_budget": False,
            },
        )
    profile = chosen_trap_profile(log_path=log)
    assert profile[0].trap == "trap.out_of_scope"
    assert profile[0].count == 2
    assert profile[0].label  # human label present
    assert any(p.trap == "trap.opposite" for p in profile)


# --------------------------------------------------------------------------- #
# Gap 4: reasoning-evaluator wiring
# --------------------------------------------------------------------------- #


def test_grade_fork_explanation_offline_is_graceful():
    payload = {
        "item_id": "lr-1",
        "student_text": "The runner-up is out of scope; it never addresses the conclusion.",
        "expected_schema": "trap.out_of_scope",
        "fork_rationale": "The runner-up is out of scope because it discusses an unrelated conclusion.",
    }
    graded = grade_fork_explanation(payload, client=StubLLMClient())
    assert 0.0 <= graded["score"] <= 1.0
    assert graded["source"] == "offline"  # AI off -> heuristic, still works
    assert graded["ai_used"] is False
    assert graded["feedback"]
    assert graded["item_id"] == "lr-1"


def test_grade_fork_explanation_uses_ai_when_available():
    payload = {
        "item_id": "lr-1",
        "student_text": "out of scope",
        "expected_schema": "trap.out_of_scope",
        "fork_rationale": "It is out of scope.",
    }
    client = ScriptedLLMClient(
        ['{"score": 0.9, "feedback": "Good — you named the scope trap."}'],
        source="openai:test-model",
    )
    graded = grade_fork_explanation(payload, client=client)
    assert graded["score"] == 0.9
    assert graded["source"] == "openai:test-model"
    assert graded["ai_used"] is True


def test_record_and_summary_surface_recurring_weakness(tmp_path):
    log = tmp_path / "sessions.jsonl"
    logger = SessionLogger(log_path=log)
    for _ in range(3):
        record_reasoning_result(
            logger,
            {
                "item_id": "lr-1",
                "student_text": "correlation does not prove causation",
                "expected_schema": "flaw.causal.correlation_causation",
                "fork_rationale": "The argument confuses correlation with causation.",
            },
            client=StubLLMClient(),
        )
    summary = reasoning_weakness_summary(log_path=log)
    assert summary["n"] == 3
    assert summary["mean_score"] is not None
    top = {w["schema"] for w in summary["recurring_weaknesses"]}
    assert "flaw.causal.correlation_causation" in top


def test_reasoning_summary_empty_without_log(tmp_path):
    s = reasoning_weakness_summary(log_path=tmp_path / "none.jsonl")
    assert s == {"n": 0, "mean_score": None, "recurring_weaknesses": []}
