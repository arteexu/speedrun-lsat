# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for taxonomy schema label helpers."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.taxonomy.labels import (  # noqa: E402
    normalize_schema_id,
    schema_display_html,
    schema_label,
    schema_short_label,
    schema_tooltip,
)


def test_normalize_schema_id_strips_tag_prefixes():
    assert normalize_schema_id("sr:schema:rc.main_point") == "rc.main_point"
    assert normalize_schema_id("sr:trap:trap.half_right") == "trap.half_right"
    assert normalize_schema_id("sr:qtype:qt.weaken") == "qt.weaken"
    assert (
        normalize_schema_id("flaw.conditional.mistaken_negation")
        == "flaw.conditional.mistaken_negation"
    )


def test_schema_label_uses_taxonomy_name():
    assert schema_label("rc.main_point") == "RC · Main point / primary purpose"
    assert (
        schema_label("flaw.conditional.mistaken_negation") == "Flaw · Mistaken negation"
    )
    assert (
        schema_label("flaw.causal.correlation_causation")
        == "Flaw · Correlation treated as causation"
    )


def test_schema_label_handles_trap_tags():
    assert schema_label("sr:trap:trap.half_right") == "Trap · Half right / half wrong"


def test_schema_short_label_uses_title_case_tail():
    assert schema_short_label("rc.main_point") == "RC · Main Point"
    assert (
        schema_short_label("flaw.conditional.mistaken_negation")
        == "Flaw · Mistaken Negation"
    )
    assert schema_short_label("sr:trap:trap.half_right") == "Trap · Half Right"


def test_schema_label_fallback_for_unknown_id():
    assert schema_label("custom.unknown_schema") == "CUSTOM · Unknown Schema"


def test_schema_tooltip_includes_raw_id():
    tip = schema_tooltip("flaw.conditional.mistaken_negation")
    assert "Mistaken negation" in tip
    assert "flaw.conditional.mistaken_negation" in tip


def test_schema_display_html_hides_id_by_default():
    html = schema_display_html("rc.main_point")
    assert "Main point / primary purpose" in html
    assert 'class="sr-schema-id"' not in html
    assert "rc.main_point" in html  # in title attribute only


def test_schema_display_html_shows_id_when_requested():
    html = schema_display_html("rc.main_point", show_id=True)
    assert "Main point / primary purpose" in html
    assert 'class="sr-schema-id"' in html
    assert "rc.main_point" in html


def test_schema_display_html_compact_omits_subtitle():
    html = schema_display_html("rc.main_point", compact=True)
    assert "RC · Main Point" in html
    assert 'class="sr-schema-id"' not in html
    assert 'title="' in html
    assert "rc.main_point" in html  # in title attribute
