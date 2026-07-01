# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Predict-the-schema cold-open: isolate recall vs transfer (SPOV1 / SPOV2).

A normal flashcard shows the stimulus, the question and the answer choices all at
once, so a student can pattern-match their way to the answer without ever proving
they can extract the deep structure themselves. The cold-open removes that crutch:
show the stimulus ALONE, force the student to commit to a flaw schema from the full
taxonomy, and only THEN reveal the question and choices.

The payoff is a diagnostic that grades two things separately:
  * schema-ID accuracy -- did you name the flaw from the stimulus alone?
  * answer accuracy     -- did you then pick the right choice?
The gap between them (answer-right but flaw-wrong) is the recall-vs-transfer gap
SPOV1 names. These self-driven grades are diagnostic/training signal only and must
NEVER feed the memory/performance/readiness scores (honesty rule); graded transfer
for scoring still comes exclusively from the Anki revlog.

Kept Qt-free and pure-data so it is unit-testable; the aqt layer drops the HTML
into a dialog and (optionally) persists results via SessionLogger.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from speedrun.contrasting import (
    DEFAULT_SEED,
    DEFAULT_TAXONOMY,
    FLAW_PREFIX,
    _category_order,
    _flaw_of,
    _load_taxonomy_meta,
    load_seed_items,
)
from speedrun.taxonomy.labels import category_label, schema_label


@dataclass
class ColdOpenChoice:
    id: str
    text: str
    correct: bool
    trap: str | None = None
    trap_label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ColdOpenItem:
    """One cold-open prompt: stimulus shown first, question/choices gated behind
    the schema prediction."""

    id: str
    section: str
    stimulus: str
    question: str
    choices: list[ColdOpenChoice]
    flaw_id: str
    flaw_label: str
    flaw_description: str
    category: str
    category_label: str
    correct_choice_id: str
    why_runner_up_wrong: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["choices"] = [c.to_dict() for c in self.choices]
        return d


@dataclass
class ColdOpenSet:
    items: list[ColdOpenItem] = field(default_factory=list)
    flaw_options: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [it.to_dict() for it in self.items],
            "flaw_options": self.flaw_options,
            "stats": self.stats,
        }


def _to_item(raw: dict[str, Any], meta: dict[str, dict[str, Any]]) -> ColdOpenItem:
    flaw = _flaw_of(raw.get("schemas", [])) or ""
    fmeta = meta.get(flaw, {})
    cat = fmeta.get("category") or ""
    choices: list[ColdOpenChoice] = []
    correct_id = ""
    for c in raw.get("choices", []):
        trap = c.get("trap")
        if c.get("correct"):
            correct_id = c.get("id", "")
        choices.append(
            ColdOpenChoice(
                id=c.get("id", ""),
                text=c.get("text", ""),
                correct=bool(c.get("correct")),
                trap=trap,
                trap_label=schema_label(trap) if trap else None,
            )
        )
    fork = raw.get("two_answer_fork", {}) or {}
    return ColdOpenItem(
        id=raw.get("id", ""),
        section=raw.get("section", ""),
        stimulus=raw.get("stimulus") or raw.get("passage") or "",
        question=raw.get("question", ""),
        choices=choices,
        flaw_id=flaw,
        flaw_label=schema_label(flaw),
        flaw_description=fmeta.get("description", ""),
        category=cat,
        category_label=category_label(f"flaw.{cat}") if cat else "",
        correct_choice_id=correct_id,
        why_runner_up_wrong=fork.get("why_runner_up_wrong", ""),
    )


