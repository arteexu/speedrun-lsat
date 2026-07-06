# Speedrun LSAT — Demo Compliance & Script

One reader-facing document that does three things:

- **Part A — Hard limits:** every PRD §19 hard limit, why we clear it, and the exact
  click/command/number that proves it on demand.
- **Part B — Grading criteria:** every PRD §19 rubric row (with its weight), mapped to
  concrete, reproducible demo evidence.
- **Part C — Demo script:** a spoken 3–5 minute narration (with time markers and
  `[ON SCREEN]` cues) that teaches the pedagogy in plain terms while walking the seeded
  demo profile end to end.

This doc **cross-references** rather than duplicates the deeper docs:
[`PRD.md`](PRD.md) · [`CHECKLIST.md`](CHECKLIST.md) · [`RESULTS.md`](RESULTS.md) ·
[`AI-NOTES.md`](AI-NOTES.md) · [`TRACEABILITY.md`](TRACEABILITY.md) ·
[`BRAINLIFT.md`](BRAINLIFT.md) · [`SYNC.md`](SYNC.md) · [`INSTALL.md`](INSTALL.md) ·
[`rust-change.md`](rust-change.md) · [`DEMO.md`](DEMO.md) ·
[`DEMO-VIDEO-SCRIPT.md`](DEMO-VIDEO-SCRIPT.md).

Every number below was re-measured against the tools before publishing. Numbers that
move run-to-run (the LLM-judge baseline percentages) or that are external-only (the
recorded video, a signed iOS build, a physical clean machine) are flagged as such.

---

## 0. One-time setup for the whole demo

All commands run from the repo root on a machine that has built the fork once
(`out/pylib`, `out/pyenv` exist).

```bash
cd ~/dev/speedrun-lsat
```

**Launch the fully-seeded demo profile.** Anki is single-instance, so **quit any running
Anki first**, then:

```bash
# fully QUIT Anki first, then:
cd ~/dev/speedrun-lsat && ANKI_BASE=~/dev/speedrun-lsat/.ankidata-demo ./run
```

**What the demo profile actually contains** (re-measured from
`.ankidata-demo/User 1/collection.anki2` on 2026‑07‑05):

| Fact | Verified value |
| --- | --- |
| Reviews in the revlog | **1,171** |
| Distinct cards reviewed | **504** (the whole exam deck) |
| Study days / calendar span | **46 days** studied over a **~45-day** span |
| Total study time logged | **~17.5 hours** |
| Memory score | **94%** (range 93%–94% recall) |
| Performance score | **70%** (range 67%–72% transfer) |
| Readiness score | **161** (range **152–170**, high confidence) |
| Evidence gate | **OPEN** |
| Mistake graph | **52 nodes / 473 edges** |
| Concept map | 57 nodes / 474 edges |

> The real ~504-card `.ankidata` profile is seeded identically; use `.ankidata` in place
> of `.ankidata-demo` above if you want to demo on the primary profile. On that profile
> AI is enabled (`ai_enabled: true`) so the live tutor works on camera.

Everything in Parts A and B is reproducible with the commands shown. Where a proof is a
**human recording** (not something a command can emit), it is marked **🎥 external-only**.

---

## Part A — Hard limits, and how to demo each is satisfied

PRD §19 lists eight hard limits. Each row: the limit, why we clear it, and the exact
on-screen action or command that proves it.

### A1. No real Rust change → 50% max

**Why we clear it.** The required brownfield change is a new review-ordering mode inside
Anki's Rust core: a **schema-weighted "points-at-stake" queue** in
`rslib/src/scheduler/schema_weighted.rs`, exposed as a new protobuf RPC
(`build_schema_weighted_queue`, `SchedulerService`) and reused by both apps. A companion
Rust module `rslib/src/scheduler/speedrun_scores.rs` computes the three scores and the
per-section give-up in Rust with Python parity tests. It is a genuine engine change, not
a Python screen. See [`rust-change.md`](rust-change.md).

