# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""RC AI commentator: explain reading-comprehension passages on demand.

Reading-comprehension tutoring is where a language model is genuinely useful, but
also where hallucination is most dangerous: a confident wrong reading of the
passage teaches the student the exact habit the LSAT punishes. So this commentator
follows the established precedents for a *grounded* reading assistant:

* **Grounded / extractive first.** Every answer is tied to the passage text. The
  offline path (always available) produces a structural read -- main point,
  organization, author's attitude, attributed viewpoints, transition pivots -- and
  answers questions by returning the most relevant passage sentences, never invented
  facts.
* **AI is opt-in, advisory, and gated.** A generative explanation is only produced
  when the AI subsystem is explicitly enabled (``speedrun.ai.config.ai_enabled``,
  default OFF). When enabled, the prompt hard-constrains the model to the passage,
  to quote its evidence, to separate reported views from the author's own, and to
  say so when a question is not answerable from the text.
* **Never feeds the scores.** Commentary is a study aid, like the contrasting and
  cold-open drills -- it is not a graded transfer attempt (honesty rule).

Everything here is Qt-free and pure-data so it is unit-testable; the aqt layer just
drops the returned HTML into a dialog.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PKG_ROOT = Path(__file__).resolve().parent
DEFAULT_SEED = PKG_ROOT / "data" / "seed_deck.json"

_SEE_REF = "(see"

# --------------------------------------------------------------------------- #
# Passage loading
# --------------------------------------------------------------------------- #


@dataclass
class Passage:
    passage_id: str
    title: str
    text: str
    schemas: list[str]
    questions: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_seed_rc_items(path: Path = DEFAULT_SEED) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [it for it in data.get("items", []) if it.get("section") == "RC"]


def resolve_passage_text(items: list[dict[str, Any]], passage_id: str) -> str:
    """The full passage text for a passage_id (siblings carry a "(see ...)" ref)."""
    for it in items:
        if it.get("passage_id") == passage_id:
            txt = (it.get("passage") or "").strip()
            if txt and not txt.startswith(_SEE_REF):
                return txt
    return ""


def _title_for(passage_id: str, text: str) -> str:
    first = re.split(r"(?<=[.!?])\s+", text.strip())[0] if text else passage_id
    words = first.split()
    snippet = " ".join(words[:6]) + ("…" if len(words) > 6 else "")
    return f"{passage_id.upper()} · {snippet}"


def load_passages(path: Path = DEFAULT_SEED) -> list[Passage]:
    items = load_seed_rc_items(path)
    order: list[str] = []
    seen: set[str] = set()
    for it in items:
        pid = it.get("passage_id")
        if pid and pid not in seen:
            seen.add(pid)
            order.append(pid)

    passages: list[Passage] = []
    for pid in order:
        text = resolve_passage_text(items, pid)
        if not text:
            continue
        qs = [it for it in items if it.get("passage_id") == pid]
        schemas = sorted({s for it in qs for s in it.get("schemas", [])})
        questions = [
            {
                "id": it.get("id", ""),
                "question": it.get("question", ""),
                "schema": (it.get("schemas") or [""])[0],
            }
            for it in qs
        ]
        passages.append(
            Passage(
                passage_id=pid,
                title=_title_for(pid, text),
                text=text,
                schemas=schemas,
                questions=questions,
            )
        )
    return passages


# --------------------------------------------------------------------------- #
# Deterministic (offline) analysis -- always available, fully grounded
# --------------------------------------------------------------------------- #


@dataclass
class PassageCommentary:
    passage_id: str
    main_point: str
    primary_purpose: str
    tone: str
    tone_evidence: str
    structure: list[dict[str, str]] = field(default_factory=list)
    viewpoints: list[dict[str, str]] = field(default_factory=list)
    transitions: list[dict[str, str]] = field(default_factory=list)
    reading_tips: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with",
    "as", "at", "by", "is", "are", "was", "were", "be", "been", "that", "this",
    "these", "those", "it", "its", "their", "they", "them", "which", "who", "what",
    "how", "why", "when", "where", "than", "then", "so", "such", "also", "not",
    "no", "into", "from", "about", "would", "could", "should", "may", "might",
    "one", "some", "others", "other", "more", "most", "both", "each", "any",
}

