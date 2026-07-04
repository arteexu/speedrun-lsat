# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""AI "how your reasoning compares" for the contrasting-pairs drill.

After a student answers an item, this compares THEIR chosen answer to the
credited answer and explains how the two reasoning paths differ — so the gap is
visible, not just the verdict. Design mirrors the AI Tutor / recommender so it
obeys the same honesty + traceability rules:

* **Grounded in the item's own data.** The comparison is built from the item's
  structured explanation (:mod:`speedrun.explanations`): the credited choice, the
  chosen choice, its trap tag, the two-answer-fork ``why_runner_up_wrong``
  rationale, and the tested schema. Only the single answered item is used, so no
  unrelated pair member leaks into the prompt.
* **Works with AI off (default).** A deterministic comparator picks the right
  rationale for each case — student picked the runner-up, another distractor, or
  the credited answer — from that structured data. Always available, no key.
* **AI is opt-in, advisory, gated, sourced.** A generative comparison is shown
  only when :func:`speedrun.ai.config.ai_enabled` is true AND the response carries
  a real named source (``resp.ok``). The grounding context is injection-sanitized
  before it reaches the model; on any error / disabled / no-key we fall back to
  the deterministic comparison.
* **Never feeds the scores.** Like the drills, this is a study aid, not a graded
  transfer attempt.

Qt-free and pure-data so it is unit-testable; the aqt drill bridge resolves the
item by id and relays the JSON-serializable reply.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PKG_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = PKG_ROOT / "data" / "seed_deck.json"

MAX_TOKENS = 400


def _ai_on() -> bool:
    try:
        from speedrun.ai.config import ai_enabled

        return bool(ai_enabled())
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass
class ReasoningComparison:
    item_id: str
    chosen_id: str
    credited_id: str
    verdict: str  # "correct" | "runner_up" | "distractor" | "unknown"
    chosen_trap: str | None  # trap label of the chosen wrong answer, if any
    comparison: str  # human-readable "your reasoning vs correct" text
    source: str  # "offline" or a model/source name
    ai_used: bool
    citations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Grounding helpers
# --------------------------------------------------------------------------- #


def _all_choices(exp) -> list[Any]:
    return ([exp.correct] if exp.correct else []) + list(exp.distractors)


def _find_choice(exp, choice_id: str):
    cid = (choice_id or "").strip().upper()
    for ch in _all_choices(exp):
        if ch.id.upper() == cid:
            return ch
    return None


def _most_tempting(exp):
    """The distractor a student is most likely to fall for: the runner-up if the
    fork names one, else the first listed distractor."""
    ru = next((d for d in exp.distractors if d.is_runner_up), None)
    if ru is not None:
        return ru
    return exp.distractors[0] if exp.distractors else None


def _distinguishing_move(exp) -> str:
    if exp.schemas:
        s = exp.schemas[0]
        base = f"This item tests {s['label']}"
        if s.get("description"):
            base += f" — {s['description']}"
        return base + ". Anchor on that, and pick the choice the stimulus actually supports."
    return "Anchor on what the stimulus actually supports, not what merely sounds relevant."


# --------------------------------------------------------------------------- #
# Deterministic (offline) comparison — grounded in the item's own data
# --------------------------------------------------------------------------- #


