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
.sr-gate { border: 1px solid var(--border); border-radius: 12px; padding: 14px 18px; margin-bottom: 18px;
  background: var(--surface); border-left: 4px solid var(--warn); }
.sr-gate.open { border-left-color: var(--high); }
.sr-gate-head { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.sr-gate-head h3 { margin: 0; font-size: 0.95rem; font-weight: 700; }
.sr-gate-status { font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
  padding: 2px 10px; border-radius: 999px; }
.sr-gate-status.locked { background: rgba(180,83,9,0.15); color: var(--warn); }
.sr-gate-status.open { background: rgba(22,163,74,0.15); color: var(--high); }
.sr-gate-reason { color: var(--muted); font-size: 0.82rem; margin-bottom: 10px; }
.sr-reqs { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 8px; }
.sr-req { font-size: 0.78rem; }
.sr-req-head { display: flex; justify-content: space-between; margin-bottom: 3px; }
.sr-req-head .met { color: var(--high); } .sr-req-head .unmet { color: var(--warn); }
.req-bar { background: var(--bar-bg); height: 6px; border-radius: 3px; overflow: hidden; }
.req-fill { height: 6px; border-radius: 3px; }
.req-fill.ok { background: var(--high); } .req-fill.no { background: var(--warn); }
.sr-trap-banner { border: 1px solid var(--border); border-left: 4px solid var(--accent); border-radius: 10px;
  padding: 10px 14px; margin-bottom: 18px; background: var(--surface); font-size: 0.85rem; }
.sr-trap-banner b { color: var(--accent); }
.sr-map { position: relative; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); overflow: hidden; }
.sr-map-toolbar { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; padding: 10px 14px; border-bottom: 1px solid var(--border); font-size: 0.78rem; color: var(--muted); }
.sr-map-legend { display: flex; gap: 12px; flex-wrap: wrap; }
.sr-map-legend span { display: inline-flex; align-items: center; gap: 5px; }
.sr-dot { width: 11px; height: 11px; border-radius: 50%; display: inline-block; }
.sr-dot.strong { background: var(--high); } .sr-dot.learning { background: var(--med); }
.sr-dot.weak { background: var(--low); } .sr-dot.untested { background: var(--abstain); }
.sr-map-hint { margin-left: auto; }
.sr-map-svg { display: block; width: 100%; height: 520px; cursor: grab; background:
  radial-gradient(circle at 50% 40%, rgba(37,99,235,0.05), transparent 70%); }
.sr-map-svg:active { cursor: grabbing; }
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
.sr-map-panel .pill.strong { background: rgba(22,163,74,0.15); color: var(--high); }
.sr-map-panel .pill.learning { background: rgba(217,119,6,0.15); color: var(--med); }
.sr-map-panel .pill.weak { background: rgba(220,38,38,0.15); color: var(--low); }
.sr-map-panel .pill.untested { background: rgba(148,163,184,0.2); color: var(--muted); }
.sr-map-panel .pill.chronic { background: rgba(220,38,38,0.15); color: var(--low); }
.sr-map-panel .pill.shaky { background: rgba(217,119,6,0.15); color: var(--med); }
.sr-map-panel .pill.occasional { background: rgba(22,163,74,0.15); color: var(--high); }
.sr-map-panel dl { margin: 0; display: grid; grid-template-columns: auto 1fr; gap: 2px 10px; }
.sr-map-panel dt { color: var(--muted); } .sr-map-panel dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; }
.sr-map-panel .nbrs { margin-top: 8px; color: var(--muted); font-size: 0.72rem; }
.sr-map-empty { padding: 40px 16px; text-align: center; color: var(--muted); font-size: 0.85rem; }
@media (max-width: 600px) { .sr-dash { padding: 14px 12px; } .sr-grid { grid-template-columns: 1fr; }
  .sr-map-panel { position: static; width: auto; margin: 10px; } .sr-map-svg { height: 420px; } }
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

