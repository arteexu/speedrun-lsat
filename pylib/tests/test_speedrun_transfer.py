# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for transfer gap evaluation (spec 7d)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import json  # noqa: E402

SEED_ITEM_COUNT = len(
    json.loads(
        (REPO_ROOT / "speedrun/data/seed_deck.json").read_text(encoding="utf-8")
    )["items"]
)

from speedrun.eval.transfer_gap import (  # noqa: E402
    RewordedAttempt,
    generate_reworded_variants,
    load_reworded_attempts,
    record_reworded_attempt,
    transfer_gap_report,
)
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def _full_seed_pass(col):
    """Import the seed deck and grade every card once (Good)."""
    col.set_config("fsrs", True)
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    while True:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)


def test_generate_reworded_variants():
    variants = generate_reworded_variants()
    assert len(variants) == SEED_ITEM_COUNT * 2  # seed deck × 2 variants
    assert (
        variants[0].stimulus != variants[1].stimulus or variants[0].variant_index != 1
    )


def test_authored_paraphrases_are_recognized(tmp_path):
    """Items carrying `paraphrases` feed the transfer test as authored variants."""
    seed = {
        "deck": "t",
        "items": [
            {
                "id": "lr-9001",
                "section": "LR",
                "stem_type": "qt.weaken",
                "schemas": ["flaw.causal.correlation_causation", "qt.weaken"],
                "stimulus": "Original stimulus about coffee and productivity.",
                "question": "Which weakens?",
                "paraphrases": [
                    {"stimulus": "Restated: tea and focus.", "question": "Which weakens?"},
                    {"stimulus": "Restated again: water and energy.", "question": "?"},
                ],
            }
        ],
    }
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(seed), encoding="utf-8")
    variants = generate_reworded_variants(path)
    assert len(variants) == 2
    assert all(v.authored for v in variants)
    assert variants[0].stimulus == "Restated: tea and focus."
    assert variants[0].schema == "flaw.causal.correlation_causation"


def test_transfer_gap_synthetic():
    col = getEmptyCol()
    col.set_config("fsrs", True)
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    while True:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)
    report = transfer_gap_report(col, synthetic_transfer_penalty=0.15)
    assert report.gave_up is False, report.reason
    assert report.recall_point is not None
    assert report.reworded_point is not None
    assert report.gap is not None
    assert report.gap > 0  # recall should exceed transfer with penalty
    col.close()


def test_transfer_gap_abstains_without_reviews():
    col = getEmptyCol()
    import_seed_deck(col)
    report = transfer_gap_report(col)
    assert report.gave_up is True
    col.close()


def test_record_and_load_reworded_attempts(tmp_path):
    store = tmp_path / "reworded.json"
    assert load_reworded_attempts(store) == []  # absent store -> empty
    record_reworded_attempt(
        source_id="lr-1", schema="qt.weaken", correct=True, latency_ms=42_000,
        store_path=store,
    )
    record_reworded_attempt(
        source_id="lr-1", schema="qt.weaken", correct=False, latency_ms=90_000,
        variant_index=1, store_path=store,
    )
    loaded = load_reworded_attempts(store)
    assert len(loaded) == 2
    assert isinstance(loaded[0], RewordedAttempt)
    assert loaded[0].source_id == "lr-1"
    assert loaded[0].correct is True
    assert loaded[1].correct is False


def test_transfer_gap_uses_real_reworded_attempts(tmp_path):
    col = getEmptyCol()
    _full_seed_pass(col)
    # Real graded reworded attempts: only 1 in 5 correct => a large transfer gap
    # computed straight from the recorded data (not the proxy).
    attempts = [
        RewordedAttempt(
            source_id=f"lr-{i}",
            schema="qt.weaken",
            correct=(i % 5 == 0),
            latency_ms=60_000,
        )
        for i in range(30)
    ]
    report = transfer_gap_report(col, reworded_attempts=attempts, attempts_store=None)
    assert report.gave_up is False, report.reason
    assert report.source == "real"
    assert report.n_real_attempts == 30
    assert report.reworded_point is not None
    # Transfer (~20%) well below recall => a positive, real gap.
    assert report.gap is not None and report.gap > 0
    col.close()