# Ordered role cues: earlier entries win.
_ROLE_CUES: list[tuple[str, tuple[str, ...]]] = [
    (
        "Author's synthesis",
        (
            "the author", "author argues", "author suggests", "evidence suggests",
            "middle position", "both views", "the point is", "miss the point",
            "should serve", "should ", "the balance",
        ),
    ),
    (
        "Competing responses",
        ("some researchers", "some ", " others", "critics", "proponents",
         "resisted", "embraced", "revisionist", "these scholars"),
    ),
    (
        "Complication / turn",
        ("recent", "later", "however", "but ", "yet ", "revealed", "complicat",
         " new "),
    ),
    (
        "Setup / traditional view",
        ("once", "long ", "traditionally", "historically", "mainly", "used to",
         "classified"),
    ),
]

_TONE_LEXICON: list[tuple[str, tuple[str, ...]]] = [
    ("Measured and evaluative",
     ("middle", "balance", "qualified", "pragmatic", "together", "nuance",
      "both views", "moderate")),
    ("Critical / skeptical",
     ("overreach", "miss the point", "resisted", "flawed", "fails", "naive",
      "mistaken", "overlook")),
    ("Appreciative",
     ("embraced", "valuable", "powerful", "elegant", "compelling", "illuminating")),
]

_TRANSITION_WORDS = (
    "however", "but", "yet", "although", "though", "recent", "later", "therefore",
    "thus", "moreover", "whereas", "while", "instead", "nonetheless", "nevertheless",
)

_VIEWPOINT_CUES: list[tuple[str, tuple[str, ...]]] = [
    ("Traditional / earlier view",
     ("once", "long ", "traditionally", "historians", "used to", "classified mainly",
      "long classified")),
    ("Newer / revisionist view",
     ("recent scholarship", "these scholars", "revisionist", "molecular", "later revealed",
      "new taxonomy")),
    ("One camp", ("some researchers", "some ", "resisted", "critics")),
    ("Opposing camp", (" others", "embraced", "proponents")),
    ("The author's own position",
     ("the author", "evidence suggests", "middle position", "the point", "should serve")),
]

_SCHEMA_TIPS = {
    "rc.main_point": "For the main point, prefer the author's qualified conclusion over the strongest-sounding claim.",
    "rc.author_attitude": "Attitude is carried by evaluative words and qualifiers — read the hedges, not just the nouns.",
    "rc.passage_organization": "Track the arc: setup → turn → competing views → resolution.",
    "rc.function_of_detail": "Ask why a detail is there — it usually supports the turn or one side's view, not itself.",
    "rc.inference": "An inference must be provable from the text alone; bring in no outside knowledge.",
    "rc.comparative_relationship": "Map how the positions relate before you judge them.",
    "rc.viewpoint_attribution": "Attribute every claim to the right party — the author is only one voice.",
}


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS]


def _role_of(sentence: str) -> str:
    low = " " + sentence.lower() + " "
    for role, cues in _ROLE_CUES:
        if any(c in low for c in cues):
            return role
    return "Development"


