# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Per-collection, state-keyed memoization for the dashboard's expensive scores.

Rendering the three-score dashboard on the shared 50k-card deck used to rescan
the whole collection several times per render (memory over every card, the
schema-weighted queue over every card, the performance model 4-5 times, the
recommender once per schema). This module lets those consumers share a single
computation and lets a *refresh* with an unchanged collection reuse the result.

Design (honesty-preserving):

* The cache key is a cheap **collection-state token** — the max revlog id, the
  revlog/card/note counts, and the collection mod time. Every review appends a
  revlog row (so the max id and count change) and bumps the collection mod time;
  adding/removing cards or notes changes the counts. So the token changes exactly
  when the numbers a score depends on could change, and stays constant only when
  the state is genuinely unchanged. When it changes, everything recomputes.
  The result for a given state is therefore *identical* to computing from
  scratch — this is memoization, not approximation.
* The cache is keyed by the ``Collection`` object itself (a ``WeakKeyDictionary``
  so it never keeps a closed collection alive and never leaks). Two different
  collections never share an entry, so there is no cross-collection pollution.

If a collection cannot be weak-referenced (unusual), we degrade gracefully to
computing without caching rather than failing.
"""
from __future__ import annotations

from typing import Any
from typing import Callable
from typing import TypeVar
from weakref import WeakKeyDictionary

T = TypeVar("T")

# Collection object -> {"__token__": token, key: value, ...}
_CACHE: "WeakKeyDictionary[Any, dict[str, Any]]" = WeakKeyDictionary()


def collection_state_token(col) -> tuple:
    """A cheap token that changes iff the collection's scored state could change.

    All five queries are O(1)/index lookups in SQLite (``COUNT(*)`` and the
    revlog primary-key ``MAX(id)``), so computing the token costs well under a
    millisecond even on the 50k-card deck."""
    db = col.db
    return (
        int(db.scalar("SELECT COALESCE(MAX(id), 0) FROM revlog") or 0),
        int(db.scalar("SELECT COUNT(*) FROM revlog") or 0),
        int(db.scalar("SELECT COUNT(*) FROM cards") or 0),
        int(db.scalar("SELECT COUNT(*) FROM notes") or 0),
        int(getattr(col, "mod", 0) or 0),
    )


def _entry(col) -> dict[str, Any] | None:
    """Return the live cache dict for ``col`` at its current state, or ``None``
    if the collection can't be cached (caller then computes uncached).

    Anything unexpected — a collection stand-in without a real ``db``/``mod``, an
    object that can't be weak-referenced — degrades to no caching rather than
    failing, so callers behave exactly as they did before this module existed."""
    try:
        token = collection_state_token(col)
        entry = _CACHE.get(col)
        if entry is None or entry.get("__token__") != token:
            entry = {"__token__": token}
            _CACHE[col] = entry
        return entry
    except Exception:
        return None


def cached(col, key: str, compute: Callable[[], T]) -> T:
    """Return ``compute()`` for ``col``, memoized by collection-state token.

    On a cache miss (new collection or changed state) ``compute`` runs and its
    result is stored; on a hit the stored result is returned unchanged."""
    entry = _entry(col)
    if entry is None:
        return compute()
    if key not in entry:
        entry[key] = compute()
    return entry[key]


def invalidate(col=None) -> None:
    """Drop cached results for ``col`` (or everything when ``col`` is ``None``).

    Rarely needed — the state token already invalidates on any scored change —
    but handy for tests and for forcing a recompute."""
    if col is None:
        _CACHE.clear()
    else:
        _CACHE.pop(col, None)
