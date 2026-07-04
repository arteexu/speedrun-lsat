# Speedrun LSAT — Content Audit & Course-Scaling Plan

_Analysis only. No items authored; no pipeline/deck/dashboard files edited. Numbers computed
with `out/pyenv/bin/python` over `speedrun/data/seed_deck.json` (v0.2.0) and
`speedrun/taxonomy/lsat_taxonomy.json` (v0.1.0)._

---

## TL;DR — Is 105 enough?

**No — not for a "course," but the foundation is unusually solid.** 105 items is a strong,
fully-tagged *scaffold*: it already touches **every non-trap schema in the taxonomy (44/44)**
and exercises **all 13 traps** as distractors. That is enough to *exercise the pipeline and every
app feature*. It is **not** enough to (a) give spaced repetition real depth per schema, (b) feed
the transfer/readiness models (there are **0 paraphrase items**, and the give-up rule needs
**≥200 graded transfer attempts**), or (c) *feel* like a structured curriculum (there is **no
unit/lesson/module structure** in the data model — only RC `passage_id` grouping).

**Recommended targets** (reasoned below):
- **"Good coverage" (models can run honestly): ~200–230 items** — every primary schema ≥4–5 items, plus ≥2 paraphrases on ≥40 items to seed the transfer test.
- **"Feels like a v1 course": ~350 items** — ~270 LR + ~80 RC (8–10 passages), grouped into ~8 modules with checkpoints.
- Per-schema floor: **≥5 items per flaw, ≥5 per LR question-type, ≥4 per RC structure across ≥2 passages.** Traps need no standalone items (they live on choices).

