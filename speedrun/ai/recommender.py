# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""AI "what to study next" recommender — a grounded study coach.

Design mirrors the AI Tutor (:mod:`speedrun.ai.tutor`) so it obeys the same
honesty + traceability rules:

* **Grounded in the student's real data.** Every recommendation is built from
  the scoring/queue engine: per-schema transfer weakness, raw accuracy and
  attempt counts (:mod:`speedrun.scoring.performance`), the exam points-at-stake
  weights (:mod:`speedrun.scoring.queue`), and how many cards are actually due.
  Nothing is invented.
* **Works with AI off (default).** A deterministic ranker turns those scores
  into a prioritized "study next" list plus a human summary. This is always
  available, needs no key, and never touches the network.
* **AI is opt-in, advisory, gated, and sourced.** A generative study plan is
  only produced when :func:`speedrun.ai.config.ai_enabled` is true AND the model
  response carries a real named source (``resp.ok`` — the traceability rule).
  The real score data is passed as grounded, injection-sanitized context; on any
  error / disabled / no-key we fall back to the deterministic recommendation.
* **Never feeds the scores.** Recommending is a study aid; it is not a graded
  transfer attempt. Nothing here writes to the revlog or the collection.

Qt-free and pure-data so it is unit-testable; the aqt layer renders the payload
into a dialog and relays "study this now" back over the pycmd bridge (which ties
into focused study, :mod:`speedrun.focus`).
"""
from __future__ import annotations

import html
import json
from dataclasses import asdict, dataclass, field
from typing import Any

# The minimum points-at-stake weight given to a schema whose exam weight is
# unknown/zero, so weakness alone can still rank it above nothing.
_WEIGHT_FLOOR = 0.02
# Cards due nudge urgency up, but capped so a big backlog can't dominate a much
# weaker schema. due/_DUE_CAP scaled by _DUE_GAIN.
_DUE_CAP = 20
_DUE_GAIN = 0.5


def _ai_on() -> bool:
    try:
        from speedrun.ai.config import ai_enabled

        return bool(ai_enabled())
    except Exception:
        return False


def _subject_kind(schema: str) -> str:
    """Question-types (``qt.*``) are surfaced as their own subject kind; every
    other tested pattern is a schema (flaw / RC / trap / LG family)."""
    return "question_type" if schema.startswith("qt.") else "schema"


def _label_for(schema: str) -> str:
    from speedrun.taxonomy.labels import schema_label

    return schema_label(schema)


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass
class Recommendation:
    subject: str  # schema id, e.g. "flaw.causal.correlation_causation" or "qt.*"
    kind: str  # "question_type" or "schema"
    label: str  # friendly taxonomy label
    accuracy: float | None  # raw accuracy (ignoring the clock)
    transfer: float | None  # latency-adjusted transfer estimate
    n_attempts: int
    weakness: float  # 1 - transfer
    points_at_stake: float  # exam weight (floored)
    due_count: int
    speed_flag: bool
    priority: float  # weakness * points-at-stake * due nudge
    reason: str
    focus_cmd: str  # pycmd string that launches focused study for this subject

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RecommendationSet:
    recommendations: list[Recommendation]
    summary: str
    ai_used: bool
    source: str  # "offline" or a model/source name
    gave_up: bool
    reason: str
    ai_plan: str | None = None
    citations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["recommendations"] = [r.to_dict() for r in self.recommendations]
        return d


# --------------------------------------------------------------------------- #
# Deterministic (offline) ranker — grounded in the scoring engine
# --------------------------------------------------------------------------- #


def _reason_for(
    *, accuracy: float | None, n_attempts: int, due_count: int, speed_flag: bool
) -> str:
    if accuracy is not None:
        head = f"Your accuracy is {accuracy:.0%} over {n_attempts} attempt" + (
            "s" if n_attempts != 1 else ""
        )
    else:
        head = f"{n_attempts} attempt" + ("s" if n_attempts != 1 else "") + " so far"
    tail = []
    if due_count:
        tail.append(f"{due_count} card" + ("s" if due_count != 1 else "") + " due")
    if speed_flag:
        tail.append("accurate but slow — you'd lose points on the clock")
    if tail:
        return head + "; " + " · ".join(tail) + "."
    return head + "."


def rank_recommendations(
    per_schema: dict[str, Any],
    weights: dict[str, float] | None = None,
    *,
    due_counts: dict[str, int] | None = None,
    limit: int = 5,
) -> list[Recommendation]:
    """Turn per-schema performance scores into a prioritized study-next list.

    ``per_schema`` maps schema id -> ``PerformanceScore``. Only schemas the model
    is willing to score (``not gave_up`` and a real ``point``) are ranked, so a
    recommendation always rests on enough evidence. Priority = transfer weakness
    weighted by the schema's exam points-at-stake, nudged by how many cards are
    actually due. Deterministic: ties break by weakness, then attempts, then id.
    """
    weights = weights or {}
    due_counts = due_counts or {}
    recs: list[Recommendation] = []
    for schema, score in per_schema.items():
        if getattr(score, "gave_up", True):
            continue
        point = getattr(score, "point", None)
        if point is None:
            continue
        weakness = max(0.0, 1.0 - point)
        pts = max(float(weights.get(schema, 0.0)), _WEIGHT_FLOOR)
        due = int(due_counts.get(schema, 0))
        due_nudge = 1.0 + min(due, _DUE_CAP) / _DUE_CAP * _DUE_GAIN
        priority = weakness * pts * due_nudge
        accuracy = getattr(score, "raw_accuracy", None)
        speed_flag = bool(getattr(score, "speed_flag", False))
        n_attempts = int(getattr(score, "n_attempts", 0))
        recs.append(
            Recommendation(
                subject=schema,
                kind=_subject_kind(schema),
                label=_label_for(schema),
                accuracy=accuracy,
                transfer=point,
                n_attempts=n_attempts,
                weakness=weakness,
                points_at_stake=pts,
                due_count=due,
                speed_flag=speed_flag,
                priority=priority,
                reason=_reason_for(
                    accuracy=accuracy,
                    n_attempts=n_attempts,
                    due_count=due,
                    speed_flag=speed_flag,
                ),
                focus_cmd=f"speedrun:focus:{schema}",
            )
        )
    recs.sort(key=lambda r: (-r.priority, -r.weakness, -r.n_attempts, r.subject))
    return recs[:limit]


def _summary(recs: list[Recommendation]) -> str:
    if not recs:
        return (
            "Not enough graded attempts yet to single out a weak area — keep "
            "practicing and a personalized plan will appear here."
        )
    top = recs[0]
    acc = f"{top.accuracy:.0%}" if top.accuracy is not None else "low"
    lead = (
        f"Focus first on {top.label} — {acc} accuracy over {top.n_attempts} "
        f"attempts"
    )
    if top.due_count:
        lead += f", {top.due_count} due"
    lead += "."
    if len(recs) > 1:
        rest = ", then ".join(r.label for r in recs[1:3])
        lead += f" Then work {rest}."
    return lead


# --------------------------------------------------------------------------- #
# Data pulls from the collection (reuse the scoring/queue engine)
# --------------------------------------------------------------------------- #

_DECK_SEARCH = 'deck:"LSAT Speedrun"'
_SCHEMA_TAG = "sr:schema:"


def _due_counts(col, schemas: list[str]) -> dict[str, int]:
    """Cards actually due per schema. Best-effort: never raises, returns {} if the
    collection can't be queried (keeps the offline recommendation working)."""
    out: dict[str, int] = {}
    for s in schemas:
        try:
            cids = col.find_cards(f'{_DECK_SEARCH} tag:"{_SCHEMA_TAG}{s}" is:due')
            if cids:
                out[s] = len(cids)
        except Exception:
            continue
    return out


