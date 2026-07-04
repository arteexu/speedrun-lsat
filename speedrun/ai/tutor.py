# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""AI Tutor: a grounded chat assistant that answers a student's questions about a
*specific* problem.

Design mirrors the RC commentator so it fits the honesty rule and the BrainLift:

* **Grounded in the item, not the open web.** Every answer is built from the
  problem's own structured data -- stimulus, question, each choice, its trap tag,
  the tested schema(s) and their taxonomy descriptions, and the hand-written
  two-answer-fork rationale. The tutor is told to reason only about *these*
  choices and to add no outside facts.
* **Works with AI off (default).** When the AI subsystem is disabled or returns
  nothing usable, a deterministic answerer replies from the same structured data
  (via ``speedrun.explanations``). So the tutor is useful today, with no key.
* **AI is opt-in, advisory, gated, and sourced.** A generative answer is shown
  only when ``speedrun.ai.config.ai_enabled`` is true AND the response carries a
  real named source (``resp.ok`` -- the traceability rule). Source text is
  injection-sanitized before it reaches the prompt.
* **Never feeds the scores.** Like the other drills, tutoring is a study aid; it
  is not a graded transfer attempt (honesty rule). Nothing here imports the
  scoring engine.

Qt-free and pure-data so it is unit-testable; the aqt layer drops the returned
body-only HTML into a dialog and relays chat turns over the pycmd bridge.
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from speedrun.textfmt import INLINE_MD_JS

PKG_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = PKG_ROOT / "data" / "seed_deck.json"

MAX_QUESTION_CHARS = 500
_MAX_HISTORY_TURNS = 6


# --------------------------------------------------------------------------- #
# Grounding context
# --------------------------------------------------------------------------- #


def _ai_on() -> bool:
    try:
        from speedrun.ai.config import ai_enabled

        return bool(ai_enabled())
    except Exception:
        return False


def build_context(item: dict[str, Any], *, items: list[dict[str, Any]] | None = None) -> str:
    """A compact, fully-grounded description of one problem for the prompt."""
    from speedrun.explanations import explain_item

    exp = explain_item(item, items=items)
    lines: list[str] = []
    if exp.section:
        lines.append(f"Section: {exp.section}")
    if exp.stimulus:
        lines.append(f"Stimulus: {exp.stimulus}")
    if exp.question:
        lines.append(f"Question: {exp.question}")
    lines.append("Answer choices:")
    if exp.correct:
        lines.append(f"  ({exp.correct.id}) {exp.correct.text}  [CREDITED]")
    for d in exp.distractors:
        tag = f"  [trap: {d.trap_label}]" if d.trap_label else ""
        rp = " [runner-up]" if d.is_runner_up else ""
        lines.append(f"  ({d.id}) {d.text}{rp}{tag}")
    if exp.schemas:
        lines.append("Tested schema(s):")
        for s in exp.schemas:
            desc = f" — {s['description']}" if s.get("description") else ""
            lines.append(f"  {s['label']}{desc}")
    ru = next((d for d in exp.distractors if d.is_runner_up), None)
    if ru and ru.why:
        lines.append(f"Why the runner-up ({ru.id}) is wrong: {ru.why}")
    return "\n".join(lines)


_PROMPT_RULES = (
    "You are an LSAT tutor helping a student understand ONE specific problem.\n"
    "STRICT RULES:\n"
    "1. Reason ONLY about the problem below (its stimulus, question, and the "
    "given answer choices). Add no outside facts or invented choices.\n"
    "2. When you say a choice is right or wrong, name the specific reason grounded "
    "in the stimulus or the choice's trap type.\n"
    "3. If the student asks something the problem does not determine, say so.\n"
    "4. Be concise, concrete, and encouraging; teach the transferable pattern, "
    "not just the letter."
)


