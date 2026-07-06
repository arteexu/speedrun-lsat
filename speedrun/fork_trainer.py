# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Two-answer fork trainer: drill the final binary decision (SPOV3 / Insight 6).

On hard LSAT items the difficulty does not disappear with expertise -- it
relocates to the last two answers: one attractive trap and one winner. Deciding
between them precisely AND quickly is what separates a 175 from a 160. This
mode drills exactly that step in isolation:

  1. Show the stimulus, the question, and ONLY the two finalists (the correct
     answer and the runner-up from the item's ``two_answer_fork``), sides
     shuffled deterministically. A timer runs -- the fork is a timed decision
     (SPOV4: accuracy without latency is a vanity metric).
  2. After picking, the student names WHY the loser loses: they identify the
     runner-up's trap type from the full trap taxonomy (Insight 8 -- "why is
     this wrong?" is itself a transferable schema).
  3. The reveal ALWAYS shows the fork rationale (why the runner-up is wrong and
     the winner right). This is the scaffold SPOV3 says should essentially
     never fade -- so here, by design, it never fades.

The drill grades three things separately: fork accuracy, trap-ID accuracy, and
decision latency vs. the section budget. These self-driven grades are training
signal only and must NEVER feed memory/performance/readiness (honesty rule);
graded transfer for the scores still comes exclusively from the Anki revlog.

Kept Qt-free and pure-data so it is unit-testable; the aqt layer drops the HTML
into a dialog and persists results via SessionLogger.
"""

from __future__ import annotations

import json
import zlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from speedrun.contrasting import (
    DEFAULT_SEED,
    DEFAULT_TAXONOMY,
    _category_order,
    _flaw_of,
    _load_taxonomy_meta,
)
from speedrun.taxonomy.labels import category_label, schema_label

TRAP_PREFIX = "trap."


@dataclass
class ForkChoice:
    """One of the two finalists shown to the student."""

    id: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ForkItem:
    """One two-answer fork: stimulus + question + exactly two finalists."""

    id: str
    section: str
    stimulus: str
    question: str
    choices: list[ForkChoice]  # exactly two, presentation order
    winner_id: str
    runner_up_id: str
    runner_trap: str
    runner_trap_label: str
    runner_trap_description: str
    why_runner_up_wrong: str
    flaw_id: str
    flaw_label: str
    budget_ms: int

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["choices"] = [c.to_dict() for c in self.choices]
        return d


@dataclass
class ForkSet:
    items: list[ForkItem] = field(default_factory=list)
    trap_options: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [it.to_dict() for it in self.items],
            "trap_options": self.trap_options,
            "stats": self.stats,
        }


def load_fork_items(path: Path = DEFAULT_SEED) -> list[dict[str, Any]]:
    """Raw seed items that carry a usable two-answer fork (winner + runner-up)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for it in data.get("items", []):
        fork = it.get("two_answer_fork") or {}
        runner = fork.get("runner_up")
        choices = {c.get("id"): c for c in it.get("choices", [])}
        winner = next((c for c in choices.values() if c.get("correct")), None)
        if runner and winner and runner in choices and runner != winner.get("id"):
            out.append(it)
    return out


def _winner_first(item_id: str) -> bool:
    """Deterministic, id-stable side shuffle (crc32, not the salted str hash)."""
    return zlib.crc32(item_id.encode("utf-8")) % 2 == 0


def _to_fork_item(raw: dict[str, Any], meta: dict[str, dict[str, Any]]) -> ForkItem:
    from speedrun.config import latency_budget_ms

    choices = {c.get("id"): c for c in raw.get("choices", [])}
    winner = next(c for c in choices.values() if c.get("correct"))
    fork = raw.get("two_answer_fork") or {}
    runner = choices[fork["runner_up"]]

    pair = [
        ForkChoice(id=winner.get("id", ""), text=winner.get("text", "")),
        ForkChoice(id=runner.get("id", ""), text=runner.get("text", "")),
    ]
    if not _winner_first(raw.get("id", "")):
        pair.reverse()

    trap = runner.get("trap") or ""
    tmeta = meta.get(trap, {})
    flaw = _flaw_of(raw.get("schemas", [])) or ""
    section = raw.get("section", "")
    return ForkItem(
        id=raw.get("id", ""),
        section=section,
        stimulus=raw.get("stimulus") or raw.get("passage") or "",
        question=raw.get("question", ""),
        choices=pair,
        winner_id=winner.get("id", ""),
        runner_up_id=runner.get("id", ""),
        runner_trap=trap,
        runner_trap_label=schema_label(trap) if trap else "",
        runner_trap_description=tmeta.get("description", ""),
        why_runner_up_wrong=fork.get("why_runner_up_wrong", ""),
        flaw_id=flaw,
        flaw_label=schema_label(flaw) if flaw else "",
        budget_ms=latency_budget_ms(section or None),
    )


def _trap_options(meta: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Every trap schema in the taxonomy, grouped for the 'why does the loser
    lose?' picker. Includes traps not present in the current set: the student
    must discriminate, not eliminate (SPOV2)."""
    opts: list[dict[str, Any]] = []
    for sid, m in meta.items():
        if not sid.startswith(TRAP_PREFIX):
            continue
        cat = m.get("category") or ""
        opts.append(
            {
                "id": sid,
                "label": schema_label(sid),
                "category": cat,
                "category_label": category_label(f"trap.{cat}") if cat else "",
            }
        )
    opts.sort(key=lambda o: (o["category_label"], o["label"]))
    return opts


def build_fork_set(
    col=None,
    *,
    count: int | None = None,
    seed_path: Path = DEFAULT_SEED,
    taxonomy_path: Path = DEFAULT_TAXONOMY,
) -> ForkSet:
    """Build up to ``count`` fork prompts, weakest flaw family first.

    Deterministic given the same inputs: items are grouped by the flaw family
    of the underlying argument and ordered weakest-first when a collection is
    supplied (else by exam weight); non-flaw items (RC) come last, by id."""
    if count is None:
        from speedrun.config import fork_trainer_count

        count = fork_trainer_count()

    meta = _load_taxonomy_meta(taxonomy_path)
    raw_items = load_fork_items(seed_path)

    by_category: dict[str, list[dict[str, Any]]] = {}
    tail: list[dict[str, Any]] = []
    for raw in raw_items:
        flaw = _flaw_of(raw.get("schemas", []))
        cat = (meta.get(flaw) or {}).get("category") if flaw else None
        if cat:
            by_category.setdefault(cat, []).append(raw)
        else:
            tail.append(raw)

    ordered_cats = _category_order(col, list(by_category), meta)

    items: list[ForkItem] = []
    for cat in ordered_cats:
        for raw in sorted(by_category[cat], key=lambda r: r.get("id", "")):
            items.append(_to_fork_item(raw, meta))
    for raw in sorted(tail, key=lambda r: r.get("id", "")):
        items.append(_to_fork_item(raw, meta))

    items = items[: max(0, count)]
    options = _trap_options(meta)
    stats = {
        "n_items": len(items),
        "sections": sorted({it.section for it in items}),
        "n_trap_options": len(options),
    }
    return ForkSet(items=items, trap_options=options, stats=stats)


_FORK_CSS = """
.sr-fk { max-width: 860px; }
.sr-fk-top { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.sr-fk-progress { font-size: 0.8rem; color: var(--muted); font-weight: 600; }
.sr-fk-badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.7rem;
  font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
  background: rgba(37,99,235,0.14); color: var(--accent); }
.sr-fk-timer { margin-left: auto; font-variant-numeric: tabular-nums; font-weight: 700;
  font-size: 0.9rem; color: var(--muted); }
.sr-fk-timer.over { color: var(--low); }
.sr-fk-stim { border: 1px solid var(--border); border-radius: 12px; background: var(--surface);
  padding: 16px 18px; font-size: 0.95rem; line-height: 1.5; margin-bottom: 12px; }
.sr-fk-q { font-weight: 600; font-size: 0.9rem; margin: 4px 0 12px; }
.sr-fk-duel { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 640px) { .sr-fk-duel { grid-template-columns: 1fr; } }
.sr-fk-choice { text-align: left; cursor: pointer; border: 2px solid var(--border); background: var(--surface);
  color: var(--text); border-radius: 12px; padding: 14px 16px; font-size: 0.9rem; font-family: inherit;
  line-height: 1.45; }
.sr-fk-choice:hover { border-color: var(--accent); }
.sr-fk-choice .cid { display:inline-block; font-weight: 800; margin-right: 8px; color: var(--accent); }
.sr-fk-choice.correct { border-color: var(--high); background: rgba(22,163,74,0.10); }
.sr-fk-choice.chosen-wrong { border-color: var(--low); background: rgba(220,38,38,0.08); }
.sr-fk-hint { font-size: 0.82rem; color: var(--muted); margin: 10px 0; }
.sr-fk-ask { font-weight: 700; font-size: 0.95rem; margin: 14px 0 8px; }
.sr-fk-conf { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin:10px 0; }
.sr-fk-conf-lbl { font-size:0.85rem; color:var(--muted); font-weight:600; }
.sr-btn.conf.sel { background: var(--accent); color:#fff; border-color: var(--accent); }
.sr-fk-select { width: 100%; font-family: inherit; font-size: 0.9rem; padding: 10px 12px;
  border: 1px solid var(--border); border-radius: 10px; background: var(--bg); color: var(--text); }
.sr-fk-actions { display: flex; gap: 10px; margin: 14px 0; flex-wrap: wrap; }
.sr-btn { cursor: pointer; border: 1px solid var(--border); background: var(--surface); color: var(--text);
  border-radius: 8px; padding: 8px 16px; font-size: 0.85rem; font-weight: 600; }
.sr-btn:disabled { opacity: 0.5; cursor: default; }
.sr-btn.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
.sr-fk-reveal { border: 1px solid var(--border); border-radius: 12px; background: var(--surface);
  padding: 16px 18px; margin-top: 14px; }
.sr-fk-verdict { display: flex; gap: 18px; flex-wrap: wrap; margin-bottom: 12px; font-size: 0.9rem; font-weight: 700; }
.sr-fk-verdict .ok { color: var(--high); } .sr-fk-verdict .no { color: var(--low); }
.sr-fk-scaffold { font-size: 0.9rem; line-height: 1.5; border-left: 3px solid var(--accent);
  padding-left: 12px; margin: 10px 0; }
.sr-fk-trap { font-size: 0.85rem; color: var(--muted); margin-top: 8px; }
.sr-fk-trap b { color: var(--text); }
.sr-fk-lat { font-size: 0.82rem; color: var(--muted); margin-top: 10px; }
.sr-fk-lat .over { color: var(--low); font-weight: 700; }
.sr-fk-done { border: 1px solid var(--border); border-radius: 12px; background: var(--surface); padding: 22px;
  text-align: center; }
.sr-fk-done h2 { margin: 0 0 10px; }
.sr-fk-scores { display: flex; gap: 26px; justify-content: center; flex-wrap: wrap; margin: 10px 0; }
.sr-fk-scores .num { font-size: 1.9rem; font-weight: 800; }
.sr-fk-scores .lbl { font-size: 0.78rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
.sr-fk-note { font-size: 0.85rem; color: var(--muted); margin-top: 12px; }
"""

_FORK_JS = """
(function () {
  const holder = document.getElementById('sr-fk');
  if (!holder) return;
  const data = JSON.parse(document.getElementById('sr-fk-data').textContent);
  const items = data.items;
  const options = data.trap_options || [];
  let idx = 0;
  let picked = null;
  let pickedAt = 0;
  let startedAt = 0;
  let timerId = null;
  let lastWhy = '';
  const tally = { fork: 0, trap: 0, n: 0, latSum: 0, inBudget: 0 };
  const stage = document.getElementById('sr-fk-stage');

  function esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
  function fmtSec(ms) { return (ms / 1000).toFixed(1) + 's'; }

  function optionsHtml() {
    const groups = {}; const order = [];
    options.forEach(function (o) {
      if (!groups[o.category_label]) { groups[o.category_label] = []; order.push(o.category_label); }
      groups[o.category_label].push(o);
    });
    let h = '<option value="">— name the trap that sinks the loser —</option>';
    order.forEach(function (g) {
      h += '<optgroup label="' + esc(g) + '">';
      groups[g].forEach(function (o) { h += '<option value="' + esc(o.id) + '">' + esc(o.label) + '</option>'; });
      h += '</optgroup>';
    });
    return h;
  }

  function head(it) {
    return '<div class="sr-fk-top"><span class="sr-fk-progress">Fork ' + (idx + 1) + ' of ' + items.length + '</span>' +
      '<span class="sr-fk-badge">' + esc(it.section) + '</span>' +
      '<span class="sr-fk-timer" id="sr-fk-timer">0.0s</span></div>';
  }

  function startTimer(it) {
    startedAt = Date.now();
    if (timerId) clearInterval(timerId);
    timerId = setInterval(function () {
      const el = document.getElementById('sr-fk-timer');
      if (!el) return;
      const ms = Date.now() - startedAt;
      el.textContent = fmtSec(ms);
      if (ms > it.budget_ms) el.classList.add('over');
    }, 100);
  }

  function stopTimer() { if (timerId) { clearInterval(timerId); timerId = null; } }

  function renderDuel() {
    const it = items[idx];
    let duel = '<div class="sr-fk-duel">';
    it.choices.forEach(function (c) {
      duel += '<button class="sr-fk-choice" data-cid="' + esc(c.id) + '">' +
        '<span class="cid">' + esc(c.id) + '</span>' + esc(c.text) + '</button>';
    });
    duel += '</div>';
    stage.innerHTML = head(it) +
      '<div class="sr-fk-stim">' + esc(it.stimulus) + '</div>' +
      '<div class="sr-fk-q">' + esc(it.question) + '</div>' +
      '<div class="sr-fk-hint">Every other answer is gone. This is the final two-answer decision — pick the winner.</div>' +
      duel;
    startTimer(it);
    stage.querySelectorAll('[data-cid]').forEach(function (b) {
      b.addEventListener('click', function () {
        picked = b.dataset.cid;
        pickedAt = Date.now() - startedAt;
        stopTimer();
        renderTrapStep();
      });
    });
  }

  function renderTrapStep() {
    const it = items[idx];
    const loserId = picked === it.winner_id ? it.runner_up_id : it.winner_id;
    stage.innerHTML = head(it) +
      '<div class="sr-fk-stim">' + esc(it.stimulus) + '</div>' +
      '<div class="sr-fk-ask">You picked (' + esc(picked) + '). Before the reveal: the runner-up answer is a trap — which trap?</div>' +
      '<div class="sr-fk-hint">Being able to say precisely why the loser loses is the transferable skill (Insight 8).</div>' +
      '<select class="sr-fk-select" id="sr-fk-pick">' + optionsHtml() + '</select>' +
      '<div class="sr-fk-conf" id="sr-fk-conf"><span class="sr-fk-conf-lbl">How sure is your pick?</span>' +
      '<button class="sr-btn conf" data-c="0.5">Guess</button>' +
      '<button class="sr-btn conf" data-c="0.75">Fairly sure</button>' +
      '<button class="sr-btn conf" data-c="0.95">Certain</button></div>' +
      '<div class="sr-fk-explain"><label class="sr-fk-ask" for="sr-fk-why">In one sentence, why is the runner-up wrong?</label>' +
      '<div class="sr-fk-hint">Optional — putting the reasoning into words is the scaffold that never fades (SPOV3 / Insight 5). It is graded against the fork rationale.</div>' +
      '<textarea class="sr-fk-select" id="sr-fk-why" rows="2" placeholder="e.g. it is out of scope — it never addresses the conclusion"></textarea></div>' +
      '<div class="sr-fk-actions"><button class="sr-btn primary" id="sr-fk-lock" disabled>Lock in &amp; reveal</button></div>';
    const timerEl = document.getElementById('sr-fk-timer');
    if (timerEl) { timerEl.textContent = fmtSec(pickedAt); if (pickedAt > it.budget_ms) timerEl.classList.add('over'); }
    const sel = document.getElementById('sr-fk-pick');
    const lock = document.getElementById('sr-fk-lock');
    let conf = null;
    function refresh() { lock.disabled = !(sel.value && conf !== null); }
    sel.addEventListener('change', refresh);
    stage.querySelectorAll('#sr-fk-conf .conf').forEach(function (b) {
      b.addEventListener('click', function () {
        conf = parseFloat(b.dataset.c);
        stage.querySelectorAll('#sr-fk-conf .conf').forEach(function (x) { x.classList.remove('sel'); });
        b.classList.add('sel');
        refresh();
      });
    });
    lock.addEventListener('click', function () {
      const whyEl = document.getElementById('sr-fk-why');
      grade(sel.value, loserId, conf, whyEl ? whyEl.value : '');
    });
  }

  function grade(trapPick, loserId, confidence, why) {
    const it = items[idx];
    lastWhy = (why || '').trim();
    const forkOk = picked === it.winner_id;
    const trapOk = trapPick === it.runner_trap;
    const overBudget = pickedAt > it.budget_ms;
    tally.n += 1;
    if (forkOk) tally.fork += 1;
    if (trapOk) tally.trap += 1;
    tally.latSum += pickedAt;
    if (!overBudget) tally.inBudget += 1;
    try {
      if (typeof pycmd === 'function') {
        pycmd('speedrun:fork:' + JSON.stringify({
          item_id: it.id, picked: picked, fork_correct: forkOk,
          trap_pick: trapPick, actual_trap: it.runner_trap, trap_correct: trapOk,
          confidence: confidence,
          latency_ms: Math.round(pickedAt), budget_ms: it.budget_ms, over_budget: overBudget
        }));
      }
    } catch (e) {}
    renderReveal(forkOk, trapPick, trapOk, overBudget);
  }

  function trapLabel(id) {
    for (let i = 0; i < options.length; i++) { if (options[i].id === id) return options[i].label; }
    return id;
  }

  function renderReveal(forkOk, trapPick, trapOk, overBudget) {
    const it = items[idx];
    let duel = '<div class="sr-fk-duel">';
    it.choices.forEach(function (c) {
      let cls = 'sr-fk-choice';
      if (c.id === it.winner_id) cls += ' correct';
      else if (c.id === picked) cls += ' chosen-wrong';
      duel += '<div class="' + cls + '"><span class="cid">' + esc(c.id) + '</span>' + esc(c.text) + '</div>';
    });
    duel += '</div>';
    stage.innerHTML = head(it) +
      '<div class="sr-fk-stim">' + esc(it.stimulus) + '</div>' +
      '<div class="sr-fk-q">' + esc(it.question) + '</div>' + duel +
      '<div class="sr-fk-reveal">' +
      '<div class="sr-fk-verdict">' +
      '<span class="' + (forkOk ? 'ok' : 'no') + '">Fork: ' + (forkOk ? 'won' : 'lost') + '</span>' +
      '<span class="' + (trapOk ? 'ok' : 'no') + '">Trap-ID: ' + (trapOk ? 'correct' : 'missed') + '</span>' +
      '</div>' +
      '<div class="sr-fk-scaffold">' + esc(it.why_runner_up_wrong) + '</div>' +
      '<div class="sr-fk-trap">The runner-up (' + esc(it.runner_up_id) + ') is <b>' + esc(it.runner_trap_label) + '</b>' +
      (trapOk ? '' : ' — you said ' + esc(trapLabel(trapPick))) + '.' +
      (it.runner_trap_description ? ' ' + esc(it.runner_trap_description) : '') + '</div>' +
      (it.flaw_label ? '<div class="sr-fk-trap">Underlying flaw: <b>' + esc(it.flaw_label) + '</b></div>' : '') +
      '<div class="sr-fk-lat">Decision time ' + fmtSec(pickedAt) +
      (overBudget ? ' <span class="over">over the ' + fmtSec(it.budget_ms) + ' budget — a right answer that costs points elsewhere (SPOV4)</span>'
                  : ' — within the ' + fmtSec(it.budget_ms) + ' budget') + '</div>' +
      (lastWhy ? '<div class="sr-fk-scaffold" id="sr-fk-reasoning">Grading your explanation\u2026</div>' : '') +
      '<div class="sr-fk-actions"><button class="sr-btn primary" id="sr-fk-next">' +
      (idx + 1 >= items.length ? 'See results' : 'Next fork') + '</button></div></div>';
    const timerEl = document.getElementById('sr-fk-timer');
    if (timerEl) { timerEl.textContent = fmtSec(pickedAt); if (overBudget) timerEl.classList.add('over'); }
    gradeExplanation(it);
    document.getElementById('sr-fk-next').addEventListener('click', function () { idx += 1; render(); });
  }

  function gradeExplanation(it) {
    const box = document.getElementById('sr-fk-reasoning');
    if (!box || !lastWhy) return;
    if (typeof pycmd !== 'function') {
      box.textContent = 'Explanation captured. Reopen inside the app to grade it against the fork rationale.';
      return;
    }
    // §14.2: grade the student's runner-up-vs-winner explanation against the
    // item's fork rationale; recurring weakness patterns are surfaced app-side.
    pycmd('speedrun:reasoning:' + JSON.stringify({
      item_id: it.id, student_text: lastWhy,
      expected_schema: it.runner_trap, fork_rationale: it.why_runner_up_wrong
    }), function (resp) {
      let r = (typeof resp === 'string') ? JSON.parse(resp) : (resp || {});
      const pct = (typeof r.score === 'number') ? Math.round(r.score * 100) + '% match · ' : '';
      const src = r.source ? (' (' + esc(r.source) + ')') : '';
      box.innerHTML = '<b>Your explanation:</b> ' + pct + esc(r.feedback || 'Explanation recorded.') + src;
    });
  }

  function pct(n, d) { return d ? Math.round((n / d) * 100) : 0; }

  function render() {
    if (idx >= items.length) {
      stopTimer();
      const fp = pct(tally.fork, tally.n), tp = pct(tally.trap, tally.n);
      const ib = pct(tally.inBudget, tally.n);
      const avg = tally.n ? fmtSec(tally.latSum / tally.n) : '0.0s';
      stage.innerHTML = '<div class="sr-fk-done"><h2>Fork session complete</h2>' +
        '<div class="sr-fk-scores">' +
        '<div><div class="num" style="color:var(--high)">' + fp + '%</div><div class="lbl">Fork accuracy</div></div>' +
        '<div><div class="num" style="color:var(--accent)">' + tp + '%</div><div class="lbl">Trap&#8209;ID accuracy</div></div>' +
        '<div><div class="num">' + avg + '</div><div class="lbl">Avg decision</div></div>' +
        '<div><div class="num" style="color:' + (ib < 70 ? 'var(--low)' : 'var(--text)') + '">' + ib + '%</div><div class="lbl">In budget</div></div>' +
        '</div>' +
        '<div class="sr-fk-note">The two-answer fork is where high scorers keep losing points (SPOV3), ' +
        'so its explanation never fades here. These are training signals only and do not change your scores.</div></div>';
      return;
    }
    picked = null;
    lastWhy = '';
    renderDuel();
  }
  render();
})();
"""


def _fork_body(fset: ForkSet) -> str:
    """Inner fork-trainer markup (style + content + script) without the page shell."""
    if not fset.items:
        return (
            '<div class="sr-header"><h1>Two-answer fork trainer</h1></div>'
            '<div class="sr-empty">No fork items available yet. Import the seed deck '
            "(Tools &rarr; LSAT Speedrun &rarr; Import seed deck); forks are built "
            "from items that carry a two-answer-fork rationale.</div>"
        )
    data_json = json.dumps(fset.to_dict()).replace("<", "\\u003c")
    intro = (
        f"{fset.stats['n_items']} forks &middot; only the two finalists are shown. "
        "Pick the winner under the clock, then name the trap that sinks the loser."
    )
    return (
        f"<style>{_FORK_CSS}</style>"
        '<div class="sr-header"><h1>Two-answer fork trainer</h1>'
        f"<p>{intro}</p></div>"
        '<div class="sr-fk" id="sr-fk"><div id="sr-fk-stage"></div>'
        f'<script type="application/json" id="sr-fk-data">{data_json}</script></div>'
        f"<script>{_FORK_JS}</script>"
    )


def render_fork_trainer_html(fset: ForkSet, *, embed: bool = False) -> str:
    """Render the interactive two-answer fork trainer.

    ``embed=False`` returns a full standalone HTML document; ``embed=True``
    returns body-only markup with the dashboard stylesheet inlined, for
    injection into an AnkiWebView (which supplies ``pycmd`` but not our CSS)."""
    from speedrun.dashboard import _DASHBOARD_CSS, _shell

    inner = _fork_body(fset)
    if embed:
        return f'<style>{_DASHBOARD_CSS}</style><div class="sr-dash">{inner}</div>'
    return _shell(inner, title="Two-answer fork trainer")


def record_fork_result(logger, payload: dict[str, Any]) -> None:
    """Persist one fork result via a SessionLogger.

    ``payload`` carries item_id, picked, fork_correct, trap_pick, actual_trap,
    trap_correct, latency_ms, budget_ms and over_budget. Self-driven training
    signal only -- it must never feed the scores (honesty rule)."""
    if logger._current is None or logger._current.mode != "fork":
        logger.start(mode="fork")
    import time

    from speedrun.session_logger import SessionEvent

    # §8.2 / SPOV2: the trap the student actually *fell for* is the runner-up's
    # trap type, and only when they picked the runner-up (fork wrong). This is the
    # first-class ``chosen_trap_type`` of the attempt — the habitual-trap signal,
    # distinct from ``trap_pick`` (the student's *diagnosis* of the loser's trap).
    fork_correct = bool(payload.get("fork_correct"))
    chosen_trap_type = None if fork_correct else payload.get("actual_trap")

    ev = SessionEvent(
        ts=int(time.time()),
        event="fork",
        schema=payload.get("actual_trap"),
        latency_ms=payload.get("latency_ms"),
        extra={
            "item_id": payload.get("item_id"),
            "picked": payload.get("picked"),
            "fork_correct": fork_correct,
            "trap_pick": payload.get("trap_pick"),
            "actual_trap": payload.get("actual_trap"),
            "trap_correct": bool(payload.get("trap_correct")),
            "chosen_trap_type": chosen_trap_type,
            "confidence": payload.get("confidence"),
            "budget_ms": payload.get("budget_ms"),
            "over_budget": bool(payload.get("over_budget")),
        },
    )
    logger._current.events.append(ev)
    logger._append(
        {"type": "fork", "session_id": logger._current.session_id, **ev.to_dict()}
    )


def fork_summary(log_path: Path | None = None) -> dict[str, Any]:
    """Summarise fork practice for the dashboard.

    Honesty-safe: fork accuracy, trap-ID accuracy and pacing are reported as
    training signal; none of it feeds the scores. Also aggregates the traps the
    student most often mis-names -- the habitual-trap diagnostic (Insight 8)."""
    from speedrun.session_logger import DEFAULT_LOG, load_sessions

    records = load_sessions(log_path or DEFAULT_LOG, limit=4000)
    events = [r for r in records if r.get("type") == "fork"]
    n = len(events)
    if n == 0:
        return {
            "n": 0,
            "fork_accuracy": None,
            "trap_id_accuracy": None,
            "avg_latency_ms": None,
            "in_budget_rate": None,
            "missed_traps": [],
            "chosen_traps": [],
        }
    extras = [e.get("extra", {}) for e in events]
    fork_hits = sum(1 for e in extras if e.get("fork_correct"))
    trap_hits = sum(1 for e in extras if e.get("trap_correct"))
    lats = [e.get("latency_ms") for e in events if e.get("latency_ms") is not None]
    in_budget = sum(1 for e in extras if not e.get("over_budget"))

    from collections import Counter

    missed = Counter(
        e.get("actual_trap")
        for e in extras
        if not e.get("trap_correct") and e.get("actual_trap")
    )
    missed_traps = [
        {"trap": t, "label": schema_label(t), "misses": c}
        for t, c in missed.most_common(3)
    ]
    # SPOV2 / Insight 8: the traps the student actually *fell for* (chose the
    # runner-up), ranked. Distinct from ``missed_traps`` (mis-*named* traps).
    chosen = Counter(
        e.get("chosen_trap_type") for e in extras if e.get("chosen_trap_type")
    )
    chosen_traps = [
        {"trap": t, "label": schema_label(t), "count": c}
        for t, c in chosen.most_common(3)
    ]
    return {
        "n": n,
        "fork_accuracy": round(fork_hits / n, 4),
        "trap_id_accuracy": round(trap_hits / n, 4),
        "avg_latency_ms": round(sum(lats) / len(lats)) if lats else None,
        "in_budget_rate": round(in_budget / n, 4),
        "missed_traps": missed_traps,
        "chosen_traps": chosen_traps,
    }
