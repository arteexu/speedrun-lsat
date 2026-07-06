# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Minimal reviewer hooks: post-review toast and optional sidebar stats."""

from __future__ import annotations

import sys
from pathlib import Path

from aqt.qt import QDockWidget, QLabel, Qt, QWidget, qconnect
from aqt.utils import tooltip


def _ensure_speedrun_on_path() -> bool:
    here = Path(__file__).resolve()
    candidates = [Path.cwd()]
    if len(here.parents) > 4:
        candidates.append(here.parents[4])
    for cand in candidates:
        if (cand / "speedrun" / "scoring" / "memory.py").exists():
            if str(cand) not in sys.path:
                sys.path.insert(0, str(cand))
            return True
    return False


def _schema_from_card(card) -> str | None:
    for tag in card.note().tags:
        if tag.startswith("sr:schema:"):
            return tag[len("sr:schema:") :]
    return None


def _section_from_note(note) -> str:
    for tag in note.tags:
        if tag.startswith("sr:section:"):
            return tag[len("sr:section:") :]
    return "LR"


def on_reviewer_did_answer(reviewer, card, ease: int) -> None:
    """Post-review feedback toast: schema, latency vs budget, retrievability."""
    if not _ensure_speedrun_on_path():
        return
    schema = _schema_from_card(card)
    if schema is None:
        return
    try:
        import time

        from speedrun.config import latency_budget_ms
        from speedrun.scoring.memory import collection_memory_records

        col = reviewer.mw.col
        section = _section_from_note(card.note())
        budget = latency_budget_ms(section)
        latency_ms = (
            int((time.time() - reviewer._speedrun_card_start) * 1000)
            if hasattr(reviewer, "_speedrun_card_start")
            else 0
        )
        on_budget = ease != 1 and latency_ms <= budget
        retr = None
        for s, r in collection_memory_records(col):
            if s == schema and r is not None:
                retr = r
                break
        parts = [schema.split(".")[-1]]
        if latency_ms:
            parts.append(f"{latency_ms // 1000}s vs {budget // 1000}s budget")
        parts.append("on-budget" if on_budget else "over budget / miss")
        if retr is not None:
            parts.append(f"R={retr:.0%}")
        tooltip("Speedrun · " + " · ".join(parts))
        if hasattr(reviewer, "_speedrun_session_stats"):
            reviewer._speedrun_session_stats["reviews"] += 1
            if ease != 1:
                reviewer._speedrun_session_stats["hits"] += 1
            _update_sidebar(reviewer)
    except Exception:
        pass


def on_reviewer_will_show_question(reviewer, card) -> None:
    import time

    reviewer._speedrun_card_start = time.time()
    if not hasattr(reviewer, "_speedrun_session_stats"):
        reviewer._speedrun_session_stats = {"reviews": 0, "hits": 0}
    _update_sidebar(reviewer, card=card)


def _update_sidebar(reviewer, card=None) -> None:
    dock = getattr(reviewer.mw, "_speedrun_sidebar", None)
    if dock is None:
        return
    label = dock.widget().findChild(QLabel, "speedrun_sidebar_label")
    if label is None:
        return
    schema = _schema_from_card(card) if card else None
    stats = getattr(reviewer, "_speedrun_session_stats", {"reviews": 0, "hits": 0})
    acc = stats["hits"] / stats["reviews"] if stats["reviews"] else 0
    label.setText(
        f"Schema: {schema or '—'}\nSession: {stats['reviews']} reviews · {acc:.0%} hits"
    )


def install_sidebar(mw) -> None:
    """Optional dock widget with current schema + session stats."""
    if getattr(mw, "_speedrun_sidebar", None) is not None:
        return
    dock = QDockWidget("Speedrun", mw)
    dock.setObjectName("SpeedrunSidebar")
    widget = QWidget()
    label = QLabel("Schema: —\nSession: 0 reviews")
    label.setObjectName("speedrun_sidebar_label")
    label.setWordWrap(True)
    from aqt.qt import QVBoxLayout

    layout = QVBoxLayout(widget)
    layout.addWidget(label)
    dock.setWidget(widget)
    mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    mw._speedrun_sidebar = dock


def hook_reviewer(reviewer) -> None:
    """Attach speedrun hooks to an open reviewer instance."""
    qconnect(
        reviewer.didAnswerCard,
        lambda ease: on_reviewer_did_answer(reviewer, reviewer.card, ease),
    )
    qconnect(
        reviewer.showQuestion,
        lambda: on_reviewer_will_show_question(reviewer, reviewer.card),
    )