def build_tutor_prompt(
    context: str, question: str, *, history: list[dict[str, str]] | None = None
) -> str:
    """A grounding-hardened single-string prompt. ``context`` is sanitized."""
    from speedrun.ai.guard import sanitize_source_text

    safe_context = sanitize_source_text(context)
    parts = [_PROMPT_RULES, "", "Problem:", '"""', safe_context, '"""']
    if history:
        parts.append("")
        parts.append("Conversation so far:")
        for turn in history[-_MAX_HISTORY_TURNS:]:
            role = "Student" if turn.get("role") == "user" else "Tutor"
            text = (turn.get("text") or "").strip()
            if text:
                parts.append(f"{role}: {text}")
    parts += ["", f"Student question: {question.strip()}", "", "Tutor answer:"]
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Deterministic (offline) answerer — grounded in the item's own data
# --------------------------------------------------------------------------- #

_STOP = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with",
    "as", "at", "by", "is", "are", "was", "were", "be", "this", "that", "it",
    "why", "how", "what", "which", "does", "do", "did", "answer", "choice",
    "option", "question", "problem", "explain", "tell", "me", "about", "here",
    "correct", "right", "wrong", "would", "could", "should", "can", "you",
}


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOP]


def _referenced_choice(exp, question: str):
    """Find a choice the question refers to, e.g. "(B)", "choice C", or a lone
    uppercase letter. Returns a ChoiceExplanation or None."""
    all_choices = ([exp.correct] if exp.correct else []) + list(exp.distractors)
    for pat in (
        r"\(([A-Ea-e])\)",
        r"(?:choice|option|answer)\s+([A-Ea-e])\b",
        r"\b([A-E])\b",
    ):
        m = re.search(pat, question)
        if m:
            cid = m.group(1).upper()
            for ch in all_choices:
                if ch.id == cid:
                    return ch
    return None


def _extractive(text: str, question: str, *, limit: int = 2) -> list[str]:
    q = set(_tokens(question))
    if not q or not text:
        return []
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    scored = [
        (len(q & set(_tokens(s))), i, s) for i, s in enumerate(sents)
    ]
    scored = [t for t in scored if t[0] > 0]
    if not scored:
        return []
    scored.sort(key=lambda t: (-t[0], t[1]))
    top = sorted(scored[:limit], key=lambda t: t[1])
    return [s for _o, _i, s in top]


def offline_answer(exp, question: str) -> tuple[str, list[str]]:
    """Answer a question about the problem from its structured data only.

    Returns ``(answer_text, citations)``. Never invents facts."""
    q = question.lower()
    cites: list[str] = []

    # 1. A specific choice was named -> explain that choice.
    ch = _referenced_choice(exp, question)
    if ch is not None:
        if ch.correct:
            ans = f"({ch.id}) is the credited answer. {ch.why}."
        else:
            lead = "the runner-up trap" if ch.is_runner_up else "a trap"
            label = f" ({ch.trap_label})" if ch.trap_label else ""
            ans = f"({ch.id}) is {lead}{label}: {ch.why}"
        if exp.schemas:
            cites.append(f"Tested schema: {exp.schemas[0]['label']}")
        return ans, cites

    # 2. Asking about the flaw / schema / what it tests.
    if any(w in q for w in ("flaw", "schema", "pattern", "testing", "tests", "concept", "type")):
        if exp.schemas:
            s = exp.schemas[0]
            desc = f" — {s['description']}" if s.get("description") else ""
            ans = f"This problem tests **{s['label']}**{desc}."
            if len(exp.schemas) > 1:
                extra = ", ".join(x["label"] for x in exp.schemas[1:])
                ans += f" It also involves: {extra}."
            return ans, [f"Question type: {exp.question_type or 'n/a'}"]

    # 3. The two-answer fork ("between", "runner up", "down to two"). Checked
    # before the generic credited-answer intent, since "between the two answers"
    # also contains "answer".
    if any(w in q for w in ("between", "runner", "two ", "narrow", "confus", "versus", "vs")):
        ru = next((d for d in exp.distractors if d.is_runner_up), None)
        if ru and exp.correct:
            return (
                f"On this item the decision comes down to ({exp.correct.id}) vs "
                f"({ru.id}). Pick ({exp.correct.id}): {exp.correct.why}. "
                f"Reject ({ru.id}): {ru.why}",
                [exp.takeaway] if exp.takeaway else [],
            )

    # 4. Asking about traps / wrong answers / distractors.
    if any(w in q for w in ("trap", "wrong", "distractor", "eliminate", "rule out", "avoid")):
        parts = []
        for d in exp.distractors:
            label = d.trap_label or "unsupported"
            parts.append(f"({d.id}) {label}: {d.why}")
        if parts:
            return "Here is why each distractor is tempting-but-wrong:\n" + "\n".join(parts), []

    # 5. Asking about the credited/right answer.
    if any(w in q for w in ("right", "correct", "credited", "best", "answer")) and exp.correct:
        ans = f"The credited answer is ({exp.correct.id}). {exp.correct.why}."
        if exp.takeaway:
            cites.append(exp.takeaway)
        return ans, cites

    # 6. Free-text: try extractive over the stimulus, then fall back to takeaway.
    ev = _extractive(exp.stimulus, question)
    if ev:
        return "From the stimulus: " + " ".join(ev), ["Grounded in the stimulus text"]

    if exp.correct:
        ans = f"The credited answer is ({exp.correct.id}). {exp.correct.why}."
        if exp.takeaway:
            ans += f" {exp.takeaway}"
        return ans, []
    return (
        "I can explain why each choice is right or wrong, the flaw being tested, "
        "or how to decide between the final two — just ask.",
        [],
    )


