# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Independent AI-solver verification for generated items.

The card_generator writes an item *with* its intended answer key. This module is
the adversarial cross-check: a separate, low-temperature model call is shown the
item **with the answer key hidden** (no ``correct`` flags, no traps, no
rationale) and asked to solve it cold. The item only passes if the solver:

  1. independently picks the same letter the author credited, AND
  2. reports that exactly one choice is clearly best (no ambiguity).

This catches the two failure modes that matter for a self-authored deck: the
credited answer is not actually defensible, and items with more than one
defensible answer. It is a self-consistency gate (same model family), so it is
honest about what it proves: not "a human agrees", but "the answer survives an
independent cold solve". Empty/again-unavailable AI yields ``None`` (unknown),
never a silent pass.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from speedrun.ai.client import LLMClient


@dataclass
class SolveResult:
    passed: bool
    chosen: str | None       # the letter the solver picked
    credited: str | None     # the letter the author marked correct
    single_best: bool | None  # solver's ambiguity judgement
    reason: str

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "chosen": self.chosen,
            "credited": self.credited,
            "single_best": self.single_best,
            "reason": self.reason,
        }


def _credited_letter(item: dict) -> str | None:
    for c in item.get("choices", []):
        if c.get("correct"):
            return str(c.get("id"))
    return None


def _render_blind(item: dict) -> str:
    """Render the item with the answer key stripped out."""
    stem = item.get("stimulus") or item.get("passage", "")
    lines = [f"Passage/Stimulus: {stem}", f"Question: {item.get('question','')}", "Choices:"]
    for c in item.get("choices", []):
        lines.append(f"({c.get('id')}) {c.get('text','')}")
    return "\n".join(lines)


def solve_item(item: dict, client: LLMClient) -> SolveResult:
    """Cold-solve ``item`` and compare against the author's credited answer."""
    credited = _credited_letter(item)
    if not credited:
        return SolveResult(False, None, None, None, "no credited answer on item")

    prompt = (
        "You are an expert LSAT test-taker. Solve the question below on the merits. "
        "You are NOT told which answer is intended; decide yourself.\n\n"
        f"{_render_blind(item)}\n\n"
        "Reply ONLY as compact JSON, no prose:\n"
        '{"answer":"A|B|C|D|E","single_best":true|false,"why":"<=25 words"}\n'
        "Set single_best to true ONLY if exactly one choice is clearly correct and "
        "every other choice is clearly wrong for this specific task. If two or more "
        "choices could defensibly be selected, set single_best to false."
    )
    resp = client.complete(prompt, max_tokens=120)
    if not resp.ok:
        return SolveResult(False, None, credited, None, f"solver unavailable ({resp.source})")

    chosen = None
    m = re.search(r'"answer"\s*:\s*"?([A-E])"?', resp.text, re.I)
    if m:
        chosen = m.group(1).upper()
    sb = None
    m2 = re.search(r'"single_best"\s*:\s*(true|false)', resp.text, re.I)
    if m2:
        sb = m2.group(1).lower() == "true"

    if chosen is None:
        return SolveResult(False, None, credited, sb, "solver produced no parseable letter")
    if chosen != credited:
        return SolveResult(
            False, chosen, credited, sb,
            f"solver picked {chosen}, author credited {credited}",
        )
    if sb is False:
        return SolveResult(False, chosen, credited, sb, "solver reports more than one defensible answer")
    return SolveResult(True, chosen, credited, sb, "solver agrees; single defensible answer")


def _extract_json_obj(text: str) -> dict | None:
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    s, e = t.find("{"), t.rfind("}")
    if s == -1 or e <= s:
        return None
    try:
        obj = json.loads(t[s : e + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None
