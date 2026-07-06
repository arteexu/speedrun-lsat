# Speedrun LSAT — Test Replicability Audit

Meta-audit of every PRD-required test/eval/benchmark for **replicability**: can a
third party run one documented command and get the same result? Ran 2026-07-05.
Honesty rule: specific tasks, real numbers, no hiding.

Environment for every command below (from repo root, `~/dev/speedrun-lsat`):

```bash
# out/pylib + out/pyenv/bin/python exist. AI unset => deterministic/offline.
unset SPEEDRUN_AI_SETTINGS_PATH
```

Tasks **7a (Rust queue), 7b (sync), 7c (coverage map), 7d (paraphrase/transfer),
7e (leakage), 7f (AI card check), 7g (crash+offline), 7h (50k bench)** are covered
by the parallel 7a–7h audit; artifacts confirmed present, not re-audited here.

---

## Headline suite (deterministic)

```bash
unset SPEEDRUN_AI_SETTINGS_PATH
PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python -m pytest pylib/tests/ -k "speedrun or schema" -q
```

**396 passed · 2 failed · 1 skipped · 121 deselected (~44 s).**

- The 2 failures are the **known local-only demo-seed artifact**:
  `test_default_thresholds_present_and_valid` and
  `test_dashboard_gate_stays_locked_after_seed_pass`. A seeded demo profile relaxed
  the working-tree `speedrun/config.json` to `min_pattern_coverage: 0.73` (tests
  demand ≥0.80). Committed config is clean; not a real regression.
- 1 skip: `aqt not importable in this environment` (GUI-only dashboard test).

---

## Replicability matrix

| # | Test | PRD § | Exact command | Det/seeded | In CI | Result / number | Status | Notes |
|---|------|-------|---------------|:---------:|:-----:|-----------------|--------|-------|
| 1 | Memory calibration (Brier/log-loss, held-out) | §10.1 / §17 | `pytest pylib/tests/test_speedrun_calibration.py` | Y (seed-free temporal split, later 30%) | N (only in full local suite) | 4/4 pass. Seed deck: n_total=1008, train=706, **held-out=302**, **Brier=0.0**, **log-loss≈1e-15** | partial | Machinery is a real held-out temporal split + deterministic. **Numbers are degenerate** (seed harness answers every card Good → all outcomes=1, FSRS≈1 → perfect). No standalone CLI. |
| 2 | Performance accuracy on held-out exam-style items | §10.2 / §17 | `pytest pylib/tests/test_speedrun_performance.py` | Y | N | 5/5 pass (Wilson interval, latency penalty, give-up) | partial | The PRD's held-out validation for §10.2 **is the paraphrase/transfer test = 7d** (`speedrun/eval/transfer_gap.py`, owned by parallel worker). These unit tests validate model math on **synthetic all-correct** data, not real held-out items. |
| 3a | AI held-out eval — offline/generative | §14.3 | `python -m speedrun.eval.ai_eval` | Y (deterministic) | partial (AI *unit* subset only) | AI **stub 0%**, keyword 10%, vector 20%, cutoff 0.6, leakage clean → **GATE FAILED (honest)** | satisfied (as honest-fail) | Offline generative path can't beat baselines because AI is a stub with no key. Deterministic + CI-safe but proves nothing about the model. |
| 3b | AI held-out eval — offline/grounded | §14.3 | `python -m speedrun.eval.grounding_eval` | **Y (identical across 2 runs)** | N | **grounded 50% / wrong 50%**, keyword 30%, vector 30%, cutoff 0.4 → **beats both, GATE PASSED (exit 0)**; 10 test / 40 corpus / 57 source | satisfied | This is the deterministic/CI-safe "AI beats keyword+vector" story. |
| 3c | AI held-out eval — live LLM judge | §14.3 | `SPEEDRUN_AI_SETTINGS_PATH=$PWD/.ankidata/speedrun_ai_settings.json python -m speedrun.eval.ai_eval` | **N (LLM judge nondeterministic)** | N | Per RESULTS.md live run: fair-acc **AI 80%** vs keyword 20% / vector 30%, wrong-rate 20%, cutoff 0.6, leakage clean → PASSED | partial | **Not run in this audit (no key set).** Requires live key; run-to-run variance; not third-party reproducible without the key + tolerance for variance. |
| 4 | Source traceability (`require_source`) | §14.3 | `pytest pylib/tests/test_speedrun_ai.py -k "source or require_source"` | Y | Y (AI job) | **5 passed** | satisfied | Every AI output names a source; `require_source` enforced at tutor/recommender/generator call sites. |
| 5 | Prompt-injection defense | §14.1 | `pytest pylib/tests/ -k "injection or sanitiz"` | Y | Y (AI job) | **5 passed** | satisfied | Source text cannot alter generation policy; sanitization tested. |
| 6 | Reasoning evaluator (why runner-up wrong + weakness patterns) | §14.2 | `pytest pylib/tests/test_speedrun_trap_and_reasoning.py` | Y | partial | **8 passed** | satisfied | Grades the two-answer-fork explanation and surfaces recurring weakness. |
| 7 | AI off-switch → all three scores still render | §14.3 / §16 | `pytest pylib/tests/test_speedrun_ai.py -k "three_scores_compute_with_ai_off"` | Y | N (excluded in CI: needs anki build) | 1 pass (+38 in off/disable/degrade filter) | satisfied | `SPEEDRUN_AI_OFF=1` → `ai_enabled()==False`; memory + performance don't give up, readiness computes without error; scoring modules never import `speedrun.ai`. |
| 8 | Interleaving 3-build experiment | §15 | `python -m speedrun.eval.interleaving_experiment` | **Y (master seed 42, 20 seeds; identical across runs)** | N | **interleaved−blocked = +10.3% 95%CI [+8.5%,+12.0%]** (winner interleaved, null=False); **app vs plain-Anki = +0.2% 95%CI [−0.5%,+0.9%] (null=True, honest)** | satisfied | Three arms (interleaved / blocked ablation / plain Anki + schema_weighted), equal study time, pre-registered hypothesis, reports range + honest null. Also `pytest test_speedrun_interleaving.py`. |
| 9 | Give-up / readiness Python↔Rust parity | §10.3 | `pytest pylib/tests/ -k "readiness or guardrail"` + `pytest pylib/tests/test_speedrun_scores_rpc.py` | Y | Rust side yes (`cargo test speedrun_scores`); Python side N | readiness/guardrail **16 passed** (+1 known demo-seed fail); parity RPC **4/4 passed** | satisfied | Enforced thresholds: **MIN_ATTEMPTS=200, MIN_COVERAGE=0.50 per section (LR & RC), MIN_DECK_COVERAGE=0.50**. Python (`readiness.py`) ↔ Rust (`speedrun_scores.rs`) agree via service 13 / method 40. |
| 10a | Sync of a normal session < 5 s | §18 | `python speedrun/tools/sync_test.py` | — | N | Correctness only (no lost/double-count + conflict rule) | **gap** | **No `< 5 s` assertion anywhere.** Timing is external/manual. |
| 10b | Memory ceiling on 50k | §18 | `just bench` (`_peak_rss_mb`) | Y | N | Deferred to 7h | external/deferred | Desktop measurable via bench; **mid-range phone = device-only/external**. |
| 10c | Cold start < 5 s desktop | §18 | `just bench` (`cold_start`, target 5.0 s) | Y | N | Deferred to 7h | external/deferred | bench opens the 50k collection and grades PASS/FAIL. **Phone < 4 s = device-only/external.** (`test_speedrun_cold_open.py` is an unrelated study feature, not app cold-start.) |
| 10d | Nothing freezes UI > 100 ms | §18 | `just bench` (`next_card` p95<100ms, `dashboard_refresh` p95<500ms) | Y | N | Deferred to 7h | partial/external | Desktop proxied by per-action p95; a true "UI thread never blocks" claim is device/UX-level, **phone = external**. |
| 11 | Replicability META (CI + docs + seeds) | §17 | see below | mixed | partial | `.github/workflows/speedrun-tests.yml` exists | partial | See gaps. |

