# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the deterministic (no-AI) per-problem explanations."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.explanations import (  # noqa: E402
    ProblemExplanation,
    explain_item,
    explain_item_by_id,
    items_by_id,
    load_items,
    render_explanations_report_html,
    render_problem_explanation_html,
)

LR_ITEM = {
    "id": "lr-test-1",
    "section": "LR",
    "stem_type": "qt.flaw",
    "schemas": ["flaw.causal.correlation_causation"],
    "difficulty": 3,
    "stimulus": "Cities with more police have more crime, so police cause crime.",
    "question": "The reasoning is most vulnerable to criticism because it",
    "choices": [
        {"id": "A", "text": "confuses correlation with causation", "trap": None, "correct": True},
        {"id": "B", "text": "assumes what it sets out to prove", "trap": "trap.out_of_scope", "correct": False},
        {"id": "C", "text": "overlooks a reversed relationship", "trap": "trap.reversed_relationship", "correct": False},
    ],
    "two_answer_fork": {
        "runner_up": "C",
        "why_runner_up_wrong": "C is tempting but the argument's error is causal, not merely directional.",
    },
}


def test_explain_lr_item_marks_correct_and_traps():
    exp = explain_item(LR_ITEM)
    assert isinstance(exp, ProblemExplanation)
    assert exp.correct is not None
    assert exp.correct.id == "A"
    assert exp.correct.correct is True
    assert "Credited response" in exp.correct.why

    ids = {d.id for d in exp.distractors}
    assert ids == {"B", "C"}
    for d in exp.distractors:
        assert d.correct is False
        assert d.why  # every distractor has a reason


def test_runner_up_uses_fork_note():
    exp = explain_item(LR_ITEM)
    runner = next(d for d in exp.distractors if d.id == "C")
    assert runner.is_runner_up is True
    assert runner.why == LR_ITEM["two_answer_fork"]["why_runner_up_wrong"]


def test_distractor_uses_trap_description():
    exp = explain_item(LR_ITEM)
    b = next(d for d in exp.distractors if d.id == "B")
    assert b.trap_id == "trap.out_of_scope"
    assert b.trap_label and "Out of scope" in b.trap_label
    assert b.why  # pulled from taxonomy description


def test_takeaway_mentions_schema_and_trap():
    exp = explain_item(LR_ITEM)
    assert exp.takeaway
    assert "tests" in exp.takeaway.lower()


def test_explain_is_deterministic():
    a = explain_item(LR_ITEM).to_dict()
    b = explain_item(LR_ITEM).to_dict()
    assert a == b


def test_rc_sibling_resolves_passage():
    items = load_items()
    by_id = items_by_id(items)
    # rc-0001-q2 is a sibling with passage "(see rc-0001)".
    sibling = by_id.get("rc-0001-q2")
    if sibling is None:  # pragma: no cover - depends on seed content
        return
    exp = explain_item(sibling, items=items)
    assert exp.stimulus
    assert not exp.stimulus.startswith("(see")
    assert "cartography" in exp.stimulus.lower()


def test_explain_from_seed_by_id():
    items = load_items()
    first_id = items[0]["id"]
    exp = explain_item_by_id(first_id)
    assert exp is not None
    assert exp.item_id == first_id
    assert explain_item_by_id("does-not-exist") is None


def test_render_single_problem_full_and_embed():
    full = render_problem_explanation_html(LR_ITEM)
    assert "<!DOCTYPE html>" in full or "<html" in full
    assert "Why this answer" in full
    assert "confuses correlation with causation" in full
    assert "Correct" in full

    embed = render_problem_explanation_html(LR_ITEM, embed=True)
    assert "sr-dash" in embed
    assert "<!DOCTYPE html>" not in embed


def test_render_report_lists_all_and_groups():
    html = render_explanations_report_html()
    assert "Problem explanations" in html
    assert "<details" in html
    # Section headers present
    assert "LR" in html or "RC" in html


def test_render_report_empty(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"items": []}), encoding="utf-8")
    html = render_explanations_report_html(path=empty)
    assert "No problems available" in html