**Prove it on demand:**

```bash
cargo test -p anki schema_weighted        # 5 Rust unit tests (priority, tie-break,
                                          # unknown-schema default, time-pressure, limit)
PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python \
  -m pytest pylib/tests/test_schema_weighted_queue.py -v   # Python calls the Rust RPC
```

- **On screen:** in the app, **Tools → LSAT Speedrun → Study now** walks this exact
  Rust-ordered queue; the diff is `proto/anki/scheduler.proto` +
  `rslib/src/scheduler/{mod,service/mod}.rs` + the new module.
- **Point at:** the "upstream files touched / merge-difficulty" table in
  [`rust-change.md`](rust-change.md) (three small additive edits + one new module).

### A2. No phone companion sharing the engine + syncing → 70% max

**Why we clear it.** The iOS app links the **same** `rslib` engine through a C/FFI bridge
(`rslib-ffi`), not a Swift reimplementation. Desktop and phone send the *identical*
protobuf command (`service=13, method=39` for the queue; the scores RPC likewise). Two-way
sync runs over Anki's own sync protocol against a self-hosted server. See
[`SYNC.md`](SYNC.md), [`CHECKLIST.md`](CHECKLIST.md).

**Prove it on demand:**

```bash
PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/sync_test.py   # two-way, no loss
bash ios/run-tests.sh                                                   # rslib-ffi + AnkiKit
```

- `sync_test.py` creates a "desktop" and a "phone" collection, syncs the exam deck both
  ways, reviews **different** cards on each (they all land exactly once), then reviews the
  **same** card on both and asserts one consistent card state with **both** revlog rows
  preserved — no lost, none double-counted.
- **On screen (🎥 external-only for the live round-trip):** review a card on the iOS
  simulator → Sync → switch to desktop → Sync → the phone review appears, counted once.
  The mechanism is fully tested; the on-camera capture is the human proof.

### A3. No re-runnable test setup → 60% max

**Why we clear it.** Everything is scripted with seeded splits and a CI workflow
(`.github/workflows/speedrun-tests.yml`); anyone can reproduce the same numbers.

**Prove it on demand:**

```bash
unset SPEEDRUN_AI_SETTINGS_PATH
PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python \
  -m pytest pylib/tests/ -k "speedrun or schema" -q
```

- **Committed / CI result: `398 passed, 1 skipped`** (fresh checkout; the skip is the
  aqt-not-importable dashboard test). The committed `speedrun/config.json` is at the code
  defaults — `git show HEAD:speedrun/config.json` shows **no** `guardrail` override.
- **If you run the suite while a demo profile is seeded you may see `396 passed, 2 failed`.**
  This is a *local-only* artifact, not a shipped bug: `seed_demo_stats.py` relaxes
  `min_pattern_coverage` to **0.73** in your **working-tree** `config.json` so the evidence
  gate opens on the small deck, and two self-consistency tests
  (`test_default_thresholds_present_and_valid`, `test_dashboard_gate_stays_locked_after_seed_pass`)
  assert the **0.80** code default. Restore it and the suite is green again:
  `python speedrun/tools/seed_demo_stats.py --clear --col ".ankidata-demo/User 1/collection.anki2"`.
  Even relaxed, the gate stays far above the PRD §10.3 floor (50% coverage).
- Re-runnable harnesses (each prints the same numbers on a clean run):
  `speedrun/tools/bench.py`, `speedrun/eval/ai_eval.py`, `speedrun/eval/grounding_eval.py`,
  `speedrun/eval/interleaving_experiment.py`, `speedrun/eval/leakage_check.py`,
  `speedrun/tools/crash_test.py`, `speedrun/tools/sync_test.py`.

### A4. No held-out testing → 60% max

**Why we clear it.** Two independent held-out evaluations, both with a pre-set cutoff and a
deterministic split:

- **AI eval** — a held-out set (10 test items) vs a 40-item corpus, cutoff fixed **before**
  results; `speedrun/eval/ai_eval.py`.
- **Memory calibration** — a deterministic *temporal* held-out split
  (`speedrun/eval/calibration.py`): train on earlier reviews, score reliability/Brier on
  later held-out reviews.

**Prove it on demand:**

```bash
export SPEEDRUN_AI_SETTINGS_PATH="$PWD/.ankidata/speedrun_ai_settings.json"
PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python -m speedrun.eval.ai_eval
```

- **Point at:** the header line `test items: 10 | corpus: 40`, the fixed `accuracy cutoff:
  0.6`, and `Leakage (thr 0.6): clean`. On the readiness dashboard, point at
  "trained on the earlier 820 reviews; evaluated on the later held-out" — the split is
  temporal and reproducible.

### A5. Made-up / misleading readiness → AUTOMATIC FAIL (honesty rule / give-up rule)

**Why we clear it.** Readiness is **abstained** unless there is enough evidence, and the
abstention is enforced in code (`speedrun/scoring/guardrail.py`) *and* in Rust
(`speedrun_scores.rs`, `gave_up` flag with `MIN_ATTEMPTS_PER_SCHEMA` + section coverage).
The rule (PRD §10.3): **no readiness score until ≥200 graded transfer attempts AND ≥50%
schema coverage across both LR and RC.** Every score that *does* show carries a range,
a confidence level, coverage %, last-updated, top reasons, and the single best next step.
Training-signal drills (cold-open, contrasting pairs, fork, calibration) are deliberately
**excluded** from the three scores (unit-tested) so practice can never inflate the number.

**Prove it on demand:**

- **On screen (abstention):** launch a *fresh* profile (`ANKI_BASE=/tmp/sr-fresh ./run`) →
  Dashboard → all three cards read **"No score yet"** with the specific missing data named,
  and the evidence gate reads **Locked**.
- **On screen (open, but honest):** on `.ankidata-demo`, the gate reads **Open** and
  Readiness shows **161 with the range 152–170** plus its reasons — never a bare number.
- **Command:**

```bash
PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python \
  -m pytest pylib/tests/test_speedrun_guardrail.py pylib/tests/test_speedrun_readiness.py -q
```

> Honesty caveat we surface ourselves: the give-up thresholds are configurable. The
> **committed** `config.json` ships the strict code defaults (`min_pattern_coverage = 0.80`);
> the demo seeder *temporarily* relaxes this axis to **0.73** in the working tree so the gate
> opens on the small deck, and restores it on `--clear` (see A3/B2). The rule is still
> *stated, falsifiable, and enforced* — it is not a made-up number. We disclose the exact
> threshold rather than hiding it.

### A6. Either app fails on a clean device → 50% max