---

## Determinism / seeding summary

- **Deterministic & seed-free/seeded (third-party reproducible):** calibration
  (temporal split, no RNG), grounding_eval (byte-identical across runs),
  interleaving_experiment (master seed 42), offline ai_eval, all pytest suites.
- **NOT reproducible by a third party:**
  - **Live AI eval (3c)** — needs a private OpenAI key AND the LLM judge is
    nondeterministic (run-to-run variance). RESULTS.md captures a passing run but
    a fresh run may differ. The **deterministic substitute is grounding_eval (3b)**.
  - **50k bench (7h)** — needs a full local Anki build; not in CI.
  - **Human interleaving study, clean-machine install, phone recordings** — manual.

## CI coverage (`.github/workflows/speedrun-tests.yml`)

Runs on push/PR: `cargo test -p anki schema_weighted`, `cargo test -p anki
speedrun_scores`, `cargo test -p rslib-ffi`, and a **stdlib-only subset** of
`test_speedrun_ai.py` (`SPEEDRUN_AI_OFF=1`, excludes `compute_with_ai_off`).

**NOT in CI** (documented as "run locally"): the full Python speedrun suite,
calibration, performance, readiness/guardrail, dashboard, grounding_eval,
interleaving_experiment, ai_eval, and `just bench`. A one-command local
reproduce exists — `tools/verify-speedrun-checklist.sh` — but it is not wired
into GitHub Actions and does not invoke the eval CLIs.

---

## Gaps needing remediation (report only — not fixed here)

1. **CI under-covers the evals (replicability risk).** CI runs Rust + an AI unit
   subset only. Add jobs that run, at minimum: `grounding_eval` (deterministic
   AI-beats-baseline gate), `interleaving_experiment`, and the full Python
   speedrun suite (calibration / performance / readiness / dashboard). These are
   already deterministic; only the CI wiring is missing. *(doc/CI change)*
2. **`docs/speedrun/RESULTS.md` is stale.** It reports "35 passed" (now **396**),
   interleaving `seed=99 → +6.5%` (now **seed 42 → +10.3%**), and calibration
   `held-out n=22` (now **302**). A third party following RESULTS.md gets
   different numbers than the current harness. Regenerate it. *(doc change)*
3. **Calibration numbers are degenerate.** Brier=0 / log-loss≈0 come from a seed
   harness that answers every card Good. The held-out mechanism is real, but the
   reported numbers are not representative. Seed some `Again`/failed reviews (or
   ship a mixed-outcome fixture) so calibration reports a non-trivial Brier.
   *(test/fixture change)*
4. **Sync `< 5 s` (§18) is unmeasured.** `sync_test.py` proves correctness but
   asserts no latency. Add a timed assertion for a normal session or explicitly
   document it as external/manual. *(test change)*
5. **§10.2 performance held-out relies on 7d.** The only true held-out validation
   for performance is the paraphrase/transfer test (7d). Confirm 7d lands; the
   local performance unit tests use synthetic all-correct data. *(coordinate w/ 7d)*

## External-only (cannot be automated in this repo)

- Live AI eval numbers (private key + nondeterministic judge).
- Mid-range-phone memory ceiling; phone cold start (<4 s); phone UI-freeze.
- Clean-machine installer recording; phone review recording; TestFlight/signed build.
