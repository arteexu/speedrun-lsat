# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Pre-ship AI eval + baseline comparison (Friday spec).

Held-out task: answer taxonomy questions. Baselines RETRIEVE the closest answer
from a train corpus (keyword / TF-IDF vector); the AI GENERATES an answer from
the question alone. All three are judged identically by ``token_f1`` against the
reference answer, so the comparison is apples-to-apples.

Reported per method: accuracy and wrong-answer rate. The gate passes only when
the AI clears a pre-set accuracy cutoff AND beats both baselines. Numbers are
computed before any AI content is shown to students. Deterministic split so the
run is reproducible.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from speedrun.ai.baseline import (
    DEFAULT_GOLD,
    keyword_retrieve,
    load_gold_set,
    token_f1,
    vector_retrieve,
)
from speedrun.ai.client import LLMClient, default_client

# Pre-set thresholds - stated before looking at results.
ANSWER_F1_THRESHOLD = 0.5   # an answer counts correct at F1 >= this vs reference
ACCURACY_CUTOFF = 0.6       # AI must answer at least this fraction correctly


@dataclass
class MethodResult:
    method: str
    accuracy: float
    wrong_rate: float
    n_correct: int
    n_test: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvalReport:
    n_test: int
    n_corpus: int
    f1_threshold: float
    accuracy_cutoff: float
    ai_source: str
    methods: dict[str, MethodResult] = field(default_factory=dict)
    ai_beats_keyword: bool = False
    ai_beats_vector: bool = False
    passed: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["methods"] = {k: v.to_dict() for k, v in self.methods.items()}
        return d


def _split(gold: list[dict]) -> tuple[list[dict], list[dict]]:
    """Deterministic held-out split: every 5th item is test, rest are corpus."""
    test = [g for i, g in enumerate(gold) if i % 5 == 0]
    corpus = [g for i, g in enumerate(gold) if i % 5 != 0]
    return corpus, test


def _score(answers: list[tuple[str, str]]) -> tuple[int, int]:
    """answers = [(predicted, reference)]; returns (n_correct, n_total)."""
    correct = sum(1 for pred, ref in answers if token_f1(pred, ref) >= ANSWER_F1_THRESHOLD)
    return correct, len(answers)


def _ai_answer(question: str, client: LLMClient) -> str:
    prompt = (
        "Answer this LSAT reasoning-concept question in one concise sentence, "
        "using precise terminology. Question: " + question
    )
    resp = client.complete(prompt, max_tokens=128)
    return resp.text if resp.ok else ""


def run_ai_eval(
    *,
    gold_path: Path = DEFAULT_GOLD,
    client: LLMClient | None = None,
) -> EvalReport:
    client = client or default_client()
    gold = load_gold_set(gold_path)
    corpus, test = _split(gold)

    kw = [(keyword_retrieve(t["question"], corpus)[0], t["answer"]) for t in test]
    vec = [(vector_retrieve(t["question"], corpus)[0], t["answer"]) for t in test]
    ai_source = "stub"
    ai_answers: list[tuple[str, str]] = []
    for t in test:
        resp = client.complete(
            "Answer this LSAT reasoning-concept question in one concise sentence, "
            "using precise terminology. Question: " + t["question"],
            max_tokens=128,
        )
        if resp.source and resp.source != "stub":
            ai_source = resp.source
        ai_answers.append((resp.text if resp.ok else "", t["answer"]))

    methods: dict[str, MethodResult] = {}
    for name, answers in (("keyword", kw), ("vector", vec), ("ai", ai_answers)):
        n_correct, n = _score(answers)
        acc = n_correct / n if n else 0.0
        methods[name] = MethodResult(
            method=name,
            accuracy=round(acc, 4),
            wrong_rate=round(1.0 - acc, 4),
            n_correct=n_correct,
            n_test=n,
        )

    ai_acc = methods["ai"].accuracy
    beats_kw = ai_acc > methods["keyword"].accuracy
    beats_vec = ai_acc > methods["vector"].accuracy
    return EvalReport(
        n_test=len(test),
        n_corpus=len(corpus),
        f1_threshold=ANSWER_F1_THRESHOLD,
        accuracy_cutoff=ACCURACY_CUTOFF,
        ai_source=ai_source,
        methods=methods,
        ai_beats_keyword=beats_kw,
        ai_beats_vector=beats_vec,
        passed=(ai_acc >= ACCURACY_CUTOFF and beats_kw and beats_vec),
    )


def format_report(report: EvalReport) -> str:
    lines = [
        "AI eval (held-out gold set)",
        f"  test items: {report.n_test}  |  corpus: {report.n_corpus}",
        f"  F1 threshold: {report.f1_threshold}  |  accuracy cutoff: {report.accuracy_cutoff}",
        f"  AI source: {report.ai_source}",
        "",
        f"  {'method':<10}{'accuracy':>10}{'wrong-rate':>12}",
    ]
    for name in ("keyword", "vector", "ai"):
        m = report.methods[name]
        lines.append(f"  {m.method:<10}{m.accuracy:>10.0%}{m.wrong_rate:>12.0%}")
    lines += [
        "",
        f"  AI beats keyword: {report.ai_beats_keyword}",
        f"  AI beats vector:  {report.ai_beats_vector}",
        f"  GATE PASSED: {report.passed}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    print(format_report(run_ai_eval()))
