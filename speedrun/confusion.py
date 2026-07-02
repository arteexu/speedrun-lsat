# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Confusion-pair interleaving: interleave the schemas a student actually mixes up.

Interleaving beats blocking specifically for *confusable* categories -- similar,
hard-to-tell-apart items -- and is near-useless or harmful for unrelated ones
(Brunmair & Richter, 2019, meta-analysis g~0.42, strongest when between-category
similarity is high). So random interleaving is the wrong default. This module
interleaves the pairs of schemas the student *demonstrably confuses*:

* Observed confusions come from the drills: predict-the-schema cold-opens where
  the predicted flaw != the actual flaw, and fork-trainer trap picks where the
  named trap != the actual trap. Each mislabel is a directed A->B confusion; we
  fold direction away and count the undirected pair.
* A curated **confusable-cluster prior** seeds the cold-start (before a student
  has enough mislabels): flaws/traps known to be routinely confused
  (necessary/sufficient vs. mistaken reversal/negation; correlation->causation vs.
  common-cause; too-strong vs. opposite; ...). The prior is weighted well below
  one observation so real data dominates as soon as it exists.

The interleave sequence alternates cards from the two schemas of each top pair,
skipping any pair whose schemas lack enough cards in the deck; when there is no
usable confusion signal it falls back to the schema-weighted queue. Kept Qt-free
and pure-data so it is unit-testable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

from speedrun.contrasting import DEFAULT_SEED
from speedrun.taxonomy.labels import schema_label

SCHEMA_TAG = "sr:schema:"
DECK_SEARCH = 'deck:"LSAT Speedrun"'

# A prior observation is worth this fraction of one real mislabel, so a single
# observed confusion outranks a purely-prior pair.
PRIOR_WEIGHT = 0.5

# Curated clusters of routinely-confused schemas (BrainLift taxonomy). Any two
# members of a cluster form a prior confusable pair.
CONFUSABLE_CLUSTERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Conditional logic",
        (
            "flaw.conditional.nec_suff_confusion",
            "flaw.conditional.mistaken_reversal",
            "flaw.conditional.mistaken_negation",
        ),
    ),
    (
        "Causal reasoning",
        (
            "flaw.causal.correlation_causation",
            "flaw.causal.reversed",
            "flaw.causal.common_cause",
            "flaw.causal.post_hoc",
        ),
    ),
    (
        "Scope / quantity",
        (
            "flaw.scope.part_whole",
            "flaw.scope.percent_vs_number",
            "flaw.scope.equivocation",
        ),
    ),
    (
        "Sampling / evidence",
        (
            "flaw.sampling.unrepresentative",
            "flaw.sampling.appeal_to_ignorance",
        ),
    ),
    (
        "Strength traps",
        ("trap.too_strong_extreme", "trap.too_weak", "trap.opposite"),
    ),
    (
        "Scope traps",
        (
            "trap.out_of_scope",
            "trap.could_be_true",
            "trap.real_world_plausible",
            "trap.right_answer_wrong_question",
        ),
    ),
    (
        "Relationship traps",
        ("trap.reversed_relationship", "trap.premise_restatement", "trap.half_right"),
    ),
)


@dataclass
class ConfusionPair:
    a: str
    b: str
    a_label: str
    b_label: str
    observed: int  # times the student mislabeled one as the other
    prior: bool  # part of a curated confusable cluster
    score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InterleavedCard:
    card_id: int
    schema: str
    schema_label: str
    pair: str  # "A vs B" label of the confusion pair this card drills

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def prior_pairs() -> set[tuple[str, str]]:
    """Every within-cluster pair from the curated prior."""
    out: set[tuple[str, str]] = set()
    for _name, members in CONFUSABLE_CLUSTERS:
        for a, b in combinations(sorted(members), 2):
            out.add(_pair_key(a, b))
    return out


def build_confusion_graph(log_path: Path | None = None) -> dict[tuple[str, str], int]:
    """Observed undirected confusion counts from cold-open and fork mislabels."""
    from speedrun.session_logger import DEFAULT_LOG, load_sessions

    records = load_sessions(log_path or DEFAULT_LOG, limit=8000)
    counts: dict[tuple[str, str], int] = {}
    for r in records:
        extra = r.get("extra", {})
        typ = r.get("type")
        if typ == "cold_open" and not extra.get("schema_correct"):
            pred, actual = extra.get("predicted_schema"), extra.get("actual_schema")
        elif typ == "fork" and not extra.get("trap_correct"):
            pred, actual = extra.get("trap_pick"), extra.get("actual_trap")
        else:
            continue
        if not pred or not actual or pred == actual:
            continue
        key = _pair_key(pred, actual)
        counts[key] = counts.get(key, 0) + 1
    return counts


def confusion_pairs(
    log_path: Path | None = None, *, include_prior: bool = True
) -> list[ConfusionPair]:
    """Ranked confusion pairs: observed mislabels merged with the curated prior.

    Score = observed_count + (PRIOR_WEIGHT if in a prior cluster). Deterministic:
    ties break by score, then labels."""
    observed = build_confusion_graph(log_path)
    priors = prior_pairs() if include_prior else set()

    keys = set(observed) | priors
    pairs: list[ConfusionPair] = []
    for a, b in keys:
        obs = observed.get((a, b), 0)
        is_prior = (a, b) in priors
        score = obs + (PRIOR_WEIGHT if is_prior else 0.0)
        pairs.append(
            ConfusionPair(
                a=a,
                b=b,
                a_label=schema_label(a),
                b_label=schema_label(b),
                observed=obs,
                prior=is_prior,
                score=score,
            )
        )
    pairs.sort(key=lambda p: (-p.score, p.a_label, p.b_label))
    return pairs


