# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Paraphrase / transfer-gap test (spec 7d).

Compare recall on taught cards with accuracy on reworded questions testing the
same schema. A large gap (recall >> transfer) means memory is not transfer;
recall ≈ transfer means the performance bridge is not built yet.

For now, reworded variants are synthetic proxies derived from seed-deck items
(by swapping surface nouns while preserving schema structure).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

from speedrun.scoring.memory import memory_score
from speedrun.scoring.performance import Attempt, score_from_attempts

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEED = REPO_ROOT / "speedrun" / "data" / "seed_deck.json"

# Minimum cards with both recall signal and reworded attempts before reporting.
MIN_CARDS = 5
VARIANTS_PER_CARD = 2

# Simple noun swaps to produce exam-style paraphrases (surface change only).
_SWAP_PAIRS = [
    ("employees", "students"),
    ("company", "university"),
    ("desks", "schedules"),
    ("headaches", "fatigue"),
    ("Maria", "James"),
    ("calculus", "logic"),
    ("puzzles", "problems"),
    ("city", "town"),
    ("mayor", "council"),
    ("traffic", "pollution"),
    ("study", "survey"),
    ("doctor", "researcher"),
    ("patients", "participants"),
    ("drug", "treatment"),
    ("novel", "book"),
    ("author", "writer"),
    ("museum", "gallery"),
    ("painting", "sculpture"),
]


@dataclass
class RewordedItem:
    source_id: str
    schema: str
    variant_index: int
    stimulus: str
    authored: bool = False  # True when drawn from an item's hand-written paraphrases
    correct: bool | None = None  # filled when graded


@dataclass
class TransferGapReport:
    n_cards: int
    n_reworded: int
    recall_point: float | None
    recall_low: float | None
    recall_high: float | None
    reworded_point: float | None
    reworded_low: float | None
    reworded_high: float | None
    gap: float | None  # recall - reworded (positive => memory overstates transfer)
    bridge_distinct: bool  # True when models meaningfully differ
    gave_up: bool
    reason: str
    last_updated: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def format_report(self) -> str:
        lines = [
            "Transfer gap report (spec 7d)",
            "=" * 40,
        ]
        if self.gave_up:
            lines.append(f"No report: {self.reason}")
            return "\n".join(lines)
        lines.extend(
            [
                f"Cards evaluated: {self.n_cards}",
                f"Reworded items: {self.n_reworded}",
                f"Recall (memory/FSRS): {self.recall_point:.0%} "
                f"[{self.recall_low:.0%}–{self.recall_high:.0%}]",
                f"Transfer (reworded):  {self.reworded_point:.0%} "
                f"[{self.reworded_low:.0%}–{self.reworded_high:.0%}]",
                f"Gap (recall − transfer): {self.gap:+.0%}",
                f"Bridge distinct from memory: {self.bridge_distinct}",
            ]
        )
        if abs(self.gap or 0) < 0.05:
            lines.append(
                "NOTE: gap ≈ 0 — performance may still echo memory; "
                "collect more reworded attempts."
            )
        return "\n".join(lines)


def _reword_stimulus(text: str, variant: int) -> str:
    out = text
    pairs = _SWAP_PAIRS[variant::VARIANTS_PER_CARD] + _SWAP_PAIRS
    for old, new in pairs[: 3 + variant]:
        out = re.sub(rf"\b{old}\b", new, out, flags=re.IGNORECASE)
    return out


def generate_reworded_variants(
    seed_path: Path = DEFAULT_SEED,
    *,
    variants_per_card: int = VARIANTS_PER_CARD,
) -> list[RewordedItem]:
    data = json.loads(seed_path.read_text(encoding="utf-8"))
    items: list[RewordedItem] = []
    for item in data["items"]:
        primary_schema = item["schemas"][0]
        source_text = item.get("stimulus") or item.get("question") or item.get("passage", "")
        # Prefer the item's hand-authored paraphrases (same schema, restated
        # surface) -- these are the real transfer variants the content plan calls
        # for. Fall back to synthetic noun-swaps so every card still yields
        # `variants_per_card` reworded items (keeps the transfer test populated).
        authored = item.get("paraphrases") or []
        for vi in range(variants_per_card):
            if vi < len(authored):
                text = authored[vi].get("stimulus") or authored[vi].get("question", "")
                items.append(
                    RewordedItem(
                        source_id=item["id"],
                        schema=primary_schema,
                        variant_index=vi,
                        stimulus=text,
                        authored=True,
                    )
                )
            else:
                items.append(
                    RewordedItem(
                        source_id=item["id"],
                        schema=primary_schema,
                        variant_index=vi,
                        stimulus=_reword_stimulus(source_text, vi),
                        authored=False,
                    )
                )
    return items


