# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Contrasting-pairs drill: the schema-abstraction study mode (SPOV1 / Insight 3).

Gick & Holyoak showed that a single worked example rarely transfers to a
structurally identical new problem, but comparing two analogs that share deep
structure does -- because comparison forces the learner to extract the schema.
This module builds those pairs from the item bank and renders an interactive
drill: two same-structure LSAT items shown together, the student articulates
what they share, then reveals the shared schema and each item's flaw.

Pairs are formed flaw-first (SPOV2): ideally two items with the *same* flaw on
different topics; when the bank has only one item per flaw, we fall back to two
different flaws in the same taxonomy family (e.g. two causal errors), which
doubles as discrimination practice ("same family, what's the difference?").

Kept Qt-free and pure-data so it is unit-testable; the aqt layer drops the HTML
into a dialog and (optionally) persists the student's self-ratings.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

from speedrun.taxonomy.labels import category_label, schema_label
from speedrun.textfmt import INLINE_MD_JS

PKG_ROOT = Path(__file__).resolve().parent
DEFAULT_SEED = PKG_ROOT / "data" / "seed_deck.json"
DEFAULT_TAXONOMY = PKG_ROOT / "taxonomy" / "lsat_taxonomy.json"

FLAW_PREFIX = "flaw."


def _ai_on() -> bool:
    try:
        from speedrun.ai.config import ai_enabled

        return bool(ai_enabled())
    except Exception:
        return False


@dataclass
class ContrastItem:
    """One side of a contrasting pair, flattened from a seed-deck item."""

    id: str
    section: str
    text: str  # LR stimulus or RC passage
    question: str
    correct_text: str
    flaw_id: str
    flaw_label: str
    why_runner_up_wrong: str
    # Answer choices (id + text only) so the drill can let the student mark which
    # answer they picked and then compare their reasoning to the credited one.
    choices: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContrastPair:
    category: str
    category_label: str
    relation: str  # same_flaw | same_category
    shared_prompt: str
    reveal_note: str
    item_a: ContrastItem
    item_b: ContrastItem
    shared_schema: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["item_a"] = self.item_a.to_dict()
        d["item_b"] = self.item_b.to_dict()
        return d


@dataclass
class ContrastSet:
    pairs: list[ContrastPair] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"pairs": [p.to_dict() for p in self.pairs], "stats": self.stats}


def _flaw_of(schemas: list[str]) -> str | None:
    for sid in schemas:
        if sid.startswith(FLAW_PREFIX):
            return sid
    return None


def _load_taxonomy_meta(path: Path = DEFAULT_TAXONOMY) -> dict[str, dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        s["id"]: {
            "category": s.get("category"),
            "name": s.get("name"),
            "description": s.get("description", ""),
            "exam_weight": float(s.get("exam_weight", 0.0) or 0.0),
        }
        for s in data["schemas"]
    }