def _weights() -> dict[str, float]:
    try:
        from speedrun.scoring.queue import load_schema_weights

        return load_schema_weights()
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
# AI-enhanced plan (opt-in, gated, sourced)
# --------------------------------------------------------------------------- #

_PROMPT_RULES = (
    "You are an LSAT study coach. Using ONLY the student's real performance data "
    "below, write a short prioritized study plan (3-5 sentences).\n"
    "STRICT RULES:\n"
    "1. Recommend ONLY the schemas/question-types listed below. Do not invent "
    "topics, numbers, or accuracies.\n"
    "2. For each pick, name the specific weakness using the given accuracy and "
    "attempt count.\n"
    "3. Put the highest points-at-stake, weakest areas first.\n"
    "4. Be concrete and encouraging; explain what to drill and why it moves the "
    "score."
)


def build_grounding(recs: list[Recommendation]) -> str:
    """A compact, fully-grounded description of the ranked weaknesses for the LLM."""
    lines = ["Student weakness data (ranked by points-at-stake):"]
    for i, r in enumerate(recs, 1):
        acc = f"{r.accuracy:.0%}" if r.accuracy is not None else "n/a"
        tr = f"{r.transfer:.0%}" if r.transfer is not None else "n/a"
        lines.append(
            f"{i}. {r.label} [{r.kind}] — accuracy {acc}, transfer {tr}, "
            f"weakness {r.weakness:.0%}, exam-weight {r.points_at_stake:.2f}, "
            f"{r.n_attempts} attempts, {r.due_count} due"
            + (", accurate-but-slow" if r.speed_flag else "")
        )
    return "\n".join(lines)