def analyze_passage(
    text: str, *, passage_id: str = "", schemas: list[str] | None = None
) -> PassageCommentary:
    """A grounded structural read of an RC passage, using only its own text."""
    sents = _sentences(text)
    schemas = schemas or []

    # Structure: role per sentence.
    structure = [{"role": _role_of(s), "text": s} for s in sents]

    # Main point: last author-synthesis sentence, else the last sentence.
    synthesis = [s["text"] for s in structure if s["role"] == "Author's synthesis"]
    main_point = synthesis[-1] if synthesis else (sents[-1] if sents else "")

    # Primary purpose from the shape of the argument.
    roles = {s["role"] for s in structure}
    if "Author's synthesis" in roles and "Competing responses" in roles:
        primary_purpose = (
            "To weigh competing interpretations and defend a qualified, "
            "purpose-dependent position."
        )
    elif "Complication / turn" in roles:
        primary_purpose = (
            "To complicate a traditional view by introducing newer evidence."
        )
    else:
        primary_purpose = "To explain and describe the topic for the reader."

    # Tone.
    tone, tone_evidence = "Neutral / expository", ""
    low_all = text.lower()
    for label, cues in _TONE_LEXICON:
        hit = next((c for c in cues if c in low_all), None)
        if hit:
            tone = label
            tone_evidence = next((s for s in sents if hit in s.lower()), "")
            break

    # Viewpoints (attribution) — de-duplicated, in order of appearance.
    viewpoints: list[dict[str, str]] = []
    used_holders: set[str] = set()
    for s in sents:
        low = " " + s.lower() + " "
        for holder, cues in _VIEWPOINT_CUES:
            if holder in used_holders:
                continue
            if any(c in low for c in cues):
                viewpoints.append({"holder": holder, "text": s})
                used_holders.add(holder)
                break

    # Transition pivots.
    transitions: list[dict[str, str]] = []
    seen_words: set[str] = set()
    for s in sents:
        low = " " + s.lower() + " "
        for w in _TRANSITION_WORDS:
            if w in seen_words:
                continue
            if f" {w} " in low or low.strip().startswith(w + " "):
                transitions.append({"word": w, "clause": s})
                seen_words.add(w)

    # Reading tips: grounded generic + schema-targeted.
    tips = [
        "Separate the views the passage reports from the view the author endorses.",
        "The main point is the author's own conclusion — often the qualified one.",
    ]
    if transitions:
        pivot = transitions[0]["word"]
        tips.insert(
            1,
            f"Watch the pivot at “{pivot}” — the author's stance usually emerges there.",
        )
    for sc in schemas:
        tip = _SCHEMA_TIPS.get(sc)
        if tip and tip not in tips:
            tips.append(tip)

    return PassageCommentary(
        passage_id=passage_id,
        main_point=main_point,
        primary_purpose=primary_purpose,
        tone=tone,
        tone_evidence=tone_evidence,
        structure=structure,
        viewpoints=viewpoints,
        transitions=transitions,
        reading_tips=tips,
    )


def extractive_answer(text: str, question: str, *, max_sentences: int = 2) -> list[str]:
    """Return the passage sentences most relevant to the question (grounded, no
    invention). Token-overlap scoring; passage order preserved among ties."""
    q_tokens = set(_tokens(question))
    if not q_tokens:
        return []
    scored: list[tuple[int, int, str]] = []
    for i, s in enumerate(_sentences(text)):
        overlap = len(q_tokens & set(_tokens(s)))
        if overlap > 0:
            scored.append((overlap, i, s))
    if not scored:
        return []
    scored.sort(key=lambda t: (-t[0], t[1]))
    top = scored[:max_sentences]
    top.sort(key=lambda t: t[1])  # restore passage order
    return [s for _o, _i, s in top]


# --------------------------------------------------------------------------- #
# AI layer (opt-in, grounded prompt)
# --------------------------------------------------------------------------- #

_PROMPT_RULES = (
    "You are an LSAT reading-comprehension tutor. Explain the passage to a student.\n"
    "STRICT RULES:\n"
    "1. Use ONLY information stated in the passage. Add no outside facts.\n"
    "2. Quote short phrases from the passage as your evidence.\n"
    "3. Separate the views the passage reports from the author's own position.\n"
    "4. If a question cannot be answered from the passage, say so explicitly.\n"
    "5. Be concise and structured (main point, organization, author's attitude)."
)


