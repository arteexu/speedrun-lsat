# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Deterministic, no-AI explanations for the problems that actually exist.

Every seed item already carries everything a good explanation needs: the tested
schema(s), which choice is credited, a per-choice trap tag, and a hand-written
"why the runner-up is wrong" note (the two-answer fork). This module turns that
structured data into a full walkthrough -- why the right answer is right, and why
each wrong answer is tempting-but-wrong -- with zero model calls.

The taxonomy is the source of truth for what a schema or a trap *means*
(``description`` fields in ``lsat_taxonomy.json``), so explanations stay consistent
with the rest of the app and never invent reasoning.
"""

from __future__ import annotations

import html
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PKG_ROOT = Path(__file__).resolve().parent
DEFAULT_SEED = PKG_ROOT / "data" / "seed_deck.json"

_SEE_REF = "(see"


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def load_items(path: Path = DEFAULT_SEED) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(data.get("items", []))


def items_by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {it.get("id", ""): it for it in items}


def _resolve_passage(items: list[dict[str, Any]], passage_id: str) -> str:
    for it in items:
        if it.get("passage_id") == passage_id:
            txt = (it.get("passage") or "").strip()
            if txt and not txt.startswith(_SEE_REF):
                return txt
    return ""


def _display_stimulus(item: dict[str, Any], items: list[dict[str, Any]] | None) -> str:
    stim = (item.get("stimulus") or "").strip()
    if stim:
        return stim
    passage = (item.get("passage") or "").strip()
    if passage and not passage.startswith(_SEE_REF):
        return passage
    # Sibling RC question: resolve "(see rc-0001)" to the real passage text.
    if items is not None and item.get("passage_id"):
        return _resolve_passage(items, item["passage_id"])
    return passage


# --------------------------------------------------------------------------- #
# Explanation model
# --------------------------------------------------------------------------- #


@dataclass
class ChoiceExplanation:
    id: str
    text: str
    correct: bool
    is_runner_up: bool = False
    trap_id: str | None = None
    trap_label: str | None = None
    why: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProblemExplanation:
    item_id: str
    section: str
    question_type: str
    difficulty: str
    stimulus: str
    question: str
    schemas: list[dict[str, str]] = field(default_factory=list)
    correct: ChoiceExplanation | None = None
    distractors: list[ChoiceExplanation] = field(default_factory=list)
    takeaway: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


_AXIS_WHY = {
    "flaw": "it names the reasoning flaw the argument actually commits",
    "rc": "it matches what the passage supports",
    "qt": "it performs the task the question asks for",
}


def _why_correct(primary_id: str, primary_desc: str) -> str:
    axis = primary_id.split(".", 1)[0] if primary_id else ""
    lead = _AXIS_WHY.get(axis, "it does what the question asks")
    tail = f" — {primary_desc}" if primary_desc else ""
    return f"Credited response: {lead}{tail}"


def explain_item(
    item: dict[str, Any],
    *,
    items: list[dict[str, Any]] | None = None,
    defs: dict[str, str] | None = None,
) -> ProblemExplanation:
    """Build a full, grounded explanation for one seed item."""
    from speedrun.taxonomy.labels import schema_label

    if defs is None:
        from speedrun.insights import load_taxonomy_definitions

        defs = load_taxonomy_definitions()

    schema_ids = [s for s in item.get("schemas", []) if s]
    schemas = [
        {"id": s, "label": schema_label(s), "description": defs.get(s, "")}
        for s in schema_ids
    ]
    primary_id = schema_ids[0] if schema_ids else ""
    primary_desc = defs.get(primary_id, "") if primary_id else ""

    fork = item.get("two_answer_fork", {}) or {}
    runner_up = fork.get("runner_up", "")
    why_runner_up = fork.get("why_runner_up_wrong", "")

    correct: ChoiceExplanation | None = None
    distractors: list[ChoiceExplanation] = []
    trap_labels: list[str] = []

    for ch in item.get("choices", []):
        cid = ch.get("id", "")
        text = ch.get("text", "")
        if ch.get("correct"):
            correct = ChoiceExplanation(
                id=cid, text=text, correct=True,
                why=_why_correct(primary_id, primary_desc),
            )
            continue
        trap_id = ch.get("trap")
        trap_label = schema_label(trap_id) if trap_id else None
        is_runner_up = bool(runner_up) and cid == runner_up
        if is_runner_up and why_runner_up:
            why = why_runner_up
        elif trap_id:
            desc = defs.get(trap_id, "")
            why = desc or "A tempting distractor that the stimulus does not support."
        else:
            why = "Unsupported by the stimulus."
        if trap_label:
            trap_labels.append(trap_label)
        distractors.append(
            ChoiceExplanation(
                id=cid, text=text, correct=False, is_runner_up=is_runner_up,
                trap_id=trap_id, trap_label=trap_label, why=why,
            )
        )

    takeaway = _build_takeaway(primary_id, schemas, distractors)

    return ProblemExplanation(
        item_id=item.get("id", ""),
        section=item.get("section", ""),
        question_type=item.get("stem_type", ""),
        difficulty=str(item.get("difficulty", "")),
        stimulus=_display_stimulus(item, items),
        question=item.get("question", ""),
        schemas=schemas,
        correct=correct,
        distractors=distractors,
        takeaway=takeaway,
    )


def _build_takeaway(
    primary_id: str,
    schemas: list[dict[str, str]],
    distractors: list[ChoiceExplanation],
) -> str:
    from speedrun.taxonomy.labels import schema_label

    parts: list[str] = []
    if schemas:
        parts.append(f"This item tests {schemas[0]['label']}.")
    # Most common trap family among the distractors.
    fam_counts: dict[str, int] = {}
    for d in distractors:
        if d.trap_id:
            fam = schema_label(d.trap_id)
            fam_counts[fam] = fam_counts.get(fam, 0) + 1
    if fam_counts:
        top = sorted(fam_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        parts.append(f"The distractors lean hardest on the “{top}” trap — rule it out first.")
    return " ".join(parts)


def explain_item_by_id(
    item_id: str, path: Path = DEFAULT_SEED
) -> ProblemExplanation | None:
    items = load_items(path)
    item = items_by_id(items).get(item_id)
    if item is None:
        return None
    return explain_item(item, items=items)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _esc(text: object) -> str:
    return html.escape(str(text))


_EXP_CSS = """
.sr-exp { max-width: 860px; }
.sr-exp-meta { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.sr-exp-tag { background: rgba(37,99,235,0.12); color: var(--accent); border-radius: 999px;
  padding: 3px 11px; font-size: 0.78rem; font-weight: 600; }
.sr-exp-tag.sec { background: rgba(148,163,184,0.18); color: var(--muted); }
.sr-exp-stim { border: 1px solid var(--border); border-left: 4px solid var(--muted); border-radius: 10px;
  background: var(--surface); padding: 12px 14px; margin-bottom: 10px; line-height: 1.55; font-size: 0.93rem; }
.sr-exp-q { font-weight: 600; margin: 4px 0 12px; }
.sr-exp-choice { border: 1px solid var(--border); border-radius: 10px; padding: 11px 13px; margin-bottom: 9px;
  background: var(--surface); }
.sr-exp-choice.correct { border-color: var(--high); background: rgba(22,163,74,0.08); }
.sr-exp-choice.runner { border-left: 4px solid var(--accent); }
.sr-exp-choice .lead { display: flex; align-items: baseline; gap: 8px; }
.sr-exp-choice .cid { font-weight: 700; min-width: 20px; }
.sr-exp-choice .verdict { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em;
  font-weight: 700; padding: 1px 7px; border-radius: 999px; }
.sr-exp-choice.correct .verdict { color: var(--high); background: rgba(22,163,74,0.15); }
.sr-exp-choice .verdict.trap { color: var(--low); background: rgba(220,38,38,0.12); }
.sr-exp-why { font-size: 0.86rem; color: var(--muted); margin-top: 6px; }
.sr-exp-why .traplabel { color: var(--low); font-weight: 700; }
.sr-exp-card { border: 1px solid var(--border); border-radius: 12px; background: var(--surface);
  padding: 13px 15px; margin-top: 12px; }
.sr-exp-card h3 { margin: 0 0 6px; font-size: 0.98rem; }
.sr-exp-schema { font-size: 0.87rem; margin-bottom: 6px; }
.sr-exp-schema .lbl { font-weight: 700; }
.sr-exp-take { border-left: 4px solid var(--accent); background: rgba(37,99,235,0.06); }
details.sr-exp-item { border: 1px solid var(--border); border-radius: 10px; margin-bottom: 8px;
  background: var(--surface); padding: 4px 12px; }
details.sr-exp-item > summary { cursor: pointer; padding: 8px 0; font-weight: 600; font-size: 0.9rem; }
details.sr-exp-item[open] > summary { border-bottom: 1px solid var(--border); margin-bottom: 8px; }
"""


def _choice_html(ch: ChoiceExplanation) -> str:
    cls = "sr-exp-choice"
    if ch.correct:
        cls += " correct"
    elif ch.is_runner_up:
        cls += " runner"
    if ch.correct:
        verdict = '<span class="verdict">Correct</span>'
    else:
        vlabel = "Runner-up trap" if ch.is_runner_up else "Trap"
        verdict = f'<span class="verdict trap">{vlabel}</span>'
    trap_prefix = (
        f'<span class="traplabel">{_esc(ch.trap_label)}:</span> '
        if ch.trap_label and not ch.correct
        else ""
    )
    return (
        f'<div class="{cls}"><div class="lead">'
        f'<span class="cid">({_esc(ch.id)})</span>'
        f"<span>{_esc(ch.text)}</span>{verdict}</div>"
        f'<div class="sr-exp-why">{trap_prefix}{_esc(ch.why)}</div></div>'
    )


def _explanation_body(exp: ProblemExplanation) -> str:
    from speedrun.taxonomy.labels import schema_label

    meta = (
        f'<span class="sr-exp-tag sec">{_esc(exp.section or "—")}</span>'
        f'<span class="sr-exp-tag">{_esc(schema_label(exp.question_type)) if exp.question_type else "Question"}</span>'
        + (f'<span class="sr-exp-tag">Difficulty {_esc(exp.difficulty)}</span>' if exp.difficulty else "")
    )
    stim = f'<div class="sr-exp-stim">{_esc(exp.stimulus)}</div>' if exp.stimulus else ""
    q = f'<div class="sr-exp-q">{_esc(exp.question)}</div>' if exp.question else ""

    choices = []
    if exp.correct:
        choices.append(_choice_html(exp.correct))
    choices.extend(_choice_html(d) for d in exp.distractors)

    schema_rows = "".join(
        f'<div class="sr-exp-schema"><span class="lbl">{_esc(s["label"])}</span>'
        + (f' — {_esc(s["description"])}' if s["description"] else "")
        + "</div>"
        for s in exp.schemas
    )
    schema_card = (
        f'<div class="sr-exp-card"><h3>What this problem tests</h3>{schema_rows}</div>'
        if schema_rows
        else ""
    )
    take = (
        f'<div class="sr-exp-card sr-exp-take"><h3>Takeaway</h3>'
        f"<div>{_esc(exp.takeaway)}</div></div>"
        if exp.takeaway
        else ""
    )
    return (
        f'<div class="sr-exp-meta">{meta}</div>'
        f"{stim}{q}"
        + "".join(choices)
        + schema_card
        + take
    )


def render_problem_explanation_html(
    item: dict[str, Any],
    *,
    items: list[dict[str, Any]] | None = None,
    embed: bool = False,
) -> str:
    """Render a full walkthrough for a single problem (no AI)."""
    from speedrun.dashboard import _DASHBOARD_CSS, _shell

    exp = explain_item(item, items=items)
    inner = (
        f"<style>{_EXP_CSS}</style>"
        '<div class="sr-header"><h1>Why this answer</h1></div>'
        f'<div class="sr-exp">{_explanation_body(exp)}</div>'
    )
    if embed:
        return f'<style>{_DASHBOARD_CSS}</style><div class="sr-dash">{inner}</div>'
    return _shell(inner, title="Problem explanation")


def render_explanations_report_html(
    col=None, *, path: Path = DEFAULT_SEED, embed: bool = False
) -> str:
    """Browsable, collapsible explanations for every problem, grouped by section.

    ``col`` is accepted for a uniform report signature but unused (content comes
    from the seed deck)."""
    from speedrun.dashboard import _DASHBOARD_CSS, _shell

    items = load_items(path)
    if not items:
        inner = (
            '<div class="sr-header"><h1>Problem explanations</h1></div>'
            '<div class="sr-empty">No problems available. Import the seed deck first.</div>'
        )
        if embed:
            return f'<style>{_DASHBOARD_CSS}</style><div class="sr-dash">{inner}</div>'
        return _shell(inner, title="Problem explanations")

    defs = None
    from speedrun.insights import load_taxonomy_definitions

    defs = load_taxonomy_definitions()

    sections: dict[str, list[str]] = {}
    for it in items:
        exp = explain_item(it, items=items, defs=defs)
        summary = _esc(exp.question or exp.item_id)
        block = (
            f'<details class="sr-exp-item"><summary>{summary}</summary>'
            f'<div class="sr-exp">{_explanation_body(exp)}</div></details>'
        )
        sections.setdefault(exp.section or "Other", []).append(block)

    order = [s for s in ("LR", "RC") if s in sections] + [
        s for s in sections if s not in ("LR", "RC")
    ]
    body_parts = []
    for sec in order:
        blocks = sections[sec]
        body_parts.append(
            f'<h2 style="margin-top:18px">{_esc(sec)} · {len(blocks)} problems</h2>'
            + "".join(blocks)
        )

    inner = (
        f"<style>{_EXP_CSS}</style>"
        '<div class="sr-header"><h1>Problem explanations</h1>'
        "<p>A grounded, no-AI walkthrough of every problem: why the credited answer "
        "is right and why each distractor is a trap.</p></div>"
        f'<div class="sr-exp">{"".join(body_parts)}</div>'
    )
    if embed:
        return f'<style>{_DASHBOARD_CSS}</style><div class="sr-dash">{inner}</div>'
    return _shell(inner, title="Problem explanations")
