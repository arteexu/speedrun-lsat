# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Analytics: mastery map, wrong-answer patterns, latency histogram, readiness trajectory."""
from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

from speedrun.config import latency_budget_ms
from speedrun.scoring.memory import SCHEMA_TAG
from speedrun.scoring.memory import _schema_from_tags
from speedrun.scoring.memory import memory_score
from speedrun.scoring.performance import performance_score
from speedrun.scoring.readiness import readiness_score
from speedrun.scoring.readiness import scaled_from_fraction
from speedrun.timeline import progress_timeline

PKG_ROOT = Path(__file__).resolve().parent
DEFAULT_TAXONOMY = PKG_ROOT / "taxonomy" / "lsat_taxonomy.json"

TRAP_TAG = "sr:trap:"
SECTION_TAG = "sr:section:"

MasteryStatus = str  # untested | learning | solid | weak


@dataclass
class SchemaMastery:
    schema: str
    status: MasteryStatus
    memory: float | None
    performance: float | None
    n_reviewed: int
    n_attempts: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WrongPattern:
    tag: str
    count: int
    pct: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LatencyBucket:
    label: str
    count: int
    pct: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReadinessPoint:
    day: str
    projected: float | None
    low: float | None
    high: float | None
    n_attempts: int
    gave_up: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _classify_schema(
    mem_point: float | None,
    perf_point: float | None,
    n_reviewed: int,
    n_attempts: int,
) -> MasteryStatus:
    if n_reviewed == 0 and n_attempts == 0:
        return "untested"
    if perf_point is not None and perf_point >= 0.75:
        return "solid"
    if perf_point is not None and perf_point < 0.50:
        return "weak"
    if mem_point is not None and mem_point >= 0.70 and (perf_point is None or perf_point < 0.60):
        return "learning"
    if n_attempts > 0 or n_reviewed > 0:
        return "learning"
    return "untested"


def schema_mastery_map(col) -> list[SchemaMastery]:
    mem = memory_score(col)
    perf = performance_score(col)
    schemas = sorted(set(mem["per_schema"]) | set(perf["per_schema"]))
    out: list[SchemaMastery] = []
    for schema in schemas:
        ms = mem["per_schema"].get(schema)
        ps = perf["per_schema"].get(schema)
        mem_p = None if (ms is None or ms.gave_up) else ms.point
        perf_p = None if (ps is None or ps.gave_up) else ps.point
        n_rev = 0 if ms is None else ms.n_reviewed
        n_att = 0 if ps is None else ps.n_attempts
        out.append(
            SchemaMastery(
                schema=schema,
                status=_classify_schema(mem_p, perf_p, n_rev, n_att),
                memory=mem_p,
                performance=perf_p,
                n_reviewed=n_rev,
                n_attempts=n_att,
            )
        )
    return out


def wrong_answer_patterns(col, *, top_n: int = 10) -> list[WrongPattern]:
    """Top trap/flaw tags on Again (ease=1) reviews."""
    rows = col.db.all(
        """
        SELECT n.tags
        FROM revlog r
        JOIN cards c ON r.cid = c.id
        JOIN notes n ON c.nid = n.id
        WHERE r.ease = 1
        """
    )
    counter: Counter[str] = Counter()
    for (tags,) in rows:
        if _schema_from_tags(tags, SCHEMA_TAG) is None:
            continue
        for tok in tags.split():
            if tok.startswith(TRAP_TAG) or (
                tok.startswith(SCHEMA_TAG) and "flaw." in tok
            ):
                counter[tok] += 1
    total = sum(counter.values()) or 1
    patterns = [
        WrongPattern(tag=k, count=v, pct=v / total)
        for k, v in counter.most_common(top_n)
    ]
    return patterns


def _section_from_tags(tags: str) -> str:
    for tok in tags.split():
        if tok.startswith(SECTION_TAG):
            return tok[len(SECTION_TAG) :]
    schema = _schema_from_tags(tags, SCHEMA_TAG)
    if schema and schema.startswith("rc."):
        return "RC"
    return "LR"


