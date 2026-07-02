# Adaptive mastery-ordered fading (SPOV3)

**Module:** `speedrun/fading.py` · **Tests:** `pylib/tests/test_speedrun_fading.py` ·
**Report:** Tools → LSAT Speedrun → *Mastery ladder (adaptive fading)*

## Why (the learning science)

The consensus **expertise-reversal effect** says scaffolding that helps a novice
becomes inert or harmful for an expert, so guidance should *fade* as expertise
grows ([Kalyuga et al.](https://link.springer.com/article/10.1007/s10648-007-9054-3);
[Sweller, guidance-fading](https://cogscisci.wordpress.com/wp-content/uploads/2019/08/sweller-guidance-fading.pdf)).
Classic **backward fading** removes the *last* solution step first.

SPOV3 originally said the two-answer-fork explanation should "never fade." Taken
literally that contradicts expertise reversal, and literal backward fading is even
worse here — the fork *is* the last step, so it would fade *first*. This feature
reconciles the two:

> Scaffolding fades by **step difficulty (mastery), hardest-last**. The
> two-answer fork is the terminal scaffold — the last thing to go — and it only
> fades once fork accuracy is high, at which point the item switches to **timed
> pressure** (SPOV4). This keeps the spiky claim (the fork is special) while
> honoring the most-replicated result in the field (you *do* fade, adaptively).

Worked-example study only transfers when paired with active generation + feedback
([Pan & Rickard, 2018](https://doi.org/10.1037/bul0000151)); the ladder is what
moves the student from *reading* the worked example to *generating* it.

## The mastery ladder

Per schema, evidence puts the student on a rung (thresholds in `config.fading`):

| Rung | Gate (per schema) | Scaffold faded | Response |
|---|---|---|---|
| 0 Novice | `< min_attempts` (10) | nothing | read the full worked example |
| 1 Recognition | `≥ min_attempts` | flaw definition + easy-distractor reasoning | recall / pick |
| 2 Generation | raw accuracy `≥ recognition_gate` (0.70) | + the flaw name | generate, then self-check |
| 3 Fork mastery | fork accuracy `≥ fork_gate` (0.90) | + the fork rationale | **timed pressure** |

Every gate requires `min_attempts` (10) first, so a lucky small sample cannot
promote a student. Rungs are computed top-down (highest demonstrated mastery
wins); fork accuracy comes from the fork-trainer log, everything else from the
objective performance model (revlog).

**Pressure mode (rung 3, SPOV4):** target `pressure_accuracy_target` (92%) with a
steep penalty below, and a steep speed penalty beyond the section budget +
`pressure_speed_grace_ms` (10s) — i.e. 84s+10s for LR, 96s+10s for RC.

## Honesty rule

Rung, fade state, and pressure telemetry are **guidance only** and never feed the
memory/performance/readiness scores. The report says so on its face.

## Config (`speedrun/config.json` → `fading`)

```json
{
  "min_attempts": 10,
  "recognition_gate": 0.70,
  "fork_gate": 0.90,
  "pressure_accuracy_target": 0.92,
  "pressure_speed_grace_ms": 10000
}
```

## Deferred (designed, not yet built)

- **Confusion-pair interleaving** — interleave the *confusable* schemas a student
  actually mixes up (the condition where interleaving pays off,
  [Brunmair & Richter, 2019](https://www.psychologie.uni-wuerzburg.de/fileadmin/06020400/2019/Brunmair_Richter_in_press__2019_META-ANALYSIS_OF_INTERLEAVED_LEARNING.pdf)),
  seeded from a curated "confusable clusters" list for cold-start.
- **AI-graded generation (rung 2)** — grade free-text reasoning against the
  deterministic rubric; offline fallback = self-grade checklist. Kept off by
  default per the AI stance ([LLM-tutoring RCTs show short-term gains, poor
  retention](https://arxiv.org/html/2507.07357v1)).
