# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Revlog-based progress timeline for the dashboard."""
from __future__ import annotations

import time
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from speedrun.config import latency_budget_ms
from speedrun.scoring.memory import SCHEMA_TAG, _schema_from_tags

DEFAULT_DAYS = 14


@dataclass
class DayStats:
    day: str  # YYYY-MM-DD
    n_reviews: int
    accuracy: float | None
    on_budget_rate: float | None
    mean_latency_ms: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TimelineReport:
    days: list[DayStats]
    total_reviews: int
    gave_up: bool
    reason: str
    last_updated: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["days"] = [x.to_dict() for x in self.days]
        return d


def progress_timeline(col, *, days: int = DEFAULT_DAYS) -> TimelineReport:
    """Aggregate schema-tagged revlog rows into daily accuracy/latency stats."""
    rows = col.db.all(
        """
        SELECT n.tags, r.ease, r.time, r.id
        FROM revlog r
        JOIN cards c ON r.cid = c.id
        JOIN notes n ON c.nid = n.id
        WHERE r.ease > 0
        """
    )
    cutoff_ms = int((time.time() - days * 86400) * 1000)
    by_day: dict[str, list[tuple[bool, int, bool]]] = {}

    for tags, ease, latency, rid in rows:
        schema = _schema_from_tags(tags, SCHEMA_TAG)
        if schema is None:
            continue
        if int(rid) < cutoff_ms:
            continue
        section = "RC" if schema.startswith("rc.") else "LR"
        budget = latency_budget_ms(section)
        correct = int(ease) != 1
        on_budget = correct and int(latency) <= budget
        day = time.strftime("%Y-%m-%d", time.localtime(int(rid) / 1000))
        by_day.setdefault(day, []).append((correct, int(latency), on_budget))

    if not by_day:
        return TimelineReport(
            days=[],
            total_reviews=0,
            gave_up=True,
            reason="No schema-tagged reviews in the selected window.",
        )

    stats: list[DayStats] = []
    total = 0
    for key in sorted(by_day.keys()):
        bucket = by_day[key]
        hits = sum(1 for c, _l, _ob in bucket if c)
        on_budget = sum(1 for _c, _l, ob in bucket if ob)
        n_rev = len(bucket)
        total += n_rev
        stats.append(
            DayStats(
                day=key,
                n_reviews=n_rev,
                accuracy=(hits / n_rev) if n_rev else None,
                on_budget_rate=(on_budget / n_rev) if n_rev else None,
                mean_latency_ms=(sum(l for _c, l, _ob in bucket) / n_rev) if n_rev else None,
            )
        )

    return TimelineReport(
        days=stats[-days:],
        total_reviews=total,
        gave_up=False,
        reason=f"Timeline over last {days} day(s) from {total} review(s).",
    )
