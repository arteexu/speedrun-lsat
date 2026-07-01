# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Correlate the mistakes a student makes so they can see their *mistake graph*.

The concept map (``concept_graph.py``) shows what you've practiced and how strong
you are. This is its shadow: a graph built only from the cards you got WRONG, whose
edges answer a different question -- "which mistakes tend to happen together?"

BrainLift SPOV2 says flaws and traps are the unit of mastery, and Insight 8 says
*which* wrong pattern a student keeps choosing is the transferable signal. A single
miss-rate table hides structure; correlation reveals it. If every time you're off
on causal reasoning you also miss sampling flaws, those two belong to one weakness
cluster and should be remediated together.

Algorithm (kept Qt-free and pure-data so it is unit-testable):

* A **mistake node** is every schema (flaw / trap / question-type / RC-structure)
  that appears on at least one *missed* review (Anki ``ease == 1``). Node size is
  the number of misses; colour is the student's miss-rate on that schema
  (chronic / shaky / occasional).
* Misses are bucketed by study day. Two schemas are **correlated** when they are
  missed in the same buckets more than chance predicts; strength is the phi
  coefficient (Pearson correlation for the two binary "missed in this bucket?"
  variables). We keep only positive correlations that co-occur in at least
  ``MIN_CO_OCCUR`` buckets so a single coincidence does not draw an edge.
* When the student has practiced on fewer than two distinct days there is not
  enough temporal spread to correlate across days, so each missed review becomes
  its own bucket -- correlation then reduces to "missed on the same card / sitting".
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from itertools import combinations
from math import sqrt
from pathlib import Path
from typing import Any

from speedrun.concept_graph import (
    DEFAULT_TAXONOMY,
    _axis_of,
    _group_of,
    _load_taxonomy_meta,
    _schema_ids_from_tags,
)
from speedrun.taxonomy.labels import schema_label, schema_short_label

# Miss-rate cutoffs (0..1) for colouring a mistake node.
CHRONIC_AT = 0.50  # you miss this at least half the time you see it
SHAKY_AT = 0.25

# Only correlate two mistakes once they co-occur in at least this many buckets,
# and only draw positively-correlated edges above this phi strength.
MIN_CO_OCCUR = 2
MIN_CORR = 0.0


@dataclass
class MistakeNode:
    id: str
    label: str
    short_label: str
    axis: str
    group: str
    group_label: str
    status: str  # chronic | shaky | occasional
    misses: int
    attempts: int
    miss_rate: float
    exam_weight: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MistakeEdge:
    source: str
    target: str
    weight: float  # phi correlation, 0..1 (positive only)
    co_miss: int  # buckets where both were missed
    kind: str  # corr

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MistakeGraph:
    nodes: list[MistakeNode] = field(default_factory=list)
    edges: list[MistakeEdge] = field(default_factory=list)
    groups: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "groups": self.groups,
            "stats": self.stats,
        }


def _status_from_miss_rate(miss_rate: float) -> str:
    if miss_rate >= CHRONIC_AT:
        return "chronic"
    if miss_rate >= SHAKY_AT:
        return "shaky"
    return "occasional"


def _phi(n11: int, n10: int, n01: int, n00: int) -> float:
    """Phi coefficient (Pearson correlation of two binary variables)."""
    row1 = n11 + n10
    row0 = n01 + n00
    col1 = n11 + n01
    col0 = n10 + n00
    denom = sqrt(row1 * row0 * col1 * col0)
    if denom == 0:
        return 0.0
    return (n11 * n00 - n10 * n01) / denom