def build_plan_prompt(recs: list[Recommendation]) -> str:
    """Grounding-hardened single-string prompt; the data block is sanitized."""
    from speedrun.ai.guard import sanitize_source_text

    safe = sanitize_source_text(build_grounding(recs))
    return "\n".join([_PROMPT_RULES, "", "Data:", '"""', safe, '"""', "", "Study plan:"])


# --------------------------------------------------------------------------- #
# Public recommend API
# --------------------------------------------------------------------------- #


def recommend(col, *, client=None, limit: int = 5) -> RecommendationSet:
    """Recommend what to study next, grounded in ``col``'s real scores.

    Deterministic offline ranking is always produced. When AI is enabled and the
    model returns a usable, named-source response, an explained plan is added on
    top; otherwise only the offline recommendation is returned."""
    from speedrun.scoring.performance import performance_score

    perf = performance_score(col)
    per_schema = perf["per_schema"]
    weights = _weights()
    scored = [s for s, sc in per_schema.items() if not sc.gave_up and sc.point is not None]
    due_counts = _due_counts(col, scored)
    recs = rank_recommendations(per_schema, weights, due_counts=due_counts, limit=limit)
    summary = _summary(recs)

    if not recs:
        return RecommendationSet(
            recommendations=[],
            summary=summary,
            ai_used=False,
            source="offline",
            gave_up=True,
            reason="No schema has enough graded attempts to rank yet.",
        )

    ai_used = False
    ai_plan: str | None = None
    source = "offline"
    citations: list[str] = []

    if _ai_on():
        try:
            if client is None:
                from speedrun.ai.client import default_client

                client = default_client()
            prompt = build_plan_prompt(recs)
            resp = client.complete(prompt, max_tokens=400)
            if getattr(resp, "ok", False):
                ai_used = True
                ai_plan = resp.text.strip()
                source = resp.source
                citations = [
                    "Grounded in your per-schema accuracy, transfer weakness, "
                    "exam weights, and due counts"
                ]
        except Exception:
            pass  # fall through to the offline recommendation

    return RecommendationSet(
        recommendations=recs,
        summary=summary,
        ai_used=ai_used,
        source=source,
        gave_up=False,
        reason="Ranked by transfer weakness × exam points-at-stake.",
        ai_plan=ai_plan,
        citations=citations,
    )


def recommend_payload(col, *, limit: int = 5) -> dict[str, Any]:
    """JSON-serializable payload for the UI. Never raises."""
    try:
        rs = recommend(col, limit=limit)
        payload = rs.to_dict()
    except Exception as exc:  # pragma: no cover - defensive
        payload = {
            "recommendations": [],
            "summary": f"Could not build recommendations ({type(exc).__name__}).",
            "ai_used": False,
            "source": "offline",
            "gave_up": True,
            "reason": "error",
            "ai_plan": None,
            "citations": [],
        }
    payload["ai_enabled"] = _ai_on()
    return payload