def load_seed_items(path: Path = DEFAULT_SEED) -> list[dict[str, Any]]:
    """Return the raw seed-deck items that carry a flaw schema (pairing candidates)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("items", [])
    return [it for it in items if _flaw_of(it.get("schemas", []))]


def _to_item(raw: dict[str, Any]) -> ContrastItem:
    flaw = _flaw_of(raw.get("schemas", [])) or ""
    correct = next(
        (c.get("text", "") for c in raw.get("choices", []) if c.get("correct")), ""
    )
    fork = raw.get("two_answer_fork", {}) or {}
    choices = [
        {"id": c.get("id", ""), "text": c.get("text", "")}
        for c in raw.get("choices", [])
        if c.get("id")
    ]
    return ContrastItem(
        id=raw.get("id", ""),
        section=raw.get("section", ""),
        text=raw.get("stimulus") or raw.get("passage") or "",
        question=raw.get("question", ""),
        correct_text=correct,
        flaw_id=flaw,
        flaw_label=schema_label(flaw),
        why_runner_up_wrong=fork.get("why_runner_up_wrong", ""),
        choices=choices,
    )


def _shared_prompt(relation: str, category_lbl: str) -> str:
    if relation == "same_flaw":
        return (
            "Both arguments commit the same reasoning flaw on different topics. "
            "Name the shared flaw and describe how each argument commits it."
        )
    return (
        f"Both arguments are {category_lbl.lower()} reasoning errors. Identify the "
        "deep structure they share, then the key difference between them."
    )


def _reveal_note(
    relation: str, item_a: ContrastItem, item_b: ContrastItem, meta: dict[str, Any]
) -> str:
    desc = meta.get("description", "")
    if relation == "same_flaw":
        base = f"Shared flaw: {item_a.flaw_label}."
        return f"{base} {desc}".strip()
    return (
        f"Same family, different flaw: {item_a.flaw_label} vs {item_b.flaw_label}. "
        "They share the family's deep structure but differ in exactly which step breaks."
    )


def _category_order(
    col, categories: list[str], meta: dict[str, dict[str, Any]]
) -> list[str]:
    """Order categories weakest-first when we have performance data, else by exam
    weight. Always deterministic (tie-break alphabetically)."""
    weakness_by_cat: dict[str, float] = {}
    weight_by_cat: dict[str, float] = {}
    for sid, m in meta.items():
        cat = m.get("category")
        if cat:
            weight_by_cat[cat] = weight_by_cat.get(cat, 0.0) + m.get("exam_weight", 0.0)

    if col is not None:
        try:
            from speedrun.scoring.performance import performance_score, weakness_map

            weaknesses = weakness_map(performance_score(col)["per_schema"])
            for sid, w in weaknesses.items():
                cat = (meta.get(sid) or {}).get("category")
                if cat:
                    weakness_by_cat[cat] = max(weakness_by_cat.get(cat, 0.0), w)
        except Exception:  # pragma: no cover - scoring is best-effort here
            weakness_by_cat = {}

    def key(cat: str) -> tuple[float, float, str]:
        # Higher weakness first, then higher exam weight, then name for stability.
        return (-weakness_by_cat.get(cat, 0.0), -weight_by_cat.get(cat, 0.0), cat)

    return sorted(categories, key=key)


def build_contrasting_pairs(
    col=None,
    *,
    count: int | None = None,
    seed_path: Path = DEFAULT_SEED,
    taxonomy_path: Path = DEFAULT_TAXONOMY,
) -> ContrastSet:
    """Build up to ``count`` contrasting pairs, weakest family first.

    ``count`` defaults to the config value. Pairs prefer same-flaw (different
    topic); when a family has no repeated flaw, they pair two distinct flaws in
    the same family. Deterministic given the same inputs."""
    if count is None:
        from speedrun.config import contrasting_pairs_count

        count = contrasting_pairs_count()

    meta = _load_taxonomy_meta(taxonomy_path)
    raw_items = load_seed_items(seed_path)

    by_category: dict[str, list[dict[str, Any]]] = {}
    for raw in raw_items:
        flaw = _flaw_of(raw.get("schemas", []))
        cat = (meta.get(flaw) or {}).get("category")
        if cat:
            by_category.setdefault(cat, []).append(raw)

    ordered_cats = _category_order(col, list(by_category), meta)

    pairs: list[ContrastPair] = []
    for cat in ordered_cats:
        members = sorted(by_category[cat], key=lambda r: r.get("id", ""))
        used: set[str] = set()

        # Prefer same-flaw pairs (strongest transfer signal).
        by_flaw: dict[str, list[dict[str, Any]]] = {}
        for raw in members:
            by_flaw.setdefault(_flaw_of(raw["schemas"]), []).append(raw)
        for flaw, group in sorted(by_flaw.items()):
            for a, b in combinations(sorted(group, key=lambda r: r["id"]), 2):
                if a["id"] in used or b["id"] in used:
                    continue
                pairs.append(_make_pair(cat, "same_flaw", a, b, meta))
                used.update({a["id"], b["id"]})

        # Fall back to distinct-flaw pairs within the family (discrimination).
        remaining = [r for r in members if r["id"] not in used]
        for a, b in combinations(remaining, 2):
            if a["id"] in used or b["id"] in used:
                continue
            if _flaw_of(a["schemas"]) == _flaw_of(b["schemas"]):
                continue
            pairs.append(_make_pair(cat, "same_category", a, b, meta))
            used.update({a["id"], b["id"]})

    pairs = pairs[: max(0, count)]
    stats = {
        "n_pairs": len(pairs),
        "same_flaw": sum(1 for p in pairs if p.relation == "same_flaw"),
        "same_category": sum(1 for p in pairs if p.relation == "same_category"),
        "categories": sorted({p.category for p in pairs}),
    }
    return ContrastSet(pairs=pairs, stats=stats)


def _make_pair(
    cat: str,
    relation: str,
    a: dict[str, Any],
    b: dict[str, Any],
    meta: dict[str, dict[str, Any]],
) -> ContrastPair:
    item_a, item_b = _to_item(a), _to_item(b)
    cat_lbl = category_label(f"flaw.{cat}")
    shared_schema = item_a.flaw_id if relation == "same_flaw" else None
    flaw_meta = meta.get(item_a.flaw_id, {})
    return ContrastPair(
        category=cat,
        category_label=cat_lbl,
        relation=relation,
        shared_prompt=_shared_prompt(relation, cat_lbl),
        reveal_note=_reveal_note(relation, item_a, item_b, flaw_meta),
        item_a=item_a,
        item_b=item_b,
        shared_schema=shared_schema,
    )


_DRILL_CSS = """
.sr-drill { max-width: 960px; }
.sr-cd-top { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.sr-cd-progress { font-size: 0.8rem; color: var(--muted); font-weight: 600; }
.sr-cd-badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.7rem;
  font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
  background: rgba(37,99,235,0.14); color: var(--accent); }
