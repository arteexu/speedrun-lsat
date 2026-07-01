# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Pre-test simulation: timed block with deferred feedback."""
from __future__ import annotations

import html
import time
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from speedrun.config import latency_budget_ms
from speedrun.scoring.memory import SCHEMA_TAG
from speedrun.scoring.memory import _schema_from_tags
from speedrun.scoring.performance import score_from_attempts
from speedrun.scoring.performance import Attempt
from speedrun.scoring.queue import ordered_cards
from speedrun.taxonomy.labels import schema_display_html


@dataclass
class PretestItem:
    card_id: int
    schema: str
    section: str
    started_ms: int = 0
    answered_ms: int = 0
    ease: int = 0
    correct: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PretestSession:
    items: list[PretestItem]
    block_size: int
    time_limit_ms: int | None
    started_at: int
    finished_at: int | None = None
    performance: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["items"] = [i.to_dict() for i in self.items]
        return d


def _section_from_schema(schema: str) -> str:
    return "RC" if schema.startswith("rc.") else "LR"


def build_pretest_queue(col, *, block_size: int = 10, search: str | None = None) -> list[PretestItem]:
    """Select cards for a pre-test block (no immediate feedback during study)."""
    base_search = search or 'deck:"LSAT Speedrun"'
    cards = ordered_cards(col, limit=block_size, search=base_search)
    items: list[PretestItem] = []
    for c in cards:
        sec = _section_from_schema(c.schema or "")
        items.append(PretestItem(card_id=c.card_id, schema=c.schema or "", section=sec))
    return items


def score_pretest_session(session: PretestSession) -> dict[str, Any]:
    """Score a completed pre-test using the performance model."""
    attempts: list[Attempt] = []
    for item in session.items:
        if item.answered_ms <= 0:
            continue
        latency = item.answered_ms - item.started_ms if item.started_ms else item.answered_ms
        attempts.append(
            Attempt(schema=item.schema, correct=item.correct, latency_ms=max(1, latency))
        )
    overall = score_from_attempts(attempts, label="pretest", min_attempts=1)
    by_schema: dict[str, list[Attempt]] = {}
    for a in attempts:
        by_schema.setdefault(a.schema, []).append(a)
    per_schema = {
        s: score_from_attempts(g, label=s, min_attempts=1) for s, g in sorted(by_schema.items())
    }
    return {"overall": overall.to_dict(), "per_schema": {k: v.to_dict() for k, v in per_schema.items()}}


def render_pretest_results_html(session: PretestSession, score: dict[str, Any]) -> str:
    o = score["overall"]
    esc = html.escape
    if o.get("gave_up"):
        body = f'<p style="color:#b00">No score — {esc(o.get("reason", ""))}</p>'
    else:
        body = (
            f'<p><span style="font-size:22px;color:#1a7f37"><b>{o["point"]:.0%}</b></span> '
            f"on-budget transfer · range {o['low']:.0%}–{o['high']:.0%}</p>"
        )
    rows = ""
    for item in session.items:
        mark = "✓" if item.correct else "✗"
        color = "#1a7f37" if item.correct else "#b00"
        rows += (
            f'<tr><td>{schema_display_html(item.schema)}</td><td>{esc(item.section)}</td>'
            f'<td style="color:{color}">{mark}</td></tr>'
        )
    return (
        '<div style="font-family:system-ui,sans-serif">'
        "<h2>Pre-test simulation results</h2>"
        f"<p>{len(session.items)} items · no immediate feedback during block</p>"
        f"{body}"
        '<table width="100%" cellpadding="4" style="margin-top:10px;font-size:13px">'
        '<tr style="color:#777"><td>schema</td><td>section</td><td>result</td></tr>'
        f"{rows}</table></div>"
    )


def simulate_pretest_from_revlog(col, *, block_size: int = 10) -> PretestSession:
    """Replay the most recent reviews as a synthetic pre-test (for CLI/demo)."""
    rows = col.db.all(
        """
        SELECT c.id, n.tags, r.ease, r.time, r.id
        FROM revlog r
        JOIN cards c ON r.cid = c.id
        JOIN notes n ON c.nid = n.id
        WHERE r.ease > 0
        ORDER BY r.id DESC
        LIMIT ?
        """,
        block_size,
    )
    items: list[PretestItem] = []
    for cid, tags, ease, latency, rid in reversed(rows):
        schema = _schema_from_tags(tags, SCHEMA_TAG)
        if schema is None:
            continue
        sec = _section_from_schema(schema)
        items.append(
            PretestItem(
                card_id=int(cid),
                schema=schema,
                section=sec,
                started_ms=int(rid) - int(latency),
                answered_ms=int(rid),
                ease=int(ease),
                correct=int(ease) != 1,
            )
        )
    session = PretestSession(
        items=items,
        block_size=block_size,
        time_limit_ms=None,
        started_at=int(time.time()),
        finished_at=int(time.time()),
    )
    session.performance = score_pretest_session(session)
    return session
