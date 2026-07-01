# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Client helper for the schema-weighted queue Rust RPC.

Loads schema weights from the taxonomy (the single source of truth) and calls
`build_schema_weighted_queue` on the backend. Student weakness comes from the
performance model once it exists; until then callers pass weaknesses explicitly
or rely on the default (unknown schema == maximally weak), so ordering is driven
by exam weight.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TAXONOMY = REPO_ROOT / "speedrun" / "taxonomy" / "lsat_taxonomy.json"
SCHEMA_TAG_PREFIX = "sr:schema:"
DEFAULT_DECK_SEARCH = 'deck:"LSAT Speedrun"'


def load_schema_weights(path: Path = DEFAULT_TAXONOMY) -> dict[str, float]:
    """Map schema id -> exam_weight from the taxonomy."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {s["id"]: float(s.get("exam_weight", 0.0)) for s in data["schemas"]}


def ordered_cards(
    col,
    *,
    limit: int = 20,
    search: str = DEFAULT_DECK_SEARCH,
    weaknesses: dict[str, float] | None = None,
    time_pressured: list[str] | None = None,
    time_pressure_factor: float = 1.0,
) -> list[Any]:
    """Return cards ordered by schema points-at-stake (list of ScoredCard)."""
    weights = load_schema_weights()
    return list(
        col._backend.build_schema_weighted_queue(
            search=search,
            limit=limit,
            schema_tag_prefix=SCHEMA_TAG_PREFIX,
            schema_weight=weights,
            schema_weakness=weaknesses or {},
            time_pressured_schemas=time_pressured or [],
            time_pressure_factor=time_pressure_factor,
            default_weight=0.0,
            default_weakness=1.0,
        )
    )
