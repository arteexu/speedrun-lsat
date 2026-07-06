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
import time
from typing import Any

from speedrun.concept_graph import build_concept_graph
from speedrun.mistake_graph import build_mistake_graph
from speedrun.config import (
    interleaving_enabled,
    latency_budget_ms,
    load_config,
    section_filter,
)
from speedrun.insights import (
    latency_histogram,
    readiness_trajectory,
    schema_mastery_map,
    trap_profile,
    wrong_answer_patterns,
)
from speedrun.scoring.guardrail import evidence_gate
from speedrun.scoring.memory import MIN_REVIEWED_OVERALL, memory_score
from speedrun.scoring.performance import MIN_ATTEMPTS_OVERALL, performance_score
from speedrun.scoring.queue import (
    dashboard_ordered_cards,
    load_schema_weights,
    ordered_cards,
)
from speedrun.scoring.readiness import (
    MIN_ATTEMPTS as READINESS_MIN_ATTEMPTS,
    MIN_COVERAGE as READINESS_MIN_COVERAGE,
    readiness_score,
)
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


def _format_ago(ts: int | None) -> str:
    """Human 'time since' for a score's last_updated epoch seconds."""
    if not ts:
        return "unknown"
    delta = max(0, int(time.time()) - int(ts))
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


def _updated_meta(ts: int | None) -> str:
    """The 'last updated: <when>' line the PRD (§10) requires on every score."""
    return f"<div class='sr-meta sr-updated'>last updated: {_esc(_format_ago(ts))}</div>"


def _perf_confidence(coverage: float | None, n_attempts: int) -> str:
    """Confidence label for the performance score, mirroring readiness thresholds."""
    if coverage is None:
        return "low"
    if coverage >= 0.8 and n_attempts >= 400:
        return "high"
    if coverage >= 0.5 and n_attempts >= 100:
        return "medium"
    return "low"


def _mem_confidence(coverage: float | None, n_reviewed: int) -> str:
    """Confidence label ("how sure") for the memory score.

    Mirrors the performance/readiness confidence shape so all three cards carry a
    comparable badge (PRD §10): more exam covered + more reviewed cards => surer."""
    if coverage is None:
        return "low"
    if coverage >= 0.8 and n_reviewed >= 100:
        return "high"
    if coverage >= 0.5 and n_reviewed >= 25:
        return "medium"
    return "low"


def _reason_meta(reason: str | None) -> str:
    """Render a score's main reason (PRD §10: 'the main reasons behind it').

    Shown on every card when a number is displayed, so the evidence behind the
    number is always on screen next to it."""
    if not reason:
        return ""
    return f"<div class='sr-meta sr-reason'>{_esc(reason)}</div>"


def _giveup_meta(text: str) -> str:
    """Render a score's give-up rule so it is always falsifiable on screen.

    PRD §1/§10: the rule that would withhold the number must be visible even when
    a number *is* shown, so a reader can always check it against the evidence."""
    return f"<div class='sr-meta sr-giveup'>Give-up rule: {_esc(text)}</div>"


_MEMORY_GIVEUP = f"no score until \u2265 {MIN_REVIEWED_OVERALL} reviewed cards."
_PERFORMANCE_GIVEUP = (
    f"no score until \u2265 {MIN_ATTEMPTS_OVERALL} graded transfer attempts."
)
_READINESS_GIVEUP = (
    f"no score until \u2265 {READINESS_MIN_ATTEMPTS} graded attempts and "
    f"\u2265 {READINESS_MIN_COVERAGE:.0%} coverage of each of LR and RC "
    "(deck and attempts)."
)


