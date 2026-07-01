# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Interleaving experiment harness (spec 8).

Pre-registered hypothesis (stated before results):
  Interleaving schema types within a session raises accuracy on novel,
  mixed-schema transfer questions at equal study time, versus blocked practice.

Three builds compared on identical synthetic learners:
  1. full    — interleaving ON (schema types mixed within session)
  2. ablation — interleaving OFF (blocked by schema)
  3. plain   — baseline Anki-like random order

This harness simulates with synthetic data to prove the pipeline runs; real
human-subject results would replace the simulator later.
"""
from __future__ import annotations

import random
import time
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from typing import Any

# Stated before any results are generated — do not edit after running.
PRE_REGISTERED_HYPOTHESIS = (
    "Interleaving schema types within a session raises accuracy on novel, "
    "mixed-schema transfer questions at equal study time, versus blocked practice."
)
FAILURE_CRITERION = (
    "No improvement (or a drop) on the mixed-schema transfer set at equal time."
)


class BuildKind(str, Enum):
    FULL = "full"
    ABLATION = "ablation"
    PLAIN = "plain"


@dataclass
class SessionResult:
    build: BuildKind
    n_items: int
    study_accuracy: float
    transfer_accuracy: float
    hard_item_accuracy: float
    seed: int


@dataclass
class ExperimentReport:
    hypothesis: str
    failure_criterion: str
    builds: list[SessionResult]
    winner: BuildKind | None
    effect_size: float | None  # full transfer - ablation transfer
    null_result: bool
    conclusion: str
    last_updated: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["builds"] = [asdict(b) for b in self.builds]
        return d

    def format_report(self) -> str:
        lines = [
            "Interleaving experiment report (spec 8)",
            "=" * 40,
            f"Hypothesis: {self.hypothesis}",
            f"Failure criterion: {self.failure_criterion}",
            "",
        ]
        for b in self.builds:
            lines.append(
                f"  {b.build.value:10s}  study={b.study_accuracy:.0%}  "
                f"transfer={b.transfer_accuracy:.0%}  hard={b.hard_item_accuracy:.0%}  "
                f"(n={b.n_items}, seed={b.seed})"
            )
        lines.extend(
            [
                "",
                f"Effect (full − ablation transfer): "
                f"{self.effect_size:+.1%}" if self.effect_size is not None else "n/a",
                f"Winner (transfer): {self.winner.value if self.winner else 'none'}",
                f"Null result: {self.null_result}",
                "",
                f"Conclusion: {self.conclusion}",
            ]
        )
        return "\n".join(lines)


def _simulate_session(
    build: BuildKind,
    *,
    n_items: int,
    n_schemas: int,
    seed: int,
) -> SessionResult:
    """Synthetic learner: interleaving helps discrimination on mixed transfer."""
    rng = random.Random(seed)
    schemas = list(range(n_schemas))

    if build == BuildKind.FULL:
        interleave_bonus = 0.08
        order_noise = 0.02
    elif build == BuildKind.ABLATION:
        interleave_bonus = 0.0
        order_noise = 0.02
    else:  # PLAIN
        interleave_bonus = -0.02
        order_noise = 0.05

    study_hits = 0
    transfer_hits = 0
    hard_hits = 0
    for i in range(n_items):
        schema = schemas[i % n_schemas] if build == BuildKind.ABLATION else schemas[rng.randint(0, n_schemas - 1)]
        base_p = 0.55 + rng.uniform(-0.05, 0.05)
        study_p = min(0.95, base_p + 0.15)
        transfer_p = min(0.95, base_p + interleave_bonus + rng.uniform(-order_noise, order_noise))
        hard_p = transfer_p * 0.85
        if rng.random() < study_p:
            study_hits += 1
        if rng.random() < transfer_p:
            transfer_hits += 1
        if rng.random() < hard_p:
            hard_hits += 1
        _ = schema  # logged in real experiment; kept for clarity

    return SessionResult(
        build=build,
        n_items=n_items,
        study_accuracy=study_hits / n_items,
        transfer_accuracy=transfer_hits / n_items,
        hard_item_accuracy=hard_hits / n_items,
        seed=seed,
    )


def run_experiment(
    *,
    n_items: int = 120,
    n_schemas: int = 8,
    seed: int = 42,
) -> ExperimentReport:
    builds = [
        _simulate_session(BuildKind.FULL, n_items=n_items, n_schemas=n_schemas, seed=seed),
        _simulate_session(BuildKind.ABLATION, n_items=n_items, n_schemas=n_schemas, seed=seed),
        _simulate_session(BuildKind.PLAIN, n_items=n_items, n_schemas=n_schemas, seed=seed),
    ]
    full = next(b for b in builds if b.build == BuildKind.FULL)
    ablation = next(b for b in builds if b.build == BuildKind.ABLATION)
    effect = full.transfer_accuracy - ablation.transfer_accuracy
    null_result = abs(effect) < 0.02

    if null_result:
        conclusion = (
            "Interleaving made no meaningful difference on synthetic transfer "
            f"(effect {effect:+.1%}). Null results reported honestly."
        )
        winner = None
    elif effect > 0:
        conclusion = f"Full app beat ablation on transfer by {effect:+.1%} (synthetic)."
        winner = BuildKind.FULL
    else:
        conclusion = f"Ablation beat full on transfer by {-effect:+.1%} (synthetic)."
        winner = BuildKind.ABLATION

    return ExperimentReport(
        hypothesis=PRE_REGISTERED_HYPOTHESIS,
        failure_criterion=FAILURE_CRITERION,
        builds=builds,
        winner=winner,
        effect_size=effect,
        null_result=null_result,
        conclusion=conclusion,
    )
