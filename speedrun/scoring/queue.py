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
from functools import lru_cache
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

# §9.2: the schema-weighted queue must rank *due* cards, not every card in the
# deck. FSRS due-state is reused via Anki's ``is:due`` (review/learning cards due
# now); new cards are kept via ``is:new`` because they are the primary study pool
# and a freshly imported deck (all-new) must still produce a queue. Restricting
# to this studyable set is what stops the RPC from ranking far-future reviews.
DUE_STATE_FILTER = "(is:due OR is:new)"


def build_search(
    base: str = DEFAULT_DECK_SEARCH,
    *,
    section: str | None = None,
) -> str:
    """Append section filter (LR/RC/LG) via sr:section: tags."""
    if section:
        return f'{base} tag:"{SECTION_TAG_PREFIX}{section}"'
    return base


def restrict_to_due(search: str) -> str:
    """Restrict a deck search to cards that are studyable *right now* (§9.2).

    Reuses FSRS due-state (``is:due``) plus new cards (``is:new``) so the queue
    ranks the studyable pool rather than every card in the deck. Kept as a small
    pure helper so the review session and the queue builder compose the exact
    same restriction."""
    return f"({search}) {DUE_STATE_FILTER}"


@lru_cache(maxsize=8)
def _load_schema_weights_cached(path: Path) -> dict[str, float]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {s["id"]: float(s.get("exam_weight", 0.0)) for s in data["schemas"]}


def load_schema_weights(path: Path = DEFAULT_TAXONOMY) -> dict[str, float]:
    """Map schema id -> exam_weight from the taxonomy.

    Returns a fresh dict each call (over a path-cached parse) so callers may
    mutate their copy without disturbing the cache."""
    return dict(_load_schema_weights_cached(path))


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
    due_only: bool = True,
    **performance_kwargs: Any,
) -> list[Any]:
    """Return cards ordered by schema points-at-stake (list of ScoredCard).

    When interleaving is off, returns plain Anki due order instead.

    ``due_only`` (default True, §9.2): restrict ranking to studyable cards
    (``is:due`` reuse of FSRS due-state, plus new cards) rather than every card
    in the deck, so the RPC never ranks far-future reviews. Pass ``due_only=False``
    to rank the whole deck (used by whole-deck previews).

    ``time_pressured``/``time_pressure_factor`` default to *auto*: the
    accurate-but-slow schemas (SPOV4) are pulled from the performance model and
    up-weighted by the configured speed-pressure factor, activating the Rust
    queue's time-pressure path. Pass explicit values to override."""
    sec = section if section is not None else section_filter()
    effective_search = build_search(search or DEFAULT_DECK_SEARCH, section=sec)
    use_interleave = interleaving_enabled() if interleaving is None else interleaving
    if not use_interleave:
        return plain_due_cards(col, limit=limit, search=effective_search)

    rpc_search = restrict_to_due(effective_search) if due_only else effective_search

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
            search=rpc_search,
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


def ordered_card_ids(col, *, limit: int = 50, **queue_kwargs: Any) -> list[int]:
    """Just the card ids in schema-weighted priority order (highest first).

    The ordering authority is the Rust ``build_schema_weighted_queue`` RPC via
    :func:`ordered_cards`; this is a thin projection used to drive a review
    session that grades cards in exactly that order."""
    return [int(c.card_id) for c in ordered_cards(col, limit=limit, **queue_kwargs)]


