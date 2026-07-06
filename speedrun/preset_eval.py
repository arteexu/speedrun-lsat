# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Pre-set AI readiness briefing — a grounded standing check before a study set.

Shown on the desktop set launchers *before* a student begins a study set (Focus
by subject, Contrasting-pair drill, Cold-open diagnostic, or the main Review
session). It answers, honestly and up-front: *where do you currently stand on
this set's schemas, how hard will this set be for you, and what should you watch
for?* — then hands off to the real set launch.

Design mirrors the AI recommender (:mod:`speedrun.ai.recommender`) so it obeys
the same honesty + traceability rules:

* **Grounded in the student's real data.** Every number is built from the
  scoring/queue engine: per-schema transfer weakness, raw accuracy, attempt
  counts and the accurate-but-slow flag (:mod:`speedrun.scoring.performance`),
  the exam points-at-stake weights (:mod:`speedrun.scoring.queue`), and how many
  cards are actually due. Nothing is invented.
* **Works with AI off (default).** A deterministic evaluator turns those scores
  into the briefing (standing, weakest schemas, predicted difficulty, watch-fors).
  It is always available, needs no key, and never touches the network.
* **AI is opt-in, advisory, gated, and sourced.** A generative briefing is only
  produced when :func:`speedrun.ai.config.ai_enabled` is true AND the model
  response carries a real named source (``resp.ok`` — the traceability rule). The
  real score data is passed as grounded, injection-sanitized context; on any
  error / disabled / no-key we fall back to the deterministic briefing.
