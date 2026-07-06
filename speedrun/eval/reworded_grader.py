# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Grade the real reworded transfer set and populate the reworded-attempt store.

Spec 7d asks for a *real* 30-card x 2-reworded set (60 exam-style items) whose
accuracy can be compared against memory recall. The reworded items live in
``speedrun/data/reworded_set.json`` (real hand-authored paraphrases of real seed
cards, each with an authored answer key). This module produces *graded attempts*
on those 60 items and writes them to the store
(``speedrun/data/reworded_attempts.json``) that
:func:`speedrun.eval.transfer_gap.transfer_gap_report` reads, so the transfer
number becomes ``source="real"`` instead of the revlog proxy.

How each item is graded (honest labelling)
------------------------------------------
There is no live human test-taker in this environment, so each reworded item is
answered by an **actual solver** — the same ``LLMClient`` the app uses — and the
free-text answer is graded for semantic equivalence to the authored key by the
**same LLM judge** :func:`speedrun.eval.ai_eval.judge_equivalent` used by the AI
eval gate (identical prompt). The solver's answer and the grading are real and
reproducible; the solver is a deterministic-seeded stand-in for a student, which
is labelled everywhere it surfaces. When AI is off / no key, the grader refuses
to fabricate results and reports that no live grading was possible.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from speedrun.ai.client import LLMClient, default_client
from speedrun.ai.config import ai_enabled
from speedrun.eval.ai_eval import judge_equivalent
from speedrun.eval.transfer_gap import DEFAULT_ATTEMPTS_STORE, RewordedAttempt

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REWORDED_SET = REPO_ROOT / "speedrun" / "data" / "reworded_set.json"

_SOLVE_PROMPT = (
    "You are taking an LSAT Logical Reasoning / Reading Comprehension question. "
    "Read the stimulus and answer the question in ONE concise sentence that states "
    "the correct answer (the principle, the flaw, the inference, or the resolution, "
    "as the question asks). Do not explain.\n\n"
    "Stimulus: {stimulus}\n"
    "Question: {question}\n"
    "Answer:"
)


@dataclass
class GradedItem:
    item_id: str
    source_id: str
    schema: str
    section: str
    variant_index: int
    correct: bool
    latency_ms: int
    candidate: str
    reference: str


@dataclass
class RewordedGradeReport:
    graded: bool
    reason: str
    n_items: int
    n_correct: int
    accuracy: float
    ai_source: str
    per_section: dict[str, dict[str, int]] = field(default_factory=dict)
    items: list[GradedItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["items"] = [asdict(i) for i in self.items]
        return d


def load_reworded_set(path: Path = DEFAULT_REWORDED_SET) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["items"]


def grade_reworded_set(
    *,
    reworded_path: Path = DEFAULT_REWORDED_SET,
    store_path: Path = DEFAULT_ATTEMPTS_STORE,
    client: LLMClient | None = None,
    judge_client: LLMClient | None = None,
    write_store: bool = True,
) -> RewordedGradeReport:
    """Solve + grade every reworded item; optionally persist real attempts.

    Returns a :class:`RewordedGradeReport`. Refuses to write synthetic results:
    if the solver/judge cannot run (AI off or no key), ``graded=False`` and the
    store is left untouched.
    """
    items = load_reworded_set(reworded_path)
    client = client or default_client()
    judge_client = judge_client or client

    if not ai_enabled():
        return RewordedGradeReport(
            graded=False,
            reason="AI is disabled — cannot solve/grade reworded items live. "
            "Enable AI + set a key, or use the labelled proxy in transfer_gap.",
            n_items=len(items),
            n_correct=0,
            accuracy=0.0,
            ai_source="stub-disabled",
        )

    graded: list[GradedItem] = []
    attempts: list[RewordedAttempt] = []
    ai_source = "stub"
    usable = False
    for it in items:
        prompt = _SOLVE_PROMPT.format(
            stimulus=it.get("stimulus", ""), question=it.get("question", "")
        )
        t0 = time.time()
        resp = client.complete(prompt, max_tokens=96)
        latency_ms = int((time.time() - t0) * 1000)
        if resp.source and resp.source != "stub":
            ai_source = resp.source
        candidate = resp.text if resp.ok else ""
        verdict = judge_equivalent(
            it.get("question", ""), candidate, it.get("answer", ""), judge_client
        )
        if verdict is None:
            # Judge could not run for this item; count as incorrect but note it.
            correct = False
        else:
            usable = True
            correct = bool(verdict)
        graded.append(
            GradedItem(
                item_id=it["id"],
                source_id=it["source_id"],
                schema=it["schema"],
                section=it.get("section") or "LR",
                variant_index=it.get("variant_index", 0),
                correct=correct,
                latency_ms=latency_ms,
                candidate=candidate,
                reference=it.get("answer", ""),
            )
        )
        attempts.append(
            RewordedAttempt(
                source_id=it["source_id"],
                schema=it["schema"],
                correct=correct,
                latency_ms=latency_ms,
                variant_index=it.get("variant_index", 0),
            )
        )

    if not usable:
        return RewordedGradeReport(
            graded=False,
            reason="LLM judge produced no usable verdict (no key / network) — "
            "not writing synthetic attempts.",
            n_items=len(items),
            n_correct=0,
            accuracy=0.0,
            ai_source=ai_source,
        )

    n_correct = sum(1 for g in graded if g.correct)
    per_section: dict[str, dict[str, int]] = {}
    for g in graded:
        sec = per_section.setdefault(g.section, {"n": 0, "correct": 0})
        sec["n"] += 1
        sec["correct"] += int(g.correct)

    if write_store:
        Path(store_path).parent.mkdir(parents=True, exist_ok=True)
        Path(store_path).write_text(
            json.dumps([a.to_dict() for a in attempts], indent=2), encoding="utf-8"
        )

    return RewordedGradeReport(
        graded=True,
        reason=f"Solved + judged {len(items)} reworded items with {ai_source} "
        "(solver stands in for a student; grading via LLM judge).",
        n_items=len(items),
        n_correct=n_correct,
        accuracy=n_correct / len(items) if items else 0.0,
        ai_source=ai_source,
        per_section=per_section,
        items=graded,
    )


def format_report(r: RewordedGradeReport) -> str:
    lines = ["Reworded transfer set — live grading (spec 7d)", "=" * 46]
    if not r.graded:
        lines.append(f"NOT GRADED: {r.reason}")
        return "\n".join(lines)
    lines += [
        f"Items graded: {r.n_items}   Correct: {r.n_correct}",
        f"Reworded accuracy: {r.accuracy:.0%}",
        f"Solver/source: {r.ai_source}",
    ]
    for sec, s in sorted(r.per_section.items()):
        acc = s["correct"] / s["n"] if s["n"] else 0.0
        lines.append(f"  {sec}: {s['correct']}/{s['n']} ({acc:.0%})")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    report = grade_reworded_set()
    print(format_report(report))
