# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Honest memory score built on Anki's FSRS.

Memory answers: "can the student recall a taught fact right now?" We read each
card's current recall probability from the *engine's own* FSRS via the
`extract_fsrs_retrievability` SQL function (no reimplementation), aggregate per
schema and overall, and report a point estimate WITH a range and an explicit
give-up rule. Below the data line, the score abstains instead of guessing.

On the LSAT this is deliberately a small part of the system (the BrainLift treats
memory as supporting, not foundational); the value is in reporting it honestly.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import Any

SCHEMA_TAG = "sr:schema:"

# Give-up thresholds (mirror the readiness give-up style; tunable).
# Counted in cards that have FSRS memory state, i.e. reviewed at least once.
MIN_REVIEWED_OVERALL = 5
MIN_REVIEWED_PER_SCHEMA = 2

_Z_95 = 1.96


@dataclass
class MemoryScore:
    """An honest memory estimate. When `gave_up` is True, point/low/high are None."""

    label: str
    point: float | None
    low: float | None
    high: float | None
    n_reviewed: int
    n_cards: int
    coverage: float
    gave_up: bool
    reason: str
    last_updated: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def mean_ci(values: list[float], z: float = _Z_95) -> tuple[float, float, float]:
    """Point estimate and a [low, high] band for the mean of recall probabilities.

    Uses a normal approximation of the standard error of the mean, clamped to
    [0, 1]. A single sample yields a deliberately wide band (we do not pretend to
    precision we lack)."""
    n = len(values)
    if n == 0:
        raise ValueError("mean_ci requires at least one value")
    point = sum(values) / n
    if n >= 2:
        half = z * statistics.stdev(values) / (n**0.5)
    else:
        half = 0.5
    return point, max(0.0, point - half), min(1.0, point + half)


def score_from_reviewed(
    reviewed: list[float],
    n_cards: int,
    *,
    label: str,
    min_reviewed: int,
) -> MemoryScore:
    """Build a MemoryScore from the *reviewed* retrievabilities and the total
    card count.

    `reviewed` holds only the non-``None`` per-card recall probabilities (cards
    that have FSRS memory state); `n_cards` is the total number of cards in scope
    (reviewed or not). Splitting the reviewed values from the total lets callers
    avoid materialising a ``None`` for every unreviewed card on the 50k deck — the
    math is identical because only the reviewed values and the two counts matter."""
    n_reviewed = len(reviewed)
    coverage = (n_reviewed / n_cards) if n_cards else 0.0

    if n_reviewed < min_reviewed:
        return MemoryScore(
            label=label,
            point=None,
            low=None,
            high=None,
            n_reviewed=n_reviewed,
            n_cards=n_cards,
            coverage=coverage,
            gave_up=True,
            reason=(
                f"Not enough data: {n_reviewed} reviewed card(s) < required "
                f"{min_reviewed}. Review more cards to get a memory score."
            ),
        )

    point, low, high = mean_ci(reviewed)
    return MemoryScore(
        label=label,
        point=point,
        low=low,
        high=high,
        n_reviewed=n_reviewed,
        n_cards=n_cards,
        coverage=coverage,
        gave_up=False,
        reason=f"Mean FSRS recall over {n_reviewed} reviewed card(s).",
    )


def score_from_retrievabilities(
    retrievabilities: list[float | None],
    *,
    label: str,
    min_reviewed: int,
) -> MemoryScore:
    """Build a MemoryScore from per-card retrievabilities.

    `None` entries are cards with no FSRS memory yet (not reviewed); they count
    toward `n_cards` but not toward the estimate."""
    reviewed = [r for r in retrievabilities if r is not None]
    return score_from_reviewed(
        reviewed, len(retrievabilities), label=label, min_reviewed=min_reviewed
    )


def _schema_from_tags(tags: str, prefix: str = SCHEMA_TAG) -> str | None:
    for tok in tags.split():
        if tok.startswith(prefix):
            return tok[len(prefix) :]
    return None


def collection_memory_records(
    col, schema_tag_prefix: str = SCHEMA_TAG
) -> list[tuple[str, float | None]]:
    """Return (schema, retrievability|None) for every schema-tagged card, reading
    retrievability from the engine's own FSRS via SQL."""
    timing = col._backend.sched_timing_today()
    today = timing.days_elapsed
    next_day_at = timing.next_day_at
    now = int(time.time())

    rows = col.db.all(
        """
        SELECT n.tags,
               extract_fsrs_retrievability(
                   c.data,
                   CASE WHEN c.odue != 0 THEN c.odue ELSE c.due END,
                   c.ivl, ?, ?, ?)
        FROM cards c JOIN notes n ON c.nid = n.id
        """,
        today,
        next_day_at,
        now,
    )
    records: list[tuple[str, float | None]] = []
    for tags, retr in rows:
        schema = _schema_from_tags(tags, schema_tag_prefix)
        if schema is None:
            continue  # not an LSAT schema card
        records.append((schema, retr))
    return records


