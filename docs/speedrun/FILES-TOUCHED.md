# Files touched vs upstream Anki

This is the concrete list of every file this fork changed relative to upstream
Anki. It is grouped by area for readability.

**Baseline (reproducible):** the merge-base of this branch (`speedrun-lsat`) and
`upstream/main` is commit `6770ad3ef460b766d85a3399bd268ff87f4224cb`
(`upstream = https://github.com/ankitects/anki.git`; `upstream/main` tip was
`3186cc31c4b1e7efd9a847104a625f7c49725805` when this list was generated).
Regenerate the list at any time with:

```bash
git fetch upstream
git diff --name-status upstream/main...HEAD   # three-dot = since the merge-base
```

Status legend: `A` = added, `M` = modified (upstream file changed), `D` = deleted.

---

## Rust engine (rslib / rslib-ffi)

The required brownfield change lives here (a schema-weighted "points-at-stake"
study queue and the speedrun scores service), plus a new C-ABI FFI crate so iOS
can call the same engine.

- `M` rslib/src/scheduler/mod.rs
- `M` rslib/src/scheduler/service/mod.rs
- `A` rslib/src/scheduler/schema_weighted.rs
- `A` rslib/src/scheduler/speedrun_scores.rs
- `A` rslib-ffi/Cargo.toml
- `A` rslib-ffi/src/lib.rs
- `A` rslib-ffi/include/anki_ffi.h
- `A` rslib-ffi/include/module.modulemap

### Protobuf interface

- `M` proto/anki/scheduler.proto — RPCs exposing the schema-weighted queue and speedrun scores.

## Python core (pylib/anki)

No `pylib/anki` upstream modules were modified. The fork integrates through the
Qt layer (`qt/aqt`) and a standalone `speedrun/` package rather than editing
Anki's core Python library. (Speedrun tests live under `pylib/tests/`, listed
below.)

## Desktop Qt (qt/aqt)

- `M` qt/aqt/main.py — wires the "Tools → LSAT Speedrun" menu.
- `A` qt/aqt/speedrun/__init__.py
- `A` qt/aqt/speedrun/reviewer.py

## Python speedrun package (speedrun/)

New standalone package holding the scoring models, taxonomy, AI helpers, and CLI
tools. (~85 files.)

Top level:

- `A` speedrun/__init__.py
- `A` speedrun/README.md
- `A` speedrun/config.json
- `A` speedrun/config.py
- `A` speedrun/cold_open.py
- `A` speedrun/concept_graph.py
- `A` speedrun/confidence_calibration.py
- `A` speedrun/confusion.py
- `A` speedrun/contrasting.py
- `A` speedrun/coverage_gap.py
- `A` speedrun/dashboard.py
- `A` speedrun/dialog_geometry.py
- `A` speedrun/drill.py
- `A` speedrun/explanations.py
- `A` speedrun/export.py
- `A` speedrun/fading.py
- `A` speedrun/focus.py
- `A` speedrun/fork_trainer.py
- `A` speedrun/insights.py
- `A` speedrun/logic_diagram.py
- `A` speedrun/mistake_graph.py
- `A` speedrun/preset_eval.py
- `A` speedrun/pretest.py
- `A` speedrun/rc_commentator.py
- `A` speedrun/score_cache.py
- `A` speedrun/session_logger.py
- `A` speedrun/study_goals.py
- `A` speedrun/textfmt.py
- `A` speedrun/timeline.py

speedrun/ai/:

- `A` speedrun/ai/__init__.py
- `A` speedrun/ai/baseline.py
- `A` speedrun/ai/card_checker.py
- `A` speedrun/ai/card_generator.py
- `A` speedrun/ai/client.py
- `A` speedrun/ai/config.py
- `A` speedrun/ai/guard.py
- `A` speedrun/ai/pair_compare.py
- `A` speedrun/ai/reasoning_evaluator.py
- `A` speedrun/ai/recommender.py
- `A` speedrun/ai/settings.py
- `A` speedrun/ai/solver_verify.py
- `A` speedrun/ai/tutor.py

speedrun/scoring/:

- `A` speedrun/scoring/__init__.py
- `A` speedrun/scoring/guardrail.py
- `A` speedrun/scoring/memory.py
- `A` speedrun/scoring/performance.py
- `A` speedrun/scoring/queue.py
- `A` speedrun/scoring/readiness.py

speedrun/eval/:

- `A` speedrun/eval/__init__.py
- `A` speedrun/eval/ai_eval.py
- `A` speedrun/eval/calibration.py
- `A` speedrun/eval/card_check_run.py
- `A` speedrun/eval/grounding_eval.py
- `A` speedrun/eval/interleaving_experiment.py
- `A` speedrun/eval/leakage_check.py
- `A` speedrun/eval/reworded_grader.py
- `A` speedrun/eval/transfer_gap.py

speedrun/taxonomy/:

- `A` speedrun/taxonomy/labels.py
- `A` speedrun/taxonomy/lsat_taxonomy.json
- `A` speedrun/taxonomy/methodology.md

speedrun/tools/:

- `A` speedrun/tools/__init__.py
- `A` speedrun/tools/add_practice_items.py
- `A` speedrun/tools/assign_units.py
- `A` speedrun/tools/bench.py
- `A` speedrun/tools/coverage_map.py
- `A` speedrun/tools/crash_test.py
- `A` speedrun/tools/expand_seed_deck.py
- `A` speedrun/tools/export_exam_deck.py
- `A` speedrun/tools/generate_to_target.py
- `A` speedrun/tools/health_check.py
- `A` speedrun/tools/import_seed_deck.py
- `A` speedrun/tools/make_big_deck.py
- `A` speedrun/tools/memory_report.py
- `A` speedrun/tools/offline_test.py
- `A` speedrun/tools/schema_drill.py
- `A` speedrun/tools/seed_demo_stats.py
- `A` speedrun/tools/seed_sample_reviews.py
- `A` speedrun/tools/speedrun_cli.py
- `A` speedrun/tools/sync_test.py

speedrun/data/:

- `A` speedrun/data/gold_set.json
- `A` speedrun/data/seed_deck.json
- `A` speedrun/data/reworded_attempts.json
- `A` speedrun/data/reworded_set.json
- `A` speedrun/data/sources/lr_flaws_primer.md

## iOS app (ios/)

Native SwiftUI companion that links the Rust engine through `rslib-ffi`. (21 files.)

- `A` ios/AnkiKit/Package.swift
- `A` ios/AnkiKit/Sources/AnkiKit/AnkiBackend.swift
- `A` ios/AnkiKit/Sources/AnkiKit/Protobuf.swift
- `A` ios/AnkiKit/Sources/AnkiKit/SpeedrunEngine.swift
- `A` ios/AnkiKit/Sources/AnkiKit/Resources/collection.anki2
- `A` ios/AnkiKit/Tests/AnkiKitTests/AnkiBackendTests.swift
- `A` ios/AnkiKit/Tests/AnkiKitTests/SpeedrunEngineTests.swift
- `A` ios/App/ContentView.swift
- `A` ios/App/ReviewView.swift
- `A` ios/App/SpeedrunLSATApp.swift
- `A` ios/App/SpeedrunSession.swift
- `A` ios/App/SyncView.swift
- `A` ios/App/project.yml
- `A` ios/LAUNCH.md
- `A` ios/README.md
- `A` ios/Resources/exam/SpeedrunExam.colpkg
- `A` ios/Resources/exam/collection.anki2
- `A` ios/build-xcframework.sh
- `A` ios/run-tests.sh
- `A` ios/screenshot-home.png
- `A` ios/screenshot-review.png

## Docs (docs/speedrun/)

- `A` docs/speedrun/AI-NOTES.md
- `A` docs/speedrun/BRAINLIFT.md
- `A` docs/speedrun/CHECKLIST.md
- `A` docs/speedrun/CONFIG_SCHEMA.md
- `A` docs/speedrun/CONTENT-PLAN.md
- `A` docs/speedrun/DEMO-COMPLIANCE-AND-SCRIPT.md
- `A` docs/speedrun/DEMO-VIDEO-SCRIPT.md
- `A` docs/speedrun/DEMO.md
- `A` docs/speedrun/FILES-TOUCHED.md  ← this file
- `A` docs/speedrun/INSTALL.md
- `A` docs/speedrun/IOS-DEV.md
- `A` docs/speedrun/LSAT-BrainLift-Arthur.pdf
- `A` docs/speedrun/MISTAKE-GRAPH.md
- `A` docs/speedrun/PRD.md
- `A` docs/speedrun/RESULTS.md
- `A` docs/speedrun/SYNC-PLAN.md
- `A` docs/speedrun/SYNC-SERVER.md
- `A` docs/speedrun/SYNC.md
- `A` docs/speedrun/TEST-REPLICABILITY.md
- `A` docs/speedrun/TRACEABILITY.md
- `A` docs/speedrun/VERIFICATION-7b-7f.md
- `A` docs/speedrun/adaptive-fading.md
- `A` docs/speedrun/ai.md
- `A` docs/speedrun/card_check_drafts.json
- `A` docs/speedrun/rust-change.md
- `A` docs/speedrun/generation_report.json
- `A` docs/speedrun/generation_report_topup.json
- `A` docs/speedrun/generation_report_topup2.json
- `A` docs/speedrun/docs/architecture.md
- `A` docs/speedrun/docs/roadmap.md
- `A` docs/speedrun/docs/models/memory-model.md
- `A` docs/speedrun/docs/models/performance-model.md
- `A` docs/speedrun/docs/models/readiness-model.md

