# Readiness Model — one-page description

> Status: TEMPLATE. Fill the bracketed values with real numbers before hand-in. **A made-up readiness number is an automatic fail** — this model exists to be honest, including abstaining.

## Question it answers
What **LSAT score (120–180)** would the student get today, and how sure are we?

## Method
1. Aggregate per-schema **performance** estimates → **expected raw correct per scored section** (two LR, one RC), weighting schemas by their frequency on the exam.
2. Map expected raw correct across the three scored sections → the **120–180** scale via a stated equating/linear function: `[function + source/assumptions]`.
3. Propagate uncertainty (from per-schema ranges + coverage) into a **score range**.
4. **Latency adjustment (SPOV4):** discount correct-but-over-budget responses, because in aggregate a slow correct answer trades away points elsewhere. Flag the accurate-but-slow student rather than rewarding them.

## Honest reporting (all shown together)
- **Projected LSAT:** `[point]`
- **Likely range:** `[low–high]`
- **% of exam covered:** `[coverage %]`
- **Confidence:** `[low/med/high + the reason, e.g., low coverage / thin RC data]`
- **Last updated:** `[timestamp]`
- **Main reasons:** `[drivers of the estimate]`
- **Single best next step:** `[weakest high-weight schema to drill]`
- **Speed flag:** `[shown if accurate-but-slow]`

Example display:
> Projected LSAT: 161 · range 157–165 · confidence low (38% covered, RC thin) · best next: necessary-assumption.

## Give-up rule (stated, enforced in code)
Show **no** readiness score until **≥ 200 graded transfer attempts AND ≥ 50% schema coverage across both LR and RC**. Below the line, display "Not enough data for a score yet" and name exactly what is missing. (Thresholds configurable; defaults stated so the rule is falsifiable.)

## Validation
- Step 1 (required): memory calibrated — see [memory-model.md](memory-model.md).
- Step 2 (required): performance predicts held-out exam-style items — see [performance-model.md](performance-model.md).
- Step 3 (required): score mapping written down with a range (this document).
- Step 4 (bonus): check against real students with both study history and practice-test scores — `[if available]`.

> Honest-grading note: "we calibrated memory but lack data to prove the projected score" scores higher than a polished score we cannot back up. State clearly what is and is not yet validated.

## Re-runnability
Command: `[just eval-readiness]` — regenerates the mapping, range, and any back-test deterministically from seeded data.

## Known limitations
- A true score model needs students studying then taking real practice tests over time; we grade the **steps of the bridge**, not a fabricated final number.
- `[equating-function assumptions; small-sample sections]`