# --------------------------------------------------------------------------- #
# Speedrun-native review flow (§9/§11): grade due cards in schema-weighted
# priority order through the shared Rust scheduler.
#
# Native Anki filtered decks cannot reproduce an arbitrary priority order (see
# the comment in focus.py), so the live "Study now" path used to fall back to
# native scheduler order and never actually applied the schema-weighted queue.
# This surface walks `SchemaWeightedReview` (which snapshots the Rust-ordered
# queue and grades via `col.sched.answerCard`, mirroring the iOS ReviewView) so
# the graded order matches priority, latency is recorded, undo works, and no
# review is lost or double-counted. All the correctness lives in the tested,
# Qt-free session core; this module only renders it and relays button presses.
# --------------------------------------------------------------------------- #


def _note_field(note, name: str) -> str:
    try:
        return (note[name] or "").strip()
    except Exception:
        return ""


def build_review_cards(col, session) -> list:
    """Per-card render data for the queued review, in schema-weighted order.

    Renders each card's question/answer HTML once (via Anki's own card render)
    and carries the two-answer-fork rationale when the underlying item has one,
    so the review flow can show the runner-up-vs-winner scaffold on hard items
    (SPOV3 / §11 fork-in-review)."""
    out = []
    for cid in session.card_ids():
        try:
            card = col.get_card(cid)
            note = card.note()
            out.append(
                {
                    "card_id": int(cid),
                    "schema": session._schema.get(int(cid), ""),
                    "section": _section_from_note(note),
                    "question": card.question(),
                    "answer": card.answer(),
                    "runner_up": _note_field(note, "RunnerUp"),
                    "why_runner_up_wrong": _note_field(note, "WhyRunnerUpWrong"),
                }
            )
        except Exception:
            continue
    return out


_REVIEW_CSS = """
.sr-rv { max-width: 820px; }
.sr-rv-top { display:flex; align-items:center; gap:12px; margin-bottom:14px; }
.sr-rv-progress { font-size:0.8rem; color:var(--muted); font-weight:600; }
.sr-rv-badge { display:inline-block; padding:2px 10px; border-radius:999px; font-size:0.7rem;
  font-weight:700; text-transform:uppercase; letter-spacing:0.04em;
  background:rgba(37,99,235,0.14); color:var(--accent); }
.sr-rv-timer { margin-left:auto; font-variant-numeric:tabular-nums; font-weight:700;
  font-size:0.9rem; color:var(--muted); }
.sr-rv-timer.over { color:var(--low); }
.sr-rv-card { border:1px solid var(--border); border-radius:12px; background:var(--surface);
  padding:18px 20px; font-size:0.98rem; line-height:1.55; margin-bottom:14px; }
.sr-rv-actions { display:flex; gap:10px; flex-wrap:wrap; margin:14px 0; }
.sr-btn { cursor:pointer; border:1px solid var(--border); background:var(--surface); color:var(--text);
  border-radius:8px; padding:9px 16px; font-size:0.85rem; font-weight:600; }
.sr-btn:disabled { opacity:0.5; cursor:default; }
.sr-btn.primary { background:var(--accent); color:#fff; border-color:var(--accent); }
.sr-btn.again { border-color:var(--low); color:var(--low); }
.sr-btn.good { background:var(--high); color:#fff; border-color:var(--high); }
.sr-rv-fork { border:1px solid var(--border); border-left:3px solid var(--accent); border-radius:12px;
  background:var(--surface); padding:14px 16px; margin:14px 0; font-size:0.9rem; line-height:1.5; }
.sr-rv-fork h4 { margin:0 0 6px; font-size:0.82rem; text-transform:uppercase; letter-spacing:0.04em;
  color:var(--muted); }
.sr-rv-done { border:1px solid var(--border); border-radius:12px; background:var(--surface); padding:26px;
  text-align:center; }
.sr-rv-undo { font-size:0.8rem; }
"""

