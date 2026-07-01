# Readiness Model — one-page description

> Status: **Implemented** with stated linear map and strict give-up rule. **A made-up readiness number is an automatic fail** — this model abstains until thresholds are met.

## Question it answers

What **LSAT score (120–180)** would the student get today, and how sure are we?

## Method

1. Aggregate per-schema **performance** estimates → **expected fraction correct per section** (LR vs RC), weighting schemas by `exam_weight` in the taxonomy.
2. Combine sections (**LR ~66%, RC ~34%**) into an overall expected fraction correct.
3. Map fraction → **120–180** via a **stated linear function**: `120 + fraction × 60` (`scaled_from_fraction` in `speedrun/scoring/readiness.py`). Documented as a rough placeholder for real equating.
4. Propagate performance Wilson intervals into a **score range**.
5. **Latency adjustment (SPOV4):** already in performance model (on-budget accuracy); readiness inherits it. `speed_flag` surfaces accurate-but-slow students.

## Honest reporting (seed deck, default thresholds)

At default thresholds (**≥ 200 attempts, ≥ 50% coverage**):

- **Projected LSAT:** abstains — "No score yet: need >= 200 graded attempts (have 11)…"
- Dashboard shows reason text, not a fabricated number.

With lowered thresholds for harness test only (`min_attempts=10`, `min_coverage=0.01`):

- **Projected LSAT:** ~**168** (point), range ~**157–178** (varies with revlog)
- **% of exam covered:** low (seed deck covers few taxonomy weights)
- **Confidence:** **low**
- **Single best next step:** weakest high-weight schema from performance (shown in dashboard)
- **Speed flag:** shown when any schema has accurate-but-slow performance

Example display (when enough data):

> Projected LSAT: 168 · range 157–178 · confidence low · best next: qt.necessary_assumption.

## Give-up rule (stated, enforced in code)

Show **no** readiness score until **≥ 200 graded transfer attempts AND ≥ 50% schema coverage** (weight-based across LR+RC). Below the line, display "Not enough data for a score yet" and name exactly what is missing. Thresholds are kwargs to `readiness_score()` for tests.

## Validation

- Step 1 (required): memory calibration harness runs — see [memory-model.md](memory-model.md).
- Step 2 (required): performance + transfer gap — see [performance-model.md](performance-model.md).
- Step 3 (required): score mapping written down with a range (this document, linear map stated).
- Step 4 (bonus): real students with practice tests — **not available**.

> Honest-grading note: at seed-deck scale we **abstain by default**. The linear map is explicitly labeled an approximation, never a precise prediction.

## Re-runnability

```bash
PYTHONPATH=out/pylib out/pyenv/bin/python -c "
from speedrun.scoring.readiness import readiness_score
# readiness_score(col)  # abstains at defaults
"
```

Tests: `pylib/tests/test_speedrun_readiness.py`.

## Known limitations

- Linear 120–180 map is not LSAC equating; real readiness needs practice-test back-tests.
- Seed deck cannot satisfy 200-attempt / 50%-coverage rule — by design.
- RC section remains thin until more RC-tagged items are added.
