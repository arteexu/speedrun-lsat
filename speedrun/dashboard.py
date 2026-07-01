# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Render the three-score dashboard and analytics as HTML.

Qt-free so it can be unit-tested; the aqt layer drops the returned HTML into
a dialog. Honesty rule: each score shows a range + give-up rule and abstains
when data is insufficient.
"""
from __future__ import annotations

import html
import json
from typing import Any

from speedrun.config import interleaving_enabled
from speedrun.config import latency_budget_ms
from speedrun.config import load_config
from speedrun.config import section_filter
from speedrun.insights import latency_histogram
from speedrun.insights import readiness_trajectory
from speedrun.insights import schema_mastery_map
from speedrun.insights import wrong_answer_patterns
from speedrun.scoring.memory import memory_score
from speedrun.scoring.performance import performance_score
from speedrun.scoring.queue import load_schema_weights, ordered_cards
from speedrun.scoring.readiness import readiness_score
from speedrun.study_goals import study_goal_report
from speedrun.taxonomy.labels import schema_display_html
from speedrun.timeline import progress_timeline


def _esc(text: object) -> str:
    return html.escape(str(text))


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.0%}"


def _score_state(gave_up: bool, point: float | None, *, lsat: bool = False) -> str:
    if gave_up or point is None:
        return "abstain"
    if lsat:
        if point >= 165:
            return "high"
        if point >= 150:
            return "medium"
        return "low"
    if point >= 0.75:
        return "high"
    if point >= 0.55:
        return "medium"
    return "low"


def _confidence_badge(label: str) -> str:
    cls = {"high": "badge-high", "medium": "badge-med", "low": "badge-low"}.get(
        label, "badge-low"
    )
    return f'<span class="badge {cls}">{_esc(label)}</span>'


_DASHBOARD_CSS = """
:root {
  --bg: #f4f6f9; --surface: #ffffff; --text: #1a1d21; --muted: #5c6570;
  --border: #dde2e8; --accent: #2563eb; --abstain: #94a3b8;
  --low: #dc2626; --med: #d97706; --high: #16a34a; --warn: #b45309; --bar-bg: #e8edf3;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1419; --surface: #1a2332; --text: #e8edf3; --muted: #94a3b8;
    --border: #2d3a4d; --accent: #60a5fa; --bar-bg: #243044;
  }
}
* { box-sizing: border-box; }
body { margin: 0; }
.sr-dash { font-family: system-ui, -apple-system, sans-serif; background: var(--bg);
  color: var(--text); padding: 20px 24px 28px; line-height: 1.45; max-width: 960px; }
.sr-header { margin-bottom: 20px; }
.sr-header h1 { margin: 0 0 4px; font-size: 1.5rem; font-weight: 700; }
.sr-header p { margin: 0; color: var(--muted); font-size: 0.85rem; }
.sr-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 14px; margin-bottom: 20px; }
.sr-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 16px 18px; border-top: 4px solid var(--border); }
.sr-card.state-abstain { border-top-color: var(--abstain); }
.sr-card.state-low { border-top-color: var(--low); }
.sr-card.state-medium { border-top-color: var(--med); }
.sr-card.state-high { border-top-color: var(--high); }
.sr-card-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; }
.sr-card-head h2 { margin: 0; font-size: 0.75rem; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--muted); font-weight: 600; }
.sr-value { font-size: 2rem; font-weight: 700; line-height: 1.1; margin: 4px 0; }
.sr-value.abstain { color: var(--abstain); font-size: 1.1rem; font-weight: 600; }
.sr-range, .sr-meta { font-size: 0.85rem; color: var(--muted); }
.sr-meta { margin-top: 8px; }
.sr-warn { margin-top: 8px; padding: 6px 10px; border-radius: 6px;
  background: rgba(180,83,9,0.12); color: var(--warn); font-size: 0.8rem; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 999px;
  font-size: 0.7rem; font-weight: 600; text-transform: uppercase; }
.badge-high { background: rgba(22,163,74,0.15); color: var(--high); }
.badge-med { background: rgba(217,119,6,0.15); color: var(--med); }
.badge-low { background: rgba(148,163,184,0.2); color: var(--muted); }
.sr-section { margin-top: 22px; }
.sr-section h3 { margin: 0 0 10px; font-size: 0.95rem; font-weight: 600; }
.sr-table-wrap { overflow-x: auto; border-radius: 10px; border: 1px solid var(--border); }
table.sr-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; background: var(--surface); }
table.sr-table th { text-align: left; padding: 8px 12px; background: var(--bar-bg);
  color: var(--muted); font-weight: 600; cursor: pointer; white-space: nowrap; }
