# Speedrun LSAT — Feature → BrainLift / PRD Traceability

This document maps **every implemented Speedrun feature** back to its origin:
either a BrainLift **Spiky POV (SPOV)** / **Insight**, or a **PRD** requirement
section. It is the printable companion to the interactive traceability canvas.

**Sources**
- Product requirements: [`docs/speedrun/PRD.md`](PRD.md) (mirror of the workspace `PRD.md`).
- Learning science: *LSAT Speedrun Brainlift* (SPOV 1–4, Insights 1–10).
- Implementation: this repository (`~/dev/speedrun-lsat`).

**The through-line.** The BrainLift's four Spiky POVs are the spine; the PRD
turns them into binding requirements; the code implements them.

- **SPOV 1** — the LSAT is a *transfer* problem → the **schema** is the unit of
  mastery (engine + data model + scores key to schema, not card).
- **SPOV 2** — mastery starts with **flaws, then traps**, not question type
  (flaw-primary taxonomy + trap diagnostics).
- **SPOV 3** — scaffolding fades **hardest-step-last**; the two-answer fork is
  the terminal scaffold (fork trainer + adaptive fading ladder).
- **SPOV 4** — **speed is co-equal** with accuracy (latency is first-class
  everywhere).

**The honesty discipline.** Cold-open, contrasting-pairs, fork, and calibration
grades are self-driven *training signal* and are deliberately **excluded** from
the Memory / Performance / Readiness scores (enforced in code + unit-tested).
Only graded transfer from the Anki revlog feeds the scores.

---

## 1. The four Spiky POVs → features

### SPOV 1 — The LSAT is a transfer problem; the schema is the unit of mastery
> Every LR item is surface-unique, so the only thing that transfers is deep
> structure. The data model, study queue, and scores must all key to schema
> mastery, not card retention. The key metric is the recall-vs-transfer gap.

| Feature | File | Insight | PRD |
| --- | --- | --- | --- |
| Schema-weighted "points-at-stake" queue (Rust) | `rslib/src/scheduler/schema_weighted.rs` | I1 | §9 |
| Schema-centric data model (card = instance) | `speedrun/data/seed_deck.json` | I1 | §8.2 |
| Transfer-gap report (recall vs transfer) | `speedrun/eval/transfer_gap.py` | I1 | §10.2, §17 |
| Performance score (memory→transfer bridge) | `speedrun/scoring/performance.py` | I1 | §10.2 |
| Contrasting-pairs drill | `speedrun/contrasting.py` | I3 | §15 |
| Predict-the-schema cold-open | `speedrun/cold_open.py` | I1, I2 | §8.2 |
| Concept map (traversable mastery graph) | `speedrun/concept_graph.py` | I1 | §8.2 |

### SPOV 2 — Mastery starts with flaws, then traps, not question type
> Flaw is the primary organizing/diagnostic axis; question-type is secondary.
> Distractors are systematic, so "why wrong" is a learnable schema, and the
> habitual trap a student falls for is the high-value diagnostic signal.

| Feature | File | Insight | PRD |
| --- | --- | --- | --- |
| Flaw-primary schema taxonomy | `speedrun/taxonomy/lsat_taxonomy.json` | I2 | §8.1 |
| Per-choice trap tagging | `speedrun/data/seed_deck.json` | I8 | §8.1 |
| Mistake correlation graph | `speedrun/mistake_graph.py` | I8 | §8.2 |
| Confusion-pair interleaving | `speedrun/confusion.py` | I4, I8 | §15 |
| Conditional-logic visualizer | `speedrun/logic_diagram.py` | I2 | §8.1 |
| Deterministic explanations (no AI) | `speedrun/explanations.py` | I8, I9 | §11 |
| Reasoning evaluator (AI, grounded) | `speedrun/ai/reasoning_evaluator.py` | I5 | §14.2 |

### SPOV 3 — Scaffolding fades slowly; the two-answer fork fades last
> Fade in order of step difficulty (hardest-last). The two-answer fork is the
> terminal scaffold, replaced by speed pressure at ≈90% fork accuracy rather
> than removed outright — reconciling the expertise-reversal effect.