def build_commentary_prompt(passage_text: str, question: str | None = None) -> str:
    """A grounding-hardened single-string prompt for the LLM client."""
    parts = [_PROMPT_RULES, "", "Passage:", '"""', passage_text.strip(), '"""']
    if question:
        parts += ["", f"Student question: {question.strip()}"]
        parts += ["", "Answer the question using only the passage, quoting evidence."]
    else:
        parts += ["", "Give grounded commentary on the passage."]
    return "\n".join(parts)


@dataclass
class CommentaryResult:
    source: str  # "offline" or a model/source name
    ai_used: bool
    analysis: PassageCommentary
    ai_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["analysis"] = self.analysis.to_dict()
        return d


def _ai_on() -> bool:
    try:
        from speedrun.ai.config import ai_enabled

        return bool(ai_enabled())
    except Exception:
        return False


def commentate(
    passage_text: str,
    *,
    passage_id: str = "",
    schemas: list[str] | None = None,
    client=None,
) -> CommentaryResult:
    """Grounded commentary. Uses the LLM only when AI is enabled and returns text;
    always falls back to the deterministic structural read."""
    analysis = analyze_passage(passage_text, passage_id=passage_id, schemas=schemas)
    if _ai_on():
        try:
            if client is None:
                from speedrun.ai.client import default_client

                client = default_client()
            resp = client.complete(build_commentary_prompt(passage_text))
            if getattr(resp, "text", "").strip():
                return CommentaryResult(
                    source=getattr(resp, "source", "ai"),
                    ai_used=True,
                    analysis=analysis,
                    ai_text=resp.text.strip(),
                )
        except Exception:
            pass
    return CommentaryResult(source="offline", ai_used=False, analysis=analysis)


def answer_question(passage_text: str, question: str, *, client=None) -> dict[str, Any]:
    """Answer a question about the passage. AI path when enabled+available; otherwise
    grounded extractive sentences (or an honest "not addressed")."""
    if _ai_on():
        try:
            if client is None:
                from speedrun.ai.client import default_client

                client = default_client()
            resp = client.complete(build_commentary_prompt(passage_text, question))
            if getattr(resp, "text", "").strip():
                return {
                    "answer": resp.text.strip(),
                    "source": getattr(resp, "source", "ai"),
                    "ai_used": True,
                    "evidence": [],
                }
        except Exception:
            pass
    evidence = extractive_answer(passage_text, question)
    if evidence:
        answer = "Based on the passage: " + " ".join(evidence)
    else:
        answer = "The passage does not directly address that."
    return {
        "answer": answer,
        "source": "offline-extractive",
        "ai_used": False,
        "evidence": evidence,
    }


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _esc(text: object) -> str:
    return html.escape(str(text))


def commentator_payload(path: Path = DEFAULT_SEED) -> dict[str, Any]:
    passages = load_passages(path)
    return {
        "ai_enabled": _ai_on(),
        "passages": [
            {
                **p.to_dict(),
                "commentary": analyze_passage(
                    p.text, passage_id=p.passage_id, schemas=p.schemas
                ).to_dict(),
            }
            for p in passages
        ],
    }