* **Honesty / give-up rule.** With too few graded attempts on a schema (the
  performance model's give-up rule) that schema is reported as *unknown* — no
  standing or difficulty is fabricated for it. When the whole set has no scored
  schema, the briefing abstains from an overall standing and difficulty entirely.
* **Never feeds the scores.** The briefing is a study aid, not a graded transfer
  attempt. It only *reads* the collection; nothing here writes to the revlog or
  the collection, and it does not touch the memory/performance/readiness scores.

The set → schemas mapping reuses the existing set builders (it does not
duplicate their logic): Focus uses the subject schema(s); Contrasting uses the
flaw schemas in the built pairs; Cold-open uses the flaw schemas in the built
items; Review uses the top schemas of the schema-weighted queue.

Qt-free and pure-data so it is unit-testable; the aqt layer renders the payload
into a dialog whose "Start set" button relays back over the pycmd bridge to the
existing set launch path.
"""
from __future__ import annotations

import html
from dataclasses import asdict, dataclass, field
from typing import Any

# The minimum points-at-stake weight given to a schema whose exam weight is
# unknown/zero, so it still carries weight in the difficulty average. Mirrors the
# recommender's floor for consistency.
_WEIGHT_FLOOR = 0.02

# Predicted-difficulty bands on the [0,1] expected-miss scale (higher = harder
# for THIS student). Difficulty is the points-at-stake-weighted mean of transfer
# weakness across the set's scored schemas.
_DIFF_MODERATE = 0.30
_DIFF_HARD = 0.55

# Standing bands on the transfer scale (points-at-stake-weighted mean transfer).
_STANDING_SOLID = 0.75
_STANDING_BUILDING = 0.55

# The four set kinds this briefing understands.
FOCUS = "focus"
CONTRASTING = "contrasting"
COLD_OPEN = "cold_open"
REVIEW = "review"
SET_KINDS = (FOCUS, CONTRASTING, COLD_OPEN, REVIEW)

# Reused from focus so the "weakest areas" token means the same thing everywhere.
WEAKEST_TOKEN = "__weakest__"

_SET_LABELS = {
    FOCUS: "Focused study",
    CONTRASTING: "Contrasting-pairs drill",
    COLD_OPEN: "Predict-the-schema cold-open",
    REVIEW: "Review session",
}


def _ai_on() -> bool:
    try:
        from speedrun.ai.config import ai_enabled

        return bool(ai_enabled())
    except Exception:
        return False


def _subject_kind(schema: str) -> str:
    return "question_type" if schema.startswith("qt.") else "schema"


def _label_for(schema: str) -> str:
    from speedrun.taxonomy.labels import schema_label

    return schema_label(schema)


def _status_for(transfer: float | None, gave_up: bool) -> str:
    if gave_up or transfer is None:
        return "untested"
    if transfer >= _STANDING_SOLID:
        return "solid"
    if transfer >= _STANDING_BUILDING:
        return "learning"
    return "weak"


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass
class SchemaStanding:
    """The student's current standing on ONE schema in the set. When the schema
    has too few graded attempts, ``gave_up`` is true and the numeric fields are
    ``None`` — the briefing never fabricates a standing for it."""

    schema: str
    kind: str  # "question_type" or "schema"
    label: str
    accuracy: float | None  # raw accuracy (ignoring the clock)
    transfer: float | None  # latency-adjusted transfer estimate
    weakness: float | None  # 1 - transfer, when scored
    n_attempts: int
    points_at_stake: float  # exam weight (floored)
    due_count: int
    speed_flag: bool
    status: str  # "weak" | "learning" | "solid" | "untested"
    gave_up: bool  # too little data to score this schema
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WatchFor:
    schema: str | None
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PreSetBriefing:
    set_kind: str
    set_label: str
    schemas: list[str]
    standings: list[SchemaStanding]
    weakest: list[SchemaStanding]  # weakest SCORED schemas in the set (worst first)
    watch_fors: list[WatchFor]
    standing_level: str  # "solid" | "building" | "weak" | "insufficient"
    overall_transfer: float | None  # points-weighted mean transfer over scored schemas
    predicted_difficulty: str  # "easy" | "moderate" | "hard" | "unknown"
    difficulty_score: float | None  # [0,1] expected-miss for this student
    confidence: str  # "high" | "medium" | "low"
    summary: str  # human, grounded standing sentence
    n_scored: int
    gave_up: bool  # no scored schema in the whole set
    reason: str
    ai_used: bool = False
    source: str = "offline"
    ai_briefing: str | None = None
    citations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["standings"] = [s.to_dict() for s in self.standings]
        d["weakest"] = [s.to_dict() for s in self.weakest]
        d["watch_fors"] = [w.to_dict() for w in self.watch_fors]
        return d


# --------------------------------------------------------------------------- #
# Set → schemas mapping (reuse the existing set builders; no logic duplicated)
# --------------------------------------------------------------------------- #


def _dedupe(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in seq:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def resolve_set_schemas(
    col,
    *,
    set_kind: str,
    schema: str | None = None,
    limit: int = 6,
    count: int | None = None,
) -> tuple[list[str], str]:
    """Resolve the schema ids a set will exercise, plus a friendly set label.

    Delegates to the existing builders so the briefing always evaluates exactly
    what the set will study:

    * **Focus** — the subject schema(s). ``schema`` is a single schema id, or the
      ``__weakest__`` token (auto-selected weakest areas via
      :func:`speedrun.focus.weakest_subjects`).
    * **Contrasting** — the distinct flaw schemas across the built pairs
      (:func:`speedrun.contrasting.build_contrasting_pairs`).
    * **Cold-open** — the distinct flaw schemas across the built items
      (:func:`speedrun.cold_open.build_cold_open_set`).
    * **Review** — the top distinct schemas of the schema-weighted queue over the
      whole deck (:func:`speedrun.scoring.queue.ordered_cards`).

    Deterministic given the same inputs. Never raises for the empty case; returns
    ``([], label)`` when no schemas resolve.
    """
    if set_kind == FOCUS:
        label = _SET_LABELS[FOCUS]
        tok = (schema or "").strip()
        if tok == WEAKEST_TOKEN:
            from speedrun.focus import weakest_subjects

            schemas = list(weakest_subjects(col))
            label = "Focus: your weakest areas"
        elif tok:
            schemas = [tok]
            label = f"Focus: {_label_for(tok)}"
        else:
            schemas = []
        return _dedupe(schemas), label

    if set_kind == CONTRASTING:
        from speedrun.contrasting import build_contrasting_pairs

        cset = build_contrasting_pairs(col, count=count)
        schemas: list[str] = []
        for p in cset.pairs:
            schemas.append(p.item_a.flaw_id)
            schemas.append(p.item_b.flaw_id)
        return _dedupe(schemas), _SET_LABELS[CONTRASTING]

    if set_kind == COLD_OPEN:
        from speedrun.cold_open import build_cold_open_set

        cset = build_cold_open_set(col, count=count)
        schemas = [it.flaw_id for it in cset.items]
        return _dedupe(schemas), _SET_LABELS[COLD_OPEN]

    if set_kind == REVIEW:
        from speedrun.scoring.queue import ordered_cards

        try:
            cards = ordered_cards(col, limit=max(limit * 8, 40))
        except Exception:
            cards = []
        schemas = _dedupe([getattr(c, "schema", "") or "" for c in cards])
        return schemas[:limit], _SET_LABELS[REVIEW]

    raise ValueError(f"unknown set_kind: {set_kind!r}")


# --------------------------------------------------------------------------- #
# Data pulls (reuse the scoring/queue engine)
# --------------------------------------------------------------------------- #

_DECK_SEARCH = 'deck:"LSAT Speedrun"'
_SCHEMA_TAG = "sr:schema:"


def _weights() -> dict[str, float]:
    try:
        from speedrun.scoring.queue import load_schema_weights

        return load_schema_weights()
    except Exception:
        return {}


def _due_counts(col, schemas: list[str]) -> dict[str, int]:
    """Cards actually due per schema. Best-effort; never raises."""
    out: dict[str, int] = {}
    for s in schemas:
        try:
            cids = col.find_cards(f'{_DECK_SEARCH} tag:"{_SCHEMA_TAG}{s}" is:due')
            if cids:
                out[s] = len(cids)
        except Exception:
            continue
    return out


# --------------------------------------------------------------------------- #
# Deterministic (offline) evaluator — grounded in the scoring engine
# --------------------------------------------------------------------------- #


def _weighted_mean(pairs: list[tuple[float, float]]) -> float | None:
    """Weighted mean of (value, weight); ``None`` when there is no positive weight."""
    denom = sum(w for _v, w in pairs)
    if denom <= 0:
        return None
    return sum(v * w for v, w in pairs) / denom


def _standing_for_schema(
    schema: str, score: Any, weight: float, due: int
) -> SchemaStanding:
    gave_up = score is None or getattr(score, "gave_up", True) or getattr(
        score, "point", None
    ) is None
    pts = max(float(weight), _WEIGHT_FLOOR)
    if gave_up:
        n_attempts = 0 if score is None else int(getattr(score, "n_attempts", 0))
        reason = (
            f"Only {n_attempts} graded attempt"
            + ("s" if n_attempts != 1 else "")
            + " — not enough to assess yet."
        )
        return SchemaStanding(
            schema=schema,
            kind=_subject_kind(schema),
            label=_label_for(schema),
            accuracy=None,
            transfer=None,
            weakness=None,
            n_attempts=n_attempts,
            points_at_stake=pts,
            due_count=due,
            speed_flag=False,
            status="untested",
            gave_up=True,
            reason=reason,
        )
    transfer = float(score.point)
    weakness = max(0.0, 1.0 - transfer)
    accuracy = getattr(score, "raw_accuracy", None)
    speed_flag = bool(getattr(score, "speed_flag", False))
    n_attempts = int(getattr(score, "n_attempts", 0))
    return SchemaStanding(
        schema=schema,
        kind=_subject_kind(schema),
        label=_label_for(schema),
        accuracy=accuracy,
        transfer=transfer,
        weakness=weakness,
        n_attempts=n_attempts,
        points_at_stake=pts,
        due_count=due,
        speed_flag=speed_flag,
        status=_status_for(transfer, gave_up=False),
        reason="Latency-adjusted transfer on graded attempts.",
        gave_up=False,
    )


def evaluate_standings(
    schemas: list[str],
    per_schema: dict[str, Any],
    weights: dict[str, float] | None = None,
    *,
    due_counts: dict[str, int] | None = None,
) -> list[SchemaStanding]:
    """Build a :class:`SchemaStanding` for each schema in the set, weakest-first.

    Scored schemas come first (worst transfer first), then the untested ones,
    with deterministic tie-breaks. ``per_schema`` maps schema id ->
    ``PerformanceScore``; missing/give-up schemas are reported as untested."""
    weights = weights or {}
    due_counts = due_counts or {}
    standings = [
        _standing_for_schema(
            s, per_schema.get(s), weights.get(s, 0.0), int(due_counts.get(s, 0))
        )
        for s in schemas
    ]
    standings.sort(
        key=lambda s: (
            0 if not s.gave_up else 1,
            -(s.weakness or 0.0),
            -s.n_attempts,
            s.schema,
        )
    )
    return standings


def _difficulty_band(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= _DIFF_HARD:
        return "hard"
    if score >= _DIFF_MODERATE:
        return "moderate"
    return "easy"


def _standing_level(transfer: float | None) -> str:
    if transfer is None:
        return "insufficient"
    if transfer >= _STANDING_SOLID:
        return "solid"
    if transfer >= _STANDING_BUILDING:
        return "building"
    return "weak"


def _confidence(n_scored: int, n_total: int, total_attempts: int) -> str:
    frac = (n_scored / n_total) if n_total else 0.0
    if frac >= 0.8 and total_attempts >= 30:
        return "high"
    if frac >= 0.5 and total_attempts >= 10:
        return "medium"
    return "low"


def _summary(
    set_label: str,
    level: str,
    overall_transfer: float | None,
    n_scored: int,
    n_total: int,
    difficulty: str,
) -> str:
    if level == "insufficient":
        return (
            "Not enough graded attempts on this set's schemas yet to assess your "
            "standing — treat this as a diagnostic run and read carefully."
        )
    tr = f"{overall_transfer:.0%}" if overall_transfer is not None else "n/a"
    scored = f"{n_scored} of {n_total} schema" + ("s" if n_total != 1 else "")
    phrase = {
        "solid": "You're on solid ground here",
        "building": "You're still building this set",
        "weak": "This set is a current weak spot",
    }.get(level, "You're still building this set")
    return (
        f"{phrase}: {tr} points-weighted transfer across {scored} with a graded "
        f"standing. Predicted difficulty for you: {difficulty}."
    )


def _watch_fors(standings: list[SchemaStanding]) -> list[WatchFor]:
    """Two–three concrete, grounded things to watch for. Built from the real
    standings only: the weakest scored schemas, any accurate-but-slow schema, and
    any untested schema (honestly flagged as unknown). Never fabricated."""
    watch: list[WatchFor] = []
    seen: set[str] = set()
    scored = [s for s in standings if not s.gave_up]
    for st in scored[:2]:
        acc = f"{st.accuracy:.0%}" if st.accuracy is not None else "low"
        watch.append(
            WatchFor(
                schema=st.schema,
                text=(
                    f"{st.label}: your lowest transfer in this set — {acc} accuracy "
                    f"over {st.n_attempts} attempts. Name the pattern before you commit."
                ),
            )
        )
        seen.add(st.schema)
    for st in standings:
        if st.speed_flag and st.schema not in seen:
            watch.append(
                WatchFor(
                    schema=st.schema,
                    text=(
                        f"{st.label}: you're accurate but slow here — you'd lose "
                        "points on the clock. Watch your pacing."
                    ),
                )
            )
            seen.add(st.schema)
            break
    for st in standings:
        if len(watch) >= 3:
            break
        if st.gave_up and st.schema not in seen:
            watch.append(
                WatchFor(
                    schema=st.schema,
                    text=(
                        f"{st.label}: no graded attempts yet — treat it as an "
                        "unknown and read carefully rather than pattern-matching."
                    ),
                )
            )
            seen.add(st.schema)
    return watch[:3]


def _offline_briefing(
    set_kind: str, set_label: str, schemas: list[str], standings: list[SchemaStanding]
) -> PreSetBriefing:
    scored = [s for s in standings if not s.gave_up]
    n_total = len(standings)
    n_scored = len(scored)
    total_attempts = sum(s.n_attempts for s in scored)

    overall_transfer = _weighted_mean(
        [(s.transfer, s.points_at_stake) for s in scored if s.transfer is not None]
    )
    difficulty_score = _weighted_mean(
        [(s.weakness, s.points_at_stake) for s in scored if s.weakness is not None]
    )
    predicted_difficulty = _difficulty_band(difficulty_score)
    level = _standing_level(overall_transfer)
    confidence = _confidence(n_scored, n_total, total_attempts)
    weakest = [s for s in scored][:3]  # already weakest-first from evaluate_standings
    watch_fors = _watch_fors(standings)
    gave_up = n_scored == 0
    if not schemas:
        reason = "No schemas resolved for this set — import the seed deck first."
    elif gave_up:
        reason = (
            "No schema in this set has enough graded attempts to score — the "
            "standing and difficulty abstain rather than guess."
        )
    else:
        reason = "Grounded in your per-schema transfer, accuracy, and exam weights."
    summary = _summary(
        set_label, level, overall_transfer, n_scored, n_total, predicted_difficulty
    )
    return PreSetBriefing(
        set_kind=set_kind,
        set_label=set_label,
        schemas=schemas,
        standings=standings,
        weakest=weakest,
        watch_fors=watch_fors,
        standing_level=level,
        overall_transfer=overall_transfer,
        predicted_difficulty=predicted_difficulty,
        difficulty_score=difficulty_score,
        confidence=confidence,
        summary=summary,
        n_scored=n_scored,
        gave_up=gave_up,
        reason=reason,
    )


# --------------------------------------------------------------------------- #
# AI-enhanced briefing (opt-in, gated, sourced)
# --------------------------------------------------------------------------- #

_PROMPT_RULES = (
    "You are an LSAT study coach writing a SHORT pre-set briefing (3-5 sentences) "
    "for a student about to start a study set. Use ONLY the student's real "
    "standing data below.\n"
    "STRICT RULES:\n"
    "1. Discuss ONLY the schemas/question-types listed below. Do not invent "
    "topics, numbers, accuracies, or a difficulty.\n"
    "2. State the student's overall standing on this set, name the weakest "
    "areas using the given accuracy/transfer, and echo the predicted difficulty "
    "and the concrete things to watch for.\n"
    "3. If a schema is marked UNKNOWN (too few attempts), say it is untested — do "
    "NOT guess a standing for it.\n"
    "4. Be concise, concrete, and encouraging."
)


def build_grounding(briefing: PreSetBriefing) -> str:
    """A compact, fully-grounded description of the briefing for the LLM."""
    lines = [f"Set: {briefing.set_label} ({briefing.set_kind})."]
    if briefing.overall_transfer is not None:
        lines.append(
            f"Overall standing: {briefing.standing_level}, "
            f"{briefing.overall_transfer:.0%} points-weighted transfer "
            f"({briefing.n_scored} scored schemas)."
        )
    else:
        lines.append(
            "Overall standing: insufficient data — no scored schema in this set."
        )
    if briefing.difficulty_score is not None:
        lines.append(
            f"Predicted difficulty for this student: {briefing.predicted_difficulty} "
            f"(expected-miss {briefing.difficulty_score:.0%})."
        )
    else:
        lines.append("Predicted difficulty: unknown (insufficient data).")
    lines.append("Per-schema standing:")
    for s in briefing.standings:
        if s.gave_up:
            lines.append(
                f"- {s.label} [{s.kind}] — UNKNOWN, {s.n_attempts} attempts "
                f"(too few to score), exam-weight {s.points_at_stake:.2f}"
            )
        else:
            acc = f"{s.accuracy:.0%}" if s.accuracy is not None else "n/a"
            tr = f"{s.transfer:.0%}" if s.transfer is not None else "n/a"
            lines.append(
                f"- {s.label} [{s.kind}] — accuracy {acc}, transfer {tr}, "
                f"weakness {(s.weakness or 0.0):.0%}, exam-weight "
                f"{s.points_at_stake:.2f}, {s.n_attempts} attempts, {s.due_count} due"
                + (", accurate-but-slow" if s.speed_flag else "")
            )
    if briefing.watch_fors:
        lines.append("Things to watch for:")
        for w in briefing.watch_fors:
            lines.append(f"- {w.text}")
    return "\n".join(lines)


def build_briefing_prompt(briefing: PreSetBriefing) -> str:
    """Grounding-hardened single-string prompt; the data block is sanitized."""
    from speedrun.ai.guard import sanitize_source_text

    safe = sanitize_source_text(build_grounding(briefing))
    return "\n".join(
        [_PROMPT_RULES, "", "Data:", '"""', safe, '"""', "", "Briefing:"]
    )


# --------------------------------------------------------------------------- #
# Public build API
# --------------------------------------------------------------------------- #


def build_preset_briefing(
    col,
    *,
    set_kind: str,
    schema: str | None = None,
    schemas: list[str] | None = None,
    limit: int = 6,
    count: int | None = None,
    client=None,
) -> PreSetBriefing:
    """Build the pre-set briefing for ``set_kind``, grounded in ``col``'s scores.

    ``schemas`` may be passed explicitly (an explicit schema-id list); otherwise
    the set's schemas are resolved from the set builders via
    :func:`resolve_set_schemas`. A deterministic briefing is always produced;
    when AI is enabled and the model returns a usable, named-source response, an
    explained briefing is added on top. Never writes to the collection."""
    from speedrun.scoring.performance import performance_score

    if schemas is not None:
        set_schemas = _dedupe(list(schemas))
        set_label = _SET_LABELS.get(set_kind, "Study set")
    else:
        set_schemas, set_label = resolve_set_schemas(
            col, set_kind=set_kind, schema=schema, limit=limit, count=count
        )

    per_schema = performance_score(col)["per_schema"]
    weights = _weights()
    scored_ids = [
        s
        for s in set_schemas
        if s in per_schema
        and not per_schema[s].gave_up
        and per_schema[s].point is not None
    ]
    due_counts = _due_counts(col, scored_ids)
    standings = evaluate_standings(
        set_schemas, per_schema, weights, due_counts=due_counts
    )
    briefing = _offline_briefing(set_kind, set_label, set_schemas, standings)

    if briefing.gave_up:
        return briefing  # nothing scored -> do not fabricate an AI standing

    if _ai_on():
        try:
            if client is None:
                from speedrun.ai.client import default_client

                client = default_client()
            prompt = build_briefing_prompt(briefing)
            resp = client.complete(prompt, max_tokens=400)
            if getattr(resp, "ok", False):
                briefing.ai_used = True
                briefing.ai_briefing = resp.text.strip()
                briefing.source = resp.source
                briefing.citations = [
                    "Grounded in your per-schema transfer, accuracy, exam weights, "
                    "and due counts for this set"
                ]
        except Exception:
            pass  # fall through to the deterministic briefing

    return briefing


def preset_briefing_payload(
    col,
    *,
    set_kind: str,
    schema: str | None = None,
    schemas: list[str] | None = None,
    limit: int = 6,
    count: int | None = None,
) -> dict[str, Any]:
    """JSON-serializable payload for the UI. Never raises."""
    try:
        briefing = build_preset_briefing(
            col,
            set_kind=set_kind,
            schema=schema,
            schemas=schemas,
            limit=limit,
            count=count,
        )
        payload = briefing.to_dict()
    except Exception as exc:  # pragma: no cover - defensive
        payload = {
            "set_kind": set_kind,
            "set_label": _SET_LABELS.get(set_kind, "Study set"),
            "schemas": [],
            "standings": [],
            "weakest": [],
            "watch_fors": [],
            "standing_level": "insufficient",
            "overall_transfer": None,
            "predicted_difficulty": "unknown",
            "difficulty_score": None,
            "confidence": "low",
            "summary": f"Could not build the briefing ({type(exc).__name__}).",
            "n_scored": 0,
            "gave_up": True,
            "reason": "error",
            "ai_used": False,
            "source": "offline",
            "ai_briefing": None,
            "citations": [],
        }
    payload["ai_enabled"] = _ai_on()
    return payload


# --------------------------------------------------------------------------- #
# Rendering (Qt-free HTML; the aqt layer drops it into a dialog)
# --------------------------------------------------------------------------- #


def _esc(text: object) -> str:
    return html.escape(str(text))


def _md(text: object) -> str:
    from speedrun.textfmt import format_inline_md

    return format_inline_md(text)


def _weak_bar(weakness: float | None) -> str:
    if weakness is None:
        return (
            '<div class="heat-bar" style="min-width:80px">'
            '<div class="heat-fill" style="width:0"></div></div>'
        )
    pct = max(0, min(100, int(weakness * 100)))
    cls = "weak" if pct >= 60 else ("mid" if pct >= 30 else "strong")
    return (
        f'<div class="heat-bar" style="min-width:80px"><div class="heat-fill {cls}" '
        f'style="width:{pct}%"></div></div>'
    )


def _standing_row(s: dict[str, Any]) -> str:
    from speedrun.taxonomy.labels import schema_display_html

    kind = "Question type" if s.get("kind") == "question_type" else "Schema"
    status = s.get("status", "untested")
    if s.get("gave_up"):
        acc = "—"
        tr = "untested"
    else:
        acc = f"{s['accuracy']:.0%}" if s.get("accuracy") is not None else "—"
        tr = f"{s['transfer']:.0%}" if s.get("transfer") is not None else "—"
    return (
        "<tr>"
        f"<td>{schema_display_html(s['schema'], compact=True)}</td>"
        f"<td>{_esc(kind)}</td>"
        f'<td><span class="sr-preset-status {_esc(status)}">{_esc(status)}</span></td>'
        f"<td class='num'>{_esc(acc)}</td>"
        f"<td class='num'>{_esc(tr)}</td>"
        f"<td>{_weak_bar(s.get('weakness'))}</td>"
        f"<td class='num'>{int(s.get('n_attempts') or 0)}</td>"
        "</tr>"
    )


_PRESET_CSS = """
.sr-preset-status-banner { display:flex; align-items:center; gap:8px; padding:10px 14px; border-radius:10px;
  font-size:0.84rem; margin-bottom:14px; border:1px solid var(--border); }
.sr-preset-status-banner.off { background: rgba(148,163,184,0.12); }
.sr-preset-status-banner.on { background: rgba(22,163,74,0.10); border-color: var(--high); }
.sr-preset-status-banner .dot { width:9px; height:9px; border-radius:50%; background:var(--muted); }
.sr-preset-status-banner.on .dot { background: var(--high); }
.sr-preset-headline { display:flex; gap:14px; flex-wrap:wrap; margin-bottom:14px; }
.sr-preset-tile { flex:1; min-width:150px; border:1px solid var(--border); border-radius:12px;
  background:var(--surface); padding:12px 16px; box-shadow:var(--shadow); }
.sr-preset-tile .lbl { font-size:0.64rem; text-transform:uppercase; letter-spacing:0.06em;
  font-weight:700; color:var(--muted); }
.sr-preset-tile .val { font-size:1.4rem; font-weight:800; margin-top:2px; letter-spacing:-0.01em; }
.sr-preset-tile .val.abstain { font-size:1rem; color:var(--muted); }
.sr-preset-tile .val.diff-hard { color:var(--low); } .sr-preset-tile .val.diff-moderate { color:var(--med); }
.sr-preset-tile .val.diff-easy { color:var(--high); }
.sr-preset-tile .val.lvl-weak { color:var(--low); } .sr-preset-tile .val.lvl-building { color:var(--med); }
.sr-preset-tile .val.lvl-solid { color:var(--high); }
.sr-preset-summary { font-size:0.98rem; line-height:1.55; margin-bottom:14px; padding:12px 16px;
  border:1px solid var(--border); border-left:4px solid var(--accent); border-radius:10px; background:var(--surface); }
.sr-preset-ai { font-size:0.92rem; line-height:1.6; margin-bottom:16px; padding:12px 16px;
  border:1px solid var(--high); border-radius:10px; background:rgba(22,163,74,0.06); white-space:pre-wrap; }
.sr-preset-ai .src { display:block; margin-top:8px; font-size:0.74rem; color:var(--muted); }
.sr-preset-ai .src .ai { color:var(--high); font-weight:700; }
.sr-preset-watch { list-style:none; padding:0; margin:0 0 16px; display:flex; flex-direction:column; gap:8px; }
.sr-preset-watch li { border:1px solid var(--border); border-left:4px solid var(--med); border-radius:10px;
  background:var(--surface); padding:10px 14px; font-size:0.88rem; line-height:1.5; }
.sr-preset-status { font-size:0.62rem; text-transform:uppercase; letter-spacing:0.05em; font-weight:700;
  padding:2px 8px; border-radius:999px; }
.sr-preset-status.weak { background:rgba(224,65,90,0.15); color:var(--low); }
.sr-preset-status.learning { background:rgba(224,140,31,0.15); color:var(--med); }
.sr-preset-status.solid { background:rgba(12,166,120,0.15); color:var(--high); }
.sr-preset-status.untested { background:rgba(154,161,181,0.2); color:var(--muted); }
.sr-preset-actions { display:flex; gap:10px; align-items:center; margin:6px 0 4px; flex-wrap:wrap; }
.sr-preset-note { font-size:0.76rem; color:var(--muted); }
"""

_PRESET_JS = r"""
(function () {
  document.querySelectorAll('.sr-preset-cmd[data-cmd]').forEach(function (b) {
    b.addEventListener('click', function () {
      if (typeof pycmd === 'function') pycmd(b.dataset.cmd);
    });
  });
})();
"""

# The wire command the "Start set" button posts back over the pycmd bridge; the
# aqt layer intercepts it and runs the real set launch it captured in Python.
START_SET_CMD = "speedrun:startset"


def _headline_tiles(payload: dict[str, Any]) -> str:
    level = payload.get("standing_level", "insufficient")
    diff = payload.get("predicted_difficulty", "unknown")
    conf = payload.get("confidence", "low")
    tr = payload.get("overall_transfer")
    if level == "insufficient" or tr is None:
        standing_val = '<div class="val abstain">Not enough data</div>'
    else:
        standing_val = (
            f'<div class="val lvl-{_esc(level)}">{tr:.0%}<span '
            f'style="font-size:0.7rem;color:var(--muted);font-weight:600"> transfer</span></div>'
        )
    if diff == "unknown":
        diff_val = '<div class="val abstain">Unknown</div>'
    else:
        diff_val = f'<div class="val diff-{_esc(diff)}">{_esc(diff.title())}</div>'
    return (
        '<div class="sr-preset-headline">'
        f'<div class="sr-preset-tile"><div class="lbl">Overall standing</div>{standing_val}</div>'
        f'<div class="sr-preset-tile"><div class="lbl">Predicted difficulty</div>{diff_val}</div>'
        f'<div class="sr-preset-tile"><div class="lbl">Confidence</div>'
        f'<div class="val" style="font-size:1rem">{_esc(conf.title())}</div></div>'
        "</div>"
    )


def _preset_body(payload: dict[str, Any], *, embed: bool) -> str:
    ai_on = bool(payload.get("ai_enabled"))
    set_label = payload.get("set_label", "Study set")
    status = (
        f'<div class="sr-preset-status-banner {"on" if ai_on else "off"}"><span class="dot"></span>'
        + (
            "AI is <b>enabled</b> — this briefing is generated and grounded in your "
            "real scores, with the model named as the source."
            if ai_on
            else "AI is <b>off by default</b> (opt-in). This briefing is computed "
            "deterministically from your transfer, accuracy, and exam weights — no "
            "outside facts."
        )
        + "</div>"
    )
    summary = f'<div class="sr-preset-summary">{_md(payload.get("summary", ""))}</div>'
    ai_block = ""
    if payload.get("ai_used") and payload.get("ai_briefing"):
        cites = payload.get("citations") or []
        cite_txt = (" · " + _esc(" · ".join(cites))) if cites else ""
        ai_block = (
            f'<div class="sr-preset-ai">{_md(payload["ai_briefing"])}'
            f'<span class="src"><span class="ai">AI</span> · source: '
            f'{_esc(payload.get("source", "?"))}{cite_txt}</span></div>'
        )
    watch = payload.get("watch_fors", [])
    if watch:
        items = "".join(f"<li>{_md(w.get('text', ''))}</li>" for w in watch)
        watch_html = (
            '<div class="sr-section"><h3>Things to watch for</h3>'
            f'<ul class="sr-preset-watch">{items}</ul></div>'
        )
    else:
        watch_html = ""
    standings = payload.get("standings", [])
    if standings:
        rows = "".join(_standing_row(s) for s in standings)
        table = (
            '<div class="sr-section"><h3>Your standing on this set\u2019s schemas</h3>'
            '<div class="sr-table-wrap"><table class="sr-table"><thead><tr>'
            "<th>schema</th><th>kind</th><th>status</th><th class='num'>accuracy</th>"
            "<th class='num'>transfer</th><th>weakness</th><th class='num'>attempts</th>"
            "</tr></thead>"
            f"<tbody>{rows}</tbody></table></div></div>"
        )
    else:
        table = (
            '<div class="sr-empty">No schemas resolved for this set. Import the '
            "seed deck first.</div>"
        )
    start_btn = (
        f'<button type="button" class="sr-btn primary sr-preset-cmd sr-preset-start" '
        f'data-cmd="{_esc(START_SET_CMD)}">Start set</button>'
    )
    actions = (
        '<div class="sr-preset-actions">'
        f"{start_btn}"
        '<span class="sr-preset-note">This briefing is a study aid — it does not '
        "change your memory, performance, or readiness scores.</span>"
        "</div>"
    )
    intro = (
        "Where you currently stand on this set's schemas, how hard it is likely to "
        "be for you, and what to watch for — grounded in your real scores. Click "
        "<b>Start set</b> when you're ready."
    )
    return (
        f"<style>{_PRESET_CSS}</style>"
        f'<div class="sr-header"><h1>Before you start: {_esc(set_label)}</h1>'
        f"<p>{intro}</p></div>"
        f"{status}{_headline_tiles(payload)}{summary}{ai_block}{actions}"
        f"{watch_html}{table}"
        f"<script>{_PRESET_JS}</script>"
    )


def render_preset_briefing_html(briefing: PreSetBriefing, *, embed: bool = False) -> str:
    """Render the pre-set briefing.

    ``embed=True`` returns body-only markup with the dashboard stylesheet inlined,
    for injection into an AnkiWebView (which supplies the ``pycmd`` bridge but not
    our CSS); ``embed=False`` returns a full standalone HTML document."""
    from speedrun.dashboard import _DASHBOARD_CSS, _shell

    payload = briefing.to_dict()
    payload["ai_enabled"] = _ai_on()
    inner = _preset_body(payload, embed=embed)
    if embed:
        return f'<style>{_DASHBOARD_CSS}</style><div class="sr-dash">{inner}</div>'
    return _shell(inner, title=f"Before you start: {briefing.set_label}")