class SchemaWeightedReview:
    """A Speedrun-native review session that grades due cards in schema-weighted
    priority order through the shared Rust scheduler.

    Why this exists (§9/§11, the blocker): native Anki filtered decks cannot
    reproduce an *arbitrary* priority order (see the comment in ``focus.py``), so
    the live review path used to fall back to native scheduler order and never
    actually applied the schema-weighted queue. This session mirrors the iOS
    ``ReviewView``: it snapshots the schema-weighted order once
    (:func:`ordered_card_ids`) and then walks it, grading each card with the same
    ``col.sched.answerCard`` the native reviewer uses. That call is the shared
    engine, so:

      * (a) the graded order matches schema-weighted priority — we grade the
        snapshot in order;
      * (b) latency is recorded per attempt — the card timer feeds
        ``milliseconds_taken`` in the revlog (``answer`` can inject a measured
        latency);
      * (c) undo still works — every ``answerCard`` is a normal undoable engine
        op, so :meth:`undo` (or ``col.undo()``) reverts it;
      * (d) no lost/double-counted reviews — the snapshot holds distinct card
        ids and each is graded exactly once, writing exactly one revlog row.

    Pure/Qt-free so it is unit-testable without aqt; the Qt layer only renders
    the current card and relays button presses into :meth:`answer`.
    """

    def __init__(self, col, *, limit: int = 50, **queue_kwargs: Any) -> None:
        self.col = col
        scored = ordered_cards(col, limit=limit, **queue_kwargs)
        self._order: list[int] = [int(c.card_id) for c in scored]
        # Snapshot the schema/priority the queue assigned so the UI (and tests)
        # can show/verify the order without re-querying.
        self._schema: dict[int, str] = {
            int(c.card_id): getattr(c, "schema", "") or "" for c in scored
        }
        self._priority: dict[int, float] = {
            int(c.card_id): float(getattr(c, "priority", 0.0)) for c in scored
        }
        self._pos = 0
        self.graded: list[dict[str, Any]] = []

    # -- introspection ----------------------------------------------------- #
    @property
    def total(self) -> int:
        return len(self._order)

    @property
    def position(self) -> int:
        return self._pos

    @property
    def remaining(self) -> int:
        return max(0, len(self._order) - self._pos)

    def card_ids(self) -> list[int]:
        """The queued card ids, in schema-weighted priority order."""
        return list(self._order)

    def schema_order(self) -> list[str]:
        """The schema of each queued card, in priority order (for the UI/tests)."""
        return [self._schema.get(cid, "") for cid in self._order]

    def priority_order(self) -> list[float]:
        """The points-at-stake priority of each queued card, in order."""
        return [self._priority.get(cid, 0.0) for cid in self._order]

    def answer_card_id(self, card_id: int, ease: int, *, latency_ms: int | None = None):
        """Grade by card id (loads the card first). Convenience for a UI that
        holds a snapshot of the order and reports the card it graded."""
        card = self.col.get_card(int(card_id))
        return self.answer(card, ease, latency_ms=latency_ms)

    def current_card_id(self) -> int | None:
        if self._pos >= len(self._order):
            return None
        return self._order[self._pos]

    def current_card(self):
        """Load the current card and start its answer timer, or None if done."""
        cid = self.current_card_id()
        if cid is None:
            return None
        card = self.col.get_card(cid)
        card.start_timer()
        return card

    # -- grading ----------------------------------------------------------- #
    def answer(self, card, ease: int, *, latency_ms: int | None = None):
        """Grade ``card`` with ``ease`` (1..4) through the shared engine.

        ``latency_ms`` (optional): the measured time-on-card. It is injected via
        the card timer so the engine records it as ``milliseconds_taken`` in the
        revlog (SPOV4 — latency is first-class). When omitted, whatever the card
        timer already holds is used."""
        import time

        if latency_ms is not None:
            card.timer_started = time.time() - max(0, int(latency_ms)) / 1000.0
        elif getattr(card, "timer_started", None) is None:
            card.start_timer()
        cid = int(card.id)
        recorded = card.time_taken(capped=False)
        self.col.sched.answerCard(card, ease)
        # Advance past this card in the snapshot (match by id so an out-of-order
        # answer still advances correctly).
        try:
            self._pos = self._order.index(cid, self._pos) + 1
        except ValueError:
            self._pos += 1
        self.graded.append(
            {
                "card_id": cid,
                "schema": self._schema.get(cid, ""),
                "ease": int(ease),
                "latency_ms": int(recorded),
            }
        )
        return card

    def undo(self) -> bool:
        """Undo the most recent grade via the shared engine (§9.3).

        Returns True if an answer was reverted. Steps the session cursor back so
        the reverted card is presented again, and drops it from ``graded``."""
        if not self.graded:
            return False
        try:
            status = self.col.undo_status()
            if not status.undo:
                return False
            self.col.undo()
        except Exception:
            return False
        self._pos = max(0, self._pos - 1)
        self.graded.pop()
        return True


