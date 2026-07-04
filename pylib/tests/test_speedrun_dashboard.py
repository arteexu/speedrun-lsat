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
    render_dashboard_html,
    render_study_list_html,
)
from speedrun.scoring.queue import load_schema_weights, ordered_cards  # noqa: E402
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


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