### Other docs (repo root / upstream docs)

- `M` docs/architecture.md
- `A` docs/roadmap.md
- `A` docs/models/memory-model.md
- `A` docs/models/performance-model.md
- `A` docs/models/readiness-model.md

## Tests (pylib/tests/)

- `A` pylib/tests/test_schema_weighted_queue.py
- `A` pylib/tests/test_speedrun_ai.py
- `A` pylib/tests/test_speedrun_ai_settings.py
- `A` pylib/tests/test_speedrun_big_deck.py
- `A` pylib/tests/test_speedrun_calibration.py
- `A` pylib/tests/test_speedrun_cold_open.py
- `A` pylib/tests/test_speedrun_concept_graph.py
- `A` pylib/tests/test_speedrun_confidence_calibration.py
- `A` pylib/tests/test_speedrun_config.py
- `A` pylib/tests/test_speedrun_confusion.py
- `A` pylib/tests/test_speedrun_contrasting.py
- `A` pylib/tests/test_speedrun_crash.py
- `A` pylib/tests/test_speedrun_dashboard.py
- `A` pylib/tests/test_speedrun_dialog_geometry.py
- `A` pylib/tests/test_speedrun_explanations.py
- `A` pylib/tests/test_speedrun_fading.py
- `A` pylib/tests/test_speedrun_features.py
- `A` pylib/tests/test_speedrun_focus.py
- `A` pylib/tests/test_speedrun_fork_trainer.py
- `A` pylib/tests/test_speedrun_guardrail.py
- `A` pylib/tests/test_speedrun_insights.py
- `A` pylib/tests/test_speedrun_interleaving.py
- `A` pylib/tests/test_speedrun_labels.py
- `A` pylib/tests/test_speedrun_logic_diagram.py
- `A` pylib/tests/test_speedrun_memory.py
- `A` pylib/tests/test_speedrun_mistake_graph.py
- `A` pylib/tests/test_speedrun_packaging.py
- `A` pylib/tests/test_speedrun_pair_compare.py
- `A` pylib/tests/test_speedrun_performance.py
- `A` pylib/tests/test_speedrun_preset_eval.py
- `A` pylib/tests/test_speedrun_rc_commentator.py
- `A` pylib/tests/test_speedrun_readiness.py
- `A` pylib/tests/test_speedrun_recommender.py
- `A` pylib/tests/test_speedrun_review_session.py
- `A` pylib/tests/test_speedrun_schema_review.py
- `A` pylib/tests/test_speedrun_scores_rpc.py
- `A` pylib/tests/test_speedrun_seed_demo_stats.py
- `A` pylib/tests/test_speedrun_study_goals.py
- `A` pylib/tests/test_speedrun_tools.py
- `A` pylib/tests/test_speedrun_transfer.py
- `A` pylib/tests/test_speedrun_trap_and_reasoning.py
- `A` pylib/tests/test_speedrun_tutor.py
- `A` pylib/tests/test_speedrun_units.py

## Build/tooling (justfile, tools/, .gitignore, etc.)

- `M` justfile — speedrun test/bench/wheels recipes.
- `M` .gitignore — ignore `.ankidata*`, build/eval artifacts, AI settings/keys.
- `M` .cargo/config.toml
- `M` Cargo.toml
- `M` Cargo.lock
- `M` ts/mathjax/index.ts
- `A` .github/workflows/speedrun-tests.yml
- `A` launch-speedrun.command
- `A` launch-speedrun.sh
- `A` packaging/macos/README.txt
- `A` packaging/macos/install.command
- `A` packaging/speedrun/pyproject.toml
- `A` tools/build-macos-installer.sh
- `A` tools/build-speedrun-installer.sh
- `A` tools/verify-speedrun-checklist.sh

## Repo root

- `M` README.md — Speedrun LSAT section (exam, build instructions, architecture, Rust-change note, and the link to this file).