table.sr-table td { padding: 7px 12px; border-top: 1px solid var(--border); }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.heat-bar { height: 8px; border-radius: 4px; background: var(--bar-bg); overflow: hidden; min-width: 60px; }
.heat-fill { height: 100%; border-radius: 4px; }
.heat-fill.weak { background: var(--low); }
.heat-fill.mid { background: var(--med); }
.heat-fill.strong { background: var(--high); }
.sr-timeline { display: flex; align-items: flex-end; gap: 4px; height: 80px; padding: 8px 0; }
.sr-timeline-bar { flex: 1; min-width: 12px; border-radius: 4px 4px 0 0; background: var(--accent); opacity: 0.85; position: relative; }
.sr-timeline-bar span { position: absolute; bottom: -18px; left: 50%; transform: translateX(-50%);
  font-size: 0.6rem; color: var(--muted); white-space: nowrap; }
.sr-queue-item { display: flex; align-items: center; gap: 10px; padding: 10px 12px;
  border-bottom: 1px solid var(--border); font-size: 0.82rem; }
.sr-queue-item:last-child { border-bottom: none; }
.sr-tag { font-size: 0.72rem; padding: 2px 8px; border-radius: 6px; background: var(--bar-bg);
  color: var(--text); max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sr-schema-cell { display: inline-block; line-height: 1.25; }
.sr-schema-label { display: block; font-weight: 500; }
.sr-schema-id { display: block; font-size: 0.68rem; color: var(--muted);
  font-family: ui-monospace, monospace; margin-top: 1px; }
.sr-schema-compact { font-size: inherit; font-weight: 500; }
.sr-priority { margin-left: auto; font-weight: 700; color: var(--accent); }
.sr-empty { color: var(--muted); font-size: 0.85rem; padding: 12px; }
.goal-bar { background: var(--bar-bg); height: 10px; border-radius: 5px; margin-top: 6px; max-width: 280px; }
.goal-fill { background: var(--high); height: 10px; border-radius: 5px; }
@media (max-width: 600px) { .sr-dash { padding: 14px 12px; } .sr-grid { grid-template-columns: 1fr; } }
"""

_DASHBOARD_JS = """
function srSortTable(tableId, colIdx, numeric) {
  const table = document.getElementById(tableId);
  if (!table) return;
  const tbody = table.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const th = table.querySelectorAll('th')[colIdx];
  const asc = th.dataset.sort !== 'asc';
  table.querySelectorAll('th').forEach(h => delete h.dataset.sort);
  th.dataset.sort = asc ? 'asc' : 'desc';
  rows.sort((a, b) => {
    let av = a.children[colIdx].dataset.val || a.children[colIdx].textContent.trim();
    let bv = b.children[colIdx].dataset.val || b.children[colIdx].textContent.trim();
    if (numeric) { av = parseFloat(av) || 0; bv = parseFloat(bv) || 0; }
    else { av = av.toLowerCase(); bv = bv.toLowerCase(); }
    return av < bv ? (asc ? -1 : 1) : av > bv ? (asc ? 1 : -1) : 0;
  });
  rows.forEach(r => tbody.appendChild(r));
}
document.querySelectorAll('table.sr-table th[data-col]').forEach(th => {
  th.addEventListener('click', () => {
    srSortTable(th.closest('table').id, parseInt(th.dataset.col, 10), th.dataset.numeric === '1');
  });
});
"""


def _shell(body: str, *, title: str = "LSAT Speedrun") -> str:
    return (
        f'<!DOCTYPE html><html><head><meta charset="utf-8">'
        f"<title>{_esc(title)}</title><style>{_DASHBOARD_CSS}</style></head>"
        f'<body><div class="sr-dash">{body}</div>'
        f"<script>{_DASHBOARD_JS}</script></body></html>"
    )


def _heat_bar(value: float | None) -> str:
    if value is None:
        return '<div class="heat-bar"><div class="heat-fill" style="width:0"></div></div>'
    pct = max(0, min(100, int(value * 100)))
    cls = "weak" if pct < 40 else ("mid" if pct < 70 else "strong")
    return f'<div class="heat-bar"><div class="heat-fill {cls}" style="width:{pct}%"></div></div>'


def _memory_card(result: dict[str, Any]) -> str:
    o = result["overall"]
    state = _score_state(o.gave_up, o.point)
    if o.gave_up:
        val = f'<div class="sr-value abstain">No score</div><div class="sr-range">{_esc(o.reason)}</div>'
    else:
        val = f'<div class="sr-value">{o.point:.0%}</div><div class="sr-range">likely {_pct(o.low)}–{_pct(o.high)} recall</div>'
    return (
        f'<div class="sr-card state-{state}"><div class="sr-card-head"><h2>Memory</h2></div>'
        f"{val}<div class='sr-meta'>reviewed {o.n_reviewed}/{o.n_cards} · coverage {o.coverage:.0%} · FSRS</div></div>"
    )


def _performance_card(result: dict[str, Any]) -> str:
    o = result["overall"]
    state = _score_state(o.gave_up, o.point)
    if o.gave_up:
        val = f'<div class="sr-value abstain">No score</div><div class="sr-range">{_esc(o.reason)}</div>'
    else:
        val = f'<div class="sr-value">{o.point:.0%}</div><div class="sr-range">likely {_pct(o.low)}–{_pct(o.high)} transfer</div>'
    warn = '<div class="sr-warn">Accurate but slow — would lose points on the clock.</div>' if o.speed_flag else ""
    sub = f"{o.n_attempts} attempts"
    if o.raw_accuracy is not None:
        sub += f" · raw {_pct(o.raw_accuracy)}"
    if o.on_budget_rate is not None:
        sub += f" · on-budget {_pct(o.on_budget_rate)}"
    lr, rc = latency_budget_ms("LR") // 1000, latency_budget_ms("RC") // 1000
    sub += f" · budgets LR {lr}s / RC {rc}s"
    return f'<div class="sr-card state-{state}"><div class="sr-card-head"><h2>Performance</h2></div>{val}{warn}<div class="sr-meta">{sub}</div></div>'


def _readiness_card(result: Any) -> str:
    state = _score_state(result.gave_up, result.point, lsat=True)
    if result.gave_up:
        val = f'<div class="sr-value abstain">No score</div><div class="sr-range">{_esc(result.reason)}</div>'
    else:
        val = f'<div class="sr-value">{result.point:.0f}</div><div class="sr-range">likely {result.low:.0f}–{result.high:.0f} LSAT</div>'
    warn = '<div class="sr-warn">Latency penalty applied.</div>' if result.speed_flag else ""
    next_step = (
        f"<div class='sr-meta'>Best next: {schema_display_html(result.best_next_step)}</div>"
        if result.best_next_step
        else ""
    )
    return (
        f'<div class="sr-card state-{state}"><div class="sr-card-head"><h2>Readiness</h2>'
        f"{_confidence_badge(result.confidence)}</div>{val}{warn}{next_step}"
        f"<div class='sr-meta'>coverage {result.coverage:.0%} · {result.n_attempts} attempts</div></div>"
    )


def _goal_card(col) -> str:
    report = study_goal_report(col)
    t = report.today
    bar_w = int(t.cards_pct * 100)
    mins = f" · {t.minutes_studied:.0f}/{t.goal_minutes} min" if t.goal_minutes else ""
    met = "Goal met today" if t.goal_met else "Keep going"
    return (
        f'<div class="sr-card state-{"high" if t.goal_met else "medium"}">'
        f'<div class="sr-card-head"><h2>Daily goal</h2></div>'
        f"<div>{t.cards_reviewed}/{t.goal_cards} cards{mins} · streak <b>{report.streak_days}</b></div>"
        f'<div class="goal-bar"><div class="goal-fill" style="width:{bar_w}%"></div></div>'
        f'<div class="sr-meta">{met}</div></div>'
    )


def _schema_table(table_id: str, rows: list[dict[str, Any]], *, score_label: str) -> str:
    if not rows:
        return '<div class="sr-empty">No per-schema data yet.</div>'
    body = ""
    for r in rows:
        body += (
            f"<tr><td data-val='{_esc(r['schema'])}'>{schema_display_html(r['schema'])}</td>"
            f"<td class='num' data-val='{r.get('score_val', '')}'>{r['score']}</td>"
            f"<td class='num'>{r['range']}</td><td class='num' data-val='{r.get('n', 0)}'>{r['n']}</td>"
            f"<td class='num' data-val='{r.get('weakness', 0)}'>{r['heat']}</td></tr>"
        )
    return (
        f'<div class="sr-table-wrap"><table class="sr-table" id="{table_id}"><thead><tr>'
        f'<th data-col="0">schema</th><th data-col="1" data-numeric="1" class="num">{score_label}</th>'
        f'<th data-col="2" class="num">range</th><th data-col="3" data-numeric="1" class="num">n</th>'
        f'<th data-col="4" data-numeric="1" class="num">weakness</th></tr></thead><tbody>{body}</tbody></table></div>'
    )


def _perf_schema_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for schema, s in result["per_schema"].items():
        if s.gave_up:
            continue
        weakness = 1.0 - (s.point or 0)
        rows.append(
            {
                "schema": schema,
                "score": f"{s.point:.0%}",
                "score_val": s.point,
                "range": f"{s.low:.0%}–{s.high:.0%}",
                "n": s.n_attempts,
                "weakness": weakness,
                "heat": _heat_bar(s.point),
            }
        )
    return sorted(rows, key=lambda r: r["weakness"], reverse=True)


def _mem_schema_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for schema, s in result["per_schema"].items():
        if s.gave_up:
            continue
        rows.append(
            {
                "schema": schema,
                "score": f"{s.point:.0%}",
                "score_val": s.point,
                "range": f"{s.low:.0%}–{s.high:.0%}",
                "n": s.n_reviewed,
                "weakness": 1.0 - (s.point or 0),
                "heat": _heat_bar(s.point),
            }
        )
    return sorted(rows, key=lambda r: r["weakness"], reverse=True)


def _weakness_heatmap(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    bars = ""
    for r in rows[:12]:
        w = r["weakness"]
        bars += (
            f'<div style="display:flex;align-items:center;gap:8px;margin:6px 0;font-size:0.78rem">'
            f'<span style="width:180px;overflow:hidden;text-overflow:ellipsis">{schema_display_html(r["schema"], compact=True)}</span>'
            f'{_heat_bar(1.0 - w)}<span class="num" style="width:36px">{w:.0%}</span></div>'
        )
    return f'<div class="sr-section"><h3>Weakness heatmap</h3>{bars}</div>'


def _timeline_chart(col, *, days: int = 14) -> str:
    tl = progress_timeline(col, days=days)
    if tl.gave_up or not tl.days:
        return f'<div class="sr-section"><h3>Progress timeline</h3><div class="sr-empty">{_esc(tl.reason)}</div></div>'
    max_n = max(d.n_reviews for d in tl.days) or 1
    bars = ""
    for d in tl.days:
        h = max(4, int(70 * d.n_reviews / max_n))
        acc = f"{d.accuracy:.0%}" if d.accuracy is not None else "—"
        bars += f'<div class="sr-timeline-bar" style="height:{h}px" title="{_esc(d.day)}: {d.n_reviews} reviews, {acc}"><span>{d.day[5:]}</span></div>'
    return f'<div class="sr-section"><h3>Progress timeline ({days}d)</h3><div class="sr-timeline">{bars}</div><div class="sr-meta">{_esc(tl.reason)}</div></div>'


def _mastery_table(col) -> str:
    items = schema_mastery_map(col)
    if not items:
        return ""
    colors = {"solid": "var(--high)", "weak": "var(--low)", "learning": "var(--med)", "untested": "var(--muted)"}
    rows = ""
    for m in items[:20]:
        c = colors.get(m.status, "var(--muted)")
        mem = "—" if m.memory is None else f"{m.memory:.0%}"
        perf = "—" if m.performance is None else f"{m.performance:.0%}"
        rows += f"<tr><td>{schema_display_html(m.schema)}</td><td style='color:{c}'>{_esc(m.status)}</td><td class='num'>{mem}</td><td class='num'>{perf}</td></tr>"
    extra = f'<div class="sr-meta">+ {len(items) - 20} more</div>' if len(items) > 20 else ""
    return (
        f'<div class="sr-section"><h3>Schema mastery map</h3>'
        f'<div class="sr-table-wrap"><table class="sr-table"><thead><tr>'
        f"<th>schema</th><th>status</th><th class='num'>memory</th><th class='num'>transfer</th>"
        f"</tr></thead><tbody>{rows}</tbody></table></div>{extra}</div>"
    )


def _wrong_patterns_table(col) -> str:
    patterns = wrong_answer_patterns(col, top_n=8)
    if not patterns:
        return ""
    rows = "".join(
        f"<tr><td>{schema_display_html(p.tag)}</td><td class='num'>{p.count}</td><td class='num'>{p.pct:.0%}</td></tr>"
        for p in patterns
    )
    return (
        f'<div class="sr-section"><h3>Wrong-answer patterns</h3>'
        f"<div class='sr-table-wrap'><table class='sr-table'><thead><tr>"
        f"<th>trap/flaw tag</th><th class='num'>count</th><th class='num'>%</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></div>"
    )


def _latency_table(col) -> str:
    parts = []
    for section in ("LR", "RC"):
        buckets = latency_histogram(col, section=section)
        if not buckets:
            continue
        rows = "".join(f"<tr><td>{_esc(b.label)}</td><td class='num'>{b.count}</td><td class='num'>{b.pct:.0%}</td></tr>" for b in buckets)
        parts.append(f"<h4>{section}</h4><div class='sr-table-wrap'><table class='sr-table'><tbody>{rows}</tbody></table></div>")
    if not parts:
        return ""
    return f'<div class="sr-section"><h3>Latency histogram</h3>{"".join(parts)}</div>'


def _trajectory_table(col) -> str:
    points = [p for p in readiness_trajectory(col, days=30) if not p.gave_up and p.projected is not None]
    if not points:
        return ""
    rows = "".join(f"<tr><td>{_esc(p.day)}</td><td class='num'>{p.projected:.0f}</td><td class='num'>{p.low:.0f}–{p.high:.0f}</td></tr>" for p in points[-10:])
    return (
        f'<div class="sr-section"><h3>Readiness trajectory</h3>'
        f"<div class='sr-table-wrap'><table class='sr-table'><thead><tr>"
        f"<th>day</th><th class='num'>projected</th><th class='num'>range</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></div>"
    )


def _queue_html(col, *, limit: int = 8) -> str:
    try:
        cards = ordered_cards(col, limit=limit)
    except Exception as exc:  # pragma: no cover
        return f'<div class="sr-empty">Could not build queue: {_esc(exc)}</div>'
    if not cards:
        return '<div class="sr-empty">No cards found. Import the seed deck first.</div>'
    weights = load_schema_weights()
    items = ""
    for i, c in enumerate(cards, 1):
        w = weights.get(c.schema, c.schema_weight)
        items += (
            f'<div class="sr-queue-item"><span style="color:var(--muted)">{i}</span>'
            f'<span class="sr-tag">{schema_display_html(c.schema or "", compact=True)}</span>'
            f'<span style="color:var(--muted);font-size:0.75rem">w={w:.2f}</span>'
            f'<span class="sr-priority">{c.priority:.2f} pts</span></div>'
        )
    return f'<div style="border:1px solid var(--border);border-radius:10px;background:var(--surface)">{items}</div>'


def render_config_editor_html() -> str:
    cfg = load_config()
    budgets = cfg.get("latency_budget_ms", {})
    body = (
        f"<table class='sr-table'><tbody>"
        f"<tr><td>Daily goal (cards)</td><td><b>{cfg.get('daily_study_goal_cards')}</b></td></tr>"
        f"<tr><td>Interleaving</td><td>{interleaving_enabled()}</td></tr>"
        f"<tr><td>Section filter</td><td>{section_filter() or 'all'}</td></tr>"
        f"<tr><td>Show schema ids</td><td>{cfg.get('show_schema_ids', False)}</td></tr>"
        f"<tr><td>LR budget</td><td>{budgets.get('LR', 84000) / 1000:.0f}s</td></tr>"
        f"<tr><td>RC budget</td><td>{budgets.get('RC', 96000) / 1000:.0f}s</td></tr>"
        f"</tbody></table>"
        f"<pre style='font-size:11px;margin-top:12px'>{_esc(json.dumps(cfg, indent=2))}</pre>"
    )
    return _shell(f'<div class="sr-header"><h1>Speedrun settings</h1></div>{body}', title="Settings")


def render_dashboard_html(col, *, timeline_days: int = 14) -> str:
    mem = memory_score(col)
    perf = performance_score(col)
    ready = readiness_score(col)
    perf_rows = _perf_schema_rows(perf)
    mode = "schema-weighted" if interleaving_enabled() else "plain Anki due"
    filt = section_filter()
    body = (
        f'<div class="sr-header"><h1>LSAT Speedrun</h1>'
        f"<p>Three separate scores with ranges. Queue: {mode}{' · ' + filt if filt else ''}. "
        f"Use <b>Tools → LSAT Speedrun → Study Now</b> or Ctrl+Shift+L for dashboard.</p></div>"
        f'<div class="sr-grid">{_goal_card(col)}{_memory_card(mem)}{_performance_card(perf)}{_readiness_card(ready)}</div>'
        f"{_weakness_heatmap(perf_rows)}"
        f'<div class="sr-section"><h3>Schema breakdown — memory</h3>{_schema_table("mem-table", _mem_schema_rows(mem), score_label="recall")}</div>'
        f'<div class="sr-section"><h3>Schema breakdown — performance</h3>{_schema_table("perf-table", perf_rows, score_label="transfer")}</div>'
        f"{_timeline_chart(col, days=timeline_days)}{_mastery_table(col)}{_wrong_patterns_table(col)}"
        f"{_latency_table(col)}{_trajectory_table(col)}"
        f'<div class="sr-section"><h3>Next up — schema-weighted queue</h3>{_queue_html(col)}</div>'
    )
    return _shell(body)


def render_study_list_html(col, *, limit: int = 20, heading: bool = True) -> str:
    title = '<div class="sr-header"><h1>Schema-weighted queue</h1></div>' if heading else ""
    return _shell(title + f'<div class="sr-section">{_queue_html(col, limit=limit)}</div>', title="Queue")


def render_report_html(col, *, title: str, body_html: str) -> str:
    return _shell(f'<div class="sr-header"><h1>{_esc(title)}</h1></div>{body_html}', title=title)


def render_transfer_gap_html(col) -> str:
    from speedrun.eval.transfer_gap import transfer_gap_report

    r = transfer_gap_report(col)
    if r.gave_up:
        body = f'<div class="sr-empty">{_esc(r.reason)}</div>'
    else:
        body = (
            f'<div class="sr-grid">'
            f'<div class="sr-card"><h2>Recall</h2><div class="sr-value">{r.recall_point:.0%}</div></div>'
            f'<div class="sr-card"><h2>Transfer</h2><div class="sr-value">{r.reworded_point:.0%}</div></div>'
            f'<div class="sr-card"><h2>Gap</h2><div class="sr-value">{r.gap:+.0%}</div>'
            f'<div class="sr-meta">Bridge distinct: {r.bridge_distinct}</div></div></div>'
        )
    return render_report_html(col, title="Transfer gap report", body_html=body)


def render_calibration_html(col) -> str:
    from speedrun.eval.calibration import calibration_report

    r = calibration_report(col)
    if r.gave_up:
        body = f'<div class="sr-empty">{_esc(r.reason)}</div>'
    else:
        rows = "".join(
            f"<tr><td>{b.bin_low:.0%}–{b.bin_high:.0%}</td><td class='num'>{b.mean_predicted:.0%}</td>"
            f"<td class='num'>{b.mean_actual:.0%}</td><td class='num'>{b.n}</td></tr>"
            for b in r.bins
        )
        body = (
            f"<p class='sr-meta'>Brier {r.brier:.3f} · log loss {r.log_loss:.3f} · {r.n_held_out} reviews</p>"
            f"<div class='sr-table-wrap'><table class='sr-table'><thead><tr>"
            f"<th>bin</th><th>predicted</th><th>actual</th><th>n</th></tr></thead><tbody>{rows}</tbody></table></div>"
        )
    return render_report_html(col, title="Calibration report", body_html=body)


def render_memory_report_html(col) -> str:
    mem = memory_score(col)
    body = _memory_card(mem) + _schema_table("mem-rpt", _mem_schema_rows(mem), score_label="recall")
    return render_report_html(col, title="Memory report", body_html=body)


def render_performance_report_html(col) -> str:
    perf = performance_score(col)
    body = _performance_card(perf) + _schema_table("perf-rpt", _perf_schema_rows(perf), score_label="transfer")
    return render_report_html(col, title="Performance report", body_html=body)


def render_readiness_report_html(col) -> str:
    return render_report_html(col, title="Readiness report", body_html=_readiness_card(readiness_score(col)))


def export_dashboard_html(col, path: str | None = None) -> str:
    from pathlib import Path

    from speedrun.export import render_full_export_html

    html_out = render_full_export_html(col)
    if path:
        Path(path).write_text(html_out, encoding="utf-8")
    return html_out


def dashboard_summary(col) -> dict[str, str]:
    mem = memory_score(col)["overall"]
    perf = performance_score(col)["overall"]
    ready = readiness_score(col)

    def fmt(gave_up: bool, point: float | None, *, lsat: bool = False) -> str:
        if gave_up or point is None:
            return "—"
        return f"{point:.0f}" if lsat else f"{point:.0%}"

    return {
        "memory": fmt(mem.gave_up, mem.point),
        "performance": fmt(perf.gave_up, perf.point),
        "readiness": fmt(ready.gave_up, ready.point, lsat=True),
    }