# --------------------------------------------------------------------------- #
# Rendering (Qt-free HTML; the aqt layer drops it into a dialog)
# --------------------------------------------------------------------------- #


def _esc(text: object) -> str:
    return html.escape(str(text))


def _md(text: object) -> str:
    """HTML-escape then render lightweight Markdown (``**bold**`` + newlines).

    Shared with the tutor/contrasting surfaces via :func:`speedrun.textfmt`, so
    AI plans and template reasons containing ``**…**`` render as ``<strong>``
    instead of literal asterisks. Escapes first, so it is injection-safe."""
    from speedrun.textfmt import format_inline_md

    return format_inline_md(text)


def _weak_bar(weakness: float) -> str:
    pct = max(0, min(100, int(weakness * 100)))
    cls = "weak" if pct >= 60 else ("mid" if pct >= 30 else "strong")
    return (
        f'<div class="heat-bar" style="min-width:80px"><div class="heat-fill {cls}" '
        f'style="width:{pct}%"></div></div>'
    )


def _rec_card(r: dict[str, Any]) -> str:
    acc = f"{r['accuracy']:.0%}" if r.get("accuracy") is not None else "—"
    kind_badge = "Question type" if r.get("kind") == "question_type" else "Schema"
    from speedrun.taxonomy.labels import schema_display_html

    return (
        '<div class="sr-rec-card">'
        '<div class="sr-rec-main">'
        f'<span class="sr-rec-kind">{_esc(kind_badge)}</span>'
        f'<div class="sr-rec-label">{schema_display_html(r["subject"], compact=True)}</div>'
        f'<div class="sr-rec-reason">{_md(r["reason"])}</div></div>'
        '<div class="sr-rec-side">'
        f'<div class="sr-rec-acc">{_esc(acc)}<span>accuracy</span></div>'
        f'{_weak_bar(float(r.get("weakness") or 0.0))}'
        f'<button type="button" class="sr-btn primary sr-rec-study" '
        f'data-cmd="{_esc(r["focus_cmd"])}">Study this now</button>'
        "</div></div>"
    )


_RECOMMENDER_CSS = """
.sr-rec-status { display:flex; align-items:center; gap:8px; padding:10px 14px; border-radius:10px;
  font-size:0.84rem; margin-bottom:14px; border:1px solid var(--border); }
.sr-rec-status.off { background: rgba(148,163,184,0.12); }
.sr-rec-status.on { background: rgba(22,163,74,0.10); border-color: var(--high); }
.sr-rec-status .dot { width:9px; height:9px; border-radius:50%; background:var(--muted); }
.sr-rec-status.on .dot { background: var(--high); }
.sr-rec-summary { font-size:0.98rem; line-height:1.55; margin-bottom:14px; padding:12px 16px;
  border:1px solid var(--border); border-left:4px solid var(--accent); border-radius:10px;
  background:var(--surface); }
.sr-rec-plan { font-size:0.92rem; line-height:1.6; margin-bottom:16px; padding:12px 16px;
  border:1px solid var(--high); border-radius:10px; background:rgba(22,163,74,0.06); white-space:pre-wrap; }
.sr-rec-plan .src { display:block; margin-top:8px; font-size:0.74rem; color:var(--muted); }
.sr-rec-plan .src .ai { color:var(--high); font-weight:700; }
.sr-rec-list { display:flex; flex-direction:column; gap:10px; }
.sr-rec-card { display:flex; gap:14px; align-items:center; justify-content:space-between;
  border:1px solid var(--border); border-radius:12px; background:var(--surface); padding:12px 16px;
  box-shadow:var(--shadow); }
.sr-rec-main { min-width:0; }
.sr-rec-kind { font-size:0.64rem; text-transform:uppercase; letter-spacing:0.06em; font-weight:700;
  color:var(--muted); }
.sr-rec-label { font-weight:700; font-size:0.98rem; margin:2px 0; }
.sr-rec-reason { font-size:0.82rem; color:var(--muted); }
.sr-rec-side { display:flex; align-items:center; gap:12px; flex-shrink:0; }
.sr-rec-acc { text-align:center; font-weight:800; font-size:1.1rem; font-variant-numeric:tabular-nums; }
.sr-rec-acc span { display:block; font-size:0.62rem; font-weight:600; color:var(--muted);
  text-transform:uppercase; letter-spacing:0.05em; }
.sr-rec-study { white-space:nowrap; }
@media (max-width:600px){ .sr-rec-card{ flex-direction:column; align-items:stretch; } }
"""

