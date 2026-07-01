# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for schema drill, health check, queue section/interleaving."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.scoring.queue import (  # noqa: E402
    build_search,
    ordered_cards,
    plain_due_cards,
)
from speedrun.tools.health_check import run_checks  # noqa: E402
from speedrun.tools.import_seed_deck import import_seed_deck  # noqa: E402
from speedrun.tools.schema_drill import (
    drill_search,
    schema_drill_queue,
    weakest_schemas,
)  # noqa: E402
from tests.shared import getEmptyCol  # noqa: E402


def test_build_search_section():
    s = build_search(section="LR")
    assert "sr:section:LR" in s


def test_drill_search_includes_schemas():
    q = drill_search(["flaw.causal.correlation_causation", "qt.weaken"])
    assert "sr:schema:flaw.causal.correlation_causation" in q


def test_weakest_schemas_returns_list():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    schemas = weakest_schemas(col, count=3)
    assert len(schemas) <= 3
    col.close()


def test_plain_due_cards():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    cards = plain_due_cards(col, limit=5)
    assert cards
    col.close()


def test_interleaving_off_mode():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    cards = ordered_cards(col, limit=5, interleaving=False)
    assert cards
    col.close()


def test_health_check_passes():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    results = run_checks(col)
    assert all(ok for _, ok, _ in results)
    col.close()


def test_schema_drill_queue():
    col = getEmptyCol()
    import_seed_deck(col, backup=False)
    schemas, cards = schema_drill_queue(col, count=2, limit=10)
    assert schemas
    col.close()