_REVIEW_JS = r"""
(function () {
  const holder = document.getElementById('sr-rv');
  if (!holder) return;
  const cards = JSON.parse(document.getElementById('sr-rv-data').textContent);
  const stage = document.getElementById('sr-rv-stage');
  let idx = 0;
  let revealed = false;
  let shownAt = 0;
  let timerId = null;
  let graded = 0;

  function fmtSec(ms) { return (ms / 1000).toFixed(1) + 's'; }
  function hasBridge() { return typeof pycmd === 'function'; }

  function startTimer() {
    shownAt = Date.now();
    if (timerId) clearInterval(timerId);
    timerId = setInterval(function () {
      const el = document.getElementById('sr-rv-timer');
      if (el) el.textContent = fmtSec(Date.now() - shownAt);
    }, 100);
  }
  function stopTimer() { if (timerId) { clearInterval(timerId); timerId = null; } }

  function head(c) {
    const schema = c.schema ? c.schema.split('.').pop().replace(/_/g, ' ') : '—';
    return '<div class="sr-rv-top">' +
      '<span class="sr-rv-progress">Card ' + (idx + 1) + ' of ' + cards.length + '</span>' +
      '<span class="sr-rv-badge">' + (c.section || 'LR') + ' · ' + schema + '</span>' +
      '<span class="sr-rv-timer" id="sr-rv-timer">0.0s</span></div>';
  }

  function forkPanel(c) {
    if (!c.why_runner_up_wrong) return '';
    return '<div class="sr-rv-fork"><h4>Two-answer fork — the scaffold that never fades (SPOV3)</h4>' +
      (c.runner_up ? '<b>Why the runner-up (' + c.runner_up + ') is wrong:</b> ' : '<b>Why the runner-up is wrong:</b> ') +
      c.why_runner_up_wrong + '</div>';
  }

  function undoBtn() {
    if (idx === 0 && graded === 0) return '';
    return '<button class="sr-btn sr-rv-undo" id="sr-rv-undo">Undo last</button>';
  }

  function renderQuestion() {
    const c = cards[idx];
    revealed = false;
    stage.innerHTML = head(c) +
      '<div class="sr-rv-card">' + c.question + '</div>' +
      '<div class="sr-rv-actions"><button class="sr-btn primary" id="sr-rv-show">Show answer</button>' +
      undoBtn() + '</div>';
    startTimer();
    document.getElementById('sr-rv-show').addEventListener('click', renderAnswer);
    wireUndo();
  }

  function renderAnswer() {
    const c = cards[idx];
    revealed = true;
    stage.innerHTML = head(c) +
      '<div class="sr-rv-card">' + c.answer + '</div>' +
      forkPanel(c) +
      '<div class="sr-rv-actions">' +
      '<button class="sr-btn again" data-ease="1">Again</button>' +
      '<button class="sr-btn" data-ease="2">Hard</button>' +
      '<button class="sr-btn good" data-ease="3">Good</button>' +
      '<button class="sr-btn" data-ease="4">Easy</button>' +
      undoBtn() + '</div>';
    const el = document.getElementById('sr-rv-timer');
    if (el) el.textContent = fmtSec(Date.now() - shownAt);
    stage.querySelectorAll('[data-ease]').forEach(function (b) {
      b.addEventListener('click', function () { grade(parseInt(b.dataset.ease, 10)); });
    });
    wireUndo();
  }

  function grade(ease) {
    const c = cards[idx];
    const latency = Date.now() - shownAt;
    stopTimer();
    if (hasBridge()) {
      pycmd('speedrun:review:grade:' + JSON.stringify({
        card_id: c.card_id, ease: ease, latency_ms: Math.round(latency)
      }));
    }
    graded += 1;
    idx += 1;
    render();
  }

  function wireUndo() {
    const u = document.getElementById('sr-rv-undo');
    if (!u) return;
    u.addEventListener('click', function () {
      if (idx === 0 && graded === 0) return;
      if (hasBridge()) pycmd('speedrun:review:undo');
      if (idx > 0) idx -= 1;
      if (graded > 0) graded -= 1;
      render();
    });
  }

  function render() {
    if (idx >= cards.length) {
      stopTimer();
      stage.innerHTML = '<div class="sr-rv-done"><h2>Review set complete</h2>' +
        '<p>' + graded + ' card(s) graded in schema-weighted priority order on the shared engine.</p>' +
        '<div class="sr-rv-actions" style="justify-content:center">' + undoBtn() +
        '<button class="sr-btn primary" onclick="if(typeof pycmd===\'function\')pycmd(\'close\')">Done</button></div></div>';
      wireUndo();
      return;
    }
    renderQuestion();
  }
  render();
})();
"""


def render_schema_weighted_review_html(cards: list, *, embed: bool = True) -> str:
    """Render the Speedrun-native review surface for a queued, ordered card set.

    ``embed=True`` returns body-only markup with the dashboard stylesheet inlined
    for injection into an AnkiWebView (which supplies pycmd/media but not our
    CSS)."""
    import json as _json

    from speedrun.dashboard import _DASHBOARD_CSS, _shell

    if not cards:
        inner = (
            '<div class="sr-header"><h1>Review</h1></div>'
            '<div class="sr-empty">Nothing due right now. Import the seed deck or '
            "come back when cards are due.</div>"
        )
        if embed:
            return f'<style>{_DASHBOARD_CSS}</style><div class="sr-dash">{inner}</div>'
        return _shell(inner, title="Review")

    data_json = _json.dumps(cards).replace("<", "\\u003c")
    intro = (
        f"{len(cards)} card(s), ordered by schema points-at-stake (§9). Each grade "
        "is a real review on the shared Rust scheduler."
    )
    inner = (
        f"<style>{_REVIEW_CSS}</style>"
        '<div class="sr-header"><h1>Schema-weighted review</h1>'
        f"<p>{intro}</p></div>"
        '<div class="sr-rv" id="sr-rv"><div id="sr-rv-stage"></div>'
        f'<script type="application/json" id="sr-rv-data">{data_json}</script></div>'
        f"<script>{_REVIEW_JS}</script>"
    )
    if embed:
        return f'<style>{_DASHBOARD_CSS}</style><div class="sr-dash">{inner}</div>'
    return _shell(inner, title="Schema-weighted review")
