# Speedrun LSAT — grading checklist status

Regenerate the automated portion any time with:

```bash
tools/verify-speedrun-checklist.sh          # desktop + engine
RUN_IOS=1 tools/verify-speedrun-checklist.sh  # also iOS simulator
```

Legend: ✅ done & automatically verified · 🎥 code done, needs a human screen recording.

---

## Desktop

| # | Requirement | Status | Evidence / how to reproduce |
|---|-------------|--------|------------------------------|
| 1 | Anki forked and building from source | ✅ | Fork of `ankitects/anki` (merge-base `6770ad3ef`). Build+run: `./run`. Clean build → 🎥 record `git clean -xdf && ./run`. |
| 2 | Rust change end to end: the diff, 3 Rust unit tests, 1 Python test that calls it | ✅ | Diff: `rslib/src/scheduler/schema_weighted.rs` + `service/mod.rs` + `proto/anki/scheduler.proto` (see `docs/speedrun/rust-change.md`). **5** Rust unit tests: `cargo test -p anki schema_weighted`. Python→Rust FFI: `pylib/tests/test_schema_weighted_queue.py`. |
| 3 | A review loop running on your exam deck | ✅ | `pylib/tests/test_speedrun_review_session.py`: import exam deck → order via the Rust schema-weighted queue → answer cards → revlog + new-count change. Also live in the app reviewer. |
| 4 | A memory model with an honest score: a range plus the give-up rule | ✅ | `speedrun/scoring/memory.py` (FSRS retrievability; `mean_ci` range; `MIN_REVIEWED_*` give-up) + evidence gate `speedrun/scoring/guardrail.py`. Tests: `test_speedrun_memory.py`, `test_speedrun_guardrail.py`. |
| 5 | An installer that runs on a clean machine | ✅ (Path A) / 🎥 | `speedrun` is now a wheel (`packaging/speedrun/pyproject.toml`), builds via `tools/build-speedrun-installer.sh`, installs on a clean Python 3.12+ machine (`docs/speedrun/INSTALL.md`). Guarded by `test_speedrun_packaging.py`. Native `.dmg`/`.msi` via `--native`. 🎥 record the clean-machine install. |

## Mobile

| # | Requirement | Status | Evidence / how to reproduce |
|---|-------------|--------|------------------------------|
| 6 | A phone app that builds and runs on a device/emulator | ✅ / 🎥 | Runnable app: `ios/App` (XcodeGen `project.yml` → `SpeedrunLSAT.xcodeproj`, `@main SpeedrunLSATApp`). Built & launched on the iOS 26.5 simulator (`ios/screenshot-home.png`). 🎥 record the run. |
| 7 | Loads your exam deck and runs a review session on the shared engine | ✅ / 🎥 | `ios/AnkiKit` `SpeedrunEngine` opens the bundled exam deck and builds the schema-weighted queue over the shared `AnkiFFI` engine. XCTest passes on the simulator (`SpeedrunEngineTests`). Review UI: `ios/App/ReviewView.swift` (`ios/screenshot-review.png`, "Card 1 of 41"). 🎥 record a review session. |

## Proof artifacts

| Item | Status | Where |
|------|--------|-------|
| Commit hash | ✅ | `git rev-parse HEAD` |
| Test results | ✅ | `tools/verify-speedrun-checklist.sh` (7/7 groups pass) |
| Clean-build recording | 🎥 | `git clean -xdf && ./run` |
| Clean-machine install recording | 🎥 | `docs/speedrun/INSTALL.md` Path A |
| Phone review-session recording | 🎥 | Xcode → Run `ios/App` → "Study the exam deck" |

The shared engine is genuinely shared: the desktop reaches the schema-weighted
queue via `pylib/rsbridge` (PyO3) and the phone reaches the *same*
`anki::backend::Backend` via `rslib-ffi` (C FFI) — both send the identical
`(service=13, method=39)` protobuf command. Proof on the real exam deck:
`rslib-ffi` test `open_exam_deck_and_queue_over_ffi` and iOS
`SpeedrunEngineTests`.

## What's intentionally not done yet

- Two-way sync between phone and desktop (not required for this checklist).
- Full FSRS grading UI on the phone (the engine supports it; the phone review
  screen currently drives a schema-interleaved pass over the engine-ordered
  queue). Desktop has full grading.
- Speedrun-branded native `.dmg` (the Briefcase bundle is still "Anki"-branded;
  Path A wheels are the branded, verified install route).
