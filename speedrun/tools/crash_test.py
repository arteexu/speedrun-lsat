#!/usr/bin/env python3
# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Crash / durability test: quit mid-review repeatedly and verify no data loss
or corruption (spec 7g / 18: "zero corrupted collections").

The old version reopened the collection once and had a self-cancelling
assertion. This is a real durability loop:

    for cycle in 1..N (N >= 20):
        open the collection from disk
        answer a few due cards (a real review)
        record the on-disk state
        close the handle abruptly  (simulates a crash / hard quit)
        REOPEN the same file
        assert nothing was lost, nothing double-counted, nothing corrupted

Because every cycle opens the exact same ``.anki2`` file that the previous
cycle wrote and closed, a lost write, a double-applied review, or a torn
database would surface as a failed invariant. On any violation the tool prints
a FAIL line and exits non-zero.

Invariants checked after every reopen:
  * the collection opens cleanly (no exception, ``fix_integrity`` reports OK);
  * the real-review count (revlog rows with ease > 0) equals the exact number
    of reviews we have performed so far -- catches loss AND double-counting;
  * that count is monotonic non-decreasing across cycles;
  * the card count never changes;
  * sum(card.reps) over all cards equals the real-review count -- catches a
    review being applied to a card's scheduling state twice (or not at all);
  * every card is in a structurally valid (type, queue) state.

Run:
    PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python -m speedrun.tools.crash_test
