# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Human-readable labels for taxonomy schema ids and Anki tag strings."""

from __future__ import annotations

import html
import json
from functools import lru_cache
from pathlib import Path

TAXONOMY_PATH = Path(__file__).resolve().parent / "lsat_taxonomy.json"

TAG_PREFIXES = ("sr:schema:", "sr:qtype:", "sr:trap:", "sr:section:")

AXIS_LABELS = {
    "flaw": "Flaw",
    "qt": "QT",
    "rc": "RC",
    "trap": "Trap",
    "lg": "LG",
}


def normalize_schema_id(schema_id: str) -> str:
    """Strip Speedrun tag prefixes so ``sr:trap:trap.half_right`` → ``trap.half_right``."""
    text = schema_id.strip()
    for prefix in TAG_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


def _title_case_segment(segment: str) -> str:
    return segment.replace("_", " ").title()


def _axis_label(schema_id: str) -> str:
    axis = schema_id.split(".", 1)[0]
    return AXIS_LABELS.get(axis, axis.upper())


@lru_cache(maxsize=1)
def _taxonomy_names() -> dict[str, str]:
    data = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    return {s["id"]: s.get("name", s["id"]) for s in data["schemas"]}


def schema_label(schema_id: str) -> str:
    """Full label, e.g. ``rc.main_point`` → ``RC · Main point / primary purpose``."""
    raw = normalize_schema_id(schema_id)
    if not raw:
        return "(none)"
    prefix = _axis_label(raw)
    name = _taxonomy_names().get(raw)
    if name:
        return f"{prefix} · {name}"
    parts = raw.split(".")
    tail = (
        _title_case_segment(parts[-1]) if len(parts) > 1 else _title_case_segment(raw)
    )
    return f"{prefix} · {tail}"


def category_label(schema_id: str) -> str:
    """Human label for a taxonomy family, e.g. ``flaw.causal`` -> ``Causal``.

    Accepts a full schema id (uses its second segment) or a bare category token."""
    raw = normalize_schema_id(schema_id)
    parts = raw.split(".")
    category = parts[1] if len(parts) >= 2 else parts[0]
    return _title_case_segment(category)


def schema_short_label(schema_id: str) -> str:
    """Compact label for heatmaps and queue chips, e.g. ``RC · Main Point``."""
    raw = normalize_schema_id(schema_id)
    if not raw:
        return "(none)"
    prefix = _axis_label(raw)
    parts = raw.split(".")
    tail = (
        _title_case_segment(parts[-1]) if len(parts) > 1 else _title_case_segment(raw)
    )
    return f"{prefix} · {tail}"


def schema_tooltip(schema_id: str) -> str:
    """Hover text: full label plus raw id for power users."""
    raw = normalize_schema_id(schema_id)
    if not raw:
        return "(none)"
    return f"{schema_label(schema_id)} ({raw})"


def schema_display_html(
    schema_id: str, *, compact: bool = False, show_id: bool | None = None
) -> str:
    """Render friendly label; raw id in tooltip by default, subtitle when show_id is true."""
    raw = normalize_schema_id(schema_id)
    label = schema_short_label(schema_id) if compact else schema_label(schema_id)
    title = html.escape(schema_tooltip(schema_id))
    esc_label = html.escape(label)
    if not raw:
        return f'<span class="sr-schema-cell">{esc_label}</span>'
    if show_id is None:
        from speedrun.config import show_schema_ids

        show_id = show_schema_ids()
    if compact or not show_id:
        return f'<span class="sr-schema-cell sr-schema-compact" title="{title}">{esc_label}</span>'
    esc_raw = html.escape(raw)
    return (
        f'<span class="sr-schema-cell" title="{title}">'
        f'<span class="sr-schema-label">{esc_label}</span>'
        f'<span class="sr-schema-id">{esc_raw}</span>'
        f"</span>"
    )
