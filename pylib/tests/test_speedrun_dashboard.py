# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the queue client helper and the (Qt-free) dashboard HTML renderer."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.dashboard import (  # noqa: E402
    LAUNCHER_GROUPS,
    LAUNCHER_KEYS,
    _memory_card,
    _performance_card,
    _readiness_card,
    _reliability_chart,
    render_dashboard_html,
    render_readiness_report_html,
    render_study_list_html,
)
from speedrun.scoring.memory import MemoryScore  # noqa: E402
from speedrun.scoring.performance import PerformanceScore  # noqa: E402
from speedrun.scoring.queue import load_schema_weights, ordered_cards  # noqa: E402
from speedrun.scoring.readiness import ReadinessScore  # noqa: E402
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def _reviewed_col(n: int = 80):
    """A collection with FSRS on and ``n`` graded reviews of the seed deck."""
    col = getEmptyCol()
    col.set_config("fsrs", True)
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    answered = 0
    while answered < n:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)
        answered += 1
    return col


def test_load_schema_weights():
    weights = load_schema_weights()
    assert weights["flaw.causal.correlation_causation"] == 0.12
    assert weights["qt.necessary_assumption"] == 0.12
    # all values are non-negative floats
    assert all(isinstance(v, float) and v >= 0 for v in weights.values())


def test_ordered_cards_sorted_by_priority():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    cards = ordered_cards(col, limit=50)
    assert cards, "expected the imported deck to yield cards"
    priorities = [c.priority for c in cards]
    assert priorities == sorted(priorities, reverse=True)
    # every card resolved a schema and a positive weight (all seed schemas exist)
    assert all(c.schema for c in cards)
    assert cards[0].priority > 0
    col.close()


def test_dashboard_html_abstains_without_reviews():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    html = render_dashboard_html(col)
    assert "Memory" in html
    assert "Performance" in html
    assert "Readiness" in html
    assert "sr-dash" in html
    # all three abstain without reviews
    assert html.count("No score") >= 3
    col.close()


def test_dashboard_gate_stays_locked_after_seed_pass():
    # The default evidence gate is strict (250 cards + 80% coverage of every
    # axis). A single pass of the small seed deck must NOT be enough to unlock a
    # score -- that is the whole point of the guardrail.
    col = getEmptyCol()
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    while True:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)
    html = render_dashboard_html(col)
    assert "Evidence gate" in html
    assert "Locked" in html
    # Scores abstain while the gate is locked.
    assert "No score" in html
    col.close()


def test_dashboard_shows_last_updated_on_score_cards():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    html = render_dashboard_html(col)
    # PRD §10: memory, performance, and readiness each render a last-updated line.
    assert html.count("last updated:") >= 3
    col.close()


def test_dashboard_shows_calibration_inline_with_scores():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    html = render_dashboard_html(col)
    # Honesty rule §10/§17: the memory-model calibration summary is on the same
    # screen as the three scores, not only as a separate report.
    assert "Calibration — memory model" in html
    # And the readiness report screen also carries it beside the readiness score.
    ready_html = render_readiness_report_html(col)
    assert "Calibration — memory model" in ready_html
    col.close()


def test_dashboard_shows_deck_coverage_panel():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    html = render_dashboard_html(col)
    # §8.3: overall deck coverage of the taxonomy is surfaced on the dashboard.
    assert "Deck coverage" in html
    assert "of the taxonomy" in html
    assert "you have practiced" in html
    col.close()


def test_performance_card_shows_coverage_and_confidence():
    # §10.2 / gap #4: the performance card mirrors readiness with a coverage %
    # and a confidence indicator.
    from speedrun.scoring.performance import PerformanceScore

    class _Gate:
        concept_coverage = 0.62

    score = PerformanceScore(
        label="overall",
        point=0.70,
        low=0.60,
        high=0.80,
        raw_accuracy=0.72,
        on_budget_rate=0.65,
        mean_latency_ms=40_000,
        n_attempts=150,
        speed_flag=False,
        gave_up=False,
        reason="ok",
    )
    html = _performance_card({"overall": score}, gate=_Gate())
    assert "coverage 62%" in html
    # 62% coverage + 150 attempts => medium confidence badge.
    assert "badge-med" in html
    assert "last updated:" in html


