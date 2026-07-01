# Speedrun LSAT — Results Report

Generated from automated tests on 2026-07-01. Numbers are from the seed deck
(11 cards) and synthetic/simulated harnesses unless noted.

## Test suite

```
PYTHONPATH=out/pylib out/pyenv/bin/python -m pytest pylib/tests/test_speedrun_*.py -q
35 passed
```

| Module       | Tests |
| ------------ | ----- |
| memory       | 6     |
| performance  | 5     |
| readiness    | 4     |
| dashboard    | 5     |
| transfer gap | 3     |
| interleaving | 3     |
| calibration  | 2     |
| AI (AI_OFF)  | 7     |

## Three scores (seed deck, 11 reviews)

After importing seed deck and answering all cards Good:

| Score       | Result                           | Notes                                  |
| ----------- | -------------------------------- | -------------------------------------- |
| Memory      | ~100% recall (range reported)    | FSRS via `extract_fsrs_retrievability` |
| Performance | ~93% transfer (latency-adjusted) | Revlog-based; Wilson interval          |
| Readiness   | Abstains at default thresholds   | Needs ≥200 attempts + ≥50% coverage    |

With lowered thresholds (test mode: 10 attempts, 1% coverage): readiness computes
a projected LSAT in 120–180 range with confidence `low`.

## Transfer gap (spec 7d)

Synthetic harness with 15% transfer penalty on reworded variants:

- Recall (FSRS) > Transfer (reworded) — gap positive
- Bridge marked distinct from memory when gap ≥ 5%

Real reworded grading (human or AI) not yet wired; proxy uses revlog attempts.

## Interleaving experiment (spec 8)

Synthetic 3-build comparison (n=120 items, seed=42):

- Pre-registered hypothesis documented in code
- Reports effect size (full − ablation) and null results honestly
- Run: `python -c "from speedrun.eval.interleaving_experiment import run_experiment; print(run_experiment().format_report())"`

## Memory calibration (spec 9)

After 11 reviews: Brier score and log loss computed on schema-tagged revlog rows.
Insufficient data for reliable calibration chart at production scale — abstains below
10 held-out reviews without seed-deck study session.

## AI evaluation (spec 7f, AI_OFF=1)

| Check               | Result                                        |
| ------------------- | --------------------------------------------- |
| Gold set            | 50 Q&A pairs in `speedrun/data/gold_set.json` |
| Card checker cutoff | 0.35 (pre-set)                                |
| Seed deck check     | 11 items checked                              |
| Leakage check       | Clean at threshold 0.9                        |
| Offline scoring     | All three scores run with AI disabled         |

## Benchmarks (spec 7g)

Seed deck + 11 reviews, 20 iterations each:

| Action            | p50     | p95     | worst   |
| ----------------- | ------- | ------- | ------- |
| memory_score      | 0.0001s | 0.0002s | 0.0002s |
| performance_score | 0.0001s | 0.0001s | 0.0001s |
| readiness_score   | 0.0002s | 0.0003s | 0.0003s |
| ordered_cards     | 0.0006s | 0.0010s | 0.0010s |
| render_dashboard  | 0.0010s | 0.0012s | 0.0012s |

Run: `just bench`

## Reliability scripts

| Script                           | Result                                   |
| -------------------------------- | ---------------------------------------- |
| `speedrun/tools/crash_test.py`   | 5 reviews persist after close/reopen     |
| `speedrun/tools/offline_test.py` | Scores produced with `SPEEDRUN_AI_OFF=1` |

## iOS engine

| Check                | Result                                              |
| -------------------- | --------------------------------------------------- |
| XCFramework build    | OK (`ios/AnkiFFI.xcframework`)                      |
| rslib-ffi host tests | 2 passed (C boundary + buildHash)                   |
| Simulator Swift test | `AnkiKitTests.testBuildHashNonEmpty` — run in Xcode |

## Known gaps (honest)

1. Readiness give-up at production thresholds — insufficient seed-deck data.
2. Transfer gap uses synthetic reworded variants until real paraphrase grading ships.
3. Interleaving experiment uses synthetic learners, not human subjects.
4. AI LLM path stubbed — keyword baseline only until API keys provided.
5. Two-way sync not implemented — conflict rule documented only.
6. iOS review session + dashboard not built — engine loads, hash smoke test only.
