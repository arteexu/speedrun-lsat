# Memory Model — one-page description

> Status: TEMPLATE. Fill the bracketed values with real numbers from held-out evaluation before hand-in.

## Question it answers

Can the student recall a **taught fact** right now? On the LSAT this is deliberately a _small_ part of the system (SPOV / BrainLift "Out of Scope"): flaw and trap **definitions**, conditional-logic terminology, RC vocabulary. Memory is supporting, not foundational.

## Method

Anki's built-in **FSRS** scheduler estimates recall probability per card from review history. We consume FSRS's retrievability estimate directly; we do not modify the memory algorithm.

- Input: per-card review history (grades + timing) maintained by `rslib`.
- Output: P(recall) per card, aggregated per schema and overall, reported **with a range** (not a bare point).

**Implementation.** Per-card retrievability is read straight from the engine via
the `extract_fsrs_retrievability` SQL function (no FSRS reimplementation). Cards
carry their schema as an `sr:schema:` note tag. Aggregation, the range, and the
give-up rule live in [`speedrun/scoring/memory.py`](../../../../speedrun/scoring/memory.py);
the range is a normal-approximation CI on the mean of per-card recall
probabilities, clamped to [0, 1]. Cards with no FSRS memory yet (unreviewed) are
excluded from the estimate but counted in coverage.

## Honest reporting

- Point estimate: `[p]`
- Likely range: `[low–high]` (method: `[e.g., Wilson interval / posterior band]`)
- Coverage: `[% of memory-eligible schemas with ≥ N reviews]`
- Confidence indicator: `[low/med/high + why]`
- Last updated: `[timestamp]`
- Top reasons: `[e.g., few reviews on conditional-logic terms]`

## Give-up rule

Show **no** memory score until enough cards have been reviewed. Implemented
defaults (tunable in `speedrun/scoring/memory.py`): **overall ≥ 5** reviewed
cards; **per schema ≥ 2** reviewed cards. Below the line the score abstains and
names exactly what is missing (e.g., "Not enough data: 1 reviewed card < required
2"). These low seed-stage defaults will be raised as the deck grows.

## Calibration (held-out)

Calibrate on reviews held out of fitting. When the model says 80%, observed recall should be ≈80%.

- Reliability chart: `[path to figure]`
- Brier score: `[value]` (lower is better)
- Log loss: `[value]`
- Held-out set size: `[n reviews]`, split method: `[seeded, re-runnable]`

## Re-runnability

Report the current memory score for any collection:

```bash
python speedrun/tools/memory_report.py --col /path/to/collection.anki2        # or --base <ANKI_BASE>
python speedrun/tools/memory_report.py --col ... --json
```

Tests (`pylib/tests/test_speedrun_memory.py`) cover the importer, the abstain
path (no reviews), and a real score after FSRS reviews. Calibration on a held-out
split (`just eval-memory`, Brier/log-loss + reliability chart) is future work,
tracked in the eval/ship phase.

## Known limitations

- FSRS estimates memory, not transfer; a high memory score does **not** imply LSAT performance (that gap is the whole point — see the performance model).
- `[other limitations found during eval]`