def schema_card_totals(col, schema_tag_prefix: str = SCHEMA_TAG) -> dict[str, int]:
    """Cards per schema across the collection via one ``GROUP BY notes.tags``.

    SQLite collapses the 50k cards into a few hundred distinct tag strings, so
    this costs ~40ms on the big deck rather than shipping every row to Python.
    Memoized per collection-state token and shared by the memory aggregation and
    the dashboard queue pre-filter (both need per-schema card counts), so the
    GROUP BY runs once per render."""
    from speedrun.score_cache import cached

    def compute() -> dict[str, int]:
        out: dict[str, int] = {}
        for tags, cnt in col.db.all(
            """
            SELECT n.tags, COUNT(*)
            FROM cards c JOIN notes n ON c.nid = n.id
            GROUP BY n.tags
            """
        ):
            schema = _schema_from_tags(tags, schema_tag_prefix)
            if schema is None:
                continue
            out[schema] = out.get(schema, 0) + int(cnt)
        return out

    return cached(col, f"schema_card_totals::{schema_tag_prefix}", compute)


def _memory_aggregates(
    col, schema_tag_prefix: str = SCHEMA_TAG
) -> tuple[int, dict[str, int], dict[str, list[float]]]:
    """Single-pass memory aggregation, shared by every consumer of the score.

    Returns ``(overall_total, per_schema_total, per_schema_reviewed)`` where:

    * ``overall_total`` / ``per_schema_total`` count *all* schema-tagged cards
      (reviewed or not) — the denominators for coverage. They come from a
      ``GROUP BY notes.tags`` aggregation, so SQLite collapses the 50k cards into
      a few hundred distinct tag strings instead of shipping every row to Python.
    * ``per_schema_reviewed`` holds the FSRS retrievabilities of the cards that
      actually have memory state. ``extract_fsrs_retrievability`` returns non-None
      only for cards with stored FSRS state, which always means the card has been
      reviewed (``reps > 0``), so scanning that subset yields exactly the same set
      of retrievabilities as scanning every card — but touches ~the reviewed count
      of rows instead of all 50k.

    The result is memoized per collection-state token so the (gated and ungated)
    memory scores, the mastery map, and the concept graph all share one scan."""
    from speedrun.score_cache import cached

    def compute() -> tuple[int, dict[str, int], dict[str, list[float]]]:
        totals = schema_card_totals(col, schema_tag_prefix)
        overall_total = sum(totals.values())

        timing = col._backend.sched_timing_today()
        today = timing.days_elapsed
        next_day_at = timing.next_day_at
        now = int(time.time())
        reviewed: dict[str, list[float]] = {}
        for tags, retr in col.db.all(
            """
            SELECT n.tags,
                   extract_fsrs_retrievability(
                       c.data,
                       CASE WHEN c.odue != 0 THEN c.odue ELSE c.due END,
                       c.ivl, ?, ?, ?)
            FROM cards c JOIN notes n ON c.nid = n.id
            WHERE c.reps > 0
               OR (c.data IS NOT NULL AND c.data != '' AND c.data != '{}')
            """,
            today,
            next_day_at,
            now,
        ):
            if retr is None:
                continue
            schema = _schema_from_tags(tags, schema_tag_prefix)
            if schema is None:
                continue
            reviewed.setdefault(schema, []).append(retr)
        return overall_total, totals, reviewed

    return cached(col, f"memory_aggregates::{schema_tag_prefix}", compute)


def memory_score(
    col,
    *,
    min_reviewed_overall: int = MIN_REVIEWED_OVERALL,
    min_reviewed_per_schema: int = MIN_REVIEWED_PER_SCHEMA,
    schema_tag_prefix: str = SCHEMA_TAG,
    gate: Any = None,
) -> dict[str, Any]:
    """Compute the honest memory score (overall + per schema) for a collection.

    If an evidence `gate` is supplied and it is closed, the score abstains with the
    gate's reason (not enough flashcards/flaws/patterns practiced yet)."""
    overall_total, totals, reviewed = _memory_aggregates(col, schema_tag_prefix)
    all_reviewed = [r for vals in reviewed.values() for r in vals]

    if gate is not None and not gate.open:
        overall = MemoryScore(
            label="overall",
            point=None,
            low=None,
            high=None,
            n_reviewed=len(all_reviewed),
            n_cards=overall_total,
            coverage=(len(all_reviewed) / overall_total) if overall_total else 0.0,
            gave_up=True,
            reason=gate.reason,
        )
        return {"overall": overall, "per_schema": {}}

    overall = score_from_reviewed(
        all_reviewed, overall_total, label="overall", min_reviewed=min_reviewed_overall
    )

    per_schema = {
        schema: score_from_reviewed(
            reviewed.get(schema, []),
            totals[schema],
            label=schema,
            min_reviewed=min_reviewed_per_schema,
        )
        for schema in sorted(totals)
    }

    return {"overall": overall, "per_schema": per_schema}
