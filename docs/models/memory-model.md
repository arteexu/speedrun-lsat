# Memory Model — one-page description

> **Canonical PRD-path copy.** This is the model description linked from the
> PRD (`docs/models/memory-model.md`). It is kept in sync with the in-repo copy
> at [`../speedrun/docs/models/memory-model.md`](../speedrun/docs/models/memory-model.md);
> if the two ever diverge, this file and its sibling are the same document.

> Status: **Implemented** on seed deck; calibration harness runs; full-scale held-out eval pending larger deck.

## Question it answers

Can the student recall a **taught fact** right now? On the LSAT this is deliberately a _small_ part of the system (SPOV / BrainLift "Out of Scope"): flaw and trap **definitions**, conditional-logic terminology, RC vocabulary. Memory is supporting, not foundational.

## Method

Anki's built-in **FSRS** scheduler estimates recall probability per card from review history. We consume FSRS's retrievability estimate directly; we do not modify the memory algorithm.

- Input: per-card review history (grades + timing) maintained by `rslib`.
- Output: P(recall) per card, aggregated per schema and overall, reported **with a range** (not a bare point).

**Implementation.** Per-card retrievability is read straight from the engine via
the `extract_fsrs_retrievability` SQL function (no FSRS reimplementation). Cards
carry their schema as an `sr:schema:` note tag. Aggregation, the range, and the
give-up rule live in [`speedrun/scoring/memory.py`](../../speedrun/scoring/memory.py);
the range is a normal-approximation CI on the mean of per-card recall
probabilities, clamped to [0, 1]. Cards with no FSRS memory yet (unreviewed) are
excluded from the estimate but counted in coverage.

## Honest reporting (seed deck, 11 reviews, 2026-07-01)

- Point estimate: **100%** recall
- Likely range: **100%–100%** (normal-approx CI on per-card FSRS retrievability)
- Coverage: **100%** of reviewed cards (11/11)
- Confidence indicator: **low** (tiny deck; all Good answers)
- Last updated: runtime timestamp in score object
- Top reasons: seed deck only; not representative of production scale

## Give-up rule

Show **no** memory score until enough cards have been reviewed. Implemented
defaults (tunable in `speedrun/scoring/memory.py`): **overall ≥ 5** reviewed
cards; **per schema ≥ 2** reviewed cards. Below the line the score abstains and
names exactly what is missing (e.g., "Not enough data: 1 reviewed card < required
2"). These low seed-stage defaults will be raised as the deck grows.

## Calibration (held-out)

Calibrate on reviews held out of fitting. When the model says 80%, observed recall should be ≈80%.

Harness: `speedrun/eval/calibration.py` (`pylib/tests/test_speedrun_calibration.py`).

Seed-deck result (all Good answers, min held-out=5):

- Reliability chart: not yet exported to figure (bins in report object)
- Brier score: **0.0000** (lower is better)
- Log loss: **0.0000**
- Held-out set size: **22 reviews**, split method: **last 30% of revlog rows per card (seeded order)**

**Caveat:** perfect scores on 11 cards are not meaningful calibration evidence.

## Re-runnability

Report the current memory score for any collection:

```bash
python speedrun/tools/memory_report.py --col /path/to/collection.anki2        # or --base <ANKI_BASE>
python speedrun/tools/memory_report.py --col ... --json
PYTHONPATH=out/pylib out/pyenv/bin/python -c "from speedrun.eval.calibration import calibration_report; ..."
```

Tests (`pylib/tests/test_speedrun_memory.py`) cover the importer, the abstain
path (no reviews), and a real score after FSRS reviews.

## Known limitations

- FSRS estimates memory, not transfer; a high memory score does **not** imply LSAT performance (that gap is the whole point — see the performance model).
- Seed deck is too small for reliable calibration or per-schema breakdowns at scale.
