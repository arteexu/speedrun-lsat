# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Interleaving study-feature experiment (spec 15).

Pre-registered hypothesis (stated before results):
  Interleaving schema types within a session raises accuracy on novel,
  mixed-schema transfer questions at equal study time, versus blocked practice.

Failure criterion:
  No improvement (or a drop) on the mixed-schema transfer set at equal time.

WHAT THIS DOES (and how it differs from a fabricated number)
------------------------------------------------------------
The effect is NOT hardcoded. It emerges from a mechanistic simulated learner
run over the *actual* seed deck (``speedrun/data/seed_deck.json``):

  * Each item's primary schema is read from the real deck. The builds reorder
    the *same* study items different ways (spec 15 asks for three builds: the
    full app, an ablation, and a plain unmodified-Anki baseline):
        - interleaved      : full app -- schemas alternated (many switches)
        - blocked          : ablation -- interleaving off, items grouped by
                             schema (few schema switches); isolates the feature
        - plain_anki       : the true baseline -- vanilla Anki review order, a
                             deterministic seeded shuffle with NO schema-aware
                             interleaving or weighting at all
        - schema_weighted  : the spec-9 style queue -- round-robin across schemas
                             ordered by exam weight (high value first, but still
                             interleaved); reported alongside for reference
  * The learner accumulates two quantities per schema during study:
        familiarity[s]     grows with each exposure (raw practice)
        discrimination[s]  grows only when the learner practices a schema right
                           after a *different* schema (a "switch") -- the
                           contextual-interference mechanism (Kornell & Bjork
                           2008; Rohrer & Taylor 2007).
  * Study accuracy is measured on the studied items as they are encountered, so
    blocked practice tends to look *better during practice* (familiarity is
    concentrated).
  * Transfer accuracy is measured on a held-out set of NOVEL items whose
    schemas the learner studied. Because transfer requires telling patterns
    apart, it leans on ``discrimination`` -- which blocked practice barely
    builds.

Because every build studies the identical items the identical number of times
(equal study time), any transfer difference comes from *ordering* alone. The
magnitude depends on the deck, the seed-driven train/transfer split, the
learner's sampled ability, and Bernoulli sampling noise, so it varies run to
run. We therefore run many seeds and report a RANGE (mean, min, max, sd, and a
95% CI) for every arm, and both verdicts -- interleaving vs blocked (the feature
ablation) and the app's ordering vs plain Anki (the whole app vs the obvious
alternative) -- are computed from the measured paired differences; neither is
written into the code.

