# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Pre-ship AI eval + baseline comparison (Friday spec).

Held-out task: answer taxonomy questions. Baselines RETRIEVE the closest answer
from a train corpus (keyword / TF-IDF vector); the AI GENERATES an answer from
the question alone.

FAIRNESS (§14.3): every method is judged by the SAME two metrics against the
same gold reference, so the side-by-side is apples-to-apples and never tilted
toward the AI:

  * ``token_f1`` - lexical overlap vs the (terse) reference answer. Cheap and
    deterministic, but it penalizes a correct answer that is *paraphrased* or
    *fuller* than the reference and rewards verbatim retrieval. Kept for
    transparency, but no longer the sole judge.
  * fair metric (LLM judge) - a yes/no "is this answer correct and equivalent
    to the reference?" asked via ``LLMClient.complete``. It grades keyword,
    vector, and AI outputs with the *identical* prompt, so semantic-equivalence
    credit is given the same way to every method (not AI-preferring).

Both metrics are reported per method. The gate passes only when the AI clears a
pre-set accuracy cutoff AND beats BOTH baselines *on the fair metric*, AND the
leakage check is clean. Numbers are computed before any AI content is shown to
students. Deterministic split so the run is reproducible.

Graceful degradation (determinism/offline): the LLM judge needs AI switched on
(and a usable key). When AI is off or the judge cannot produce a usable verdict,
the fair metric falls back to ``token_f1`` and the report says so - it never
crashes. Offline unit tests drive a scripted client for deterministic verdicts.

Leakage enforcement (spec 7e / §14.3 / §19): the held-out gold set must not
overlap the training/seed data above threshold. Leaked test data invalidates the
score, so any leak forces the gate to FAIL (non-zero exit) regardless of accuracy.
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
from speedrun.ai.config import ai_enabled
from speedrun.eval.leakage_check import DEFAULT_SEED, leakage_check

# Pre-set thresholds - stated before looking at results.
ANSWER_F1_THRESHOLD = 0.5   # an answer counts correct at F1 >= this vs reference
ACCURACY_CUTOFF = 0.6       # AI must answer at least this fraction correctly
LEAKAGE_THRESHOLD = 0.6     # gold/seed jaccard at/above this is a leak (zeroes the score)

# Label used for the fair metric in the report when the live LLM judge ran.
FAIR_METRIC_LLM_JUDGE = "llm-judge (semantic equivalence)"
# ...and when it could not run and we transparently fell back to token_f1.
FAIR_METRIC_FALLBACK = "token_f1 (fallback: fair LLM judge needs AI on + a key)"


@dataclass
class MethodResult:
    method: str
    # token_f1 metric (kept for transparency).
    accuracy: float
    wrong_rate: float
    n_correct: int
    # Fair metric (LLM judge, or token_f1 fallback). Reported side by side.
    fair_accuracy: float
    fair_wrong_rate: float
    n_fair_correct: int
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
    fair_metric: str
    fair_metric_available: bool
    methods: dict[str, MethodResult] = field(default_factory=dict)
    # AI vs baselines on the FAIR metric (what the gate uses).
    ai_beats_keyword: bool = False
    ai_beats_vector: bool = False
    # AI vs baselines on token_f1 (kept for transparency).
    ai_beats_keyword_f1: bool = False
    ai_beats_vector_f1: bool = False
    leakage_clean: bool = True
    leakage_hits: int = 0
    leakage_threshold: float = LEAKAGE_THRESHOLD
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


def _f1_correct(pred: str, ref: str) -> bool:
    return token_f1(pred, ref) >= ANSWER_F1_THRESHOLD


_JUDGE_PROMPT = (
    "You are grading answers to an LSAT reasoning-concept question. Decide whether "
    "the CANDIDATE answer is CORRECT and semantically equivalent to the REFERENCE "
    "answer: it names the same concept, even if it is phrased differently, is fuller, "
    "or uses different words. Ignore verbosity and wording; judge only the meaning. "
    'Reply with exactly one word, "yes" or "no".\n\n'
    "Question: {question}\n"
    "Reference answer: {reference}\n"
    "Candidate answer: {candidate}\n"
    "Is the candidate correct and equivalent to the reference?"
)


