# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Card checker with a pre-set cutoff (spec 7f).

Two layers:
  * Keyword topicality vs the gold set (works fully offline, AI off).
  * Optional LLM correctness check: when a usable client is supplied, the model
    is asked whether the item's marked-correct answer is actually best; a "no"
    forces the item to fail as ``wrong`` regardless of keyword score.

`block_failing` returns only the items at/above cutoff, so generated cards can be
gated before students ever see them.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from speedrun.ai.baseline import load_gold_set
from speedrun.ai.client import LLMClient

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLD = REPO_ROOT / "speedrun" / "data" / "gold_set.json"

# Pre-set cutoff - stated before looking at results.
#
# The topicality score (see ``gold_topicality``) is the best *content*-token F1
# (English + LSAT question-frame stopwords removed) of an item's question +
# marked-correct answer against the taxonomy gold set's question+answer pairs.
# It is a deliberately LENIENT off-topic FLOOR, not the main quality gate: the
# 50-item gold set does not cover every word in a 500-item deck, so a high bar
# would falsely reject genuine items. Correctness is decided by the LLM veto and
# teaching quality by the difficulty/duplicate heuristics below. Calibrated so
# off-topic gibberish (0.0 content overlap) is blocked while a genuine LSAT item
# that names its taxonomy concept clears it (good card ~0.47; ~87% of the curated
# seed clears 0.05, the rest use vocabulary outside the terse gold concepts).
PASSING_CUTOFF = 0.05

# Below this there is essentially no topical alignment with the taxonomy at all
# (off-topic or malformed) — treated as "wrong" on the offline path.
_WRONG_FLOOR = 0.02

# Two items whose stimuli overlap at/above this Jaccard are treated as near
# duplicates (the second is demoted to bad-teaching).
_DUPLICATE_JACCARD = 0.8

_WORD = re.compile(r"[a-z]{3,}")

# Generic English words + LSAT question-frame boilerplate. Removed before
# measuring topical overlap so the score reflects real conceptual alignment
# (e.g. "correlation", "causation", "sample") rather than shared frame words
# ("what", "the", "following", "reasoning").
_STOPWORDS = frozenset(
    """the and that this for are was were with from which one following most
    argument arguments reasoning because vulnerable criticism statement statements
    above true support supports supported what whether does play role each any all
    also into than then them they their there here when will would could should
    more some such only other others its it is in on of to as by or an be been
    being has have had not no nor but if so we you he she his her our your question
    answer choice choices best help helps justify conform conforms above given
    about over under out very much many few said says claim claims""".split()
)


def _content_tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall((text or "").lower()) if w not in _STOPWORDS]


def _token_set(text: str) -> set[str]:
    return set(_content_tokens(text))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _content_f1(a: str, b: str) -> float:
    from collections import Counter

    ca, cb = Counter(_content_tokens(a)), Counter(_content_tokens(b))
    if not ca or not cb:
        return 0.0
    overlap = sum((ca & cb).values())
    if overlap == 0:
        return 0.0
    precision = overlap / sum(ca.values())
    recall = overlap / sum(cb.values())
    return 2 * precision * recall / (precision + recall)


def _correct_choice_text(item: dict) -> str:
    for c in item.get("choices", []):
        if c.get("correct"):
            return c.get("text", "") or ""
    return item.get("answer", "") or ""


def gold_topicality(item: dict, gold: list[dict]) -> float:
    """Best content-token F1 of the item's question + marked answer against any
    gold question+answer. Measures whether the card is on-topic for the taxonomy.

    Unlike the old raw-stimulus Jaccard (which the long stimulus diluted to near
    zero for every real item), this compares the *claim the card teaches* — its
    stem plus the answer it marks correct — to the terse gold concepts with
    frame words removed, so a genuine LSAT flaw item aligns with its gold concept
    while gibberish does not.
    """
    text = f"{item.get('question', '')} {_correct_choice_text(item)}".strip()
    if not text:
        return 0.0
    best = 0.0
    for g in gold:
        ref = f"{g.get('question', '')} {g.get('answer', '')}"
        best = max(best, _content_f1(text, ref))
    return best


@dataclass
class CheckResult:
    item_id: str
    passed: bool
    score: float
    category: str  # correct_useful | wrong | correct_bad_teaching
    reason: str
    llm_verified: bool | None = None  # None when no LLM check was run

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
        if score < _WRONG_FLOOR:
            return "wrong", "No topical alignment with the taxonomy gold set — off-topic or malformed."
        return "correct_bad_teaching", "Below topicality cutoff — weak/marginal alignment."
    if item.get("difficulty", 1) <= 1:
        return "correct_bad_teaching", "Trivial or low-difficulty content."
    return "correct_useful", "Clears topicality cutoff and (if run) the LLM correctness check."


