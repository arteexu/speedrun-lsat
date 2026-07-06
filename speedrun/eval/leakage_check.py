# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Leakage check: scan training data for test-item overlap (spec 7f)."""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLD = REPO_ROOT / "speedrun" / "data" / "gold_set.json"
DEFAULT_SEED = REPO_ROOT / "speedrun" / "data" / "seed_deck.json"

_WORD = re.compile(r"[a-z]{4,}")


@dataclass
class LeakageHit:
    test_id: str
    train_id: str
    jaccard: float
    shared_sample: str


@dataclass
class LeakageReport:
    clean: bool
    n_hits: int
    threshold: float
    hits: list[LeakageHit]
    reason: str
    n_gold: int = 0
    n_train: int = 0
    n_comparisons: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["hits"] = [asdict(h) for h in self.hits]
        return d


def _text_blob(item: dict) -> str:
    parts = [item.get("question", ""), item.get("stimulus", ""), item.get("answer", "")]
    for c in item.get("choices", []):
        parts.append(c.get("text", ""))
    return " ".join(parts).lower()


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def leakage_check(
    *,
    gold_path: Path = DEFAULT_GOLD,
    train_path: Path = DEFAULT_SEED,
    threshold: float = 0.6,
) -> LeakageReport:
    gold = json.loads(gold_path.read_text(encoding="utf-8"))["items"]
    train = json.loads(train_path.read_text(encoding="utf-8"))["items"]
    hits: list[LeakageHit] = []
    for test in gold:
        t_tok = set(_WORD.findall(_text_blob(test)))
        for tr in train:
            tr_tok = set(_WORD.findall(_text_blob(tr)))
            j = _jaccard(t_tok, tr_tok)
            if j >= threshold:
                shared = " ".join(sorted(t_tok & tr_tok))[:120]
                hits.append(
                    LeakageHit(
                        test_id=test.get("id", "?"),
                        train_id=tr.get("id", "?"),
                        jaccard=j,
                        shared_sample=shared,
                    )
                )
    clean = len(hits) == 0
    return LeakageReport(
        clean=clean,
        n_hits=len(hits),
        threshold=threshold,
        hits=hits,
        reason="No overlap above threshold." if clean else f"{len(hits)} potential leak(s) found.",
        n_gold=len(gold),
        n_train=len(train),
        n_comparisons=len(gold) * len(train),
    )