# --------------------------------------------------------------------------- #
# Public answer API
# --------------------------------------------------------------------------- #


@dataclass
class TutorReply:
    item_id: str
    answer: str
    source: str  # "offline" or a model/source name
    ai_used: bool
    citations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def answer_question(
    item: dict[str, Any],
    question: str,
    *,
    items: list[dict[str, Any]] | None = None,
    client=None,
    history: list[dict[str, str]] | None = None,
) -> TutorReply:
    """Answer a student's question about ``item``.

    Uses the LLM (grounded to the problem) only when AI is enabled and returns a
    usable, named-source response; otherwise a deterministic grounded answer."""
    from speedrun.explanations import explain_item

    item_id = item.get("id", "")
    question = (question or "").strip()[:MAX_QUESTION_CHARS]
    exp = explain_item(item, items=items)

    if not question:
        text, cites = offline_answer(exp, "")
        return TutorReply(item_id, text, "offline", False, cites)

    if _ai_on():
        try:
            if client is None:
                from speedrun.ai.client import default_client

                client = default_client()
            context = build_context(item, items=items)
            prompt = build_tutor_prompt(context, question, history=history)
            resp = client.complete(prompt, max_tokens=400)
            # Source enforcement: only show AI text with a real, named source.
            if getattr(resp, "ok", False):
                return TutorReply(
                    item_id=item_id,
                    answer=resp.text.strip(),
                    source=resp.source,
                    ai_used=True,
                    citations=["Grounded in this problem's stimulus, choices, and fork rationale"],
                )
        except Exception:
            pass  # fall through to the offline answer

    text, cites = offline_answer(exp, question)
    return TutorReply(item_id, text, "offline", False, cites)


# --------------------------------------------------------------------------- #
# Payload + rendering (chat UI)
# --------------------------------------------------------------------------- #


def _esc(text: object) -> str:
    return html.escape(str(text))


def load_items(path: Path = DEFAULT_SEED) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(data.get("items", []))


def _label_for(item: dict[str, Any]) -> str:
    from speedrun.taxonomy.labels import schema_label

    iid = item.get("id", "")
    sec = item.get("section", "")
    stem = item.get("stem_type", "")
    qt = schema_label(stem) if stem else ""
    return f"{iid} · {sec}" + (f" · {qt}" if qt else "")