def _llm_verify_correct(item: dict, client: LLMClient) -> bool | None:
    """Ask the model whether the item's marked-correct answer is truly best.
    Returns True/False, or None if AI unavailable / unparseable."""
    choices = item.get("choices", [])
    correct = next((c for c in choices if c.get("correct")), None)
    if not correct:
        return None
    rendered = "\n".join(f"({c.get('id')}) {c.get('text','')}" for c in choices)
    prompt = (
        "You are checking an LSAT item. Is the marked answer actually the single "
        "best answer to the question given the stimulus? Reply ONLY as JSON: "
        '{"correct": true|false}.\n\n'
        f"Stimulus: {item.get('stimulus') or item.get('passage','')}\n"
        f"Question: {item.get('question','')}\n"
        f"Choices:\n{rendered}\n"
        f"Marked answer: {correct.get('id')}"
    )
    resp = client.complete(prompt, max_tokens=64)
    if not resp.ok:
        return None
    m = re.search(r'"correct"\s*:\s*(true|false)', resp.text, re.I)
    if not m:
        return None
    return m.group(1).lower() == "true"


def check_card(
    item: dict,
    gold: list[dict],
    *,
    cutoff: float = PASSING_CUTOFF,
    client: LLMClient | None = None,
) -> CheckResult:
    score = gold_topicality(item, gold)
    passed = score >= cutoff
    category, reason = _classify(score, passed, item)

    llm_verified: bool | None = None
    if client is not None:
        llm_verified = _llm_verify_correct(item, client)
        if llm_verified is False:
            passed = False
            category = "wrong"
            reason = "LLM check: the marked answer is not the best answer."

    # Only correct & useful cards ship. A "correct but bad teaching" card (trivial
    # or below the topicality floor) is blocked too — passed is true iff the card
    # is in the correct_useful bucket (spec 7f: "failing cards are BLOCKED").
    passed = category == "correct_useful"

    return CheckResult(
        item_id=item.get("id", "?"),
        passed=passed,
        score=score,
        category=category,
        reason=reason,
        llm_verified=llm_verified,
    )


def check_items(
    items: list[dict],
    *,
    gold_path: Path = DEFAULT_GOLD,
    cutoff: float = PASSING_CUTOFF,
    client: LLMClient | None = None,
) -> CheckerReport:
    gold = load_gold_set(gold_path)
    results = [check_card(it, gold, cutoff=cutoff, client=client) for it in items]

    # Batch-level near-duplicate demotion: a correct card that merely repeats an
    # earlier card's stimulus teaches nothing new, so it counts as bad teaching
    # (spec 7f count 3: "duplicate"). Only demotes items that otherwise passed.
    by_id = {it.get("id", "?"): it for it in items}
    seen_tokens: list[set[str]] = []
    for r in results:
        item = by_id.get(r.item_id, {})
        toks = _token_set(item.get("stimulus") or item.get("passage") or item.get("question", ""))
        is_dup = any(
            _jaccard(toks, prev) >= _DUPLICATE_JACCARD for prev in seen_tokens
        )
        if not is_dup:
            seen_tokens.append(toks)
        elif r.passed:
            r.passed = False
            r.category = "correct_bad_teaching"
            r.reason = "Near-duplicate of an earlier card — no new teaching value."

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


def block_failing(
    items: list[dict],
    *,
    gold_path: Path = DEFAULT_GOLD,
    cutoff: float = PASSING_CUTOFF,
    client: LLMClient | None = None,
) -> tuple[list[dict], CheckerReport]:
    """Return (only items that passed the checker, report). This is the gate that
    keeps wrong/weak generated cards away from students."""
    report = check_items(items, gold_path=gold_path, cutoff=cutoff, client=client)
    passed_ids = {r.item_id for r in report.results if r.passed}
    kept = [it for it in items if it.get("id", "?") in passed_ids]
    return kept, report


@dataclass
class GateTally:
    """Running three-count tally for a streaming card-checker gate."""

    cutoff: float
    n_checked: int = 0
    n_passed: int = 0
    n_blocked: int = 0
    correct_useful: int = 0
    wrong: int = 0
    correct_bad_teaching: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CardCheckGate:
    """Reusable single-item ship gate for the generation pipeline (spec 7f).

    The gold set is loaded once, then :meth:`check` is called on each candidate
    draft as it is produced. This is the same keyword/cutoff (plus optional LLM
    correctness veto) logic as :func:`check_items`, exposed as a streaming gate so
    ``generate_to_target`` can reject failing items *before* they are written and
    still emit the three-count report (correct_useful / wrong / correct_bad_teaching).
    """

    def __init__(
        self,
        *,
        gold_path: Path = DEFAULT_GOLD,
        cutoff: float = PASSING_CUTOFF,
        client: LLMClient | None = None,
    ) -> None:
        self.gold = load_gold_set(gold_path)
        self.cutoff = cutoff
        self.client = client
        self.tally = GateTally(cutoff=cutoff)

    def check(self, item: dict) -> CheckResult:
        """Check one item, update the running tally, and return its result.

        ``result.passed`` is ``True`` iff the item cleared the pre-set cutoff (and
        was not vetoed by the optional LLM correctness check)."""
        result = check_card(item, self.gold, cutoff=self.cutoff, client=self.client)
        self.tally.n_checked += 1
        if result.passed:
            self.tally.n_passed += 1
        else:
            self.tally.n_blocked += 1
        setattr(
            self.tally,
            result.category,
            getattr(self.tally, result.category) + 1,
        )
        return result


def check_seed_deck(seed_path: Path | None = None) -> CheckerReport:
    path = seed_path or REPO_ROOT / "speedrun" / "data" / "seed_deck.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return check_items(data["items"])
