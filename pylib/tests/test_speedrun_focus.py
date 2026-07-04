# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for dedicated / focused study by subject.

Covers the subject search filter, that focused study returns ONLY the chosen
subject's items while preserving the queue/scheduler ordering, the one-click
"weakest areas" auto-selection, the annotated subject catalog, and the picker
render. All offline; no network. The queue backend is a fake so no Rust/DB path
is exercised."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.focus import (  # noqa: E402
    STUDY_ALL_DECK_NAME,
    STUDY_ALL_LIMIT,
    focus_payload,
    focused_cards,
    render_focus_html,
    study_all_spec,
    subject_catalog,
    subject_search,
    weakest_subjects,
)
from speedrun.scoring.queue import DEFAULT_DECK_SEARCH  # noqa: E402


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


@dataclass
class _Card:
    card_id: int
    schema: str
    priority: float
    schema_weight: float = 0.0
    weakness: float = 0.0


class _QueueBackend:
    """Emulates the Rust schema-weighted queue: filters by the schema tags found
    in the search, and returns the cards in the order it was given them (already
    priority-sorted), so callers must not re-order."""

    def __init__(self, cards):
        self._cards = cards
        self.last_search = None

    def build_schema_weighted_queue(self, *, search, limit, **kwargs):
        self.last_search = search
        want = set(re.findall(r"sr:schema:([A-Za-z0-9._]+)", search))
        out = [c for c in self._cards if (not want) or c.schema in want]
        return out[:limit]


class _FakeDB:
    def __init__(self, revlog_rows, note_rows):
        self._revlog = revlog_rows
        self._notes = note_rows

    def all(self, query, *args):
        if "revlog" in query:
            return list(self._revlog)
        if "FROM notes" in query:
            return list(self._notes)
        return []


class _FakeCol:
    def __init__(self, *, cards=None, revlog_rows=None, note_rows=None):
        self._backend = _QueueBackend(cards or [])
        self.db = _FakeDB(revlog_rows or [], note_rows or [])

    def find_cards(self, search):
        return []


def _revlog(schema, n, n_correct, latency_ms=30_000):
    tags = f"sr:schema:{schema}"
    return [(tags, 2 if i < n_correct else 1, latency_ms) for i in range(n)]


# --------------------------------------------------------------------------- #
# Subject search filter
# --------------------------------------------------------------------------- #


def test_subject_search_single():
    s = subject_search(["qt.necessary_assumption"])
    assert s == 'deck:"LSAT Speedrun" (tag:"sr:schema:qt.necessary_assumption")'


def test_subject_search_multi_uses_or():
    s = subject_search(["flaw.a", "flaw.b"])
    assert "OR" in s
    assert 'tag:"sr:schema:flaw.a"' in s and 'tag:"sr:schema:flaw.b"' in s


def test_subject_search_section_scopes():
    s = subject_search(["qt.x"], section="LR")
    assert 'tag:"sr:section:LR"' in s


# --------------------------------------------------------------------------- #
# "Study all (uncapped)" filtered-deck spec
# --------------------------------------------------------------------------- #


def test_study_all_spec_covers_whole_deck_uncapped():
    name, search, limit, order = study_all_spec()
    # Whole-deck search so the filtered ("cram") deck ignores the daily cap.
    assert search == DEFAULT_DECK_SEARCH == 'deck:"LSAT Speedrun"'
    assert limit == STUDY_ALL_LIMIT >= 166  # comfortably above the 166-item deck
    # Distinct from the focused-study decks ("LSAT Focus: ...") and the home deck.
    assert name == STUDY_ALL_DECK_NAME == "LSAT Study All"
    assert not name.startswith("LSAT Focus:")
    assert name != "LSAT Speedrun"
    assert isinstance(order, int)


# --------------------------------------------------------------------------- #
# Focused study returns only the subject, ordering preserved
# --------------------------------------------------------------------------- #


def test_focused_cards_filters_to_subject_only():
    cards = [
        _Card(1, "qt.necessary_assumption", 0.9),
        _Card(2, "flaw.causal.correlation_causation", 0.8),
        _Card(3, "qt.necessary_assumption", 0.7),
        _Card(4, "rc.main_point", 0.6),
    ]
    col = _FakeCol(cards=cards)
    # Pass explicit weaknesses/time_pressure so the queue does not recompute the
    # performance model (keeps the test to the filtering behavior).
    out = focused_cards(
        col,
        ["qt.necessary_assumption"],
        weaknesses={},
        time_pressured=[],
        time_pressure_factor=1.0,
    )
    assert [c.card_id for c in out] == [1, 3]  # only the subject, order preserved
    assert all(c.schema == "qt.necessary_assumption" for c in out)
    assert 'sr:schema:qt.necessary_assumption' in col._backend.last_search


def test_focused_cards_preserves_scheduler_order():
    cards = [
        _Card(1, "flaw.a", 0.9),
        _Card(2, "flaw.a", 0.5),
        _Card(3, "flaw.a", 0.7),
    ]
    col = _FakeCol(cards=cards)
    out = focused_cards(
        col, ["flaw.a"], weaknesses={}, time_pressured=[], time_pressure_factor=1.0
    )
    # The queue's order (as given by the backend) must be preserved verbatim.
    assert [c.card_id for c in out] == [1, 2, 3]


# --------------------------------------------------------------------------- #
# Weakest-areas auto-selection
# --------------------------------------------------------------------------- #


def test_weakest_subjects_picks_lowest_performers():
    rows = _revlog("flaw.weak", 12, 3)  # 25% -> weakest
    rows += _revlog("flaw.mid", 12, 7)  # ~58%
    rows += _revlog("qt.strong", 12, 11)  # ~92%
    col = _FakeCol(revlog_rows=rows)
    weakest = weakest_subjects(col, count=2)
    assert weakest[0] == "flaw.weak"
    assert "qt.strong" not in weakest


# --------------------------------------------------------------------------- #
# Subject catalog (picker data) + render
# --------------------------------------------------------------------------- #


def _catalog_col():
    notes = [
        ("sr:schema:flaw.weak sr:section:LR",),
        ("sr:schema:flaw.weak sr:section:LR",),
        ("sr:schema:qt.strong sr:section:LR",),
    ]
    rows = _revlog("flaw.weak", 12, 3) + _revlog("qt.strong", 12, 11)
    return _FakeCol(revlog_rows=rows, note_rows=notes)


def test_subject_catalog_annotates_and_sorts_weak_first():
    subjects = subject_catalog(_catalog_col())
    by_id = {s.schema: s for s in subjects}
    assert "flaw.weak" in by_id and "qt.strong" in by_id
    # Weakest subject sorts first.
    assert subjects[0].schema == "flaw.weak"
    weak = by_id["flaw.weak"]
    assert weak.item_count == 2
    assert weak.accuracy is not None and weak.status == "weak"
    assert by_id["qt.strong"].kind == "question_type"


def test_focus_payload_and_render():
    col = _catalog_col()
    payload = focus_payload(col)
    assert payload["subjects"], "expected annotated subjects"
    html = render_focus_html(col, embed=True)
    assert "Focus / study by subject" in html
    assert "sr-dash" in html
    assert 'data-cmd="speedrun:focus:flaw.weak"' in html
    assert "speedrun:focus:__weakest__" in html
