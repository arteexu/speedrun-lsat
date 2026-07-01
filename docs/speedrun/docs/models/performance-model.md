# Performance Model — one-page description

> Status: **Implemented** with revlog-based transfer proxy; paraphrase harness (7d) runs; real reworded grading pending.

## Question it answers

Can the student get a **new, exam-style item right** — including items they have never seen — using a given schema? This is the **memory → transfer bridge**, the core of the app (BrainLift SPOV1). It must **not** simply echo FSRS memory.

## Method

A per-schema model predicting P(correct) on a novel item, from:

- **Schema mastery** — running transfer estimate for the item's schema(s) (primary: flaw).
- **Item difficulty** — not yet item-level; uses revlog grades as proxy.
- **Latency** — response time co-equal with correctness (SPOV4): correct-but-over-budget is discounted via `on_budget_rate`.
- **Coverage** — whether the student has enough exposure across the schema to generalize.

Model form: **Wilson interval on latency-adjusted accuracy** per schema and overall (`speedrun/scoring/performance.py`). Habitual trap type is planned; not yet wired from revlog.

## Honest reporting (seed deck, 11 reviews, 2026-07-01)

- Point estimate (overall): **93%** transfer (latency-adjusted)
- Likely range: reported per score object (Wilson on on-budget accuracy)
- Coverage: all seed schemas with ≥10 revlog attempts after full deck review
- Confidence: **low** (11 cards, single session)
- Last updated: runtime timestamp
- Top reasons / weakest schema: surfaced in dashboard per-schema table

## Give-up rule

No per-schema performance estimate until **≥ 2** graded attempts on that schema.
Overall performance abstains below **≥ 10** total graded attempts (`MIN_ATTEMPTS_OVERALL`).

## Validation — the paraphrase / transfer test (spec 7d)

Harness: `speedrun/eval/transfer_gap.py` — 11 seed cards × 2 synthetic reworded variants.

After full seed review with synthetic transfer penalty 0.15:

- Recall (FSRS): **100%** [100%–100%]
- Transfer accuracy (reworded): **54%** [35%–73%]
- **Gap (recall − transfer): +46%** — bridge is distinct from memory (not echoing FSRS)
- Without reviews: report **abstains** honestly

Held-out exam-style items at scale: **not yet run** (needs larger tagged deck).

## Re-runnability

```bash
PYTHONPATH=out/pylib out/pyenv/bin/python -c "
from speedrun.eval.transfer_gap import transfer_gap_report
from tests.shared import getEmptyCol
from speedrun.tools.import_seed_deck import import_seed_deck
# ... review loop ...
print(transfer_gap_report(col, synthetic_transfer_penalty=0.15).format_report())
"
```

Tests: `pylib/tests/test_speedrun_performance.py`, `pylib/tests/test_speedrun_transfer.py`.

## Known limitations

- Current revlog proxy is same-card review, not true novel items until reworded grading ships.
- Sparse data on low-frequency schemas widens Wilson intervals.
- Latency budget defaults to schema taxonomy `time_budget_ms`; seed deck uses defaults.
