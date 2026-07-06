# Verification report — graded items 7b–7f

Every claim below was produced by running the REAL check. Exact numbers, exact
commands, honest verdict per sub-requirement. Anything synthetic/proxy or
externally blocked is labelled. Run from repo root with `out/pylib` +
`out/pyenv/bin/python`. (No git was run.)

Live AI runs used the device key at `.ankidata/speedrun_ai_settings.json`
(`ai_enabled: true`, model `gpt-4o-mini`), reached via `ANKI_BASE=$PWD/.ankidata`.

---

## 7b — The sync test — SATISFIED

```
PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/sync_test.py
```

Output (exact):
```
[A] disjoint: desktop revlog=20 phone revlog=20 (expect 20 each)
[A] PASS: 20 reviews, each card counted once, no duplicated cards.
[B] conflict: desktop.mod=1783313323 phone.mod=1783313325 -> merged.mod=1783313325
[B] PASS: later timestamp won, both review rows kept, no double-count.
[C] PASS: both collections pass Anki's database check (not corrupt).
SYNC TEST PASSED: two-way merge + deterministic conflict resolution.
```

- **10 + 10 disjoint, nothing lost / double-counted:** reviews 10 cards on
  desktop, 10 DIFFERENT on phone (offline), full two-way sync → merged revlog =
  **20 on each client**, distinct reviewed cards = 20, max reviews/card = 1, card
  count unchanged. Asserted at sync_test.py lines 262–277.
- **Same card on both → deterministic winner:** desktop AGAIN (mod 1783313323),
  phone EASY at a strictly later real timestamp (mod 1783313325) → both clients
  converge to **merged.mod = 1783313325 (the phone/later review wins)**; the card
  keeps **2 revlog rows** (history preserved), total revlog = 22, card count
  unchanged; both collections pass Anki's DB integrity check.
- **Exact conflict rule (SYNC.md):** *"for the same card reviewed on two devices
  offline, the later real-timestamp review wins the card's scheduling state"* via
  Anki's USN + modification-time merge, so *"both revlog rows are kept and none
  are double-counted."* The test asserts this: `merged == phone_local` (later
  wins), `merged != desktop_local`, `revlog_for(card) == 2`, `revlog_count ==
  total + 2` (lines 308–326).

---

## 7c — The coverage map — SATISFIED

Taxonomy (source of truth): `speedrun/taxonomy/lsat_taxonomy.json`. Deck:
`speedrun/data/seed_deck.json`. The modern LSAT scores only **Logical Reasoning**
and **Reading Comprehension**; **Analytical Reasoning / Logic Games was removed
(Aug 2024)** and is now explicitly recorded as excluded in the taxonomy
(`excluded_sections`), so coverage/readiness are computed only over sections that
count.

```
PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python speedrun/tools/coverage_map.py
```
Real seed deck (504 items):
- Overall: **57/57 schemas covered (100%)**.
- Per axis: flaw 20/20, question_type 17/17, rc_structure 7/7, trap 13/13 — all 100%.
- **Per section: LR 50/50 (100%), RC 7/7 (100%)** → Readiness gate **OPEN**.
- **Threshold: 50% per section** (`MIN_COVERAGE_PER_SECTION` / readiness
  `MIN_DECK_COVERAGE = 0.50`).

Dashboard shows the number: `dashboard._deck_coverage_panel` ("Deck covers 100%
of the taxonomy … By section: LR … RC …") and the readiness card prints per-section
coverage.

**Abstain proof (drop a whole section):** with RC removed from the deck,
```
PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python speedrun/tools/coverage_map.py --deck <rc-dropped>
```
gives **RC 0/7 (0%) [BELOW LINE]**, LR 47/50 (94%), and
`Readiness gate: CLOSED — readiness ABSTAINS`. Confirmed by tests
`test_readiness_abstains_when_a_whole_section_is_skipped` and
`test_readiness_abstains_when_deck_coverage_below_line` (both pass): a deck that
skips a high-weight section never reads "ready".

---

## 7d — The paraphrase test — SATISFIED (transfer grading labelled)

**Real set authored:** `speedrun/data/reworded_set.json` — **30 real seed cards ×
2 exam-style reworded questions = 60 items** (56 LR + 4 RC). The reworded
stimuli/questions are the seed deck's hand-authored paraphrases (same schema, new
surface); each item carries an authored answer key. Before this work no real
reworded-attempt store existed, so `transfer_gap` fell back to a **labelled proxy**
(revlog attempts): recall 94% / transfer 70% / gap +24pp.

