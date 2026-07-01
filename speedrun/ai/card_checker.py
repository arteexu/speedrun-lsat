# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Card checker against gold set with pre-set cutoff (spec 7f).

Works with AI_OFF=true using keyword overlap; LLM path optional when enabled.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from speedrun.ai.baseline import keyword_score
from speedrun.ai.baseline import load_gold_set
from speedrun.ai.client import default_client

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLD = REPO_ROOT / "speedrun" / "data" / "gold_set.json"

# Pre-set cutoff — stated before looking at results.
PASSING_CUTOFF = 0.35


@dataclass
class CheckResult:
    item_id: str
    passed: bool
    score: float
    category: str  # correct_useful | wrong | correct_bad_teaching
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CheckerReport:
    cutoff: float
    n_checked: int
    n_passed: int
    n_failed: int
    correct_useful: int
    wrong: int
    correct_bad_teaching: int
    results: list[CheckResult]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["results"] = [r.to_dict() for r in self.results]
        return d


def _classify(score: float, passed: bool, item: dict) -> tuple[str, str]:
    if not passed:
        if score < 0.1:
            return "wrong", "No overlap with gold set — likely wrong or off-topic."
        return "correct_bad_teaching", "Below cutoff — vague or weak teaching value."
    if item.get("difficulty", 1) <= 1:
        return "correct_bad_teaching", "Trivial or duplicate content."
    return "correct_useful", "Passes keyword baseline cutoff."


def check_card(
    item: dict,
    gold: list[dict],
    *,
    cutoff: float = PASSING_CUTOFF,
) -> CheckResult:
    q = item.get("question", "") + " " + item.get("stimulus", "")
    score = keyword_score(q, "", gold)
    passed = score >= cutoff
    category, reason = _classify(score, passed, item)
    return CheckResult(
        item_id=item.get("id", "?"),
        passed=passed,
        score=score,
        category=category,
        reason=reason,
    )


def check_items(
    items: list[dict],
    *,
    gold_path: Path = DEFAULT_GOLD,
    cutoff: float = PASSING_CUTOFF,
) -> CheckerReport:
    gold = load_gold_set(gold_path)
    _ = default_client()  # reserved for LLM-enhanced check when AI on
    results = [check_card(it, gold, cutoff=cutoff) for it in items]
    counts = {"correct_useful": 0, "wrong": 0, "correct_bad_teaching": 0}
    for r in results:
        counts[r.category] += 1
    return CheckerReport(
        cutoff=cutoff,
        n_checked=len(results),
        n_passed=sum(1 for r in results if r.passed),
        n_failed=sum(1 for r in results if not r.passed),
        correct_useful=counts["correct_useful"],
        wrong=counts["wrong"],
        correct_bad_teaching=counts["correct_bad_teaching"],
        results=results,
    )


def check_seed_deck(seed_path: Path | None = None) -> CheckerReport:
    path = seed_path or REPO_ROOT / "speedrun" / "data" / "seed_deck.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return check_items(data["items"])