| Feature | File | Insight | PRD |
| --- | --- | --- | --- |
| Two-answer fork trainer (rationale always shown) | `speedrun/fork_trainer.py` | I6 | §11, §14.2 |
| Mastery ladder / adaptive fading | `speedrun/fading.py` | I7, New Insight | §11 |
| Adaptive-fading design note | `docs/speedrun/adaptive-fading.md` | I7 | §11 |

### SPOV 4 — Speed is co-equal with accuracy
> Accuracy without latency is a vanity metric on a timed test. A correct-but-slow
> answer is, in aggregate, a wrong answer. The readiness model jointly models
> latency and flags the accurate-but-slow student.

| Feature | File | Insight | PRD |
| --- | --- | --- | --- |
| Latency-adjusted performance score | `speedrun/scoring/performance.py` | I10 | §10.2 |
| Readiness discounts slow-but-correct | `speedrun/scoring/readiness.py` | I10 | §10.3 |
| Queue `time_pressure_factor` input | `speedrun/scoring/queue.py` | I10 | §9.1 |
| Fork trainer runs on the section clock | `speedrun/fork_trainer.py` | I10 | §11 |
| Post-review latency/budget toast | `qt/aqt/speedrun/reviewer.py` | I10 | §11 |

---

## 2. The three scores + the honesty rule

| Feature | File | Origin | PRD |
| --- | --- | --- | --- |
| Memory score (FSRS recall — supporting, not foundational) | `speedrun/scoring/memory.py` | BrainLift: "memory-model as centerpiece" is out of scope | §10.1 |
| Performance score (transfer bridge) | `speedrun/scoring/performance.py` | SPOV 1 + SPOV 4 | §10.2 |
| Readiness score (120–180 projection, with range) | `speedrun/scoring/readiness.py` | SPOV 4 | §10.3 |
| Shared Rust score math (desktop/iOS parity) | `rslib/src/scheduler/speedrun_scores.rs` | PRD shared-engine rule | §6, §10 |
| Evidence gate / give-up rule | `speedrun/scoring/guardrail.py` | Honesty rule; Karpicke (confidence ≠ retention) | §1, §10.3 |
| Confidence calibration | `speedrun/confidence_calibration.py` | I5; honesty rule | §1, §10 |
| FSRS memory calibration eval | `speedrun/eval/calibration.py` | Held-out validation | §10.1, §17 |

**Give-up rule (PRD §10.3, enforced in `guardrail.py`):** no readiness score
until enough graded transfer attempts and schema coverage exist. Below the line
the app shows *no* score and names the missing data. Making up a readiness
number is an automatic fail (PRD §19).

---

## 3. Schema taxonomy, data model, coverage

| Feature | File | Origin | PRD |
| --- | --- | --- | --- |
| Four-axis schema taxonomy (flaw-primary) | `speedrun/taxonomy/lsat_taxonomy.json` | SPOV 2, I2 | §8.1 |
| Taxonomy methodology | `speedrun/taxonomy/methodology.md` | SPOV 2 | §8.1 |
| Friendly schema/tag labels | `speedrun/taxonomy/labels.py` | UX / clean product | §11 |
| Seed deck (original, license-clean items) | `speedrun/data/seed_deck.json` | SPOV 1, I1 | §8.2 |
| Seed importer + friendly-tag backfill | `speedrun/tools/import_seed_deck.py` | Data model | §8.2 |
| Coverage map (give-up precondition) | `speedrun/tools/coverage_map.py` | Honesty rule | §8.3 |
| Coverage-gap report (next-item suggestions) | `speedrun/coverage_gap.py` | SPOV 1 | §8.3 |
| Add / expand practice items | `speedrun/tools/add_practice_items.py`, `speedrun/tools/expand_seed_deck.py` | SPOV 1 depth (I3) | §8.2 |

---

## 4. AI subsystem (sourced, evaluated, switch-off-able)