The single biggest *content* gap is **depth, not breadth**, plus **RC volume** and **paraphrase/transfer data**. The single biggest *structural* gap is the missing `unit`/`lesson` grouping — a small, additive, backward-compatible data-model change (spec'd in §5, not implemented).

---

## 1. Content audit (quantitative)

### 1.1 Seed deck totals (`seed_deck.json` v0.2.0)

| Metric | Value |
| --- | --- |
| Total items | **105** |
| Section: LR | **89** (`lr-0001`..`lr-0089`, contiguous) |
| Section: RC | **16** (5 passages: `rc-0001/0002/0025/0100/0101`, 3–4 q each) |
| Section: LG / other | **0** (correct — LG is out of scope per PRD §4) |
| Distinct primary schemas used | **46** |
| Distinct traps used as distractors | **13 / 13** |
| Items with `two_answer_fork` | **105 (100%)** |
| Items with `paraphrases` | **0** ⚠️ |
| Choices per item | 5 on every item (exactly 1 correct — enforced) |

**Difficulty distribution (1=easiest … 4=hardest):**

| Difficulty | 1 | 2 | 3 | 4 |
| --- | --- | --- | --- | --- |
| LR | 1 | 26 | 47 | 15 |
| RC | 0 | 0 | 13 | 3 |
| **All** | **1** | **26** | **60** | **18** |

Skew: heavily mid-hard (d3 = 57%), almost no easy on-ramp (one d1 item), and **RC has no d1/d2 at all** — bad for a course that should ease learners in.

**Question-type (stem_type) distribution** — note the dominance of `qt.flaw`:

| stem_type | n | | stem_type | n |
| --- | --- | --- | --- | --- |
| qt.flaw | **37** | | rc.main_point | 3 |
| qt.inference_must_be_true | 9 | | rc.author_attitude | 3 |
| qt.weaken | 7 | | qt.parallel_reasoning | 3 |
| qt.necessary_assumption | 4 | | qt.parallel_flaw | 3 |
| qt.strengthen | 4 | | qt.main_conclusion | 3 |
| qt.most_strongly_supported | 3 | | (13 more types at 2) | 2 each |
| qt.method_of_reasoning | 3 | | qt.principle_identify | **1** |

`qt.flaw` alone is 35% of the deck; 8 question types sit at the n=2 floor and one at n=1.

### 1.2 Taxonomy coverage (`lsat_taxonomy.json` v0.1.0)

**57 schemas total** across 4 axes: **flaw 20, question_type 17, trap 13, rc_structure 7.**

| Axis | Schemas | With ≥1 item | Coverage | Notes |
| --- | --- | --- | --- | --- |
| flaw (primary) | 20 | 20 | **100%** | breadth complete; depth thin (11 at n=2) |
| question_type | 17 | 17 | **100%** | breadth complete; 8 at n=2, 1 at n=1 |
| rc_structure | 7 | 7 | **100%** | all at n=2–3 only |
| trap | 13 | 13 (as distractors) | **100%** | by design: traps live on `choices[].trap`, not `schemas[]` |
| **Total** | **57** | **57** | **100% breadth** | **exam_weight covered: flaw 0.85/0.85, qt 0.97/0.97, rc 1.00/1.00** |

**Coverage verdict: breadth is effectively complete; the gaps are depth, difficulty balance, RC volume, and transfer data — not missing schemas.** (This is enforced: `coverage_map.py` exits non-zero if any item references an unknown schema id, so every tag is guaranteed to exist in the taxonomy.)

### 1.3 Ranked depth gaps (lowest-coverage primary schemas — the real "gap list")

These have items but are too thin for spaced repetition + held-out transfer. Ranked by exam_weight (fill high-weight first):

**Question types at the floor:**
| schema | weight | items |
| --- | --- | --- |
| qt.principle_identify | 0.040 | **1** |
| qt.sufficient_assumption | 0.060 | 2 |
| qt.paradox | 0.060 | 2 |
| qt.principle_apply | 0.030 | 2 |
| qt.role_of_statement | 0.030 | 2 |
| qt.point_at_issue | 0.020 | 2 |
| qt.evaluate | 0.020 | 2 |

**Flaws at the floor (all n=2):** `flaw.conditional.nec_suff_confusion`, `flaw.conditional.mistaken_reversal`, `flaw.conditional.mistaken_negation`, `flaw.causal.reversed`, `flaw.causal.common_cause`, `flaw.sampling.appeal_to_ignorance`, `flaw.scope.part_whole`, `flaw.scope.percent_vs_number`, `flaw.structure.ad_hominem`, `flaw.structure.straw_man`, `flaw.structure.false_dilemma`.

**RC structures at the floor (all n=2):** `rc.passage_organization`, `rc.viewpoint_attribution`, `rc.function_of_detail`, `rc.inference`, `rc.comparative_relationship`.

Traps are well-distributed as distractors (`trap.out_of_scope` 167, `trap.too_strong_extreme` 64, down to `trap.rc.*` at 7–10) — no trap needs standalone authoring.

### 1.4 Non-flashcard content the app consumes

The **seed deck is the single content source** — nearly every feature derives from it (verified by grep):

- `contrasting.py` — contrasting/discrimination pairs, built from `seed_deck.json`.
- `cold_open.py`, `fork_trainer.py` — cold-open diagnostic & two-answer-fork trainer, slice items from the deck.
- `rc_commentator.py`, `explanations.py` — RC commentary & explanations over deck items.
- `eval/transfer_gap.py`, `eval/leakage_check.py` — transfer test & leakage check.
- `ai/tutor.py`, `ai/card_checker.py` — AI tutor & generated-item checker.
- Separate data: `data/gold_set.json` (**50** gold Q&A pairs for the AI card checker) and `data/sources/lr_flaws_primer.md` (**1** license-clean source for the generator).

**Implication:** every item you add automatically enriches contrasting pairs, cold-open, fork trainer, and the dashboards — but there is **no dedicated "explainer/lesson" content type**. Lessons would either be authored as intro items or added as a light content type (see §5).

### 1.5 Reconciliation with PRD vision

- PRD §4 scopes **LR + RC only, LG permanently out** → deck matches (0 LG). ✅
- PRD §8 makes **schema the unit, flaw primary** → deck is schema-tagged, flaw-heavy. ✅
- PRD §10.3 give-up rule: **no readiness until ≥200 graded transfer attempts AND ≥50% schema coverage across LR and RC.** Schema coverage is already >50% both sections, but **transfer attempts require novel/paraphrase items and there are 0 paraphrases** → readiness model currently can't clear the bar on real data. ⚠️
- PRD §17 transfer test: **30 cards × 2 reworded each** → needs ≥60 paraphrase variants; **0 exist today.** ⚠️
- PRD never specifies a course/module structure or a target item count — this plan proposes both.

---

## 2. Sufficiency judgment

**Bar for "enough":** a learner needs, per schema, enough *instances* that (a) FSRS has multiple cards to space, (b) the transfer model can hold some items out and still train, and (c) interleaved drills don't repeat the same 2 arguments. One or two items per schema fails all three — the student memorizes the specific argument (the exact failure mode SPOV1 warns about) instead of the transferable pattern.

**Judgment:** 105 items **proves the system** but is **~1/3 of a v1 course** and **cannot yet feed the honesty-critical readiness model**. Concrete targets:

| Milestone | Per-schema floor | LR | RC | Total | Unlocks |
| --- | --- | --- | --- | --- | --- |
| **Today** | many at 1–2 | 89 | 16 | 105 | pipeline + all features exercised |
| **Good coverage** | flaw ≥4, qt ≥4, rc ≥4 + **paraphrases on ≥40 items** | ~150 | ~50 | **~200–230** | honest transfer/readiness on real data |
| **v1 course** | flaw ≥5, qt ≥5, rc ≥4 across ≥8 passages | ~270 | ~80 | **~350** | curriculum feel: modules + checkpoints |
| **Depth (stretch)** | ≥8 per high-weight schema, balanced d1–d4 | ~450 | ~120 | **~570** | robust held-out eval, difficulty ramps |

Rationale for ~350: a real LSAT is ~50 LR + ~27 RC questions per sitting; a course wants several sittings' worth of *distinct* material plus diagnostics and checkpoints, weighted ~2:1 LR:RC to mirror the exam.

---

## 3. Existing content pipeline (precise how-to)

### 3.1 Add items — the `NEW_ITEMS` append pattern

`speedrun/tools/add_practice_items.py` holds a `NEW_ITEMS: list[dict]`. `main()` reads the seed
deck, appends any item whose `id` is not already present (**idempotent — safe to re-run**),
asserts **exactly one correct choice**, and rewrites `seed_deck.json` (2-space indent).

Choices use the helper `_c(cid, text, correct=False, trap=None)`.

**Required item schema** (fields the importer reads — see `import_seed_deck.py`):

```python
{
    "id": "lr-0090",                 # unique; "lr-"/"rc-" prefix by section
    "section": "LR",                 # LR | RC
    "stem_type": "qt.weaken",        # a qt.* / rc.* id from the taxonomy
    "schemas": ["flaw.causal.reversed", "qt.weaken"],  # primary flaw/rc first, then qt
    "difficulty": 3,                 # 1..4
    "source": "original",            # provenance
    "stimulus": "...",               # LR: the argument (RC uses "passage" + "passage_id")
    "question": "...",
    "choices": [ _c("A", "...", correct=True), _c("B", "...", trap="trap.out_of_scope"), ... ],
    "two_answer_fork": {"runner_up": "B", "why_runner_up_wrong": "..."},
    # optional: "paraphrases": [{"stimulus": "...", "question": "..."}]  # feeds transfer test
}
```

**Tagging rules (enforced):**
- Every id in `schemas[]` and every `choices[].trap` **must exist in `lsat_taxonomy.json`** — `coverage_map.py` fails otherwise.
- The importer routes tags by prefix: `flaw.*`/`rc.*` → `sr:schema:`, `qt.*` → `sr:qtype:`, `trap.*` → `sr:trap:`, plus `sr:section:`. The **primary** schema (first `flaw.*`/`rc.*`, else first schema) becomes the mastery unit the schema-weighted queue reads. Friendly `LSAT::…` Browse tags are auto-derived.
- RC items: use `passage` + `passage_id` (shared across a passage's questions) instead of `stimulus`; ids like `rc-0102-q1`.

### 3.2 Run the pipeline (commands)

```bash
# 1) Append the new batch to the seed deck (idempotent)
PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/add_practice_items.py

# 2) Validate coverage + that every schema/trap id exists in the taxonomy (non-zero on error)
out/pyenv/bin/python speedrun/tools/coverage_map.py

# 3) Import into a collection (auto-backup first)
PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/import_seed_deck.py \
    --base ~/dev/speedrun-lsat/.ankidata        # or --col /path/to/collection.anki2

# 4) Regenerate the bundled iOS exam deck so mobile stays in sync
PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/export_exam_deck.py
#   → ios/Resources/exam/{collection.anki2, SpeedrunExam.colpkg}
```

(`expand_seed_deck.py` is an older bulk-authoring variant of the same append pattern.)

### 3.3 AI / generator tooling (present)

There **is** an AI authoring path, gated behind the AI-off switch:

- `speedrun/ai/card_generator.py` → `generate_items(source_path, n, id_prefix="gen")`: prompts the LLM (`ai/client.py`, model in `ai/config.py`) to emit items **using only flaws/traps from one named source** (`data/sources/lr_flaws_primer.md`), sanitizes the source (`ai/guard.py`, prompt-injection defense), stamps `source="generated:<stem>"` + `source_model`, and validates "exactly one correct." **With AI off / no key it returns `[]` (never fabricates).**
- `speedrun/ai/card_checker.py` → `check_items(...)` runs every generated item against the **50-pair gold set** (`data/gold_set.json`) and buckets them **correct-&-useful / wrong / correct-but-bad-teaching** with a pre-set cutoff (PRD §14.1).

**Recommended authoring loop:** generate with `card_generator` → filter with `card_checker` → hand-review survivors → paste the survivors into `NEW_ITEMS` (converting to the `_c()` form, adding `two_answer_fork` + a real `source`) → run §3.2. This keeps the durable deck 100% reviewed while using AI to draft. Pure-manual/agent authoring uses the same `NEW_ITEMS` path directly.

---

## 4. Proposed course structure (curriculum feel)

Map the schema taxonomy onto **~8 modules → lessons → graded drills → checkpoint**, reusing existing features rather than inventing new ones:

| Module | Focus (schemas) | Feature hooks |
| --- | --- | --- |
| 0. Diagnostic | mixed cold-open across all axes | `cold_open.py` (pretest) |
| 1. Argument foundations | main_conclusion, role_of_statement, method_of_reasoning | contrasting pairs |
| 2. Assumption family | necessary/sufficient assumption, flaw, gap.unwarranted_assumption | two-answer fork (slow-fade) |
| 3. Causal reasoning | all `flaw.causal.*` + weaken/strengthen/evaluate | contrasting pairs (discrimination) |
| 4. Conditional logic | `flaw.conditional.*` + parallel/parallel_flaw | `logic_diagram.py` |
| 5. Strengthen / Weaken / Paradox | qt.strengthen, weaken, paradox, evaluate | fork trainer |
| 6. Inference family | inference_must_be_true, most_strongly_supported, principle_* | — |
| 7. Point at issue & parallel | point_at_issue, parallel_reasoning, parallel_flaw | contrasting pairs |
| 8. Reading Comprehension | all `rc.*` (structure, attitude, function, comparative) | `rc_commentator.py` |

**Progression pattern per module:** lesson intro item(s) (low difficulty, scaffolding on) → interleaved graded drill (mixed schemas within the module) → **checkpoint** = a held-out mixed-schema set (feeds the interleaving experiment, PRD §15, and transfer test, §17). The **schema-weighted queue already orders by schema weight × weakness**, so modules layer *on top* of the existing engine without changing scheduling.

---

## 5. Minimal data-model change for course grouping

**Current state:** items have **no** `unit`/`module`/`lesson`/`order`/`tags` field. The only grouping is RC `passage_id`. So a curriculum ordering cannot be expressed today.

**Smallest change that enables it (spec only — do NOT implement here):**

1. **Item-level (optional, additive, backward-compatible):**
   ```jsonc
   "unit": "m3-causal",   // module id
   "lesson": 2,            // lesson within the module (int)
   "order": 40             // sort key within a lesson
   ```
   All optional → existing 105 items remain valid; absent = "unassigned."
2. **Deck-level curriculum manifest** (new top-level key in `seed_deck.json` or a sibling `curriculum.json`):
   ```jsonc
   "units": [
     {"id": "m3-causal", "title": "Causal reasoning", "schemas": ["flaw.causal.*"], "checkpoint": true}
   ]
   ```
3. **Importer**: emit a `sr:unit:<id>` machine tag (and optional `LSAT::Unit::…` friendly tag) in `build_tags()`, mirroring the existing `sr:schema:` pattern — one small addition, no scheduler change. Dashboard/queue can then group and report per-module mastery.

This is ~1 optional field + 1 manifest + ~5 lines in the importer. Because it's additive, it can land **before** or **after** the authoring phases without reflowing existing content.

---

## 6. Phased content roadmap

| Phase | Goal | Target counts | Type |
| --- | --- | --- | --- |
| **P1 — Depth on LR** | Bring every thin LR schema to floor; add d1/d2 on-ramps | flaws→≥5 each, qt→≥5 each (esp. principle_identify 1→5, sufficient_assumption, paradox, evaluate, point_at_issue, role_of_statement); **LR ~150** | pure authoring (`NEW_ITEMS`) |
| **P2 — RC build-out** | Real RC volume with full passages | **8–10 passages × ~6 q ≈ 50–60 RC**; every `rc.*` structure ≥4 across ≥2 passages; add d2 RC | pure authoring |
| **P3 — Transfer data** | Feed readiness/transfer + give-up rule | **≥2 `paraphrases` on ≥40 items** (≥60 variants → clears §17's 30×2) | authoring (uses existing optional field) |
| **P4 — Course structure** | Curriculum grouping + checkpoints | add `unit`/`lesson` to items + `units` manifest + importer tag; assign all items to 8 modules | **small data-model change (§5)** + authoring |
| **P5 — Depth & difficulty balance** | Robust held-out eval; smooth ramps | high-weight schemas →≥8; balance d1–d4 per module; **total ~350→570** | pure authoring |

Phases 1–3 and 5 are **pure authoring** through the existing `NEW_ITEMS` pipeline. Only **Phase 4** needs the small additive schema change in §5. Do P3 early — it is the only thing unblocking honest readiness numbers.

---

## 7. Worked example — add one fully-tagged item + verify

Append to `NEW_ITEMS` in `speedrun/tools/add_practice_items.py` (fills the `qt.principle_identify` floor, currently n=1):

```python
{
    "id": "lr-0090", "section": "LR", "stem_type": "qt.principle_identify",
    "schemas": ["qt.principle_identify"],
    "difficulty": 3, "source": "original",
    "stimulus": "The museum let a donor skip the entry line because she had given generously. "
                "But everyone in line had paid the same admission, so the museum treated equal "
                "customers unequally.",
    "question": "Which one of the following principles, if valid, most helps to justify the reasoning?",
    "choices": [
        _c("A", "Those who pay the same price for the same service are entitled to the same treatment.", correct=True),
        _c("B", "Museums should reward their most generous donors.", trap="trap.opposite"),
        _c("C", "Charitable giving should never influence public institutions.", trap="trap.too_strong_extreme"),
        _c("D", "Customers who wait in line deserve a discount.", trap="trap.out_of_scope"),
        _c("E", "A museum may set any admission policy it wishes.", trap="trap.out_of_scope"),
    ],
    "two_answer_fork": {"runner_up": "C",
        "why_runner_up_wrong": "C is too strong — it bans all donor influence, more than the argument needs; "
                               "A states exactly the equal-treatment principle the conclusion relies on."},
    # optional, feeds the transfer test (Phase 3):
    "paraphrases": [{
        "stimulus": "A frequent flyer was allowed to board before others holding the same economy ticket.",
        "question": "Which principle most helps to justify calling this unequal treatment?"
    }],
},
```

Verify:

```bash
# append (idempotent)
PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/add_practice_items.py
#   → "Added 1 new items. Total now: 106."

# taxonomy + coverage check (must exit 0)
out/pyenv/bin/python speedrun/tools/coverage_map.py

# quick sanity: confirm it landed and is well-formed
out/pyenv/bin/python -c "import json; d=json.load(open('speedrun/data/seed_deck.json')); \
it=[i for i in d['items'] if i['id']=='lr-0090'][0]; \
assert sum(c['correct'] for c in it['choices'])==1; print('ok', it['stem_type'], len(d['items']))"

# import + re-export the iOS deck
PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/import_seed_deck.py --base ~/dev/speedrun-lsat/.ankidata
PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/export_exam_deck.py
```

---

## Appendix — commands used for this audit

```bash
out/pyenv/bin/python -c "import json,collections; d=json.load(open('speedrun/data/seed_deck.json')); \
t=json.load(open('speedrun/taxonomy/lsat_taxonomy.json')); ..."   # totals, section/stem/difficulty, schema & trap usage
out/pyenv/bin/python speedrun/tools/coverage_map.py               # taxonomy-vs-deck coverage + unknown-id guard
```
