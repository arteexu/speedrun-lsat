# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for timeline, pretest, export, coverage gap, session logger."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.coverage_gap import coverage_gap_report  # noqa: E402
from speedrun.export import export_html, render_full_export_html  # noqa: E402
from speedrun.pretest import (  # noqa: E402
    build_pretest_queue,
    simulate_pretest_from_revlog,
)
from speedrun.session_logger import SessionLogger  # noqa: E402
from speedrun.timeline import progress_timeline  # noqa: E402
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def test_timeline_abstains_without_reviews():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    report = progress_timeline(col)
    assert report.gave_up
    col.close()


def test_pretest_queue_builds():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    items = build_pretest_queue(col, block_size=5)
    assert len(items) <= 5
    assert all(i.schema for i in items)
    col.close()


def test_export_html_self_contained():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    html = render_full_export_html(col)
    assert "<!DOCTYPE html>" in html
    assert "LSAT Speedrun" in html
    assert "cdn" not in html.lower()
    col.close()


def test_export_writes_file():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.html"
        export_html(col, path)
        assert path.is_file()
        assert "Memory" in path.read_text(encoding="utf-8")
    col.close()


def test_coverage_gap_report():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    gaps = coverage_gap_report(col, top_n=5)
    assert gaps
    col.close()


def test_session_logger_writes_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "sessions.jsonl"
        logger = SessionLogger(log)
        logger.start(mode="test")
        logger.log_review(card_id=1, schema="flaw.test", ease=3, latency_ms=5000)
        session = logger.end()
        assert session is not None
        assert log.is_file()
        assert "review" in log.read_text(encoding="utf-8")


def test_pretest_simulate_from_revlog():
    col = getEmptyCol()
    result = import_seed_deck(col, backup=False)
    col.decks.select(result.deck_id)
    col.reset()
    for _ in range(3):
        card = col.sched.getCard()
        if not card:
            break
        col.sched.answerCard(card, 3)
    session = simulate_pretest_from_revlog(col, block_size=3)
    assert session.performance is not None
    col.close()
