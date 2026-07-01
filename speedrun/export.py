# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""One-click export of dashboard + reports to a self-contained HTML file."""
from __future__ import annotations

import html
import json
import time
from pathlib import Path
from typing import Any

from speedrun.config import load_config
from speedrun.dashboard import render_dashboard_html
from speedrun.insights import latency_histogram
from speedrun.insights import readiness_trajectory
from speedrun.insights import schema_mastery_map
from speedrun.insights import wrong_answer_patterns
from speedrun.study_goals import study_goal_report
from speedrun.timeline import progress_timeline


def _esc(text: object) -> str:
    return html.escape(str(text))


def _timeline_chart_html(col, *, days: int = 14) -> str:
    report = progress_timeline(col, days=days)
    if report.gave_up:
        return f'<p style="color:#777">{_esc(report.reason)}</p>'
    bars = ""
    for day in report.days:
        acc = day.accuracy or 0
        pct = int(acc * 100)
        bars += (
            f'<div style="display:inline-block;width:28px;margin:2px;text-align:center">'
            f'<div style="height:{pct}px;background:#1a7f37;min-height:2px"></div>'
            f'<div style="font-size:9px;color:#777">{day.day[5:]}</div></div>'
        )
    return f'<div style="margin:8px 0">{bars}</div>'


def _mastery_map_html(col) -> str:
    rows = ""
    for m in schema_mastery_map(col):
        color = {"solid": "#1a7f37", "weak": "#b00", "learning": "#b85c00", "untested": "#777"}.get(
            m.status, "#777"
        )
        rows += (
            f'<tr><td>{_esc(m.schema)}</td>'
            f'<td style="color:{color}">{_esc(m.status)}</td>'
            f'<td align="right">{"" if m.memory is None else f"{m.memory:.0%}"}</td>'
            f'<td align="right">{"" if m.performance is None else f"{m.performance:.0%}"}</td></tr>'
        )
    return (
        '<table width="100%" cellpadding="4" style="font-size:13px;border:1px solid #ddd">'
        '<tr style="color:#777"><td>schema</td><td>status</td>'
        '<td align="right">memory</td><td align="right">transfer</td></tr>'
        f"{rows}</table>"
    )


def _wrong_patterns_html(col) -> str:
    patterns = wrong_answer_patterns(col)
    if not patterns:
        return '<p style="color:#777">No Again reviews yet.</p>'
    rows = ""
    for p in patterns:
        rows += f'<tr><td>{_esc(p.tag)}</td><td align="right">{p.count}</td><td align="right">{p.pct:.0%}</td></tr>'
    return (
        '<table width="100%" cellpadding="4" style="font-size:13px">'
        '<tr style="color:#777"><td>pattern</td><td align="right">count</td><td align="right">%</td></tr>'
        f"{rows}</table>"
    )


def _latency_html(col) -> str:
    parts = []
    for section in (None, "LR", "RC"):
        label = section or "all"
        buckets = latency_histogram(col, section=section)
        if not buckets:
            continue
        rows = "".join(
            f'<tr><td>{_esc(b.label)}</td><td align="right">{b.count}</td><td align="right">{b.pct:.0%}</td></tr>'
            for b in buckets
        )
        parts.append(
            f"<h4>{_esc(label)}</h4>"
            f'<table width="100%" cellpadding="4" style="font-size:13px">'
            f'<tr style="color:#777"><td>bucket</td><td align="right">n</td><td align="right">%</td></tr>'
            f"{rows}</table>"
        )
    return "".join(parts) or '<p style="color:#777">No latency data yet.</p>'


def _goal_html(col) -> str:
    report = study_goal_report(col)
    t = report.today
    bar_w = int(t.cards_pct * 200)
    mins = (
        f" · {t.minutes_studied:.0f}/{t.goal_minutes} min"
        if t.goal_minutes
        else ""
    )
    return (
        f'<p>Today: {t.cards_reviewed}/{t.goal_cards} cards{mins} · '
        f'streak <b>{report.streak_days}</b> day(s)</p>'
        f'<div style="background:#eee;width:200px;height:12px">'
        f'<div style="background:#1a7f37;width:{bar_w}px;height:12px"></div></div>'
    )


def _dashboard_embed(col) -> str:
    """Dashboard inner HTML without nested document shell."""
    full = render_dashboard_html(col)
    start = full.find('<div class="sr-dash">')
    end = full.rfind("</div><script>")
    if start >= 0 and end > start:
        return full[start : end + len("</div>")]
    return full


def render_full_export_html(col) -> str:
    dashboard = _dashboard_embed(col)
    trajectory = readiness_trajectory(col)
    traj_rows = ""
    for p in trajectory[-14:]:
        if p.gave_up or p.projected is None:
            traj_rows += f'<tr><td>{_esc(p.day)}</td><td colspan="2" style="color:#777">abstain (n={p.n_attempts})</td></tr>'
        else:
            traj_rows += (
                f'<tr><td>{_esc(p.day)}</td>'
                f'<td align="right">{p.projected:.0f}</td>'
                f'<td align="right" style="color:#777">{p.low:.0f}–{p.high:.0f}</td></tr>'
            )
    config_json = json.dumps(load_config(), indent=2)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>LSAT Speedrun Export</title>
<style>body{{font-family:system-ui,sans-serif;max-width:900px;margin:24px auto;padding:0 16px}}
section{{margin:24px 0;padding:16px;border:1px solid #ddd;border-radius:6px}}</style>
</head><body>
<h1>LSAT Speedrun — Offline Export</h1>
<p style="color:#777">Generated {_esc(time.strftime("%Y-%m-%d %H:%M"))} · offline only</p>
<section><h2>Daily goal</h2>{_goal_html(col)}</section>
<section>{dashboard}</section>
<section><h2>Progress timeline (14 days)</h2>{_timeline_chart_html(col)}</section>
<section><h2>Schema mastery map</h2>{_mastery_map_html(col)}</section>
<section><h2>Wrong-answer patterns</h2>{_wrong_patterns_html(col)}</section>
<section><h2>Latency histogram</h2>{_latency_html(col)}</section>
<section><h2>Readiness trajectory</h2>
<table width="100%" cellpadding="4" style="font-size:13px">
<tr style="color:#777"><td>day</td><td align="right">projected</td><td align="right">range</td></tr>
{traj_rows or '<tr><td colspan="3" style="color:#777">Not enough data yet.</td></tr>'}
</table></section>
<section><h2>Config snapshot</h2><pre style="font-size:12px;background:#f6f6f6;padding:8px">{_esc(config_json)}</pre></section>
</body></html>"""


def export_html(col, path: Path) -> Path:
    path.write_text(render_full_export_html(col), encoding="utf-8")
    return path
