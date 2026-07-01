# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Performance model: the memory -> transfer bridge.

Memory (FSRS) answers "can you recall this card?". Performance answers the harder
question "can you get a NEW exam-style item of this schema right, in time?". It is
computed per schema from the student's actual attempts and is deliberately kept
distinct from memory so the paraphrase/transfer test can measure the gap.

Attempts come from Anki's revlog (real data): ease==1 (Again) is a miss, ease>=2
is a hit, and `time` is the response latency. Per SPOV4, latency is co-equal with
correctness: an answer that is correct but over the per-item time budget is
discounted, and an accurate-but-slow student is flagged rather than flattered.
"""
from __future__ import annotations

import time
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import Any

SCHEMA_TAG = "sr:schema:"

from speedrun.config import latency_budget_ms as _latency_budget_ms

# Per-item time budget. LSAT gives ~35 min for ~25 questions ~= 84s/question.
DEFAULT_BUDGET_MS = 90_000

# Give-up threshold: minimum graded attempts before a schema gets a number.
MIN_ATTEMPTS_PER_SCHEMA = 3
MIN_ATTEMPTS_OVERALL = 10

_Z_95 = 1.96


@dataclass
class Attempt:
    schema: str
    correct: bool
    latency_ms: int

    def on_budget_hit(self, budget_ms: int) -> bool:
        """A hit that also came in under the time budget (SPOV4)."""
        return self.correct and self.latency_ms <= budget_ms


@dataclass
class PerformanceScore:
    label: str
    point: float | None  # latency-adjusted P(correct on a novel item)
    low: float | None
    high: float | None
    raw_accuracy: float | None  # ignoring the clock
    on_budget_rate: float | None
    mean_latency_ms: float | None
    n_attempts: int
    speed_flag: bool  # accurate but too slow
    gave_up: bool
    reason: str
    last_updated: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def wilson_interval(successes: int, n: int, z: float = _Z_95) -> tuple[float, float, float]:
    """Wilson score interval for a binomial proportion.

    Returns (center, low, high). The center shrinks small samples toward 0.5, so a
    single lucky hit does not read as 100% -- honest by construction."""
    if n == 0:
        raise ValueError("wilson_interval requires n >= 1")
    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = (z * ((p * (1 - p) / n + z2 / (4 * n * n)) ** 0.5)) / denom
    return center, max(0.0, center - margin), min(1.0, center + margin)


def score_from_attempts(
    attempts: list[Attempt],
    *,
    label: str,
    budget_ms: int = DEFAULT_BUDGET_MS,
    min_attempts: int = MIN_ATTEMPTS_PER_SCHEMA,
) -> PerformanceScore:
    n = len(attempts)
    if n < min_attempts:
        return PerformanceScore(
            label=label,
            point=None,
            low=None,
            high=None,
            raw_accuracy=None,
            on_budget_rate=None,
            mean_latency_ms=None,
            n_attempts=n,
            speed_flag=False,
            gave_up=True,
            reason=f"Not enough data: {n} attempt(s) < required {min_attempts}.",
        )

    hits = sum(1 for a in attempts if a.correct)
    on_budget = sum(
        1
        for a in attempts
        if a.correct and a.latency_ms <= _budget_for_schema(a.schema, budget_ms)
    )
    raw_accuracy = hits / n
    on_budget_rate = on_budget / n
    mean_latency = sum(a.latency_ms for a in attempts) / n
    # The transfer estimate is the latency-adjusted (on-budget) hit rate.
    center, low, high = wilson_interval(on_budget, n)
    # Flag students who are accurate but slow: they'd lose points on the clock.
    speed_flag = (raw_accuracy - on_budget_rate) >= 0.15

    return PerformanceScore(
        label=label,
        point=center,
        low=low,
        high=high,
        raw_accuracy=raw_accuracy,
        on_budget_rate=on_budget_rate,
        mean_latency_ms=mean_latency,
        n_attempts=n,
        speed_flag=speed_flag,
        gave_up=False,
        reason=(
            "Latency-adjusted accuracy on graded attempts."
            + (" Accurate but slow — would lose points on the clock." if speed_flag else "")
        ),
    )


def _schema_from_tags(tags: str, prefix: str = SCHEMA_TAG) -> str | None:
    for tok in tags.split():
        if tok.startswith(prefix):
            return tok[len(prefix) :]
    return None


def _budget_for_schema(schema: str, default_budget_ms: int) -> int:
    if schema.startswith("rc."):
        return _latency_budget_ms("RC")
    if schema.startswith(("flaw.", "qt.", "trap.")):
        return _latency_budget_ms("LR")
    return default_budget_ms


def collection_attempts(col, schema_tag_prefix: str = SCHEMA_TAG) -> list[Attempt]:
    """Derive attempts from the revlog: ease==1 is a miss, ease>=2 a hit; time is
    the latency. Only schema-tagged cards are included."""
    rows = col.db.all(
        """
        SELECT n.tags, r.ease, r.time
        FROM revlog r
        JOIN cards c ON r.cid = c.id
        JOIN notes n ON c.nid = n.id
        WHERE r.ease > 0
        """
    )
    attempts: list[Attempt] = []
    for tags, ease, time_ms in rows:
        schema = _schema_from_tags(tags, schema_tag_prefix)
        if schema is None:
            continue
        attempts.append(
            Attempt(schema=schema, correct=int(ease) != 1, latency_ms=int(time_ms))
        )
    return attempts


def performance_score(
    col,
    *,
    budget_ms: int = DEFAULT_BUDGET_MS,
    min_attempts_per_schema: int = MIN_ATTEMPTS_PER_SCHEMA,
    min_attempts_overall: int = MIN_ATTEMPTS_OVERALL,
    schema_tag_prefix: str = SCHEMA_TAG,
) -> dict[str, Any]:
    attempts = collection_attempts(col, schema_tag_prefix)

    overall = score_from_attempts(
        attempts, label="overall", budget_ms=budget_ms, min_attempts=min_attempts_overall
    )

    by_schema: dict[str, list[Attempt]] = {}
    for a in attempts:
        by_schema.setdefault(a.schema, []).append(a)

    per_schema = {
        schema: score_from_attempts(
            group,
            label=schema,
            budget_ms=_budget_for_schema(schema, budget_ms),
            min_attempts=min_attempts_per_schema,
        )
        for schema, group in sorted(by_schema.items())
    }
    return {"overall": overall, "per_schema": per_schema}


def weakness_map(per_schema: dict[str, PerformanceScore]) -> dict[str, float]:
    """weakness = 1 - transfer estimate, for schemas that have a score. Feeds the
    schema-weighted queue so weak, high-value schemas surface first."""
    out: dict[str, float] = {}
    for schema, score in per_schema.items():
        if not score.gave_up and score.point is not None:
            out[schema] = max(0.0, 1.0 - score.point)
    return out