_RECOMMENDER_JS = r"""
(function () {
  document.querySelectorAll('.sr-rec-study[data-cmd], .sr-rec-weakest[data-cmd]').forEach(function (b) {
    b.addEventListener('click', function () {
      if (typeof pycmd === 'function') pycmd(b.dataset.cmd);
    });
  });
})();
"""


def _recommender_body(payload: dict[str, Any], *, panel: bool = False) -> str:
    ai_on = bool(payload.get("ai_enabled"))
    status = (
        f'<div class="sr-rec-status {"on" if ai_on else "off"}"><span class="dot"></span>'
        + (
            "AI is <b>enabled</b> — the plan below is generated and grounded in your "
            "real scores, with the model named as the source."
            if ai_on
            else "AI is <b>off by default</b> (opt-in). This plan is ranked "
            "deterministically from your accuracy, transfer weakness, exam weights, "
            "and due cards — no outside facts."
        )
        + "</div>"
    )
    summary = f'<div class="sr-rec-summary">{_md(payload.get("summary", ""))}</div>'
    plan = ""
    if payload.get("ai_used") and payload.get("ai_plan"):
        cites = payload.get("citations") or []
        cite_txt = (" · " + _esc(" · ".join(cites))) if cites else ""
        plan = (
            f'<div class="sr-rec-plan">{_md(payload["ai_plan"])}'
            f'<span class="src"><span class="ai">AI</span> · source: '
            f'{_esc(payload.get("source", "?"))}{cite_txt}</span></div>'
        )
    recs = payload.get("recommendations", [])
    if recs:
        cards = "".join(_rec_card(r) for r in recs)
        body = f'<div class="sr-rec-list">{cards}</div>'
    else:
        body = f'<div class="sr-empty">{_md(payload.get("summary", "No recommendations yet."))}</div>'
    weakest_btn = (
        '<button type="button" class="sr-btn sr-rec-weakest" '
        'data-cmd="speedrun:focus:__weakest__">Study my weakest areas</button>'
    )
    controls = f'<div style="margin:6px 0 14px">{weakest_btn}</div>' if recs else ""
    if panel:
        # Compact section for embedding in the dashboard.
        head = '<div class="sr-section"><h3>What to study next</h3>'
        return f"<style>{_RECOMMENDER_CSS}</style>{head}{status}{summary}{plan}{controls}{body}</div><script>{_RECOMMENDER_JS}</script>"
    intro = (
        "A prioritized plan grounded in your real scores: your weakest, "
        "highest-value schemas and question-types first. Click <b>Study this "
        "now</b> to drill just that subject."
    )
    return (
        f"<style>{_RECOMMENDER_CSS}</style>"
        '<div class="sr-header"><h1>What to study next</h1>'
        f"<p>{intro}</p></div>"
        f"{status}{summary}{plan}{controls}{body}"
        f"<script>{_RECOMMENDER_JS}</script>"
    )


def render_recommender_panel(col) -> str:
    """Compact dashboard section. Never raises (returns an empty-state on error)."""
    try:
        payload = recommend_payload(col)
        return _recommender_body(payload, panel=True)
    except Exception:  # pragma: no cover - defensive
        return ""


def render_recommender_html(col, *, embed: bool = False) -> str:
    """Standalone "What to study next" page (``embed`` for the pycmd dialog)."""
    from speedrun.dashboard import _DASHBOARD_CSS, _shell

    payload = recommend_payload(col)
    inner = _recommender_body(payload)
    if embed:
        return f'<style>{_DASHBOARD_CSS}</style><div class="sr-dash">{inner}</div>'
    return _shell(inner, title="What to study next")