def _cards_for_schema(col, schema: str, *, search: str = DECK_SEARCH) -> list[int]:
    try:
        return list(col.find_cards(f'{search} "tag:{SCHEMA_TAG}{schema}"'))
    except Exception:
        return []


def interleave_sequence(
    col,
    *,
    limit: int = 20,
    log_path: Path | None = None,
    min_pair_cards: int = 2,
) -> list[InterleavedCard]:
    """Alternate cards from the two schemas of each top confusion pair.

    A pair is used only if the deck has at least ``min_pair_cards`` cards across
    its two schemas (interleaving needs something to contrast). Trap-only pairs
    are naturally skipped because traps are not card tags. Falls back to the
    schema-weighted queue when there is no usable confusion signal."""
    used: set[int] = set()
    out: list[InterleavedCard] = []

    for pair in confusion_pairs(log_path):
        if len(out) >= limit:
            break
        a_cards = [c for c in _cards_for_schema(col, pair.a) if c not in used]
        b_cards = [c for c in _cards_for_schema(col, pair.b) if c not in used]
        if len(a_cards) + len(b_cards) < min_pair_cards:
            continue
        pair_label = f"{pair.a_label} vs {pair.b_label}"
        # Alternate A, B, A, B ... until both exhausted or limit hit.
        i = 0
        while (i < len(a_cards) or i < len(b_cards)) and len(out) < limit:
            for cards, schema in ((a_cards, pair.a), (b_cards, pair.b)):
                if i < len(cards) and len(out) < limit:
                    cid = cards[i]
                    used.add(cid)
                    out.append(
                        InterleavedCard(
                            card_id=cid,
                            schema=schema,
                            schema_label=schema_label(schema),
                            pair=pair_label,
                        )
                    )
            i += 1

    if not out:
        # No usable confusion signal -> fall back to the schema-weighted queue.
        from speedrun.scoring.queue import ordered_cards

        for sc in ordered_cards(col, limit=limit):
            out.append(
                InterleavedCard(
                    card_id=getattr(sc, "card_id", 0),
                    schema=getattr(sc, "schema", ""),
                    schema_label=schema_label(getattr(sc, "schema", "")),
                    pair="(schema-weighted fallback)",
                )
            )
    return out[:limit]


# ------------------------------- rendering ---------------------------------

_CONF_CSS = """
.sr-conf { max-width: 820px; }
.sr-conf-pair { border:1px solid var(--border); border-radius:12px; background:var(--surface);
  padding:12px 16px; margin-bottom:10px; display:flex; align-items:center; gap:12px; }
.sr-conf-names { font-weight:700; }
.sr-conf-tag { font-size:0.7rem; font-weight:700; text-transform:uppercase; letter-spacing:0.04em;
  padding:2px 8px; border-radius:999px; }
.sr-conf-tag.obs { background:rgba(220,38,38,0.12); color:var(--low); }
.sr-conf-tag.prior { background:rgba(37,99,235,0.12); color:var(--accent); }
.sr-conf-meta { margin-left:auto; font-size:0.8rem; color:var(--muted); font-variant-numeric:tabular-nums; }
.sr-conf-seq { border:1px solid var(--border); border-radius:12px; background:var(--surface);
  padding:12px 16px; margin-top:8px; }
.sr-conf-chip { display:inline-block; margin:3px 4px; padding:3px 10px; border-radius:999px;
  background:var(--bar-bg); font-size:0.8rem; }
"""


def render_confusion_report_html(col, *, embed: bool = False, log_path: Path | None = None) -> str:
    """Report: the student's top confusion pairs (observed vs prior) and the
    interleaved study plan that alternates them. Study guidance, not a score."""
    from speedrun.dashboard import _DASHBOARD_CSS, _esc, _shell

    pairs = confusion_pairs(log_path)
    seq = interleave_sequence(col, limit=16, log_path=log_path)

    pair_rows = []
    for p in pairs[:12]:
        tag = (
            '<span class="sr-conf-tag obs">observed</span>'
            if p.observed
            else '<span class="sr-conf-tag prior">likely</span>'
        )
        meta = (
            f"{p.observed} mislabel(s)"
            if p.observed
            else "curated confusable pair"
        )
        pair_rows.append(
            f'<div class="sr-conf-pair">{tag}'
            f'<span class="sr-conf-names">{_esc(p.a_label)} &harr; {_esc(p.b_label)}</span>'
            f'<span class="sr-conf-meta">{meta}</span></div>'
        )

    chips = "".join(
        f'<span class="sr-conf-chip" title="{_esc(c.pair)}">{_esc(c.schema_label)}</span>'
        for c in seq
    )
    seq_html = (
        f'<div class="sr-conf-seq"><b>Interleaved plan ({len(seq)} cards):</b><br>{chips}</div>'
        if seq
        else '<div class="sr-empty">No cards to interleave yet — import the seed deck.</div>'
    )

    intro = (
        "Interleaving pays off for <i>confusable</i> schemas, not random ones "
        "(Brunmair &amp; Richter, 2019). These are the pairs you actually mix up "
        "(from cold-open and fork mislabels), seeded by a curated prior until you "
        "have data. The plan alternates cards from each pair. Guidance only, not a score."
    )
    inner = (
        f"<style>{_CONF_CSS}</style>"
        '<div class="sr-header"><h1>Confusion-pair interleaving</h1>'
        f"<p>{intro}</p></div>"
        f'<div class="sr-conf">{"".join(pair_rows) or "<div class=sr-empty>No confusion pairs yet.</div>"}'
        f"{seq_html}</div>"
    )
    if embed:
        return f'<style>{_DASHBOARD_CSS}</style><div class="sr-dash">{inner}</div>'
    return _shell(inner, title="Confusion-pair interleaving")
