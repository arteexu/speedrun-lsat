# Speedrun LSAT

**Exam: LSAT (Law School Admission Test), scored 120–180.**

An accelerated-learning study app for the LSAT, built as a brownfield fork of
[Anki](https://github.com/ankitects/anki). It ships a desktop app and an iOS
companion that share one Rust engine, makes a real change inside Anki's Rust
core (a schema-weighted study queue), and reports three separate scores —
memory, performance, and readiness — each with a range and a give-up rule.

See the product spec in [`docs/speedrun/PRD.md`](docs/speedrun/PRD.md) — the single
source of truth. Every required write-up is indexed below.

## Deliverables & reports

A one-stop map of every required description and report. Each links straight to
the real file, so nothing has to be hunted for.

**Overview & architecture**

- [`docs/speedrun/PRD.md`](docs/speedrun/PRD.md) — the single source of truth: every requirement, the honesty rule, and the grading map.
- [`docs/architecture.md`](docs/architecture.md) — system architecture and the shared-engine design (desktop + iOS on one Rust core), including the sync merge outcome.
- [`docs/speedrun/rust-change.md`](docs/speedrun/rust-change.md) — the Rust engine-change note: what the schema-weighted queue does, why it belongs in Rust (hot path, shared by both apps), its tests, and the upstream files-touched / rebase-difficulty table.
- [`docs/roadmap.md`](docs/roadmap.md) — deadline-by-deadline execution checklist with the proof artifact required for each item.

**The three scores (model descriptions)** — one short page each, including the **give-up rule** enforced in code

- [`docs/models/memory-model.md`](docs/models/memory-model.md) — memory (FSRS recall); give-up: ≥ 5 reviewed cards overall, ≥ 2 per schema.
- [`docs/models/performance-model.md`](docs/models/performance-model.md) — performance (the memory → transfer bridge); give-up: ≥ 2 graded attempts per schema, ≥ 10 overall.
- [`docs/models/readiness-model.md`](docs/models/readiness-model.md) — readiness (projected 120–180 with a range); give-up: ≥ 200 graded attempts **and** ≥ 50% coverage in each of LR and RC.

**Evaluation & results**

- [`docs/speedrun/RESULTS.md`](docs/speedrun/RESULTS.md) — honest numbers from the re-runnable harnesses: accuracy, wrong-answer rate, the pre-set cutoff, and the AI-vs-baseline comparison.

**AI**

- [`docs/speedrun/ai.md`](docs/speedrun/ai.md) — what AI was built, why, and what was skipped; source traceability; the off switch (all three scores compute with AI off).
- [`docs/speedrun/AI-NOTES.md`](docs/speedrun/AI-NOTES.md) — demo-ready AI note with copy-pasteable proof numbers and the commands to reproduce them.
- [`docs/speedrun/TRACEABILITY.md`](docs/speedrun/TRACEABILITY.md) — every feature traced back to a BrainLift SPOV/Insight or a PRD section.

**Sync**

- [`docs/speedrun/SYNC.md`](docs/speedrun/SYNC.md) — sync mechanism and the **conflict rule**: later real-timestamp wins; no reviews lost, none double-counted.
- [`docs/speedrun/SYNC-SERVER.md`](docs/speedrun/SYNC-SERVER.md) — runbook for the self-hosted Anki sync server both clients point at.
- [`docs/speedrun/SYNC-PLAN.md`](docs/speedrun/SYNC-PLAN.md) — the sync design and the two-way offline round-trip test.

**Learning science**

- [`docs/speedrun/BRAINLIFT.md`](docs/speedrun/BRAINLIFT.md) — the LSAT BrainLift (SPOVs + Insights), tracked alongside its [source PDF](docs/speedrun/LSAT-BrainLift-Arthur.pdf).
- [`docs/speedrun/adaptive-fading.md`](docs/speedrun/adaptive-fading.md) — adaptive mastery-ordered fading (SPOV3) and its experiment.
- [`docs/speedrun/MISTAKE-GRAPH.md`](docs/speedrun/MISTAKE-GRAPH.md) — the mistake-graph analytics feature: the data it needs, how to populate it, and how to test it.
- [`docs/speedrun/CONTENT-PLAN.md`](docs/speedrun/CONTENT-PLAN.md) — content audit and course-scaling plan for the seed deck.

**Build & install**

- [`docs/speedrun/INSTALL.md`](docs/speedrun/INSTALL.md) — install the desktop app on a clean machine (one-click installer / wheels / Briefcase).
- [`docs/speedrun/IOS-DEV.md`](docs/speedrun/IOS-DEV.md) — build, run, and test the iOS app (XCFramework, simulator/device).
- [`docs/speedrun/CONFIG_SCHEMA.md`](docs/speedrun/CONFIG_SCHEMA.md) — the shared `config.json` schema used by desktop and iOS.

**Demo & proof**

- [`docs/speedrun/DEMO.md`](docs/speedrun/DEMO.md) — walkthrough script.
- [`docs/speedrun/DEMO-VIDEO-SCRIPT.md`](docs/speedrun/DEMO-VIDEO-SCRIPT.md) — the 3–5 minute demo video script.
- [`docs/speedrun/DEMO-COMPLIANCE-AND-SCRIPT.md`](docs/speedrun/DEMO-COMPLIANCE-AND-SCRIPT.md) — hard-limit compliance + rubric-mapped evidence + a spoken demo narration.

**Compliance & tests**

- [`docs/speedrun/CHECKLIST.md`](docs/speedrun/CHECKLIST.md) — grading-checklist status (auto-verified vs. needs-recording).
- [`docs/speedrun/VERIFICATION-7b-7f.md`](docs/speedrun/VERIFICATION-7b-7f.md) — per-requirement verification (sync, transfer gap, leakage, AI card check) with exact commands and numbers.
- [`docs/speedrun/TEST-REPLICABILITY.md`](docs/speedrun/TEST-REPLICABILITY.md) — replicability audit: one documented command → the same result, for every PRD test/eval/benchmark.

**Files touched**

- [`docs/speedrun/FILES-TOUCHED.md`](docs/speedrun/FILES-TOUCHED.md) — every file this fork changed vs upstream Anki, grouped by area and reproducible from the merge-base.

## Speedrun LSAT — build and run

> ⚠️ **Clone to a path with NO SPACES.** Anki's build **fails on paths that
> contain spaces**, so this fork must live in a space-free directory (e.g.
> `~/dev/speedrun-lsat`), not somewhere like `~/Desktop/Alpha AI/Speedrun`.
> Keep the PRD/PDFs wherever you like; build the code from the no-space path.

Full install paths for both apps: [`docs/speedrun/INSTALL.md`](docs/speedrun/INSTALL.md) (desktop) and [`docs/speedrun/IOS-DEV.md`](docs/speedrun/IOS-DEV.md) (iOS).

### Desktop

```bash
./run --profile .ankidata          # dev mode (first build ~5 min)
```

In the app: **Tools → LSAT Speedrun** (Dashboard, Queue, Import Seed Deck).

```bash
just check                         # full lint + test
PYTHONPATH=out/pylib out/pyenv/bin/python -m pytest pylib/tests/test_speedrun_*.py -q
just bench                         # scoring benchmarks
just wheels                        # packaging wheels
```

### iOS companion

```bash
bash ios/build-xcframework.sh      # build AnkiFFI.xcframework
bash ios/run-tests.sh              # verify FFI + host tests
```

See [`ios/README.md`](ios/README.md) for Xcode simulator setup.

### The Rust engine change (brownfield)

The required change inside Anki's Rust core is a **schema-weighted
"points-at-stake" study queue** that orders due cards by exam value at stake.
It lives in [`rslib/src/scheduler/schema_weighted.rs`](rslib/src/scheduler/schema_weighted.rs),
is exposed as a protobuf RPC, and is called identically from desktop (via
`pylib/rsbridge`) and iOS (via `rslib-ffi`). The engine-change note —
[`docs/speedrun/rust-change.md`](docs/speedrun/rust-change.md) — explains what it
does, why it belongs in Rust, its tests, and the upstream files-touched table.

## License and attribution

This project is a fork of **Anki** by Ankitects Pty Ltd and contributors, and
is distributed under **AGPL-3.0-or-later**, the same license as Anki. Some Anki
components are under BSD-3-Clause. All original Anki copyrights and licenses are
retained. Anki is a trademark of Ankitects Pty Ltd; this is an independent fork
and is not affiliated with or endorsed by Ankitects.

---

# Anki (upstream)

[![Build Status](https://github.com/ankitects/anki/actions/workflows/ci.yml/badge.svg)](https://github.com/ankitects/anki/actions/workflows/ci.yml)
[![Documentation](https://img.shields.io/badge/docs-dev--docs.ankiweb.net-blue)](https://dev-docs.ankiweb.net)

This repo contains the source code for the computer version of
[Anki](https://apps.ankiweb.net).

## About

Anki is a spaced repetition program. Please see the [website](https://apps.ankiweb.net) to learn more.

## Getting Started

### Contributing

Want to contribute to Anki? Check out the [Contribution Guidelines](./docs/contributing.md).

For more information on building and developing, please see [Development](./docs/development.md).

#### Contributors

The following people have contributed to Anki: [CONTRIBUTORS](./CONTRIBUTORS)

### Anki Betas

If you'd like to try development builds of Anki but don't feel comfortable
building the code, please see [Anki betas](https://betas.ankiweb.net/).

## License

Anki's license: [LICENSE](./LICENSE)
