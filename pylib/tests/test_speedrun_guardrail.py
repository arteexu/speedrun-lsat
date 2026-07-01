# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the evidence gate: no score until enough flashcards + flaws + patterns.

Encodes BrainLift SPOV1/SPOV2 and the PRD honesty rule: breadth of concepts is a
precondition for any score, not just review volume.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.config import guardrail_thresholds  # noqa: E402
from speedrun.config import validate_config  # noqa: E402
from speedrun.scoring.guardrail import evidence_gate  # noqa: E402
from speedrun.scoring.memory import memory_score  # noqa: E402
from speedrun.scoring.performance import performance_score  # noqa: E402
from speedrun.scoring.readiness import readiness_score  # noqa: E402
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402

# Modest thresholds the seed deck can satisfy after a full pass.
LENIENT = {
    "min_cards_read": 10,
    "min_concept_coverage": 0.10,
    "min_flaw_coverage": 0.10,
    "min_trap_coverage": 0.10,
    "min_pattern_coverage": 0.10,
}


def _answer_all_due(col, deck_id, ease=3):
    col.decks.select(deck_id)
    col.reset()
    answered = 0
    while True:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, ease)
        answered += 1
    return answered


def test_gate_closed_on_empty_collection():
    col = getEmptyCol()
    gate = evidence_gate(col, thresholds=LENIENT)
    assert gate.open is False
    assert gate.cards_read == 0
    assert "Locked" in gate.reason
    assert {r.key for r in gate.requirements} >= {
        "cards_read",
        "concept_coverage",
        "flaw_coverage",
        "trap_coverage",
        "pattern_coverage",
    }
    col.close()


def test_gate_opens_after_broad_practice():
    col = getEmptyCol()
    result = import_seed_deck(col)
    answered = _answer_all_due(col, result.deck_id)
    assert answered >= 10

    gate = evidence_gate(col, thresholds=LENIENT)
    assert gate.open is True, gate.reason
    assert gate.cards_read >= LENIENT["min_cards_read"]
    assert gate.flaw_coverage >= LENIENT["min_flaw_coverage"]
    assert gate.trap_coverage >= LENIENT["min_trap_coverage"]
    assert all(r.met for r in gate.requirements)
    col.close()


def test_gate_stays_closed_on_narrow_practice():
    # A full-coverage bar the small seed deck can't meet => still locked,
    # even though plenty of cards were read.
    strict = dict(LENIENT, min_flaw_coverage=1.0, min_pattern_coverage=1.0)
    col = getEmptyCol()
    result = import_seed_deck(col)
    _answer_all_due(col, result.deck_id)
    gate = evidence_gate(col, thresholds=strict)
    assert gate.open is False
    missing_keys = {r.key for r in gate.missing()}
    assert "flaw_coverage" in missing_keys or "pattern_coverage" in missing_keys
    col.close()


def test_scores_abstain_when_gate_closed():
    col = getEmptyCol()
    result = import_seed_deck(col)
    _answer_all_due(col, result.deck_id)
    # Force a closed gate regardless of data.
    closed = evidence_gate(col, thresholds=dict(LENIENT, min_cards_read=10_000))
    assert closed.open is False

    mem = memory_score(col, gate=closed)
    perf = performance_score(col, gate=closed)
    ready = readiness_score(col, gate=closed)

    assert mem["overall"].gave_up is True
    assert mem["overall"].point is None
    assert perf["overall"].gave_up is True
    assert ready.gave_up is True
    # The abstention explains exactly what's missing.
    assert "Locked" in mem["overall"].reason
    assert mem["per_schema"] == {}
    col.close()


def test_scores_report_when_gate_open():
    col = getEmptyCol()
    result = import_seed_deck(col)
    _answer_all_due(col, result.deck_id)
    gate = evidence_gate(col, thresholds=LENIENT)
    assert gate.open is True

    perf = performance_score(col, gate=gate)
    assert perf["overall"].gave_up is False, perf["overall"].reason
    assert perf["overall"].point is not None
    col.close()


def test_default_thresholds_present_and_valid():
    th = guardrail_thresholds()
    for key in (
        "min_cards_read",
        "min_concept_coverage",
        "min_flaw_coverage",
        "min_trap_coverage",
        "min_pattern_coverage",
    ):
        assert key in th
    # The default bar is strict: 250 cards + 80% coverage of every axis.
    assert th["min_cards_read"] >= 250
    assert th["min_concept_coverage"] >= 0.80
    assert th["min_flaw_coverage"] >= 0.80
    assert th["min_trap_coverage"] >= 0.80
    assert th["min_pattern_coverage"] >= 0.80
    assert validate_config() == []


def test_config_validation_flags_bad_guardrail():
    errors = validate_config({"guardrail": {"min_cards_read": -1, "min_concept_coverage": 2.0}})
    assert any("min_cards_read" in e for e in errors)
    assert any("min_concept_coverage" in e for e in errors)
