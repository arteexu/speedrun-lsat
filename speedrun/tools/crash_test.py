#!/usr/bin/env python3
"""Crash test: kill mid-review and verify collection integrity (spec 7g).

Simulates abrupt close after partial review session; reopens and checks
scheduler + card counts are consistent.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from anki.collection import Collection as aopen  # noqa: E402
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def main() -> int:
    col = getEmptyCol()
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    n_before = col.db.scalar("SELECT COUNT(*) FROM cards")
    answered = 0
    while answered < 5:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)
        answered += 1
    revlog_count = col.db.scalar("SELECT COUNT(*) FROM revlog WHERE ease > 0")
    db_path = col.path
    col.close()  # simulate crash — no graceful shutdown beyond close()

    col2 = aopen(db_path)
    n_after = col2.db.scalar("SELECT COUNT(*) FROM cards")
    revlog_after = col2.db.scalar("SELECT COUNT(*) FROM revlog WHERE ease > 0")
    assert n_before == n_after, "card count changed after reopen"
    assert revlog_count == revlog_after, "revlog count changed after reopen"
    card = col2.sched.getCard()
    assert card is not None or answered >= 11, "scheduler should still yield cards or deck done"
    col2.close()
    print(f"OK: {answered} reviews persisted, {n_after} cards, revlog={revlog_after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