| Feature | File | Origin | PRD |
| --- | --- | --- | --- |
| Global AI off-switch (default off) | `speedrun/ai/config.py` | PRD: runs with AI off | §14, §11 |
| Pluggable LLM client (named source) | `speedrun/ai/client.py` | Source traceability | §14 |
| Named-source enforcement + injection guard | `speedrun/ai/guard.py` | Prompt-injection defense | §14.1 |
| Card generator (from one real source) | `speedrun/ai/card_generator.py` | Sourced generation | §14.1 |
| Card checker (pre-set cutoff, block failing) | `speedrun/ai/card_checker.py` | Gold-set gate | §14.1 |
| Reasoning evaluator (grounded to fork rationale) | `speedrun/ai/reasoning_evaluator.py` | SPOV 2; I5 (retrieval) | §14.2 |
| Keyword/vector baselines | `speedrun/ai/baseline.py` | Beat-a-baseline | §14.3 |
| AI eval harness (held-out, cutoff) | `speedrun/eval/ai_eval.py` | Held-out eval | §14.3, §17 |
| Leakage check | `speedrun/eval/leakage_check.py` | Leakage → 0 rule | §14.3, §17 |
| Interleaving experiment (A/B/C) | `speedrun/eval/interleaving_experiment.py` | I4; study-feature test | §15 |
| RC commentator (grounded, optional AI) | `speedrun/rc_commentator.py` | RC structures | §14 |

---

## 5. Shared engine, iOS, and sync

| Feature | File | Origin | PRD |
| --- | --- | --- | --- |
| Schema-weighted queue + scores RPC (protobuf) | `proto/anki/scheduler.proto` | Shared-engine rule | §9.2, §6 |
| Python queue client (calls Rust RPC) | `speedrun/scoring/queue.py` | SPOV 1 | §9.2 |
| rslib-ffi C bridge (engine on the phone) | `rslib-ffi/src/lib.rs` | Real engine on iOS | §12, §6 |
| Swift backend wrapper | `ios/AnkiKit/Sources/AnkiKit/AnkiBackend.swift` | Shared engine | §12 |
| iOS engine (shared RPCs) | `ios/AnkiKit/Sources/AnkiKit/SpeedrunEngine.swift` | SPOV 1, §12 | §12 |
| iOS review + three scores UI | `ios/App/ContentView.swift`, `ios/App/ReviewView.swift` | SPOV 1, SPOV 4 | §12, §10 |
| Two-way sync + conflict rule | `docs/speedrun/SYNC.md` | Sync/conflict rule | §13 |
| Self-hosted sync-server runbook | `docs/speedrun/SYNC-SERVER.md` | Dev sync | §13 |
| Sync integration test | `speedrun/tools/sync_test.py` | Sync test (no lost/double) | §13 |
| iOS sync client + UI | `ios/App/SyncView.swift` | Offline-first sync | §13 |

---

## 6. Desktop app shell

| Feature | File | Origin | PRD |
| --- | --- | --- | --- |
| Qt integration (LSAT Speedrun menu) | `qt/aqt/speedrun/__init__.py` | Product shell | §11 |
| Three-score dashboard (abstain-aware) | `speedrun/dashboard.py` | SPOV 1/4; honesty | §11, §10 |
| Reviewer hooks (latency/budget toast) | `qt/aqt/speedrun/reviewer.py` | SPOV 4 | §11 |
| Schema-weighted queue view | `qt/aqt/speedrun/__init__.py` | SPOV 1 | §9 |
| Clean-machine installer | `tools/build-macos-installer.sh`, `packaging/macos/install.command` | Clean-device install | §11, §20 |
| Unified CLI | `speedrun/tools/speedrun_cli.py` | Re-runnable tooling | §17 |
| Health check | `speedrun/tools/health_check.py` | Reliability | §18 |

---

## 7. Tests, benchmarks, CI, proof