def test_memory_card_shows_exam_coverage_badge_and_reason():
    # Gap #1: the memory card shows EXAM coverage (not cards-reviewed/deck-cards),
    # a "how sure" confidence badge, and the score's main reason.
    score = MemoryScore(
        label="overall",
        point=0.82,
        low=0.74,
        high=0.90,
        n_reviewed=120,
        n_cards=500,
        coverage=0.24,  # cards-reviewed/deck-cards — must NOT be shown as coverage
        gave_up=False,
        reason="Mean FSRS recall over 120 reviewed card(s).",
    )
    html = _memory_card({"overall": score}, exam_coverage=0.83)
    # Exam coverage is surfaced from the readiness/coverage source, not 24%.
    assert "exam covered 83%" in html
    assert "coverage 24%" not in html
    # 83% coverage + 120 reviewed => high confidence badge.
    assert "badge-high" in html
    # The main reason is rendered next to the number.
    assert "Mean FSRS recall" in html
    # The give-up rule stays visible even though a score IS shown.
    assert "Give-up rule:" in html
    assert "last updated:" in html


def test_all_three_cards_render_reason_and_giveup_when_scored():
    # Gap #2 + #3: each card renders its reason text AND its give-up rule even
    # when a number is displayed, so the evidence and the rule are always visible.
    mem = MemoryScore(
        label="overall", point=0.8, low=0.7, high=0.9, n_reviewed=50, n_cards=200,
        coverage=0.25, gave_up=False, reason="MEM_REASON_TOKEN",
    )
    perf = PerformanceScore(
        label="overall", point=0.7, low=0.6, high=0.8, raw_accuracy=0.72,
        on_budget_rate=0.66, mean_latency_ms=40000, n_attempts=150,
        speed_flag=False, gave_up=False, reason="PERF_REASON_TOKEN",
    )
    ready = ReadinessScore(
        point=160.0, low=155.0, high=165.0, coverage=0.7, confidence="medium",
        n_attempts=250, expected_fraction=0.66, best_next_step="qt.necessary_assumption",
        speed_flag=False, gave_up=False, reason="READY_REASON_TOKEN",
    )

    mem_html = _memory_card({"overall": mem}, exam_coverage=0.7)
    perf_html = _performance_card(
        {"overall": perf}, best_next_step="qt.necessary_assumption"
    )
    ready_html = _readiness_card(ready)

    for token, card in (
        ("MEM_REASON_TOKEN", mem_html),
        ("PERF_REASON_TOKEN", perf_html),
        ("READY_REASON_TOKEN", ready_html),
    ):
        assert token in card
        assert "Give-up rule:" in card
    # Best-next-step surfaced beyond the Readiness card (on Performance too).
    assert "Best next:" in perf_html
    assert "Best next:" in ready_html


def test_dashboard_shows_giveup_rule_on_every_score_card():
    # Gap #3: the give-up rule is visible on all three score cards on the
    # dashboard (memory, performance, readiness) even in the abstaining state.
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    html = render_dashboard_html(col)
    assert html.count("Give-up rule:") >= 3
    col.close()


def test_dashboard_shows_transfer_gap_panel():
    # Gap #5: the recall-vs-transfer gap (SPOV1) is surfaced on the main
    # dashboard, not only in the separate menu report.
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    html = render_dashboard_html(col)
    assert "Recall vs transfer gap" in html
    col.close()


def test_reliability_chart_renders_from_bins():
    # Gap #4 (unit): the reliability chart is inline SVG built from calibration
    # bins — no heavy deps — and plots each bin as a point.
    from speedrun.eval.calibration import ReliabilityBin

    bins = [
        ReliabilityBin(bin_low=0.7, bin_high=0.8, mean_predicted=0.75, mean_actual=0.70, n=40),
        ReliabilityBin(bin_low=0.8, bin_high=0.9, mean_predicted=0.85, mean_actual=0.88, n=25),
    ]
    svg = _reliability_chart(bins)
    assert "<svg" in svg and "sr-reliability" in svg
    assert svg.count('class="pt"') == 2
    # Empty bins => no chart (abstains cleanly).
    assert _reliability_chart([]) == ""


