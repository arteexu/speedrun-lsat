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

from speedrun.config import interleaving_enabled
from speedrun.config import section_filter
from speedrun.scoring.performance import performance_score
from speedrun.scoring.performance import weakness_map

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TAXONOMY = REPO_ROOT / "speedrun" / "taxonomy" / "lsat_taxonomy.json"
SCHEMA_TAG_PREFIX = "sr:schema:"
SECTION_TAG_PREFIX = "sr:section:"
DEFAULT_DECK_SEARCH = 'deck:"LSAT Speedrun"'


def build_search(
    base: str = DEFAULT_DECK_SEARCH,
    *,
    section: str | None = None,
) -> str:
    """Append section filter (LR/RC/LG) via sr:section: tags."""
    if section:
        return f'{base} tag:"{SECTION_TAG_PREFIX}{section}"'
    return base


def load_schema_weights(path: Path = DEFAULT_TAXONOMY) -> dict[str, float]:
    """Map schema id -> exam_weight from the taxonomy."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {s["id"]: float(s.get("exam_weight", 0.0)) for s in data["schemas"]}


def weakness_from_collection(col, **performance_kwargs: Any) -> dict[str, float]:
    """Per-schema weakness (1 - transfer) from the performance model."""
    perf = performance_score(col, **performance_kwargs)
    return weakness_map(perf["per_schema"])


def speed_pressured_schemas(per_schema: dict[str, Any]) -> list[str]:
    """Schemas the student is accurate-but-slow on (SPOV4): they'd lose points on
    the clock, so the queue up-weights them for speed drilling. This is what
    populates the Rust queue's ``time_pressured_schemas`` parameter."""
    return sorted(s for s, score in per_schema.items() if getattr(score, "speed_flag", False))


def plain_due_cards(col, *, limit: int = 20, search: str = DEFAULT_DECK_SEARCH) -> list[Any]:
    """Anki's default due order (no schema weighting) for interleaving-off mode."""
    cids = col.find_cards(f"{search} is:due")
    if not cids:
        cids = col.find_cards(search)[:limit]
    out = []
    for cid in cids[:limit]:
        card = col.get_card(cid)
        note = card.note()
        schema = None
        for tag in note.tags:
            if tag.startswith(SCHEMA_TAG_PREFIX):
                schema = tag[len(SCHEMA_TAG_PREFIX) :]
                break
        out.append(
            type(
                "PlainCard",
                (),
                {
                    "card_id": cid,
                    "schema": schema or "",
                    "priority": 0.0,
                    "schema_weight": 0.0,
                    "weakness": 0.0,
                },
            )()
        )
    return out


def ordered_cards(
    col,
    *,
    limit: int = 20,
    search: str | None = None,
    section: str | None = None,
    interleaving: bool | None = None,
    weaknesses: dict[str, float] | None = None,
    time_pressured: list[str] | None = None,
    time_pressure_factor: float | None = None,
    use_performance_weakness: bool = True,
    **performance_kwargs: Any,
) -> list[Any]:
    """Return cards ordered by schema points-at-stake (list of ScoredCard).

    When interleaving is off, returns plain Anki due order instead.

    ``time_pressured``/``time_pressure_factor`` default to *auto*: the
    accurate-but-slow schemas (SPOV4) are pulled from the performance model and
    up-weighted by the configured speed-pressure factor, activating the Rust
    queue's time-pressure path. Pass explicit values to override."""
    sec = section if section is not None else section_filter()
    effective_search = build_search(search or DEFAULT_DECK_SEARCH, section=sec)
    use_interleave = interleaving_enabled() if interleaving is None else interleaving
    if not use_interleave:
        return plain_due_cards(col, limit=limit, search=effective_search)

    weights = load_schema_weights()

    # Compute the performance model once if we need weakness and/or the
    # accurate-but-slow set from it.
    perf = None
    if (weaknesses is None and use_performance_weakness) or time_pressured is None:
        perf = performance_score(col, **performance_kwargs)
    if weaknesses is None and use_performance_weakness:
        weaknesses = weakness_map(perf["per_schema"])
    if time_pressured is None:
        time_pressured = speed_pressured_schemas(perf["per_schema"]) if perf else []
    if time_pressure_factor is None:
        from speedrun.config import speed_pressure_factor as _spf

        time_pressure_factor = _spf() if time_pressured else 1.0

    return list(
        col._backend.build_schema_weighted_queue(
            search=effective_search,
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
