# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Paraphrase / transfer-gap test (spec 7d, PRD §10.2 / §17).

Compare recall on taught cards with accuracy on reworded questions testing the
same schema. A large gap (recall >> transfer) means memory is not transfer;
recall ≈ transfer means the performance bridge is not built yet.

Grading paths (in precedence order).
------------------------------------
1. **Real reworded attempts.** Actual graded attempts on paraphrased items
   (recorded via :func:`record_reworded_attempt` and read back with
   :func:`load_reworded_attempts`, or passed straight to
   :func:`transfer_gap_report`). This is the honest path the spec asks for: the
   transfer number comes from the student answering *reworded* questions on the
   same schema, not from a proxy.
2. **Synthetic** (test harness only) when ``synthetic_transfer_penalty`` is set.
3. **Proxy fallback.** When no real reworded attempts exist yet, fall back to
   revlog attempts on schema-tagged cards so the dashboard still shows a
   (clearly labelled) estimate. The report's ``source`` field records which path
   produced the number.

Reworded *variants* (the questions themselves) are drawn from each item's
hand-authored ``paraphrases`` where present, falling back to synthetic surface
noun-swaps so every card still yields ``variants_per_card`` items.
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
# Where real graded reworded attempts are persisted (offline JSON store).
DEFAULT_ATTEMPTS_STORE = REPO_ROOT / "speedrun" / "data" / "reworded_attempts.json"

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
class RewordedAttempt:
    """A real, graded attempt on a paraphrased (reworded) item.

    This is the transfer-side evidence: the student answered a reworded question
    testing ``schema`` and we recorded whether it was ``correct`` and how long it
    took. ``latency_ms`` is first-class (SPOV4) so the transfer number can be
    latency-adjusted exactly like the performance score.
    """

    source_id: str
    schema: str
    correct: bool
    latency_ms: int
    variant_index: int = 0
    timestamp: int = field(default_factory=lambda: int(time.time()))

    def to_attempt(self) -> Attempt:
        return Attempt(
            schema=self.schema, correct=bool(self.correct), latency_ms=int(self.latency_ms)
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    # Which grading path produced the transfer number: "real", "synthetic", or "proxy".
    source: str = "proxy"
    n_real_attempts: int = 0
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
        source_note = {
            "real": "graded attempts on reworded items",
            "synthetic": "simulated (test harness)",
            "proxy": "proxy — revlog attempts (no real reworded grading yet)",
        }.get(self.source, self.source)
        lines.extend(
            [
                f"Cards evaluated: {self.n_cards}",
                f"Reworded items: {self.n_reworded}",
                f"Transfer source: {source_note}",
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


# --------------------------- real reworded-attempt store ---------------------


def load_reworded_attempts(
    store_path: Path = DEFAULT_ATTEMPTS_STORE,
) -> list[RewordedAttempt]:
    """Read persisted real reworded attempts. Returns [] when the store is absent."""
    p = Path(store_path)
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    return [RewordedAttempt(**row) for row in raw]


def record_reworded_attempt(
    *,
    source_id: str,
    schema: str,
    correct: bool,
    latency_ms: int,
    variant_index: int = 0,
    timestamp: int | None = None,
    store_path: Path = DEFAULT_ATTEMPTS_STORE,
) -> RewordedAttempt:
    """Append one graded reworded-item attempt to the offline JSON store.

    This is the data path the transfer test consumes: as the student answers
    reworded questions, each attempt is recorded here and later summed into a
    *real* transfer number by :func:`transfer_gap_report`. Deterministic and
    offline; no AI. Returns the stored attempt.
    """
    attempt = RewordedAttempt(
        source_id=source_id,
        schema=schema,
        correct=bool(correct),
        latency_ms=int(latency_ms),
        variant_index=int(variant_index),
        timestamp=int(timestamp if timestamp is not None else time.time()),
    )
    p = Path(store_path)
    existing = load_reworded_attempts(p)
    existing.append(attempt)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps([a.to_dict() for a in existing], indent=2), encoding="utf-8"
    )
    return attempt


# --------------------------------- report ------------------------------------


def _abstain(recall, variants, reason: str, *, source: str, n_real: int) -> TransferGapReport:
    return TransferGapReport(
        n_cards=getattr(recall, "n_reviewed", recall.n_cards),
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
        reason=reason,
        source=source,
        n_real_attempts=n_real,
    )


def transfer_gap_report(
    col,
    *,
    seed_path: Path = DEFAULT_SEED,
    reworded_attempts: list[RewordedAttempt | Attempt] | None = None,
    attempts_store: Path | None = DEFAULT_ATTEMPTS_STORE,
    synthetic_transfer_penalty: float | None = None,
    rng=None,
) -> TransferGapReport:
    """Compare memory recall vs reworded transfer accuracy.

    Grading path precedence (see module docstring):

    1. ``reworded_attempts`` passed in, or loaded from ``attempts_store`` — the
       real transfer signal (``source="real"``).
    2. ``synthetic_transfer_penalty`` — simulated attempts for harness tests
       (``source="synthetic"``).
    3. Proxy: revlog attempts on schema-tagged cards, used only when no real
       reworded attempts exist yet (``source="proxy"``).
    """
    import random

    rng = rng or random.Random(42)
    mem = memory_score(col)
    recall = mem["overall"]
    variants = generate_reworded_variants(seed_path)

    # Resolve real reworded attempts: explicit arg wins, else load the store.
    real: list[RewordedAttempt] = []
    if reworded_attempts:
        real = [
            a if isinstance(a, RewordedAttempt)
            else RewordedAttempt(
                source_id="", schema=a.schema, correct=a.correct, latency_ms=a.latency_ms
            )
            for a in reworded_attempts
        ]
    elif reworded_attempts is None and attempts_store is not None:
        real = load_reworded_attempts(attempts_store)

    if real:
        source = "real"
    elif synthetic_transfer_penalty is not None:
        source = "synthetic"
    else:
        source = "proxy"

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
            source=source,
            n_real_attempts=len(real),
        )

    if source == "real":
        attempts = [a.to_attempt() for a in real]
    elif source == "synthetic":
        attempts = _synthetic_reworded_attempts(
            variants,
            recall_rate=recall.point,
            transfer_penalty=synthetic_transfer_penalty,
            rng=rng,
        )
    else:
        # Proxy: revlog attempts until real reworded grading has been recorded.
        from speedrun.scoring.performance import collection_attempts

        attempts = collection_attempts(col)

    if len(attempts) < MIN_CARDS:
        kind = "reworded" if source in ("real", "synthetic") else "reworded/transfer"
        return _abstain(
            recall,
            variants,
            f"Not enough {kind} attempts: {len(attempts)} < {MIN_CARDS}.",
            source=source,
            n_real=len(real),
        )

    transfer = score_from_attempts(attempts, label="reworded", min_attempts=MIN_CARDS)
    if transfer.gave_up or transfer.point is None:
        return _abstain(
            recall,
            variants,
            f"Transfer abstains: {transfer.reason}",
            source=source,
            n_real=len(real),
        )

    gap = recall.point - transfer.point
    bridge_distinct = abs(gap) >= 0.05 or transfer.speed_flag
    reason = {
        "real": "Compared FSRS recall vs latency-adjusted accuracy on real reworded items.",
        "synthetic": "Compared FSRS recall vs simulated reworded accuracy (test harness).",
        "proxy": (
            "Compared FSRS recall vs latency-adjusted transfer accuracy "
            "(proxy: revlog attempts — record reworded attempts for a real number)."
        ),
    }[source]

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
        reason=reason,
        source=source,
        n_real_attempts=len(real),
    )