_DASHBOARD_CSS = """
:root {
  --bg: #f4f5fb; --surface: #ffffff; --surface-2: #f7f8fd; --text: #1a1c2b;
  --muted: #656b81; --border: #e6e8f2; --accent: #5b57d1; --accent-soft: rgba(91,87,209,0.10);
  --abstain: #9aa1b5; --low: #e0415a; --med: #e08c1f; --high: #0ca678; --warn: #bb5a10;
  --bar-bg: #e8eaf4;
  --shadow: 0 1px 2px rgba(26,28,43,0.05), 0 4px 14px rgba(26,28,43,0.06);
  --shadow-lg: 0 8px 30px rgba(26,28,43,0.10);
  --radius: 14px;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0e0f1a; --surface: #181a29; --surface-2: #1e2133; --text: #e7e9f5;
    --muted: #9aa0b8; --border: #2a2e45; --accent: #8f8cf0; --accent-soft: rgba(143,140,240,0.16);
    --abstain: #7f869c; --low: #f0577a; --med: #f0a63d; --high: #2dd4a0; --warn: #e08544;
    --bar-bg: #242840;
    --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 4px 16px rgba(0,0,0,0.35);
    --shadow-lg: 0 10px 34px rgba(0,0,0,0.5);
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); }
.sr-dash { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  background: var(--bg); color: var(--text); padding: 28px 28px 40px; line-height: 1.5;
  max-width: 1040px; margin: 0 auto; -webkit-font-smoothing: antialiased; }
.sr-header { margin-bottom: 22px; }
.sr-header h1 { margin: 0 0 6px; font-size: 1.7rem; font-weight: 800; letter-spacing: -0.02em; }
.sr-header p { margin: 0; color: var(--muted); font-size: 0.88rem; max-width: 70ch; }
.sr-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 16px; margin-bottom: 22px; }
.sr-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 18px 20px; box-shadow: var(--shadow); position: relative; overflow: hidden;
  transition: transform .15s ease, box-shadow .15s ease; }
.sr-card::before { content: ""; position: absolute; top: 0; left: 0; right: 0; height: 4px;
  background: var(--border); }
.sr-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-lg); }
.sr-card.state-abstain::before { background: var(--abstain); }
.sr-card.state-low::before { background: var(--low); }
.sr-card.state-medium::before { background: var(--med); }
.sr-card.state-high::before { background: var(--high); }
.sr-card-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.sr-card-head h2 { margin: 0; font-size: 0.72rem; text-transform: uppercase;
  letter-spacing: 0.08em; color: var(--muted); font-weight: 700; }
.sr-value { font-size: 2.3rem; font-weight: 800; line-height: 1.05; margin: 6px 0 2px;
  letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
.sr-value.abstain { color: var(--abstain); font-size: 1.15rem; font-weight: 700; letter-spacing: 0; }
.sr-range, .sr-meta { font-size: 0.82rem; color: var(--muted); }
.sr-meta { margin-top: 10px; }
.sr-warn { margin-top: 10px; padding: 7px 11px; border-radius: 8px;
  background: rgba(224,140,31,0.13); color: var(--warn); font-size: 0.8rem; font-weight: 500; }
.badge { display: inline-block; padding: 3px 9px; border-radius: 999px;
  font-size: 0.66rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; }
.badge-high { background: rgba(12,166,120,0.15); color: var(--high); }
.badge-med { background: rgba(224,140,31,0.15); color: var(--med); }
.badge-low { background: rgba(154,161,181,0.2); color: var(--muted); }
.sr-section { margin-top: 30px; }
.sr-section h3 { margin: 0 0 12px; font-size: 1.02rem; font-weight: 700; letter-spacing: -0.01em;
  display: flex; align-items: center; gap: 9px; }
.sr-section h3::before { content: ""; width: 4px; height: 1.05em; border-radius: 3px;
  background: var(--accent); opacity: 0.85; }
.sr-table-wrap { overflow-x: auto; border-radius: 12px; border: 1px solid var(--border);
  box-shadow: var(--shadow); }
table.sr-table { width: 100%; border-collapse: collapse; font-size: 0.83rem; background: var(--surface); }
table.sr-table th { text-align: left; padding: 10px 14px; background: var(--surface-2);
  color: var(--muted); font-weight: 700; cursor: pointer; white-space: nowrap;
  font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; }
table.sr-table th:hover { color: var(--text); }
table.sr-table td { padding: 9px 14px; border-top: 1px solid var(--border); }
table.sr-table tbody tr:hover { background: var(--surface-2); }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.heat-bar { height: 8px; border-radius: 999px; background: var(--bar-bg); overflow: hidden; min-width: 64px; }
.heat-fill { height: 100%; border-radius: 999px; transition: width .3s ease; }
.heat-fill.weak { background: var(--low); }
.heat-fill.mid { background: var(--med); }
.heat-fill.strong { background: var(--high); }
.sr-timeline { display: flex; align-items: flex-end; gap: 5px; height: 84px; padding: 8px 0 22px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding-left: 12px; padding-right: 12px; box-shadow: var(--shadow); }
.sr-timeline-bar { flex: 1; min-width: 12px; border-radius: 5px 5px 0 0;
  background: linear-gradient(var(--accent), var(--accent-soft)); opacity: 0.9; position: relative; }
.sr-timeline-bar:hover { opacity: 1; }
.sr-timeline-bar span { position: absolute; bottom: -18px; left: 50%; transform: translateX(-50%);
  font-size: 0.6rem; color: var(--muted); white-space: nowrap; }
.sr-queue-item { display: flex; align-items: center; gap: 12px; padding: 12px 14px;
  border-bottom: 1px solid var(--border); font-size: 0.84rem; }
.sr-queue-item:hover { background: var(--surface-2); }
.sr-queue-item:last-child { border-bottom: none; }
.sr-tag { font-size: 0.74rem; padding: 3px 9px; border-radius: 7px; background: var(--accent-soft);
  color: var(--text); max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sr-schema-cell { display: inline-block; line-height: 1.3; }
.sr-schema-label { display: block; font-weight: 600; }
.sr-schema-id { display: block; font-size: 0.68rem; color: var(--muted);
  font-family: ui-monospace, monospace; margin-top: 1px; }
.sr-schema-compact { font-size: inherit; font-weight: 600; }
.sr-priority { margin-left: auto; font-weight: 800; color: var(--accent); font-variant-numeric: tabular-nums; }
.sr-empty { color: var(--muted); font-size: 0.85rem; padding: 18px; text-align: center;
  background: var(--surface); border: 1px dashed var(--border); border-radius: 12px; }
.goal-bar { background: var(--bar-bg); height: 10px; border-radius: 999px; margin-top: 10px; max-width: 300px; }
.goal-fill { background: linear-gradient(90deg, var(--high), #3fdda4); height: 10px; border-radius: 999px;
  transition: width .3s ease; }
.sr-gate { border: 1px solid var(--border); border-radius: var(--radius); padding: 18px 20px;
  margin-bottom: 22px; background: var(--surface); box-shadow: var(--shadow);
  border-left: 5px solid var(--warn); }
.sr-gate.open { border-left-color: var(--high); }
.sr-gate-head { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }
.sr-gate-head h3 { margin: 0; font-size: 1.05rem; font-weight: 800; }
.sr-gate-status { font-size: 0.68rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.06em;
  padding: 3px 11px; border-radius: 999px; }
.sr-gate-status.locked { background: rgba(187,90,16,0.15); color: var(--warn); }
.sr-gate-status.open { background: rgba(12,166,120,0.15); color: var(--high); }
.sr-gate-reason { color: var(--muted); font-size: 0.84rem; margin-bottom: 14px; }
.sr-reqs { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
.sr-req { font-size: 0.78rem; }
.sr-req-head { display: flex; justify-content: space-between; margin-bottom: 5px; }
.sr-req-head .met { color: var(--high); font-weight: 700; } .sr-req-head .unmet { color: var(--warn); font-weight: 700; }
.req-bar { background: var(--bar-bg); height: 7px; border-radius: 999px; overflow: hidden; }
.req-fill { height: 7px; border-radius: 999px; transition: width .3s ease; }
.req-fill.ok { background: var(--high); } .req-fill.no { background: var(--warn); }
.sr-signals { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px;
  margin-bottom: 22px; }
.sr-signals .sr-trap-banner { margin-bottom: 0; }
.sr-trap-banner { border: 1px solid var(--border); border-left: 4px solid var(--accent);
  border-radius: 12px; padding: 13px 16px; margin-bottom: 18px; background: var(--surface);
  font-size: 0.85rem; box-shadow: var(--shadow); }
.sr-trap-banner b { color: var(--accent); }
.sr-map { position: relative; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); overflow: hidden; box-shadow: var(--shadow); }
.sr-map-toolbar { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; padding: 12px 16px; border-bottom: 1px solid var(--border); font-size: 0.78rem; color: var(--muted); background: var(--surface-2); }
.sr-map-legend { display: flex; gap: 12px; flex-wrap: wrap; }
.sr-map-legend span { display: inline-flex; align-items: center; gap: 5px; }
.sr-dot { width: 11px; height: 11px; border-radius: 50%; display: inline-block; }
.sr-dot.strong { background: var(--high); } .sr-dot.learning { background: var(--med); }
.sr-dot.weak { background: var(--low); } .sr-dot.untested { background: var(--abstain); }
.sr-map-hint { margin-left: auto; }
.sr-map-svg { display: block; width: 100%; height: 520px; cursor: grab; background:
  radial-gradient(circle at 50% 40%, rgba(91,87,209,0.05), transparent 70%); }
.sr-map.active .sr-map-svg:active { cursor: grabbing; }
.sr-map:not(.active) .sr-map-svg { cursor: default; }
/* Click-to-interact lock: covers the graph so page scroll/clicks don't zoom or
   pan it until the user explicitly clicks to activate. Hidden once active. */
.sr-map-lock { position: absolute; inset: 0; z-index: 5; display: flex; align-items: center;
  justify-content: center; cursor: pointer; background: rgba(30,27,75,0.03); }
.sr-map.active .sr-map-lock { display: none; }
.sr-map-lock span { background: var(--surface); border: 1px solid var(--border); border-radius: 999px;
  padding: 8px 16px; font-size: 0.8rem; font-weight: 600; color: var(--text); box-shadow: var(--shadow);
  opacity: 0; transition: opacity .12s ease; }
.sr-map:hover .sr-map-lock span { opacity: 1; }
.sr-map-svg .edge { stroke: var(--border); stroke-opacity: 0.55; }
.sr-map-svg .edge.shared { stroke: var(--accent); stroke-opacity: 0.4; }
.sr-map-svg .edge.dim { stroke-opacity: 0.08; }
.sr-map-svg .edge.hot { stroke: var(--accent); stroke-opacity: 0.9; }
.sr-map-svg .node { cursor: pointer; stroke: var(--surface); stroke-width: 1.5; }
.sr-map-svg .node.strong { fill: var(--high); } .sr-map-svg .node.learning { fill: var(--med); }
.sr-map-svg .node.weak { fill: var(--low); } .sr-map-svg .node.untested { fill: var(--abstain); }
.sr-map-svg .node.chronic { fill: var(--low); } .sr-map-svg .node.shaky { fill: var(--med); }
.sr-map-svg .node.occasional { fill: var(--high); }
.sr-map-svg .edge.corr { stroke: var(--low); stroke-opacity: 0.45; }
.sr-map-svg .edge.corr.hot { stroke: var(--low); stroke-opacity: 0.95; }
.sr-map-svg .node.dim { opacity: 0.2; } .sr-map-svg .node.sel { stroke: var(--text); stroke-width: 2.5; }
.sr-map-svg .glabel { fill: var(--muted); font-size: 10px; font-weight: 600; text-anchor: middle;
  pointer-events: none; opacity: 0.75; }
.sr-map-svg .nlabel { fill: var(--text); font-size: 9px; text-anchor: middle; pointer-events: none; }
.sr-map-panel { position: absolute; top: 54px; right: 12px; width: 220px; background: var(--surface);
  border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; font-size: 0.8rem;
  box-shadow: 0 6px 22px rgba(0,0,0,0.18); display: none; }
.sr-map-panel.show { display: block; }
.sr-map-panel h4 { margin: 0 0 4px; font-size: 0.9rem; }
.sr-map-panel .pill { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 0.68rem;
  font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 8px; }
.sr-map-panel .pill.strong { background: rgba(12,166,120,0.15); color: var(--high); }
.sr-map-panel .pill.learning { background: rgba(224,140,31,0.15); color: var(--med); }
.sr-map-panel .pill.weak { background: rgba(224,65,90,0.15); color: var(--low); }
.sr-map-panel .pill.untested { background: rgba(154,161,181,0.2); color: var(--muted); }
.sr-map-panel .pill.chronic { background: rgba(224,65,90,0.15); color: var(--low); }
.sr-map-panel .pill.shaky { background: rgba(224,140,31,0.15); color: var(--med); }
.sr-map-panel .pill.occasional { background: rgba(12,166,120,0.15); color: var(--high); }
.sr-map-panel dl { margin: 0; display: grid; grid-template-columns: auto 1fr; gap: 2px 10px; }
.sr-map-panel dt { color: var(--muted); } .sr-map-panel dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; }
.sr-map-panel .nbrs { margin-top: 8px; color: var(--muted); font-size: 0.72rem; }
.sr-map-empty { padding: 40px 16px; text-align: center; color: var(--muted); font-size: 0.85rem; }
@media (max-width: 600px) { .sr-dash { padding: 16px 14px; } .sr-grid { grid-template-columns: 1fr; }
  .sr-signals { grid-template-columns: 1fr; }
  .sr-map-panel { position: static; width: auto; margin: 10px; } .sr-map-svg { height: 420px; } }
/* Quick-launch nav: one button per Speedrun feature, styled with the shared
   palette so it matches the rest of the dashboard. */
.sr-launcher { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px; margin-bottom: 24px; }
.sr-launch-group { background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 14px 16px; box-shadow: var(--shadow); }
.sr-launch-group-title { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted); font-weight: 700; margin-bottom: 10px; }
.sr-launch-btns { display: flex; flex-direction: column; gap: 8px; }
.sr-launch-btn { display: flex; flex-direction: column; align-items: flex-start; gap: 1px;
  text-align: left; cursor: pointer; font-family: inherit; width: 100%;
  border: 1px solid var(--border); background: var(--surface-2); color: var(--text);
  border-radius: 10px; padding: 9px 12px;
  transition: transform .12s ease, border-color .12s ease, box-shadow .12s ease; }
.sr-launch-btn:hover { transform: translateY(-1px); border-color: var(--accent); box-shadow: var(--shadow); }
.sr-launch-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.sr-launch-label { font-weight: 700; font-size: 0.9rem; }
.sr-launch-desc { font-size: 0.72rem; color: var(--muted); }
/* Calibration reliability chart: a small predicted-vs-actual scatter with a
   y=x reference line. Lightweight inline SVG, no external deps. */
.sr-calib-chart { display: flex; gap: 18px; flex-wrap: wrap; align-items: flex-start; margin-top: 8px; }
.sr-reliability { border: 1px solid var(--border); border-radius: 10px; background: var(--surface-2); }
.sr-reliability .diag { stroke: var(--muted); stroke-dasharray: 4 3; stroke-width: 1; opacity: 0.6; }
.sr-reliability .axis { stroke: var(--border); stroke-width: 1; }
.sr-reliability .pt { fill: var(--accent); fill-opacity: 0.75; }
.sr-reliability .plabel { fill: var(--muted); font-size: 9px; }
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

// ---- Quick-launch buttons: each posts a namespaced command back to Python over
// the pycmd bridge. When rendered outside the app (no bridge) the buttons are
// inert, so the dashboard still renders fine in a plain browser / export. ----
document.querySelectorAll('.sr-launch-btn[data-cmd]').forEach(function (b) {
  b.addEventListener('click', function () {
    if (typeof pycmd === 'function') pycmd(b.dataset.cmd);
  });
});

// ---- Click-to-interact gate: a graph only zooms/pans/drags after the user
// clicks it. The lock overlay sits on top and absorbs wheel/click while
// inactive, so page scrolling never zooms the map unintentionally. Moving the
// pointer off the map, clicking elsewhere, or Escape re-locks it. ----
function srMapGate(holder) {
  if (!holder) return function () { return false; };
  const lock = holder.querySelector('.sr-map-lock');
  function activate() { holder.classList.add('active'); }
  function deactivate() { holder.classList.remove('active'); }
  if (lock) lock.addEventListener('click', activate);
  holder.addEventListener('mouseleave', deactivate);
  document.addEventListener('mousedown', function (ev) {
    if (!holder.contains(ev.target)) deactivate();
  });
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape') deactivate();
  });
  return function () { return holder.classList.contains('active'); };
}

// ---- Concept map: self-contained force-directed graph (no external libs) ----
function srConceptMap() {
  const holder = document.getElementById('sr-concept');
  if (!holder) return;
  const isActive = srMapGate(holder);
  const data = JSON.parse(document.getElementById('sr-concept-data').textContent);
  const svg = holder.querySelector('svg');
  const gEdges = svg.querySelector('.edges');
  const gNodes = svg.querySelector('.nodes');
  const gLabels = svg.querySelector('.glabels');
  const panel = holder.querySelector('.sr-map-panel');
  const W = 900, H = 520;
  const nodes = data.nodes.map(n => Object.assign({}, n));
  const byId = {}; nodes.forEach((n, i) => { n.i = i; byId[n.id] = n; });
  const edges = data.edges
    .map(e => ({ s: byId[e.source], t: byId[e.target], w: e.weight, kind: e.kind }))
    .filter(e => e.s && e.t);

  // Seed positions in a circle per group so clusters start apart.
  const groups = {};
  nodes.forEach(n => { (groups[n.group] = groups[n.group] || []).push(n); });
  const gkeys = Object.keys(groups);
  const gCenter = {};
  gkeys.forEach((g, gi) => {
    const a = (gi / gkeys.length) * Math.PI * 2;
    gCenter[g] = { x: W / 2 + Math.cos(a) * 250, y: H / 2 + Math.sin(a) * 200 };
  });
  nodes.forEach(n => {
    const c = gCenter[n.group];
    n.x = c.x + (Math.random() - 0.5) * 80;
    n.y = c.y + (Math.random() - 0.5) * 80;
    n.vx = 0; n.vy = 0;
    n.r = Math.max(7, Math.min(26, 7 + Math.sqrt(n.cards) * 4));
  });

  // Interaction state (declared before the simulation because step() reads it).
  let dragged = null, panning = false, last = null;

  // Force simulation.
  const K_REPULSE = 5200, K_SPRING = 0.02, SPRING_LEN = 62, K_GROUP = 0.015, DAMP = 0.85;
  function step() {
    for (let a = 0; a < nodes.length; a++) {
      for (let b = a + 1; b < nodes.length; b++) {
        const p = nodes[a], q = nodes[b];
        let dx = p.x - q.x, dy = p.y - q.y;
        let d2 = dx * dx + dy * dy || 0.01;
        const f = K_REPULSE / d2;
        const d = Math.sqrt(d2);
        const ux = dx / d, uy = dy / d;
        p.vx += ux * f; p.vy += uy * f; q.vx -= ux * f; q.vy -= uy * f;
      }
    }
    edges.forEach(e => {
      let dx = e.t.x - e.s.x, dy = e.t.y - e.s.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const f = K_SPRING * (d - SPRING_LEN) * (e.kind === 'shared' ? 1.4 : 0.7);
      const ux = dx / d, uy = dy / d;
      e.s.vx += ux * f; e.s.vy += uy * f; e.t.vx -= ux * f; e.t.vy -= uy * f;
    });
    nodes.forEach(n => {
      const c = gCenter[n.group];
      n.vx += (c.x - n.x) * K_GROUP + (W / 2 - n.x) * 0.002;
      n.vy += (c.y - n.y) * K_GROUP + (H / 2 - n.y) * 0.002;
      if (n === dragged) return;
      n.vx *= DAMP; n.vy *= DAMP;
      n.x += n.vx; n.y += n.vy;
      n.x = Math.max(24, Math.min(W - 24, n.x));
      n.y = Math.max(24, Math.min(H - 24, n.y));
    });
  }
  for (let i = 0; i < 320; i++) step();

  // Render.
  const SVGNS = 'http://www.w3.org/2000/svg';
  const edgeEls = edges.map(e => {
    const l = document.createElementNS(SVGNS, 'line');
    l.setAttribute('class', 'edge ' + e.kind);
    l.setAttribute('stroke-width', e.kind === 'shared' ? Math.min(4, 1 + e.w * 0.6) : 1);
    gEdges.appendChild(l); e.el = l; return e;
  });
  gkeys.forEach(g => {
    const t = document.createElementNS(SVGNS, 'text');
    t.setAttribute('class', 'glabel');
    t.textContent = (groups[g][0].group_label || g);
    gLabels.appendChild(t); gCenter[g].el = t;
  });
  const nodeEls = nodes.map(n => {
    const c = document.createElementNS(SVGNS, 'circle');
    c.setAttribute('class', 'node ' + n.status);
    c.setAttribute('r', n.r);
    const tt = document.createElementNS(SVGNS, 'title');
    tt.textContent = n.label + '  (' + n.status + ')';
    c.appendChild(tt);
    gNodes.appendChild(c); n.el = c;
    const lab = document.createElementNS(SVGNS, 'text');
    lab.setAttribute('class', 'nlabel');
    lab.textContent = n.short_label.replace(/^[^·]*· /, '');
    lab.style.display = 'none';
    gLabels.appendChild(lab); n.lab = lab;
    return n;
  });
  const adj = {}; nodes.forEach(n => adj[n.id] = new Set());
  edges.forEach(e => { adj[e.s.id].add(e.t.id); adj[e.t.id].add(e.s.id); });

  function paint() {
    edgeEls.forEach(e => {
      e.el.setAttribute('x1', e.s.x); e.el.setAttribute('y1', e.s.y);
      e.el.setAttribute('x2', e.t.x); e.el.setAttribute('y2', e.t.y);
    });
    nodeEls.forEach(n => {
      n.el.setAttribute('cx', n.x); n.el.setAttribute('cy', n.y);
      n.lab.setAttribute('x', n.x); n.lab.setAttribute('y', n.y - n.r - 3);
    });
    gkeys.forEach(g => {
      let mx = 0, my = 1e9;
      groups[g].forEach(n => { mx += n.x; my = Math.min(my, n.y); });
      gCenter[g].el.setAttribute('x', mx / groups[g].length);
      gCenter[g].el.setAttribute('y', my - 14);
    });
  }
  paint();

  // Pan + zoom via viewBox.
  let vb = { x: 0, y: 0, w: W, h: H };
  function applyVB() { svg.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.w} ${vb.h}`); }
  applyVB();
  svg.addEventListener('wheel', ev => {
    if (!isActive()) return;  // let the page scroll until the map is activated
    ev.preventDefault();
    const scale = ev.deltaY > 0 ? 1.1 : 0.9;
    const pt = svgPoint(ev);
    vb.x = pt.x - (pt.x - vb.x) * scale;
    vb.y = pt.y - (pt.y - vb.y) * scale;
    vb.w *= scale; vb.h *= scale; applyVB();
  }, { passive: false });

  function svgPoint(ev) {
    const r = svg.getBoundingClientRect();
    return { x: vb.x + (ev.clientX - r.left) / r.width * vb.w,
             y: vb.y + (ev.clientY - r.top) / r.height * vb.h };
  }

  function selectNode(n) {
    const on = adj[n.id];
    nodeEls.forEach(m => {
      m.el.classList.toggle('dim', m !== n && !on.has(m.id));
      m.el.classList.toggle('sel', m === n);
      m.lab.style.display = (m === n || on.has(m.id)) ? '' : 'none';
    });
    edgeEls.forEach(e => {
      const hot = e.s === n || e.t === n;
      e.el.classList.toggle('hot', hot);
      e.el.classList.toggle('dim', !hot);
    });
    const pct = v => v == null ? '—' : Math.round(v * 100) + '%';
    panel.innerHTML =
      '<h4>' + esc(n.label) + '</h4>' +
      '<span class="pill ' + n.status + '">' + n.status + '</span>' +
      '<dl>' +
      '<dt>Group</dt><dd>' + esc(n.group_label) + '</dd>' +
      '<dt>Strength</dt><dd>' + pct(n.strength) + '</dd>' +
      '<dt>Memory</dt><dd>' + pct(n.memory) + '</dd>' +
      '<dt>Performance</dt><dd>' + pct(n.performance) + '</dd>' +
      '<dt>Accuracy</dt><dd>' + pct(n.accuracy) + '</dd>' +
      '<dt>Cards</dt><dd>' + n.cards + '</dd>' +
      '<dt>Reviews</dt><dd>' + n.reviews + '</dd>' +
      '</dl>' +
      '<div class="nbrs">Linked to ' + on.size + ' related concept' + (on.size === 1 ? '' : 's') + '. Click empty space to reset.</div>';
    panel.classList.add('show');
  }
  function clearSel() {
    nodeEls.forEach(m => { m.el.classList.remove('dim', 'sel'); m.lab.style.display = 'none'; });
    edgeEls.forEach(e => e.el.classList.remove('hot', 'dim'));
    panel.classList.remove('show');
  }
  function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

  nodeEls.forEach(n => {
    n.el.addEventListener('mousedown', ev => { if (!isActive()) return; ev.stopPropagation(); dragged = n; last = svgPoint(ev); });
    n.el.addEventListener('click', ev => { ev.stopPropagation(); selectNode(n); });
  });
  svg.addEventListener('mousedown', ev => { if (!isActive()) return; panning = true; last = svgPoint(ev); });
  svg.addEventListener('click', () => { if (!dragged) clearSel(); });
  window.addEventListener('mousemove', ev => {
    if (dragged) { const p = svgPoint(ev); dragged.x = p.x; dragged.y = p.y; dragged.vx = 0; dragged.vy = 0; paint(); }
    else if (panning) { const p = svgPoint(ev); vb.x -= (p.x - last.x); vb.y -= (p.y - last.y); applyVB(); }
  });
  window.addEventListener('mouseup', () => { dragged = null; panning = false; });

  // Keep cooling gently after interaction for a settled feel.
  let ticks = 0;
  (function anneal() { if (ticks++ < 120) { step(); paint(); requestAnimationFrame(anneal); } })();
}
srConceptMap();

function srMistakeGraph() {
  const holder = document.getElementById('sr-mistake');
  if (!holder) return;
  const isActive = srMapGate(holder);
  const data = JSON.parse(document.getElementById('sr-mistake-data').textContent);
  const svg = holder.querySelector('svg');
  const gEdges = svg.querySelector('.edges');
  const gNodes = svg.querySelector('.nodes');
  const gLabels = svg.querySelector('.glabels');
  const panel = holder.querySelector('.sr-map-panel');
  const W = 900, H = 520;
  const nodes = data.nodes.map(n => Object.assign({}, n));
  const byId = {}; nodes.forEach((n, i) => { n.i = i; byId[n.id] = n; });
  const edges = data.edges
    .map(e => ({ s: byId[e.source], t: byId[e.target], w: e.weight, co: e.co_miss, kind: e.kind }))
    .filter(e => e.s && e.t);

  const groups = {};
  nodes.forEach(n => { (groups[n.group] = groups[n.group] || []).push(n); });
  const gkeys = Object.keys(groups);
  const gCenter = {};
  gkeys.forEach((g, gi) => {
    const a = (gi / gkeys.length) * Math.PI * 2;
    gCenter[g] = { x: W / 2 + Math.cos(a) * 250, y: H / 2 + Math.sin(a) * 200 };
  });
  nodes.forEach(n => {
    const c = gCenter[n.group];
    n.x = c.x + (Math.random() - 0.5) * 80;
    n.y = c.y + (Math.random() - 0.5) * 80;
    n.vx = 0; n.vy = 0;
    n.r = Math.max(7, Math.min(26, 7 + Math.sqrt(n.misses) * 4));
  });

  let dragged = null, panning = false, last = null;
  const K_REPULSE = 5200, K_SPRING = 0.02, SPRING_LEN = 62, K_GROUP = 0.015, DAMP = 0.85;
  function step() {
    for (let a = 0; a < nodes.length; a++) {
      for (let b = a + 1; b < nodes.length; b++) {
        const p = nodes[a], q = nodes[b];
        let dx = p.x - q.x, dy = p.y - q.y;
        let d2 = dx * dx + dy * dy || 0.01;
        const f = K_REPULSE / d2;
        const d = Math.sqrt(d2);
        const ux = dx / d, uy = dy / d;
        p.vx += ux * f; p.vy += uy * f; q.vx -= ux * f; q.vy -= uy * f;
      }
    }
    edges.forEach(e => {
      let dx = e.t.x - e.s.x, dy = e.t.y - e.s.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const f = K_SPRING * (d - SPRING_LEN) * (0.7 + e.w);
      const ux = dx / d, uy = dy / d;
      e.s.vx += ux * f; e.s.vy += uy * f; e.t.vx -= ux * f; e.t.vy -= uy * f;
    });
    nodes.forEach(n => {
      const c = gCenter[n.group];
      n.vx += (c.x - n.x) * K_GROUP + (W / 2 - n.x) * 0.002;
      n.vy += (c.y - n.y) * K_GROUP + (H / 2 - n.y) * 0.002;
      if (n === dragged) return;
      n.vx *= DAMP; n.vy *= DAMP;
      n.x += n.vx; n.y += n.vy;
      n.x = Math.max(24, Math.min(W - 24, n.x));
      n.y = Math.max(24, Math.min(H - 24, n.y));
    });
  }
  for (let i = 0; i < 320; i++) step();

  const SVGNS = 'http://www.w3.org/2000/svg';
  const edgeEls = edges.map(e => {
    const l = document.createElementNS(SVGNS, 'line');
    l.setAttribute('class', 'edge ' + e.kind);
    l.setAttribute('stroke-width', Math.min(5, 1 + e.w * 4));
    gEdges.appendChild(l); e.el = l; return e;
  });
  gkeys.forEach(g => {
    const t = document.createElementNS(SVGNS, 'text');
    t.setAttribute('class', 'glabel');
    t.textContent = (groups[g][0].group_label || g);
    gLabels.appendChild(t); gCenter[g].el = t;
  });
  const nodeEls = nodes.map(n => {
    const c = document.createElementNS(SVGNS, 'circle');
    c.setAttribute('class', 'node ' + n.status);
    c.setAttribute('r', n.r);
    const tt = document.createElementNS(SVGNS, 'title');
    tt.textContent = n.label + '  (' + Math.round(n.miss_rate * 100) + '% miss rate)';
    c.appendChild(tt);
    gNodes.appendChild(c); n.el = c;
    const lab = document.createElementNS(SVGNS, 'text');
    lab.setAttribute('class', 'nlabel');
    lab.textContent = n.short_label.replace(/^[^·]*· /, '');
    lab.style.display = 'none';
    gLabels.appendChild(lab); n.lab = lab;
    return n;
  });
  const adj = {}; nodes.forEach(n => adj[n.id] = new Set());
  const wById = {}; nodes.forEach(n => wById[n.id] = []);
  edges.forEach(e => {
    adj[e.s.id].add(e.t.id); adj[e.t.id].add(e.s.id);
    wById[e.s.id].push({ id: e.t.id, w: e.w }); wById[e.t.id].push({ id: e.s.id, w: e.w });
  });

  function paint() {
    edgeEls.forEach(e => {
      e.el.setAttribute('x1', e.s.x); e.el.setAttribute('y1', e.s.y);
      e.el.setAttribute('x2', e.t.x); e.el.setAttribute('y2', e.t.y);
    });
    nodeEls.forEach(n => {
      n.el.setAttribute('cx', n.x); n.el.setAttribute('cy', n.y);
      n.lab.setAttribute('x', n.x); n.lab.setAttribute('y', n.y - n.r - 3);
    });
    gkeys.forEach(g => {
      let mx = 0, my = 1e9;
      groups[g].forEach(n => { mx += n.x; my = Math.min(my, n.y); });
      gCenter[g].el.setAttribute('x', mx / groups[g].length);
      gCenter[g].el.setAttribute('y', my - 14);
    });
  }
  paint();

  let vb = { x: 0, y: 0, w: W, h: H };
  function applyVB() { svg.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.w} ${vb.h}`); }
  applyVB();
  svg.addEventListener('wheel', ev => {
    if (!isActive()) return;  // let the page scroll until the map is activated
    ev.preventDefault();
    const scale = ev.deltaY > 0 ? 1.1 : 0.9;
    const pt = svgPoint(ev);
    vb.x = pt.x - (pt.x - vb.x) * scale;
    vb.y = pt.y - (pt.y - vb.y) * scale;
    vb.w *= scale; vb.h *= scale; applyVB();
  }, { passive: false });
  function svgPoint(ev) {
    const r = svg.getBoundingClientRect();
    return { x: vb.x + (ev.clientX - r.left) / r.width * vb.w,
             y: vb.y + (ev.clientY - r.top) / r.height * vb.h };
  }

  function selectNode(n) {
    const on = adj[n.id];
    nodeEls.forEach(m => {
      m.el.classList.toggle('dim', m !== n && !on.has(m.id));
      m.el.classList.toggle('sel', m === n);
      m.lab.style.display = (m === n || on.has(m.id)) ? '' : 'none';
    });
    edgeEls.forEach(e => {
      const hot = e.s === n || e.t === n;
      e.el.classList.toggle('hot', hot);
      e.el.classList.toggle('dim', !hot);
    });
    const pct = v => v == null ? '—' : Math.round(v * 100) + '%';
    const linked = (wById[n.id] || []).slice().sort((a, b) => b.w - a.w).slice(0, 3)
      .map(x => esc((byId[x.id].short_label || x.id).replace(/^[^·]*· /, '')) + ' (' + pct(x.w) + ')')
      .join(', ');
    panel.innerHTML =
      '<h4>' + esc(n.label) + '</h4>' +
      '<span class="pill ' + n.status + '">' + n.status + '</span>' +
      '<dl>' +
      '<dt>Group</dt><dd>' + esc(n.group_label) + '</dd>' +
      '<dt>Miss rate</dt><dd>' + pct(n.miss_rate) + '</dd>' +
      '<dt>Misses</dt><dd>' + n.misses + '</dd>' +
      '<dt>Attempts</dt><dd>' + n.attempts + '</dd>' +
      '</dl>' +
      '<div class="nbrs">' + (on.size
        ? 'Most correlated: ' + linked + '. Click empty space to reset.'
        : 'No correlated mistakes yet. Click empty space to reset.') + '</div>';
    panel.classList.add('show');
  }
  function clearSel() {
    nodeEls.forEach(m => { m.el.classList.remove('dim', 'sel'); m.lab.style.display = 'none'; });
    edgeEls.forEach(e => e.el.classList.remove('hot', 'dim'));
    panel.classList.remove('show');
  }
  function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

  nodeEls.forEach(n => {
    n.el.addEventListener('mousedown', ev => { if (!isActive()) return; ev.stopPropagation(); dragged = n; last = svgPoint(ev); });
    n.el.addEventListener('click', ev => { ev.stopPropagation(); selectNode(n); });
  });
  svg.addEventListener('mousedown', ev => { if (!isActive()) return; panning = true; last = svgPoint(ev); });
  svg.addEventListener('click', () => { if (!dragged) clearSel(); });
  window.addEventListener('mousemove', ev => {
    if (dragged) { const p = svgPoint(ev); dragged.x = p.x; dragged.y = p.y; dragged.vx = 0; dragged.vy = 0; paint(); }
    else if (panning) { const p = svgPoint(ev); vb.x -= (p.x - last.x); vb.y -= (p.y - last.y); applyVB(); }
  });
  window.addEventListener('mouseup', () => { dragged = null; panning = false; });

  let ticks = 0;
  (function anneal() { if (ticks++ < 120) { step(); paint(); requestAnimationFrame(anneal); } })();
}
srMistakeGraph();
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
        return (
            '<div class="heat-bar"><div class="heat-fill" style="width:0"></div></div>'
        )
    pct = max(0, min(100, int(value * 100)))
    cls = "weak" if pct < 40 else ("mid" if pct < 70 else "strong")
    return f'<div class="heat-bar"><div class="heat-fill {cls}" style="width:{pct}%"></div></div>'


def _memory_card(result: dict[str, Any], *, exam_coverage: float | None = None) -> str:
    o = result["overall"]
    state = _score_state(o.gave_up, o.point)
    # "How sure" badge (PRD §10) — mirrors performance/readiness. Uses the same
    # exam-coverage source the readiness/coverage panel uses (not the old
    # cards-reviewed/deck-cards ratio, which is not exam coverage).
    confidence = _mem_confidence(exam_coverage, o.n_reviewed)
    badge = "" if o.gave_up else _confidence_badge(confidence)
    if o.gave_up:
        # When abstaining, the reason IS the headline; no separate reason line.
        val = f'<div class="sr-value abstain">No score</div><div class="sr-range">{_esc(o.reason)}</div>'
        reason = ""
    else:
        val = f'<div class="sr-value">{o.point:.0%}</div><div class="sr-range">likely {_pct(o.low)}–{_pct(o.high)} recall</div>'
        reason = _reason_meta(o.reason)
    cov_txt = "—" if exam_coverage is None else f"{exam_coverage:.0%}"
    meta = (
        f"<div class='sr-meta'>reviewed {o.n_reviewed}/{o.n_cards} · "
        f"exam covered {cov_txt} · FSRS</div>"
    )
    return (
        f'<div class="sr-card state-{state}"><div class="sr-card-head"><h2>Memory</h2>{badge}</div>'
        f"{val}{reason}{meta}{_giveup_meta(_MEMORY_GIVEUP)}"
        f"{_updated_meta(o.last_updated)}</div>"
    )


def _performance_card(
    result: dict[str, Any], *, gate: Any = None, best_next_step: str | None = None
) -> str:
    o = result["overall"]
    state = _score_state(o.gave_up, o.point)
    # Coverage % and a confidence indicator, mirroring the readiness card. The
    # performance/transfer signal only speaks to as much of the taxonomy as has
    # been practiced, so we surface that reach honestly.
    coverage = getattr(gate, "concept_coverage", None) if gate is not None else None
    confidence = _perf_confidence(coverage, o.n_attempts)
    badge = "" if o.gave_up else _confidence_badge(confidence)
    if o.gave_up:
        val = f'<div class="sr-value abstain">No score</div><div class="sr-range">{_esc(o.reason)}</div>'
        reason = ""
    else:
        val = f'<div class="sr-value">{o.point:.0%}</div><div class="sr-range">likely {_pct(o.low)}–{_pct(o.high)} transfer</div>'
        reason = _reason_meta(o.reason)
    warn = (
        '<div class="sr-warn">Accurate but slow — would lose points on the clock.</div>'
        if o.speed_flag
        else ""
    )
    # Best next step is the weakest high-value schema to drill — sensible on the
    # transfer card too (not only Readiness), since that is exactly what would
    # raise the transfer number fastest (PRD §10).
    next_step = (
        f"<div class='sr-meta'>Best next: {schema_display_html(best_next_step)}</div>"
        if (best_next_step and not o.gave_up)
        else ""
    )
    sub = f"{o.n_attempts} attempts"
    if coverage is not None:
        sub += f" · coverage {coverage:.0%}"
    if o.raw_accuracy is not None:
        sub += f" · raw {_pct(o.raw_accuracy)}"
    if o.on_budget_rate is not None:
        sub += f" · on-budget {_pct(o.on_budget_rate)}"
    lr, rc = latency_budget_ms("LR") // 1000, latency_budget_ms("RC") // 1000
    sub += f" · budgets LR {lr}s / RC {rc}s"
    return (
        f'<div class="sr-card state-{state}"><div class="sr-card-head"><h2>Performance</h2>{badge}</div>'
        f'{val}{warn}{reason}{next_step}<div class="sr-meta">{sub}</div>'
        f"{_giveup_meta(_PERFORMANCE_GIVEUP)}{_updated_meta(o.last_updated)}</div>"
    )


def _readiness_card(result: Any) -> str:
    state = _score_state(result.gave_up, result.point, lsat=True)
    if result.gave_up:
        val = f'<div class="sr-value abstain">No score</div><div class="sr-range">{_esc(result.reason)}</div>'
        reason = ""
    else:
        val = f'<div class="sr-value">{result.point:.0f}</div><div class="sr-range">likely {result.low:.0f}–{result.high:.0f} LSAT</div>'
        reason = _reason_meta(result.reason)
    warn = (
        '<div class="sr-warn">Latency penalty applied.</div>'
        if result.speed_flag
        else ""
    )
    next_step = (
        f"<div class='sr-meta'>Best next: {schema_display_html(result.best_next_step)}</div>"
        if result.best_next_step
        else ""
    )
    # Per-section coverage makes the give-up rule falsifiable on screen: a deck
    # that skips a section reads e.g. "LR 62% · RC 0%" so the abstention is
    # self-explaining (PRD §8.3/§10).
    section_meta = ""
    section_cov = getattr(result, "section_coverage", None)
    if section_cov:
        parts = " · ".join(f"{s} {c:.0%}" for s, c in sorted(section_cov.items()))
        section_meta = f"<div class='sr-meta'>section coverage: {_esc(parts)}</div>"
    return (
        f'<div class="sr-card state-{state}"><div class="sr-card-head"><h2>Readiness</h2>'
        f"{_confidence_badge(result.confidence)}</div>{val}{warn}{reason}{next_step}"
        f"<div class='sr-meta'>coverage {result.coverage:.0%} · {result.n_attempts} attempts</div>"
        f"{section_meta}"
        f"{_giveup_meta(_READINESS_GIVEUP)}"
        f"{_updated_meta(result.last_updated)}</div>"
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


def _schema_table(
    table_id: str, rows: list[dict[str, Any]], *, score_label: str
) -> str:
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
    colors = {
        "solid": "var(--high)",
        "weak": "var(--low)",
        "learning": "var(--med)",
        "untested": "var(--muted)",
    }
    rows = ""
    for m in items[:20]:
        c = colors.get(m.status, "var(--muted)")
        mem = "—" if m.memory is None else f"{m.memory:.0%}"
        perf = "—" if m.performance is None else f"{m.performance:.0%}"
        rows += f"<tr><td>{schema_display_html(m.schema)}</td><td style='color:{c}'>{_esc(m.status)}</td><td class='num'>{mem}</td><td class='num'>{perf}</td></tr>"
    extra = (
        f'<div class="sr-meta">+ {len(items) - 20} more</div>'
        if len(items) > 20
        else ""
    )
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
        rows = "".join(
            f"<tr><td>{_esc(b.label)}</td><td class='num'>{b.count}</td><td class='num'>{b.pct:.0%}</td></tr>"
            for b in buckets
        )
        parts.append(
            f"<h4>{section}</h4><div class='sr-table-wrap'><table class='sr-table'><tbody>{rows}</tbody></table></div>"
        )
    if not parts:
        return ""
    return f'<div class="sr-section"><h3>Latency histogram</h3>{"".join(parts)}</div>'


def _trajectory_table(col) -> str:
    points = [
        p
        for p in readiness_trajectory(col, days=30)
        if not p.gave_up and p.projected is not None
    ]
    if not points:
        return ""
    rows = "".join(
        f"<tr><td>{_esc(p.day)}</td><td class='num'>{p.projected:.0f}</td><td class='num'>{p.low:.0f}–{p.high:.0f}</td></tr>"
        for p in points[-10:]
    )
    return (
        f'<div class="sr-section"><h3>Readiness trajectory</h3>'
        f"<div class='sr-table-wrap'><table class='sr-table'><thead><tr>"
        f"<th>day</th><th class='num'>projected</th><th class='num'>range</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></div>"
    )


def _queue_html(col, *, limit: int = 8, search: str | None = None) -> str:
    try:
        # The dashboard preview (no explicit search) uses the pruned fast path,
        # which returns the identical top-`limit` without ranking all 50k cards.
        if search is None:
            cards = dashboard_ordered_cards(col, limit=limit)
        else:
            cards = ordered_cards(col, limit=limit, search=search)
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


def _gate_panel(gate: Any) -> str:
    """Render the evidence gate: what's practiced vs. required before any score."""
    status_cls = "open" if gate.open else "locked"
    status_txt = "Open" if gate.open else "Locked"
    reqs = ""
    for r in gate.requirements:
        met_cls = "met" if r.met else "unmet"
        if r.is_fraction:
            have_txt, need_txt = f"{r.have:.0%}", f"{r.need:.0%}"
            pct = 100 if r.need == 0 else min(100, int(100 * r.have / r.need))
        else:
            have_txt, need_txt = f"{int(r.have)}", f"{int(r.need)}"
            pct = 100 if r.need == 0 else min(100, int(100 * r.have / r.need))
        fill_cls = "ok" if r.met else "no"
        reqs += (
            f'<div class="sr-req"><div class="sr-req-head"><span>{_esc(r.label)}</span>'
            f'<span class="{met_cls}">{have_txt} / {need_txt}</span></div>'
            f'<div class="req-bar"><div class="req-fill {fill_cls}" style="width:{pct}%"></div></div></div>'
        )
    return (
        f'<div class="sr-gate {"open" if gate.open else ""}">'
        f'<div class="sr-gate-head"><h3>Evidence gate</h3>'
        f'<span class="sr-gate-status {status_cls}">{status_txt}</span></div>'
        f'<div class="sr-gate-reason">{_esc(gate.reason)}</div>'
        f'<div class="sr-reqs">{reqs}</div></div>'
    )


