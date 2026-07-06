# LSAT Speedrun BrainLift — Teaching the LSAT as a Skill, Not a Fact Base

> The learning-science foundation for Speedrun LSAT. This is the in-repo,
> tracked version of the BrainLift. The original document is kept alongside it as
> [`LSAT-BrainLift-Arthur.pdf`](LSAT-BrainLift-Arthur.pdf).

**Owner:** Arthur Xu

Every **Spiky POV (SPOV)** and **Insight (I#)** referenced from the codebase and
docs (e.g. `BrainLift SPOV4`, `Insight 8`) resolves to an entry below. See
[§ "Where each SPOV / Insight shows up in the build"](#where-each-spov--insight-shows-up-in-the-build)
for the code map, and [`TRACEABILITY.md`](TRACEABILITY.md) for the full
feature → SPOV/Insight/PRD table.

---

## Purpose

Redefine how an LSAT study tool should be built. The modern LSAT is roughly
**two-thirds Logical Reasoning**, and every Logical Reasoning problem is
surface-unique — there is almost nothing to memorize. What must improve is a
**transferable reasoning skill**: recognizing, under time pressure, which
underlying pattern a never-before-seen argument uses, and applying the right
procedure to it.

So the flashcard aspect of this app is **not** traditional memorization. It
rewards **transfer** — performing well on novel problems that share deep
structure with prior problems but differ on nearly every surface feature. The
BrainLift assembles a learning science around four pillars: **schema
abstraction, discrimination, transfer, and the speed–accuracy tradeoff.**

### In scope
- Learning science for transfer, schema induction, discrimination learning,
  retrieval practice, scaffolding/fading, and the speed–accuracy tradeoff, as
  they apply to a *reasoning* exam.
- A structured categorization of LSAT patterns: question types, flaw types, trap
  (wrong-answer) types, and reading-comprehension structures.
- Defensible spiky positions on how an LSAT tool should differ from a
  conventional flashcard system.
- Light references to how the principles surface in the app (a schema-weighted
  study queue, separate measurement of memory vs. performance, a falsifiable
  feature test).

### Out of scope
- **Logic Games / Analytical Reasoning** — permanently removed from the LSAT in
  August 2024 and replaced by a second Logical Reasoning section.
- **Memory-model research as the centerpiece** (FSRS, spacing) — the LSAT has too
  little memorizable content; memory is supporting, not foundational.
- Full engineering specification of the app — this document is learning-science
  context.

---

## DOK 4 — Spiky Points of View (SPOVs)

### SPOV 1 — The LSAT is a transfer problem, so a flashcard app cannot be used in a traditional memory-retention manner.
The flashcard structure and the memory-scheduling algorithm on top of it assume
the thing being learned is a stable item that will reappear and must be retained.
That holds for the MCAT's fact base; it fails for the LSAT, where the item (a
specific argument about coffee, voting, or paleontology) will literally never be
seen again. What recurs is **deep structure** — a correlation→causation flaw, a
sufficient/necessary confusion, an out-of-scope trap. Building around memory
retention makes students good at recalling explanations they have already seen,
but not at extrapolating to new problems. **The correct unit of mastery is the
schema.** The app's data model, study queue, and scoring must all key to schema
mastery, not card retention, and the key metric is the **gap between "can recall
this card" and "can answer a new question with this structure."**

### SPOV 2 — Mastery should be measured at the level of the schema, starting with the flaws of a problem rather than question type.
Prep companies organize the LSAT by question type (Assumption, Strengthen,
Weaken, Inference…) because the stem announces the type and it is easy to label.
But question type is a **surface** feature of the task, not of the reasoning.
Flaws are a more transferable unit: identifying a flaw requires deep
understanding, and — as with teaching being the highest form of learning — being
able to articulate precisely why other answers are wrong is central to solving.
A handful of flaws (correlation/causation, sufficient/necessary, part/whole,
sampling error, equivocation) recur across question types. This is spiky because
it **inverts the standard prep-company information architecture**: the secondary
tag (flaw) becomes the primary organizing axis; question type comes second. Trap
identification is the companion signal — each problem's wrong answers follow
recurring traps students must learn to avoid.

### SPOV 3 — For LSAT explanation-reading, scaffolding should fade dramatically more slowly than consensus prescribes; for the two-answer decision it should very nearly never fade.
Worked-example research (Sweller) says instructional scaffolding should fade as a
learner gains expertise, because support that helps a novice becomes redundant or
harmful for an expert (the expertise-reversal effect). SPOV 3 accepts the
direction but argues it is **miscalibrated for the LSAT**: on hard items the
difficulty does not disappear with expertise — it **relocates to the final
two-answer decision**, where one attractive trap and one correct answer remain.
Distinguishing them precisely *and quickly* is what separates a 175 from a 160.
So the explanation of why the runner-up is wrong and the winner is right retains
its value far longer than fading theory predicts; it should fade slowly and, for
the binary decision, essentially never. **Falsifiable version:** it keeps raising
accuracy on hard (two-answer) items past the point where fading theory predicts a
plateau.

### SPOV 4 — Speed is not a separate skill to train after accuracy; accuracy measured without latency is a vanity metric on a timed reasoning test.
Most prep advice treats timing as a final-phase concern (get accurate first, then
fast). That is fine early, but there must come a point where the student trains
under time pressure, because the goal is to change the *reasoning process* —
narrowing candidate answers the way the real test demands. On a brutally timed
test, **a correct-but-too-slow answer is, in aggregate, a wrong answer**, because
it consumes the budget that would have earned points elsewhere. A readiness model
reporting accuracy without jointly modeling latency reports a number the exam will
not honor. A student who is 95% accurate at 2× the time budget is **less ready**
than one who is 85% accurate within budget, and an honest tool must say so and
**flag the accurate-but-slow student** rather than flatter them.

---

## DOK 3 — Insights

### Theme A — The unit of mastery
- **Insight 1.** Because every LR item is surface-unique, the only thing that can
  be mastered and reused is the deep structure. The app's atomic object should be
  a **schema** (a flaw, a trap, a question-type procedure); individual questions
  are merely **instances** used to train and test that schema. This is a different
  data model from every flashcard app, where the card is the atom.
- **Insight 2.** Flaw structures are the highest-leverage schemas because they are
  shared across question types (key categories: Flaw, Weaken, Necessary
  Assumption, Parallel-Flaw). Organizing study and diagnosis by flaw gives the
  most transfer per unit of study. (Synthesizes Gick & Holyoak's schema-transfer
  with the LSAT taxonomy.)

### Theme B — How schemas are actually acquired
- **Insight 3.** A single worked example does not produce transfer; **comparison
  of two analogs does** (Gick & Holyoak). The app should deliberately present
  items in **contrasting pairs/sets** — two arguments with the same flaw but
  different topics, or one with a flaw and one cleverly without — and prompt the
  student to articulate what they share.
- **Insight 4.** Interleaving beats blocking **specifically when the skill
  includes identifying which category an item belongs to** (Kornell & Bjork;
  Rohrer). Since LR's first move is "what type is this?", interleaving
  question/flaw types is matched to the cognitive demand.
- **Insight 5.** **Retrieval, not restudy, consolidates** (Karpicke & Roediger).
  For the LSAT the retrieved object is a **procedure**, so effective practice
  makes the student execute the reasoning from memory, then checks it. This is
  where AI fits: AI can point out specific errors but is weaker at surfacing
  **patterns** of weakness; training it on strong data so it flags recurring
  patterns in student reasoning is the high-value use.

### Theme C — Scaffolding and the two-answer fork
- **Insight 6.** On hard LSAT items, students routinely face a decision between
  **two remaining answers**. This is the key empirical observation behind SPOV 3
  and explains why even high scorers keep losing points at the same step: fading
  theory assumes the expert no longer benefits from the explanation, but the
  expert is still missing exactly the thing the explanation addresses.
- **Insight 7.** Therefore scaffolding should be **decomposed, not faded
  uniformly** — fade the parts an expert has internalized while preserving the
  contrastive two-answer explanation.

### Theme D — Traps, weighting, and speed
- **Insight 8.** Wrong answers are not random — there is a small set of recurring
  **trap types** (out-of-scope, too-strong, reversed relationship, half-right,
  premise-restatement, etc.). So "why is this wrong?" is itself a learnable,
  transferable schema, and **modeling which trap a student habitually falls for is
  more diagnostic than which question they missed**. (Novel application of
  schema-transfer logic to the distractor side.)
- **Insight 9.** Choosing the right answer is partly a **weighting problem** —
  deciding whether vagueness, scope, or strength is the decisive feature on this
  item. Re-encountering items that reward the same weighting builds the pattern
  recognition that lets a student apply it to a novel item. This connects schema
  induction to the **answer-selection step** specifically, not just flaw-spotting.
- **Insight 10.** On a brutally timed test, **latency and accuracy are not
  separable** measures of readiness; a correct-but-slow answer trades away points
  elsewhere. An honest readiness model must treat response time as **co-equal**
  with correctness and flag the accurate-but-slow student. (Basis for SPOV 4.)

---

## Experts

| Expert(s) | Contribution the app relies on | Key reference |
| --- | --- | --- |
| **Robert & Elizabeth Bjork; Nate Kornell** | "Desirable difficulties"; interleaving improves categorization of novel exemplars — the discrimination skill at the heart of LR. | Kornell & Bjork (2008), *Learning concepts and categories: Is spacing the enemy of induction?*, *Psychological Science*. |
| **Mary Gick & Keith Holyoak** | Schema induction via **analogical transfer**: one example rarely transfers; comparing two analogs sharing deep structure does. Scientific core of SPOV 1/2 and the contrasting-cases method. | Gick & Holyoak (1980) *Analogical Problem Solving*; (1983) *Schema Induction and Analogical Transfer*, *Cognitive Psychology*. |
| **Jeffrey Karpicke & Henry Roediger III** | The **testing/retrieval-practice effect**; confidence is uncorrelated with actual retention (justifies measuring performance over self-report). | Karpicke & Roediger (2008), *Science* 319, 966–968, DOI 10.1126/science.1152408. |
| **John Sweller** | Cognitive Load Theory and the **worked-example effect / expertise reversal** — the consensus SPOV 3 pushes against. | Sweller (1988); Kirschner, Sweller & Clark (2006), *Educational Psychologist* 41(2). |
| **Doug Rohrer** | Interleaved practice of problem types improves later **method selection** on mixed tests; maps almost one-to-one onto LR. | Rohrer & Taylor (2007); Rohrer (2012). |

---

## DOK 2 — Knowledge Tree (structured foundation)

### Category 1 — The modern LSAT: structure and what it measures
*Source: LSAC, "About the LSAT" / "Types of LSAT Questions" —
<https://www.lsac.org/lsat/prepare/types-lsat-questions>*
- Three scored sections: two **Logical Reasoning** (24–26 questions each) and one
  **Reading Comprehension** (26–28 questions), 35 minutes each.
- Logic Games (Analytical Reasoning) **permanently removed August 2024**,
  replaced by a second LR section.
- Scored **120–180**; raw score (number correct) is **equated** for form
  difficulty, not curved against other test-takers; **no guessing penalty**.
- One unscored **experimental** section (LR or RC), indistinguishable during the
  test.
- **Summary:** ~2/3 LR, so LR drives most of the score and is the primary target;
  the exam measures reasoning on novel material, not recall — the whole premise.

### Category 2 — The schemas to be mastered (LSAT pattern taxonomy)
- **2.1 LR question types** *(prep-taxonomy synthesis: PowerScore, Manhattan, The
  LSAT Trainer, Cambridge LSAT)* — ~10–14 types (Identify the Flaw; Necessary /
  Sufficient Assumption; Strengthen; Weaken; Evaluate; Must Be True/Inference;
  Most Strongly Supported; Main Conclusion; Method of Reasoning; Parallel
  Reasoning; Parallel Flaw; Point at Issue/Agreement; Paradox; Principle; Role of
  a Statement; + EXCEPT variants). Assumption + Flaw + Inference ≈ 40% of LR;
  adding Strengthen, Weaken, Paradox, Principle ≈ 75%+. *Surface/task axis —
  useful for labeling but not the deepest organizing unit (SPOV 2).*
- **2.2 Flaw types (the transferable backbone)** *(Khan Academy LSAT "Types of
  flaws"; LSATHacks)* — Causal (correlation→causation, reversed causation,
  common-cause overlooked, post hoc); Conditional (necessary/sufficient
  confusion, mistaken reversal, mistaken negation); Sampling/evidence
  (unrepresentative/biased/small sample, appeal to ignorance); Quantity/scope
  (part↔whole, percentage vs. absolute, equivocation); Structure (circular
  reasoning, ad hominem, straw man, false dilemma, appeal to authority/emotion).
  *The same flaw recurs across question types — the highest-transfer schema and
  the right primary diagnostic axis.*
- **2.3 Trap (wrong-answer) types** *(prep-taxonomy synthesis)* — out-of-scope;
  too-strong/extreme; too-weak; opposite; reversed relationship;
  half-right/half-wrong; premise restatement; could-be-true (fails must-be-true
  bar); real-world-plausible-but-unsupported; right-answer-to-wrong-question.
  RC-specific: distortion of author's view, wrong-viewpoint attribution, scope
  too broad/narrow, tone mismatch. *Distractors are systematic, so "why wrong" is
  a learnable schema; the habitual trap is highly diagnostic (Insight 8).*

### Category 3 — Learning-science foundations
- **3.1 Schema induction / transfer** — Gick & Holyoak (1980, 1983): a single
  example rarely transfers; comparing two analogs forces schema extraction.
  Foundation for the contrasting-cases method and the schema-as-unit data model.
- **3.2 Interleaving / discrimination** — Kornell & Bjork (2008); Rohrer & Taylor
  (2007): interleaving improves categorization/method selection of novel items
  despite feeling harder; matched to LR's "which type is this?" demand.
- **3.3 Retrieval practice** — Karpicke & Roediger (2008): repeated testing beats
  repeated studying for delayed recall; confidence ≠ performance. For the LSAT the
  retrieved object is a procedure.
- **3.4 Worked examples, fading, expertise reversal** — Sweller; Kirschner,
  Sweller & Clark (2006): novices benefit from worked examples; support that aids
  novices can hinder experts. The consensus SPOV 3 pushes against — the LSAT's
  difficulty relocates to the two-answer fork instead of disappearing.

---

## Where each SPOV / Insight shows up in the build

The numbers referenced from code resolve to the entries above. Representative
map (see [`TRACEABILITY.md`](TRACEABILITY.md) for the full table):

| Origin | Realized in |
| --- | --- |
| **SPOV 1** (schema is the unit) / **I1** | Schema-weighted queue [`rslib/src/scheduler/schema_weighted.rs`](../../rslib/src/scheduler/schema_weighted.rs); schema-centric data model `speedrun/data/seed_deck.json`; transfer-gap report `speedrun/eval/transfer_gap.py`; performance score `speedrun/scoring/performance.py` |
| **SPOV 2** (flaws → traps) / **I2** | Flaw-primary taxonomy `speedrun/taxonomy/lsat_taxonomy.json`; methodology `speedrun/taxonomy/methodology.md` |
| **I3** (compare analogs) | Contrasting-pairs drill `speedrun/contrasting.py` |
| **I4** (interleaving) | Confusion-pair interleaving `speedrun/confusion.py`; interleaving experiment `speedrun/eval/interleaving_experiment.py` |
| **I5** (retrieval) | Reasoning evaluator `speedrun/ai/reasoning_evaluator.py`; confidence calibration `speedrun/confidence_calibration.py` |
| **SPOV 3 / I6 / I7** (two-answer fork; decomposed fading) | Fork trainer `speedrun/fork_trainer.py`; adaptive fading `speedrun/fading.py` + [`adaptive-fading.md`](adaptive-fading.md) |
| **I8** (habitual trap) | Mistake-correlation graph `speedrun/mistake_graph.py`; habitual-trap diagnostics `speedrun/insights.py`; per-choice trap tags in `speedrun/data/seed_deck.json` |
| **I9** (answer weighting) | Two-answer fork decision + trap-weighting drill `speedrun/fork_trainer.py` |
| **SPOV 4 / I10** (speed co-equal) | Latency-adjusted performance/readiness `speedrun/scoring/performance.py`, `speedrun/scoring/readiness.py`; queue `time_pressure_factor` `speedrun/scoring/queue.py`; post-review budget toast `qt/aqt/speedrun/reviewer.py` |

*Honesty discipline:* cold-open, contrasting-pairs, fork, and calibration grades
are self-driven **training signal** and are deliberately excluded from the
Memory / Performance / Readiness scores; only graded transfer from the Anki
revlog feeds the scores (enforced in code and unit-tested).

---

*Source document: [`LSAT-BrainLift-Arthur.pdf`](LSAT-BrainLift-Arthur.pdf)
(tracked in this repo). Product requirements: [`PRD.md`](PRD.md).*