def judge_equivalent(
    question: str, candidate: str, reference: str, client: LLMClient
) -> bool | None:
    """LLM judge for a single answer.

    Returns ``True``/``False`` for a usable verdict, or ``None`` when the judge
    could not run (no usable response from ``client`` - e.g. AI off, no key, or a
    network error). ``None`` is the graceful-degradation signal: the caller falls
    back to ``token_f1`` rather than crashing. Applied identically to every method
    so the comparison stays fair.
    """
    ref = (reference or "").strip()
    if not ref:
        return None
    prompt = _JUDGE_PROMPT.format(
        question=(question or "").strip(),
        reference=ref,
        candidate=(candidate or "").strip() or "(no answer)",
    )
    resp = client.complete(prompt, max_tokens=4)
    if not resp.ok:
        return None
    return resp.text.strip().lower().startswith("y")


def _fair_scores(
    per_method: dict[str, list[tuple[str, str, str]]], judge_client: LLMClient
) -> tuple[dict[str, int], bool]:
    """Grade every method with the LLM judge (identical prompt).

    ``per_method`` maps method name -> list of ``(question, predicted, reference)``.
    Returns ``(n_fair_correct_by_method, available)`` where ``available`` is True
    iff the judge produced at least one usable verdict across the whole run.
    """
    correct_by_method: dict[str, int] = {}
    available = False
    for name, items in per_method.items():
        correct = 0
        for question, pred, ref in items:
            verdict = judge_equivalent(question, pred, ref, judge_client)
            if verdict is None:
                continue
            available = True
            if verdict:
                correct += 1
        correct_by_method[name] = correct
    return correct_by_method, available


def run_ai_eval(
    *,
    gold_path: Path = DEFAULT_GOLD,
    train_path: Path = DEFAULT_SEED,
    leakage_threshold: float = LEAKAGE_THRESHOLD,
    client: LLMClient | None = None,
    judge_client: LLMClient | None = None,
) -> EvalReport:
    client = client or default_client()
    judge_client = judge_client or client
    gold = load_gold_set(gold_path)
    corpus, test = _split(gold)

    # Each entry: (question, predicted_answer, reference_answer).
    kw: list[tuple[str, str, str]] = [
        (t["question"], keyword_retrieve(t["question"], corpus)[0], t["answer"])
        for t in test
    ]
    vec: list[tuple[str, str, str]] = [
        (t["question"], vector_retrieve(t["question"], corpus)[0], t["answer"])
        for t in test
    ]
    ai_source = "stub"
    ai: list[tuple[str, str, str]] = []
    for t in test:
        resp = client.complete(
            "Answer this LSAT reasoning-concept question in one concise sentence, "
            "using precise terminology. Question: " + t["question"],
            max_tokens=128,
        )
        if resp.source and resp.source != "stub":
            ai_source = resp.source
        ai.append((t["question"], resp.text if resp.ok else "", t["answer"]))

    per_method: dict[str, list[tuple[str, str, str]]] = {
        "keyword": kw,
        "vector": vec,
        "ai": ai,
    }

    # Fair metric: LLM judge, but only when AI is on (the live judge needs a key).
    # Otherwise we degrade gracefully to token_f1 and say so in the report.
    fair_available = False
    fair_correct: dict[str, int] = {}
    if ai_enabled():
        fair_correct, fair_available = _fair_scores(per_method, judge_client)

    methods: dict[str, MethodResult] = {}
    for name, items in per_method.items():
        n = len(items)
        f1_correct = sum(1 for _, pred, ref in items if _f1_correct(pred, ref))
        f1_acc = f1_correct / n if n else 0.0
        if fair_available:
            fair_c = fair_correct.get(name, 0)
        else:
            # Graceful fallback: mirror the token_f1 result as the fair metric.
            fair_c = f1_correct
        fair_acc = fair_c / n if n else 0.0
        methods[name] = MethodResult(
            method=name,
            accuracy=round(f1_acc, 4),
            wrong_rate=round(1.0 - f1_acc, 4),
            n_correct=f1_correct,
            fair_accuracy=round(fair_acc, 4),
            fair_wrong_rate=round(1.0 - fair_acc, 4),
            n_fair_correct=fair_c,
            n_test=n,
        )

    # The gate compares the AI to the baselines on the FAIR metric.
    ai_fair = methods["ai"].fair_accuracy
    beats_kw = ai_fair > methods["keyword"].fair_accuracy
    beats_vec = ai_fair > methods["vector"].fair_accuracy
    # token_f1 comparison kept alongside for transparency.
    ai_f1 = methods["ai"].accuracy
    beats_kw_f1 = ai_f1 > methods["keyword"].accuracy
    beats_vec_f1 = ai_f1 > methods["vector"].accuracy

    # Leakage enforcement: a leaked held-out item zeroes the score (spec §14.3/§19).
    leak = leakage_check(
        gold_path=gold_path, train_path=train_path, threshold=leakage_threshold
    )
    return EvalReport(
        n_test=len(test),
        n_corpus=len(corpus),
        f1_threshold=ANSWER_F1_THRESHOLD,
        accuracy_cutoff=ACCURACY_CUTOFF,
        ai_source=ai_source,
        fair_metric=FAIR_METRIC_LLM_JUDGE if fair_available else FAIR_METRIC_FALLBACK,
        fair_metric_available=fair_available,
        methods=methods,
        ai_beats_keyword=beats_kw,
        ai_beats_vector=beats_vec,
        ai_beats_keyword_f1=beats_kw_f1,
        ai_beats_vector_f1=beats_vec_f1,
        leakage_clean=leak.clean,
        leakage_hits=leak.n_hits,
        leakage_threshold=leakage_threshold,
        passed=(
            ai_fair >= ACCURACY_CUTOFF and beats_kw and beats_vec and leak.clean
        ),
    )