def _trap_banner(col) -> str:
    """Headline the student's most habitual trap (SPOV2 first-class diagnostic)."""
    habits = trap_profile(col, top_n=3)
    if not habits:
        return ""
    top = habits[0]
    rest = ""
    if len(habits) > 1:
        rest = " · then " + ", ".join(
            f"{schema_display_html('trap.' + h.trap if not h.trap.startswith('trap.') else h.trap, compact=True)} ({h.pct:.0%})"
            for h in habits[1:]
        )
    top_id = top.trap if top.trap.startswith("trap.") else "trap." + top.trap
    return (
        f'<div class="sr-trap-banner">Habitual trap: '
        f"<b>{schema_display_html(top_id, compact=True)}</b> — you fall for it "
        f"{top.pct:.0%} of your misses{rest}. Flaws & traps are the unit of mastery (SPOV2).</div>"
    )


def _contrast_practice_banner() -> str:
    """Report contrasting-pairs practice. Honesty rule: self-ratings are training
    signal only and are NOT part of the memory/performance/readiness scores."""
    from speedrun.contrasting import contrasting_practice_summary

    s = contrasting_practice_summary()
    if not s["n"]:
        return ""
    transfer = "—" if s["transfer"] is None else f"{s['transfer']:.0%}"
    return (
        f'<div class="sr-trap-banner">Contrasting-pairs practice: '
        f"<b>{s['n']}</b> pairs · self-rated transfer <b>{transfer}</b> "
        f"({s['got_it']} got it · {s['partial']} partial · {s['missed']} missed). "
        f"Comparison builds schema abstraction (SPOV1); this is training signal, not a score.</div>"
    )


