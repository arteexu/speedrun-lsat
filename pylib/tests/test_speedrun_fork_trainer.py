# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the two-answer fork trainer (SPOV3 / Insight 6 / Insight 8).

The trainer isolates the final binary decision: winner vs. runner-up, under the
section time budget, followed by naming the runner-up's trap. The reveal always
carries the fork rationale (the never-fading scaffold). All grades are training
signal only and must never feed the scores (honesty rule).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.config import fork_trainer_count, validate_config  # noqa: E402
from speedrun.fork_trainer import (  # noqa: E402
    ForkSet,
    build_fork_set,
    fork_summary,
    load_fork_items,
    record_fork_result,
    render_fork_trainer_html,
)
from speedrun.session_logger import SessionLogger  # noqa: E402
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def test_every_fork_has_exactly_two_finalists_winner_and_runner_up():
    fset = build_fork_set(count=50)
    assert fset.stats["n_items"] > 0
    for it in fset.items:
        assert len(it.choices) == 2, "the fork shows only the two finalists"
        ids = {c.id for c in it.choices}
        assert it.winner_id in ids
        assert it.runner_up_id in ids
        assert it.winner_id != it.runner_up_id
        # the never-fading scaffold (SPOV3) must exist on every drilled item
        assert it.why_runner_up_wrong.strip()
        # the runner-up must carry a nameable trap (Insight 8)
        assert it.runner_trap.startswith("trap.")
        assert it.runner_trap_label
        # timed decision (SPOV4)
        assert it.budget_ms > 0


def test_build_is_deterministic_including_side_shuffle():
    a = build_fork_set(count=12)
    b = build_fork_set(count=12)
    assert [it.id for it in a.items] == [it.id for it in b.items]
    # presentation order of the two finalists is id-stable across builds
    assert [[c.id for c in it.choices] for it in a.items] == [
        [c.id for c in it.choices] for it in b.items
    ]
    # both sides actually occur across the set (not always winner-first)
    firsts = {it.choices[0].id == it.winner_id for it in build_fork_set(count=50).items}
    assert firsts == {True, False}


def test_trap_options_span_full_taxonomy():
    fset = build_fork_set(count=5)
    option_ids = {o["id"] for o in fset.trap_options}
    present = {it.runner_trap for it in fset.items}
    assert option_ids >= present
    assert len(option_ids) > len(present), "picker must include absent traps"
    assert all(o["id"].startswith("trap.") for o in fset.trap_options)


def test_count_is_respected_and_loader_filters_broken_forks(tmp_path):
    assert len(build_fork_set(count=3).items) <= 3
    assert len(build_fork_set(count=0).items) == 0

    seed = tmp_path / "seed.json"
    seed.write_text(
        json.dumps(
            {
                "deck": "t",
                "items": [
                    {  # no two_answer_fork at all
                        "id": "x1",
                        "section": "LR",
                        "schemas": ["flaw.causal.post_hoc"],
                        "choices": [
                            {"id": "A", "text": "a", "correct": True},
                            {"id": "B", "text": "b", "trap": "trap.opposite"},
                        ],
                    },
                    {  # runner_up points at the correct answer -> unusable
                        "id": "x2",
                        "section": "LR",
                        "schemas": ["flaw.causal.post_hoc"],
                        "choices": [
                            {"id": "A", "text": "a", "correct": True},
                            {"id": "B", "text": "b", "trap": "trap.opposite"},
                        ],
                        "two_answer_fork": {"runner_up": "A", "why_runner_up_wrong": "x"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    assert load_fork_items(seed) == []
    assert build_fork_set(count=5, seed_path=seed).items == []


def test_weakness_ordering_is_deterministic_with_collection():
    baseline = build_fork_set(col=None, count=50)

    col = getEmptyCol()
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    for _ in range(300):
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)
    with_col = build_fork_set(col=col, count=50)
    assert with_col.stats["n_items"] == baseline.stats["n_items"]
    assert {it.id for it in with_col.items} == {it.id for it in baseline.items}
    again = build_fork_set(col=col, count=50)
    assert [it.id for it in again.items] == [it.id for it in with_col.items]
    col.close()


def test_render_full_embed_empty_and_scaffold_in_payload():
    fset = build_fork_set(count=4)
    full = render_fork_trainer_html(fset)
    assert full.strip().startswith("<!DOCTYPE html>")
    for token in ("sr-fk-data", "sr-fk-stage", "name the trap", "budget_ms"):
        assert token in full
    # the fork rationale ships with every item (never-fading scaffold, SPOV3)
    payload = json.loads(
        full.split('id="sr-fk-data">', 1)[1].split("</script>", 1)[0]
    )
    assert all(i["why_runner_up_wrong"] for i in payload["items"])
    assert all(len(i["choices"]) == 2 for i in payload["items"])

    embed = render_fork_trainer_html(fset, embed=True)
    assert "<!DOCTYPE html>" not in embed
    assert 'class="sr-dash"' in embed

    empty = render_fork_trainer_html(ForkSet(items=[], trap_options=[], stats={}))
    assert "No fork items" in empty


def test_record_and_summary_roundtrip(tmp_path):
    log = tmp_path / "sessions.jsonl"
    logger = SessionLogger(log_path=log)
    record_fork_result(
        logger,
        {
            "item_id": "lr-0001",
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
    record_fork_result(
        logger,
        {
            "item_id": "lr-0002",
            "picked": "C",
            "fork_correct": False,
            "trap_pick": "trap.out_of_scope",
            "actual_trap": "trap.too_strong",
            "trap_correct": False,
            "latency_ms": 100000,
            "budget_ms": 84000,
            "over_budget": True,
        },
    )
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    events = [x for x in lines if x.get("type") == "fork"]
    assert len(events) == 2
    assert events[0]["extra"]["fork_correct"] is True
    assert events[1]["extra"]["over_budget"] is True
    assert logger._current is not None and logger._current.mode == "fork"

    s = fork_summary(log_path=log)
    assert s["n"] == 2
    assert abs(s["fork_accuracy"] - 0.5) < 1e-9
    assert abs(s["trap_id_accuracy"] - 0.5) < 1e-9
    assert s["avg_latency_ms"] == 65000
    assert abs(s["in_budget_rate"] - 0.5) < 1e-9
    # habitual-trap diagnostic: the mis-named trap is surfaced (Insight 8)
    assert s["missed_traps"][0]["trap"] == "trap.too_strong"
    assert s["missed_traps"][0]["misses"] == 1


def test_summary_empty_when_no_log(tmp_path):
    s = fork_summary(log_path=tmp_path / "none.jsonl")
    assert s["n"] == 0
    assert s["fork_accuracy"] is None
    assert s["missed_traps"] == []


def test_fork_events_do_not_change_performance_score(tmp_path):
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

    logger = SessionLogger(log_path=tmp_path / "sessions.jsonl")
    record_fork_result(
        logger,
        {
            "item_id": "lr-0001",
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

    after = performance_score(col)["overall"]
    assert before.point == after.point
    assert before.n_attempts == after.n_attempts
    col.close()


def test_config_accessor_and_validation():
    assert fork_trainer_count() >= 1
    assert validate_config() == []
    errors = validate_config({"fork_trainer_count": 0})
    assert any("fork_trainer_count" in e for e in errors)
