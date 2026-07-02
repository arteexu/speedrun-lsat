# Speedrun LSAT — Test Results

Honest numbers from the re-runnable harnesses (seed deck, 11 cards). Run on
2026-07-01 against commit on branch `speedrun-lsat`.

## Unit tests

```bash
PYTHONPATH=out/pylib out/pyenv/bin/python -m pytest pylib/tests/test_speedrun_*.py -q
```

**Result: 35 passed in ~0.3s**

| Suite             | Tests |
| ----------------- | ----- |
| memory + importer | 6     |
| performance       | 5     |
| readiness         | 4     |
| dashboard + queue | 5     |
| transfer gap (7d) | 3     |
| interleaving (8)  | 3     |
| calibration (9)   | 2     |
| AI + leakage (7f) | 7     |

## Rust engine

```bash
cargo test -p rslib -- speedrun::schema_weighted_queue
cargo test -p rslib-ffi
```

- `rslib`: schema-weighted queue unit tests pass (see `rslib/src/scheduler/queue/schema_weighted.rs`).
- `rslib-ffi`: 2 host tests pass (C boundary + `buildHash`).

## Benchmarks (seed deck, not 50k)

```bash
just bench
```

| Action            | p50     | p95     | worst   |
| ----------------- | ------- | ------- | ------- |
| memory_score      | 0.0001s | 0.0002s | 0.0002s |
| performance_score | 0.0001s | 0.0001s | 0.0001s |
| readiness_score   | 0.0002s | 0.0003s | 0.0003s |
| ordered_cards     | 0.0006s | 0.0011s | 0.0011s |
| render_dashboard  | 0.0009s | 0.0015s | 0.0015s |

**Note:** Targets in PRD §18 are measured on a 50k-card deck; seed-deck numbers
are much faster. Full 50k benchmark is not yet run.

## Transfer gap (spec 7d)

After reviewing all 11 seed cards (synthetic reworded penalty 0.15):

| Metric              | Value            |
| ------------------- | ---------------- |
| Recall (FSRS)       | 100% [100%–100%] |
| Transfer (reworded) | 54% [35%–73%]    |
| Gap                 | +46%             |
| Bridge distinct     | Yes              |

Without reviews, the report abstains honestly.

## Interleaving experiment (spec 8)

Pre-registered hypothesis: interleaving beats blocked practice on mixed-schema
transfer at equal study time.

Synthetic simulation (n=200, seed=99):

| Build              | Study acc | Transfer acc | Hard acc |
| ------------------ | --------- | ------------ | -------- |
| full (interleave)  | 68%       | 62%          | 57%      |
| ablation (blocked) | 69%       | 56%          | 47%      |
| plain (random)     | 68%       | 54%          | 47%      |

Effect (full − ablation transfer): **+6.5%**. Winner: full. **Not a null result**
on synthetic data — human-subject replication still needed.

## Memory calibration (spec 9)

After all seed reviews (min held-out=5):

| Metric     | Value  |
| ---------- | ------ |
| Brier      | 0.0000 |
| Log loss   | 0.0000 |
| Held-out n | 22     |

Perfect calibration on this tiny deck is expected (all Good answers); not
representative of production scale.

## AI card check (spec 7f, AI_OFF=true)

Gold set: 50 held-out Q&A pairs. Seed deck checker (keyword baseline, cutoff 0.35):

| Metric                    | Value |
| ------------------------- | ----- |
| Checked                   | 11    |
| Passed                    | 0     |
| Wrong                     | 8     |
| Correct but weak teaching | 3     |

**Honest finding:** seed deck items do not overlap the gold set by design; checker
correctly flags them. Real LLM generation not wired (API key required).

## Leakage check (7e)

Threshold 0.9: **clean** (no near-duplicates between gold set and seed deck).

## Reliability (spec 7g)

```bash
PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/crash_test.py
PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/offline_test.py
```

- **Crash test:** 5 mid-review closes → reopen same collection → card count and
  revlog unchanged. (Single simulated crash, not 20×.)
- **Offline test:** `SPEEDRUN_AI_OFF=1` → memory 100%, performance 93%, readiness
  computes with lowered thresholds.

## AI (checked, off-switchable)

See [ai.md](ai.md) for the full note. AI is off by default; the three scores
never import `speedrun.ai` (`test_three_scores_compute_with_ai_off`).

```bash
# baseline-only (AI off): honest gate failure
PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/speedrun_cli.py ai-eval
# real numbers (needs a key):
SPEEDRUN_AI_OFF=0 OPENAI_API_KEY=sk-... PYTHONPATH=out/pylib \
  out/pyenv/bin/python speedrun/tools/speedrun_cli.py ai-eval
```

- Held-out eval (10 test / 40 corpus, 50-item gold set) reports per-method
  **accuracy** and **wrong-answer rate** vs a pre-set cutoff; side-by-side AI vs
  keyword vs TF-IDF vector.
- With AI off, baselines score (keyword ~10%, vector ~20%) and the AI gate fails
  honestly (0%). Real AI numbers to be recorded here after a live key run.
- Card generation is gated by `block_failing` (cutoff 0.35) with an optional LLM
  correctness veto; every AI output carries a named `source`.
- 21 AI unit tests pass fully offline (scripted client, no network).

## Shared scores RPC (desktop + phone)

- `ComputeSpeedrunScores` (scheduler service 13, method 40) computes memory /
  performance / readiness in Rust; 8 Rust unit tests pass.
- Python<->Rust **parity** verified on the exam deck
  (`pylib/tests/test_speedrun_scores_rpc.py`, 4 tests) - the phone and desktop
  get identical scores from one implementation.
- Phone renders the three scores via this RPC (AnkiKit `testComputeScores...`).

## Two-way sync

```bash
PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/sync_test.py
```

- Two collections against a live self-hosted server: reviews from both land
  exactly once (6 each, then 10 each), no cards duplicated. **No lost or
  double-counted reviews.**
- iOS sync client verified against the running server on the simulator
  (`testSyncAgainstLocalServerIfAvailable`): real login + full-upload round-trip.
- Conflict semantics documented in [SYNC.md](SYNC.md) (Anki USN+mtime merge).
- Phone->desktop demo steps: [SYNC-SERVER.md](SYNC-SERVER.md) (recording is
  human-captured: review on phone -> Sync -> Sync desktop -> review appears).

## iOS engine

```bash
bash ios/build-xcframework.sh
bash ios/run-tests.sh
```

- XCFramework builds (~166 MB artifact, gitignored; rebuild locally).
- Host `rslib-ffi` tests pass; AnkiKit simulator tests pass (deck load,
  schema-weighted queue, card content, three scores, sync).

## Not yet measured

- 50k-card benchmark (PRD §18 p95 targets)
- 20× crash test per platform
- Real LLM eval numbers (harness + gate ready; run `ai-eval` with a key)
- On-device FSRS grading on the phone (`answer_card`; needs nested-state protos)
- Human interleaving study
- Clean-machine installer recording
- TestFlight / signed iOS build