_RC_CSS = """
.sr-rc { max-width: 900px; }
.sr-rc-status { display: flex; align-items: center; gap: 8px; padding: 10px 14px; border-radius: 10px;
  font-size: 0.84rem; margin-bottom: 14px; border: 1px solid var(--border); }
.sr-rc-status.off { background: rgba(148,163,184,0.12); }
.sr-rc-status.on { background: rgba(22,163,74,0.10); border-color: var(--high); }
.sr-rc-status .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--muted); }
.sr-rc-status.on .dot { background: var(--high); }
.sr-rc-controls { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.sr-rc-controls label { font-size: 0.8rem; color: var(--muted); font-weight: 600; }
.sr-rc-select { font-family: inherit; font-size: 0.88rem; padding: 8px 10px; border: 1px solid var(--border);
  border-radius: 8px; background: var(--bg); color: var(--text); max-width: 100%; }
.sr-rc-passage { border: 1px solid var(--border); border-left: 4px solid var(--accent); border-radius: 10px;
  background: var(--surface); padding: 14px 16px; margin-bottom: 14px; font-size: 0.95rem; line-height: 1.6; }
.sr-rc-card { border: 1px solid var(--border); border-radius: 12px; background: var(--surface);
  padding: 14px 16px; margin-bottom: 12px; }
.sr-rc-card h3 { margin: 0 0 8px; font-size: 1rem; }
.sr-rc-headline { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 620px) { .sr-rc-headline { grid-template-columns: 1fr; } }
.sr-rc-kv .k { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); font-weight: 700; }
.sr-rc-kv .v { font-size: 0.9rem; margin-top: 3px; }
.sr-rc-struct { list-style: none; margin: 0; padding: 0; }
.sr-rc-struct li { display: grid; grid-template-columns: 160px 1fr; gap: 10px; padding: 6px 0;
  border-top: 1px solid var(--border); font-size: 0.88rem; }
.sr-rc-struct li:first-child { border-top: none; }
.sr-rc-role { font-weight: 700; color: var(--accent); font-size: 0.78rem; }
.sr-rc-vp { margin: 0; padding: 0; list-style: none; }
.sr-rc-vp li { padding: 6px 0; border-top: 1px solid var(--border); font-size: 0.88rem; }
.sr-rc-vp li:first-child { border-top: none; }
.sr-rc-vp .holder { font-weight: 700; color: var(--text); }
.sr-rc-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.sr-rc-chip { background: rgba(37,99,235,0.12); color: var(--accent); border-radius: 999px; padding: 2px 10px;
  font-size: 0.78rem; font-weight: 600; }
.sr-rc-tips { margin: 6px 0 0; padding-left: 18px; font-size: 0.86rem; }
.sr-rc-tips li { margin-bottom: 4px; }
.sr-rc-ask { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.sr-rc-input { flex: 1; min-width: 240px; font-family: inherit; font-size: 0.9rem; padding: 9px 12px;
  border: 1px solid var(--border); border-radius: 8px; background: var(--bg); color: var(--text); }
.sr-btn { cursor: pointer; border: 1px solid var(--border); background: var(--surface); color: var(--text);
  border-radius: 8px; padding: 9px 16px; font-size: 0.85rem; font-weight: 600; }
.sr-btn.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
.sr-rc-samples { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.sr-rc-sample { cursor: pointer; background: transparent; border: 1px dashed var(--border); color: var(--muted);
  border-radius: 999px; padding: 3px 10px; font-size: 0.78rem; }
.sr-rc-answer { display: none; border-radius: 10px; padding: 12px 14px; font-size: 0.9rem;
  background: rgba(37,99,235,0.06); border: 1px solid var(--border); }
.sr-rc-answer.show { display: block; }
.sr-rc-answer .src { font-size: 0.74rem; color: var(--muted); margin-top: 8px; }
.sr-rc-answer mark { background: rgba(217,119,6,0.25); border-radius: 3px; padding: 0 2px; }
"""

