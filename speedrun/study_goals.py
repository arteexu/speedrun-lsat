# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Daily study goal progress and review streak from the revlog."""
from __future__ import annotations

import time
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from speedrun.config import daily_study_goal
from speedrun.config import daily_study_goal_minutes
from speedrun.scoring.memory import SCHEMA_TAG
from speedrun.scoring.memory import _schema_from_tags


@dataclass
class DailyProgress:
    day: str
    cards_reviewed: int
    minutes_studied: float
    goal_cards: int
    goal_minutes: int | None
    cards_pct: float
    minutes_pct: float | None
    goal_met: bool
    streak_days: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StudyGoalReport:
    today: DailyProgress
    streak_days: int
    last_7_days: list[DailyProgress] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["today"] = self.today.to_dict()
        d["last_7_days"] = [x.to_dict() for x in self.last_7_days]
        return d


def _day_key(ts_ms: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts_ms / 1000))


def _review_days(col) -> dict[str, tuple[int, int]]:
    """Map YYYY-MM-DD -> (card_count, total_latency_ms) for schema-tagged reviews."""
    rows = col.db.all(
        """
        SELECT n.tags, r.time, r.id
        FROM revlog r
        JOIN cards c ON r.cid = c.id
        JOIN notes n ON c.nid = n.id
        WHERE r.ease > 0
        """
    )
    by_day: dict[str, list[int]] = {}
    for tags, latency, rid in rows:
        if _schema_from_tags(tags, SCHEMA_TAG) is None:
            continue
        day = _day_key(int(rid))
        by_day.setdefault(day, []).append(int(latency))
    return {d: (len(lats), sum(lats)) for d, lats in by_day.items()}


def _compute_streak(days_with_reviews: set[str], *, today: str) -> int:
    """Consecutive calendar days ending today (or yesterday if today empty)."""
    if not days_with_reviews:
        return 0
    anchor = today if today in days_with_reviews else None
    if anchor is None:
        # streak continues from yesterday if no reviews yet today
        yesterday_ts = time.time() - 86400
        anchor = time.strftime("%Y-%m-%d", time.localtime(yesterday_ts))
        if anchor not in days_with_reviews:
            return 0
    streak = 0
    cursor = anchor
    while cursor in days_with_reviews:
        streak += 1
        ts = time.mktime(time.strptime(cursor, "%Y-%m-%d")) - 86400
        cursor = time.strftime("%Y-%m-%d", time.localtime(ts))
    return streak


def _day_progress(
    day: str,
    cards: int,
    latency_ms: int,
    *,
    goal_cards: int,
    goal_minutes: int | None,
    streak: int,
) -> DailyProgress:
    minutes = latency_ms / 60_000.0
    cards_pct = min(1.0, cards / goal_cards) if goal_cards else 0.0
    minutes_pct = None
    goal_met = cards >= goal_cards
    if goal_minutes is not None:
        minutes_pct = min(1.0, minutes / goal_minutes)
        goal_met = goal_met and minutes >= goal_minutes
    return DailyProgress(
        day=day,
        cards_reviewed=cards,
        minutes_studied=round(minutes, 1),
        goal_cards=goal_cards,
        goal_minutes=goal_minutes,
        cards_pct=cards_pct,
        minutes_pct=minutes_pct,
        goal_met=goal_met,
        streak_days=streak,
    )


def study_goal_report(col, *, config: dict[str, Any] | None = None) -> StudyGoalReport:
    goal_cards = daily_study_goal(config=config)
    goal_minutes = daily_study_goal_minutes(config=config)
    by_day = _review_days(col)
    today = time.strftime("%Y-%m-%d", time.localtime())
    streak = _compute_streak(set(by_day.keys()), today=today)

    cards, latency = by_day.get(today, (0, 0))
    today_prog = _day_progress(
        today, cards, latency, goal_cards=goal_cards, goal_minutes=goal_minutes, streak=streak
    )

    last_7: list[DailyProgress] = []
    for offset in range(6, -1, -1):
        ts = time.time() - offset * 86400
        day = time.strftime("%Y-%m-%d", time.localtime(ts))
        c, lat = by_day.get(day, (0, 0))
        last_7.append(
            _day_progress(day, c, lat, goal_cards=goal_cards, goal_minutes=goal_minutes, streak=0)
        )

    return StudyGoalReport(today=today_prog, streak_days=streak, last_7_days=last_7)
