# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Memory calibration on held-out FSRS predictions (spec 9 step 1).

When the model says 80% recall, actual recall on held-out reviews should be
≈80%. Reports Brier score, log loss, and reliability bins.
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


def _held_out_pairs(col) -> list[tuple[float, int]]:
    """Schema-tagged reviews with FSRS predicted R vs outcome (Again=0, else=1)."""
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


def calibration_report(col, *, min_held_out: int = MIN_HELD_OUT) -> CalibrationReport:
    pairs = _held_out_pairs(col)
    n_total = len(pairs)
    if n_total < min_held_out:
        return CalibrationReport(
            n_total=n_total,
            n_held_out=n_total,
            brier=None,
            log_loss=None,
            bins=[],
            gave_up=True,
            reason=f"Not enough held-out reviews: {n_total} < {min_held_out}.",
        )
    return CalibrationReport(
        n_total=n_total,
        n_held_out=n_total,
        brier=_brier(pairs),
        log_loss=_log_loss(pairs),
        bins=_reliability_bins(pairs),
        gave_up=False,
        reason=f"Calibration over {n_total} schema-tagged reviews.",
    )
