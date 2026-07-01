# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for interleaving experiment harness (spec 8)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.eval.interleaving_experiment import (  # noqa: E402
    PRE_REGISTERED_HYPOTHESIS,
    BuildKind,
    run_experiment,
)


def test_hypothesis_is_preregistered():
    assert "Interleaving" in PRE_REGISTERED_HYPOTHESIS
    assert "blocked" in PRE_REGISTERED_HYPOTHESIS.lower()


def test_experiment_runs_three_builds():
    report = run_experiment(n_items=60, seed=7)
    kinds = {b.build for b in report.builds}
    assert kinds == {BuildKind.FULL, BuildKind.ABLATION, BuildKind.PLAIN}
    assert all(0 <= b.transfer_accuracy <= 1 for b in report.builds)
    text = report.format_report()
    assert "Hypothesis" in text
    assert "Conclusion" in text


def test_experiment_reports_honestly():
    report = run_experiment(n_items=200, seed=99)
    assert isinstance(report.null_result, bool)
    assert report.conclusion
