# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Readiness model: projected LSAT score (120-180) with a range.

Method (stated, per the honesty rule):
1. Per-schema performance -> expected fraction correct per scored section,
   weighting schemas by their exam weight (the taxonomy is the source of truth).
2. Section fractions combine (LR ~0.66, RC ~0.34) into an overall expected
   fraction correct.
3. A stated linear map turns that fraction into the 120-180 scale.
4. Uncertainty from the performance intervals propagates into a score range;
   coverage and attempt count drive a confidence label.
5. Give-up rule: no score until enough graded attempts AND enough coverage.

Latency is already baked in: performance uses latency-adjusted (on-budget)
accuracy, so an accurate-but-slow student is projected lower, not flattered.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

from speedrun.scoring.performance import performance_score

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TAXONOMY = REPO_ROOT / "speedrun" / "taxonomy" / "lsat_taxonomy.json"

SCALE_MIN = 120
SCALE_MAX = 180

# Give-up thresholds (PRD defaults). Deliberately strict: a real score needs a
# lot of evidence. Tests may lower these to exercise the computed path.
MIN_ATTEMPTS = 200
MIN_COVERAGE = 0.50


def scaled_from_fraction(fraction: float) -> float:
    """Map expected fraction-correct in [0,1] to the 120-180 scale.

    A rough linear approximation (documented as such); it is a placeholder for a
    real raw->scaled equating table and is reported only with a range and a
    confidence caveat, never as a precise number."""
    fraction = max(0.0, min(1.0, fraction))
    return SCALE_MIN + fraction * (SCALE_MAX - SCALE_MIN)


@dataclass
class ReadinessScore:
    point: float | None
    low: float | None
    high: float | None
    coverage: float
    confidence: str
    n_attempts: int
    expected_fraction: float | None
    best_next_step: str | None
    speed_flag: bool
    gave_up: bool
    reason: str
    last_updated: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_schema_meta(path: Path = DEFAULT_TAXONOMY) -> dict[str, dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    meta = {}
    for s in data["schemas"]:
        section = "RC" if s["id"].startswith("rc.") else "LR"
        meta[s["id"]] = {"weight": float(s.get("exam_weight", 0.0)), "section": section}
    return meta


def _weighted_fraction(
    per_schema, meta, section: str, which: str
) -> tuple[float | None, float, float]:
    """Return (fraction, covered_weight, total_weight) for a section.

    `which` selects the performance field: 'point', 'low', or 'high'."""
    covered_weight = 0.0
    acc = 0.0
    total_weight = sum(m["weight"] for m in meta.values() if m["section"] == section)
    for sid, m in meta.items():
        if m["section"] != section:
            continue
        score = per_schema.get(sid)
        if score is None or score.gave_up:
            continue
        value = getattr(score, which)
        if value is None:
            continue
        acc += m["weight"] * value
        covered_weight += m["weight"]
    if covered_weight == 0.0:
        return None, 0.0, total_weight
    return acc / covered_weight, covered_weight, total_weight


def _overall_fraction(per_schema, meta, which: str) -> tuple[float | None, float]:
    """Section-weighted overall fraction and overall coverage (weight-based)."""
    section_weight = {"LR": 0.66, "RC": 0.34}
    num = 0.0
    denom = 0.0
    cov_num = 0.0
    cov_denom = 0.0
    for section, sw in section_weight.items():
        frac, covered, total = _weighted_fraction(per_schema, meta, section, which)
        cov_denom += sw
        if frac is not None:
            num += sw * frac
            denom += sw
        if total > 0:
            cov_num += sw * (covered / total)
    fraction = (num / denom) if denom > 0 else None
    coverage = (cov_num / cov_denom) if cov_denom > 0 else 0.0
    return fraction, coverage


def _confidence(coverage: float, n_attempts: int) -> str:
    if coverage >= 0.8 and n_attempts >= 400:
        return "high"
    if coverage >= 0.5 and n_attempts >= 100:
        return "medium"
    return "low"


def _best_next_step(per_schema, meta) -> str | None:
    """Weakest high-value schema: maximize weight * (1 - performance)."""
    best = None
    best_val = -1.0
    for sid, m in meta.items():
        score = per_schema.get(sid)
        perf = 0.0 if (score is None or score.gave_up or score.point is None) else score.point
        val = m["weight"] * (1.0 - perf)
        if val > best_val:
            best_val = val
            best = sid
    return best


def readiness_score(
    col,
    *,
    min_attempts: int = MIN_ATTEMPTS,
    min_coverage: float = MIN_COVERAGE,
    taxonomy_path: Path = DEFAULT_TAXONOMY,
    **performance_kwargs: Any,
) -> ReadinessScore:
    perf = performance_score(col, **performance_kwargs)
    per_schema = perf["per_schema"]
    n_attempts = perf["overall"].n_attempts
    meta = _load_schema_meta(taxonomy_path)

    point_frac, coverage = _overall_fraction(per_schema, meta, "point")
    speed_flag = any(s.speed_flag for s in per_schema.values() if not s.gave_up)
    best = _best_next_step(per_schema, meta)

    if n_attempts < min_attempts or coverage < min_coverage or point_frac is None:
        return ReadinessScore(
            point=None,
            low=None,
            high=None,
            coverage=coverage,
            confidence="low",
            n_attempts=n_attempts,
            expected_fraction=point_frac,
            best_next_step=best,
            speed_flag=speed_flag,
            gave_up=True,
            reason=(
                f"No score yet: need >= {min_attempts} graded attempts "
                f"(have {n_attempts}) and >= {min_coverage:.0%} coverage "
                f"(have {coverage:.0%})."
            ),
        )

    low_frac, _ = _overall_fraction(per_schema, meta, "low")
    high_frac, _ = _overall_fraction(per_schema, meta, "high")
    point = scaled_from_fraction(point_frac)
    low = scaled_from_fraction(low_frac if low_frac is not None else point_frac)
    high = scaled_from_fraction(high_frac if high_frac is not None else point_frac)

    return ReadinessScore(
        point=point,
        low=low,
        high=high,
        coverage=coverage,
        confidence=_confidence(coverage, n_attempts),
        n_attempts=n_attempts,
        expected_fraction=point_frac,
        best_next_step=best,
        speed_flag=speed_flag,
        gave_up=False,
        reason="Projected from per-schema performance via a stated linear map.",
    )