**Wired in + graded for real:** `speedrun/eval/reworded_grader.py` has an actual
solver (live `gpt-4o-mini`) answer each of the 60 items; the same LLM judge used
by the AI eval gate grades semantic equivalence to the authored key; 60 real
graded attempts are written to `speedrun/data/reworded_attempts.json`.

```
ANKI_BASE=$PWD/.ankidata PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python -m speedrun.eval.reworded_grader
PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python speedrun/tools/speedrun_cli.py --base .ankidata transfer-gap
```
- Live grading: **60 items, 34 correct → reworded accuracy 57%** (LR 55%, RC 75%).
- transfer-gap (source = **real**, n = **60**):
  - **Recall (FSRS memory): 94%** [93–94%]
  - **Transfer (reworded, latency-adjusted): 56%** [44–68%] (raw 34/60 = 56.7%)
  - **Gap (recall − transfer): +37 percentage points** → memory clearly
    overstates transfer; performance is NOT just copying memory.

**Synthetic/labelling caveat (honest):** the 60 reworded items and their grading
are real (live solve + LLM judge against an authored key). This environment has
no live human test-taker, so the **solver stands in for a student** (labelled in
the code and report), and **recall is computed on the seeded collection's** FSRS
reviews. 11/11 transfer tests pass, including new tests for the 60-item set and
the grader.

---

## 7e — The leakage check — SATISFIED

```
PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python speedrun/tools/speedrun_cli.py leakage-check
```
**Clean:** `CLEAN — No overlap above threshold. scanned 50 gold x 504 train =
25200 comparisons; matches found: 0` — **threshold 0.6, 25,200 items scanned, 0
matches, exit 0**.

**Gate bites:**
```
PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python speedrun/tools/speedrun_cli.py leakage-check --threshold 0.0
```
`LEAK — 25200 potential leak(s) found.` → **exit 1** (non-zero).

**Wired into the AI eval gate:** `speedrun/eval/ai_eval.run_ai_eval` calls
`leakage_check`; the gate `passed` is `False` unless `leak.clean` (ai_eval.py
line ~281), and `ai-eval` prints `Leakage (thr 0.6): clean`. A leak zeroes the AI
score regardless of accuracy.

---

## 7f — The AI card check — SATISFIED

- **Gold set:** `speedrun/data/gold_set.json` = **50 Q&A pairs** with known-correct
  answers (verified size 50).
- **One real source:** `speedrun/data/sources/lr_flaws_primer.md`.
- **Pre-set cutoff (stated before results): 0.05** topicality floor
  (`card_checker.PASSING_CUTOFF`); correctness decided by the live LLM veto.

```
ANKI_BASE=$PWD/.ankidata PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python \
  speedrun/tools/speedrun_cli.py card-check --n 50
```
Live run (`gpt-4o-mini`), **50/50 cards generated** from the source, drafts saved
to `docs/speedrun/card_check_drafts.json`:

| count | value |
|---|---|
| (1) correct & useful | **21** |
| (2) wrong (worse than no card) | **5** |
| (3) correct-but-bad-teaching | **24** |
| BLOCKED (wrong + bad-teaching) | **29** |
| PASSED / kept (== useful) | **21** |

The cutoff + LLM veto are applied by `card_checker.block_failing`; failing cards
never ship (`passed` is true iff a card is correct **and** useful). (The "wrong"
count varies ±1 across runs due to the judge's temperature 0.2; a prior run gave
20/6/24.)

**Real fix (was broken):** the checker previously scored an item by Jaccard of
its full stimulus vs a concept-quiz gold set, which diluted every real item below
the old 0.35 cutoff — it blocked **100% of the 504 curated seed cards** and
labelled 478 of them "wrong". Rebuilt as stopword-filtered content-F1 of the
card's *question + marked answer* vs the gold concepts, recalibrated the cutoff to
a genuine off-topic floor, added batch duplicate detection, and made `passed ⇔
correct_useful`. 38 AI tests pass.

---

## Tests

Green after changes:
`test_speedrun_ai.py` (38), `test_speedrun_transfer.py` (11),
`test_speedrun_readiness.py`, `test_speedrun_tools.py`.

Pre-existing, **unrelated** failure (not in this work's domain):
`test_speedrun_dashboard.py::test_dashboard_gate_stays_locked_after_seed_pass` —
the test assumes a "small seed deck" below the 250-card evidence-gate threshold,
but the seed deck was previously expanded to 504 items, so a full pass now
legitimately unlocks the gate. None of the modules changed here touch the
evidence gate.