def tutor_payload(path: Path = DEFAULT_SEED) -> dict[str, Any]:
    items = load_items(path)
    problems = []
    for it in items:
        stim = (it.get("stimulus") or it.get("passage") or "").strip()
        if stim.startswith("(see"):
            stim = ""
        problems.append(
            {
                "id": it.get("id", ""),
                "label": _label_for(it),
                "section": it.get("section", ""),
                "stimulus": stim,
                "question": it.get("question", ""),
            }
        )
    return {"ai_enabled": _ai_on(), "problems": problems}


_TUTOR_SAMPLES = [
    "Why is the credited answer right?",
    "What flaw is being tested?",
    "Why is the runner-up wrong?",
    "Why are the other choices traps?",
]


def find_item(item_id: str, path: Path = DEFAULT_SEED) -> dict[str, Any] | None:
    for it in load_items(path):
        if it.get("id") == item_id:
            return it
    return None


def answer_for_bridge(
    item_id: str, question: str, *, path: Path = DEFAULT_SEED, history=None
) -> dict[str, Any]:
    """Thin wrapper the aqt bridge calls; resolves the item by id and returns a
    JSON-serializable reply. Never raises."""
    try:
        items = load_items(path)
        item = next((it for it in items if it.get("id") == item_id), None)
        if item is None:
            return {
                "item_id": item_id,
                "answer": "That problem could not be found. Import the seed deck first.",
                "source": "offline",
                "ai_used": False,
                "citations": [],
            }
        return answer_question(item, question, items=items, history=history).to_dict()
    except Exception as exc:  # pragma: no cover - never break the chat
        return {
            "item_id": item_id,
            "answer": f"Sorry — I hit an error answering that ({type(exc).__name__}).",
            "source": "offline",
            "ai_used": False,
            "citations": [],
        }


_TUTOR_CSS = """
.sr-tutor { max-width: 900px; display: flex; flex-direction: column; height: 100%; }
.sr-tutor-status { display:flex; align-items:center; gap:8px; padding:10px 14px; border-radius:10px;
  font-size:0.84rem; margin-bottom:12px; border:1px solid var(--border); }
.sr-tutor-status.off { background: rgba(148,163,184,0.12); }
.sr-tutor-status.on { background: rgba(22,163,74,0.10); border-color: var(--high); }
.sr-tutor-status .dot { width:9px; height:9px; border-radius:50%; background:var(--muted); }
.sr-tutor-status.on .dot { background: var(--high); }
.sr-tutor-controls { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:10px; }
.sr-tutor-controls label { font-size:0.8rem; color:var(--muted); font-weight:600; }
.sr-tutor-select { font-family:inherit; font-size:0.88rem; padding:8px 10px; border:1px solid var(--border);
  border-radius:8px; background:var(--bg); color:var(--text); max-width:100%; flex:1; min-width:220px; }
.sr-tutor-problem { border:1px solid var(--border); border-left:4px solid var(--accent); border-radius:10px;
  background:var(--surface); padding:12px 14px; margin-bottom:12px; font-size:0.92rem; line-height:1.55; }
.sr-tutor-problem .q { font-weight:600; margin-top:6px; }
.sr-tutor-log { flex:1; overflow-y:auto; border:1px solid var(--border); border-radius:12px;
  background:var(--bg); padding:12px; margin-bottom:10px; min-height:180px; }
.sr-msg { max-width:85%; padding:9px 13px; border-radius:14px; margin-bottom:9px; font-size:0.9rem; line-height:1.5;
  white-space:pre-wrap; }
.sr-msg.user { margin-left:auto; background:var(--accent); color:#fff; border-bottom-right-radius:4px; }
.sr-msg.bot { margin-right:auto; background:var(--surface); border:1px solid var(--border);
  border-bottom-left-radius:4px; }
.sr-msg .src { display:block; margin-top:7px; font-size:0.72rem; color:var(--muted); }
.sr-msg .src .ai { color: var(--high); font-weight:700; }
.sr-msg strong { font-weight:700; }
.sr-tutor-samples { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px; }
.sr-tutor-sample { cursor:pointer; background:transparent; border:1px dashed var(--border); color:var(--muted);
  border-radius:999px; padding:3px 10px; font-size:0.78rem; }
.sr-tutor-ask { display:flex; gap:8px; }
.sr-tutor-input { flex:1; min-width:200px; font-family:inherit; font-size:0.9rem; padding:10px 12px;
  border:1px solid var(--border); border-radius:8px; background:var(--bg); color:var(--text); }
.sr-btn { cursor:pointer; border:1px solid var(--border); background:var(--surface); color:var(--text);
  border-radius:8px; padding:10px 16px; font-size:0.85rem; font-weight:600; }
.sr-btn.primary { background:var(--accent); color:#fff; border-color:var(--accent); }
.sr-btn:disabled { opacity:0.5; cursor:default; }
"""