| Feature | File | Origin | PRD |
| --- | --- | --- | --- |
| Rust unit tests (queue + score math) | `rslib/src/scheduler/schema_weighted.rs`, `speedrun_scores.rs` | Rust artifacts | §9.3 |
| Python-over-RPC queue test | `pylib/tests/test_schema_weighted_queue.py` | Rust artifacts | §9.3 |
| Python↔Rust score parity test | `pylib/tests/test_speedrun_scores_rpc.py` | Parity | §6, §9.3 |
| Score + gate unit tests | `pylib/tests/test_speedrun_{memory,performance,readiness,guardrail}.py` | Held-out / honesty | §10, §17 |
| Learning-feature unit tests | `pylib/tests/test_speedrun_{contrasting,cold_open,fork_trainer,fading,confusion,...}.py` | SPOV 1–4 | §15, §17 |
| AI tests (offline) | `pylib/tests/test_speedrun_ai.py` | AI safety | §14, §17 |
| CI workflow | `.github/workflows/speedrun-tests.yml` | Re-runnable tests | §17 |
| Benchmark harness (p50/p95/worst) | `speedrun/tools/bench.py`, `justfile` (`bench`) | Speed targets | §18 |
| Crash-integrity test | `speedrun/tools/crash_test.py` | Zero-corruption | §17, §18 |
| Offline AI-off proof | `speedrun/tools/offline_test.py` | Runs with AI off | §14, §11 |
| Checklist + published results | `docs/speedrun/CHECKLIST.md`, `docs/speedrun/RESULTS.md` | Proof artifacts | §16, §17 |

---

## 8. PRD hard limits (§19) — and where each is neutralized

| If the build... | Score cap | Neutralized by |
| --- | --- | --- |
| has no real Rust change | 50% max | Schema-weighted queue in `rslib` + RPC (§9) |
| has no phone sharing the engine + syncing | 70% max | `rslib-ffi` + two-way sync (§12, §13) |
| has no re-runnable tests | 60% max | CI + seeded eval harnesses (§17) |
| has no held-out testing | 60% max | AI eval + FSRS calibration on held-out (§10, §17) |
| shows made-up / misleading readiness | **auto-fail** | Evidence gate + give-up rule (§1, §10.3) |
| fails on a clean device | 50% max | Clean-machine installer + iOS build (§11, §12) |
| leaks test data | score → 0 | `leakage_check.py` Jaccard scan (§14) |
| makes AI claims with no source | AI section → 0 | Named-source enforcement (§14.1) |

---

## 9. Training signal deliberately excluded from scores

Only graded transfer from the Anki revlog feeds Memory / Performance /
Readiness. These features are diagnostic/practice signal and are excluded
(enforced in code + unit-tested), so adding practice modes never inflates the
honest number.

- Contrasting-pairs self-ratings — `speedrun/contrasting.py`
- Predict-the-schema cold-open — `speedrun/cold_open.py`
- Two-answer fork trainer grades — `speedrun/fork_trainer.py`
- Mastery-ladder / fading telemetry — `speedrun/fading.py`
- Confidence calibration — `speedrun/confidence_calibration.py`
- Confusion-pair interleaving plan — `speedrun/confusion.py`
- RC commentator output — `speedrun/rc_commentator.py`
- Session-logger drill events — `speedrun/session_logger.py`
- Any AI-generated content (must pass checker first) — `speedrun/ai/*`

---

## 10. Where the BrainLift's experts show up in the build

| Expert(s) | Contribution | Feature(s) |
| --- | --- | --- |
| Gick & Holyoak | Schema induction via comparison of analogs | Contrasting-pairs drill, concept map, transfer-gap report |
| Kornell & Bjork; Rohrer | Interleaving aids discrimination ("which type is this?") | Confusion-pair interleaving, interleaving experiment |
| Karpicke & Roediger | Retrieval consolidates; confidence ≠ retention | Reasoning evaluator, confidence calibration, evidence gate |
| Sweller; Kalyuga | Worked examples + expertise-reversal (fade with expertise) | Mastery ladder / adaptive fading (hardest-step-last) |
| LSAC; prep-taxonomy synthesis | Format facts + pattern taxonomy | Four-axis taxonomy, 120–180 readiness mapping |

---

*Note on scope: the PRD explicitly required only one learning-science feature
(interleaving, §15). Several BrainLift-driven study features (contrasting-pairs,
cold-open, confusion interleaving, logic visualizer) exceed that requirement and
are mapped here to their closest PRD section.*