def _cold_open_practice_banner() -> str:
    """Report predict-the-schema cold-open practice. Honesty rule: these self-driven
    grades are diagnostic signal only and are NOT part of the scores. Schema-ID
    accuracy is shown separately from answer accuracy so the transfer gap is visible."""
    from speedrun.cold_open import cold_open_summary

    s = cold_open_summary()
    if not s["n"]:
        return ""
    schema = "—" if s["schema_accuracy"] is None else f"{s['schema_accuracy']:.0%}"
    answer = "—" if s["answer_accuracy"] is None else f"{s['answer_accuracy']:.0%}"
    gap = s["transfer_gap"]
    gap_txt = "" if gap is None else f" · transfer gap {gap:+.0%}"
    return (
        f'<div class="sr-trap-banner">Cold-open predictions: '
        f"<b>{s['n']}</b> items · schema-ID accuracy <b>{schema}</b> vs "
        f"answer accuracy <b>{answer}</b>{gap_txt}. "
        f"Naming the flaw from the stimulus alone is the transfer skill (SPOV1); "
        f"diagnostic only, not a score.</div>"
    )


def _calibration_banner() -> str:
    """Confidence-calibration summary. Honesty rule: training signal, not a score.
    Surfaces the schema where the student's certainty is most misplaced."""
    from speedrun.confidence_calibration import calibration_summary

    s = calibration_summary()
    if not s["n"] or s["gave_up"]:
        return ""
    over = s["overconfidence"]
    direction = "overconfident" if over and over > 0 else "well-calibrated"
    worst = (
        f" Most misplaced certainty: <b>{_esc(s['most_overconfident'])}</b>."
        if s["most_overconfident"]
        else ""
    )
    return (
        f'<div class="sr-trap-banner">Confidence calibration: '
        f"<b>{s['n']}</b> judged decisions · Brier <b>{s['brier']:.2f}</b> · "
        f"<b>{over:+.0%}</b> ({direction}).{worst} "
        f"Confidence rarely tracks accuracy (Karpicke &amp; Roediger); training signal, not a score.</div>"
    )


