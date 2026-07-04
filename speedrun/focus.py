# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Dedicated / focused study by subject.

A "subject" is an EXISTING stable dimension of the deck — a question-type
(``qt.*``) or any tested schema — NOT a new unit/lesson field. Focused study
lets a student drill only that subject while reusing the existing scheduler and
schema-weighted queue ordering *within* the filtered subset: we build the same
:func:`speedrun.scoring.queue.ordered_cards` queue but with a subject search
filter. No scheduling logic is forked.

Everything here is Qt-free and reads the collection at runtime only (it never
rewrites the deck): the subject catalog is derived from the notes' ``sr:schema:``
tags plus the performance model, and the filtered queue comes straight from the
queue builder. The aqt layer renders the payload and, on "Study this now",
launches the reviewer scoped to the subject (best-effort filtered deck) or falls
back to the filtered queue view.

Forward-compatible: a future ``unit``/``lesson`` field can be added as another
subject kind without changing this module's contract, but nothing here depends
on it today.
"""
from __future__ import annotations

import html
from dataclasses import asdict, dataclass
from typing import Any

from speedrun.scoring.queue import DEFAULT_DECK_SEARCH, build_search, ordered_cards

SCHEMA_TAG_PREFIX = "sr:schema:"
WEAKEST_TOKEN = "__weakest__"

# --------------------------------------------------------------------------- #
# "Study all (uncapped)" filtered-deck spec
# --------------------------------------------------------------------------- #

# Name of the native filtered ("cram") deck the "Study all" action builds. Kept
# distinct from the focused-study decks ("LSAT Focus: <subject>") so they never
# collide, and from the home deck ("LSAT Speedrun") so cards return home cleanly.
STUDY_ALL_DECK_NAME = "LSAT Study All"
# A high card limit so the filtered deck gathers the WHOLE deck in one sitting,
# ignoring the per-deck daily new-card cap.
STUDY_ALL_LIMIT = 9999
# Filtered-deck SearchTerm order. Anki's native filtered decks can't reproduce
# the schema-weighted priority order, so we use DUE (6) — due-date order — which
# is a sensible whole-deck grind order. (0=oldest-reviewed, 1=random, 6=due.)
STUDY_ALL_ORDER = 6


def study_all_spec() -> tuple[str, str, int, int]:
    """Return ``(deck_name, search, limit, order)`` for the uncapped "Study all"
    filtered deck.

    Pure/Qt-free so it is unit-testable and reused by the aqt launcher. The
    search matches the WHOLE Speedrun deck, so the filtered ("cram") deck pulls
    in every card regardless of the daily new-card cap; cards return to their
    home deck normally when studied (standard filtered-deck behavior)."""
    return STUDY_ALL_DECK_NAME, DEFAULT_DECK_SEARCH, STUDY_ALL_LIMIT, STUDY_ALL_ORDER


def _subject_kind(schema: str) -> str:
    return "question_type" if schema.startswith("qt.") else "schema"


# --------------------------------------------------------------------------- #
# Subject search (reuse the queue builder with a filter)
# --------------------------------------------------------------------------- #


def subject_search(
    schemas: list[str],
    *,
    base: str = DEFAULT_DECK_SEARCH,
    section: str | None = None,
) -> str:
    """Anki search string restricting the deck to the given subject schema(s).

    One schema -> a single tag clause; several -> an OR group (used by
    "study my weakest areas"). Section filtering is delegated to the queue's
    :func:`build_search` so LR/RC/LG scoping stays consistent."""
    clean = [s for s in schemas if s]
    if clean:
        clause = " OR ".join(f'tag:"{SCHEMA_TAG_PREFIX}{s}"' for s in clean)
        search = f"{base} ({clause})"
    else:
        search = base
    return build_search(search, section=section)


def focused_cards(
    col,
    schemas: list[str],
    *,
    limit: int = 25,
    section: str | None = None,
    **queue_kwargs: Any,
) -> list[Any]:
    """The schema-weighted queue filtered to a subject.

    Reuses :func:`ordered_cards` verbatim (same scheduler + priority ordering),
    only passing a subject-restricted ``search``. Ordering *within* the subject
    is preserved."""
    search = subject_search(schemas, section=section)
    return ordered_cards(col, limit=limit, search=search, **queue_kwargs)


# --------------------------------------------------------------------------- #
# Weakest-areas auto-selection
# --------------------------------------------------------------------------- #


def weakest_subjects(col, *, count: int | None = None) -> list[str]:
    """Auto-select the lowest-performing schemas (the one-click "weakest areas").

    Ranks by transfer weakness from the performance model; when there is no
    graded data yet it falls back to the highest exam-weight schemas so the
    button still does something sensible."""
    from speedrun.config import schema_drill_count
    from speedrun.scoring.performance import performance_score, weakness_map
    from speedrun.scoring.queue import load_schema_weights

    n = count or schema_drill_count()
    try:
        perf = performance_score(col)
        weak = weakness_map(perf["per_schema"])
    except Exception:
        weak = {}
    if weak:
        return sorted(weak, key=lambda s: (-weak[s], s))[:n]
    try:
        weights = load_schema_weights()
    except Exception:
        weights = {}
    return sorted(weights, key=lambda s: (-weights[s], s))[:n]


# --------------------------------------------------------------------------- #
# Subject catalog (the picker data)
# --------------------------------------------------------------------------- #


@dataclass
class Subject:
    schema: str
    kind: str  # "question_type" or "schema"
    label: str
    item_count: int  # cards/notes tagged with this schema in the deck
    n_attempts: int
    accuracy: float | None  # raw accuracy (ignoring the clock)
    transfer: float | None  # latency-adjusted transfer estimate
    weakness: float | None  # 1 - transfer, when scored
    status: str  # "weak" | "learning" | "solid" | "untested"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _deck_subject_counts(col) -> dict[str, int]:
    """schema id -> number of notes tagged with it. Reads notes only (no writes)."""
    from speedrun.scoring.performance import _schema_from_tags

    counts: dict[str, int] = {}
    try:
        rows = col.db.all("SELECT tags FROM notes")
    except Exception:
        return counts
    for (tags,) in rows:
        schema = _schema_from_tags(tags or "", SCHEMA_TAG_PREFIX)
        if schema:
            counts[schema] = counts.get(schema, 0) + 1
    return counts


def _status_for(transfer: float | None, n_attempts: int) -> str:
    if n_attempts == 0 or transfer is None:
        return "untested"
    if transfer >= 0.75:
        return "solid"
    if transfer >= 0.55:
        return "learning"
    return "weak"


def subject_catalog(col, *, min_items: int = 1) -> list[Subject]:
    """Every subject present in the deck, annotated with the student's accuracy /
    weakness / item counts, sorted weakest-first so weak areas are obvious.

    Question-types and schemas both appear (a question-type is just a ``qt.*``
    schema). Accuracy uses a low attempt floor so even lightly-practiced subjects
    show a number for the picker."""
    from speedrun.scoring.performance import performance_score

    counts = _deck_subject_counts(col)
    try:
        perf = performance_score(
            col, min_attempts_per_schema=1, min_attempts_overall=1
        )["per_schema"]
    except Exception:
        perf = {}

    schemas = set(counts) | set(perf)
    out: list[Subject] = []
    for schema in schemas:
        item_count = counts.get(schema, 0)
        if item_count < min_items and schema not in perf:
            continue
        score = perf.get(schema)
        if score is not None and not score.gave_up:
            transfer = score.point
            accuracy = score.raw_accuracy
            n_attempts = score.n_attempts
        else:
            transfer = None
            accuracy = None
            n_attempts = 0 if score is None else score.n_attempts
        weakness = None if transfer is None else max(0.0, 1.0 - transfer)
        from speedrun.taxonomy.labels import schema_label

        out.append(
            Subject(
                schema=schema,
                kind=_subject_kind(schema),
                label=schema_label(schema),
                item_count=item_count,
                n_attempts=n_attempts,
                accuracy=accuracy,
                transfer=transfer,
                weakness=weakness,
                status=_status_for(transfer, n_attempts),
            )
        )
    # Weakest first: scored subjects by descending weakness, then untested, then
    # by item count. Deterministic ties on schema id.
    out.sort(
        key=lambda s: (
            0 if s.weakness is not None else 1,
            -(s.weakness or 0.0),
            -s.item_count,
            s.schema,
        )
    )
    return out


def focus_payload(col, *, min_items: int = 1) -> dict[str, Any]:
    """JSON-serializable payload for the picker UI. Never raises."""
    try:
        subjects = [s.to_dict() for s in subject_catalog(col, min_items=min_items)]
    except Exception as exc:  # pragma: no cover - defensive
        return {"subjects": [], "reason": f"error: {type(exc).__name__}"}
    return {"subjects": subjects, "reason": ""}


# --------------------------------------------------------------------------- #
# Rendering (Qt-free HTML)
# --------------------------------------------------------------------------- #


def _esc(text: object) -> str:
    return html.escape(str(text))


def _acc(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"


def _weak_bar(weakness: float | None) -> str:
    if weakness is None:
        return '<div class="heat-bar" style="min-width:80px"><div class="heat-fill" style="width:0"></div></div>'
    pct = max(0, min(100, int(weakness * 100)))
    cls = "weak" if pct >= 60 else ("mid" if pct >= 30 else "strong")
    return (
        f'<div class="heat-bar" style="min-width:80px"><div class="heat-fill {cls}" '
        f'style="width:{pct}%"></div></div>'
    )


_FOCUS_CSS = """
.sr-focus-intro { font-size:0.9rem; color:var(--muted); margin-bottom:12px; }
.sr-focus-actions { margin-bottom:16px; display:flex; gap:10px; flex-wrap:wrap; }
.sr-focus-status { font-size:0.62rem; text-transform:uppercase; letter-spacing:0.05em; font-weight:700;
  padding:2px 8px; border-radius:999px; }