def build_mistake_graph(col, *, taxonomy_path: Path = DEFAULT_TAXONOMY) -> MistakeGraph:
    """Assemble the mistake-correlation graph from the collection's revlog."""
    meta = _load_taxonomy_meta(taxonomy_path)

    rows = col.db.all(
        """
        SELECT r.cid, r.ease, r.id, n.tags
        FROM revlog r
        JOIN cards c ON r.cid = c.id
        JOIN notes n ON c.nid = n.id
        WHERE r.ease > 0
        """
    )

    attempts_by_schema: dict[str, int] = {}
    misses_by_schema: dict[str, int] = {}
    # Each missed review as (day, schema-id set) so we can bucket flexibly.
    miss_events: list[tuple[str, set[str]]] = []

    for _cid, ease, rid, tags in rows:
        ids = _schema_ids_from_tags(tags)
        if not ids:
            continue
        for sid in ids:
            attempts_by_schema[sid] = attempts_by_schema.get(sid, 0) + 1
        if int(ease) == 1:
            for sid in ids:
                misses_by_schema[sid] = misses_by_schema.get(sid, 0) + 1
            day = time.strftime("%Y-%m-%d", time.localtime(int(rid) / 1000))
            miss_events.append((day, ids))

    nodes: list[MistakeNode] = []
    for sid in sorted(misses_by_schema):
        attempts = attempts_by_schema.get(sid, 0)
        misses = misses_by_schema[sid]
        miss_rate = (misses / attempts) if attempts else 1.0
        group, group_label = _group_of(sid, meta)
        nodes.append(
            MistakeNode(
                id=sid,
                label=schema_label(sid),
                short_label=schema_short_label(sid),
                axis=_axis_of(sid),
                group=group,
                group_label=group_label,
                status=_status_from_miss_rate(miss_rate),
                misses=misses,
                attempts=attempts,
                miss_rate=round(miss_rate, 4),
                exam_weight=(meta.get(sid) or {}).get("exam_weight", 0.0),
            )
        )

    present = {n.id for n in nodes}
    buckets = _miss_buckets(miss_events, present)
    edges = _build_edges(buckets, present)

    groups = _summarize_groups(nodes)
    stats = {
        "n_nodes": len(nodes),
        "n_edges": len(edges),
        "n_groups": len(groups),
        "n_buckets": len(buckets),
        "bucket_mode": _bucket_mode(miss_events),
        "chronic": sum(1 for n in nodes if n.status == "chronic"),
        "shaky": sum(1 for n in nodes if n.status == "shaky"),
        "occasional": sum(1 for n in nodes if n.status == "occasional"),
        "total_misses": sum(n.misses for n in nodes),
    }
    return MistakeGraph(nodes=nodes, edges=edges, groups=groups, stats=stats)


def _bucket_mode(miss_events: list[tuple[str, set[str]]]) -> str:
    return "day" if len({d for d, _ in miss_events}) >= 2 else "event"


def _miss_buckets(
    miss_events: list[tuple[str, set[str]]], present: set[str]
) -> list[set[str]]:
    """Group missed schemas into correlation buckets.

    Prefer study-day buckets (temporal co-occurrence across sittings). When the
    student has practiced on fewer than two days there is no temporal spread, so
    each missed review becomes its own bucket (co-occurrence on the same sitting)."""
    if _bucket_mode(miss_events) == "day":
        by_day: dict[str, set[str]] = {}
        for day, ids in miss_events:
            by_day.setdefault(day, set()).update(ids & present)
        return [s for s in by_day.values() if s]
    return [ids & present for _day, ids in miss_events if (ids & present)]


def _build_edges(buckets: list[set[str]], present: set[str]) -> list[MistakeEdge]:
    total = len(buckets)
    if total < 2:
        return []
    # Per-schema bucket membership as bit-sets of bucket indices.
    membership: dict[str, set[int]] = {sid: set() for sid in present}
    for i, b in enumerate(buckets):
        for sid in b:
            membership[sid].add(i)

    edges: list[MistakeEdge] = []
    for a, b in combinations(sorted(present), 2):
        ma, mb = membership[a], membership[b]
        if not ma or not mb:
            continue
        n11 = len(ma & mb)
        if n11 < MIN_CO_OCCUR:
            continue
        n10 = len(ma - mb)
        n01 = len(mb - ma)
        n00 = total - n11 - n10 - n01
        phi = _phi(n11, n10, n01, n00)
        if phi <= MIN_CORR:
            continue
        edges.append(
            MistakeEdge(
                source=a, target=b, weight=round(phi, 4), co_miss=n11, kind="corr"
            )
        )
    edges.sort(key=lambda e: (-e.weight, e.source, e.target))
    return edges


def _summarize_groups(nodes: list[MistakeNode]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for n in nodes:
        g = groups.setdefault(
            n.group,
            {
                "id": n.group,
                "label": n.group_label,
                "axis": n.axis,
                "count": 0,
                "chronic": 0,
                "shaky": 0,
                "occasional": 0,
                "misses": 0,
            },
        )
        g["count"] += 1
        g[n.status] += 1
        g["misses"] += n.misses
    return sorted(groups.values(), key=lambda g: (-g["misses"], g["label"]))


def mistake_graph_json(
    col, *, taxonomy_path: Path = DEFAULT_TAXONOMY
) -> dict[str, Any]:
    """Serializable mistake graph for embedding in HTML or shipping over FFI."""
    return build_mistake_graph(col, taxonomy_path=taxonomy_path).to_dict()