def _flaw_options(meta: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Every flaw schema in the taxonomy, grouped for the prediction picker.

    Deliberately includes flaws that are not in the current item set: the student
    must *discriminate*, not eliminate by process of what's on screen (SPOV2)."""
    opts: list[dict[str, Any]] = []
    for sid, m in meta.items():
        if not sid.startswith(FLAW_PREFIX):
            continue
        cat = m.get("category") or ""
        opts.append(
            {
                "id": sid,
                "label": schema_label(sid),
                "category": cat,
                "category_label": category_label(f"flaw.{cat}") if cat else "",
            }
        )
    opts.sort(key=lambda o: (o["category_label"], o["label"]))
    return opts


def build_cold_open_set(
    col=None,
    *,
    count: int | None = None,
    seed_path: Path = DEFAULT_SEED,
    taxonomy_path: Path = DEFAULT_TAXONOMY,
) -> ColdOpenSet:
    """Build up to ``count`` cold-open prompts, weakest family first.

    ``count`` defaults to the config value. Items are grouped by taxonomy family
    and ordered weakest-first when a collection is supplied, else by exam weight;
    deterministic given the same inputs."""
    if count is None:
        from speedrun.config import cold_open_count

        count = cold_open_count()

    meta = _load_taxonomy_meta(taxonomy_path)
    raw_items = load_seed_items(seed_path)

    by_category: dict[str, list[dict[str, Any]]] = {}
    for raw in raw_items:
        flaw = _flaw_of(raw.get("schemas", []))
        cat = (meta.get(flaw) or {}).get("category")
        if cat:
            by_category.setdefault(cat, []).append(raw)

    ordered_cats = _category_order(col, list(by_category), meta)

    items: list[ColdOpenItem] = []
    for cat in ordered_cats:
        for raw in sorted(by_category[cat], key=lambda r: r.get("id", "")):
            items.append(_to_item(raw, meta))

    items = items[: max(0, count)]
    options = _flaw_options(meta)
    stats = {
        "n_items": len(items),
        "categories": sorted({it.category for it in items}),
        "n_flaw_options": len(options),
    }
    return ColdOpenSet(items=items, flaw_options=options, stats=stats)


_CO_CSS = """
.sr-co { max-width: 860px; }
.sr-co-top { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.sr-co-progress { font-size: 0.8rem; color: var(--muted); font-weight: 600; }
.sr-co-badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.7rem;
  font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
  background: rgba(37,99,235,0.14); color: var(--accent); }
.sr-co-stim { border: 1px solid var(--border); border-radius: 12px; background: var(--surface);
  padding: 16px 18px; font-size: 0.95rem; line-height: 1.5; margin-bottom: 14px; }
.sr-co-ask { font-weight: 700; font-size: 0.95rem; margin-bottom: 8px; }
.sr-co-hint { font-size: 0.82rem; color: var(--muted); margin-bottom: 10px; }
.sr-co-select { width: 100%; font-family: inherit; font-size: 0.9rem; padding: 10px 12px;
  border: 1px solid var(--border); border-radius: 10px; background: var(--bg); color: var(--text); }
.sr-co-actions { display: flex; gap: 10px; margin: 14px 0; flex-wrap: wrap; }
.sr-btn { cursor: pointer; border: 1px solid var(--border); background: var(--surface); color: var(--text);
  border-radius: 8px; padding: 8px 16px; font-size: 0.85rem; font-weight: 600; }
.sr-btn:disabled { opacity: 0.5; cursor: default; }
.sr-btn.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
.sr-co-q { font-weight: 600; font-size: 0.9rem; margin: 4px 0 10px; }
.sr-co-choices { display: flex; flex-direction: column; gap: 8px; }
.sr-co-choice { text-align: left; cursor: pointer; border: 1px solid var(--border); background: var(--surface);
  color: var(--text); border-radius: 10px; padding: 10px 14px; font-size: 0.88rem; font-family: inherit; }
.sr-co-choice:hover { border-color: var(--accent); }
.sr-co-choice.correct { border-color: var(--high); background: rgba(22,163,74,0.10); }
.sr-co-choice.chosen-wrong { border-color: var(--low); background: rgba(220,38,38,0.08); }
.sr-co-choice .cid { font-weight: 700; margin-right: 8px; }
.sr-co-reveal { border: 1px solid var(--border); border-radius: 12px; background: var(--surface);
  padding: 16px 18px; margin-top: 14px; }
.sr-co-verdict { display: flex; gap: 18px; flex-wrap: wrap; margin-bottom: 12px; font-size: 0.9rem; font-weight: 700; }
.sr-co-verdict .ok { color: var(--high); } .sr-co-verdict .no { color: var(--low); }
.sr-co-truth { font-size: 0.9rem; margin-bottom: 8px; }
.sr-co-truth .flaw { font-weight: 700; color: var(--accent); }
.sr-co-desc { font-size: 0.85rem; color: var(--muted); margin-bottom: 10px; }
.sr-co-why { font-size: 0.85rem; color: var(--muted); border-left: 3px solid var(--border); padding-left: 10px; }
.sr-co-done { border: 1px solid var(--border); border-radius: 12px; background: var(--surface); padding: 22px;
  text-align: center; }
.sr-co-done h2 { margin: 0 0 10px; }
.sr-co-scores { display: flex; gap: 26px; justify-content: center; flex-wrap: wrap; margin: 10px 0; }
.sr-co-scores .num { font-size: 1.9rem; font-weight: 800; }
.sr-co-scores .lbl { font-size: 0.78rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
.sr-co-gap { font-size: 0.95rem; margin-top: 6px; }
"""

_CO_JS = """
(function () {
  const holder = document.getElementById('sr-co');
  if (!holder) return;
  const data = JSON.parse(document.getElementById('sr-co-data').textContent);
  const items = data.items;
  const options = data.flaw_options || [];
  let idx = 0;
  let predicted = null;
  const tally = { schema: 0, answer: 0, n: 0 };
  const stage = document.getElementById('sr-co-stage');

  function esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }

  function optionsHtml() {
    const groups = {};
    const order = [];
    options.forEach(function (o) {
      if (!groups[o.category_label]) { groups[o.category_label] = []; order.push(o.category_label); }
      groups[o.category_label].push(o);
    });
    let h = '<option value="">— choose the flaw at work —</option>';
    order.forEach(function (g) {
      h += '<optgroup label="' + esc(g) + '">';
      groups[g].forEach(function (o) { h += '<option value="' + esc(o.id) + '">' + esc(o.label) + '</option>'; });
      h += '</optgroup>';
    });
    return h;
  }

  function head(it) {
    return '<div class="sr-co-top"><span class="sr-co-progress">Item ' + (idx + 1) + ' of ' + items.length + '</span>' +
      '<span class="sr-co-badge">' + esc(it.section) + '</span></div>';
  }

  function renderPredict() {
    const it = items[idx];
    stage.innerHTML = head(it) +
      '<div class="sr-co-stim">' + esc(it.stimulus) + '</div>' +
      '<div class="sr-co-ask">What flaw is at work here?</div>' +
      '<div class="sr-co-hint">Read the argument alone and commit to the underlying flaw before you see the question or choices.</div>' +
      '<select class="sr-co-select" id="sr-co-pick">' + optionsHtml() + '</select>' +
      '<div class="sr-co-actions"><button class="sr-btn primary" id="sr-co-lock" disabled>Lock in &amp; reveal question</button></div>';
    const sel = document.getElementById('sr-co-pick');
    const lock = document.getElementById('sr-co-lock');
    sel.addEventListener('change', function () { lock.disabled = !sel.value; });
    lock.addEventListener('click', function () { predicted = sel.value; renderAnswer(); });
  }

  function renderAnswer() {
    const it = items[idx];
    let choices = '<div class="sr-co-choices">';
    it.choices.forEach(function (c) {
      choices += '<button class="sr-co-choice" data-cid="' + esc(c.id) + '">' +
        '<span class="cid">' + esc(c.id) + '</span>' + esc(c.text) + '</button>';
    });
    choices += '</div>';
    stage.innerHTML = head(it) +
      '<div class="sr-co-stim">' + esc(it.stimulus) + '</div>' +
      '<div class="sr-co-q">' + esc(it.question) + '</div>' + choices;
    stage.querySelectorAll('[data-cid]').forEach(function (b) {
      b.addEventListener('click', function () { grade(b.dataset.cid); });
    });
  }

  function grade(choiceId) {
    const it = items[idx];
    const schemaOk = predicted === it.flaw_id;
    const answerOk = choiceId === it.correct_choice_id;
    tally.n += 1;
    if (schemaOk) tally.schema += 1;
    if (answerOk) tally.answer += 1;
    try {
      if (typeof pycmd === 'function') {
        pycmd('speedrun:cold_open:' + JSON.stringify({
          item_id: it.id, predicted_schema: predicted, actual_schema: it.flaw_id,
          schema_correct: schemaOk, answer_choice: choiceId, answer_correct: answerOk
        }));
      }
    } catch (e) {}
    renderReveal(choiceId, schemaOk, answerOk);
  }

  function renderReveal(choiceId, schemaOk, answerOk) {
    const it = items[idx];
    let choices = '<div class="sr-co-choices">';
    it.choices.forEach(function (c) {
      let cls = 'sr-co-choice';
      if (c.id === it.correct_choice_id) cls += ' correct';
      else if (c.id === choiceId) cls += ' chosen-wrong';
      choices += '<div class="' + cls + '"><span class="cid">' + esc(c.id) + '</span>' + esc(c.text) + '</div>';
    });
    choices += '</div>';
    const predLbl = predicted ? predLabel(predicted) : '(no prediction)';
    stage.innerHTML = head(it) +
      '<div class="sr-co-stim">' + esc(it.stimulus) + '</div>' +
      '<div class="sr-co-q">' + esc(it.question) + '</div>' + choices +
      '<div class="sr-co-reveal">' +
      '<div class="sr-co-verdict">' +
      '<span class="' + (schemaOk ? 'ok' : 'no') + '">Schema: ' + (schemaOk ? 'correct' : 'missed') + '</span>' +
      '<span class="' + (answerOk ? 'ok' : 'no') + '">Answer: ' + (answerOk ? 'correct' : 'missed') + '</span>' +
      '</div>' +
      '<div class="sr-co-truth">You predicted <b>' + esc(predLbl) + '</b>. The flaw is <span class="flaw">' + esc(it.flaw_label) + '</span>.</div>' +
      (it.flaw_description ? '<div class="sr-co-desc">' + esc(it.flaw_description) + '</div>' : '') +
      (it.why_runner_up_wrong ? '<div class="sr-co-why">' + esc(it.why_runner_up_wrong) + '</div>' : '') +
      '<div class="sr-co-actions"><button class="sr-btn primary" id="sr-co-next">' +
      (idx + 1 >= items.length ? 'See results' : 'Next item') + '</button></div></div>';
    document.getElementById('sr-co-next').addEventListener('click', function () { idx += 1; render(); });
  }

  function predLabel(id) {
    for (let i = 0; i < options.length; i++) { if (options[i].id === id) return options[i].label; }
    return id;
  }

  function pct(n, d) { return d ? Math.round((n / d) * 100) : 0; }

  function render() {
    if (idx >= items.length) {
      const sp = pct(tally.schema, tally.n), ap = pct(tally.answer, tally.n);
      const gap = ap - sp;
      const gapMsg = gap > 0
        ? 'You answered right more often than you named the flaw — ' + gap + ' pts of pattern-matching without transfer.'
        : (gap < 0 ? 'You named the flaw more often than you landed the answer.' : 'Your schema and answer accuracy match.');
      stage.innerHTML = '<div class="sr-co-done"><h2>Cold-open complete</h2>' +
        '<div class="sr-co-scores">' +
        '<div><div class="num" style="color:var(--accent)">' + sp + '%</div><div class="lbl">Schema&#8209;ID accuracy</div></div>' +
        '<div><div class="num" style="color:var(--high)">' + ap + '%</div><div class="lbl">Answer accuracy</div></div>' +
        '</div>' +
        '<div class="sr-co-gap">' + gapMsg + '</div>' +
        '<p style="color:var(--muted);font-size:0.85rem;margin-top:12px">Naming the flaw from the stimulus alone is the transfer skill (SPOV1). ' +
        'These are diagnostic signal only and do not change your scores.</p></div>';
      return;
    }
    predicted = null;
    renderPredict();
  }
  render();
})();
"""


def _co_body(cset: ColdOpenSet) -> str:
    """Inner cold-open markup (style + content + script) without the page shell."""
    if not cset.items:
        return (
            '<div class="sr-header"><h1>Predict-the-schema cold-open</h1></div>'
            '<div class="sr-empty">No cold-open items available yet. Import the seed '
            "deck (Tools &rarr; LSAT Speedrun &rarr; Import seed deck); cold-opens are "
            "built from items that carry a flaw schema.</div>"
        )
    data_json = json.dumps(cset.to_dict()).replace("<", "\\u003c")
    intro = (
        f"{cset.stats['n_items']} items &middot; name the flaw from the stimulus alone, "
        "then reveal the question. Schema-ID and answer accuracy are graded separately."
    )
    return (
        f"<style>{_CO_CSS}</style>"
        '<div class="sr-header"><h1>Predict-the-schema cold-open</h1>'
        f"<p>{intro}</p></div>"
        '<div class="sr-co" id="sr-co"><div id="sr-co-stage"></div>'
        f'<script type="application/json" id="sr-co-data">{data_json}</script></div>'
        f"<script>{_CO_JS}</script>"
    )


def render_cold_open_html(cset: ColdOpenSet, *, embed: bool = False) -> str:
    """Render the interactive predict-the-schema cold-open.

    ``embed=False`` returns a full standalone HTML document (browser / raw
    QWebEngineView). ``embed=True`` returns body-only markup with the dashboard
    stylesheet inlined, for injection into an AnkiWebView (which supplies the
    ``pycmd`` bridge but not our CSS)."""
    from speedrun.dashboard import _DASHBOARD_CSS, _shell

    inner = _co_body(cset)
    if embed:
        return f'<style>{_DASHBOARD_CSS}</style><div class="sr-dash">{inner}</div>'
    return _shell(inner, title="Predict-the-schema cold-open")


def record_cold_open_result(logger, payload: dict[str, Any]) -> None:
    """Persist one cold-open result via a SessionLogger.

    ``payload`` carries item_id, predicted_schema, actual_schema, schema_correct,
    answer_choice and answer_correct. This is a self-driven diagnostic -- it is NOT
    a graded transfer attempt and must never feed the readiness/performance score
    (honesty rule)."""
    if logger._current is None or logger._current.mode != "cold_open":
        logger.start(mode="cold_open")
    import time

    from speedrun.session_logger import SessionEvent

    ev = SessionEvent(
        ts=int(time.time()),
        event="cold_open",
        schema=payload.get("actual_schema"),
        latency_ms=payload.get("latency_ms"),
        extra={
            "item_id": payload.get("item_id"),
            "predicted_schema": payload.get("predicted_schema"),
            "actual_schema": payload.get("actual_schema"),
            "schema_correct": bool(payload.get("schema_correct")),
            "answer_choice": payload.get("answer_choice"),
            "answer_correct": bool(payload.get("answer_correct")),
        },
    )
    logger._current.events.append(ev)
    logger._append(
        {"type": "cold_open", "session_id": logger._current.session_id, **ev.to_dict()}
    )


def cold_open_summary(log_path: Path | None = None) -> dict[str, Any]:
    """Read the session log and summarise cold-open practice for the dashboard.

    Honesty-safe: reports schema-ID accuracy SEPARATELY from answer accuracy, and
    the transfer gap between them. None of this feeds the scores."""
    from speedrun.session_logger import DEFAULT_LOG, load_sessions

    records = load_sessions(log_path or DEFAULT_LOG, limit=4000)
    events = [
        r.get("extra", {}) for r in records if r.get("type") == "cold_open"
    ]
    n = len(events)
    if n == 0:
        return {
            "n": 0,
            "schema_accuracy": None,
            "answer_accuracy": None,
            "transfer_gap": None,
        }
    schema_hits = sum(1 for e in events if e.get("schema_correct"))
    answer_hits = sum(1 for e in events if e.get("answer_correct"))
    schema_acc = schema_hits / n
    answer_acc = answer_hits / n
    return {
        "n": n,
        "schema_accuracy": round(schema_acc, 4),
        "answer_accuracy": round(answer_acc, 4),
        "transfer_gap": round(answer_acc - schema_acc, 4),
    }