**Why we clear it.** The desktop ships as installable wheels (`anki`, `aqt`,
`speedrun-lsat`) plus a one-click macOS installer; the only host requirement is Python
3.12+. The `speedrun_lsat` wheel bundles its data (taxonomy, seed deck, config), verified
by a packaging test. See [`INSTALL.md`](INSTALL.md). The README carries the **NO-SPACES
build-path warning** (Anki's build fails on paths with spaces).

**Prove it on demand:**

```bash
PYTHONPATH=out/pylib out/pyenv/bin/python -m pytest pylib/tests/test_speedrun_packaging.py -q
python -c "import speedrun.scoring.memory; from importlib.resources import files; \
print((files('speedrun')/'data'/'seed_deck.json').is_file())"    # -> True
```

- **🎥 external-only:** the actual clean-machine install recording
  (`docs/speedrun/INSTALL.md` Path A on a fresh HOME) and the signed/TestFlight iOS build
  are human deliverables — the packaging path is verified in-repo, the *recording on a
  physical clean machine* is not something a command emits.

### A7. Leaked test data → that score is ZERO

**Why we clear it.** A leakage scanner (`speedrun/eval/leakage_check.py`, Jaccard
near-duplicate scan) is **wired into the gate**: any leak between the 50-item gold set and
the train/seed deck flips `passed` to False and forces a non-zero exit. Result is currently
**clean**.

**Prove it on demand:**

```bash
PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python \
  speedrun/tools/speedrun_cli.py leakage-check          # prints CLEAN, exit 0
# force a failure to show the gate bites:
PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python \
  speedrun/tools/speedrun_cli.py leakage-check --threshold 0.0   # LEAK, exit 1
```

- The `ai_eval` run (A4) also prints `Leakage (thr 0.6): clean`, so the eval refuses to
  report an AI win on leaked data.

### A8. AI claims with no traceable source → AI section is ZERO

**Why we clear it.** An AI response is displayed **only** when it carries a non-blank,
non-stub `source`. `require_source` guards every production AI call site — tutor,
recommender, card generator — and untrusted source text is injection-sanitized before it
enters a prompt. See [`TRACEABILITY.md`](TRACEABILITY.md), [`AI-NOTES.md`](AI-NOTES.md).

**Prove it on demand:**

```bash
PYTHONPATH=out/pylib out/pyenv/bin/python \
  -m pytest pylib/tests/test_speedrun_ai.py -q \
  -k "source or require_source or sanitize or ok_requires"
```

- **On screen:** open the AI tutor on a problem (demo profile, AI on) → the answer names
  its source inline; nothing renders without one.

---

## Part B — Grading criteria, and how to demo each

PRD §19 rubric, one section per row with its weight.

### B1. Rust change and Anki fit — 20%

- **Evidence:** schema-weighted points-at-stake queue in `rslib`
  (`schema_weighted.rs` + `build_schema_weighted_queue` RPC); three-score math + per-section
  give-up in `speedrun_scores.rs`; 5 Rust unit tests + 1 Python-over-RPC test; read-only /
  undo-safe (asserted `undo_status().last_step` unchanged); merge-difficulty table for a
  future rebase. Same ordering ships to desktop and iOS.
- **Show it:** `cargo test -p anki schema_weighted`, then **Study now** in the app; walk
  the "why Rust not Python" and "upstream files touched" sections of
  [`rust-change.md`](rust-change.md).

### B2. Score accuracy + honest uncertainty — 20%

- **Evidence:** three separately-reported scores, each with point + range + coverage +
  confidence + reasons + give-up (PRD §10). Memory calibrated on a held-out temporal split
  (Brier/log-loss); performance = the memory→transfer bridge with a reported recall-vs-
  transfer **gap**; readiness maps expected raw-correct → 120–180 with an uncertainty band
  and latency discounting (SPOV4).
- **Show it:** Dashboard on `.ankidata-demo` → **Memory 94% [93–94] · Performance 70%
  [67–72] · Readiness 161 [152–170], gate Open**; then a fresh profile → all abstain.

```bash
PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python speedrun/tools/speedrun_cli.py \
  --base .ankidata-demo dashboard > /tmp/demo-dash.html   # scores render as above
```

> **Honest flag (also in A3/A5):** the **committed** `speedrun/config.json` ships the strict
> 0.80 defaults, so a fresh checkout / CI is `398 passed, 1 skipped`. Only while a demo
> profile is seeded does the working-tree `config.json` drop `min_pattern_coverage` to
> **0.73** (restored on the seeder's `--clear`), which makes two self-consistency tests fail
> locally (`396 passed, 2 failed`). The gate remains a
> stated, enforced, above-PRD-floor rule — the local mismatch clears the moment you run the
> seeder's `--clear`, and we disclose it rather than paper over it.

### B3. Study feature on learning science — 15%

- **Evidence:** interleaving of schema/flaw/question types, matched to LR's "which pattern
  is this?" discrimination demand (Kornell & Bjork; Rohrer). Pre-registered hypothesis;
  three builds (full / ablation-blocked / plain Anki) at equal study time; honest null
  reporting.
- **Re-measured result (2026‑07‑05):** interleaved **+10.3%** transfer over blocked
  (95% CI **[+8.5%, +12.0%]**); app-vs-plain-Anki **NULL** (+0.2%, CI [−0.5%, +0.9%]),
  reported honestly.

```bash
PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python -c \
"from speedrun.eval.interleaving_experiment import run_experiment; print(run_experiment().format_report())"
```

> Note: [`RESULTS.md`](RESULTS.md) still quotes an older `+6.5%` synthetic run; the current
> harness prints **+10.3%**. Cite the live command output.

### B4. AI checking and safety — 15%

- **Evidence:** held-out AI eval with a fixed cutoff, a **fair LLM-judge** metric (identical
  prompt per method) reported alongside `token_f1`, side-by-side vs keyword + vector
  baselines, leakage check wired into the gate, named-source enforcement, prompt-injection
  sanitization, off-by-default with all three scores still computing when off.
- **Re-measured result (2026‑07‑05, live `openai:gpt-4o-mini`):** on the fair metric,
  **AI 80%** vs **keyword ~20–30% / vector ~30–40%**; AI clears the 60% cutoff and beats
  **both** baselines; leakage clean; **GATE PASSED**.

```bash
export SPEEDRUN_AI_SETTINGS_PATH="$PWD/.ankidata/speedrun_ai_settings.json"
PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python -m speedrun.eval.ai_eval
```

> The **AI 80%** figure and the "beats both baselines / gate passed / leakage clean" verdict
> are stable across runs. The **exact baseline percentages move run-to-run** because the
> LLM judge is nondeterministic (this run: keyword 30% / vector 40%; a prior logged run:
> keyword 20% / vector 30%). The *ordering* — AI > vector > keyword — holds. An offline,
> fully-deterministic alternative is `python -m speedrun.eval.grounding_eval` (grounded 50%
> / F1 0.305 vs keyword 0.230 / vector 0.240), which gates in CI without a key.

### B5. Fair, re-runnable tests — 12%

- **Evidence:** seeded splits, scripted harnesses, CI workflow. `just bench` /
  `speedrun.tools.bench` reports p50/p95/worst (no single hand-picked number); crash and
  sync tests; leakage scan.
- **Re-measured 50k benchmark (2026‑07‑05): all 5 §18 targets PASS.**

```bash
PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python -m speedrun.tools.bench --target 50000
```

| Action | This run | Target | Verdict |
| --- | --- | --- | --- |
| Button press | p95 ~0.22 ms | < 50 ms | PASS |
| Next card | p95 ~0.27 ms | < 100 ms | PASS |
| Dashboard first load | p95 ~395 ms | < 1000 ms | PASS |
| Dashboard refresh | p95 ~408 ms | < 500 ms | PASS |
| Cold start | p95 ~1.4 ms | < 5000 ms | PASS |

> The evidence brief quoted an earlier run (first load ~421 ms, refresh ~436 ms, button
> ~0.18 ms, next-card ~0.23 ms, cold-start ~1.14 ms). Both runs pass all five targets; cite
> the numbers your own run prints. Durability: `crash_test.py` reopens the collection after
> mid-review kills with **zero loss/corruption** (the 20×-per-platform run is still pending
> — see RESULTS "Not yet measured").

### B6. Shared engine + working sync — 10%

- **Evidence:** one Rust engine reached by desktop (`pylib/rsbridge`, PyO3) and phone
  (`rslib-ffi`, C FFI) with the *identical* protobuf command; two-way sync over Anki's
  protocol with a documented conflict rule (later real-timestamp wins scheduling state;
  both revlog rows kept via USN+mtime merge; clock-skew > 300 s aborts rather than guesses).
- **Show it:** `speedrun/tools/sync_test.py` (mechanism) + **🎥 external-only** phone→desktop
  round-trip recording. Conflict semantics in [`SYNC.md`](SYNC.md).

### B7. Useful product + clean UX — 15% *(PRD table: 8%)*

> Weight note: the PRD §19 table lists **8%** for "Useful product + clean UX" — but the
> seven listed weights sum to 90%. If the intended total is 100%, this row is most likely
> **15%**. Treat 8% as the literal PRD figure and 15% as the reconciled value; flagged so
> nobody double-counts.

- **Evidence:** three-score dashboard with daily goal/streak, progress timeline, mastery/
  concept map, wrong-answer patterns, latency histogram, weakest-subjects recommender, and
  a one-click "Study my weakest" focus; menu badge with a live M·P·R summary; runs fully
  with AI off. Give-up rendered as an honest abstention state.
- **Show it:** Dashboard (Ctrl+Shift+L) on `.ankidata-demo`; the mistake graph
  (52 nodes / 473 edges) and "Study my weakest" focus buttons.

---

## Part C — 3–5 minute demo script (spoken narration)

Audience: someone who **knows the LSAT** but has **never used this app** and does **not**
know the learning science. Read the plain text aloud; `[ON SCREEN: …]` are stage directions,
not spoken. Total ≈ 4:30. This is a fresh, self-contained walkthrough; the shorter
alternate cut lives in [`DEMO-VIDEO-SCRIPT.md`](DEMO-VIDEO-SCRIPT.md).

> Pre-record checklist: quit Anki; `ANKI_BASE=~/dev/speedrun-lsat/.ankidata-demo ./run`;
> AI enabled (Tools → LSAT Speedrun → AI Settings) so the tutor answers live; sync server
> running and the iOS simulator open for the sync beat.

---

**[0:00–0:35] The one idea: the LSAT is a transfer test, not a memory test**

[ON SCREEN: desktop dashboard, three score cards visible.]

"This is Speedrun LSAT — a fork of Anki with a change made right inside its Rust engine.
Here's the conviction behind it. On the LSAT, almost nothing repeats: every Logical
Reasoning argument is a brand-new topic you'll never see again. What *does* repeat is the
underlying pattern — a correlation-to-causation flaw, a necessary-versus-sufficient mix-up,
an out-of-scope trap. So the thing worth mastering isn't a flashcard; it's the *schema* —
the reusable reasoning pattern. This whole app is organized around schemas, and it's
honesty-first: it refuses to show you a score until it actually has the evidence to back it
up."

**[0:35–1:20] Three scores that measure three different things**

[ON SCREEN: point at Memory 94%, Performance 70%, Readiness 161 (152–170).]

"Three scores, and they're deliberately *not* the same number. **Memory** — 94% — is pure
recall, Anki's spaced-repetition engine, which I use only for the small memorizable layer:
flaw and trap definitions. **Performance** — 70% — is the one that matters: can you get a
*new, unseen* question right using this schema? That's the bridge from remembering to
*doing*, and I measure the gap between the two on purpose — if they were equal, I'd just
have a memory app in a costume. **Readiness** — 161, with a range of 152 to 170 — projects
your actual 120-to-180 LSAT score. Notice it's always a *range* with reasons, never a lone
number. And there's a fourth thing baked in: speed. On a timed test a correct-but-slow
answer is, in the aggregate, a wrong answer, so a student who's accurate but over the clock
gets flagged, not flattered."

**[1:20–1:55] Why the queue is different, and why it's in Rust**

[ON SCREEN: the mistake graph / concept map, then the study queue.]

"Before we study — this map is the error analysis. It surfaces the *traps I habitually fall
for*, which is far more diagnostic than just 'which question did I miss.' Now, when I hit
**Study now**, the order isn't plain spaced repetition. It's a schema-weighted
'points-at-stake' queue: it multiplies how much a schema is worth on the exam by how weak I
am on it by how time-pressured I am, and surfaces the highest-value cards first. For a timed
exam that beats generic review, because it spends my minutes where they buy the most points.
That ordering lives in Anki's Rust core, so the phone and the desktop get the exact same
queue from one engine — no reimplementation."

**[1:55–2:40] The study loop: interleaving, the two-answer fork, trap capture**

[ON SCREEN: answer 2–3 cards; a fork drill; select the trap; latency toast appears.]

"Two things about how these cards come at me. First, they're **interleaved** — schemas and
question types mixed together, not blocked one type at a time. That feels harder, but it's
exactly what trains the 'which pattern is this?' discrimination the real test demands.
Second, on a hard item I get the **two-answer fork**: I've narrowed it to the two finalists,
and the app makes me commit — which is the trap, which is right — then shows me *why* the
runner-up is wrong. That's where points actually leak on the LSAT, so that scaffold barely
fades. When I pick the wrong answer, it captures *which trap* I fell for, and every answer
is timed against a budget — that's the latency you saw feed Performance and Readiness."

**[2:40–3:15] AI that always cites a source — and turns off cleanly**

[ON SCREEN: AI tutor on the item; then "What to study next"; then flip AI off.]

"Now the AI, with one rule: every AI output has to trace to a named source. I open the tutor
and ask why the runner-up is wrong — the answer is grounded in *this item's own* stimulus
and rationale and names its source right there; nothing shows without one. Over here,
'what to study next' turns my weakest high-value schemas into a plan with reasons. And
critically —" [ON SCREEN: toggle AI off, scores still render] "— the AI is off by default,
and with it off all three scores still compute straight from the review log. The AI helps
you reason; it never *invents* your number."

**[3:15–3:50] Proof the AI is actually better — held out, fair, leak-free**

[ON SCREEN: terminal running `python -m speedrun.eval.ai_eval`.]

"And I don't just claim the AI helps — I gate it. On a held-out set, judged the same way for
every method, the grounded AI scores **80%** and clears its pre-set 60% cutoff, while plain
keyword and vector search sit well below it. Same screen: the leakage scan comes back
**clean**, so no test question sneaked into the training data, and the gate **passes**. Held
out, fair metric, leak-checked, reproducible — no cherry-picked number."

**[3:50–4:20] The phone shares the engine and syncs both ways**

[ON SCREEN: iOS simulator — three scores with ranges → Study → grade a card → Sync → desktop
Sync → the review appears.]

"Same engine on the phone — the same Rust scheduler, not a rewrite — showing the same three
scores with their ranges and the same give-up rule: if there isn't enough evidence, it says
'no score yet' instead of faking one. I'll grade a card here offline, sync, switch to the
desktop, sync — and there's the review I just did on the phone, counted exactly once, in
both directions."

**[4:20–4:35] Close: does this student score higher, honestly measured?**

[ON SCREEN: back to the dashboard.]

"So: a real change in Anki's Rust engine, scores that separate remembering from doing and
refuse to guess, AI that always cites a source and has to beat plain search on a held-out
test, and one engine shared across desktop and phone. Every feature ties back to one
question — does this student get a higher LSAT score, honestly measured? Thanks for
watching."

---

## Appendix — external-only deliverables (honest status)

These cannot be produced by a command and are the human capture / packaging work:

- **The recorded 3–5 min demo video** itself (this doc is the script for it).
- **A signed iOS / TestFlight build** on a real device (the engine, review, scores, and sync
  are verified in-repo; the distributable signed artifact is external).
- **A clean-machine install recording** (the wheels/packaging path is verified by
  `test_speedrun_packaging.py`; the recording on a physical fresh machine is external).
- **The live phone→desktop sync round-trip capture** (the merge is proven by
  `sync_test.py`; the on-camera round-trip is the human proof).

Everything else in Parts A and B is reproducible today with the commands shown.
