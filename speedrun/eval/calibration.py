# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Memory calibration on a held-out temporal split of FSRS predictions (spec 9
step 1, PRD §10.1 / §17).

When the model says 80% recall, actual recall on *held-out* reviews should be
≈80%. Reports Brier score, log loss, and reliability bins.

Held-out method (deterministic, offline).
-----------------------------------------
Earlier versions labelled *every* schema-tagged review "held-out", which
overstates the guarantee: a review the model has already seen is not a fair test
of it. Instead we take a **deterministic temporal split**:

1. Collect every schema-tagged review paired with the FSRS-predicted
   retrievability for its card and the observed outcome (Again = 0, else = 1).
2. Order the reviews by their revlog id, which is the review's epoch-millisecond
   timestamp — a stable, reproducible ordering with no randomness.
3. Reserve the **earlier** reviews as the observed/"train" slice and evaluate
   calibration only on the **later** ``holdout_fraction`` slice. The train slice
   is never scored, so the reported Brier/log-loss/reliability numbers describe
   how well the model predicts reviews it has effectively not been graded on yet.

The split is purely temporal and seed-free, so a second run over the same
collection produces the same held-out slice and the same numbers (spec §17
re-runnability). FSRS retrievability is Anki's built-in prediction; we do not
refit it here.
"""
from __future__ import annotations

import math
import time
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import Any

MIN_HELD_OUT = 10
N_BINS = 10
# Fraction of the (time-ordered) reviews reserved as the later held-out slice.
HOLDOUT_FRACTION = 0.3


@dataclass
class ReliabilityBin:
    bin_low: float
    bin_high: float
    mean_predicted: float
    mean_actual: float
    n: int


@dataclass
class CalibrationReport:
    n_total: int
    n_held_out: int
    brier: float | None
    log_loss: float | None
    bins: list[ReliabilityBin]
    gave_up: bool
    reason: str
    n_train: int = 0
    holdout_fraction: float = HOLDOUT_FRACTION
    last_updated: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["bins"] = [asdict(b) for b in self.bins]
        return d


def _brier(pairs: list[tuple[float, int]]) -> float:
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def _log_loss(pairs: list[tuple[float, int]]) -> float:
    eps = 1e-15
    total = 0.0
    for p, y in pairs:
        p = max(eps, min(1 - eps, p))
        total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return total / len(pairs)


def _reliability_bins(pairs: list[tuple[float, int]], n_bins: int = N_BINS) -> list[ReliabilityBin]:
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for p, y in pairs:
        idx = min(n_bins - 1, int(p * n_bins))
        buckets[idx].append((p, y))
    bins: list[ReliabilityBin] = []
    for i, bucket in enumerate(buckets):
        if not bucket:
            continue
        mean_p = sum(p for p, _ in bucket) / len(bucket)
        mean_y = sum(y for _, y in bucket) / len(bucket)
        bins.append(
            ReliabilityBin(
                bin_low=i / n_bins,
                bin_high=(i + 1) / n_bins,
                mean_predicted=mean_p,
                mean_actual=mean_y,
                n=len(bucket),
            )
        )
    return bins


def _ordered_pairs(col) -> list[tuple[float, int]]:
    """Schema-tagged reviews as (predicted R, outcome), oldest first.

    Outcome is Again=0, else=1. Rows are ordered by ``revlog.id`` (the review's
    epoch-ms timestamp) so the temporal split downstream is deterministic.
    """
    import time as _time

    from speedrun.scoring.memory import SCHEMA_TAG, _schema_from_tags

    timing = col._backend.sched_timing_today()
    today = timing.days_elapsed
    next_day_at = timing.next_day_at
    now = int(_time.time())

    rows = col.db.all(
        """
        SELECT n.tags, r.ease,
               extract_fsrs_retrievability(
                   c.data,
                   CASE WHEN c.odue != 0 THEN c.odue ELSE c.due END,
                   c.ivl, ?, ?, ?)
        FROM revlog r
        JOIN cards c ON r.cid = c.id
        JOIN notes n ON c.nid = n.id
        WHERE r.ease > 0
        ORDER BY r.id ASC
        """,
        today,
        next_day_at,
        now,
    )
    pairs: list[tuple[float, int]] = []
    for tags, ease, pred in rows:
        if _schema_from_tags(tags, SCHEMA_TAG) is None:
            continue
        if pred is None:
            continue
        outcome = 0 if int(ease) == 1 else 1
        pairs.append((float(pred), outcome))
    return pairs


def _temporal_split(
    pairs: list[tuple[float, int]],
    *,
    min_held_out: int,
    holdout_fraction: float,
) -> tuple[list[tuple[float, int]], list[tuple[float, int]]]:
    """Split time-ordered ``pairs`` into (train, held_out).

    The held-out slice is the later ``holdout_fraction`` of reviews, but never
    smaller than ``min_held_out`` and never so large that no training reviews
    remain (at least one earlier review is always kept). Deterministic: depends
    only on ordering and the two integer thresholds.
    """
    n = len(pairs)
    if n < 2:
        return pairs, []
    n_holdout = max(int(round(n * holdout_fraction)), min_held_out)
    n_holdout = min(n_holdout, n - 1)
    return pairs[: n - n_holdout], pairs[n - n_holdout :]


def calibration_report(
    col,
    *,
    min_held_out: int = MIN_HELD_OUT,
    holdout_fraction: float = HOLDOUT_FRACTION,
) -> CalibrationReport:
    pairs = _ordered_pairs(col)
    n_total = len(pairs)
    train, held_out = _temporal_split(
        pairs, min_held_out=min_held_out, holdout_fraction=holdout_fraction
    )
    n_held_out = len(held_out)
    if n_held_out < min_held_out:
        return CalibrationReport(
            n_total=n_total,
            n_held_out=n_held_out,
            n_train=len(train),
            holdout_fraction=holdout_fraction,
            brier=None,
            log_loss=None,
            bins=[],
            gave_up=True,
            reason=(
                f"Not enough held-out reviews: {n_held_out} < {min_held_out} "
                f"(from {n_total} schema-tagged reviews at a "
                f"{holdout_fraction:.0%} temporal split)."
            ),
        )
    return CalibrationReport(
        n_total=n_total,
        n_held_out=n_held_out,
        n_train=len(train),
        holdout_fraction=holdout_fraction,
        brier=_brier(held_out),
        log_loss=_log_loss(held_out),
        bins=_reliability_bins(held_out),
        gave_up=False,
        reason=(
            f"Calibration on the later {n_held_out} of {n_total} schema-tagged "
            f"reviews (trained on the earlier {len(train)}; "
            f"{holdout_fraction:.0%} temporal held-out split)."
        ),
    )