_TUTOR_JS = r"""
(function () {
  const holder = document.getElementById('sr-tutor');
  if (!holder) return;
  const data = JSON.parse(document.getElementById('sr-tutor-data').textContent);
  const problems = data.problems || [];
  if (!problems.length) return;
  const sel = document.getElementById('sr-tutor-select');
  const probEl = document.getElementById('sr-tutor-problem');
  const logEl = document.getElementById('sr-tutor-log');
  const input = document.getElementById('sr-tutor-q');
  const askBtn = document.getElementById('sr-tutor-ask-btn');
  let cur = problems[0];
  let history = [];

  const esc = srEsc;   // shared with speedrun.textfmt.INLINE_MD_JS
  const fmt = srFmt;   // esc()+**bold**+newlines, escaped-first (injection-safe)
  function hasBridge(){ return typeof pycmd === 'function'; }

  function showProblem(p){
    let h = '';
    if (p.stimulus) h += esc(p.stimulus);
    if (p.question) h += '<div class="q">' + esc(p.question) + '</div>';
    if (!h) h = '<span style="color:var(--muted)">This item shares a passage; ask about its choices or flaw.</span>';
    probEl.innerHTML = h;
  }

  function addMsg(role, text, meta){
    const div = document.createElement('div');
    div.className = 'sr-msg ' + role;
    div.innerHTML = (role === 'bot' ? fmt(text) : esc(text)) + (meta ? meta : '');
    logEl.appendChild(div);
    logEl.scrollTop = logEl.scrollHeight;
    return div;
  }

  function srcLine(reply){
    if (reply.ai_used){
      return '<span class="src"><span class="ai">AI</span> · source: ' + esc(reply.source) +
        ' · grounded in this problem</span>';
    }
    let extra = (reply.citations && reply.citations.length) ? ' · ' + esc(reply.citations.join(' · ')) : '';
    return '<span class="src">Grounded answer (no AI) — built from this problem\u2019s choices, traps & fork' +
      extra + '</span>';
  }

  function ask(){
    const q = (input.value || '').trim();
    if (!q) return;
    addMsg('user', q);
    history.push({role:'user', text:q});
    input.value = '';
    askBtn.disabled = true;
    const pending = addMsg('bot', 'Thinking\u2026');
    if (hasBridge()){
      const msg = 'speedrun:tutor:' + JSON.stringify({item_id: cur.id, question: q, history: history});
      pycmd(msg, function(resp){
        // pycmd already JSON.parses the bridge result, so resp is an object;
        // tolerate a string too in case a host double-encodes.
        let reply = (typeof resp === 'string') ? JSON.parse(resp) : (resp || {});
        if (!reply.answer) reply = {answer: String(resp), source:'offline', ai_used:false, citations:[]};
        pending.innerHTML = fmt(reply.answer) + srcLine(reply);
        history.push({role:'bot', text: reply.answer});
        logEl.scrollTop = logEl.scrollHeight;
        askBtn.disabled = false;
        input.focus();
      });
    } else {
      pending.innerHTML = 'The tutor needs to run inside the app (open it from the LSAT Speedrun menu).' +
        srcLine({ai_used:false, citations:[]});
      askBtn.disabled = false;
    }
  }

  function loadProblem(i){
    cur = problems[i];
    logEl.innerHTML = '';
    history = [];
    showProblem(cur);
    addMsg('bot', 'Ask me anything about **' + (cur.label || cur.id) + '** — why an answer is right or wrong, ' +
      'the flaw being tested, or how to decide between the final two.', srcLine({ai_used:false, citations:[]}));
  }

  problems.forEach((p, i) => {
    const o = document.createElement('option'); o.value = i; o.textContent = p.label || p.id; sel.appendChild(o);
  });
  sel.addEventListener('change', () => loadProblem(+sel.value));
  askBtn.addEventListener('click', ask);
  input.addEventListener('keydown', e => { if (e.key === 'Enter') ask(); });
  document.querySelectorAll('.sr-tutor-sample').forEach(b =>
    b.addEventListener('click', () => { input.value = b.dataset.q; ask(); }));
  loadProblem(0);
})();
"""


