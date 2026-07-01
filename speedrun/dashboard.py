# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Render the three-score dashboard and the schema-weighted study preview as HTML.

Qt-free so it can be unit-tested; the aqt layer just drops the returned HTML into
a dialog. Honesty rule: performance and readiness abstain with an explicit reason
until their models exist, and memory shows a range + give-up rule.
"""
from __future__ import annotations

import html

from speedrun.scoring.memory import memory_score
from speedrun.scoring.queue import ordered_cards


def _esc(text: object) -> str:
    return html.escape(str(text))


def _score_card(title: str, body: str, subtitle: str = "") -> str:
    sub = f'<div style="color:#777;font-size:12px">{subtitle}</div>' if subtitle else ""
    return (
        '<table width="100%" cellpadding="8" style="margin-bottom:10px;border:1px solid #ddd">'
        f'<tr><td><b style="font-size:15px">{title}</b>{sub}'
        f'<div style="margin-top:6px">{body}</div></td></tr></table>'
    )


def _memory_section(col) -> str:
    result = memory_score(col)
    o = result["overall"]
    if o.gave_up:
        body = f'<span style="color:#b00">No score</span> — {_esc(o.reason)}'
    else:
        body = (
            f'<span style="font-size:22px;color:#1a7f37"><b>{o.point:.0%}</b></span>'
            f' &nbsp;recall &nbsp;·&nbsp; likely range {o.low:.0%}–{o.high:.0%}'
        )
    subtitle = (
        f"reviewed {o.n_reviewed}/{o.n_cards} cards · coverage {o.coverage:.0%} · "
        "source: Anki FSRS"
    )

    # per-schema breakdown (reviewed schemas only)
    rows = ""
    for schema, s in result["per_schema"].items():
        if s.gave_up:
            continue
        rows += (
            f'<tr><td>{_esc(schema)}</td>'
            f'<td align="right">{s.point:.0%}</td>'
            f'<td align="right" style="color:#777">{s.low:.0%}–{s.high:.0%}</td>'
            f'<td align="right" style="color:#777">n={s.n_reviewed}</td></tr>'
        )
    if rows:
        body += (
            '<table width="100%" cellpadding="4" style="margin-top:8px;font-size:13px">'
            '<tr style="color:#777"><td>schema</td><td align="right">recall</td>'
            '<td align="right">range</td><td align="right">n</td></tr>'
            f"{rows}</table>"
        )
    return _score_card("Memory", body, subtitle)


def _abstain_section(title: str, reason: str) -> str:
    body = f'<span style="color:#b00">No score</span> — {_esc(reason)}'
    return _score_card(title, body, "honesty rule: abstains until its model is built")


def render_dashboard_html(col) -> str:
    """Full three-score dashboard as an HTML string."""
    memory = _memory_section(col)
    performance = _abstain_section(
        "Performance",
        "the memory→transfer model is not built yet; a performance number now "
        "would just echo memory.",
    )
    readiness = _abstain_section(
        "Readiness (projected LSAT 120–180)",
        "needs the performance model plus coverage/latency; showing a score now "
        "would be a guess in a nice font.",
    )
    preview = render_study_list_html(col, limit=10, heading=False)
    return (
        '<div style="font-family:system-ui,sans-serif">'
        '<h2 style="margin:0 0 4px 0">LSAT Speedrun — Scores</h2>'
        '<div style="color:#777;font-size:12px;margin-bottom:10px">'
        "Three separate scores, each with a range and a give-up rule. "
        "Memory is live; performance and readiness abstain until their models exist."
        "</div>"
        f"{memory}{performance}{readiness}"
        '<h3 style="margin:14px 0 4px 0">Next up — schema-weighted queue</h3>'
        f"{preview}"
        "</div>"
    )


def render_study_list_html(col, *, limit: int = 20, heading: bool = True) -> str:
    """Table of the highest points-at-stake cards from the Rust queue."""
    try:
        cards = ordered_cards(col, limit=limit)
    except Exception as exc:  # pragma: no cover - defensive
        return f'<div style="color:#b00">Could not build queue: {_esc(exc)}</div>'

    if not cards:
        return (
            '<div style="color:#777">No cards found. Import the seed deck first '
            "(Tools → LSAT Speedrun → Import Seed Deck).</div>"
        )

    rows = ""
    for c in cards:
        rows += (
            f'<tr><td align="right">{c.priority:.3f}</td>'
            f"<td>{_esc(c.schema) or '(none)'}</td>"
            f'<td align="right" style="color:#777">w={c.schema_weight:.3f}</td>'
            f'<td align="right" style="color:#777">weak={c.weakness:.2f}</td></tr>'
        )
    table = (
        '<table width="100%" cellpadding="4" style="font-size:13px;border:1px solid #ddd">'
        '<tr style="color:#777"><td align="right">priority</td><td>schema</td>'
        '<td align="right">weight</td><td align="right">weakness</td></tr>'
        f"{rows}</table>"
    )
    if heading:
        table = '<h3 style="font-family:system-ui,sans-serif">Schema-weighted queue</h3>' + table
    return table