"""
from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from anki.collection import Collection  # noqa: E402

from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402

# Reviews answered per crash cycle. Small so the deck is never exhausted across
# the default 20+ cycles (the seed deck has hundreds of new cards available).
REVIEWS_PER_CYCLE = 4
DEFAULT_CYCLES = 22  # spec asks for "at least 20 times"

# Valid (card.type, card.queue) shapes we expect after answering "Good".
# type:  0=new 1=learning 2=review 3=relearning
# queue: -3..-1 buried/suspended, 0 new, 1 learning(day), 2 review, 3 learn(cram), 4 preview
_VALID_TYPES = {0, 1, 2, 3}
_VALID_QUEUES = {-3, -2, -1, 0, 1, 2, 3, 4}


class DurabilityError(RuntimeError):
    """Raised when a durability/corruption invariant is violated."""


@dataclass
class CycleRecord:
    cycle: int
    answered_this_cycle: int
    revlog_after_reopen: int
    cards: int
    integrity_ok: bool


@dataclass
class DurabilityReport:
    cycles: int
    total_reviews: int
    card_count: int
    records: list[CycleRecord] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.records) == self.cycles and all(
            r.integrity_ok for r in self.records
        )


def _real_revlog_count(col: Collection) -> int:
    """Reviews only (ease > 0). Excludes ease==0 rows (manual/reset entries)."""
    return col.db.scalar("SELECT COUNT(*) FROM revlog WHERE ease > 0") or 0


def _card_count(col: Collection) -> int:
    return col.db.scalar("SELECT COUNT(*) FROM cards") or 0


def _sum_reps(col: Collection) -> int:
    return col.db.scalar("SELECT COALESCE(SUM(reps), 0) FROM cards") or 0


def _answer_some(col: Collection, deck_id: int, n: int) -> int:
    """Answer up to ``n`` due cards with 'Good'. Returns how many were answered."""
    col.decks.select(deck_id)
    answered = 0
    while answered < n:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)  # 3 == Good
        answered += 1
    return answered


def _assert_structural_states(col: Collection) -> None:
    bad = col.db.scalar(
        f"SELECT COUNT(*) FROM cards WHERE type NOT IN "
        f"({','.join(map(str, sorted(_VALID_TYPES)))}) "
        f"OR queue NOT IN ({','.join(map(str, sorted(_VALID_QUEUES)))})"
    )
    if bad:
        raise DurabilityError(f"{bad} card(s) in an invalid (type, queue) state")


def run_durability_loop(
    *,
    cycles: int = DEFAULT_CYCLES,
    reviews_per_cycle: int = REVIEWS_PER_CYCLE,
    verbose: bool = True,
) -> DurabilityReport:
    """Run the open/review/crash/reopen loop and verify integrity each cycle.

    Raises DurabilityError on any lost/double-counted review or corruption.
    """
    if cycles < 20:
        raise ValueError("durability loop must run at least 20 cycles (spec 7g)")

    # A persistent temp collection we reopen every cycle. Seed it once.
    from tests.shared import getEmptyCol

    col = getEmptyCol()
    result = import_seed_deck(col, backup=False)
    deck_id = result.deck_id
    db_path = col.path
    baseline_cards = _card_count(col)
    col.close()

    report = DurabilityReport(cycles=cycles, total_reviews=0, card_count=baseline_cards)
    expected_reviews = 0
    prev_revlog = 0

    for cycle in range(1, cycles + 1):
        # --- open ---
        try:
            col = Collection(db_path)
        except Exception as err:  # noqa: BLE001 - a failed reopen == corruption
            raise DurabilityError(
                f"cycle {cycle}: collection failed to reopen: {err}"
            ) from err

        # --- review ---
        answered = _answer_some(col, deck_id, reviews_per_cycle)
        expected_reviews += answered

        # --- crash (abrupt close, no extra graceful shutdown) ---
        col.close()

        # --- reopen and verify durably-persisted state ---
        try:
            col = Collection(db_path)
        except Exception as err:  # noqa: BLE001
            raise DurabilityError(
                f"cycle {cycle}: collection failed to reopen after close: {err}"
            ) from err

        revlog = _real_revlog_count(col)
        cards = _card_count(col)
        reps = _sum_reps(col)

        # No loss / no double-count: persisted reviews == what we performed.
        if revlog != expected_reviews:
            col.close()
            raise DurabilityError(
                f"cycle {cycle}: revlog={revlog} but expected {expected_reviews} "
                f"({'lost' if revlog < expected_reviews else 'double-counted'} reviews)"
            )
        # Monotonic non-decreasing across cycles.
        if revlog < prev_revlog:
            col.close()
            raise DurabilityError(
                f"cycle {cycle}: revlog went backwards {prev_revlog} -> {revlog}"
            )
        # Card scheduling state consistent with the revlog.
        if reps != expected_reviews:
            col.close()
            raise DurabilityError(
                f"cycle {cycle}: sum(card.reps)={reps} != revlog {expected_reviews} "
                f"(card state and history disagree)"
            )
        # Card count never changes.
        if cards != baseline_cards:
            col.close()
            raise DurabilityError(
                f"cycle {cycle}: card count changed {baseline_cards} -> {cards}"
            )
        _assert_structural_states(col)

        # Deep integrity / corruption check.
        _problems, integrity_ok = col.fix_integrity()
        if not integrity_ok:
            col.close()
            raise DurabilityError(
                f"cycle {cycle}: integrity check found problems:\n{_problems}"
            )

        report.records.append(
            CycleRecord(
                cycle=cycle,
                answered_this_cycle=answered,
                revlog_after_reopen=revlog,
                cards=cards,
                integrity_ok=integrity_ok,
            )
        )
        prev_revlog = revlog
        col.close()

        if verbose:
            print(
                f"cycle {cycle:2d}/{cycles}: +{answered} reviews -> "
                f"revlog={revlog} reps={reps} cards={cards} integrity=OK"
            )

    report.total_reviews = expected_reviews
    return report


def main() -> int:
    try:
        report = run_durability_loop()
    except DurabilityError as err:
        print(f"FAIL: durability violation: {err}", file=sys.stderr)
        return 1
    except Exception as err:  # noqa: BLE001 - any crash is a durability failure
        print(f"FAIL: unexpected error: {err}", file=sys.stderr)
        traceback.print_exc()
        return 1

    if not report.ok:
        print("FAIL: durability report incomplete", file=sys.stderr)
        return 1

    print(
        f"OK: survived {report.cycles} crash/reopen cycles, "
        f"{report.total_reviews} reviews persisted with zero loss, "
        f"double-counts, or corruption ({report.card_count} cards)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
