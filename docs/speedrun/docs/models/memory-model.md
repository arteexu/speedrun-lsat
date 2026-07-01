# Memory Model — one-page description

> Status: TEMPLATE. Fill the bracketed values with real numbers from held-out evaluation before hand-in.

## Question it answers
Can the student recall a **taught fact** right now? On the LSAT this is deliberately a *small* part of the system (SPOV / BrainLift "Out of Scope"): flaw and trap **definitions**, conditional-logic terminology, RC vocabulary. Memory is supporting, not foundational.

## Method
Anki's built-in **FSRS** scheduler estimates recall probability per card from review history. We consume FSRS's retrievability estimate directly; we do not modify the memory algorithm.

- Input: per-card review history (grades + timing) maintained by `rslib`.
- Output: P(recall) per card, aggregated per schema and overall, reported **with a range** (not a bare point).

## Honest reporting
- Point estimate: `[p]`
- Likely range: `[low–high]` (method: `[e.g., Wilson interval / posterior band]`)
- Coverage: `[% of memory-eligible schemas with ≥ N reviews]`
- Confidence indicator: `[low/med/high + why]`
- Last updated: `[timestamp]`
- Top reasons: `[e.g., few reviews on conditional-logic terms]`

## Give-up rule
Show **no** per-schema memory score until that schema has `[≥ N]` graded reviews. Below the line, show "not enough data" and name the gap.

## Calibration (held-out)
Calibrate on reviews held out of fitting. When the model says 80%, observed recall should be ≈80%.

- Reliability chart: `[path to figure]`
- Brier score: `[value]` (lower is better)
- Log loss: `[value]`
- Held-out set size: `[n reviews]`, split method: `[seeded, re-runnable]`

## Re-runnability
Command: `[just eval-memory]` — loads the seeded held-out split and regenerates the chart + scores deterministically.

## Known limitations
- FSRS estimates memory, not transfer; a high memory score does **not** imply LSAT performance (that gap is the whole point — see the performance model).
- `[other limitations found during eval]`
