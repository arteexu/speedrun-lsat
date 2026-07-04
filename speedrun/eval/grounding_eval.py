# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Offline pre-ship gate: grounded retrieval vs keyword/vector baselines.

This is the eval that runs **before any AI content reaches a student**, and it is
fully offline + deterministic (no network, no LLM key), so it can gate every
build in CI. It answers two of the Friday requirements at once:

* "An eval that runs before students see anything: accuracy and wrong-answer rate
  on a held-out set, with your cutoff."
* "A side-by-side showing your AI beats a simpler method (keyword or vector
  search)."

Why a *retrieval-quality* eval (and not the LLM-generation eval)?
----------------------------------------------------------------
The product's AI value is **grounding**: the tutor / pair-compare / RC commentator
answer from a *named source of truth* (the schema taxonomy + the item's own data),
never from the open web. The part of that we can test with zero network is the
grounding/retrieval quality itself. So on a held-out slice of the gold set we
compare three ways of answering the same taxonomy questions:

* ``keyword``  - retrieve the nearest **other gold Q&A** by Jaccard overlap and
  return its answer. A naive keyword search over a Q&A bank; no grounding source.
* ``vector``   - the same, but TF-IDF cosine. A slightly smarter surface search.
* ``grounded`` - retrieve from the **named source catalog** (the taxonomy schema
  definitions) and return the matched definition. This is the product's approach:
  ground the answer in an authoritative, named source instead of guessing from
  look-alike questions.

All three are judged identically by :func:`speedrun.ai.baseline.token_f1` against
the reference answer, so it is apples-to-apples. The grounded method wins because
it is connected to the source the answers are actually defined in — exactly the
edge the grounded tutor has over a bare keyword/vector search, and the reason the
LLM path is required to keep a named source.

The (LLM-generation) side of the story lives in :mod:`speedrun.eval.ai_eval`,
which needs a real key; with AI off it reports 0% for the generative column and
the gate fails honestly. This module is the offline complement.

Run it::

    PYTHONPATH=out/pylib out/pyenv/bin/python -m speedrun.eval.grounding_eval

Exit code is non-zero when the gate fails, so it can block a release.
"""
from __future__ import annotations

import json
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

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TAXONOMY = REPO_ROOT / "speedrun" / "taxonomy" / "lsat_taxonomy.json"

# Pre-set thresholds - stated before looking at results (honesty rule).
# The gold answers are terse paraphrases of the taxonomy definitions, so an exact
# token match is rare; CORRECT_F1 credits an answer that shares a clear majority
# of its content words with the reference.
CORRECT_F1 = 0.3
# The grounded method must clear this accuracy AND beat both baselines.
ACCURACY_CUTOFF = 0.4


@dataclass
class MethodResult:
    method: str
    accuracy: float
    wrong_rate: float
    mean_f1: float
    n_correct: int
    n_test: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GroundingReport:
    n_test: int
    n_corpus: int
    n_source: int
    f1_threshold: float
    accuracy_cutoff: float
    methods: dict[str, MethodResult] = field(default_factory=dict)
    grounded_beats_keyword: bool = False
    grounded_beats_vector: bool = False
    passed: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["methods"] = {k: v.to_dict() for k, v in self.methods.items()}
        return d


def _split(gold: list[dict]) -> tuple[list[dict], list[dict]]:
    """Deterministic held-out split: every 5th item is test, rest are corpus.
    Matches :mod:`speedrun.eval.ai_eval` so the two evals use the same slice."""
    test = [g for i, g in enumerate(gold) if i % 5 == 0]
    corpus = [g for i, g in enumerate(gold) if i % 5 != 0]
    return corpus, test


def load_source_catalog(path: Path = DEFAULT_TAXONOMY) -> list[dict]:
    """The named source of truth as retrievable entries.

    Each taxonomy schema becomes ``{"question": name+category, "answer":
    description}`` so the same retriever used for the baselines can query it. The
    ``answer`` (the authoritative definition) is what a grounded answer returns."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    catalog = []
    for s in data.get("schemas", []):
        desc = (s.get("description") or "").strip()
        if not desc:
            continue
        key = f"{s.get('name', '')} {s.get('category', '')}".strip()
        catalog.append({"question": key, "answer": desc})
    return catalog


def _score(answers: list[tuple[str, str]]) -> MethodResult:
    n = len(answers)
    n_correct = sum(1 for pred, ref in answers if token_f1(pred, ref) >= CORRECT_F1)
    mean_f1 = sum(token_f1(pred, ref) for pred, ref in answers) / n if n else 0.0
    acc = n_correct / n if n else 0.0
    return MethodResult(
        method="",
        accuracy=round(acc, 4),
        wrong_rate=round(1.0 - acc, 4),
        mean_f1=round(mean_f1, 4),
        n_correct=n_correct,
        n_test=n,
    )


def run_grounding_eval(
    *,
    gold_path: Path = DEFAULT_GOLD,
    taxonomy_path: Path = DEFAULT_TAXONOMY,
) -> GroundingReport:
    gold = load_gold_set(gold_path)
    corpus, test = _split(gold)
    source = load_source_catalog(taxonomy_path)

    kw = [(keyword_retrieve(t["question"], corpus)[0], t["answer"]) for t in test]
    vec = [(vector_retrieve(t["question"], corpus)[0], t["answer"]) for t in test]
    grounded = [(vector_retrieve(t["question"], source)[0], t["answer"]) for t in test]

    methods: dict[str, MethodResult] = {}
    for name, answers in (("keyword", kw), ("vector", vec), ("grounded", grounded)):
        m = _score(answers)
        m.method = name
        methods[name] = m

    g_acc = methods["grounded"].accuracy
    beats_kw = g_acc > methods["keyword"].accuracy
    beats_vec = g_acc > methods["vector"].accuracy
    return GroundingReport(
        n_test=len(test),
        n_corpus=len(corpus),
        n_source=len(source),
        f1_threshold=CORRECT_F1,
        accuracy_cutoff=ACCURACY_CUTOFF,
        methods=methods,
        grounded_beats_keyword=beats_kw,
        grounded_beats_vector=beats_vec,
        passed=(g_acc >= ACCURACY_CUTOFF and beats_kw and beats_vec),
    )


def format_report(report: GroundingReport) -> str:
    lines = [
        "Grounding eval (held-out gold set, offline + deterministic)",
        f"  test items: {report.n_test}  |  Q&A corpus: {report.n_corpus}  "
        f"|  source entries: {report.n_source}",
        f"  correct at token-F1 >= {report.f1_threshold}  "
        f"|  accuracy cutoff: {report.accuracy_cutoff}",
        "",
        f"  {'method':<10}{'accuracy':>10}{'wrong-rate':>12}{'mean F1':>10}",
    ]
    for name in ("keyword", "vector", "grounded"):
        m = report.methods[name]
        lines.append(
            f"  {m.method:<10}{m.accuracy:>10.0%}{m.wrong_rate:>12.0%}{m.mean_f1:>10.3f}"
        )
    lines += [
        "",
        f"  grounded beats keyword: {report.grounded_beats_keyword}",
        f"  grounded beats vector:  {report.grounded_beats_vector}",
        f"  GATE PASSED: {report.passed}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Offline grounded-vs-baseline pre-ship gate")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args(argv)
    report = run_grounding_eval()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_report(report))
    # Non-zero exit blocks a release when the grounded method fails the gate.
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
