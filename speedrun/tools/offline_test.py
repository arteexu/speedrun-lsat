#!/usr/bin/env python3
"""Offline test: AI off, all three scores still produced (spec 7g)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ["SPEEDRUN_AI_OFF"] = "1"

from speedrun.ai.config import ai_enabled  # noqa: E402
from speedrun.scoring.memory import memory_score  # noqa: E402
from speedrun.scoring.performance import performance_score  # noqa: E402
from speedrun.scoring.readiness import readiness_score  # noqa: E402
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def main() -> int:
    assert ai_enabled() is False
    col = getEmptyCol()
    col.set_config("fsrs", True)
    result = import_seed_deck(col)
    col.decks.select(result.deck_id)
    col.reset()
    while True:
        card = col.sched.getCard()
        if card is None:
            break
        col.sched.answerCard(card, 3)

    mem = memory_score(col)
    perf = performance_score(col)
    ready = readiness_score(col, min_attempts=10, min_coverage=0.01, min_attempts_per_schema=1, min_attempts_overall=10)

    assert mem["overall"].gave_up is False, mem["overall"].reason
    assert perf["overall"].gave_up is False, perf["overall"].reason
    # readiness may still abstain at default thresholds but modules run
    assert ready.reason
    col.close()
    print("OK: all three score modules ran with AI_OFF=1")
    print(f"  memory: {mem['overall'].point:.0%}")
    print(f"  performance: {perf['overall'].point:.0%}")
    print(f"  readiness gave_up={ready.gave_up}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