def _fork_practice_banner() -> str:
    """Report two-answer fork practice. Honesty rule: training signal only, never
    part of the scores. Fork accuracy is the SPOV3 metric (the final binary
    decision); trap-ID accuracy and pacing are shown beside it (Insight 8, SPOV4)."""
    from speedrun.fork_trainer import fork_summary

    s = fork_summary()
    if not s["n"]:
        return ""
    fork = "—" if s["fork_accuracy"] is None else f"{s['fork_accuracy']:.0%}"
    trap = "—" if s["trap_id_accuracy"] is None else f"{s['trap_id_accuracy']:.0%}"
    pace = ""
    if s["avg_latency_ms"] is not None:
        pace = f" · avg decision {s['avg_latency_ms'] / 1000:.0f}s"
        if s["in_budget_rate"] is not None:
            pace += f" ({s['in_budget_rate']:.0%} in budget)"
    missed = ""
    if s["missed_traps"]:
        worst = s["missed_traps"][0]
        missed = f" Most mis-named trap: <b>{_esc(worst['label'])}</b>."
    return (
        f'<div class="sr-trap-banner">Two-answer forks: '
        f"<b>{s['n']}</b> decisions · fork accuracy <b>{fork}</b> · "
        f"trap-ID accuracy <b>{trap}</b>{pace}.{missed} "
        f"The final two-answer decision is where points are won (SPOV3); "
        f"training signal only, not a score.</div>"
    )


