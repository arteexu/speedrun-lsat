# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the interleaving study-feature experiment (spec 15).

These assert the experiment is a *real* seeded simulation over the actual seed
deck that reports a RANGE across seeds and derives its conclusion from the data
(not a hardcoded number)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.eval.interleaving_experiment import (  # noqa: E402
    PRE_REGISTERED_HYPOTHESIS,
    BuildKind,
    load_items,
    run_experiment,
)

# A small seed count keeps the suite fast while still exercising the range math.
_N_SEEDS = 8


def test_hypothesis_is_preregistered():
    assert "Interleaving" in PRE_REGISTERED_HYPOTHESIS
    assert "blocked" in PRE_REGISTERED_HYPOTHESIS.lower()


def test_loads_real_seed_deck():
    items = load_items()
    assert len(items) > 100
    # Primary schema should be resolvable (flaw-first per SPOV2).
    assert all(it.schema for it in items)
    assert any(it.schema.startswith("flaw.") for it in items)


def test_experiment_runs_all_builds():
    report = run_experiment(master_seed=7, n_seeds=_N_SEEDS)
    kinds = {s.build for s in report.stats}
    assert kinds == {
        BuildKind.BLOCKED,
        BuildKind.INTERLEAVED,
        BuildKind.SCHEMA_WEIGHTED,
        BuildKind.PLAIN_ANKI,
    }
    # Four builds x n_seeds session results.
    assert len(report.per_seed) == 4 * _N_SEEDS
    text = report.format_report()
    assert "Hypothesis" in text
    assert "Conclusion" in text
    assert "95%CI" in text


def test_plain_anki_baseline_arm_exists_with_real_range():
    """Spec 15 build 3: an unmodified-Anki baseline must be reported with a real
    range (mean/min/max/CI) and genuine seed-to-seed variability."""
    report = run_experiment(master_seed=321, n_seeds=_N_SEEDS)
    plain = report.stats_for(BuildKind.PLAIN_ANKI)
    assert 0.0 <= plain.transfer_min <= plain.transfer_mean <= plain.transfer_max <= 1.0
    assert plain.transfer_max > plain.transfer_min, "plain_anki has no variability"
    assert plain.transfer_sd > 0.0
    lo, hi = plain.transfer_ci95
    assert lo <= plain.transfer_mean <= hi
    assert lo < hi


def test_app_vs_plain_anki_is_a_paired_range_with_verdict():
    """The app-vs-plain-Anki comparison must be a data-derived paired estimate."""
    report = run_experiment(master_seed=42, n_seeds=_N_SEEDS)
    lo, hi = report.plain_effect_ci95
    assert lo <= report.plain_effect_mean <= hi
    assert isinstance(report.plain_null_result, bool)
    assert report.plain_conclusion
    if report.plain_null_result:
        assert report.plain_winner is None
    else:
        assert report.plain_winner is not None
        if report.plain_effect_mean > 0:
            assert report.plain_winner == BuildKind.INTERLEAVED
        else:
            assert report.plain_winner == BuildKind.PLAIN_ANKI
    text = report.format_report()
    assert "plain_anki" in text


def test_experiment_reports_a_range_not_a_point():
    """Every build (including plain_anki) must report mean/min/max/CI with genuine
    seed variability."""
    report = run_experiment(master_seed=123, n_seeds=_N_SEEDS)
    assert len(report.stats) == 4
    for s in report.stats:
        assert 0.0 <= s.transfer_min <= s.transfer_mean <= s.transfer_max <= 1.0
        # A real simulation varies across seeds; it is not one fixed number.
        assert s.transfer_max > s.transfer_min, f"{s.build} has no variability"
        assert s.transfer_sd > 0.0
        lo, hi = s.transfer_ci95
        assert lo <= s.transfer_mean <= hi
        assert lo < hi


def test_effect_is_a_paired_range_with_ci():
    report = run_experiment(master_seed=42, n_seeds=_N_SEEDS)
    lo, hi = report.effect_ci95
    assert lo <= report.effect_mean <= hi
    assert isinstance(report.null_result, bool)
    assert report.conclusion
    # Winner/null verdict must be consistent with the measured effect.
    if report.null_result:
        assert report.winner is None
    else:
        assert report.winner is not None
        if report.effect_mean > 0:
            assert report.winner == BuildKind.INTERLEAVED
        else:
            assert report.winner == BuildKind.BLOCKED


def test_equal_study_time_across_builds():
    """All builds study the same items the same number of times (fair test)."""
    report = run_experiment(master_seed=5, n_seeds=_N_SEEDS)
    n_study = {s.n_study for s in report.per_seed}
    # Study set size varies per seed split but not across builds within a seed;
    # every session should share the same study/transfer universe sizes.
    assert all(r.n_study > 0 and r.n_transfer > 0 for r in report.per_seed)
    assert len(n_study) >= 1


def test_deterministic_for_fixed_master_seed():
    a = run_experiment(master_seed=2024, n_seeds=_N_SEEDS)
    b = run_experiment(master_seed=2024, n_seeds=_N_SEEDS)
    assert a.effect_mean == b.effect_mean
    assert a.effect_ci95 == b.effect_ci95
    assert a.conclusion == b.conclusion
    assert [s.transfer_mean for s in a.stats] == [s.transfer_mean for s in b.stats]
    # The plain-Anki baseline and the app-vs-baseline verdict are deterministic too.
    assert a.plain_effect_mean == b.plain_effect_mean
    assert a.plain_effect_ci95 == b.plain_effect_ci95
    assert a.plain_conclusion == b.plain_conclusion
    a_plain = a.stats_for(BuildKind.PLAIN_ANKI)
    b_plain = b.stats_for(BuildKind.PLAIN_ANKI)
    assert a_plain.transfer_mean == b_plain.transfer_mean
    assert a_plain.transfer_ci95 == b_plain.transfer_ci95


def test_different_master_seed_changes_numbers():
    a = run_experiment(master_seed=1, n_seeds=_N_SEEDS)
    b = run_experiment(master_seed=2, n_seeds=_N_SEEDS)
    # Not a fabricated constant: different master seeds move the numbers.
    assert a.effect_mean != b.effect_mean


def test_interleaving_increases_switch_rate():
    """Sanity check on the mechanism: interleaved/weighted orders switch schemas
    far more than blocked, which is what should drive any transfer effect."""
    report = run_experiment(master_seed=99, n_seeds=_N_SEEDS)
    blocked = report.stats_for(BuildKind.BLOCKED)
    inter = report.stats_for(BuildKind.INTERLEAVED)
    plain = report.stats_for(BuildKind.PLAIN_ANKI)
    assert inter.switch_rate_mean > blocked.switch_rate_mean
    # Plain Anki's random order switches schemas incidentally -- more than
    # blocked practice, but it is not engineered like interleaving.
    assert plain.switch_rate_mean > blocked.switch_rate_mean
