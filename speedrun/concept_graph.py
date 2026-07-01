# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Build a traversable concept map from the flashcards a student has completed.

BrainLift SPOV1 says the LSAT is a *transfer* problem organised around schemas,
and SPOV2 says mastery lives at the schema (flaws first). This module turns the
student's actual review history into a graph:

* a **node** is every schema (flaw / question-type / RC-structure / trap) that has
  appeared on at least one completed card, sized by how many cards touched it and
  coloured by how strong the student is on it (strong / learning / weak);
* an **edge** links two schemas that show up together on the same flashcards
  ("these problems are similar") or that belong to the same taxonomy family, so
  related concepts cluster together and the student can traverse from a strong
  area into an adjacent weak one.

It is deliberately Qt-free and pure-data so it can be unit-tested and reused by the
dashboard, an exported report, or (later) the iOS client.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

from speedrun.insights import schema_mastery_map
from speedrun.taxonomy.labels import schema_label, schema_short_label

PKG_ROOT = Path(__file__).resolve().parent
DEFAULT_TAXONOMY = PKG_ROOT / "taxonomy" / "lsat_taxonomy.json"

SCHEMA_TAG = "sr:schema:"
QTYPE_TAG = "sr:qtype:"
TRAP_TAG = "sr:trap:"
_AXIS_TAGS = (SCHEMA_TAG, QTYPE_TAG, TRAP_TAG)

# A concept counts as "strong" / "weak" at these strength cutoffs (0..1).
STRONG_AT = 0.75
WEAK_BELOW = 0.50

# Only draw a similarity edge once two concepts have co-occurred this many times,
# so a single shared card does not create noise.
MIN_SHARED = 1

_AXIS_NAMES = {
    "flaw": "Flaws",
    "qt": "Question types",
    "rc": "Reading comprehension",
    "trap": "Traps",
}


@dataclass
class ConceptNode:
    id: str
    label: str
    short_label: str
    axis: str
    group: str
    group_label: str
    status: str  # strong | learning | weak | untested
    strength: float | None  # 0..1 blended mastery, None if untested
    memory: float | None
    performance: float | None
    accuracy: float | None
    cards: int
    reviews: int
    exam_weight: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConceptEdge:
    source: str
    target: str
    weight: int
    kind: str  # shared | family

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConceptGraph:
    nodes: list[ConceptNode] = field(default_factory=list)
    edges: list[ConceptEdge] = field(default_factory=list)
    groups: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "groups": self.groups,
            "stats": self.stats,
        }


def _axis_of(schema_id: str) -> str:
    return schema_id.split(".", 1)[0]