def _signals_grid() -> str:
    """Lay the four training-signal banners into a clean responsive grid.

    Each banner already abstains (returns "") when it has no data, so the grid
    only appears once the student has generated some practice signal."""
    banners = [
        _contrast_practice_banner(),
        _cold_open_practice_banner(),
        _fork_practice_banner(),
        _calibration_banner(),
    ]
    present = [b for b in banners if b]
    if not present:
        return ""
    return f'<div class="sr-signals">{"".join(present)}</div>'


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
    return _shell(
        f'<div class="sr-header"><h1>Speedrun settings</h1></div>{body}',
        title="Settings",
    )


def _concept_map_section(col, *, heading: bool = True) -> str:
    """Interactive concept map of every schema the student has practiced."""
    graph = build_concept_graph(col)
    head = "<h3>Concept map</h3>" if heading else ""
    if not graph.nodes:
        return (
            f'<div class="sr-section">{head}'
            f'<div class="sr-map"><div class="sr-map-empty">'
            f"Complete some flashcards to start building your concept map. "
            f"Each schema you practice becomes a node; similar problems link together."
            f"</div></div></div>"
        )
    s = graph.stats
    # Raw JSON in a <script type="application/json"> block: its content is CDATA-like
    # so HTML entities are NOT decoded (escaping would break JSON.parse). Only guard
    # against a "</script>" breakout by neutralizing "<".
    data_json = json.dumps(graph.to_dict()).replace("<", "\\u003c")
    legend = (
        '<div class="sr-map-legend">'
        '<span><i class="sr-dot strong"></i>Strong</span>'
        '<span><i class="sr-dot learning"></i>Learning</span>'
        '<span><i class="sr-dot weak"></i>Weak</span>'
        '<span><i class="sr-dot untested"></i>Untested</span>'
        "</div>"
    )
    summary = (
        f"{s['n_nodes']} concepts · {s['n_groups']} families · "
        f'<b style="color:var(--high)">{s["strong"]} strong</b> · '
        f'<b style="color:var(--low)">{s["weak"]} weak</b>'
    )
    hint = (
        '<span class="sr-map-hint">Click the map to interact · then drag / scroll to '
        "zoom · move away to lock</span>"
    )
    return (
        f'<div class="sr-section">{head}'
        f'<div class="sr-map" id="sr-concept">'
        f'<div class="sr-map-toolbar">{legend}<span>{summary}</span>{hint}</div>'
        f'<svg class="sr-map-svg" viewBox="0 0 900 520" preserveAspectRatio="xMidYMid meet">'
        f'<g class="edges"></g><g class="glabels"></g><g class="nodes"></g></svg>'
        f'<div class="sr-map-panel"></div>'
        f'<div class="sr-map-lock"><span>Click to interact</span></div>'
        f'<script type="application/json" id="sr-concept-data">{data_json}</script>'
        f"</div></div>"
    )


