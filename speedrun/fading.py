# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Adaptive mastery-ordered fading engine (SPOV3, reconciled with expertise reversal).

The consensus (Sweller/Kalyuga) is that scaffolding which helps a novice becomes
inert or harmful for an expert -- the expertise-reversal effect. SPOV3 pushes back
for the LSAT: difficulty relocates to the final two-answer decision, so the fork
explanation should be the *last* scaffold to go, not the first. Literal "backward
fading" (drop the last solution step first) would blank the fork first -- the
opposite of what we want -- so this engine fades by **step difficulty (mastery),
hardest-last**, with the fork as the terminal scaffold.

Each schema puts the student on a rung; the rung controls which worked-example
parts are shown vs. withheld, and how the student responds:

  0 Novice       (< min_attempts)                     read the full worked example
  1 Recognition  (>= min_attempts)                    recall the flaw; pick traps
  2 Generation   (raw accuracy >= recognition_gate)   generate reasoning (self-check)
  3 Fork mastery (fork accuracy >= fork_gate)          no scaffold -> timed PRESSURE

At the top rung the fork scaffold is gone and the item is scored on accuracy AND
speed (SPOV4): a steep penalty below the accuracy target and beyond the section
time budget plus a grace window.

This is training/guidance only; per the honesty rule it never feeds the
memory/performance/readiness scores. Rung thresholds live in config.fading.
Kept Qt-free and pure-data so it is unit-testable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from speedrun.contrasting import (
    DEFAULT_SEED,
    DEFAULT_TAXONOMY,
    _flaw_of,
    _load_taxonomy_meta,
)
from speedrun.taxonomy.labels import schema_label

# Rungs (ordered).
RUNG_NOVICE = 0
RUNG_RECOGNITION = 1
RUNG_GENERATION = 2
RUNG_FORK = 3

RUNG_NAMES = {
    RUNG_NOVICE: "Novice",
    RUNG_RECOGNITION: "Recognition",
    RUNG_GENERATION: "Generation",
    RUNG_FORK: "Fork mastery",
}

RESPONSE_MODE = {
    RUNG_NOVICE: "read",
    RUNG_RECOGNITION: "recall",
    RUNG_GENERATION: "generate",
    RUNG_FORK: "pressure",
}

# Worked-example parts, easiest-mastered first. `hide_at` is the lowest rung at
# which the part is withheld (student must supply it). The fork is terminal.
@dataclass(frozen=True)
class Part:
    key: str
    label: str
    hide_at: int


PARTS: tuple[Part, ...] = (
    Part("flaw_definition", "Definition of the flaw", RUNG_RECOGNITION),
    Part("trap_reasoning", "Why the easy distractors are wrong", RUNG_RECOGNITION),
    Part("flaw_name", "The name of the flaw at work", RUNG_GENERATION),
    Part("fork_rationale", "Why the runner-up loses (the two-answer fork)", RUNG_FORK),
)


@dataclass
class SchemaEvidence:
    """Objective, per-schema evidence that drives the rung. Accuracy fields are
    None until there are enough attempts to be meaningful."""

    schema: str
    attempts: int = 0
    raw_accuracy: float | None = None
    on_budget_rate: float | None = None
    fork_attempts: int = 0
    fork_accuracy: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PressurePlan:
    budget_ms: int
    accuracy_target: float
    speed_grace_ms: int
    speed_penalty_start_ms: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FadePlan:
    schema: str
    schema_label: str
    rung: int
    rung_name: str
    response_mode: str
    hidden_parts: list[str]
    visible_parts: list[str]
    next_gate: str
    reason: str
    pressure: PressurePlan | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def _budget_ms_for_schema(schema: str) -> int:
    from speedrun.config import latency_budget_ms

    if schema.startswith("rc."):
        return latency_budget_ms("RC")
    return latency_budget_ms("LR")


def rung_for(ev: SchemaEvidence, cfg: dict[str, Any] | None = None) -> int:
    """Compute the rung from objective evidence. Checked top-down so the highest
    demonstrated mastery wins; every gate needs `min_attempts` to be trusted so a
    lucky small sample cannot promote a student."""
    if cfg is None:
        from speedrun.config import fading_config

        cfg = fading_config()
    min_n = int(cfg["min_attempts"])
    if (
        ev.fork_attempts >= min_n
        and ev.fork_accuracy is not None
        and ev.fork_accuracy >= cfg["fork_gate"]
    ):
        return RUNG_FORK
    if (
        ev.attempts >= min_n
        and ev.raw_accuracy is not None
        and ev.raw_accuracy >= cfg["recognition_gate"]
    ):
        return RUNG_GENERATION
    if ev.attempts >= min_n:
        return RUNG_RECOGNITION
    return RUNG_NOVICE


