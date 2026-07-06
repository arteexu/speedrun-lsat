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
5. Give-up rule: no score until enough graded attempts AND enough coverage in
   *each* scored section (>=50% of LR and >=50% of RC exam weight, PRD §10/§8.3).
   A deck that skips a whole section (e.g. RC) can never read as "ready", even if
   the other section is fully covered and the blended average clears the line.

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
# Deck-coverage line (PRD §8.3). Independent of how much the student has
# *attempted*: it asks whether the DECK itself even touches enough of each
# scored section. A 10,000-card deck that skips a high-weight section must never
# read "ready", so this is a hard, attempts-independent precondition.
MIN_DECK_COVERAGE = 0.50


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
    # Per-section covered fraction of exam weight (e.g. {"LR": 0.62, "RC": 0.71}).
    # Exposed so the give-up rule is falsifiable and the dashboard can show why a
    # section-skipping deck abstains. Sections with no taxonomy weight are omitted.
    section_coverage: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


from functools import lru_cache


@lru_cache(maxsize=8)
def _deck_section_coverage(
    taxonomy_path: Path | None = None,
    deck_path: Path | None = None,
) -> dict[str, float]:
    """Per-section taxonomy coverage of the DECK itself, via coverage_map (§8.3).

    Returns e.g. ``{"LR": 1.0, "RC": 0.0}`` — the fraction of each scored
    section's schemas the deck contains at least one item for. This is the
    deck-side give-up precondition and is deliberately independent of the
    student's attempts: it reflects what the deck *can* ever measure, so a deck
    that skips a whole section can never read "ready".

    Reads only the static taxonomy/deck JSON (never scans the collection), and is
    cached by path so it costs nothing on repeated renders. Missing/broken files
    degrade to ``{}`` (no deck gate) rather than crashing the score."""
    from speedrun.tools.coverage_map import (
        DEFAULT_DECK,
        DEFAULT_TAXONOMY as COVERAGE_TAXONOMY,
        build_report,
        load_json,
    )

    try:
        taxonomy = load_json(Path(taxonomy_path or COVERAGE_TAXONOMY))
        deck = load_json(Path(deck_path or DEFAULT_DECK))
        report = build_report(taxonomy, deck)
    except Exception:
        return {}
    return {
        section: float(s["count_coverage"])
        for section, s in report["per_section"].items()
    }


@lru_cache(maxsize=8)
def _load_schema_meta(path: Path = DEFAULT_TAXONOMY) -> dict[str, dict[str, Any]]:
    # Cached by path: parsed several times per render (readiness, best-next-step,
    # trajectory) but the taxonomy file is static at runtime.
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


def _section_coverages(per_schema, meta) -> dict[str, float]:
    """Fraction of each section's exam weight the student has *covered* (has a
    non-give-up per-schema score for). Sections with no taxonomy weight are
    omitted so they impose no gate. This is the per-section give-up precondition:
    each returned value must clear ``min_coverage`` or readiness abstains."""
    totals: dict[str, float] = {}
    covered: dict[str, float] = {}
    for sid, m in meta.items():
        sec = m["section"]
        totals[sec] = totals.get(sec, 0.0) + m["weight"]
        score = per_schema.get(sid)
        if score is not None and not score.gave_up:
            covered[sec] = covered.get(sec, 0.0) + m["weight"]
    return {sec: covered.get(sec, 0.0) / tot for sec, tot in totals.items() if tot > 0}


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
    gate: Any = None,
    check_deck_coverage: bool = True,
    min_deck_coverage: float | None = None,
    coverage_taxonomy_path: Path | None = None,
    coverage_deck_path: Path | None = None,
    **performance_kwargs: Any,
) -> ReadinessScore:
    # The evidence gate is the outermost precondition: without enough flashcards
    # and enough distinct flaws/patterns, no readiness number is honest.
    if gate is not None and not gate.open:
        return ReadinessScore(
            point=None,
            low=None,
            high=None,
            coverage=gate.concept_coverage,
            confidence="low",
            n_attempts=0,
            expected_fraction=None,
            best_next_step=None,
            speed_flag=False,
            gave_up=True,
            reason=gate.reason,
        )

    perf = performance_score(col, gate=gate, **performance_kwargs)
    per_schema = perf["per_schema"]
    n_attempts = perf["overall"].n_attempts
    meta = _load_schema_meta(taxonomy_path)

    point_frac, coverage = _overall_fraction(per_schema, meta, "point")
    section_cov = _section_coverages(per_schema, meta)
    # PRD §10/§8.3: coverage must clear the line in *each* scored section, not
    # just on the blended average, so a section-skipping deck can never read
    # "ready".
    under_sections = {s: c for s, c in section_cov.items() if c < min_coverage}
    # PRD §8.3 (additional, deck-side gate): independent of how much the student
    # has attempted, the DECK itself must touch enough of each scored section's
    # taxonomy. This does NOT change the per-section *attempt* coverage above
    # (mirrored in Rust and guarded by the scores-RPC parity test); it is a
    # separate Python-side precondition. A 10,000-card deck that skips a
    # high-weight section abstains here regardless of attempt count.
    deck_line = min_coverage if min_deck_coverage is None else min_deck_coverage
    deck_section_cov = (
        _deck_section_coverage(coverage_taxonomy_path, coverage_deck_path)
        if check_deck_coverage
        else {}
    )
    deck_under = {s: c for s, c in deck_section_cov.items() if c < deck_line}
    speed_flag = any(s.speed_flag for s in per_schema.values() if not s.gave_up)
    best = _best_next_step(per_schema, meta)

    if (
        n_attempts < min_attempts
        or coverage < min_coverage
        or under_sections
        or deck_under
        or point_frac is None
    ):
        parts = ["No score yet:"]
        if n_attempts < min_attempts:
            parts.append(
                f"need >= {min_attempts} graded attempts (have {n_attempts})."
            )
        if deck_under:
            detail = ", ".join(
                f"{s} {c:.0%}" for s, c in sorted(deck_under.items())
            )
            parts.append(
                f"deck coverage below the line — the deck must cover >= "
                f"{deck_line:.0%} of each of LR and RC (short: {detail}); "
                f"abstaining regardless of attempts."
            )
        if under_sections:
            detail = ", ".join(
                f"{s} {c:.0%}" for s, c in sorted(under_sections.items())
            )
            parts.append(
                f"need >= {min_coverage:.0%} schema coverage in each of LR and RC "
                f"(short: {detail})."
            )
        elif coverage < min_coverage or point_frac is None:
            parts.append(
                f"need >= {min_coverage:.0%} coverage (have {coverage:.0%})."
            )
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
            reason=" ".join(parts),
            section_coverage=section_cov,
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
        section_coverage=section_cov,
    )
