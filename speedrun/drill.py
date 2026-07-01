# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Schema drill mode: queue cards from the weakest schema."""
from __future__ import annotations

from typing import Any

from speedrun.scoring.performance import performance_score, weakness_map
from speedrun.scoring.queue import load_schema_weights, ordered_cards
from speedrun.scoring.readiness import readiness_score


def weakest_schema(col, **performance_kwargs: Any) -> str | None:
    """Return the schema with highest weight * weakness (points at stake)."""
    perf = performance_score(col, **performance_kwargs)
    weaknesses = weakness_map(perf["per_schema"])
    weights = load_schema_weights()
    best_schema = None
    best_score = -1.0
    for schema, weakness in weaknesses.items():
        val = weights.get(schema, 0.0) * weakness
        if val > best_score:
            best_score = val
            best_schema = schema
    if best_schema:
        return best_schema
    # No performance data yet — fall back to readiness best next step or highest-weight schema
    ready = readiness_score(col, **performance_kwargs)
    if ready.best_next_step:
        return ready.best_next_step
    if weights:
        return max(weights, key=weights.get)
    return None


def drill_cards(col, *, schema: str | None = None, limit: int = 20, **kwargs: Any) -> list[Any]:
    """Return queue-ordered cards filtered to a single schema."""
    target = schema or weakest_schema(col, **kwargs)
    if not target:
        return []
    cards = ordered_cards(col, limit=limit * 3, **kwargs)
    filtered = [c for c in cards if c.schema == target]
    return filtered[:limit]


def drill_report(col, *, schema: str | None = None, limit: int = 20, **kwargs: Any) -> str:
    target = schema or weakest_schema(col, **kwargs)
    if not target:
        return "No schema available for drill mode."
    cards = drill_cards(col, schema=target, limit=limit, **kwargs)
    lines = [
        f"Schema drill: {target}",
        f"Cards queued: {len(cards)}",
        "",
    ]
    for i, c in enumerate(cards, 1):
        lines.append(f"  {i}. priority={c.priority:.3f}  weakness={c.weakness:.2f}")
    if not cards:
        lines.append("  (no cards in deck for this schema — import seed deck)")
    return "\n".join(lines)
