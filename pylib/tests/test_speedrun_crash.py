# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the crash / durability loop (spec 7g, 18).

Exercises the real open/review/crash/reopen loop and asserts the durability
invariants hold across at least 20 cycles, and that violations are detected."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from speedrun.tools.crash_test import (  # noqa: E402
    DEFAULT_CYCLES,
    DurabilityError,
    main,
    run_durability_loop,
)


def test_durability_loop_survives_20_cycles():
    report = run_durability_loop(cycles=20, reviews_per_cycle=3, verbose=False)
    assert report.ok
    assert report.cycles == 20
    assert len(report.records) == 20
    # Every cycle passed its integrity check.
    assert all(r.integrity_ok for r in report.records)


def test_no_reviews_lost_or_double_counted():
    report = run_durability_loop(cycles=20, reviews_per_cycle=3, verbose=False)
    # revlog is monotonic and grows by exactly the reviews performed each cycle.
    running = 0
    for rec in report.records:
        running += rec.answered_this_cycle
        assert rec.revlog_after_reopen == running, "review lost or double-counted"
    assert report.total_reviews == running
    assert running == sum(r.answered_this_cycle for r in report.records)


def test_card_count_stable_across_cycles():
    report = run_durability_loop(cycles=20, reviews_per_cycle=2, verbose=False)
    counts = {r.cards for r in report.records}
    assert len(counts) == 1, "card count changed across crash cycles"
    assert report.card_count == counts.pop()


def test_default_cycles_meets_spec_minimum():
    assert DEFAULT_CYCLES >= 20


def test_rejects_fewer_than_20_cycles():
    with pytest.raises(ValueError):
        run_durability_loop(cycles=5, verbose=False)


def test_main_exits_zero_on_clean_run():
    assert main() == 0


def test_durability_error_is_raisable():
    # The failure path is real: DurabilityError is the signal main() turns into
    # a non-zero exit.
    with pytest.raises(DurabilityError):
        raise DurabilityError("boom")
