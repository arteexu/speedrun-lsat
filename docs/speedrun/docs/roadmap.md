# Build Roadmap — Speedrun LSAT

Execution checklist with the proof artifact required for each item. Build in order: **apps work → AI → prove it.** Do not skip ahead. See [../PRD.md](../PRD.md) for full specs. Checkboxes track real completion.

---

## Phase 0 — Setup (do this before any feature)

- [ ] Fork `ankitects/anki`; keep AGPL-3.0-or-later; add Anki attribution; state exam = **LSAT** at top of README.
- [ ] Clone the fork into a **no-space path** (e.g. `~/dev/speedrun-lsat`); keep PDFs + this PRD in the current workspace.
- [ ] Install toolchain: `rustup`, `uv`, `n2`/Ninja, `just`. (For iOS later: Xcode, Rust targets `aarch64-apple-ios` + sim.)
- [ ] `just run` builds and launches the desktop app.
- [ ] Make a one-line Rust change in `rslib/` visible in the running app (proves Rust→Python→GUI path).
- [ ] `just check` runs Rust + Python tests green.
- [ ] iOS engine "hello world": `rslib-ffi` staticlib calls a simple RPC from Swift on device/sim.
- [ ] Define the schema taxonomy, seed deck, and coverage map ([../PRD.md §8](../PRD.md#8-schema-taxonomy-data-model-and-coverage-map)).

**Proof:** commit hash; recording of `just run`; recording of the one-line Rust change in the app; green test output.

---

## Wednesday — Core works on both screens, NO AI

**Desktop**

- [ ] Fork builds from source.
- [ ] Schema-weighted queue Rust change end to end: the diff, **3 Rust unit tests + 1 Python test**.
- [ ] Undo works and the collection does not corrupt after using the new queue.
- [ ] Review loop runs on the LSAT deck (records correctness + latency + chosen trap).
- [ ] Memory model produces an honest score: range + give-up rule.
- [ ] Installer runs on a clean machine.

**iOS**

- [ ] App builds and runs on a real device or emulator.
- [ ] Loads the LSAT deck and runs a real review session **on the shared engine** (two-way sync not required yet).

**Proof:** commit hash; clean-build recording; test results; clean-machine install recording; phone review-session recording.

---

## Friday — AI added and checked; phone syncs

**Desktop (AI)**

- [ ] Short note: what AI was built, why, what was skipped.
- [ ] Every AI output traces to a named source.
- [ ] Eval before students see anything: accuracy + wrong-answer rate on a held-out set, with a stated cutoff.
- [ ] Side-by-side showing the AI beats a keyword/vector baseline.
- [ ] Card generation + checker against the 50-pair gold set; block cards below cutoff; report correct/wrong/useless.
- [ ] Reasoning evaluator surfaces patterns of weakness (recurring flaw/trap).
- [ ] Leakage-check script run; result clean.
- [ ] App still scores with AI switched off.

**iOS**

- [ ] Two-way sync with desktop: review on phone → see on desktop and the reverse; no lost/double-counted reviews.
- [ ] Offline review works, then syncs on reconnect.
- [ ] Phone shows the three scores with ranges and follows the give-up rule.

**Proof:** eval numbers + baseline comparison; recording of a card reviewed on the phone appearing on desktop after sync.

---

## Sunday — Prove it, and ship both

**Models and evidence**

- [ ] Memory model calibrated: calibration chart + Brier/log loss on held-out reviews.
- [ ] Performance model: accuracy on held-out exam-style questions.
- [ ] Paraphrase/transfer-gap report (30 cards × 2 reworded each).
- [ ] Score mapping written down, with a range.
- [ ] Study-feature experiment: 3 builds (full / ablation / plain Anki), equal study time; pre-registered number; range; null results reported.
- [ ] Honest reporting incl. results that did not work.

**Desktop and mobile**

- [ ] Packaged desktop installer.
- [ ] Packaged iOS build (TestFlight or sideload).
- [ ] Sync conflict handling correct and documented (same card on both devices offline → later timestamp wins).
- [ ] Both apps run with AI off and still give a score.

**System tests**

- [ ] Crash test: kill each app mid-review 20× → zero corrupted collections.
- [ ] Offline test: AI turns off cleanly; both apps keep working and scoring.
- [ ] `just bench` on the 50k deck prints p50/p95/worst for each action vs targets.

**Proof / hand-in:** results report; model descriptions ([models/](models/)); Brainlift; recordings of both builds installing and running on clean devices; 3–5 min demo video.
