# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Render the three-score dashboard and the schema-weighted study preview as HTML.

Qt-free so it can be unit-tested; the aqt layer just drops the returned HTML into
a dialog. Honesty rule: each score shows a range + give-up rule and abstains
when data is insufficient.
"""
from __future__ import annotations

import html

from speedrun.scoring.memory import memory_score
from speedrun.scoring.performance import performance_score
from speedrun.scoring.queue import ordered_cards
from speedrun.scoring.readiness import readiness_score


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


def _performance_section(col) -> str:
    result = performance_score(col)
    o = result["overall"]
    if o.gave_up:
        body = f'<span style="color:#b00">No score</span> — {_esc(o.reason)}'
    else:
        body = (
            f'<span style="font-size:22px;color:#1a7f37"><b>{o.point:.0%}</b></span>'
            f' &nbsp;transfer &nbsp;·&nbsp; likely range {o.low:.0%}–{o.high:.0%}'
        )
        if o.speed_flag:
            body += (
                '<div style="color:#b85c00;margin-top:4px;font-size:13px">'
                "Accurate but slow — would lose points on the clock."
                "</div>"
            )
    if o.raw_accuracy is not None:
        subtitle = (
            f"{o.n_attempts} graded attempts · raw accuracy {o.raw_accuracy:.0%}"
        )
    else:
        subtitle = f"{o.n_attempts} graded attempts"
    if o.on_budget_rate is not None:
        subtitle += f" · on-budget {o.on_budget_rate:.0%}"
    subtitle += " · source: revlog (latency-adjusted)"

    rows = ""
    for schema, s in result["per_schema"].items():
        if s.gave_up:
            continue
        rows += (
            f'<tr><td>{_esc(schema)}</td>'
            f'<td align="right">{s.point:.0%}</td>'
            f'<td align="right" style="color:#777">{s.low:.0%}–{s.high:.0%}</td>'
            f'<td align="right" style="color:#777">n={s.n_attempts}</td></tr>'
        )
    if rows:
        body += (
            '<table width="100%" cellpadding="4" style="margin-top:8px;font-size:13px">'
            '<tr style="color:#777"><td>schema</td><td align="right">transfer</td>'
            '<td align="right">range</td><td align="right">n</td></tr>'
            f"{rows}</table>"
        )
    return _score_card("Performance", body, subtitle)


def _readiness_section(col) -> str:
    result = readiness_score(col)
    if result.gave_up:
        body = f'<span style="color:#b00">No score</span> — {_esc(result.reason)}'
    else:
        body = (
            f'<span style="font-size:22px;color:#1a7f37"><b>{result.point:.0f}</b></span>'
            f" &nbsp;projected LSAT &nbsp;·&nbsp; likely range "
            f"{result.low:.0f}–{result.high:.0f}"
        )
        if result.speed_flag:
            body += (
                '<div style="color:#b85c00;margin-top:4px;font-size:13px">'
                "Latency penalty applied — accurate but slow."
                "</div>"
            )
        if result.best_next_step:
            body += (
                f'<div style="margin-top:6px;font-size:13px">'
                f"Best next step: <b>{_esc(result.best_next_step)}</b></div>"
            )
    subtitle = (
        f"coverage {result.coverage:.0%} · {result.n_attempts} attempts · "
        f"confidence {result.confidence} · linear map (stated approximation)"
    )
    return _score_card("Readiness (projected LSAT 120–180)", body, subtitle)


def render_dashboard_html(col) -> str:
    """Full three-score dashboard as an HTML string."""
    memory = _memory_section(col)
    performance = _performance_section(col)
    readiness = _readiness_section(col)
    preview = render_study_list_html(col, limit=10, heading=False)
    return (
        '<div style="font-family:system-ui,sans-serif">'
        '<h2 style="margin:0 0 4px 0">LSAT Speedrun — Scores</h2>'
        '<div style="color:#777;font-size:12px;margin-bottom:10px">'
        "Three separate scores, each with a range and a give-up rule. "
        "Scores abstain when data is insufficient."
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