def offline_comparison(exp, chosen_id: str) -> tuple[str, str, str | None]:
    """Return ``(verdict, text, chosen_trap_label)`` comparing the student's pick
    to the credited answer, using only the item's structured data.

    Cases:
      * student picked the runner-up  -> use the fork's ``why_runner_up_wrong``;
      * student picked another distractor -> use that choice's trap tag/why;
      * student was correct -> contrast the credited answer with the most tempting
        distractor instead.
    """
    credited = exp.correct
    credited_id = credited.id if credited else "?"
    chosen = _find_choice(exp, chosen_id)
    move = _distinguishing_move(exp)

    # Student was correct.
    if chosen is not None and chosen.correct:
        tempt = _most_tempting(exp)
        lines = [
            f"You picked the credited answer ({credited_id}) — correct. {credited.why}.",
        ]
        if tempt is not None:
            label = f" [{tempt.trap_label}]" if tempt.trap_label else ""
            lines.append(
                f"The closest trap was ({tempt.id}){label}: {tempt.why}"
            )
            lines.append(
                f"Your reasoning avoided that trap. The move that separates them: {move}"
            )
        else:
            lines.append(f"The move that made it right: {move}")
        return "correct", "\n".join(lines), None

    # Student picked a wrong choice we can identify.
    if chosen is not None and not chosen.correct:
        verdict = "runner_up" if chosen.is_runner_up else "distractor"
        lead = "the runner-up trap" if chosen.is_runner_up else "a trap"
        label = f" ({chosen.trap_label})" if chosen.trap_label else ""
        cred_txt = (
            f"The credited answer ({credited_id}) is right: {credited.why}."
            if credited
            else "The credited answer is the one the stimulus supports."
        )
        lines = [
            f"You chose ({chosen.id}), {lead}{label}.",
            f"Your reasoning: it looked right because — {chosen.why}",
            cred_txt,
            f"The move that separates your pick from the credited one: {move}",
        ]
        return verdict, "\n".join(lines), chosen.trap_label

    # Chosen id not found among the choices — stay useful, never invent.
    if credited is not None:
        return (
            "unknown",
            (
                f"The credited answer is ({credited_id}): {credited.why}. "
                "Tell me which choice you picked and I'll compare your reasoning to it."
            ),
            None,
        )
    return (
        "unknown",
        "I can compare your chosen answer to the credited one — pick a choice first.",
        None,
    )


# --------------------------------------------------------------------------- #
# AI-enhanced comparison (opt-in, gated, sourced)
# --------------------------------------------------------------------------- #

_PROMPT_RULES = (
    "You are an LSAT tutor comparing a student's reasoning to the correct "
    "reasoning on ONE problem.\n"
    "STRICT RULES:\n"
    "1. Reason ONLY about the stimulus and the two choices given below. Add no "
    "outside facts or invented choices.\n"
    "2. Explain how the student's reasoning path (why their choice tempted them) "
    "differs from the credited path, and name the single distinguishing move.\n"
    "3. Ground every claim in the stimulus or the choice's trap type.\n"
    "4. Be concise, concrete, and encouraging."
)


def build_compare_context(exp, chosen, credited) -> str:
    """A compact, fully-grounded description of just this item's decision.

    Only the answered item's stimulus and the two relevant choices are included,
    so no other pair member can leak into the prompt."""
    lines: list[str] = []
    if exp.section:
        lines.append(f"Section: {exp.section}")
    if exp.stimulus:
        lines.append(f"Stimulus: {exp.stimulus}")
    if exp.question:
        lines.append(f"Question: {exp.question}")
    if credited is not None:
        lines.append(f"Credited answer ({credited.id}): {credited.text}")
        if credited.why:
            lines.append(f"Why credited: {credited.why}")
    if chosen is not None:
        if chosen.correct:
            lines.append("Student's choice: the credited answer (correct).")
            tempt = _most_tempting(exp)
            if tempt is not None:
                tag = f" [trap: {tempt.trap_label}]" if tempt.trap_label else ""
                lines.append(f"Most tempting distractor ({tempt.id}){tag}: {tempt.text}")
                if tempt.why:
                    lines.append(f"Why it is wrong: {tempt.why}")
        else:
            tag = f" [trap: {chosen.trap_label}]" if chosen.trap_label else ""
            ru = " (runner-up)" if chosen.is_runner_up else ""
            lines.append(f"Student's choice ({chosen.id}){ru}{tag}: {chosen.text}")
            if chosen.why:
                lines.append(f"Why the student's choice is wrong: {chosen.why}")
    if exp.schemas:
        s = exp.schemas[0]
        desc = f" — {s['description']}" if s.get("description") else ""
        lines.append(f"Tested schema: {s['label']}{desc}")
    return "\n".join(lines)