// ---- Concept map: self-contained force-directed graph (no external libs) ----
function srConceptMap() {
  const holder = document.getElementById('sr-concept');
  if (!holder) return;
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
    n.el.addEventListener('mousedown', ev => { ev.stopPropagation(); dragged = n; last = svgPoint(ev); });
    n.el.addEventListener('click', ev => { ev.stopPropagation(); selectNode(n); });
  });
  svg.addEventListener('mousedown', ev => { panning = true; last = svgPoint(ev); });
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
    n.el.addEventListener('mousedown', ev => { ev.stopPropagation(); dragged = n; last = svgPoint(ev); });
    n.el.addEventListener('click', ev => { ev.stopPropagation(); selectNode(n); });
  });
  svg.addEventListener('mousedown', ev => { panning = true; last = svgPoint(ev); });
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
    warn = (
        '<div class="sr-warn">Accurate but slow — would lose points on the clock.</div>'
        if o.speed_flag
        else ""
    )
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
        '<span class="sr-map-hint">Click a node to inspect · drag to rearrange · '
        "scroll to zoom</span>"
    )
    return (
        f'<div class="sr-section">{head}'
        f'<div class="sr-map" id="sr-concept">'
        f'<div class="sr-map-toolbar">{legend}<span>{summary}</span>{hint}</div>'
        f'<svg class="sr-map-svg" viewBox="0 0 900 520" preserveAspectRatio="xMidYMid meet">'
        f'<g class="edges"></g><g class="glabels"></g><g class="nodes"></g></svg>'
        f'<div class="sr-map-panel"></div>'
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
        '<span class="sr-map-hint">Click a node to see correlated mistakes · '
        "drag to rearrange · scroll to zoom</span>"
    )
    return (
        f'<div class="sr-section">{head}'
        f'<div class="sr-map" id="sr-mistake">'
        f'<div class="sr-map-toolbar">{legend}<span>{summary}</span>{hint}</div>'
        f'<svg class="sr-map-svg" viewBox="0 0 900 520" preserveAspectRatio="xMidYMid meet">'
        f'<g class="edges"></g><g class="glabels"></g><g class="nodes"></g></svg>'
        f'<div class="sr-map-panel"></div>'
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


def render_dashboard_html(col, *, timeline_days: int = 14) -> str:
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
        f"Use <b>Tools → LSAT Speedrun → Study Now</b> or Ctrl+Shift+L for dashboard.</p></div>"
        f"{_gate_panel(gate)}"
        f'<div class="sr-grid">{_goal_card(col)}{_memory_card(mem)}{_performance_card(perf)}{_readiness_card(ready)}</div>'
        f"{_trap_banner(col)}"
        f"{_contrast_practice_banner()}"
        f"{_cold_open_practice_banner()}"
        f"{_weakness_heatmap(perf_rows)}"
        f"{_concept_map_section(col)}"
        f"{_mistake_graph_section(col)}"
        f'<div class="sr-section"><h3>Schema breakdown — memory</h3>{_schema_table("mem-table", _mem_schema_rows(mem), score_label="recall")}</div>'
        f'<div class="sr-section"><h3>Schema breakdown — performance</h3>{_schema_table("perf-table", perf_rows, score_label="transfer")}</div>'
        f"{_timeline_chart(col, days=timeline_days)}{_mastery_table(col)}{_wrong_patterns_table(col)}"
        f"{_latency_table(col)}{_trajectory_table(col)}"
        f'<div class="sr-section"><h3>Next up — schema-weighted queue</h3>{_queue_html(col)}</div>'
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
    body = (
        _gate_panel(gate)
        + _memory_card(mem)
        + _schema_table("mem-rpt", _mem_schema_rows(mem), score_label="recall")
    )
    return render_report_html(col, title="Memory report", body_html=body)


def render_performance_report_html(col) -> str:
    gate = evidence_gate(col)
    perf = performance_score(col, gate=gate)
    body = (
        _gate_panel(gate)
        + _performance_card(perf)
        + _schema_table("perf-rpt", _perf_schema_rows(perf), score_label="transfer")
    )
    return render_report_html(col, title="Performance report", body_html=body)


def render_readiness_report_html(col) -> str:
    gate = evidence_gate(col)
    body = _gate_panel(gate) + _readiness_card(readiness_score(col, gate=gate))
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
