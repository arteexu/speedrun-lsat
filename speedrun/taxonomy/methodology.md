# LSAT schema taxonomy — methodology

This document explains how [`lsat_taxonomy.json`](lsat_taxonomy.json) is built and how its
weights are meant to be used. The taxonomy is the **source of truth** for schema
identity and `schema_weight` across the whole app: the schema-weighted queue in
`rslib`, the coverage map, and the three scores all read from it.

## Why schema, not card

Per the BrainLift, the LSAT is a transfer problem: every Logical Reasoning
argument is surface-unique, so the reusable unit of mastery is the **schema**
(a flaw, a trap, a question-type procedure, an RC structure). Cards/items are
instances of schemas. The taxonomy enumerates the schemas; the seed deck tags
each item with the schema(s) it trains.

## The four axes (flaw is primary)

- **flaw** (PRIMARY) — the reasoning error. Highest transfer because the same
  flaw recurs across question types (SPOV2). This is the primary diagnostic axis.
- **question_type** — the task the stem announces (surface axis). Used for
  labeling and section-level modeling.
- **trap** — wrong-answer/distractor types. "Why is this wrong" is itself a
  learnable schema; a student's habitual trap is a strong diagnostic (Insight 8).
- **rc_structure** — recurring structural targets in Reading Comprehension.

## Weights (`exam_weight`)

- `exam_weight` is a **relative frequency estimate within each axis**, intended to
  approximate how often a schema drives a question on a modern test. Within an
  axis the values are meant to sum to ~1.0 (the coverage tool normalizes exactly).
- Section weights (`sections.LR.weight` ≈ 0.66, `sections.RC.weight` ≈ 0.34)
  reflect the ~2/3 LR / ~1/3 RC composition (two scored LR sections of 24–26 vs
  one RC of 26–28).
- These are **estimates synthesized from prep-taxonomy sources**, not official
  LSAC frequency data (LSAC does not publish per-type frequencies). They are
  explicitly provisional and are to be refined against real form-frequency data.
  Honesty rule: we treat them as estimates, and the queue's behavior degrades
  gracefully if they are off (it still surfaces weak high-weight schemas first).

## How the queue uses this

The schema-weighted "points-at-stake" queue computes, per due card:

```
priority = schema_weight(schema) * student_weakness(schema) * time_pressure_factor(schema)
```

`schema_weight` comes from this file (combined with the section weight);
`student_weakness` and `time_pressure_factor` come from the performance model.

## Sources

- LSAC, "About the LSAT" / "Types of LSAT Questions": https://www.lsac.org/lsat/prepare/types-lsat-questions
- Cambridge LSAT, question types: https://www.cambridgelsat.com/resources/information/question-types/
- Khan Academy LSAT, "Types of flaws"; LSATHacks: https://lsathacks.com/logical-reasoning-question-types/
- Prep-taxonomy synthesis: PowerScore, Manhattan Prep, The LSAT Trainer.

## Change process

Bump `version` and `updated` in the JSON when schemas or weights change. Any code
that consumes the taxonomy should key on the stable `id` field (never on array
order or display name).