def format_report(report: EvalReport) -> str:
    lines = [
        "AI eval (held-out gold set)",
        f"  test items: {report.n_test}  |  corpus: {report.n_corpus}",
        f"  F1 threshold: {report.f1_threshold}  |  accuracy cutoff: {report.accuracy_cutoff}",
        f"  AI source: {report.ai_source}",
        f"  fair metric: {report.fair_metric}",
        "",
        f"  {'method':<10}{'f1-acc':>9}{'f1-wrong':>10}{'fair-acc':>10}{'fair-wrong':>12}",
    ]
    for name in ("keyword", "vector", "ai"):
        m = report.methods[name]
        lines.append(
            f"  {m.method:<10}{m.accuracy:>9.0%}{m.wrong_rate:>10.0%}"
            f"{m.fair_accuracy:>10.0%}{m.fair_wrong_rate:>12.0%}"
        )
    leak_txt = (
        "clean"
        if report.leakage_clean
        else f"LEAK ({report.leakage_hits} hit(s)) — score zeroed"
    )
    lines += [
        "",
        "  Gate compares on the FAIR metric (LLM judge; identical prompt per method):",
        f"  AI beats keyword: {report.ai_beats_keyword}"
        f"   (token_f1: {report.ai_beats_keyword_f1})",
        f"  AI beats vector:  {report.ai_beats_vector}"
        f"   (token_f1: {report.ai_beats_vector_f1})",
        f"  Leakage (thr {report.leakage_threshold}): {leak_txt}",
        f"  GATE PASSED: {report.passed}",
    ]
    if not report.fair_metric_available:
        lines.append(
            "  NOTE: fair LLM judge did not run (AI off or no key) — fair-acc "
            "mirrors token_f1. Enable AI + set a key for the semantic-equivalence "
            "judge."
        )
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    _report = run_ai_eval()
    print(format_report(_report))
    # Non-zero exit blocks a release when the AI fails the cutoff / baselines.
    raise SystemExit(0 if _report.passed else 1)