_RC_JS = """
(function () {
  const holder = document.getElementById('sr-rc');
  if (!holder) return;
  const data = JSON.parse(document.getElementById('sr-rc-data').textContent);
  const passages = data.passages;
  if (!passages.length) return;
  const sel = document.getElementById('sr-rc-passage');
  const passEl = document.getElementById('sr-rc-text');
  const commEl = document.getElementById('sr-rc-commentary');
  const samplesEl = document.getElementById('sr-rc-samples');
  const input = document.getElementById('sr-rc-q');
  const answerEl = document.getElementById('sr-rc-answer');
  let cur = passages[0];

  const STOP = new Set(('the a an and or but of to in on for with as at by is are was were be been that this ' +
    'these those it its their they them which who what how why when where than then so such also not no into ' +
    'from about would could should may might one some others other more most both each any').split(' '));
  function esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
  function toks(s) { return (s.toLowerCase().match(/[a-z0-9]+/g) || []).filter(t => !STOP.has(t)); }
  function sentences(t) { return t.trim().split(/(?<=[.!?])\\s+/).map(x => x.trim()).filter(Boolean); }

  function renderCommentary(p) {
    const c = p.commentary;
    const struct = c.structure.map(s =>
      '<li><span class="sr-rc-role">' + esc(s.role) + '</span><span>' + esc(s.text) + '</span></li>').join('');
    const vps = c.viewpoints.length
      ? c.viewpoints.map(v => '<li><span class="holder">' + esc(v.holder) + ':</span> ' + esc(v.text) + '</li>').join('')
      : '<li>No distinct attributed viewpoints detected.</li>';
    const trans = c.transitions.length
      ? c.transitions.map(t => '<span class="sr-rc-chip">' + esc(t.word) + '</span>').join('')
      : '<span style="color:var(--muted);font-size:0.85rem">None</span>';
    const tips = c.reading_tips.map(t => '<li>' + esc(t) + '</li>').join('');
    const toneEv = c.tone_evidence ? '<div class="v" style="color:var(--muted);font-size:0.82rem">“' + esc(c.tone_evidence) + '”</div>' : '';
    commEl.innerHTML =
      '<div class="sr-rc-card"><div class="sr-rc-headline">' +
      '<div class="sr-rc-kv"><div class="k">Main point</div><div class="v">' + esc(c.main_point) + '</div></div>' +
      '<div class="sr-rc-kv"><div class="k">Primary purpose</div><div class="v">' + esc(c.primary_purpose) + '</div></div>' +
      '<div class="sr-rc-kv"><div class="k">Author\\u2019s tone</div><div class="v">' + esc(c.tone) + '</div>' + toneEv + '</div>' +
      '<div class="sr-rc-kv"><div class="k">Transitions</div><div class="v sr-rc-chips">' + trans + '</div></div>' +
      '</div></div>' +
      '<div class="sr-rc-card"><h3>How the passage is built</h3><ul class="sr-rc-struct">' + struct + '</ul></div>' +
      '<div class="sr-rc-card"><h3>Whose view is whose</h3><ul class="sr-rc-vp">' + vps + '</ul></div>' +
      '<div class="sr-rc-card"><h3>Reading tips</h3><ul class="sr-rc-tips">' + tips + '</ul></div>';
  }

  function renderSamples(p) {
    samplesEl.innerHTML = (p.questions || []).slice(0, 4).map(q =>
      '<button class="sr-rc-sample" data-q="' + esc(q.question) + '">' + esc(q.question) + '</button>').join('');
    samplesEl.querySelectorAll('[data-q]').forEach(b =>
      b.addEventListener('click', () => { input.value = b.dataset.q; ask(); }));
  }

  function extractive(text, q) {
    const qt = new Set(toks(q));
    if (!qt.size) return [];
    const scored = [];
    sentences(text).forEach((s, i) => {
      let o = 0; toks(s).forEach(t => { if (qt.has(t)) o++; });
      if (o > 0) scored.push({ o, i, s });
    });
    scored.sort((a, b) => b.o - a.o || a.i - b.i);
    const top = scored.slice(0, 2).sort((a, b) => a.i - b.i);
    return top.map(x => x.s);
  }

  function highlight(sentence, q) {
    const qt = new Set(toks(q));
    return sentence.split(/(\\s+)/).map(w => {
      const bare = w.toLowerCase().replace(/[^a-z0-9]+/g, '');
      return (bare && qt.has(bare)) ? '<mark>' + esc(w) + '</mark>' : esc(w);
    }).join('');
  }

  function ask() {
    const q = (input.value || '').trim();
    if (!q) return;
    const ev = extractive(cur.text, q);
    let body;
    if (ev.length) {
      body = 'Based on the passage: ' + ev.map(s => highlight(s, q)).join(' ');
    } else {
      body = 'The passage does not directly address that. Try rephrasing with words from the text.';
    }
    answerEl.className = 'sr-rc-answer show';
    answerEl.innerHTML = body +
      '<div class="src">Grounded extractive answer — the most relevant sentences from the passage. ' +
      (data.ai_enabled ? 'AI is enabled; generative commentary is available in-app.' :
        'AI is off by default (opt-in); no outside facts are added.') + '</div>';
  }

  function load(p) {
    cur = p;
    passEl.textContent = p.text;
    renderCommentary(p);
    renderSamples(p);
    answerEl.className = 'sr-rc-answer';
    answerEl.innerHTML = '';
    input.value = '';
  }

  sel.addEventListener('change', () => load(passages[+sel.value]));
  document.getElementById('sr-rc-ask-btn').addEventListener('click', ask);
  input.addEventListener('keydown', e => { if (e.key === 'Enter') ask(); });
  load(passages[0]);
})();
"""


