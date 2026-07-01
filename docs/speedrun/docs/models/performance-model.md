# Performance Model — one-page description

> Status: TEMPLATE. Fill the bracketed values with real numbers from held-out evaluation before hand-in.

## Question it answers

Can the student get a **new, exam-style item right** — including items they have never seen — using a given schema? This is the **memory → transfer bridge**, the core of the app (BrainLift SPOV1). It must **not** simply echo FSRS memory.

## Method

A per-schema model predicting P(correct) on a novel item, from:

- **Schema mastery** — running transfer estimate for the item's schema(s) (primary: flaw).
- **Item difficulty** — calibrated difficulty of the item.
- **Latency** — response time, treated as co-equal with correctness (SPOV4): correct-but-over-budget is discounted.
- **Coverage** — whether the student has enough exposure across the schema to generalize.

Model form: `[e.g., logistic regression / IRT-style / hierarchical per-schema]`. Habitual **trap type** (`chosen_trap_type` on attempts) is an input/diagnostic for which distractors the student falls for (Insight 8).

## Honest reporting

- Point estimate (overall + per schema): `[p]`
- Likely range: `[low–high]`
- Coverage: `[% schemas with ≥ N transfer attempts]`
- Confidence: `[low/med/high + why]`
- Last updated: `[timestamp]`
- Top reasons / weakest schema: `[e.g., necessary-assumption]`

## Give-up rule

No per-schema performance estimate until `[≥ N]` graded **transfer** attempts on that schema. Overall performance abstains below `[coverage X%]`.

## Validation — the paraphrase / transfer test (spec 7d)

Take 30 cards; for each write 2 exam-style questions testing the same schema in new words. Compare recall on the card vs accuracy on the reworded questions.

- Recall (card): `[%]`
- Transfer accuracy (reworded): `[%]`
- **Gap (recall − transfer): `[Δ]`** — a near-zero gap means the model is just copying memory; a real gap means the bridge exists.
- Held-out accuracy on exam-style items: `[%]` (set size `[n]`, seeded split)

## Re-runnability

Command: `[just eval-performance]` — regenerates the transfer-gap report and held-out accuracy deterministically.

## Known limitations

- `[e.g., sparse data on low-frequency schemas widens ranges]`
- `[latency normalization assumptions]`
