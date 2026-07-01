# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the predict-the-schema cold-open (SPOV1 / SPOV2).

The cold-open shows the stimulus alone and forces the student to name the flaw
before the question/choices appear, then grades schema-ID accuracy SEPARATELY from
answer accuracy. Those self-driven grades are diagnostic signal only and must never
feed the scores (honesty rule).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.cold_open import (  # noqa: E402
    ColdOpenSet,
    build_cold_open_set,
    cold_open_summary,
    record_cold_open_result,
    render_cold_open_html,
)
from speedrun.config import (  # noqa: E402
    cold_open_count,
    validate_config,
)
from speedrun.session_logger import SessionLogger  # noqa: E402
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def test_build_is_deterministic_and_carries_flaws_and_choices():
    a = build_cold_open_set(count=8)
    b = build_cold_open_set(count=8)
    assert a.stats["n_items"] > 0
    assert [it.id for it in a.items] == [it.id for it in b.items]
    for it in a.items:
        assert it.flaw_id.startswith("flaw.")
        assert it.choices, "each item must carry answer choices"
        # exactly one correct choice, matching correct_choice_id
        correct = [c for c in it.choices if c.correct]
        assert len(correct) == 1
        assert correct[0].id == it.correct_choice_id


def test_flaw_options_span_full_taxonomy_not_just_present_items():
    cset = build_cold_open_set(count=3)
    option_ids = {o["id"] for o in cset.flaw_options}
    present = {it.flaw_id for it in cset.items}
    # The picker deliberately offers flaws beyond the current items (discrimination).
    assert option_ids >= present
    assert len(option_ids) > len(present)
    assert all(o["id"].startswith("flaw.") for o in cset.flaw_options)


def test_count_is_respected():
    assert len(build_cold_open_set(count=3).items) <= 3
    assert len(build_cold_open_set(count=0).items) == 0


def test_no_items_when_no_flaw_items(tmp_path):
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
    cset = build_cold_open_set(count=5, seed_path=seed)
    assert cset.items == []


def test_weakness_ordering_is_deterministic_with_collection():
    baseline = build_cold_open_set(col=None, count=50)

    col = getEmptyCol()
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    for _ in range(500):
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)
    with_col = build_cold_open_set(col=col, count=50)
    assert with_col.stats["n_items"] == baseline.stats["n_items"]
    assert {it.category for it in with_col.items} == {it.category for it in baseline.items}
    again = build_cold_open_set(col=col, count=50)
    assert [it.id for it in again.items] == [it.id for it in with_col.items]
    col.close()


def test_render_full_and_embed_and_empty():
    cset = build_cold_open_set(count=4)
    full = render_cold_open_html(cset)
    assert full.strip().startswith("<!DOCTYPE html>")
    for token in ("sr-co-data", "sr-co-stage", "What flaw is at work", "Lock in"):
        assert token in full
    # Stimulus present; question/choices are gated in JS (present only as data, not
    # pre-rendered in the initial predict stage markup).
    assert "sr-co-stage" in full
    embed = render_cold_open_html(cset, embed=True)
    assert "<!DOCTYPE html>" not in embed
    assert 'class="sr-dash"' in embed
    assert "sr-co-data" in embed
    empty = render_cold_open_html(ColdOpenSet(items=[], flaw_options=[], stats={}))
    assert "No cold-open items" in empty


def test_record_grades_schema_and_answer_separately(tmp_path):
    log = tmp_path / "sessions.jsonl"
    logger = SessionLogger(log_path=log)
    record_cold_open_result(
        logger,
        {
            "item_id": "lr-0001",
            "predicted_schema": "flaw.causal.correlation_causation",
            "actual_schema": "flaw.causal.correlation_causation",
            "schema_correct": True,
            "answer_choice": "A",
            "answer_correct": True,
        },
    )
    record_cold_open_result(
        logger,
        {
            "item_id": "lr-0002",
            "predicted_schema": "flaw.scope.equivocation",
            "actual_schema": "flaw.conditional.mistaken_reversal",
            "schema_correct": False,
            "answer_choice": "B",
            "answer_correct": True,
        },
    )
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    events = [x for x in lines if x.get("type") == "cold_open"]
    assert len(events) == 2
    assert events[0]["extra"]["schema_correct"] is True
    assert events[1]["extra"]["schema_correct"] is False
    assert events[1]["extra"]["answer_correct"] is True
    assert logger._current is not None and logger._current.mode == "cold_open"

    summary = cold_open_summary(log_path=log)
    assert summary["n"] == 2
    # schema: 1/2 = 0.5, answer: 2/2 = 1.0, gap = +0.5
    assert abs(summary["schema_accuracy"] - 0.5) < 1e-9
    assert abs(summary["answer_accuracy"] - 1.0) < 1e-9
    assert abs(summary["transfer_gap"] - 0.5) < 1e-9


def test_summary_empty_when_no_log(tmp_path):
    summary = cold_open_summary(log_path=tmp_path / "none.jsonl")
    assert summary == {
        "n": 0,
        "schema_accuracy": None,
        "answer_accuracy": None,
        "transfer_gap": None,
    }


def test_cold_open_events_do_not_change_performance_score(tmp_path):
    from speedrun.scoring.performance import performance_score

    col = getEmptyCol()
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    for _ in range(200):
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)

    before = performance_score(col)["overall"]

    log = tmp_path / "sessions.jsonl"
    logger = SessionLogger(log_path=log)
    record_cold_open_result(
        logger,
        {
            "item_id": "lr-0001",
            "predicted_schema": "flaw.causal.correlation_causation",
            "actual_schema": "flaw.causal.correlation_causation",
            "schema_correct": True,
            "answer_choice": "A",
            "answer_correct": True,
        },
    )

    after = performance_score(col)["overall"]
    assert before.point == after.point
    assert before.n_attempts == after.n_attempts
    col.close()


def test_config_accessor_and_validation():
    assert cold_open_count() >= 1
    assert validate_config() == []
    errors = validate_config({"cold_open_count": 0})
    assert any("cold_open_count" in e for e in errors)
