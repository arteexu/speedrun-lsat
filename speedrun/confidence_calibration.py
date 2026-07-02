# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Confidence calibration: is the student's felt certainty matched by reality?

Karpicke & Roediger showed learners' confidence is largely uncorrelated with
actual performance, and the Dunning-Kruger pattern is that weak students are the
*most* overconfident. That makes calibration -- the gap between how sure you feel
and how often you're right -- a first-class, honest signal: it tells a student
where their sense of mastery is a mirage.

We read the confidence the student attaches to each fork decision (Guess / Fairly
sure / Certain -> 0.5 / 0.75 / 0.95) alongside whether the fork was correct, and
report:

* **Brier score** -- mean squared error between confidence and outcome (0 = perfect,
  lower is better).
* **Overconfidence** -- mean confidence minus mean accuracy (positive = overconfident).
* **Per-schema overconfidence** -- so we can name the schema where the student's
  certainty is most misplaced (the highest-value place to correct, via the
  hypercorrection effect: high-confidence errors, once corrected, stick best).

This is training/diagnostic signal only and never feeds the
memory/performance/readiness scores (honesty rule). Distinct from
`speedrun/eval/calibration.py`, which calibrates the FSRS *memory* model against
held-out reviews. Kept Qt-free and pure-data so it is unit-testable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from speedrun.contrasting import DEFAULT_SEED, _flaw_of
from speedrun.taxonomy.labels import schema_label

# Minimum confidence-tagged attempts before we report a calibration number.
MIN_JUDGED = 10


@dataclass
class SchemaCalibration:
    schema: str
    schema_label: str
    n: int
    mean_confidence: float
    accuracy: float
    overconfidence: float  # mean_confidence - accuracy

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CalibrationResult:
    n: int
    brier: float | None
    mean_confidence: float | None
    accuracy: float | None
    overconfidence: float | None
    gave_up: bool
    reason: str
    per_schema: list[SchemaCalibration] = field(default_factory=list)
    most_overconfident: SchemaCalibration | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["per_schema"] = [s.to_dict() for s in self.per_schema]
        d["most_overconfident"] = (
            self.most_overconfident.to_dict() if self.most_overconfident else None
        )
        return d


def _judged_fork_events(log_path: Path | None, seed_path: Path) -> list[tuple[str | None, float, bool]]:
    """(schema, confidence, correct) for fork events that carry a confidence."""
    import json

    from speedrun.session_logger import DEFAULT_LOG, load_sessions

    data = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    item_flaw: dict[str, str] = {}
    for it in data.get("items", []):
        flaw = _flaw_of(it.get("schemas", []))
        if flaw:
            item_flaw[it.get("id", "")] = flaw

    out: list[tuple[str | None, float, bool]] = []
    for r in load_sessions(log_path or DEFAULT_LOG, limit=8000):
        if r.get("type") != "fork":
            continue
        extra = r.get("extra", {})
        conf = extra.get("confidence")
        if conf is None:
            continue
        out.append(
            (item_flaw.get(extra.get("item_id")), float(conf), bool(extra.get("fork_correct")))
        )
    return out


def confidence_calibration(
    log_path: Path | None = None,
    *,
    seed_path: Path = DEFAULT_SEED,
    min_judged: int = MIN_JUDGED,
) -> CalibrationResult:
    """Compute the confidence-calibration result from judged fork decisions."""
    events = _judged_fork_events(log_path, seed_path)
    n = len(events)
    if n < min_judged:
        return CalibrationResult(
            n=n,
            brier=None,
            mean_confidence=None,
            accuracy=None,
            overconfidence=None,
            gave_up=True,
            reason=(
                f"Not enough judged decisions: {n} < required {min_judged}. "
                "Rate your confidence in the fork trainer to get a calibration score."
            ),
        )

    brier = sum((c - (1.0 if ok else 0.0)) ** 2 for _s, c, ok in events) / n
    mean_conf = sum(c for _s, c, _ok in events) / n
    accuracy = sum(1 for _s, _c, ok in events if ok) / n

    by_schema: dict[str, list[tuple[float, bool]]] = {}
    for schema, c, ok in events:
        if schema:
            by_schema.setdefault(schema, []).append((c, ok))

    per_schema: list[SchemaCalibration] = []
    for schema, rows in by_schema.items():
        m = len(rows)
        mc = sum(c for c, _ in rows) / m
        acc = sum(1 for _, ok in rows if ok) / m
        per_schema.append(
            SchemaCalibration(
                schema=schema,
                schema_label=schema_label(schema),
                n=m,
                mean_confidence=round(mc, 4),
                accuracy=round(acc, 4),
                overconfidence=round(mc - acc, 4),
            )
        )
    # Rank most-overconfident first (deterministic tie-break by label).
    per_schema.sort(key=lambda s: (-s.overconfidence, s.schema_label))
    most = per_schema[0] if per_schema and per_schema[0].overconfidence > 0 else None

    return CalibrationResult(
        n=n,
        brier=round(brier, 4),
        mean_confidence=round(mean_conf, 4),
        accuracy=round(accuracy, 4),
        overconfidence=round(mean_conf - accuracy, 4),
        gave_up=False,
        reason="Confidence vs. outcome on judged fork decisions.",
        per_schema=per_schema,
        most_overconfident=most,
    )


