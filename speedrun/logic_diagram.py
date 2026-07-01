# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Conditional-logic visualiser: diagram sufficient/necessary statements.

LSAT conditional reasoning is the one area where a picture beats prose: a rule
"A -> B" (A is sufficient for B; B is necessary for A) has a contrapositive
"~B -> ~A", chains compose transitively, and the two classic errors -- affirming
the consequent (mistaken *reversal*) and denying the antecedent (mistaken
*negation*) -- are exactly the ``flaw.conditional.*`` schemas in our taxonomy.

This module is a small, fully-tested logic engine plus a renderer:

* parse a compact notation ("A -> B", "A -> ~B") into ``Rule`` objects;
* build the closure (given rules + contrapositives + transitive chains) so we can
  decide whether any candidate inference is *valid*;
* classify an invalid candidate against the rules *as authored* so we can name the
  fallacy (mistaken reversal vs mistaken negation) the way the problem states it;
* lay the literals out deterministically (longest-path layering, left-to-right,
  sufficient -> necessary) so the diagram reads like a hand-drawn conditional map.

Everything here is Qt-free and pure-data; the aqt layer just drops the returned
HTML into a dialog. The visualiser is driven by the actual conditional problems in
the seed deck so the diagram is always "based on the problem".
"""

from __future__ import annotations

import html
import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------- #
# Core model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Literal:
    term: str
    negated: bool = False

    @property
    def id(self) -> str:
        return ("~" if self.negated else "") + self.term

    def negate(self) -> "Literal":
        return Literal(self.term, not self.negated)

    def label(self, terms: dict[str, str] | None = None) -> str:
        phrase = (terms or {}).get(self.term, self.term)
        return f"not {phrase}" if self.negated else phrase

    def symbol(self) -> str:
        return ("¬" if self.negated else "") + self.term


@dataclass(frozen=True)
class Rule:
    suff: Literal
    nec: Literal

    @property
    def id(self) -> str:
        return f"{self.suff.id}->{self.nec.id}"

    def contrapositive(self) -> "Rule":
        return Rule(self.nec.negate(), self.suff.negate())


def parse_literal(text: str) -> Literal:
    raw = text.strip()
    if not raw:
        raise ValueError("empty literal")
    negated = False
    while raw[:1] in ("~", "!"):
        negated = not negated
        raw = raw[1:].strip()
    if not raw:
        raise ValueError("literal has no term")
    return Literal(term=raw, negated=negated)


def parse_rule(text: str) -> Rule:
    """Parse "A -> B" / "A -> ~B" into a Rule. Accepts ->, =>, → as the arrow."""
    normalized = text.replace("=>", "->").replace("→", "->")
    if "->" not in normalized:
        raise ValueError(f"rule must contain '->': {text!r}")
    left, right = normalized.split("->", 1)
    return Rule(suff=parse_literal(left), nec=parse_literal(right))


VERDICT_VALID = "valid"
VERDICT_REVERSAL = "mistaken_reversal"
VERDICT_NEGATION = "mistaken_negation"
VERDICT_UNSUPPORTED = "unsupported"


@dataclass
class LogicModel:
    given: list[Rule]
    terms: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Closure adjacency over literal ids: given rules + their contrapositives.
        self._adj: dict[str, set[str]] = defaultdict(set)
        self._literals: dict[str, Literal] = {}
        for rule in self.given:
            for r in (rule, rule.contrapositive()):
                self._adj[r.suff.id].add(r.nec.id)
                self._literals[r.suff.id] = r.suff
                self._literals[r.nec.id] = r.nec

    def literals(self) -> list[Literal]:
        return [self._literals[k] for k in sorted(self._literals)]

    def reachable(self, source: str, target: str) -> bool:
        return bool(self.path(source, target))

    def path(self, source: str, target: str) -> list[str]:
        """Shortest chain of literal ids from source to target (inclusive), or []."""
        if source == target:
            return [source]
        seen = {source}
        queue: list[list[str]] = [[source]]
        while queue:
            chain = queue.pop(0)
            for nxt in sorted(self._adj.get(chain[-1], ())):
                if nxt == target:
                    return chain + [nxt]
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(chain + [nxt])
        return []

    def classify(self, claim: Rule) -> str:
        s, n = claim.suff.id, claim.nec.id
        if self.reachable(s, n):
            return VERDICT_VALID
        # Fallacies are matched against rules AS AUTHORED (not contrapositives),
        # so we name the error the way the problem states its rule.
        for rule in self.given:
            if rule.suff.id == n and rule.nec.id == s:
                return VERDICT_REVERSAL  # converse of a real rule
        for rule in self.given:
            if (
                rule.suff.id == claim.suff.negate().id
                and rule.nec.id == claim.nec.negate().id
            ):
                return VERDICT_NEGATION  # inverse of a real rule
        return VERDICT_UNSUPPORTED

    def explain(self, claim: Rule) -> str:
        verdict = self.classify(claim)
        s_lbl = claim.suff.label(self.terms)
        n_lbl = claim.nec.label(self.terms)
        if verdict == VERDICT_VALID:
            p = self.path(claim.suff.id, claim.nec.id)
            steps = "" if len(p) <= 2 else " (via a chain of rules)"
            return f"Valid — “{s_lbl}” guarantees “{n_lbl}”{steps}."
        if verdict == VERDICT_REVERSAL:
            return (
                f"Mistaken reversal (affirming the consequent): the rule runs "
                f"“{n_lbl}” → “{s_lbl}”, so “{s_lbl}” → “{n_lbl}” does not follow. "
                f"A sufficient condition is being treated as necessary."
            )
        if verdict == VERDICT_NEGATION:
            pos_s = claim.suff.negate().label(self.terms)
            pos_n = claim.nec.negate().label(self.terms)
            return (
                f"Mistaken negation (denying the antecedent): the rule runs "
                f"“{pos_s}” → “{pos_n}”, so negating both to “{s_lbl}” → “{n_lbl}” "
                f"does not follow. A sufficient condition is being treated as necessary."
            )
        return f"Not supported — no rule connects “{s_lbl}” to “{n_lbl}”."


# --------------------------------------------------------------------------- #
# Graph + deterministic layout
# --------------------------------------------------------------------------- #


def build_logic_graph(model: LogicModel) -> dict[str, Any]:
    """Nodes (literals) + edges (given / contrapositive / derived) + layout."""
    nodes: dict[str, Literal] = {lit.id: lit for lit in model.literals()}

    edges: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add_edge(a: str, b: str, kind: str) -> None:
        if (a, b) in seen:
            return
        seen.add((a, b))
        edges.append({"source": a, "target": b, "kind": kind})

    for rule in model.given:
        add_edge(rule.suff.id, rule.nec.id, "given")
    for rule in model.given:
        c = rule.contrapositive()
        add_edge(c.suff.id, c.nec.id, "contrapositive")

    # Derived (transitive) inferences beyond the direct edges, for chains.
    ids = list(nodes)
    for a in ids:
        for b in ids:
            if a == b or (a, b) in seen:
                continue
            p = model.path(a, b)
            if len(p) > 2:
                add_edge(a, b, "derived")

    layers, rows = _layered_layout(list(nodes), edges)

    node_list = [
        {
            "id": lit.id,
            "symbol": lit.symbol(),
            "label": lit.label(model.terms),
            "term": lit.term,
            "negated": lit.negated,
            "layer": layers[lit.id],
            "row": rows[lit.id],
        }
        for lit in nodes.values()
    ]
    n_layers = (max(layers.values()) + 1) if layers else 1
    return {"nodes": node_list, "edges": edges, "n_layers": n_layers}


def _layered_layout(
    node_ids: list[str], edges: list[dict[str, str]]
) -> tuple[dict[str, int], dict[str, int]]:
    """Longest-path layering (sufficient on the left). Cycle-safe."""
    succ: dict[str, set[str]] = defaultdict(set)
    layout_edges = [e for e in edges if e["kind"] in ("given", "contrapositive")]
    for e in layout_edges:
        succ[e["source"]].add(e["target"])

    layer = {nid: 0 for nid in node_ids}
    # Relax layer assignments; bound iterations to avoid infinite loops on cycles.
    for _ in range(len(node_ids) + 1):
        changed = False
        for e in layout_edges:
            if layer[e["target"]] < layer[e["source"]] + 1:
                layer[e["target"]] = layer[e["source"]] + 1
                changed = True
        if not changed:
            break

    rows: dict[str, int] = {}
    by_layer: dict[int, list[str]] = defaultdict(list)
    for nid in sorted(node_ids):
        by_layer[layer[nid]].append(nid)
    for members in by_layer.values():
        for i, nid in enumerate(members):
            rows[nid] = i
    return layer, rows


# --------------------------------------------------------------------------- #
# Problems (driven by the conditional seed items)
# --------------------------------------------------------------------------- #


@dataclass
class LogicProblem:
    id: str
    source_id: str
    title: str
    stimulus: str
    flaw: str
    terms: dict[str, str]
    given: list[str]
    claim: str
    note: str


# Curated conditional problems. The mistaken-reversal / mistaken-negation items are
# taken verbatim from the seed deck (clean, unambiguous translations); the chain and
# nec/suff items are authored to teach valid chaining and the nec-as-suff error.
PROBLEMS: list[LogicProblem] = [
    LogicProblem(
        id="calculus",
        source_id="lr-0002",
        title="Sufficient treated as necessary",
        stimulus=(
            "Anyone who has mastered calculus can solve these puzzles. Maria solved "
            "these puzzles, so she has mastered calculus."
        ),
        flaw="flaw.conditional.mistaken_reversal",
        terms={"M": "has mastered calculus", "P": "can solve the puzzles"},
        given=["M -> P"],
        claim="P -> M",
        note=(
            "Mastering calculus is sufficient for solving the puzzles, not required. "
            "Solving them (P) does not prove mastery (M)."
        ),
    ),
    LogicProblem(
        id="alarm",
        source_id="lr-0012",
        title="Denying the antecedent",
        stimulus=(
            "If the alarm had sounded, we would have evacuated. The alarm did not "
            "sound, so we did not need to evacuate."
        ),
        flaw="flaw.conditional.mistaken_negation",
        terms={"A": "the alarm sounds", "E": "we evacuate"},
        given=["A -> E"],
        claim="~A -> ~E",
        note=(
            "The alarm is one sufficient trigger for evacuating, not the only one. "
            "No alarm (~A) does not establish no evacuation (~E)."
        ),
    ),
    LogicProblem(
        id="scholarship",
        source_id="chain",
        title="Valid chain + contrapositive",
        stimulus=(
            "Every scholarship winner made the dean's list. Everyone on the dean's "
            "list passed all exams. So every scholarship winner passed all exams."
        ),
        flaw="",
        terms={
            "S": "won the scholarship",
            "D": "made the dean's list",
            "X": "passed all exams",
        },
        given=["S -> D", "D -> X"],
        claim="S -> X",
        note=(
            "Chaining S → D → X yields the valid inference S → X. Its contrapositive, "
            "not-X → not-S, is equally valid; try testing it."
        ),
    ),
    LogicProblem(
        id="permit",
        source_id="nec_suff",
        title="Necessary treated as sufficient",
        stimulus=(
            "To board the flight you must have a permit. Sam has a permit, so Sam "
            "will board the flight."
        ),
        flaw="flaw.conditional.nec_suff_confusion",
        terms={"B": "boards the flight", "P": "has a permit"},
        given=["B -> P"],
        claim="P -> B",
        note=(
            "A permit is necessary to board, not sufficient. Having a permit (P) does "
            "not guarantee boarding (B)."
        ),
    ),
]


def model_for(problem: LogicProblem) -> LogicModel:
    return LogicModel(
        given=[parse_rule(r) for r in problem.given], terms=problem.terms
    )


def problem_payload(problem: LogicProblem) -> dict[str, Any]:
    """Everything the client needs for one problem: graph, term key, claim, and a
    precomputed verdict+explanation for every ordered pair of literals (so the
    tester stays purely a lookup into tested Python logic)."""
    model = model_for(problem)
    graph = build_logic_graph(model)
    lits = model.literals()

    inferences: dict[str, dict[str, Any]] = {}
    for a in lits:
        for b in lits:
            if a.id == b.id:
                continue
            claim = Rule(a, b)
            verdict = model.classify(claim)
            inferences[f"{a.id}->{b.id}"] = {
                "verdict": verdict,
                "explanation": model.explain(claim),
                "path": model.path(a.id, b.id) if verdict == VERDICT_VALID else [],
            }

    claim_rule = parse_rule(problem.claim)
    return {
        "id": problem.id,
        "source_id": problem.source_id,
        "title": problem.title,
        "stimulus": problem.stimulus,
        "flaw": problem.flaw,
        "note": problem.note,
        "terms": [
            {"symbol": sym, "phrase": problem.terms[sym]}
            for sym in sorted(problem.terms)
        ],
        "given": problem.given,
        "claim": {
            "suff": claim_rule.suff.id,
            "nec": claim_rule.nec.id,
            "text": problem.claim,
        },
        "nodes": graph["nodes"],
        "edges": graph["edges"],
        "n_layers": graph["n_layers"],
        "inferences": inferences,
    }


def logic_diagram_payload(problems: list[LogicProblem] | None = None) -> dict[str, Any]:
    probs = problems if problems is not None else PROBLEMS
    return {"problems": [problem_payload(p) for p in probs]}


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _esc(text: object) -> str:
    return html.escape(str(text))


_LOGIC_CSS = """
.sr-logic { max-width: 960px; }
.sr-lg-controls { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.sr-lg-controls label { font-size: 0.8rem; color: var(--muted); font-weight: 600; }
.sr-lg-select { font-family: inherit; font-size: 0.88rem; padding: 8px 10px; border: 1px solid var(--border);
  border-radius: 8px; background: var(--bg); color: var(--text); }
.sr-lg-stim { border: 1px solid var(--border); border-left: 4px solid var(--accent); border-radius: 10px;
  background: var(--surface); padding: 12px 14px; margin-bottom: 12px; font-size: 0.92rem; line-height: 1.5; }
.sr-lg-map { position: relative; border: 1px solid var(--border); border-radius: 12px; background: var(--surface);
  overflow: hidden; margin-bottom: 12px; }
.sr-lg-legend { display: flex; gap: 16px; flex-wrap: wrap; padding: 10px 14px; border-bottom: 1px solid var(--border);
  font-size: 0.76rem; color: var(--muted); }
.sr-lg-legend span { display: inline-flex; align-items: center; gap: 6px; }
.sr-lg-legend .ln { width: 24px; height: 0; border-top: 2px solid var(--accent); display: inline-block; }
.sr-lg-legend .ln.contra { border-top-style: dashed; border-top-color: var(--muted); }
.sr-lg-legend .ln.derived { border-top-style: dotted; border-top-color: var(--high); }
.sr-lg-svg { display: block; width: 100%; height: 340px; background:
  repeating-linear-gradient(0deg, transparent, transparent 26px, rgba(148,163,184,0.06) 27px); }
.sr-lg-svg .lg-edge { fill: none; }
.sr-lg-svg .lg-edge.given { stroke: var(--accent); stroke-width: 2; }
.sr-lg-svg .lg-edge.contrapositive { stroke: var(--muted); stroke-width: 1.6; stroke-dasharray: 6 5; }
.sr-lg-svg .lg-edge.derived { stroke: var(--high); stroke-width: 1.6; stroke-dasharray: 2 5; }
.sr-lg-svg .lg-edge.hot { stroke: var(--high); stroke-width: 3.5; stroke-dasharray: none; }
.sr-lg-svg .lg-node { fill: rgba(37,99,235,0.12); stroke: var(--accent); stroke-width: 1.6; }
.sr-lg-svg .lg-node.neg { fill: rgba(220,38,38,0.10); stroke: var(--low); }
.sr-lg-svg .lg-nlabel { fill: var(--text); font-size: 15px; font-weight: 700; text-anchor: middle;
  dominant-baseline: central; pointer-events: none; }
.sr-lg-key { display: grid; grid-template-columns: auto 1fr; gap: 2px 12px; font-size: 0.82rem;
  margin-bottom: 14px; }
.sr-lg-key dt { font-weight: 700; color: var(--accent); }
.sr-lg-key dt.neg { color: var(--low); }
.sr-lg-key dd { margin: 0; color: var(--text); }
.sr-lg-tester { border: 1px solid var(--border); border-radius: 12px; background: var(--surface); padding: 14px 16px; }
.sr-lg-tester h3 { margin: 0 0 4px; font-size: 1rem; }
.sr-lg-tester p.sub { margin: 0 0 12px; font-size: 0.82rem; color: var(--muted); }
.sr-lg-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.sr-lg-arrow { font-size: 1.2rem; color: var(--muted); }
.sr-btn { cursor: pointer; border: 1px solid var(--border); background: var(--surface); color: var(--text);
  border-radius: 8px; padding: 8px 16px; font-size: 0.85rem; font-weight: 600; }
.sr-btn.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
.sr-btn.ghost { background: transparent; }
.sr-lg-result { margin-top: 4px; border-radius: 10px; padding: 12px 14px; font-size: 0.9rem; display: none; }
.sr-lg-result.show { display: block; }
.sr-lg-result.valid { background: rgba(22,163,74,0.10); border: 1px solid var(--high); }
.sr-lg-result.mistaken_reversal { background: rgba(220,38,38,0.08); border: 1px solid var(--low); }
.sr-lg-result.mistaken_negation { background: rgba(217,119,6,0.10); border: 1px solid var(--med); }
.sr-lg-result.unsupported { background: rgba(148,163,184,0.12); border: 1px solid var(--border); }
.sr-lg-result .tag { font-weight: 800; text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.75rem; }
.sr-lg-result.valid .tag { color: var(--high); }
.sr-lg-result.mistaken_reversal .tag { color: var(--low); }
.sr-lg-result.mistaken_negation .tag { color: var(--med); }
"""

_LOGIC_JS = """
(function () {
  const holder = document.getElementById('sr-logic');
  if (!holder) return;
  const data = JSON.parse(document.getElementById('sr-logic-data').textContent);
  const problems = data.problems;
  if (!problems.length) return;
  const sel = document.getElementById('sr-lg-problem');
  const stim = document.getElementById('sr-lg-stim');
  const key = document.getElementById('sr-lg-key');
  const svg = document.getElementById('sr-lg-svg');
  const suffSel = document.getElementById('sr-lg-suff');
  const necSel = document.getElementById('sr-lg-nec');
  const result = document.getElementById('sr-lg-result');
  const W = 900, H = 340;
  let cur = problems[0];
  let nodePos = {};

  function esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
  const SVGNS = 'http://www.w3.org/2000/svg';

  function layout(p) {
    nodePos = {};
    const perLayer = {};
    p.nodes.forEach(n => { perLayer[n.layer] = (perLayer[n.layer] || 0) + 1; });
    const colW = W / (p.n_layers + 1);
    p.nodes.forEach(n => {
      const count = perLayer[n.layer];
      const x = colW * (n.layer + 1);
      const y = H * (n.row + 1) / (count + 1);
      nodePos[n.id] = { x, y, n };
    });
  }

  function draw(p) {
    layout(p);
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    const defs = document.createElementNS(SVGNS, 'defs');
    defs.innerHTML =
      '<marker id="ah" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">' +
      '<path d="M0,0 L8,3 L0,6 Z" fill="currentColor"></path></marker>';
    svg.appendChild(defs);
    const gEdges = document.createElementNS(SVGNS, 'g');
    const gNodes = document.createElementNS(SVGNS, 'g');
    svg.appendChild(gEdges); svg.appendChild(gNodes);
    const R = 24;

    p.edges.forEach(e => {
      const a = nodePos[e.source], b = nodePos[e.target];
      if (!a || !b) return;
      const path = document.createElementNS(SVGNS, 'path');
      path.setAttribute('class', 'lg-edge ' + e.kind);
      path.setAttribute('marker-end', 'url(#ah)');
      // trim endpoints to circle edge; curve when same column
      let x1 = a.x, y1 = a.y, x2 = b.x, y2 = b.y;
      const dx = x2 - x1, dy = y2 - y1, d = Math.hypot(dx, dy) || 1;
      const ux = dx / d, uy = dy / d;
      x1 += ux * R; y1 += uy * R; x2 -= ux * (R + 5); y2 -= uy * (R + 5);
      if (Math.abs(a.x - b.x) < 1) {
        const mx = x1 + (a.x > W / 2 ? 60 : -60);
        path.setAttribute('d', `M${x1},${y1} Q${mx},${(y1 + y2) / 2} ${x2},${y2}`);
      } else {
        path.setAttribute('d', `M${x1},${y1} L${x2},${y2}`);
      }
      gEdges.appendChild(path); e.el = path;
    });

    p.nodes.forEach(n => {
      const pos = nodePos[n.id];
      const g = document.createElementNS(SVGNS, 'g');
      const c = document.createElementNS(SVGNS, 'circle');
      c.setAttribute('class', 'lg-node' + (n.negated ? ' neg' : ''));
      c.setAttribute('cx', pos.x); c.setAttribute('cy', pos.y); c.setAttribute('r', R);
      const tt = document.createElementNS(SVGNS, 'title');
      tt.textContent = n.label;
      c.appendChild(tt);
      const t = document.createElementNS(SVGNS, 'text');
      t.setAttribute('class', 'lg-nlabel');
      t.setAttribute('x', pos.x); t.setAttribute('y', pos.y);
      t.textContent = n.symbol;
      g.appendChild(c); g.appendChild(t); gNodes.appendChild(g);
    });
  }

  function fillKey(p) {
    key.innerHTML = p.terms.map(t =>
      '<dt>' + esc(t.symbol) + '</dt><dd>' + esc(t.phrase) + '</dd>').join('');
  }

  function fillSelects(p) {
    const opts = p.nodes.slice().sort((a, b) => a.id.localeCompare(b.id)).map(n =>
      '<option value="' + esc(n.id) + '">' + esc(n.symbol) + ' — ' + esc(n.label) + '</option>').join('');
    suffSel.innerHTML = opts; necSel.innerHTML = opts;
    if (p.nodes.length > 1) necSel.selectedIndex = 1;
  }

  function highlightPath(path) {
    (cur.edges || []).forEach(e => { if (e.el) e.el.classList.remove('hot'); });
    if (!path || path.length < 2) return;
    for (let i = 0; i < path.length - 1; i++) {
      const a = path[i], b = path[i + 1];
      (cur.edges || []).forEach(e => {
        if (e.el && e.source === a && e.target === b) e.el.classList.add('hot');
      });
    }
  }

  const LABELS = {
    valid: 'Valid inference', mistaken_reversal: 'Mistaken reversal',
    mistaken_negation: 'Mistaken negation', unsupported: 'Not supported'
  };

  function test() {
    const s = suffSel.value, n = necSel.value;
    if (s === n) {
      result.className = 'sr-lg-result unsupported show';
      result.innerHTML = '<div class="tag">Pick two different terms</div>';
      highlightPath([]);
      return;
    }
    const info = (cur.inferences || {})[s + '->' + n] || { verdict: 'unsupported', explanation: '', path: [] };
    result.className = 'sr-lg-result ' + info.verdict + ' show';
    const sSym = nodePos[s] ? nodePos[s].n.symbol : s;
    const nSym = nodePos[n] ? nodePos[n].n.symbol : n;
    result.innerHTML = '<div class="tag">' + (LABELS[info.verdict] || info.verdict) + '</div>' +
      '<div style="margin-top:6px"><b>' + esc(sSym) + ' → ' + esc(nSym) + '</b>: ' + esc(info.explanation) + '</div>';
    highlightPath(info.path);
  }

  function load(p) {
    cur = p;
    stim.textContent = p.stimulus;
    fillKey(p); draw(p); fillSelects(p);
    result.className = 'sr-lg-result';
    result.innerHTML = '';
  }

  function revealClaim() {
    suffSel.value = cur.claim.suff; necSel.value = cur.claim.nec; test();
  }

  sel.addEventListener('change', function () { load(problems[+sel.value]); });
  document.getElementById('sr-lg-test').addEventListener('click', test);
  document.getElementById('sr-lg-reveal').addEventListener('click', revealClaim);
  load(problems[0]);
})();
"""


def _diagram_body(payload: dict[str, Any]) -> str:
    problems = payload.get("problems", [])
    if not problems:
        return (
            '<div class="sr-header"><h1>Conditional logic visualizer</h1></div>'
            '<div class="sr-empty">No conditional problems available.</div>'
        )
    data_json = json.dumps(payload).replace("<", "\\u003c")
    options = "".join(
        f'<option value="{i}">{_esc(p["title"])}</option>'
        for i, p in enumerate(problems)
    )
    legend = (
        '<div class="sr-lg-legend">'
        '<span><i class="ln"></i>Given rule (sufficient → necessary)</span>'
        '<span><i class="ln contra"></i>Contrapositive</span>'
        '<span><i class="ln derived"></i>Derived chain</span>'
        "</div>"
    )
    intro = (
        "Diagram a conditional argument: given rules point sufficient → necessary, "
        "the dashed arrow is the contrapositive, and the tester names the error when "
        "an inference does not follow."
    )
    return (
        f"<style>{_LOGIC_CSS}</style>"
        '<div class="sr-header"><h1>Conditional logic visualizer</h1>'
        f"<p>{intro}</p></div>"
        '<div class="sr-logic" id="sr-logic">'
        '<div class="sr-lg-controls"><label for="sr-lg-problem">Problem</label>'
        f'<select class="sr-lg-select" id="sr-lg-problem">{options}</select></div>'
        '<div class="sr-lg-stim" id="sr-lg-stim"></div>'
        '<div class="sr-lg-map">'
        f"{legend}"
        '<svg class="sr-lg-svg" id="sr-lg-svg" viewBox="0 0 900 340" preserveAspectRatio="xMidYMid meet"></svg>'
        "</div>"
        '<dl class="sr-lg-key" id="sr-lg-key"></dl>'
        '<div class="sr-lg-tester">'
        "<h3>Test an inference</h3>"
        '<p class="sub">Pick a sufficient term and a necessary term, then check whether it '
        "follows. Reveal the argument to see the flaw it commits.</p>"
        '<div class="sr-lg-row">'
        '<select class="sr-lg-select" id="sr-lg-suff"></select>'
        '<span class="sr-lg-arrow">→</span>'
        '<select class="sr-lg-select" id="sr-lg-nec"></select>'
        '<button class="sr-btn primary" id="sr-lg-test">Test inference</button>'
        '<button class="sr-btn ghost" id="sr-lg-reveal">Reveal the argument\u2019s claim</button>'
        "</div>"
        '<div class="sr-lg-result" id="sr-lg-result"></div>'
        "</div>"
        '<script type="application/json" id="sr-logic-data">' + data_json + "</script>"
        "</div>"
        f"<script>{_LOGIC_JS}</script>"
    )


def render_logic_diagram_html(
    col=None, *, problems: list[LogicProblem] | None = None, embed: bool = False
) -> str:
    """Render the interactive conditional-logic visualizer.

    ``col`` is accepted for a uniform report signature but is unused: the problems
    are curated conditional items. ``embed=True`` returns body-only markup with the
    dashboard stylesheet inlined; otherwise a full standalone document."""
    from speedrun.dashboard import _DASHBOARD_CSS, _shell

    payload = logic_diagram_payload(problems)
    inner = _diagram_body(payload)
    if embed:
        return f'<style>{_DASHBOARD_CSS}</style><div class="sr-dash">{inner}</div>'
    return _shell(inner, title="Conditional logic visualizer")