def _next_gate(rung: int, ev: SchemaEvidence, cfg: dict[str, Any]) -> str:
    min_n = int(cfg["min_attempts"])
    if rung == RUNG_NOVICE:
        return (
            f"Do {max(0, min_n - ev.attempts)} more attempt(s) "
            f"(reach {min_n}) to stop reading and start recalling."
        )
    if rung == RUNG_RECOGNITION:
        acc = "—" if ev.raw_accuracy is None else f"{ev.raw_accuracy:.0%}"
        return (
            f"Reach {cfg['recognition_gate']:.0%} accuracy (now {acc}) over "
            f"\u2265{min_n} attempts to generate your own reasoning."
        )
    if rung == RUNG_GENERATION:
        have = f"{ev.fork_accuracy:.0%}" if ev.fork_accuracy is not None else "no data"
        return (
            f"Reach {cfg['fork_gate']:.0%} fork accuracy (now {have}) over "
            f"\u2265{min_n} fork attempts to enter timed pressure mode."
        )
    return (
        f"Top rung: hold \u2265{cfg['pressure_accuracy_target']:.0%} accuracy within "
        f"the time budget + {cfg['pressure_speed_grace_ms'] // 1000}s."
    )


def fade_plan(ev: SchemaEvidence, cfg: dict[str, Any] | None = None) -> FadePlan:
    """The scaffold plan for one schema: rung, which parts are shown vs withheld,
    the response mode, the next gate, and (at the top rung) the pressure params."""
    if cfg is None:
        from speedrun.config import fading_config

        cfg = fading_config()
    rung = rung_for(ev, cfg)
    hidden = [p.key for p in PARTS if rung >= p.hide_at]
    visible = [p.key for p in PARTS if rung < p.hide_at]

    pressure = None
    if rung == RUNG_FORK:
        budget = _budget_ms_for_schema(ev.schema)
        grace = int(cfg["pressure_speed_grace_ms"])
        pressure = PressurePlan(
            budget_ms=budget,
            accuracy_target=float(cfg["pressure_accuracy_target"]),
            speed_grace_ms=grace,
            speed_penalty_start_ms=budget + grace,
        )

    reason = {
        RUNG_NOVICE: "Building baseline exposure — full worked example shown.",
        RUNG_RECOGNITION: "Enough reps to stop reading definitions; recall the flaw and traps.",
        RUNG_GENERATION: "Recognition is solid; generate the reasoning before the reveal.",
        RUNG_FORK: "Fork is mastered; scaffold removed and scored on accuracy + speed.",
    }[rung]

    return FadePlan(
        schema=ev.schema,
        schema_label=schema_label(ev.schema),
        rung=rung,
        rung_name=RUNG_NAMES[rung],
        response_mode=RESPONSE_MODE[rung],
        hidden_parts=hidden,
        visible_parts=visible,
        next_gate=_next_gate(rung, ev, cfg),
        reason=reason,
        pressure=pressure,
        evidence=ev.to_dict(),
    )


# --------------------------- collection adapters ---------------------------


def fork_accuracy_by_schema(
    log_path: Path | None = None, seed_path: Path = DEFAULT_SEED
) -> dict[str, tuple[int, float]]:
    """Per-flaw fork accuracy from the fork-trainer session log.

    Fork events store the item id; we map each item to its flaw schema via the
    seed deck, then aggregate attempts and hits per schema. Returns
    {schema: (attempts, accuracy)}."""
    import json

    from speedrun.session_logger import DEFAULT_LOG, load_sessions

    data = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    item_flaw: dict[str, str] = {}
    for it in data.get("items", []):
        flaw = _flaw_of(it.get("schemas", []))
        if flaw:
            item_flaw[it.get("id", "")] = flaw

    records = load_sessions(log_path or DEFAULT_LOG, limit=8000)
    agg: dict[str, list[int]] = {}  # schema -> [attempts, hits]
    for r in records:
        if r.get("type") != "fork":
            continue
        extra = r.get("extra", {})
        schema = item_flaw.get(extra.get("item_id"))
        if not schema:
            continue
        bucket = agg.setdefault(schema, [0, 0])
        bucket[0] += 1
        if extra.get("fork_correct"):
            bucket[1] += 1
    return {s: (a, (h / a if a else 0.0)) for s, (a, h) in agg.items()}


