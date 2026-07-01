# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for AI module (works with AI_OFF=true)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.ai.baseline import keyword_score, load_gold_set  # noqa: E402
from speedrun.ai.card_checker import PASSING_CUTOFF, check_seed_deck  # noqa: E402
from speedrun.ai.client import StubLLMClient  # noqa: E402
from speedrun.ai.config import ai_enabled  # noqa: E402
from speedrun.ai.reasoning_evaluator import evaluate_explanation  # noqa: E402
from speedrun.eval.leakage_check import leakage_check  # noqa: E402


def test_ai_off_by_default(monkeypatch):
    monkeypatch.delenv("SPEEDRUN_AI_OFF", raising=False)
    monkeypatch.setenv("SPEEDRUN_AI_OFF", "1")
    assert ai_enabled() is False


def test_stub_llm_no_network():
    client = StubLLMClient()
    resp = client.complete("test prompt")
    assert resp.source == "stub"


def test_gold_set_has_50_items():
    gold = load_gold_set()
    assert len(gold) == 50


def test_keyword_baseline():
    gold = load_gold_set()
    score = keyword_score(gold[0]["question"], gold[0]["answer"], gold)
    assert score > 0


def test_card_checker_runs():
    report = check_seed_deck()
    assert report.n_checked == 11
    assert report.cutoff == PASSING_CUTOFF


def test_leakage_check():
    report = leakage_check(threshold=0.9)
    assert isinstance(report.clean, bool)


def test_reasoning_evaluator_stub():
    ev = evaluate_explanation(
        "The correlation does not prove causation because selection bias.",
        expected_schema="flaw.causal.correlation_causation",
        fork_rationale="selection effect alternative explanation",
    )
    assert 0 <= ev.score <= 1
    assert ev.feedback
