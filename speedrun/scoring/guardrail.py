# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The evidence gate: a hard precondition before ANY score is reported.

The honesty rule (PRD §1) forbids showing a number the data cannot back. The
existing per-score give-up rules only checked *volume* (how many reviews). But the
BrainLift's thesis (SPOV1: the LSAT is a transfer problem; SPOV2: mastery lives at
the schema, starting with flaws) means a score off five reviews of a single flaw is
dishonest even if "enough" cards were seen. Breadth matters as much as volume.

This module computes one gate from the collection that requires BOTH:

* enough flashcards actually read (volume), and
* enough distinct flaws / patterns / traps practiced (breadth of concepts),

and enough of the taxonomy touched (coverage). Memory, performance and readiness
all consult this gate; when it is closed, they abstain and say exactly what is
missing. Thresholds are configurable (``guardrail`` block in config.json) so the
rule is falsifiable and tunable, not hidden.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

from speedrun.config import guardrail_thresholds
from speedrun.scoring.memory import SCHEMA_TAG
from speedrun.scoring.memory import _schema_from_tags

TRAP_TAG = "sr:trap:"
FLAW_PREFIX = "flaw."

PKG_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAXONOMY = PKG_ROOT / "taxonomy" / "lsat_taxonomy.json"


@dataclass
class Requirement:
    """One condition of the gate, with what the student has vs. what is needed."""

    key: str
    label: str
    have: float
    need: float
    met: bool
    is_fraction: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceGate:
    """Whether there is enough evidence (volume + broad coverage) to report a score.

    Coverage is measured PER AXIS against the taxonomy, because the LSAT is a
    transfer problem (SPOV1): reviewing 250 cards of the same three flaws is not
    readiness. A score is withheld until the student has practiced ~all of the
    flaws, traps, and question/RC patterns, and read enough distinct flashcards."""

    open: bool
    requirements: list[Requirement]
    cards_read: int
    flaws_seen: int
    traps_seen: int
    patterns_seen: int
    concepts_seen: int
    total_flaws: int
    total_traps: int
    total_patterns: int
    total_concepts: int
    concept_coverage: float
    flaw_coverage: float
    trap_coverage: float
    pattern_coverage: float
    reason: str
    last_updated: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["requirements"] = [r.to_dict() for r in self.requirements]
        return d

    def missing(self) -> list[Requirement]:
        return [r for r in self.requirements if not r.met]


from functools import lru_cache