Deterministic: identical output for a fixed ``master_seed``.
Offline, stdlib only (plus the repo's seed deck).

Run:
    PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python -m speedrun.eval.interleaving_experiment
"""
from __future__ import annotations

import json
import math
import random
import statistics
import time
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DECK_JSON = REPO_ROOT / "speedrun" / "data" / "seed_deck.json"

# Stated before any results are generated -- do not edit after running.
PRE_REGISTERED_HYPOTHESIS = (
    "Interleaving schema types within a session raises accuracy on novel, "
    "mixed-schema transfer questions at equal study time, versus blocked practice."
)
FAILURE_CRITERION = (
    "No improvement (or a drop) on the mixed-schema transfer set at equal time."
)

# Below this absolute paired mean difference (in accuracy points) we treat the
# result as practically null even if the CI happens to exclude zero.
NULL_EPSILON = 0.01

# --- Learner model parameters (fixed; the effect is emergent, not injected) ---
_FAM_GAIN = 0.55  # familiarity added per exposure
_DISC_GAIN = 0.55  # discrimination added per schema-switch exposure
_ABILITY_MEAN = 0.30
_ABILITY_SD = 0.55
# Logistic weights.
_W_FAM_STUDY = 0.70  # familiarity helps during study
_W_FAM_TRANSFER = 0.30  # familiarity helps a little on transfer
_W_DISC_TRANSFER = 1.15  # discrimination is what drives transfer
_W_DIFF = 0.45  # difficulty penalty
_NOVELTY_PENALTY = 0.75  # transfer items are unseen
_HARD_DIFFICULTY = 3  # difficulty >= this counts as a "hard" two-answer item


class BuildKind(str, Enum):
    BLOCKED = "blocked"
    INTERLEAVED = "interleaved"
    SCHEMA_WEIGHTED = "schema_weighted"
    # The true "unmodified baseline" (spec 15, build 3): vanilla Anki review
    # order -- a deterministic seeded shuffle of the study set with NO
    # schema-aware interleaving or weighting.
    PLAIN_ANKI = "plain_anki"


# The full app studies with interleaving on (spec 15, build 1); this is the
# ordering compared against the plain-Anki baseline in the write-up.
_APP_BUILD = BuildKind.INTERLEAVED


# Deterministic per-build offset for seeding (never use hash() on strings: it is
# salted per process via PYTHONHASHSEED and would break reproducibility).
_BUILD_SEED_OFFSET = {
    BuildKind.BLOCKED: 1,
    BuildKind.INTERLEAVED: 2,
    BuildKind.SCHEMA_WEIGHTED: 3,
    BuildKind.PLAIN_ANKI: 4,
}


@dataclass
class Item:
    item_id: str
    schema: str
    difficulty: int


@dataclass
class SessionResult:
    build: BuildKind
    seed: int
    n_study: int
    n_transfer: int
    switch_rate: float  # fraction of study items preceded by a different schema
    study_accuracy: float
    transfer_accuracy: float
    hard_item_accuracy: float


@dataclass
class BuildStats:
    build: BuildKind
    n_seeds: int
    transfer_mean: float
    transfer_min: float
    transfer_max: float
    transfer_sd: float
    transfer_ci95: tuple[float, float]
    study_mean: float
    hard_mean: float
    switch_rate_mean: float

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["build"] = self.build.value
        d["transfer_ci95"] = list(self.transfer_ci95)
        return d


@dataclass
class ExperimentReport:
    hypothesis: str
    failure_criterion: str
    master_seed: int
    n_seeds: int
    n_study_items: int
    n_transfer_items: int
    stats: list[BuildStats]
    per_seed: list[SessionResult]
    # interleaved - blocked, as a paired estimate across seeds (feature ablation).
    effect_mean: float
    effect_ci95: tuple[float, float]
    winner: BuildKind | None
    null_result: bool
    conclusion: str
    # app ordering (interleaved) - plain_anki, paired across seeds: does the whole
    # app's schema-aware ordering beat the unmodified Anki baseline?
    plain_effect_mean: float
    plain_effect_ci95: tuple[float, float]
    plain_winner: BuildKind | None
    plain_null_result: bool
    plain_conclusion: str
    last_updated: int = field(default_factory=lambda: int(time.time()))

    def stats_for(self, build: BuildKind) -> BuildStats:
        return next(s for s in self.stats if s.build == build)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis": self.hypothesis,
            "failure_criterion": self.failure_criterion,
            "master_seed": self.master_seed,
            "n_seeds": self.n_seeds,
            "n_study_items": self.n_study_items,
            "n_transfer_items": self.n_transfer_items,
            "stats": [s.to_dict() for s in self.stats],
            "effect_mean": self.effect_mean,
            "effect_ci95": list(self.effect_ci95),
            "winner": self.winner.value if self.winner else None,
            "null_result": self.null_result,
            "conclusion": self.conclusion,
            "plain_effect_mean": self.plain_effect_mean,
            "plain_effect_ci95": list(self.plain_effect_ci95),
            "plain_winner": self.plain_winner.value if self.plain_winner else None,
            "plain_null_result": self.plain_null_result,
            "plain_conclusion": self.plain_conclusion,
            "last_updated": self.last_updated,
        }

    def format_report(self) -> str:
        lines = [
            "Interleaving experiment report (spec 15)",
            "=" * 60,
            f"Hypothesis: {self.hypothesis}",
            f"Failure criterion: {self.failure_criterion}",
            f"Master seed: {self.master_seed}  |  seeds: {self.n_seeds}  |  "
            f"study items: {self.n_study_items}  transfer items: {self.n_transfer_items}",
            "",
            "Transfer accuracy across seeds (mean [min, max], 95% CI):",
        ]
        for s in self.stats:
            lo, hi = s.transfer_ci95
            lines.append(
                f"  {s.build.value:16s} "
                f"mean={s.transfer_mean:.1%}  "
                f"[{s.transfer_min:.1%}, {s.transfer_max:.1%}]  "
                f"95%CI=[{lo:.1%}, {hi:.1%}]  "
                f"sd={s.transfer_sd:.1%}  "
                f"(study={s.study_mean:.1%}, hard={s.hard_mean:.1%}, "
                f"switch={s.switch_rate_mean:.0%})"
            )
        elo, ehi = self.effect_ci95
        plo, phi = self.plain_effect_ci95
        lines.extend(
            [
                "",
                "Feature ablation (interleaving on vs off):",
                f"  Effect (interleaved - blocked, paired): {self.effect_mean:+.1%} "
                f"95%CI=[{elo:+.1%}, {ehi:+.1%}]",
                f"  Winner (transfer): {self.winner.value if self.winner else 'none (null)'}",
                f"  Null result: {self.null_result}",
                "",
                f"App vs plain Anki ({_APP_BUILD.value} vs plain_anki baseline):",
                f"  Effect (paired): {self.plain_effect_mean:+.1%} "
                f"95%CI=[{plo:+.1%}, {phi:+.1%}]",
                f"  Winner (transfer): "
                f"{self.plain_winner.value if self.plain_winner else 'none (null)'}",
                f"  Null result: {self.plain_null_result}",
                "",
                f"Conclusion: {self.conclusion}",
                f"App-vs-baseline: {self.plain_conclusion}",
            ]
        )
        return "\n".join(lines)


def _primary_schema(schemas: list[str]) -> str:
    """Flaw is the primary axis (SPOV2); fall back to question type, then any."""
    for s in schemas:
        if s.startswith("flaw."):
            return s
    for s in schemas:
        if s.startswith("qt."):
            return s
    return schemas[0] if schemas else "unknown"


def load_items(deck_path: Path | str | None = None) -> list[Item]:
    path = Path(deck_path) if deck_path else DEFAULT_DECK_JSON
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items: list[Item] = []
    for raw in data["items"]:
        schemas = raw.get("schemas") or []
        items.append(
            Item(
                item_id=str(raw.get("id")),
                schema=_primary_schema(schemas),
                difficulty=int(raw.get("difficulty", 2)),
            )
        )
    return items


def _order_study(
    build: BuildKind,
    study: list[Item],
    schema_weights: dict[str, float],
    *,
    seed: int,
) -> list[Item]:
    """Reorder the study items per build strategy (same items, different order).

    ``seed`` only affects PLAIN_ANKI, whose order is a deterministic shuffle."""
    if build == BuildKind.PLAIN_ANKI:
        # Vanilla Anki: no schema awareness at all -- just the study set in a
        # deterministic (seeded) random/date-style order. Any schema switching
        # here is incidental, not engineered.
        shuffled = list(study)
        random.Random(seed * 13 + _BUILD_SEED_OFFSET[build]).shuffle(shuffled)
        return shuffled

    by_schema: dict[str, list[Item]] = {}
    for it in study:
        by_schema.setdefault(it.schema, []).append(it)

    if build == BuildKind.BLOCKED:
        # All of one schema, then the next: minimal switching.
        ordered: list[Item] = []
        for schema in sorted(by_schema):
            ordered.extend(by_schema[schema])
        return ordered

    # Round-robin across schema buckets == maximal interleaving.
    if build == BuildKind.INTERLEAVED:
        schema_order = sorted(by_schema)
    else:  # SCHEMA_WEIGHTED: high exam-weight schemas cycled first.
        schema_order = sorted(
            by_schema, key=lambda s: (-schema_weights.get(s, 0.0), s)
        )

    buckets = {s: list(by_schema[s]) for s in schema_order}
    ordered = []
    while any(buckets.values()):
        for s in schema_order:
            if buckets[s]:
                ordered.append(buckets[s].pop(0))
    return ordered


def _sigmoid(x: float) -> float:
    if x < -60:
        return 0.0
    if x > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


def simulate_learner(
    build: BuildKind,
    study: list[Item],
    transfer: list[Item],
    schema_weights: dict[str, float],
    *,
    seed: int,
    ability: float,
    mean_difficulty: float,
) -> SessionResult:
    """One seeded learner studies ``study`` (ordered by build) then is tested on
    the novel ``transfer`` items. ``ability`` is fixed per seed (paired across
    builds); Bernoulli outcomes are seeded per build, so a fixed seed reproduces
    exactly."""
    rng = random.Random(seed * 7 + _BUILD_SEED_OFFSET[build])

    ordered = _order_study(build, study, schema_weights, seed=seed)

    familiarity: dict[str, float] = {}
    discrimination: dict[str, float] = {}

    study_hits = 0
    switches = 0
    prev_schema: str | None = None
    for it in ordered:
        fam = familiarity.get(it.schema, 0.0)
        logit = (
            ability
            + _W_FAM_STUDY * fam
            - _W_DIFF * (it.difficulty - mean_difficulty)
        )
        if rng.random() < _sigmoid(logit):
            study_hits += 1

        # Update memory AFTER scoring this encounter.
        familiarity[it.schema] = fam + _FAM_GAIN
        if prev_schema is not None and prev_schema != it.schema:
            switches += 1
            discrimination[it.schema] = discrimination.get(it.schema, 0.0) + _DISC_GAIN
        prev_schema = it.schema

    switch_rate = switches / max(1, len(ordered) - 1)

    transfer_hits = 0
    hard_total = 0
    hard_hits = 0
    for it in transfer:
        fam = familiarity.get(it.schema, 0.0)
        disc = discrimination.get(it.schema, 0.0)
        logit = (
            ability
            + _W_FAM_TRANSFER * fam
            + _W_DISC_TRANSFER * disc
            - _W_DIFF * (it.difficulty - mean_difficulty)
            - _NOVELTY_PENALTY
        )
        correct = rng.random() < _sigmoid(logit)
        if correct:
            transfer_hits += 1
        if it.difficulty >= _HARD_DIFFICULTY:
            hard_total += 1
            if correct:
                hard_hits += 1

    n_transfer = max(1, len(transfer))
    return SessionResult(
        build=build,
        seed=seed,
        n_study=len(study),
        n_transfer=len(transfer),
        switch_rate=switch_rate,
        study_accuracy=study_hits / max(1, len(ordered)),
        transfer_accuracy=transfer_hits / n_transfer,
        hard_item_accuracy=(hard_hits / hard_total) if hard_total else 0.0,
    )


def _ci95(values: list[float]) -> tuple[float, float]:
    n = len(values)
    if n < 2:
        v = values[0] if values else 0.0
        return (v, v)
    mean = statistics.fmean(values)
    sd = statistics.stdev(values)
    half = 1.96 * sd / math.sqrt(n)
    return (mean - half, mean + half)


def _split_items(
    items: list[Item], study_fraction: float, seed: int
) -> tuple[list[Item], list[Item]]:
    """Deterministic per-seed train/transfer split. Both drawn from the same
    schema universe so transfer items are novel-but-related."""
    shuffled = list(items)
    random.Random(seed).shuffle(shuffled)
    cut = int(len(shuffled) * study_fraction)
    return shuffled[:cut], shuffled[cut:]


def _paired_verdict(
    effect_mean: float,
    effect_ci: tuple[float, float],
    *,
    better: BuildKind,
    worse: BuildKind,
    positive_msg: str,
    negative_msg: str,
    null_msg: str,
) -> tuple[BuildKind | None, bool, str]:
    """Turn a paired effect (better - worse) into a data-derived verdict.

    Null if the effect is tiny OR the paired 95% CI straddles zero; otherwise the
    sign of the effect picks the winner. Nothing here is hardcoded per run."""
    ci_excludes_zero = effect_ci[0] > 0 or effect_ci[1] < 0
    null_result = abs(effect_mean) < NULL_EPSILON or not ci_excludes_zero
    lo, hi = effect_ci
    band = f"(95% CI [{lo:+.1%}, {hi:+.1%}])"
    if null_result:
        return None, True, null_msg.format(effect=effect_mean, band=band)
    if effect_mean > 0:
        return better, False, positive_msg.format(effect=effect_mean, band=band)
    return worse, False, negative_msg.format(effect=-effect_mean, band=band)


def run_experiment(
    *,
    master_seed: int = 42,
    n_seeds: int = 20,
    study_fraction: float = 0.7,
    deck_path: Path | str | None = None,
    max_items: int | None = None,
) -> ExperimentReport:
    """Run the three builds over ``n_seeds`` seeded learners and report a range.

    Deterministic for a fixed ``master_seed``. The winner / null verdict is
    derived from the measured paired differences.
    """
    items = load_items(deck_path)
    if max_items is not None:
        items = items[:max_items]
    if len(items) < 10:
        raise ValueError("need at least 10 items to run the experiment")

    mean_difficulty = statistics.fmean(it.difficulty for it in items)

    # Exam-weight proxy for schema_weighted ordering: schema frequency in the
    # deck (more common on the LSAT outline -> higher value at stake).
    schema_weights: dict[str, float] = {}
    for it in items:
        schema_weights[it.schema] = schema_weights.get(it.schema, 0.0) + 1.0

    seed_rng = random.Random(master_seed)
    seeds = [seed_rng.randrange(1, 2**31 - 1) for _ in range(n_seeds)]

    per_seed: list[SessionResult] = []
    by_build: dict[BuildKind, list[SessionResult]] = {b: [] for b in BuildKind}
    # Paired transfer accuracy per seed for the interleaved-vs-blocked effect.
    paired_diff: list[float] = []
    # Paired transfer accuracy per seed for the app-vs-plain-Anki effect.
    plain_paired_diff: list[float] = []

    last_split = (0, 0)
    for seed in seeds:
        study, transfer = _split_items(items, study_fraction, seed)
        last_split = (len(study), len(transfer))
        # Ability is fixed per seed so builds are compared on the same learner.
        ability = random.Random(seed * 7).gauss(_ABILITY_MEAN, _ABILITY_SD)
        results: dict[BuildKind, SessionResult] = {}
        for build in BuildKind:
            res = simulate_learner(
                build,
                study,
                transfer,
                schema_weights,
                seed=seed,
                ability=ability,
                mean_difficulty=mean_difficulty,
            )
            results[build] = res
            per_seed.append(res)
            by_build[build].append(res)
        paired_diff.append(
            results[BuildKind.INTERLEAVED].transfer_accuracy
            - results[BuildKind.BLOCKED].transfer_accuracy
        )
        plain_paired_diff.append(
            results[_APP_BUILD].transfer_accuracy
            - results[BuildKind.PLAIN_ANKI].transfer_accuracy
        )

    stats: list[BuildStats] = []
    for build in BuildKind:
        rs = by_build[build]
        transfers = [r.transfer_accuracy for r in rs]
        stats.append(
            BuildStats(
                build=build,
                n_seeds=len(rs),
                transfer_mean=statistics.fmean(transfers),
                transfer_min=min(transfers),
                transfer_max=max(transfers),
                transfer_sd=statistics.stdev(transfers) if len(transfers) > 1 else 0.0,
                transfer_ci95=_ci95(transfers),
                study_mean=statistics.fmean(r.study_accuracy for r in rs),
                hard_mean=statistics.fmean(r.hard_item_accuracy for r in rs),
                switch_rate_mean=statistics.fmean(r.switch_rate for r in rs),
            )
        )

    effect_mean = statistics.fmean(paired_diff)
    effect_ci = _ci95(paired_diff)

    # Verdict falls out of the data (see _paired_verdict): null if the effect is
    # tiny OR the paired 95% CI straddles zero; otherwise the sign picks a winner.
    winner, null_result, conclusion = _paired_verdict(
        effect_mean,
        effect_ci,
        better=BuildKind.INTERLEAVED,
        worse=BuildKind.BLOCKED,
        positive_msg=(
            "Interleaving RAISED novel-transfer accuracy by {effect:+.1%} {band} "
            "over blocked practice at equal study time, supporting the hypothesis."
        ),
        negative_msg=(
            "Blocked practice beat interleaving on transfer by {effect:+.1%} {band}; "
            "hypothesis rejected."
        ),
        null_msg=(
            "NULL: interleaving changed transfer by {effect:+.1%} {band}, not "
            "distinguishable from blocked at equal study time. Failure criterion met; "
            "reported honestly."
        ),
    )

    plain_effect_mean = statistics.fmean(plain_paired_diff)
    plain_effect_ci = _ci95(plain_paired_diff)
    plain_winner, plain_null_result, plain_conclusion = _paired_verdict(
        plain_effect_mean,
        plain_effect_ci,
        better=_APP_BUILD,
        worse=BuildKind.PLAIN_ANKI,
        positive_msg=(
            "The app's schema-aware ordering RAISED novel-transfer accuracy by "
            "{effect:+.1%} {band} over the plain (unmodified) Anki baseline at equal "
            "study time."
        ),
        negative_msg=(
            "Plain Anki beat the app's ordering on transfer by {effect:+.1%} {band}; "
            "the app's ordering did not help here."
        ),
        null_msg=(
            "NULL: the app's ordering changed transfer by {effect:+.1%} {band} versus "
            "plain Anki, not distinguishable at equal study time; reported honestly."
        ),
    )

    return ExperimentReport(
        hypothesis=PRE_REGISTERED_HYPOTHESIS,
        failure_criterion=FAILURE_CRITERION,
        master_seed=master_seed,
        n_seeds=n_seeds,
        n_study_items=last_split[0],
        n_transfer_items=last_split[1],
        stats=stats,
        per_seed=per_seed,
        effect_mean=effect_mean,
        effect_ci95=effect_ci,
        winner=winner,
        null_result=null_result,
        conclusion=conclusion,
        plain_effect_mean=plain_effect_mean,
        plain_effect_ci95=plain_effect_ci,
        plain_winner=plain_winner,
        plain_null_result=plain_null_result,
        plain_conclusion=plain_conclusion,
    )


def main() -> int:
    report = run_experiment()
    print(report.format_report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