def latency_histogram(col, *, section: str | None = None, buckets: int = 5) -> list[LatencyBucket]:
    rows = col.db.all(
        """
        SELECT n.tags, r.time, r.ease
        FROM revlog r
        JOIN cards c ON r.cid = c.id
        JOIN notes n ON c.nid = n.id
        WHERE r.ease > 0
        """
    )
    latencies: list[int] = []
    budget = latency_budget_ms(section)
    for tags, latency, _ease in rows:
        if _schema_from_tags(tags, SCHEMA_TAG) is None:
            continue
        sec = _section_from_tags(tags)
        if section and sec != section:
            continue
        latencies.append(int(latency))

    if not latencies:
        return []

    max_lat = max(max(latencies), budget)
    step = max_lat / buckets
    counts = [0] * buckets
    for lat in latencies:
        idx = min(buckets - 1, int(lat / step) if step else 0)
        counts[idx] += 1
    total = len(latencies)
    out: list[LatencyBucket] = []
    for i, count in enumerate(counts):
        lo = int(i * step / 1000)
        hi = int((i + 1) * step / 1000)
        out.append(LatencyBucket(label=f"{lo}–{hi}s", count=count, pct=count / total))
    return out


def readiness_trajectory(col, *, days: int = 30) -> list[ReadinessPoint]:
    """Cumulative readiness projection over time (honest abstain when insufficient)."""
    rows = col.db.all(
        """
        SELECT n.tags, r.ease, r.time, r.id
        FROM revlog r
        JOIN cards c ON r.cid = c.id
        JOIN notes n ON c.nid = n.id
        WHERE r.ease > 0
        ORDER BY r.id
        """
    )
    cutoff_ms = int((time.time() - days * 86400) * 1000)
    by_day: dict[str, list[tuple[str, int, int, int]]] = {}
    for tags, ease, latency, rid in rows:
        if _schema_from_tags(tags, SCHEMA_TAG) is None:
            continue
        if int(rid) < cutoff_ms:
            continue
        day = time.strftime("%Y-%m-%d", time.localtime(int(rid) / 1000))
        by_day.setdefault(day, []).append((tags, int(ease), int(latency), int(rid)))

    if not by_day:
        return []

    # Use performance model thresholds lowered for trajectory snapshots.
    from speedrun.scoring.performance import Attempt
    from speedrun.scoring.performance import score_from_attempts
    from speedrun.scoring.readiness import _load_schema_meta
    from speedrun.scoring.readiness import _overall_fraction
    from speedrun.scoring.readiness import MIN_ATTEMPTS
    from speedrun.scoring.readiness import MIN_COVERAGE

    meta = _load_schema_meta()
    all_attempts: list[Attempt] = []
    points: list[ReadinessPoint] = []

    for day in sorted(by_day.keys()):
        for tags, ease, latency, _rid in by_day[day]:
            schema = _schema_from_tags(tags, SCHEMA_TAG)
            if schema:
                all_attempts.append(
                    Attempt(schema=schema, correct=ease != 1, latency_ms=latency)
                )
        n = len(all_attempts)
        if n < 5:
            points.append(
                ReadinessPoint(day=day, projected=None, low=None, high=None, n_attempts=n, gave_up=True)
            )
            continue
        by_schema: dict[str, list[Attempt]] = {}
        for a in all_attempts:
            by_schema.setdefault(a.schema, []).append(a)
        per_schema = {
            s: score_from_attempts(g, label=s, min_attempts=2) for s, g in by_schema.items()
        }
        point_frac, coverage = _overall_fraction(per_schema, meta, "point")
        gave_up = n < MIN_ATTEMPTS or coverage < MIN_COVERAGE or point_frac is None
        if gave_up:
            points.append(
                ReadinessPoint(
                    day=day, projected=None, low=None, high=None, n_attempts=n, gave_up=True
                )
            )
        else:
            low_frac, _ = _overall_fraction(per_schema, meta, "low")
            high_frac, _ = _overall_fraction(per_schema, meta, "high")
            points.append(
                ReadinessPoint(
                    day=day,
                    projected=scaled_from_fraction(point_frac),
                    low=scaled_from_fraction(low_frac or point_frac),
                    high=scaled_from_fraction(high_frac or point_frac),
                    n_attempts=n,
                    gave_up=False,
                )
            )
    return points


def load_taxonomy_definitions(path: Path = DEFAULT_TAXONOMY) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {s["id"]: s.get("description", s.get("name", s["id"])) for s in data["schemas"]}


def explain_schema(schema_id: str, path: Path = DEFAULT_TAXONOMY) -> str:
    defs = load_taxonomy_definitions(path)
    return defs.get(schema_id, f"No definition found for {schema_id}.")