.sr-cd-badge.same_flaw { background: rgba(22,163,74,0.15); color: var(--high); }
.sr-cd-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; }
.sr-cd-side { border: 1px solid var(--border); border-radius: 12px; background: var(--surface); padding: 14px 16px; }
.sr-cd-side h4 { margin: 0 0 8px; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
.sr-cd-text { font-size: 0.9rem; margin-bottom: 10px; }
.sr-cd-q { font-size: 0.85rem; font-weight: 600; color: var(--text); }
.sr-cd-prompt { border: 1px solid var(--border); border-left: 4px solid var(--accent); border-radius: 10px;
  background: var(--surface); padding: 12px 14px; margin-bottom: 12px; font-size: 0.9rem; }
.sr-cd-articulate { width: 100%; min-height: 90px; font-family: inherit; font-size: 0.9rem; padding: 10px 12px;
  border: 1px solid var(--border); border-radius: 10px; background: var(--bg); color: var(--text); resize: vertical; }
.sr-cd-actions { display: flex; gap: 10px; margin: 12px 0; flex-wrap: wrap; }
.sr-btn { cursor: pointer; border: 1px solid var(--border); background: var(--surface); color: var(--text);
  border-radius: 8px; padding: 8px 16px; font-size: 0.85rem; font-weight: 600; }
.sr-btn.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
.sr-btn.good { border-color: var(--high); color: var(--high); }
.sr-btn.mid { border-color: var(--med); color: var(--med); }
.sr-btn.bad { border-color: var(--low); color: var(--low); }
.sr-cd-reveal { display: none; border: 1px solid var(--border); border-radius: 12px; background: var(--surface);
  padding: 14px 16px; margin-bottom: 12px; }
.sr-cd-reveal.show { display: block; }
.sr-cd-reveal h4 { margin: 0 0 6px; font-size: 0.95rem; }
.sr-cd-note { font-size: 0.88rem; color: var(--text); margin-bottom: 12px; }
.sr-cd-rev-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.sr-cd-rev-side { font-size: 0.82rem; }
.sr-cd-rev-side .flaw { font-weight: 700; color: var(--accent); margin-bottom: 4px; }
.sr-cd-rev-side .ans { color: var(--high); margin: 4px 0; }
.sr-cd-rev-side .why { color: var(--muted); }
.sr-cd-selfrate { font-size: 0.85rem; color: var(--muted); margin: 8px 0 4px; }
.sr-cd-compare { margin-top: 12px; border-top: 1px dashed var(--border); padding-top: 10px; }
.sr-cd-compare-status { display: inline-flex; align-items: center; gap: 6px; font-size: 0.72rem;
  padding: 2px 9px; border-radius: 999px; border: 1px solid var(--border); margin-bottom: 8px; }
.sr-cd-compare-status.on { background: rgba(22,163,74,0.10); border-color: var(--high); color: var(--high); }
.sr-cd-compare-status.off { background: rgba(148,163,184,0.12); color: var(--muted); }
.sr-cd-compare-status .dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
.sr-cd-compare-q { font-size: 0.8rem; color: var(--muted); margin-bottom: 6px; }
.sr-cd-pick { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.sr-cd-pick button { cursor: pointer; border: 1px solid var(--border); background: var(--bg); color: var(--text);
  border-radius: 8px; padding: 5px 11px; font-size: 0.82rem; font-weight: 700; }
.sr-cd-pick button.sel { border-color: var(--accent); background: var(--accent); color: #fff; }
.sr-cd-cmp-result { font-size: 0.85rem; line-height: 1.55; white-space: pre-wrap;
  background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; margin-top: 6px; }
.sr-cd-cmp-result .src { display: block; margin-top: 8px; font-size: 0.72rem; color: var(--muted); }
.sr-cd-cmp-result .src .ai { color: var(--high); font-weight: 700; }
.sr-cd-cmp-result strong { font-weight: 700; }
.sr-cd-done { border: 1px solid var(--border); border-radius: 12px; background: var(--surface); padding: 22px;
  text-align: center; }
.sr-cd-done h2 { margin: 0 0 8px; }
.sr-cd-tally { font-size: 1rem; }
.sr-cd-tally b.good { color: var(--high); } .sr-cd-tally b.mid { color: var(--med); } .sr-cd-tally b.bad { color: var(--low); }
@media (max-width: 640px) { .sr-cd-pair, .sr-cd-rev-grid { grid-template-columns: 1fr; } }
"""

_DRILL_JS = r"""
(function () {
  const holder = document.getElementById('sr-drill');
  if (!holder) return;
  const data = JSON.parse(document.getElementById('sr-drill-data').textContent);
  const pairs = data.pairs;
  let idx = 0;
  const tally = { got_it: 0, partial: 0, missed: 0 };
  const stage = document.getElementById('sr-cd-stage');

  const esc = srEsc;   // shared with speedrun.textfmt.INLINE_MD_JS
  const fmt = srFmt;   // esc()+**bold**+newlines, escaped-first (injection-safe)
  function srcLine(reply) {
    if (reply.ai_used) {
      return '<span class="src"><span class="ai">AI</span> &middot; source: ' + esc(reply.source) +
        ' &middot; grounded in this problem</span>';
    }
    var extra = (reply.citations && reply.citations.length) ? ' &middot; ' + esc(reply.citations.join(' &middot; ')) : '';
    return '<span class="src">Grounded comparison (no AI) — from this problem\u2019s trap tags &amp; fork' + extra + '</span>';
  }

  function compareBlock(it, label) {
    if (!it.choices || !it.choices.length) return '';
    var picks = it.choices.map(function (c) {
      return '<button type="button" data-item="' + esc(it.id) + '" data-choice="' + esc(c.id) + '">(' + esc(c.id) + ')</button>';
    }).join('');
    return '<div class="sr-cd-compare">' +
      '<div class="sr-cd-compare-q">' + esc(label) + ': which answer did you pick? Compare your reasoning to the credited one.</div>' +
      '<div class="sr-cd-pick">' + picks + '</div>' +
      '<div class="sr-cd-cmp-result" style="display:none"></div></div>';
  }

  function wireCompare() {
    stage.querySelectorAll('.sr-cd-pick button').forEach(function (b) {
      b.addEventListener('click', function () {
        var wrap = b.closest('.sr-cd-compare');
        wrap.querySelectorAll('.sr-cd-pick button').forEach(function (x) { x.classList.remove('sel'); });
        b.classList.add('sel');
        var res = wrap.querySelector('.sr-cd-cmp-result');
        res.style.display = 'block';
        res.innerHTML = 'Comparing\u2026';
        var item = b.dataset.item, choice = b.dataset.choice;
        if (typeof pycmd === 'function') {
          pycmd('speedrun:compare:' + item + ':' + choice, function (resp) {
            var reply = (typeof resp === 'string') ? JSON.parse(resp) : (resp || {});
            if (!reply.comparison) reply = { comparison: String(resp), source: 'offline', ai_used: false, citations: [] };
            res.innerHTML = fmt(reply.comparison) + srcLine(reply);
          });
        } else {
          res.innerHTML = 'Open this drill inside the app (LSAT Speedrun menu) to compare your reasoning.' +
            srcLine({ ai_used: false, citations: [] });
        }
      });
    });
  }

  function sideHtml(it, label) {
    return '<div class="sr-cd-side"><h4>' + label + ' &middot; ' + esc(it.section) + '</h4>' +
      '<div class="sr-cd-text">' + esc(it.text) + '</div>' +
      '<div class="sr-cd-q">' + esc(it.question) + '</div></div>';
  }
  function revSide(it) {
    return '<div class="sr-cd-rev-side"><div class="flaw">' + esc(it.flaw_label) + '</div>' +
      '<div class="ans">Correct: ' + esc(it.correct_text) + '</div>' +
      '<div class="why">' + esc(it.why_runner_up_wrong) + '</div></div>';
  }

  function report(rating) {
    tally[rating] = (tally[rating] || 0) + 1;
    const p = pairs[idx];
    try {
      if (typeof pycmd === 'function') {
        pycmd('speedrun:contrast:' + JSON.stringify({
          pair_a: p.item_a.id, pair_b: p.item_b.id, category: p.category,
          relation: p.relation, shared_schema: p.shared_schema, rating: rating
        }));
      }
    } catch (e) {}
    idx += 1;
    render();
  }

  function render() {
    if (idx >= pairs.length) {
      stage.innerHTML = '<div class="sr-cd-done"><h2>Session complete</h2>' +
        '<div class="sr-cd-tally">You self-rated <b class="good">' + tally.got_it + ' got it</b>, ' +
        '<b class="mid">' + tally.partial + ' partial</b>, <b class="bad">' + tally.missed + ' missed</b> ' +
        'across ' + pairs.length + ' pairs.</div>' +
        '<p style="color:var(--muted);font-size:0.85rem;margin-top:10px">Comparison is how the schema sticks. ' +
        'These self-ratings are training signal only and do not change your scores.</p></div>';
      return;
    }
    const p = pairs[idx];
    stage.innerHTML =
      '<div class="sr-cd-top"><span class="sr-cd-progress">Pair ' + (idx + 1) + ' of ' + pairs.length + '</span>' +
      '<span class="sr-cd-badge ' + p.relation + '">' + esc(p.category_label) +
      (p.relation === 'same_flaw' ? ' &middot; same flaw' : ' &middot; same family') + '</span></div>' +
      '<div class="sr-cd-pair">' + sideHtml(p.item_a, 'Argument A') + sideHtml(p.item_b, 'Argument B') + '</div>' +
      '<div class="sr-cd-prompt">' + esc(p.shared_prompt) + '</div>' +
      '<textarea class="sr-cd-articulate" id="sr-cd-text" placeholder="Type what these two arguments share (retrieval before reveal)..."></textarea>' +
      '<div class="sr-cd-actions"><button class="sr-btn primary" id="sr-cd-reveal-btn">Reveal shared structure</button></div>' +
      '<div class="sr-cd-reveal" id="sr-cd-reveal"><h4>' + esc(p.category_label) + ' &mdash; what they share</h4>' +
      '<div class="sr-cd-note">' + esc(p.reveal_note) + '</div>' +
      '<div class="sr-cd-rev-grid">' + revSide(p.item_a) + revSide(p.item_b) + '</div>' +
      '<div class="sr-cd-compare-status ' + (data.ai_enabled ? 'on' : 'off') + '"><span class="dot"></span>' +
      (data.ai_enabled
        ? 'AI is enabled — your reasoning comparison is generated and grounded in this problem.'
        : 'AI is off (opt-in) — comparisons are built from this problem\u2019s trap tags and fork rationale.') +
      '</div>' +
      compareBlock(p.item_a, 'Argument A') + compareBlock(p.item_b, 'Argument B') +
      '<div class="sr-cd-selfrate">How did your articulation compare?</div>' +
      '<div class="sr-cd-actions">' +
      '<button class="sr-btn good" data-r="got_it">Got it</button>' +
      '<button class="sr-btn mid" data-r="partial">Partial</button>' +
      '<button class="sr-btn bad" data-r="missed">Missed</button></div></div>';

    document.getElementById('sr-cd-reveal-btn').addEventListener('click', function () {
      document.getElementById('sr-cd-reveal').classList.add('show');
      this.disabled = true;
    });
    wireCompare();
    stage.querySelectorAll('[data-r]').forEach(function (b) {
      b.addEventListener('click', function () { report(b.dataset.r); });
    });
  }
  render();
})();
"""


def _drill_body(cset: ContrastSet) -> str:
    """Inner drill markup (style + content + script) without the page shell."""
    if not cset.pairs:
        return (
            '<div class="sr-header"><h1>Contrasting-pairs drill</h1></div>'
            '<div class="sr-empty">No contrasting pairs available yet. Import the seed '
            "deck (Tools &rarr; LSAT Speedrun &rarr; Import seed deck); pairs form from "
            "items that share a flaw family.</div>"
        )
    payload = cset.to_dict()
    payload["ai_enabled"] = _ai_on()
    data_json = json.dumps(payload).replace("<", "\\u003c")
    intro = (
        f"{cset.stats['n_pairs']} pairs &middot; compare two same-structure arguments, "
        "say what they share, then reveal. Comparison is what makes a schema transfer."
    )
    return (
        f"<style>{_DRILL_CSS}</style>"
        '<div class="sr-header"><h1>Contrasting-pairs drill</h1>'
        f"<p>{intro}</p></div>"
        '<div class="sr-drill" id="sr-drill"><div id="sr-cd-stage"></div>'
        f'<script type="application/json" id="sr-drill-data">{data_json}</script></div>'
        f"<script>{INLINE_MD_JS}{_DRILL_JS}</script>"
    )


def render_contrasting_drill_html(cset: ContrastSet, *, embed: bool = False) -> str:
    """Render the interactive contrasting-pairs drill.

    ``embed=False`` returns a full standalone HTML document (browser / raw
    QWebEngineView). ``embed=True`` returns body-only markup with the dashboard
    stylesheet inlined, for injection into an AnkiWebView (which supplies the
    ``pycmd`` bridge but not our CSS)."""
    from speedrun.dashboard import _DASHBOARD_CSS, _shell

    inner = _drill_body(cset)
    if embed:
        return f'<style>{_DASHBOARD_CSS}</style><div class="sr-dash">{inner}</div>'
    return _shell(inner, title="Contrasting-pairs drill")


def record_contrast_result(logger, payload: dict[str, Any]) -> None:
    """Persist one self-rated contrasting-pair result via a SessionLogger.

    ``payload`` carries pair_ids, category, relation and rating
    (got_it|partial|missed). This is training/metacognition data -- it is NOT a
    graded transfer attempt and must never feed the readiness/performance score
    (honesty rule)."""
    if logger._current is None or logger._current.mode != "contrasting":
        logger.start(mode="contrasting")
    import time

    from speedrun.session_logger import SessionEvent

    ev = SessionEvent(
        ts=int(time.time()),
        event="contrast",
        schema=payload.get("shared_schema"),
        extra={
            "pair_a": payload.get("pair_a"),
            "pair_b": payload.get("pair_b"),
            "category": payload.get("category"),
            "relation": payload.get("relation"),
            "rating": payload.get("rating"),
        },
    )
    logger._current.events.append(ev)
    logger._append(
        {"type": "contrast", "session_id": logger._current.session_id, **ev.to_dict()}
    )


def contrasting_practice_summary(log_path: Path | None = None) -> dict[str, Any]:
    """Read the session log and summarise contrasting-pairs practice for the
    dashboard. Honesty-safe: reports counts + self-rated transfer only."""
    from speedrun.session_logger import DEFAULT_LOG, load_sessions

    records = load_sessions(log_path or DEFAULT_LOG, limit=2000)
    ratings = [
        r.get("extra", {}).get("rating") for r in records if r.get("type") == "contrast"
    ]
    ratings = [r for r in ratings if r]
    n = len(ratings)
    if n == 0:
        return {"n": 0, "got_it": 0, "partial": 0, "missed": 0, "transfer": None}
    got = ratings.count("got_it")
    partial = ratings.count("partial")
    missed = ratings.count("missed")
    # Self-rated transfer credits full for got_it, half for partial.
    transfer = (got + 0.5 * partial) / n
    return {
        "n": n,
        "got_it": got,
        "partial": partial,
        "missed": missed,
        "transfer": round(transfer, 4),
    }
