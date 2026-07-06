# Build Roadmap — Speedrun LSAT

> **Canonical PRD-path copy.** This is the roadmap linked from the PRD
> (`docs/roadmap.md`). It is kept in sync with the in-repo copy at
> [`speedrun/docs/roadmap.md`](speedrun/docs/roadmap.md); both are the same
> document.

Execution checklist with the proof artifact required for each item. Build in order: **apps work → AI → prove it.** Do not skip ahead. See [speedrun/PRD.md](speedrun/PRD.md) for full specs.

**Status is reconciled with [`speedrun/CHECKLIST.md`](speedrun/CHECKLIST.md) and [`speedrun/RESULTS.md`](speedrun/RESULTS.md).**

Legend:
- `[x]` — done and verified (code + tests / measured result on record).
- `[x] … (partial: …)` — the deliverable is built and exercised, with a stated remaining gap (e.g. runs at seed-deck scale, or needs a live API key / human recording).
- `[ ]` — not done yet; honest TODO.

---

## Phase 0 — Setup (do this before any feature)

- [x] Fork `ankitects/anki`; keep AGPL-3.0-or-later; add Anki attribution; state exam = **LSAT** at top of README.
- [x] Clone the fork into a **no-space path** (`~/dev/speedrun-lsat`); keep PDFs + PRD in the workspace.
- [x] Install toolchain: `rustup`, `uv`, `n2`/Ninja, `just`. (For iOS: Xcode, Rust targets `aarch64-apple-ios` + sim.)
- [x] `just run` / `./run` builds and launches the desktop app.
- [x] Make a Rust change in `rslib/` visible in the running app (proves Rust→Python→GUI path); the schema-weighted queue is the real change.
- [x] `just check` runs Rust + Python tests green.
- [x] iOS engine "hello world": `rslib-ffi` staticlib calls a real RPC from Swift on the simulator.
- [x] Define the schema taxonomy, seed deck, and coverage map ([speedrun/PRD.md §8](speedrun/PRD.md#8-schema-taxonomy-data-model-and-coverage-map)).

**Proof:** merge-base `6770ad3ef`; `tools/verify-speedrun-checklist.sh`; clean-build recording (🎥) via `git clean -xdf && ./run`.

---

## Wednesday — Core works on both screens, NO AI

**Desktop**

- [x] Fork builds from source.
- [x] Schema-weighted queue Rust change end to end: the diff, **5 Rust unit tests + 1 Python test** (`rslib/src/scheduler/schema_weighted.rs`, `pylib/tests/test_schema_weighted_queue.py`; see [speedrun/rust-change.md](speedrun/rust-change.md)).
- [x] Undo works and the collection does not corrupt after using the new queue (RPC is read-only; Python test asserts `undo_status().last_step` unchanged).
- [x] Review loop runs on the LSAT deck (records correctness + latency + chosen trap) — `pylib/tests/test_speedrun_review_session.py`.
- [x] Memory model produces an honest score: range + give-up rule (`speedrun/scoring/memory.py`, `speedrun/scoring/guardrail.py`).
- [x] Installer runs on a clean machine (partial: Path A `speedrun` wheel builds/installs on a clean Python 3.12+ machine, guarded by `test_speedrun_packaging.py`; native `.dmg`/`.msi` and the clean-machine recording (🎥) pending).

**iOS**

- [x] App builds and runs on a real device or emulator (iOS 26.5 simulator; `ios/screenshot-home.png`).
- [x] Loads the LSAT deck and runs a real review session **on the shared engine** (two-way sync not required yet).

**Proof:** `tools/verify-speedrun-checklist.sh` (7/7 groups pass); clean-build + clean-install + phone-review recordings (🎥) pending.

---

## Friday — AI added and checked; phone syncs

**Desktop (AI)**

- [x] Short note: what AI was built, why, what was skipped ([speedrun/ai.md](speedrun/ai.md)).
- [x] Every AI output traces to a named source (named-source enforcement in `speedrun/ai/guard.py`).
- [x] Eval before students see anything: accuracy + wrong-answer rate on a held-out set with a stated cutoff (partial: harness `speedrun/eval/ai_eval.py` + baseline numbers recorded with AI off; live-key AI numbers pending — run `speedrun_cli.py ai-eval` with `OPENAI_API_KEY`).
- [ ] Side-by-side showing the AI beats a keyword/vector baseline (harness ready and baselines score, but demonstrating AI > baseline needs a live-key run).
- [x] Card generation + checker against the 50-pair gold set; block cards below cutoff; report correct/wrong/useless (partial: checker + report done — RESULTS shows counts; live LLM generation not wired, needs a key).
- [x] Reasoning evaluator surfaces patterns of weakness (recurring flaw/trap) — `speedrun/ai/reasoning_evaluator.py`; 21 AI unit tests pass offline.
- [x] Leakage-check script run; result clean (threshold 0.9, no near-duplicates) — `speedrun/eval/leakage_check.py`.
- [x] App still scores with AI switched off (`test_three_scores_compute_with_ai_off`; `speedrun/tools/offline_test.py`).

**iOS**

- [x] Two-way sync with desktop: review on phone → see on desktop and the reverse; no lost/double-counted reviews (`speedrun/tools/sync_test.py` against a live self-hosted server; iOS sync client verified on the simulator).
- [x] Offline review works, then syncs on reconnect (offline-first client; conflict semantics in [speedrun/SYNC.md](speedrun/SYNC.md)).
- [x] Phone shows the three scores with ranges and follows the give-up rule (`ComputeSpeedrunScores` RPC; AnkiKit renders the three scores).

**Proof:** RESULTS "Two-way sync" + "Shared scores RPC"; phone→desktop sync recording (🎥) per [speedrun/SYNC-SERVER.md](speedrun/SYNC-SERVER.md).

---

## Sunday — Prove it, and ship both

**Models and evidence**

- [x] Memory model calibrated: calibration chart + Brier/log loss on held-out reviews (partial: `speedrun/eval/calibration.py`; measured on the 11-card seed deck — perfect calibration is a small-deck artifact, production-scale run pending).
- [x] Performance model: accuracy on held-out exam-style questions (transfer-gap report `speedrun/eval/transfer_gap.py`).
- [x] Paraphrase/transfer-gap report (partial: run on the 11-card seed deck with a synthetic reworded penalty; the 30 cards × 2 reworded protocol at scale pending).
- [x] Score mapping written down, with a range ([models/readiness-model.md](models/readiness-model.md)).
- [x] Study-feature experiment: 3 builds (full / ablation / plain Anki), equal study time; pre-registered number; range; null results reported (partial: synthetic simulation n=200, +6.5% transfer effect; human-subject replication pending) — `speedrun/eval/interleaving_experiment.py`.
- [x] Honest reporting incl. results that did not work ([speedrun/RESULTS.md](speedrun/RESULTS.md) states every caveat).

**Desktop and mobile**

- [x] Packaged desktop installer (partial: Path A wheel via `tools/build-speedrun-installer.sh`; native branded bundle pending).
- [ ] Packaged iOS build (TestFlight or sideload) — XCFramework builds and runs on the simulator, but a signed TestFlight/sideload build is not yet produced.
- [x] Sync conflict handling correct and documented (same card on both devices offline → later timestamp wins; documented in [speedrun/SYNC.md](speedrun/SYNC.md)).
- [x] Both apps run with AI off and still give a score.

**System tests**

- [ ] Crash test: kill each app mid-review 20× → zero corrupted collections (single/simulated crash verified via `speedrun/tools/crash_test.py`; the full 20×-per-platform run is pending).
- [x] Offline test: AI turns off cleanly; both apps keep working and scoring (`speedrun/tools/offline_test.py`).
- [ ] `just bench` on the 50k deck prints p50/p95/worst for each action vs targets (benchmark harness runs on the seed deck; the 50k-card run is pending).

**Proof / hand-in:** results report ([speedrun/RESULTS.md](speedrun/RESULTS.md)); model descriptions ([models/](models/)); BrainLift ([speedrun/BRAINLIFT.md](speedrun/BRAINLIFT.md)); recordings (🎥) of both builds installing/running on clean devices; 3–5 min demo video ([speedrun/DEMO-VIDEO-SCRIPT.md](speedrun/DEMO-VIDEO-SCRIPT.md)).