def dashboard_ordered_cards(col, *, limit: int = 8, **performance_kwargs: Any) -> list[Any]:
    """Same top-``limit`` result as :func:`ordered_cards`, but far cheaper.

    The dashboard only previews the top of the queue, yet the Rust RPC fetches
    *every* candidate card to rank them (~700ms on 50k). Because every card of a
    schema shares one priority (``weight × weakness × time_pressure``), the global
    top-``limit`` cards can only come from the highest-priority schema(s). So we
    pre-select the smallest set of top-priority schemas that can contain the
    top-``limit`` (plus every schema tied at the boundary priority) and let the
    RPC rank *that* set — an identical result over a fraction of the cards.

    Correctness guards: we fall back to the full :func:`ordered_cards` when
    interleaving is off, a section filter is active, priorities are degenerate
    (all tied at the boundary or zero), or the pruned search returns fewer than
    ``limit`` cards (which means the schema totals over-counted the search space).
    """
    # Only sound for the default schema-weighted, unfiltered dashboard preview.
    if not interleaving_enabled() or section_filter():
        return ordered_cards(col, limit=limit, **performance_kwargs)

    perf = performance_score(col, **performance_kwargs)
    per_schema = perf["per_schema"]
    weights = load_schema_weights()
    weaknesses = weakness_map(per_schema)
    pressured = speed_pressured_schemas(per_schema)
    pressured_set = set(pressured)
    if pressured:
        from speedrun.config import speed_pressure_factor as _spf

        factor = _spf()
    else:
        factor = 1.0

    from speedrun.scoring.memory import schema_card_totals

    totals = schema_card_totals(col)
    if not totals:
        return ordered_cards(col, limit=limit, **performance_kwargs)

    def priority(schema: str) -> float:
        weight = weights.get(schema, 0.0)
        weakness = weaknesses.get(schema, 1.0)
        return weight * weakness * (factor if schema in pressured_set else 1.0)

    order = sorted(totals, key=lambda s: (-priority(s), s))
    cumulative = 0
    boundary: float | None = None
    for schema in order:
        cumulative += totals[schema]
        if cumulative >= limit:
            boundary = priority(schema)
            break
    # Degenerate priorities (everything zero / all tied at the boundary) give no
    # pruning benefit; the full path is just as correct and no slower.
    if boundary is None or boundary <= 0.0:
        return ordered_cards(col, limit=limit, **performance_kwargs)

    chosen = [s for s in order if priority(s) >= boundary]

    # Within a schema every card shares one priority, so the RPC breaks ties by
    # ascending card id: only a schema's lowest-id cards can reach the top. Pull
    # each chosen schema's lowest `limit` card ids (an id-only search, no card
    # loads) and hand the RPC just that union via an explicit `cid:` search, so
    # it ranks a few dozen cards instead of loading every card of a big schema.
    candidate_ids: list[int] = []
    for schema in chosen:
        try:
            ids = list(
                col.find_cards(f'{DEFAULT_DECK_SEARCH} tag:"{SCHEMA_TAG_PREFIX}{schema}"')
            )
        except Exception:
            ids = []
        candidate_ids.extend(sorted(ids)[:limit])
    if not candidate_ids:
        return ordered_cards(col, limit=limit, **performance_kwargs)

    reduced_search = "cid:" + ",".join(str(cid) for cid in candidate_ids)
    result = ordered_cards(
        col,
        limit=limit,
        search=reduced_search,
        weaknesses=weaknesses,
        time_pressured=pressured,
        time_pressure_factor=factor,
    )
    # If the pruned set couldn't fill the limit, our totals over-counted the
    # searchable cards; recompute over the full deck to stay exact.
    if len(result) < limit:
        full = ordered_cards(col, limit=limit, **performance_kwargs)
        if len(full) > len(result):
            return full
    return result