def _tutor_body(payload: dict[str, Any]) -> str:
    problems = payload.get("problems", [])
    if not problems:
        return (
            '<div class="sr-header"><h1>AI Tutor</h1></div>'
            '<div class="sr-empty">No problems available. Import the seed deck first.</div>'
        )
    ai_on = bool(payload.get("ai_enabled"))
    status = (
        f'<div class="sr-tutor-status {"on" if ai_on else "off"}"><span class="dot"></span>'
        + (
            "AI is <b>enabled</b> — answers are generated and grounded in this problem, "
            "with the model named as the source."
            if ai_on
            else "AI is <b>off by default</b> (opt-in). Answers are built deterministically "
            "from this problem's choices, trap tags, and fork rationale — no outside facts."
        )
        + "</div>"
    )
    data_json = json.dumps(payload).replace("<", "\\u003c")
    samples = "".join(
        f'<button class="sr-tutor-sample" data-q="{_esc(s)}">{_esc(s)}</button>'
        for s in _TUTOR_SAMPLES
    )
    intro = (
        "A grounded chat tutor for a single problem: pick a problem, then ask why "
        "an answer is right or wrong, what flaw it tests, or how to split the final two."
    )
    return (
        f"<style>{_TUTOR_CSS}</style>"
        '<div class="sr-header"><h1>AI Tutor</h1>'
        f"<p>{intro}</p></div>"
        '<div class="sr-tutor" id="sr-tutor">'
        f"{status}"
        '<div class="sr-tutor-controls"><label for="sr-tutor-select">Problem</label>'
        '<select class="sr-tutor-select" id="sr-tutor-select"></select></div>'
        '<div class="sr-tutor-problem" id="sr-tutor-problem"></div>'
        '<div class="sr-tutor-log" id="sr-tutor-log"></div>'
        f'<div class="sr-tutor-samples">{samples}</div>'
        '<div class="sr-tutor-ask">'
        '<input class="sr-tutor-input" id="sr-tutor-q" placeholder="Ask about this problem…">'
        '<button class="sr-btn primary" id="sr-tutor-ask-btn">Ask</button></div>'
        "</div>"
        '<script type="application/json" id="sr-tutor-data">' + data_json + "</script>"
        f"<script>{INLINE_MD_JS}{_TUTOR_JS}</script>"
    )


def render_tutor_html(col=None, *, path: Path = DEFAULT_SEED, embed: bool = False) -> str:
    """Render the interactive AI Tutor chat.

    ``col`` is accepted for a uniform report signature but unused (problems come
    from the seed deck). ``embed=True`` returns body-only markup for the pycmd
    bridge dialog; otherwise a full standalone document."""
    from speedrun.dashboard import _DASHBOARD_CSS, _shell

    payload = tutor_payload(path)
    inner = _tutor_body(payload)
    if embed:
        return f'<style>{_DASHBOARD_CSS}</style><div class="sr-dash">{inner}</div>'
    return _shell(inner, title="AI Tutor")