def _group_of(schema_id: str, meta: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """A cluster key + human label: a taxonomy family (e.g. flaw.causal) when the
    schema has a category, otherwise its axis (e.g. all question types together)."""
    axis = _axis_of(schema_id)
    category = (meta.get(schema_id) or {}).get("category")
    axis_name = _AXIS_NAMES.get(axis, axis.upper())
    if category:
        return (
            f"{axis}.{category}",
            f"{axis_name} · {category.replace('_', ' ').title()}",
        )
    return axis, axis_name


def _load_taxonomy_meta(path: Path = DEFAULT_TAXONOMY) -> dict[str, dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        s["id"]: {
            "axis": s.get("axis"),
            "category": s.get("category"),
            "name": s.get("name"),
            "exam_weight": float(s.get("exam_weight", 0.0) or 0.0),
        }
        for s in data["schemas"]
    }


def _schema_ids_from_tags(tags: str) -> set[str]:
    out: set[str] = set()
    for tok in tags.split():
        for prefix in _AXIS_TAGS:
            if tok.startswith(prefix):
                out.add(tok[len(prefix) :])
                break
    return out


def _status_from_strength(strength: float | None, reviews: int) -> str:
    if strength is None or reviews == 0:
        return "untested"
    if strength >= STRONG_AT:
        return "strong"
    if strength < WEAK_BELOW:
        return "weak"
    return "learning"


def build_concept_graph(col, *, taxonomy_path: Path = DEFAULT_TAXONOMY) -> ConceptGraph:
    """Assemble the concept map from the collection's completed reviews."""
    meta = _load_taxonomy_meta(taxonomy_path)

    # Mastery (memory/performance) is only computed for the primary flaw/RC axis;
    # keep it to enrich those nodes' colour and detail panel.
    mastery = {m.schema: m for m in schema_mastery_map(col)}

    # Every review, with its card's tags, so we can measure volume + accuracy.
    review_rows = col.db.all(
        """
        SELECT r.cid, r.ease, n.tags
        FROM revlog r
        JOIN cards c ON r.cid = c.id
        JOIN notes n ON c.nid = n.id
        WHERE r.ease > 0
        """
    )

    cards_by_schema: dict[str, set[int]] = {}
    reviews_by_schema: dict[str, int] = {}
    correct_by_schema: dict[str, int] = {}
    card_schema_sets: dict[int, set[str]] = {}

    for cid, ease, tags in review_rows:
        ids = _schema_ids_from_tags(tags)
        if not ids:
            continue
        card_schema_sets[int(cid)] = ids
        for sid in ids:
            cards_by_schema.setdefault(sid, set()).add(int(cid))
            reviews_by_schema[sid] = reviews_by_schema.get(sid, 0) + 1
            if ease > 1:  # Again == 1 is the only "wrong" grade
                correct_by_schema[sid] = correct_by_schema.get(sid, 0) + 1

    nodes: list[ConceptNode] = []
    for sid in sorted(cards_by_schema):
        reviews = reviews_by_schema.get(sid, 0)
        accuracy = (correct_by_schema.get(sid, 0) / reviews) if reviews else None
        m = mastery.get(sid)
        mem = m.memory if m else None
        perf = m.performance if m else None
        # Blend the best signal we have: performance (transfer) dominates, then
        # memory (recall), then raw accuracy on this concept's cards.
        strength = perf if perf is not None else (mem if mem is not None else accuracy)
        group, group_label = _group_of(sid, meta)
        nodes.append(
            ConceptNode(
                id=sid,
                label=schema_label(sid),
                short_label=schema_short_label(sid),
                axis=_axis_of(sid),
                group=group,
                group_label=group_label,
                status=_status_from_strength(strength, reviews),
                strength=round(strength, 4) if strength is not None else None,
                memory=round(mem, 4) if mem is not None else None,
                performance=round(perf, 4) if perf is not None else None,
                accuracy=round(accuracy, 4) if accuracy is not None else None,
                cards=len(cards_by_schema[sid]),
                reviews=reviews,
                exam_weight=(meta.get(sid) or {}).get("exam_weight", 0.0),
            )
        )

    present = {n.id for n in nodes}
    edges = _build_edges(card_schema_sets, present, meta)

    groups = _summarize_groups(nodes)
    stats = {
        "n_nodes": len(nodes),
        "n_edges": len(edges),
        "n_groups": len(groups),
        "strong": sum(1 for n in nodes if n.status == "strong"),
        "weak": sum(1 for n in nodes if n.status == "weak"),
        "learning": sum(1 for n in nodes if n.status == "learning"),
        "cards_completed": len(card_schema_sets),
    }
    return ConceptGraph(nodes=nodes, edges=edges, groups=groups, stats=stats)


def _build_edges(
    card_schema_sets: dict[int, set[str]],
    present: set[str],
    meta: dict[str, dict[str, Any]],
) -> list[ConceptEdge]:
    # 1) Similarity edges: schemas that co-occur on the same completed card.
    shared: dict[tuple[str, str], int] = {}
    for ids in card_schema_sets.values():
        for a, b in combinations(sorted(ids), 2):
            shared[(a, b)] = shared.get((a, b), 0) + 1

    edges: list[ConceptEdge] = []
    linked: set[tuple[str, str]] = set()
    for (a, b), w in shared.items():
        if w >= MIN_SHARED:
            edges.append(ConceptEdge(source=a, target=b, weight=w, kind="shared"))
            linked.add((a, b))

    # 2) Family edges: same taxonomy group (e.g. two causal flaws) so a category
    #    forms a visible cluster even when its members never share a card.
    by_group: dict[str, list[str]] = {}
    for sid in sorted(present):
        group, _ = _group_of(sid, meta)
        by_group.setdefault(group, []).append(sid)
    for members in by_group.values():
        for a, b in combinations(members, 2):
            key = (a, b) if a < b else (b, a)
            if key in linked:
                continue
            edges.append(
                ConceptEdge(source=key[0], target=key[1], weight=1, kind="family")
            )
            linked.add(key)
    return edges


def _summarize_groups(nodes: list[ConceptNode]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for n in nodes:
        g = groups.setdefault(
            n.group,
            {
                "id": n.group,
                "label": n.group_label,
                "axis": n.axis,
                "count": 0,
                "strong": 0,
                "weak": 0,
                "learning": 0,
            },
        )
        g["count"] += 1
        if n.status in ("strong", "weak", "learning"):
            g[n.status] += 1
    return sorted(groups.values(), key=lambda g: (g["axis"], g["label"]))


def concept_graph_json(
    col, *, taxonomy_path: Path = DEFAULT_TAXONOMY
) -> dict[str, Any]:
    """Serializable concept map for embedding in HTML or shipping over FFI."""
    return build_concept_graph(col, taxonomy_path=taxonomy_path).to_dict()
