# Speedrun LSAT

**Exam: LSAT (Law School Admission Test), scored 120–180.**

An accelerated-learning study app for the LSAT, built as a brownfield fork of
[Anki](https://github.com/ankitects/anki). It ships a desktop app and an iOS
companion that share one Rust engine, makes a real change inside Anki's Rust
core (a schema-weighted study queue), and reports three separate scores —
memory, performance, and readiness — each with a range and a give-up rule.

See the product spec and roadmap in
[`docs/speedrun/PRD.md`](docs/speedrun/PRD.md) (architecture:
[`docs/speedrun/docs/architecture.md`](docs/speedrun/docs/architecture.md), roadmap:
[`docs/speedrun/docs/roadmap.md`](docs/speedrun/docs/roadmap.md)).

## Speedrun LSAT — build and run

> ⚠️ **Clone to a path with NO SPACES.** Anki's build **fails on paths that
> contain spaces**, so this fork must live in a space-free directory (e.g.
> `~/dev/speedrun-lsat`), not somewhere like `~/Desktop/Alpha AI/Speedrun`.
> Keep the PRD/PDFs wherever you like; build the code from the no-space path.

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
`pylib/rsbridge`) and iOS (via `rslib-ffi`).

- [`docs/speedrun/rust-change.md`](docs/speedrun/rust-change.md) — the engine-change
  note: what it does, why it belongs in Rust, its tests, and the
  **upstream files touched** table with a rebase merge-difficulty assessment.

### Files touched

- [`docs/speedrun/FILES-TOUCHED.md`](docs/speedrun/FILES-TOUCHED.md) — every file this fork changed vs upstream Anki (grouped by area, reproducible from the merge-base).

### Model descriptions

One short page each for the three scores, including the model, its honest range, and the **give-up rule** enforced in code:

- [`docs/models/memory-model.md`](docs/models/memory-model.md) — memory (FSRS recall); give-up: ≥ 5 reviewed cards overall, ≥ 2 per schema.
- [`docs/models/performance-model.md`](docs/models/performance-model.md) — performance (memory → transfer); give-up: ≥ 2 graded attempts per schema, ≥ 10 overall.
- [`docs/models/readiness-model.md`](docs/models/readiness-model.md) — readiness (projected 120–180); give-up: ≥ 200 graded attempts **and** ≥ 50% coverage in each of LR and RC.

### Results, evaluation, and demo

- [`docs/speedrun/RESULTS.md`](docs/speedrun/RESULTS.md) — honest test numbers from the re-runnable harnesses
- [`docs/speedrun/DEMO.md`](docs/speedrun/DEMO.md) — walkthrough script
- [`docs/speedrun/DEMO-VIDEO-SCRIPT.md`](docs/speedrun/DEMO-VIDEO-SCRIPT.md) — 3–5 min demo video script
- [`docs/speedrun/ai.md`](docs/speedrun/ai.md) — AI note: sourced, evaluated, and switch-off-able
- [`docs/speedrun/SYNC.md`](docs/speedrun/SYNC.md) — sync conflict rule (documented)
- [`docs/speedrun/CHECKLIST.md`](docs/speedrun/CHECKLIST.md) — grading-checklist status
- [`docs/speedrun/docs/roadmap.md`](docs/speedrun/docs/roadmap.md) — deadline-by-deadline roadmap with proof artifacts

### Learning-science foundation

- [`docs/speedrun/BRAINLIFT.md`](docs/speedrun/BRAINLIFT.md) — the LSAT BrainLift (SPOVs + Insights), tracked alongside its [source PDF](docs/speedrun/LSAT-BrainLift-Arthur.pdf)
- [`docs/speedrun/TRACEABILITY.md`](docs/speedrun/TRACEABILITY.md) — every feature → BrainLift SPOV/Insight / PRD section

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