def calibration_summary(log_path: Path | None = None) -> dict[str, Any]:
    """Compact dashboard summary. Honesty-safe: training signal, not a score."""
    r = confidence_calibration(log_path)
    return {
        "n": r.n,
        "brier": r.brier,
        "overconfidence": r.overconfidence,
        "gave_up": r.gave_up,
        "most_overconfident": (
            r.most_overconfident.schema_label if r.most_overconfident else None
        ),
    }


# ------------------------------- rendering ---------------------------------

_CAL_CSS = """
.sr-cal-hero { display:flex; gap:26px; flex-wrap:wrap; margin:12px 0 18px; }
.sr-cal-hero .num { font-size:1.9rem; font-weight:800; }
.sr-cal-hero .lbl { font-size:0.76rem; color:var(--muted); text-transform:uppercase; letter-spacing:0.04em; }
.sr-cal-over { color:var(--low); } .sr-cal-under { color:var(--accent); } .sr-cal-ok { color:var(--high); }
.sr-cal-table { width:100%; border-collapse:collapse; font-size:0.88rem; }
.sr-cal-table th, .sr-cal-table td { text-align:left; padding:7px 10px; border-bottom:1px solid var(--border); }
.sr-cal-table td.num { text-align:right; font-variant-numeric:tabular-nums; }
.sr-cal-pos { color:var(--low); font-weight:700; } .sr-cal-neg { color:var(--accent); }
"""


def render_confidence_calibration_html(
    col=None, *, embed: bool = False, log_path: Path | None = None
) -> str:
    """Report the confidence-calibration result. ``col`` is accepted for a uniform
    report signature but unused (data comes from the drill log)."""
    from speedrun.dashboard import _DASHBOARD_CSS, _esc, _shell

    r = confidence_calibration(log_path)
    if r.gave_up:
        inner = (
            '<div class="sr-header"><h1>Confidence calibration</h1></div>'
            f'<div class="sr-empty">{_esc(r.reason)}</div>'
        )
        return (
            f'<style>{_DASHBOARD_CSS}</style><div class="sr-dash">{inner}</div>'
            if embed
            else _shell(inner, title="Confidence calibration")
        )

    def over_cls(v: float) -> str:
        return "sr-cal-over" if v > 0.1 else ("sr-cal-under" if v < -0.1 else "sr-cal-ok")

    hero = (
        f'<div class="sr-cal-hero">'
        f'<div><div class="num">{r.brier:.2f}</div><div class="lbl">Brier (lower better)</div></div>'
        f'<div><div class="num {over_cls(r.overconfidence)}">{r.overconfidence:+.0%}</div>'
        f'<div class="lbl">Over/under-confidence</div></div>'
        f'<div><div class="num">{r.mean_confidence:.0%}</div><div class="lbl">Felt sure</div></div>'
        f'<div><div class="num">{r.accuracy:.0%}</div><div class="lbl">Actually right</div></div>'
        f"</div>"
    )
    rows = []
    for s in r.per_schema:
        cls = "sr-cal-pos" if s.overconfidence > 0 else "sr-cal-neg"
        rows.append(
            f"<tr><td>{_esc(s.schema_label)}</td>"
            f'<td class="num">{s.n}</td>'
            f'<td class="num">{s.mean_confidence:.0%}</td>'
            f'<td class="num">{s.accuracy:.0%}</td>'
            f'<td class="num {cls}">{s.overconfidence:+.0%}</td></tr>'
        )
    table = (
        '<table class="sr-cal-table"><thead><tr><th>Schema</th><th>n</th>'
        "<th>Felt sure</th><th>Right</th><th>Gap</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    call = (
        f"<p><b>Most misplaced certainty:</b> {_esc(r.most_overconfident.schema_label)} "
        f"(felt {r.most_overconfident.mean_confidence:.0%}, right "
        f"{r.most_overconfident.accuracy:.0%}). High-confidence misses here are the "
        f"best to correct (hypercorrection).</p>"
        if r.most_overconfident
        else ""
    )
    intro = (
        f"{r.n} judged fork decisions. Confidence is largely uncorrelated with "
        "accuracy (Karpicke &amp; Roediger), and weak spots hide behind false "
        "certainty. Guidance only, never a score."
    )
    inner = (
        f"<style>{_CAL_CSS}</style>"
        '<div class="sr-header"><h1>Confidence calibration</h1>'
        f"<p>{intro}</p></div>{hero}{call}{table}"
    )
    if embed:
        return f'<style>{_DASHBOARD_CSS}</style><div class="sr-dash">{inner}</div>'
    return _shell(inner, title="Confidence calibration")
