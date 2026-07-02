# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Reasoning evaluator stub — pattern weakness detection (spec 7f).

Grades student explanations against two-answer-fork rationales and surfaces
recurring flaw/trap patterns. Stub works offline with keyword heuristics.
"""
from __future__ import annotations

import re
from dataclasses import asdict
from dataclasses import dataclass
from typing import Any

from speedrun.ai.client import default_client

_TRAP_PATTERNS = {
    "trap.out_of_scope": re.compile(r"out of scope|irrelevant|unrelated", re.I),
    "trap.too_weak": re.compile(r"too weak|doesn't (weaken|strengthen)", re.I),
    "trap.opposite": re.compile(r"opposite|strengthens instead", re.I),
    "flaw.causal.correlation_causation": re.compile(r"correlation|causation|cause", re.I),
    "flaw.conditional.mistaken_reversal": re.compile(r"sufficient|necessary|reversal", re.I),
}


@dataclass
class WeaknessPattern:
    schema: str
    count: int
    examples: list[str]


@dataclass
class ReasoningEval:
    score: float  # 0-1
    matched_rationale: bool
    weakness_patterns: list[WeaknessPattern]
    feedback: str
    source: str = "offline"  # "offline" or the model id (traceability rule)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["weakness_patterns"] = [asdict(w) for w in self.weakness_patterns]
        return d


def _llm_grade(student_text: str, fork_rationale: str, client) -> tuple[float, str, str] | None:
    """LLM grade grounded to the fork rationale. Returns (score, feedback, source)
    or None if AI unavailable/unparseable, so callers fall back to the heuristic."""
    if not fork_rationale.strip():
        return None
    prompt = (
        "You are grading a student's LSAT explanation against the official "
        "rationale for why the runner-up answer is wrong. Ground your judgment "
        "ONLY in the rationale. Reply as JSON: "
        '{"score": 0.0-1.0, "feedback": "one sentence"}.\n\n'
        f"Official rationale: {fork_rationale}\n"
        f"Student explanation: {student_text}"
    )
    resp = client.complete(prompt, max_tokens=128)
    if not resp.ok:
        return None
    s = re.search(r'"score"\s*:\s*([0-9]*\.?[0-9]+)', resp.text)
    f = re.search(r'"feedback"\s*:\s*"([^"]*)"', resp.text)
    if not s:
        return None
    score = max(0.0, min(1.0, float(s.group(1))))
    feedback = f.group(1) if f else "Graded against the fork rationale."
    return score, feedback, resp.source


def evaluate_explanation(
    student_text: str,
    *,
    expected_schema: str | None = None,
    fork_rationale: str = "",
    client=None,
) -> ReasoningEval:
    """Grade a student's explanation. Uses the LLM (grounded to the fork
    rationale) when available, else an offline keyword heuristic. Always tallies
    recurring flaw/trap weakness patterns (Insight 8)."""
    client = client or default_client()
    text = student_text.lower()
    rationale_hit = False
    if fork_rationale:
        rationale_hit = sum(
            1 for tok in set(re.findall(r"[a-z]{5,}", fork_rationale.lower())) if tok in text
        ) >= 2

    patterns: list[WeaknessPattern] = []
    for schema, pat in _TRAP_PATTERNS.items():
        if pat.search(student_text):
            patterns.append(WeaknessPattern(schema=schema, count=1, examples=[student_text[:80]]))

    if expected_schema and not any(p.schema == expected_schema for p in patterns):
        if expected_schema.startswith("flaw") or expected_schema.startswith("trap"):
            patterns.append(
                WeaknessPattern(
                    schema=expected_schema,
                    count=1,
                    examples=["(missing from explanation)"],
                )
            )

    score = 0.7 if rationale_hit else 0.3
    if patterns:
        score = max(0.1, score - 0.1 * len(patterns))

    feedback = (
        "Explanation references the fork rationale."
        if rationale_hit
        else "Explanation does not clearly reference the fork rationale."
    )
    if patterns:
        feedback += f" Weakness patterns: {', '.join(p.schema for p in patterns)}."

    source = "offline"
    graded = _llm_grade(student_text, fork_rationale, client)
    if graded is not None:
        score, feedback, source = graded

    return ReasoningEval(
        score=score,
        matched_rationale=rationale_hit,
        weakness_patterns=patterns,
        feedback=feedback,
        source=source,
    )
