# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Simple baselines the AI must beat, plus shared answer-scoring.

Two non-AI methods answer a taxonomy question by *retrieving* the closest entry
from a corpus and returning its answer:
  * keyword  - Jaccard overlap of question tokens.
  * vector   - TF-IDF cosine similarity (pure stdlib, no numpy).

`token_f1` is the automatic answer-correctness metric shared by the eval harness
so AI and baselines are judged identically.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLD = REPO_ROOT / "speedrun" / "data" / "gold_set.json"

_TOKEN = re.compile(r"[a-z]{3,}")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _token_set(text: str) -> set[str]:
    return set(_tokens(text))


def load_gold_set(path: Path = DEFAULT_GOLD) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["items"]


# --------------------------- answer scoring --------------------------------


def token_f1(predicted: str, reference: str) -> float:
    """Token-overlap F1 between a predicted answer and the reference answer.
    Deterministic, offline; used to judge AI and baselines on equal terms."""
    pred = Counter(_tokens(predicted))
    ref = Counter(_tokens(reference))
    if not pred or not ref:
        return 0.0
    overlap = sum((pred & ref).values())
    if overlap == 0:
        return 0.0
    precision = overlap / sum(pred.values())
    recall = overlap / sum(ref.values())
    return 2 * precision * recall / (precision + recall)


# --------------------------- keyword baseline ------------------------------


def keyword_score(question: str, answer: str, gold_entries: list[dict]) -> float:
    """Best Jaccard overlap between question tokens and any gold question.
    Kept for the card checker (answer arg unused)."""
    q_tok = _token_set(question)
    if not q_tok:
        return 0.0
    best = 0.0
    for entry in gold_entries:
        gq = _token_set(entry["question"])
        if not gq:
            continue
        overlap = len(q_tok & gq) / len(q_tok | gq)
        best = max(best, overlap)
    return best


def keyword_retrieve(question: str, corpus: list[dict]) -> tuple[str, float]:
    """Return (answer, similarity) of the corpus entry whose question best
    matches by Jaccard overlap."""
    q_tok = _token_set(question)
    best_ans, best = "", 0.0
    if not q_tok:
        return best_ans, best
    for entry in corpus:
        gq = _token_set(entry["question"])
        if not gq:
            continue
        sim = len(q_tok & gq) / len(q_tok | gq)
        if sim > best:
            best, best_ans = sim, entry.get("answer", "")
    return best_ans, best


# --------------------------- vector baseline -------------------------------


class TfidfIndex:
    """Tiny TF-IDF cosine index over corpus questions (stdlib only)."""

    def __init__(self, corpus: list[dict]) -> None:
        self.corpus = corpus
        docs = [_tokens(e["question"]) for e in corpus]
        df: Counter[str] = Counter()
        for toks in docs:
            df.update(set(toks))
        n = max(1, len(docs))
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}
        self.doc_vecs = [self._vec(toks) for toks in docs]

    def _vec(self, tokens: list[str]) -> dict[str, float]:
        tf = Counter(tokens)
        return {t: (tf[t] / len(tokens)) * self.idf.get(t, 0.0) for t in tf} if tokens else {}

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        common = set(a) & set(b)
        dot = sum(a[t] * b[t] for t in common)
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        return dot / (na * nb) if na and nb else 0.0

    def retrieve(self, question: str) -> tuple[str, float]:
        qv = self._vec(_tokens(question))
        best_i, best = -1, 0.0
        for i, dv in enumerate(self.doc_vecs):
            sim = self._cosine(qv, dv)
            if sim > best:
                best, best_i = sim, i
        if best_i < 0:
            return "", 0.0
        return self.corpus[best_i].get("answer", ""), best


def vector_retrieve(question: str, corpus: list[dict]) -> tuple[str, float]:
    return TfidfIndex(corpus).retrieve(question)