@lru_cache(maxsize=8)
def _taxonomy_totals(path: Path = DEFAULT_TAXONOMY) -> dict[str, int]:
    """Count schemas per axis: flaws, traps, patterns (question types + RC), all.

    Cached by path: the taxonomy file is read/parsed by several panels per render
    but never changes at runtime."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    schemas = data["schemas"]
    flaws = traps = patterns = 0
    for s in schemas:
        axis = s.get("axis")
        if axis == "flaw" or s["id"].startswith(FLAW_PREFIX):
            flaws += 1
        elif axis == "trap" or s["id"].startswith("trap."):
            traps += 1
        elif axis in ("question_type", "rc_structure") or s["id"].startswith(("qt.", "rc.")):
            patterns += 1
    return {
        "flaws": flaws,
        "traps": traps,
        "patterns": patterns,
        "concepts": len(schemas),
    }


def collection_evidence(col, schema_tag_prefix: str = SCHEMA_TAG) -> dict[str, int]:
    """Count distinct flashcards read and distinct flaws / patterns / traps practiced.

    A "card read" is a distinct schema-tagged card with at least one revlog entry.
    * flaws   = distinct flaw-axis schemas (the primary axis, SPOV2)
    * patterns= distinct question-type + RC-structure schemas ("which pattern is this")
    * traps   = distinct wrong-answer trap tags (Insight 8)
    * concepts= the union of all of the above (overall taxonomy touched).

    Memoized per collection-state token so the evidence gate (consulted by every
    score) is computed once per render."""
    from speedrun.score_cache import cached

    return cached(
        col, f"evidence::{schema_tag_prefix}", lambda: _collection_evidence(col, schema_tag_prefix)
    )


def _collection_evidence(col, schema_tag_prefix: str = SCHEMA_TAG) -> dict[str, int]:
    rows = col.db.all(
        """
        SELECT DISTINCT r.cid, n.tags
        FROM revlog r
        JOIN cards c ON r.cid = c.id
        JOIN notes n ON c.nid = n.id
        WHERE r.ease > 0
        """
    )
    cards: set[int] = set()
    flaws: set[str] = set()
    patterns: set[str] = set()
    traps: set[str] = set()
    for cid, tags in rows:
        if _schema_from_tags(tags, schema_tag_prefix) is None:
            continue  # not an LSAT schema card
        cards.add(int(cid))
        for tok in tags.split():
            if tok.startswith(schema_tag_prefix):
                schema = tok[len(schema_tag_prefix) :]
                if schema.startswith(FLAW_PREFIX):
                    flaws.add(schema)
                elif schema.startswith(("qt.", "rc.")):
                    patterns.add(schema)
            elif tok.startswith(TRAP_TAG):
                traps.add(tok[len(TRAP_TAG) :])
    concepts = len(flaws) + len(patterns) + len(traps)
    return {
        "cards_read": len(cards),
        "flaws_seen": len(flaws),
        "patterns_seen": len(patterns),
        "traps_seen": len(traps),
        "concepts_seen": concepts,
    }


def _safe_frac(seen: int, total: int) -> float:
    return (seen / total) if total else 0.0


def evidence_gate(
    col,
    *,
    thresholds: dict[str, Any] | None = None,
    taxonomy_path: Path = DEFAULT_TAXONOMY,
    schema_tag_prefix: str = SCHEMA_TAG,
) -> EvidenceGate:
    """Compute the evidence gate for a collection."""
    th = thresholds or guardrail_thresholds()
    ev = collection_evidence(col, schema_tag_prefix)
    totals = _taxonomy_totals(taxonomy_path)

    concept_cov = _safe_frac(ev["concepts_seen"], totals["concepts"])
    flaw_cov = _safe_frac(ev["flaws_seen"], totals["flaws"])
    trap_cov = _safe_frac(ev["traps_seen"], totals["traps"])
    pattern_cov = _safe_frac(ev["patterns_seen"], totals["patterns"])

    reqs = [
        Requirement(
            "cards_read",
            "flashcards read",
            ev["cards_read"],
            th["min_cards_read"],
            ev["cards_read"] >= th["min_cards_read"],
        ),
        Requirement(
            "concept_coverage",
            "concepts covered",
            round(concept_cov, 4),
            float(th["min_concept_coverage"]),
            concept_cov >= float(th["min_concept_coverage"]),
            is_fraction=True,
        ),
        Requirement(
            "flaw_coverage",
            "flaws covered",
            round(flaw_cov, 4),
            float(th["min_flaw_coverage"]),
            flaw_cov >= float(th["min_flaw_coverage"]),
            is_fraction=True,
        ),
        Requirement(
            "trap_coverage",
            "traps covered",
            round(trap_cov, 4),
            float(th["min_trap_coverage"]),
            trap_cov >= float(th["min_trap_coverage"]),
            is_fraction=True,
        ),
        Requirement(
            "pattern_coverage",
            "patterns covered",
            round(pattern_cov, 4),
            float(th["min_pattern_coverage"]),
            pattern_cov >= float(th["min_pattern_coverage"]),
            is_fraction=True,
        ),
    ]

    is_open = all(r.met for r in reqs)
    if is_open:
        reason = (
            "Evidence gate open: broad coverage of flaws, traps, and patterns plus "
            "enough flashcards read to report an accurate score."
        )
    else:
        parts = []
        for r in (x for x in reqs if not x.met):
            if r.is_fraction:
                parts.append(f"{r.label} {r.have:.0%} (need {r.need:.0%})")
            else:
                parts.append(f"{r.label} {int(r.have)} (need {int(r.need)})")
        reason = (
            "Locked — a score would not yet be accurate. Need: " + "; ".join(parts) + "."
        )

    return EvidenceGate(
        open=is_open,
        requirements=reqs,
        cards_read=ev["cards_read"],
        flaws_seen=ev["flaws_seen"],
        traps_seen=ev["traps_seen"],
        patterns_seen=ev["patterns_seen"],
        concepts_seen=ev["concepts_seen"],
        total_flaws=totals["flaws"],
        total_traps=totals["traps"],
        total_patterns=totals["patterns"],
        total_concepts=totals["concepts"],
        concept_coverage=concept_cov,
        flaw_coverage=flaw_cov,
        trap_coverage=trap_cov,
        pattern_coverage=pattern_cov,
        reason=reason,
    )