def render_concept_map_html(col) -> str:
    body = (
        '<div class="sr-header"><h1>Concept map</h1>'
        "<p>Every schema you have practiced, grouped by similar problems. "
        "Green is strong, red is weak — traverse from what you know into the gaps.</p></div>"
        f"{_concept_map_section(col, heading=False)}"
    )
    return _shell(body, title="Concept map")


def _mistake_graph_section(col, *, heading: bool = True) -> str:
    """Interactive graph of the schemas the student gets wrong, edges linking
    mistakes that tend to happen together (correlation)."""
    graph = build_mistake_graph(col)
    head = "<h3>Mistake graph</h3>" if heading else ""
    if not graph.nodes:
        return (
            f'<div class="sr-section">{head}'
            f'<div class="sr-map"><div class="sr-map-empty">'
            f"No mistakes recorded yet — miss a few cards (answer <b>Again</b>) and "
            f"this graph will map which flaws and traps you tend to get wrong together."
            f"</div></div></div>"
        )
    s = graph.stats
    # Raw JSON in a <script type="application/json"> block (see concept map note).
    data_json = json.dumps(graph.to_dict()).replace("<", "\\u003c")
    legend = (
        '<div class="sr-map-legend">'
        '<span><i class="sr-dot weak"></i>Chronic</span>'
        '<span><i class="sr-dot learning"></i>Shaky</span>'
        '<span><i class="sr-dot strong"></i>Occasional</span>'
        "</div>"
    )
    corr = "day" if s["bucket_mode"] == "day" else "sitting"
    summary = (
        f"{s['n_nodes']} mistake types · {s['total_misses']} misses · "
        f'<b style="color:var(--low)">{s["chronic"]} chronic</b> · '
        f"{s['n_edges']} correlations (by {corr})"
    )
    hint = (
        '<span class="sr-map-hint">Click the map to interact · then drag / scroll to '
        "zoom · move away to lock</span>"
    )
    return (
        f'<div class="sr-section">{head}'
        f'<div class="sr-map" id="sr-mistake">'
        f'<div class="sr-map-toolbar">{legend}<span>{summary}</span>{hint}</div>'
        f'<svg class="sr-map-svg" viewBox="0 0 900 520" preserveAspectRatio="xMidYMid meet">'
        f'<g class="edges"></g><g class="glabels"></g><g class="nodes"></g></svg>'
        f'<div class="sr-map-panel"></div>'
        f'<div class="sr-map-lock"><span>Click to interact</span></div>'
        f'<script type="application/json" id="sr-mistake-data">{data_json}</script>'
        f"</div></div>"
    )


def render_mistake_graph_html(col) -> str:
    body = (
        '<div class="sr-header"><h1>Mistake graph</h1>'
        "<p>Only the schemas you get wrong, sized by how often you miss them and "
        "linked when you tend to miss them together. Red is chronic, green is "
        "occasional — hunt for the clusters and remediate a whole cluster at once.</p></div>"
        f"{_mistake_graph_section(col, heading=False)}"
    )
    return _shell(body, title="Mistake graph")


# Ordered spec for the dashboard quick-launch nav. This is the single source of
# truth for the button keys; the aqt bridge (`qt/aqt/speedrun/__init__.py`) maps
# the same keys to the existing menu handlers, so features are never duplicated.
# Each entry is (key, label, description). Keys are namespaced on the wire as
# ``speedrun:open:<key>``.
LAUNCHER_GROUPS: list[tuple[str, list[tuple[str, str, str]]]] = [
    (
        "Drills",
        [
            ("study_now", "Study now", "enter the reviewer"),
            ("study_all", "Study all", "uncapped — grind everything"),
            ("study_queue", "Study queue", "schema-weighted order"),
            ("focus", "Focus / by subject", "drill one question-type or schema"),
            ("schema_drill", "Schema drill", "weakest schemas first"),
            ("contrasting_pairs", "Contrasting pairs", "compare & contrast"),
            ("cold_open", "Cold-open", "predict the schema"),
            ("two_answer_fork", "Two-answer fork", "split the final two"),
        ],
    ),
    (
        "AI",
        [
            ("study_next", "Study next", "AI: what to study next"),
            ("ai_tutor", "AI Tutor", "ask about a problem"),
            ("ai_settings", "AI Settings", "enable & configure"),
        ],
    ),
    (
        "Insights",
        [
            ("dashboard", "Refresh", "reload this dashboard"),
            ("scores", "Scores", "readiness report"),
        ],
    ),
    (
        "Deck",
        [
            ("import_seed", "Import seed deck", "load the problems"),
            ("export", "Export report", "offline HTML"),
        ],
    ),
]

# Flat, ordered list of every launcher key (used by the bridge + tests).
LAUNCHER_KEYS: list[str] = [
    key for _group, buttons in LAUNCHER_GROUPS for (key, _label, _desc) in buttons
]


def _launcher_section() -> str:
    """A grid of accessible <button>s, one per Speedrun feature. Each button
    carries a ``data-cmd`` of ``speedrun:open:<key>`` that the dashboard JS relays
    over the pycmd bridge to the same handlers the Tools menu uses."""
    groups_html = ""
    for group_label, buttons in LAUNCHER_GROUPS:
        btns = ""
        for key, label, desc in buttons:
            cmd = f"speedrun:open:{key}"
            btns += (
                f'<button type="button" class="sr-launch-btn" data-cmd="{_esc(cmd)}" '
                f'aria-label="{_esc(label)} — {_esc(desc)}">'
                f'<span class="sr-launch-label">{_esc(label)}</span>'
                f'<span class="sr-launch-desc">{_esc(desc)}</span></button>'
            )
        groups_html += (
            f'<div class="sr-launch-group" role="group" '
            f'aria-label="{_esc(group_label)}">'
            f'<div class="sr-launch-group-title">{_esc(group_label)}</div>'
            f'<div class="sr-launch-btns">{btns}</div></div>'
        )
    return (
        '<nav class="sr-launcher" aria-label="Speedrun feature launcher">'
        f"{groups_html}</nav>"
    )


def _recommender_panel(col) -> str:
    """The AI "what to study next" section, grounded in the student's scores.

    Delegates to :mod:`speedrun.ai.recommender` (lazy import to keep the module
    graph acyclic and the AI package importable without Qt). Degrades to empty."""
    try:
        from speedrun.ai.recommender import render_recommender_panel

        return render_recommender_panel(col)
    except Exception:  # pragma: no cover - defensive
        return ""


def _reliability_chart(bins: list[Any]) -> str:
    """A small inline-SVG reliability chart: mean predicted (x) vs mean actual (y)
    per bin, with a y=x reference line. Perfect calibration sits on the diagonal.

    Reuses the calibration report's bins (the same data the separate report
    tabulates) so the scores screen shows the chart §10.1/§17 asks for without a
    heavy charting dependency. Marker area grows with the bin's sample count."""
    if not bins:
        return ""
    size, pad = 200, 26
    span = size - 2 * pad

    def px(v: float) -> float:
        return pad + max(0.0, min(1.0, v)) * span

    def py(v: float) -> float:
        return size - pad - max(0.0, min(1.0, v)) * span

    axes = (
        f'<line class="axis" x1="{px(0)}" y1="{py(0)}" x2="{px(1)}" y2="{py(0)}"/>'
        f'<line class="axis" x1="{px(0)}" y1="{py(0)}" x2="{px(0)}" y2="{py(1)}"/>'
    )
    diag = f'<line class="diag" x1="{px(0)}" y1="{py(0)}" x2="{px(1)}" y2="{py(1)}"/>'
    pts = ""
    for b in bins:
        cx, cy = px(b.mean_predicted), py(b.mean_actual)
        r = max(3.0, min(9.0, 2.0 + b.n**0.5))
        pts += (
            f'<circle class="pt" cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}">'
            f"<title>predicted {b.mean_predicted:.0%} → actual {b.mean_actual:.0%} "
            f"(n={b.n})</title></circle>"
        )
    labels = (
        f'<text class="plabel" x="{px(0.5):.1f}" y="{size - 6}" '
        f'text-anchor="middle">predicted →</text>'
        f'<text class="plabel" x="9" y="{py(0.5):.1f}" text-anchor="middle" '
        f'transform="rotate(-90 9 {py(0.5):.1f})">actual →</text>'
    )
    return (
        f'<svg class="sr-reliability" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}" role="img" '
        f'aria-label="Reliability chart: predicted versus actual recall by bin">'
        f"{axes}{diag}{pts}{labels}</svg>"
    )


