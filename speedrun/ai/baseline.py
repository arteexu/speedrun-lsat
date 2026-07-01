# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Keyword baseline for AI comparison (spec 7f)."""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLD = REPO_ROOT / "speedrun" / "data" / "gold_set.json"

_TOKEN = re.compile(r"[a-z]{3,}")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def keyword_score(question: str, answer: str, gold_entries: list[dict]) -> float:
    """Jaccard overlap between question tokens and gold Q tokens; pick best answer match."""
    q_tok = _tokens(question)
    if not q_tok:
        return 0.0
    best = 0.0
    for entry in gold_entries:
        gq = _tokens(entry["question"])
        if not gq:
            continue
        overlap = len(q_tok & gq) / len(q_tok | gq)
        if overlap > best:
            best = overlap
    return best


def load_gold_set(path: Path = DEFAULT_GOLD) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["items"]