def test_scores_screen_shows_reliability_chart():
    # Gap #4 (integration): once calibration has held-out data, the scores screen
    # renders the reliability chart beside the Brier/log-loss text.
    import pytest

    from speedrun.eval.calibration import calibration_report

    col = _reviewed_col()
    if calibration_report(col).gave_up:
        col.close()
        pytest.skip("calibration lacks held-out data in this environment")
    # The dashboard and the readiness report both carry the calibration panel.
    assert "sr-reliability" in render_dashboard_html(col)
    assert "sr-reliability" in render_readiness_report_html(col)
    col.close()


def test_dashboard_html_includes_stylesheet():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    html = render_dashboard_html(col)
    assert "<style>" in html
    assert ".sr-dash" in html
    assert ".sr-card" in html
    assert ".heat-bar" in html
    assert "prefers-color-scheme: dark" in html
    assert 'class="sr-grid"' in html
    col.close()


def test_study_list_html_lists_cards():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    html = render_study_list_html(col, limit=5)
    assert "Schema-weighted queue" in html or "sr-queue-item" in html
    assert "sr:schema" not in html  # tags are stripped to bare schema ids
    assert 'class="sr-schema-id"' not in html
    assert "sr-schema-cell" in html
    assert " · " in html  # friendly axis · name labels
    col.close()


def test_dashboard_html_hides_raw_schema_ids():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    html = render_dashboard_html(col)
    assert 'class="sr-schema-id"' not in html
    assert " · " in html
    col.close()


def test_launcher_keys_match_spec():
    # LAUNCHER_KEYS is the flat, ordered view of LAUNCHER_GROUPS and must stay in
    # sync. Keys must be unique and namespace-safe (no colons/spaces).
    spec_keys = [key for _g, btns in LAUNCHER_GROUPS for (key, _l, _d) in btns]
    assert LAUNCHER_KEYS == spec_keys
    assert len(LAUNCHER_KEYS) == len(set(LAUNCHER_KEYS)), "duplicate launcher keys"
    for key in LAUNCHER_KEYS:
        assert key and ":" not in key and " " not in key
    # The stable, documented keys must all be present.
    required = {
        "study_now",
        "study_all",
        "study_queue",
        "cold_open",
        "two_answer_fork",
        "contrasting_pairs",
        "ai_tutor",
        "ai_settings",
        "export",
        "import_seed",
        "dashboard",
        "scores",
    }
    assert required <= set(LAUNCHER_KEYS)


def test_dashboard_renders_launcher_buttons():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    html = render_dashboard_html(col)
    # The launcher nav and a real <button> per feature are present, keyboard
    # focusable and labelled for accessibility.
    assert 'class="sr-launcher"' in html
    assert 'aria-label="Speedrun feature launcher"' in html
    assert html.count('class="sr-launch-btn"') == len(LAUNCHER_KEYS)
    for key in LAUNCHER_KEYS:
        assert f'data-cmd="speedrun:open:{key}"' in html
    col.close()


def test_dashboard_embed_is_body_only_with_bridge_wiring():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    embed = render_dashboard_html(col, embed=True)
    # Body-only markup for the AnkiWebView/pycmd path: no <html>/<head> wrapper,
    # but the shared stylesheet, launcher, and the pycmd relay script are inlined.
    assert "<!DOCTYPE html>" not in embed
    assert "<html>" not in embed
    assert "<style>" in embed and ".sr-dash" in embed
    assert 'class="sr-launcher"' in embed
    assert "pycmd(b.dataset.cmd)" in embed
    for key in LAUNCHER_KEYS:
        assert f'data-cmd="speedrun:open:{key}"' in embed
    col.close()


def test_launcher_dispatch_covers_every_key():
    # The aqt bridge maps every launcher key to a real, callable handler. Skip
    # cleanly when the Qt layer isn't importable (e.g. the pylib-only test run).
    import importlib

    try:
        speedrun_qt = importlib.import_module("aqt.speedrun")
    except Exception:
        import pytest

        pytest.skip("aqt not importable in this environment")

    class _FakeMw:
        col = None

    dispatch = speedrun_qt._launcher_dispatch(_FakeMw())
    assert set(dispatch) == set(LAUNCHER_KEYS)
    assert all(callable(fn) for fn in dispatch.values())