def build_compare_prompt(context: str) -> str:
    """A grounding-hardened single-string prompt; ``context`` is sanitized."""
    from speedrun.ai.guard import sanitize_source_text

    safe = sanitize_source_text(context)
    return "\n".join(
        [
            _PROMPT_RULES,
            "",
            "Problem and the two choices:",
            '"""',
            safe,
            '"""',
            "",
            "Compare the student's reasoning to the correct reasoning:",
        ]
    )


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def compare_reasoning(
    item: dict[str, Any],
    chosen_id: str,
    *,
    items: list[dict[str, Any]] | None = None,
    credited_id: str | None = None,
    client=None,
) -> ReasoningComparison:
    """Compare the student's ``chosen_id`` answer on ``item`` to the credited one.

    Uses the LLM (grounded to this item's decision) only when AI is enabled and it
    returns a usable, named-source response; otherwise a deterministic grounded
    comparison. ``credited_id`` is derived from the item when not supplied."""
    from speedrun.explanations import explain_item

    exp = explain_item(item, items=items)
    resolved_credited = credited_id or (exp.correct.id if exp.correct else "")
    chosen_id = (chosen_id or "").strip()

    verdict, offline_text, chosen_trap = offline_comparison(exp, chosen_id)

    if _ai_on():
        try:
            if client is None:
                from speedrun.ai.client import default_client

                client = default_client()
            chosen = _find_choice(exp, chosen_id)
            context = build_compare_context(exp, chosen, exp.correct)
            prompt = build_compare_prompt(context)
            resp = client.complete(prompt, max_tokens=MAX_TOKENS)
            if getattr(resp, "ok", False):
                return ReasoningComparison(
                    item_id=exp.item_id,
                    chosen_id=chosen_id,
                    credited_id=resolved_credited,
                    verdict=verdict,
                    chosen_trap=chosen_trap,
                    comparison=resp.text.strip(),
                    source=resp.source,
                    ai_used=True,
                    citations=[
                        "Grounded in this problem's stimulus, your choice, the "
                        "credited choice, and the trap/fork rationale"
                    ],
                )
        except Exception:
            pass  # fall through to the offline comparison

    return ReasoningComparison(
        item_id=exp.item_id,
        chosen_id=chosen_id,
        credited_id=resolved_credited,
        verdict=verdict,
        chosen_trap=chosen_trap,
        comparison=offline_text,
        source="offline",
        ai_used=False,
        citations=(["Tested schema: " + exp.schemas[0]["label"]] if exp.schemas else []),
    )


def load_items(path: Path = DEFAULT_SEED) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(data.get("items", []))


def compare_for_bridge(
    item_id: str, chosen_id: str, *, path: Path = DEFAULT_SEED
) -> dict[str, Any]:
    """Thin wrapper the aqt drill bridge calls; resolves the item by id and
    returns a JSON-serializable reply. Never raises."""
    try:
        items = load_items(path)
        item = next((it for it in items if it.get("id") == item_id), None)
        if item is None:
            return {
                "item_id": item_id,
                "chosen_id": chosen_id,
                "credited_id": "",
                "verdict": "unknown",
                "chosen_trap": None,
                "comparison": "That problem could not be found.",
                "source": "offline",
                "ai_used": False,
                "citations": [],
            }
        return compare_reasoning(item, chosen_id, items=items).to_dict()
    except Exception as exc:  # pragma: no cover - never break the drill
        return {
            "item_id": item_id,
            "chosen_id": chosen_id,
            "credited_id": "",
            "verdict": "unknown",
            "chosen_trap": None,
            "comparison": f"Sorry — I hit an error comparing that ({type(exc).__name__}).",
            "source": "offline",
            "ai_used": False,
            "citations": [],
        }