def _synthetic_reworded_attempts(
    variants: list[RewordedItem],
    *,
    recall_rate: float,
    transfer_penalty: float,
    rng,
) -> list[Attempt]:
    """Simulate graded reworded attempts: transfer is harder than recall."""
    attempts: list[Attempt] = []
    for v in variants:
        p_correct = max(0.0, min(1.0, recall_rate - transfer_penalty + rng.uniform(-0.1, 0.1)))
        correct = rng.random() < p_correct
        latency = rng.randint(30_000, 120_000)
        attempts.append(Attempt(schema=v.schema, correct=correct, latency_ms=latency))
    return attempts


def transfer_gap_report(
    col,
    *,
    seed_path: Path = DEFAULT_SEED,
    synthetic_transfer_penalty: float | None = None,
    rng=None,
) -> TransferGapReport:
    """Compare memory recall vs reworded transfer accuracy.

    When `synthetic_transfer_penalty` is set (for harness tests), reworded
    attempts are simulated with that penalty vs recall. Otherwise uses revlog
    attempts on schema-tagged cards as a proxy until real reworded grading exists.
    """
    import random

    rng = rng or random.Random(42)
    mem = memory_score(col)
    recall = mem["overall"]
    variants = generate_reworded_variants(seed_path)

    if recall.gave_up or recall.point is None:
        return TransferGapReport(
            n_cards=recall.n_cards,
            n_reworded=len(variants),
            recall_point=None,
            recall_low=None,
            recall_high=None,
            reworded_point=None,
            reworded_low=None,
            reworded_high=None,
            gap=None,
            bridge_distinct=False,
            gave_up=True,
            reason=f"Recall abstains: {recall.reason}",
        )

    if synthetic_transfer_penalty is not None:
        attempts = _synthetic_reworded_attempts(
            variants,
            recall_rate=recall.point,
            transfer_penalty=synthetic_transfer_penalty,
            rng=rng,
        )
    else:
        # Proxy: use performance model attempts until dedicated reworded grading ships.
        from speedrun.scoring.performance import collection_attempts

        attempts = collection_attempts(col)

    if len(attempts) < MIN_CARDS:
        return TransferGapReport(
            n_cards=recall.n_reviewed,
            n_reworded=len(variants),
            recall_point=recall.point,
            recall_low=recall.low,
            recall_high=recall.high,
            reworded_point=None,
            reworded_low=None,
            reworded_high=None,
            gap=None,
            bridge_distinct=False,
            gave_up=True,
            reason=f"Not enough reworded/transfer attempts: {len(attempts)} < {MIN_CARDS}.",
        )

    transfer = score_from_attempts(attempts, label="reworded", min_attempts=MIN_CARDS)
    if transfer.gave_up or transfer.point is None:
        return TransferGapReport(
            n_cards=recall.n_reviewed,
            n_reworded=len(variants),
            recall_point=recall.point,
            recall_low=recall.low,
            recall_high=recall.high,
            reworded_point=None,
            reworded_low=None,
            reworded_high=None,
            gap=None,
            bridge_distinct=False,
            gave_up=True,
            reason=f"Transfer abstains: {transfer.reason}",
        )

    gap = recall.point - transfer.point
    bridge_distinct = abs(gap) >= 0.05 or transfer.speed_flag

    return TransferGapReport(
        n_cards=recall.n_reviewed,
        n_reworded=len(variants),
        recall_point=recall.point,
        recall_low=recall.low,
        recall_high=recall.high,
        reworded_point=transfer.point,
        reworded_low=transfer.low,
        reworded_high=transfer.high,
        gap=gap,
        bridge_distinct=bridge_distinct,
        gave_up=False,
        reason="Compared FSRS recall vs latency-adjusted transfer accuracy.",
    )