def _commentator_body(payload: dict[str, Any]) -> str:
    passages = payload.get("passages", [])
    if not passages:
        return (
            '<div class="sr-header"><h1>RC AI commentator</h1></div>'
            '<div class="sr-empty">No reading-comprehension passages available. '
            "Import the seed deck to load RC passages.</div>"
        )
    ai_on = bool(payload.get("ai_enabled"))
    status = (
        f'<div class="sr-rc-status {"on" if ai_on else "off"}"><span class="dot"></span>'
        + (
            "AI commentary is <b>enabled</b> — generative explanations are grounded in "
            "the passage and quote their evidence."
            if ai_on
            else "AI is <b>off by default</b> (opt-in). Showing a grounded structural "
            "read generated offline; answers quote the passage and add no outside facts."
        )
        + "</div>"
    )
    data_json = json.dumps(payload).replace("<", "\\u003c")
    options = "".join(
        f'<option value="{i}">{_esc(p["title"])}</option>'
        for i, p in enumerate(passages)
    )
    intro = (
        "An on-demand reading tutor for RC passages: it maps the main point, the "
        "structure, the author's tone, and whose view is whose — then answers your "
        "questions using only the passage text."
    )
    return (
        f"<style>{_RC_CSS}</style>"
        '<div class="sr-header"><h1>RC AI commentator</h1>'
        f"<p>{intro}</p></div>"
        '<div class="sr-rc" id="sr-rc">'
        f"{status}"
        '<div class="sr-rc-controls"><label for="sr-rc-passage">Passage</label>'
        f'<select class="sr-rc-select" id="sr-rc-passage">{options}</select></div>'
        '<div class="sr-rc-passage" id="sr-rc-text"></div>'
        '<div id="sr-rc-commentary"></div>'
        '<div class="sr-rc-card"><h3>Ask the commentator</h3>'
        '<div class="sr-rc-samples" id="sr-rc-samples"></div>'
        '<div class="sr-rc-ask">'
        '<input class="sr-rc-input" id="sr-rc-q" placeholder="Ask about this passage — e.g. what does the author conclude?">'
        '<button class="sr-btn primary" id="sr-rc-ask-btn">Ask</button></div>'
        '<div class="sr-rc-answer" id="sr-rc-answer"></div>'
        "</div>"
        '<script type="application/json" id="sr-rc-data">' + data_json + "</script>"
        "</div>"
        f"<script>{_RC_JS}</script>"
    )


def render_rc_commentator_html(
    col=None, *, path: Path = DEFAULT_SEED, embed: bool = False
) -> str:
    """Render the interactive RC AI commentator.

    ``col`` is accepted for a uniform report signature but unused (passages come
    from the seed deck). ``embed=True`` returns body-only markup with the dashboard
    stylesheet inlined; otherwise a full standalone document."""
    from speedrun.dashboard import _DASHBOARD_CSS, _shell

    payload = commentator_payload(path)
    inner = _commentator_body(payload)
    if embed:
        return f'<style>{_DASHBOARD_CSS}</style><div class="sr-dash">{inner}</div>'
    return _shell(inner, title="RC AI commentator")