def test_transfer_gap_reads_real_attempts_from_store(tmp_path):
    col = getEmptyCol()
    _full_seed_pass(col)
    store = tmp_path / "reworded.json"
    for i in range(20):
        record_reworded_attempt(
            source_id=f"lr-{i}", schema="qt.weaken", correct=(i % 2 == 0),
            latency_ms=55_000, store_path=store,
        )
    report = transfer_gap_report(col, attempts_store=store)
    assert report.gave_up is False, report.reason
    assert report.source == "real"
    assert report.n_real_attempts == 20
    col.close()


def test_transfer_gap_proxy_fallback_when_no_real_attempts(tmp_path):
    col = getEmptyCol()
    _full_seed_pass(col)
    # No real attempts and no synthetic penalty: fall back to the labelled proxy.
    report = transfer_gap_report(col, attempts_store=tmp_path / "absent.json")
    assert report.source == "proxy"
    col.close()


# --- real reworded set (spec 7d): 30 cards x 2 = 60 exam-style items ----------

REWORDED_SET_PATH = REPO_ROOT / "speedrun/data/reworded_set.json"


def test_reworded_set_is_real_60_items_tied_to_seed():
    """The authored reworded set is 30 real seed cards x 2 = 60 items, and every
    item references a real seed card id, its schema, and carries an answer key."""
    data = json.loads(REWORDED_SET_PATH.read_text(encoding="utf-8"))
    items = data["items"]
    assert data["n_source_cards"] == 30
    assert data["variants_per_card"] == 2
    assert len(items) == 60

    seed = json.loads(
        (REPO_ROOT / "speedrun/data/seed_deck.json").read_text(encoding="utf-8")
    )
    by_id = {it["id"]: it for it in seed["items"]}
    source_ids = set()
    for it in items:
        assert it["source_id"] in by_id, it["source_id"]
        src = by_id[it["source_id"]]
        assert it["schema"] == src["schemas"][0]
        assert it["stimulus"].strip() and it["question"].strip()
        assert it["answer"].strip()
        source_ids.add(it["source_id"])
    assert len(source_ids) == 30
    # Each source card contributes exactly two variants.
    assert all(
        sum(1 for it in items if it["source_id"] == sid) == 2 for sid in source_ids
    )


def test_reworded_grader_writes_real_attempts_offline(tmp_path, monkeypatch):
    """The grader solves + judges every reworded item and persists real attempts.

    Driven by a scripted client (no network) so CI is deterministic: the solver
    returns a fixed answer and the judge returns 'yes', so all 60 are graded
    correct and 60 attempts are written to the store the transfer report reads."""
    from speedrun.ai.client import ScriptedLLMClient
    from speedrun.eval.reworded_grader import grade_reworded_set

    monkeypatch.setenv("SPEEDRUN_AI_OFF", "0")  # force ai_enabled() True for the test
    store = tmp_path / "reworded_attempts.json"
    solver = ScriptedLLMClient(["the correct answer"], source="scripted-solver")
    judge = ScriptedLLMClient(["yes"], source="scripted-judge")

    report = grade_reworded_set(client=solver, judge_client=judge, store_path=store)
    assert report.graded is True, report.reason
    assert report.n_items == 60
    assert report.n_correct == 60
    assert report.accuracy == 1.0

    saved = load_reworded_attempts(store)
    assert len(saved) == 60
    assert all(a.correct for a in saved)


def test_reworded_grader_refuses_when_ai_off(tmp_path, monkeypatch):
    """With AI disabled the grader will not fabricate results and leaves the store
    untouched (no synthetic attempts)."""
    from speedrun.eval.reworded_grader import grade_reworded_set

    monkeypatch.setenv("SPEEDRUN_AI_OFF", "1")
    store = tmp_path / "reworded_attempts.json"
    report = grade_reworded_set(store_path=store)
    assert report.graded is False
    assert not store.exists()