.sr-focus-status.weak { background:rgba(224,65,90,0.15); color:var(--low); }
.sr-focus-status.learning { background:rgba(224,140,31,0.15); color:var(--med); }
.sr-focus-status.solid { background:rgba(12,166,120,0.15); color:var(--high); }
.sr-focus-status.untested { background:rgba(154,161,181,0.2); color:var(--muted); }
.sr-focus-study { white-space:nowrap; padding:6px 12px; font-size:0.78rem; }
"""

_FOCUS_JS = r"""
(function () {
  document.querySelectorAll('.sr-focus-cmd[data-cmd]').forEach(function (b) {
    b.addEventListener('click', function () {
      if (typeof pycmd === 'function') pycmd(b.dataset.cmd);
    });
  });
})();
"""


def _subject_row(s: dict[str, Any]) -> str:
    from speedrun.taxonomy.labels import schema_display_html

    kind = "Question type" if s.get("kind") == "question_type" else "Schema"
    status = s.get("status", "untested")
    cmd = f"speedrun:focus:{s['schema']}"
    return (
        "<tr>"
        f"<td>{schema_display_html(s['schema'], compact=True)}</td>"
        f"<td>{_esc(kind)}</td>"
        f'<td><span class="sr-focus-status {_esc(status)}">{_esc(status)}</span></td>'
        f"<td class='num'>{_acc(s.get('accuracy'))}</td>"
        f"<td>{_weak_bar(s.get('weakness'))}</td>"
        f"<td class='num'>{int(s.get('item_count') or 0)}</td>"
        f"<td class='num'>{int(s.get('n_attempts') or 0)}</td>"
        f'<td><button type="button" class="sr-btn primary sr-focus-study sr-focus-cmd" '
        f'data-cmd="{_esc(cmd)}">Study</button></td>'
        "</tr>"
    )


def _focus_body(payload: dict[str, Any], *, embed: bool) -> str:
    subjects = payload.get("subjects", [])
    weakest_btn = (
        '<button type="button" class="sr-btn primary sr-focus-cmd" '
        'data-cmd="speedrun:focus:__weakest__">Study my weakest areas</button>'
    )
    if not subjects:
        table = '<div class="sr-empty">No subjects found. Import the seed deck first.</div>'
    else:
        rows = "".join(_subject_row(s) for s in subjects)
        table = (
            '<div class="sr-table-wrap"><table class="sr-table"><thead><tr>'
            "<th>subject</th><th>kind</th><th>status</th><th class='num'>accuracy</th>"
            "<th>weakness</th><th class='num'>items</th><th class='num'>attempts</th>"
            "<th></th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
        )
    intro = (
        "Drill a single subject — a question-type or a schema — using the same "
        "schema-weighted queue ordering, restricted to just that subject. Weak "
        "areas are listed first. Or let us pick your weakest areas automatically."
    )
    return (
        f"<style>{_FOCUS_CSS}</style>"
        '<div class="sr-header"><h1>Focus / study by subject</h1>'
        f'<p class="sr-focus-intro">{intro}</p></div>'
        f'<div class="sr-focus-actions">{weakest_btn}</div>'
        f"{table}"
        f"<script>{_FOCUS_JS}</script>"
    )


def render_focus_html(col, *, embed: bool = False) -> str:
    """The subject picker page (``embed`` for the pycmd bridge dialog)."""
    from speedrun.dashboard import _DASHBOARD_CSS, _shell

    payload = focus_payload(col)
    inner = _focus_body(payload, embed=embed)
    if embed:
        return f'<style>{_DASHBOARD_CSS}</style><div class="sr-dash">{inner}</div>'
    return _shell(inner, title="Focus / study by subject")


def render_focus_queue_html(
    col, schemas: list[str], *, title: str, limit: int = 25
) -> str:
    """A read-only view of the filtered, schema-weighted queue for a subject.

    Used as the in-app fallback when a native filtered-deck study session cannot
    be launched, and as a preview of exactly which cards focused study will use."""
    from speedrun.dashboard import _queue_html, _shell
    from speedrun.taxonomy.labels import schema_display_html

    try:
        cards = focused_cards(col, schemas, limit=limit)
    except Exception as exc:  # pragma: no cover - defensive
        cards = None
        err = str(exc)
    labels = ", ".join(schema_display_html(s, compact=True) for s in schemas) or "—"
    if cards is None:
        body = f'<div class="sr-empty">Could not build the focused queue: {_esc(err)}</div>'
    elif not cards:
        body = '<div class="sr-empty">No cards for this subject yet.</div>'
    else:
        # Reuse the dashboard's queue renderer by re-running it with the subject
        # search so ordering/labels match the rest of the app.
        search = subject_search(schemas)
        body = _queue_html(col, limit=limit, search=search)
    return _shell(
        f'<div class="sr-header"><h1>Focused study</h1>'
        f"<p>Subject: {labels}</p></div>"
        f'<div class="sr-section">{body}</div>',
        title=title,
    )