def schema_evidence_from_collection(
    col, *, log_path: Path | None = None, seed_path: Path = DEFAULT_SEED
) -> dict[str, SchemaEvidence]:
    """Assemble per-schema evidence from the objective performance model (revlog)
    plus fork accuracy from the drill log. No gate: this is study guidance, not a
    score, so it is available before the evidence gate opens."""
    from speedrun.scoring.performance import performance_score

    perf = performance_score(col)
    forks = fork_accuracy_by_schema(log_path=log_path, seed_path=seed_path)

    out: dict[str, SchemaEvidence] = {}
    for schema, score in perf["per_schema"].items():
        fa = forks.get(schema)
        out[schema] = SchemaEvidence(
            schema=schema,
            attempts=score.n_attempts,
            raw_accuracy=score.raw_accuracy,
            on_budget_rate=score.on_budget_rate,
            fork_attempts=fa[0] if fa else 0,
            fork_accuracy=fa[1] if fa else None,
        )
    # Include schemas that only have fork data (practiced in the drill, not revlog).
    for schema, (att, acc) in forks.items():
        if schema not in out:
            out[schema] = SchemaEvidence(
                schema=schema, fork_attempts=att, fork_accuracy=acc
            )
    return out


def plans_for_collection(col, **kwargs: Any) -> list[FadePlan]:
    """Fade plans for every practiced schema, hardest rung first then by label."""
    cfg = None
    from speedrun.config import fading_config

    cfg = fading_config()
    ev = schema_evidence_from_collection(col, **kwargs)
    plans = [fade_plan(e, cfg) for e in ev.values()]
    plans.sort(key=lambda p: (-p.rung, p.schema_label))
    return plans


# ------------------------------- rendering ---------------------------------