def _calibration_score_panel(col) -> str:
    """Memory-model calibration shown inline with the three scores.

    The honesty rule (§10) forbids a readiness score without, on the same screen,
    how accurate past predictions turned out to be. This surfaces the calibration
    summary (Brier / log loss on the held-out slice, from speedrun.eval.calibration)
    AND a small reliability chart (§10.1/§17) next to Readiness rather than only
    as a separate report."""
    from speedrun.eval.calibration import calibration_report

    r = calibration_report(col)
    if r.gave_up:
        body = f'<p class="sr-meta">No calibration yet — {_esc(r.reason)}</p>'
    else:
        chart = _reliability_chart(r.bins)
        text = (
            f"<div><p><b>Brier {r.brier:.3f}</b> · log loss {r.log_loss:.3f} · "
            f"{r.n_held_out} held-out reviews (of {r.n_total}).</p>"
            f'<p class="sr-meta">{_esc(r.reason)}</p>'
            '<p class="sr-meta">Reliability chart: each dot is a confidence bin; '
            "dots on the dashed diagonal are perfectly calibrated.</p></div>"
        )
        body = f'<div class="sr-calib-chart">{chart}{text}</div>'
    return (
        '<div class="sr-section sr-calib"><h3>Calibration — memory model</h3>'
        '<p class="sr-meta">When the model says 80%, recall should be ≈80%. '
        "Shown beside Readiness so a score never appears without its track record "
        "(honesty rule §10).</p>"
        f"{body}</div>"
    )


def _transfer_gap_panel(col) -> str:
    """Surface the recall-vs-transfer gap on the main dashboard (§1/§3 SPOV1/§17).

    The single most important metric is the gap between "can recall this card" and
    "can answer a NEW question with this structure": if they are equal, we have a
    memory app in an LSAT costume. It lived only in a separate menu report; this
    puts the number on the dashboard. Read-only use of speedrun.eval.transfer_gap;
    computed inside the memoized body so it stays covered by the render cache."""
    try:
        from speedrun.eval.transfer_gap import transfer_gap_report

        r = transfer_gap_report(col)
    except Exception:  # pragma: no cover - defensive
        return ""
    if r.gave_up or r.gap is None:
        body = f'<p class="sr-meta">{_esc(r.reason)}</p>'
    else:
        body = (
            f"<p>Recall <b>{r.recall_point:.0%}</b> vs transfer "
            f"<b>{r.reworded_point:.0%}</b> · gap <b>{r.gap:+.0%}</b> "
            f'<span class="sr-meta">(source: {_esc(r.source)}; '
            f"bridge distinct: {r.bridge_distinct}).</span></p>"
            '<p class="sr-meta">If recall ≈ transfer the bridge is not built '
            "(SPOV1). A positive gap means memory overstates transfer.</p>"
        )
    return (
        '<div class="sr-section sr-transfer"><h3>Recall vs transfer gap</h3>'
        f"{body}</div>"
    )


def _deck_coverage_panel(col) -> str:
    """Deck coverage of the LSAT taxonomy + how much the student has practiced.

    Uses the coverage_map module (§8.3). Below the coverage line the app abstains
    from a readiness score; this panel makes the number visible on the dashboard."""
    try:
        from speedrun.tools.coverage_map import (
            DEFAULT_DECK,
            DEFAULT_TAXONOMY,
            build_report,
            load_json,
        )

        taxonomy = load_json(DEFAULT_TAXONOMY)
        deck = load_json(DEFAULT_DECK)
        report = build_report(taxonomy, deck)
    except Exception:
        return ""

    from speedrun.scoring.performance import collection_attempts

    tax_ids = {s["id"] for s in taxonomy.get("schemas", [])}
    seen = {a.schema for a in collection_attempts(col)} & tax_ids
    seen_pct = (len(seen) / len(tax_ids)) if tax_ids else 0.0

    overall = report["overall_count_coverage"]
    sections = " · ".join(
        f"{name} {s['schemas_covered']}/{s['schemas_total']} ({s['count_coverage']:.0%})"
        for name, s in report["per_section"].items()
    )
    return (
        '<div class="sr-section sr-coverage"><h3>Deck coverage</h3>'
        f"<p>Deck covers <b>{overall:.0%}</b> of the taxonomy "
        f"({report['schemas_covered']}/{report['schemas_total']} schemas) · "
        f"you have practiced <b>{seen_pct:.0%}</b> of it.</p>"
        f'<p class="sr-meta">By section: {_esc(sections)}. '
        "Below the coverage line the app abstains from a readiness score (§8.3).</p></div>"
    )


def _dashboard_body(col, *, timeline_days: int = 14) -> str:
    """Assemble the dashboard body (everything inside ``.sr-dash``).

    Memoized by :func:`render_dashboard_html` on the collection-state token so a
    refresh with unchanged state re-serves the identical body near-instantly,
    while any review (which changes the token) forces a fresh, correct render."""
    gate = evidence_gate(col)
    mem = memory_score(col, gate=gate)
    perf = performance_score(col, gate=gate)
    ready = readiness_score(col, gate=gate)
    perf_rows = _perf_schema_rows(perf)
    mode = "schema-weighted" if interleaving_enabled() else "plain Anki due"
    filt = section_filter()
    body = (
        f'<div class="sr-header"><h1>LSAT Speedrun</h1>'
        f"<p>Three separate scores with ranges. Queue: {mode}{' · ' + filt if filt else ''}. "
        f"Launch any exercise from the buttons below, or use the "
        f"<b>Tools → LSAT Speedrun</b> menu / Ctrl+Shift+L.</p></div>"
        f"{_launcher_section()}"
        f"{_gate_panel(gate)}"
        f"{_recommender_panel(col)}"
        f'<div class="sr-grid">{_goal_card(col)}'
        f"{_memory_card(mem, exam_coverage=ready.coverage)}"
        f"{_performance_card(perf, gate=gate, best_next_step=ready.best_next_step)}"
        f"{_readiness_card(ready)}</div>"
        f"{_calibration_score_panel(col)}"
        f"{_transfer_gap_panel(col)}"
        f"{_deck_coverage_panel(col)}"
        f"{_trap_banner(col)}"
        f"{_signals_grid()}"
        f"{_weakness_heatmap(perf_rows)}"
        f"{_concept_map_section(col)}"
        f"{_mistake_graph_section(col)}"
        f'<div class="sr-section"><h3>Schema breakdown — memory</h3>{_schema_table("mem-table", _mem_schema_rows(mem), score_label="recall")}</div>'
        f'<div class="sr-section"><h3>Schema breakdown — performance</h3>{_schema_table("perf-table", perf_rows, score_label="transfer")}</div>'
        f"{_timeline_chart(col, days=timeline_days)}{_mastery_table(col)}{_wrong_patterns_table(col)}"
        f"{_latency_table(col)}{_trajectory_table(col)}"
        f'<div class="sr-section"><h3>Next up — schema-weighted queue</h3>{_queue_html(col)}</div>'
    )
    return body


def render_dashboard_html(
    col, *, timeline_days: int = 14, embed: bool = False
) -> str:
    from speedrun.score_cache import cached

    body = cached(
        col,
        f"dashboard_body::{timeline_days}",
        lambda: _dashboard_body(col, timeline_days=timeline_days),
    )
    if embed:
        # Body-only markup for the AnkiWebView/pycmd bridge path (mirrors the
        # tutor's embed shape): inline the stylesheet + script around the body.
        return (
            f"<style>{_DASHBOARD_CSS}</style>"
            f'<div class="sr-dash">{body}</div>'
            f"<script>{_DASHBOARD_JS}</script>"
        )
    return _shell(body)


def render_study_list_html(col, *, limit: int = 20, heading: bool = True) -> str:
    title = (
        '<div class="sr-header"><h1>Schema-weighted queue</h1></div>' if heading else ""
    )
    return _shell(
        title + f'<div class="sr-section">{_queue_html(col, limit=limit)}</div>',
        title="Queue",
    )


def render_report_html(col, *, title: str, body_html: str) -> str:
    return _shell(
        f'<div class="sr-header"><h1>{_esc(title)}</h1></div>{body_html}', title=title
    )


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
    gate = evidence_gate(col)
    mem = memory_score(col, gate=gate)
    # Same exam-coverage source the readiness card/coverage panel uses, so the
    # memory card shows exam coverage (not the cards-reviewed ratio).
    ready = readiness_score(col, gate=gate)
    body = (
        _gate_panel(gate)
        + _memory_card(mem, exam_coverage=ready.coverage)
        + _schema_table("mem-rpt", _mem_schema_rows(mem), score_label="recall")
    )
    return render_report_html(col, title="Memory report", body_html=body)


def render_performance_report_html(col) -> str:
    gate = evidence_gate(col)
    perf = performance_score(col, gate=gate)
    ready = readiness_score(col, gate=gate)
    body = (
        _gate_panel(gate)
        + _performance_card(perf, gate=gate, best_next_step=ready.best_next_step)
        + _schema_table("perf-rpt", _perf_schema_rows(perf), score_label="transfer")
    )
    return render_report_html(col, title="Performance report", body_html=body)


def render_readiness_report_html(col) -> str:
    gate = evidence_gate(col)
    body = (
        _gate_panel(gate)
        + _readiness_card(readiness_score(col, gate=gate))
        + _calibration_score_panel(col)
    )
    return render_report_html(col, title="Readiness report", body_html=body)


def export_dashboard_html(col, path: str | None = None) -> str:
    from pathlib import Path

    from speedrun.export import render_full_export_html

    html_out = render_full_export_html(col)
    if path:
        Path(path).write_text(html_out, encoding="utf-8")
    return html_out


def dashboard_summary(col) -> dict[str, str]:
    gate = evidence_gate(col)
    mem = memory_score(col, gate=gate)["overall"]
    perf = performance_score(col, gate=gate)["overall"]
    ready = readiness_score(col, gate=gate)

    def fmt(gave_up: bool, point: float | None, *, lsat: bool = False) -> str:
        if gave_up or point is None:
            return "—"
        return f"{point:.0f}" if lsat else f"{point:.0%}"

    return {
        "memory": fmt(mem.gave_up, mem.point),
        "performance": fmt(perf.gave_up, perf.point),
        "readiness": fmt(ready.gave_up, ready.point, lsat=True),
    }