def build_worked_example(raw_item: dict[str, Any], meta: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Extract the fade-able worked-example parts from a seed item."""
    flaw = _flaw_of(raw_item.get("schemas", [])) or ""
    fmeta = meta.get(flaw, {})
    choices = {c.get("id"): c for c in raw_item.get("choices", [])}
    fork = raw_item.get("two_answer_fork", {}) or {}
    runner = fork.get("runner_up")
    # Non-fork distractors: wrong answers that are not the runner-up.
    trap_bits = []
    for c in raw_item.get("choices", []):
        if c.get("correct") or c.get("id") == runner:
            continue
        trap = c.get("trap")
        tlabel = schema_label(trap) if trap else "distractor"
        trap_bits.append(f"({c.get('id')}) {tlabel}")
    return {
        "flaw_name": schema_label(flaw) if flaw else "(unclassified)",
        "flaw_definition": fmeta.get("description", ""),
        "trap_reasoning": "; ".join(trap_bits) or "—",
        "fork_rationale": fork.get("why_runner_up_wrong", ""),
    }


_FADE_CSS = """
.sr-fade { max-width: 820px; }
.sr-rung { display:inline-block; padding:2px 10px; border-radius:999px; font-size:0.72rem;
  font-weight:700; text-transform:uppercase; letter-spacing:0.04em; }
.sr-rung.r0 { background:rgba(100,116,139,0.16); color:var(--muted); }
.sr-rung.r1 { background:rgba(37,99,235,0.14); color:var(--accent); }
.sr-rung.r2 { background:rgba(202,138,4,0.16); color:#b45309; }
.sr-rung.r3 { background:rgba(22,163,74,0.14); color:var(--high); }
.sr-fade-row { border:1px solid var(--border); border-radius:12px; background:var(--surface);
  padding:14px 16px; margin-bottom:10px; }
.sr-fade-head { display:flex; align-items:center; gap:10px; margin-bottom:6px; }
.sr-fade-name { font-weight:700; }
.sr-fade-ev { font-size:0.8rem; color:var(--muted); margin-left:auto; font-variant-numeric:tabular-nums; }
.sr-fade-gate { font-size:0.84rem; color:var(--muted); }
.sr-fade-parts { font-size:0.8rem; margin-top:6px; }
.sr-fade-parts .hid { color:var(--low); } .sr-fade-parts .vis { color:var(--high); }
.sr-fade-pressure { font-size:0.8rem; color:#b45309; margin-top:4px; }
.sr-we-hidden { border:1px dashed var(--accent); border-radius:8px; padding:8px 12px; margin:6px 0;
  background:rgba(37,99,235,0.05); }
.sr-we-hidden summary { cursor:pointer; font-weight:600; color:var(--accent); }
.sr-we-shown { border-left:3px solid var(--border); padding-left:10px; margin:6px 0; font-size:0.9rem; }
"""


def _rung_badge(rung: int, name: str) -> str:
    return f'<span class="sr-rung r{rung}">{name}</span>'


def _part_label(key: str) -> str:
    for p in PARTS:
        if p.key == key:
            return p.label
    return key


def faded_explanation_html(
    raw_item: dict[str, Any],
    plan: FadePlan,
    meta: dict[str, dict[str, Any]],
) -> str:
    """Render one item's worked example with parts hidden per the plan. Hidden
    parts become 'your turn' prompts with the answer tucked behind <details> so it
    works without a JS bridge."""
    from speedrun.dashboard import _esc

    we = build_worked_example(raw_item, meta)
    out = [f'<div class="sr-fade-head">{_rung_badge(plan.rung, plan.rung_name)} '
           f'<span class="sr-fade-name">{_esc(plan.schema_label)}</span></div>']
    out.append(f'<div class="sr-we-shown"><b>Stimulus.</b> {_esc(raw_item.get("stimulus") or raw_item.get("passage") or "")}</div>')
    if raw_item.get("question"):
        out.append(f'<div class="sr-we-shown"><b>Question.</b> {_esc(raw_item["question"])}</div>')
    for p in PARTS:
        val = we.get(p.key) or "—"
        if p.key in plan.hidden_parts:
            verb = "Recall" if plan.rung == RUNG_RECOGNITION else "Generate"
            out.append(
                f'<details class="sr-we-hidden"><summary>{verb}: {_esc(p.label)}</summary>'
                f"<div>{_esc(val)}</div></details>"
            )
        else:
            out.append(f'<div class="sr-we-shown"><b>{_esc(p.label)}.</b> {_esc(val)}</div>')
    if plan.pressure:
        out.append(
            f'<div class="sr-fade-pressure">Pressure mode: target '
            f"{plan.pressure.accuracy_target:.0%} accuracy, budget "
            f"{plan.pressure.budget_ms // 1000}s (steep penalty beyond "
            f"{plan.pressure.speed_penalty_start_ms // 1000}s).</div>"
        )
    return "".join(out)


def render_mastery_ladder_html(
    col, *, embed: bool = False, log_path: Path | None = None
) -> str:
    """Dashboard-style report: every practiced schema, its rung, the objective
    evidence, what scaffold is faded vs shown, and the next gate."""
    from speedrun.dashboard import _DASHBOARD_CSS, _esc, _shell

    plans = plans_for_collection(col, log_path=log_path)
    if not plans:
        inner = (
            '<div class="sr-header"><h1>Mastery ladder</h1></div>'
            '<div class="sr-empty">No practiced schemas yet. Review the seed deck; '
            "each schema climbs from Novice \u2192 Recognition \u2192 Generation \u2192 "
            "Fork mastery as your accuracy grows, and the scaffold fades hardest-step-last.</div>"
        )
        return (
            f'<style>{_DASHBOARD_CSS}</style><div class="sr-dash">{inner}</div>'
            if embed
            else _shell(inner, title="Mastery ladder")
        )

    rows = []
    for p in plans:
        ev = p.evidence
        acc = "—" if ev.get("raw_accuracy") is None else f"{ev['raw_accuracy']:.0%}"
        fork = "—" if ev.get("fork_accuracy") is None else f"{ev['fork_accuracy']:.0%}"
        hidden = ", ".join(_part_label(k) for k in p.hidden_parts) or "nothing yet"
        visible = ", ".join(_part_label(k) for k in p.visible_parts) or "nothing"
        pressure = (
            f'<div class="sr-fade-pressure">Pressure: \u2265{p.pressure.accuracy_target:.0%} '
            f"within {p.pressure.budget_ms // 1000}s "
            f"(steep beyond {p.pressure.speed_penalty_start_ms // 1000}s)</div>"
            if p.pressure
            else ""
        )
        rows.append(
            f'<div class="sr-fade-row"><div class="sr-fade-head">'
            f"{_rung_badge(p.rung, p.rung_name)}"
            f'<span class="sr-fade-name">{_esc(p.schema_label)}</span>'
            f'<span class="sr-fade-ev">{ev.get("attempts", 0)} attempts · acc {acc} · fork {fork}</span>'
            f"</div>"
            f'<div class="sr-fade-parts"><span class="hid">faded:</span> {_esc(hidden)} '
            f'&nbsp;·&nbsp; <span class="vis">still shown:</span> {_esc(visible)}</div>'
            f'<div class="sr-fade-gate">Next: {_esc(p.next_gate)}</div>'
            f"{pressure}</div>"
        )

    intro = (
        f"{len(plans)} practiced schema(s). Scaffolding fades hardest-step-last as "
        "mastery grows; the two-answer fork is the terminal scaffold (SPOV3), and "
        "the top rung switches to timed pressure (SPOV4). Guidance only — never a score."
    )
    inner = (
        f"<style>{_FADE_CSS}</style>"
        '<div class="sr-header"><h1>Mastery ladder</h1>'
        f"<p>{intro}</p></div>"
        f'<div class="sr-fade">{"".join(rows)}</div>'
    )
    if embed:
        return f'<style>{_DASHBOARD_CSS}</style><div class="sr-dash">{inner}</div>'
    return _shell(inner, title="Mastery ladder")
