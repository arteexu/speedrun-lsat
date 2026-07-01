# `speedrun/` — LSAT Speedrun project assets

All Speedrun-specific, non-engine assets live here so the fork's changes to
upstream Anki stay small and easy to rebase. Engine changes (the schema-weighted
queue, new protobuf) live in `rslib/` and `proto/` and are documented separately.

## Layout

```
speedrun/
  taxonomy/
    lsat_taxonomy.json   # SOURCE OF TRUTH: schemas across 4 axes + exam weights
    methodology.md       # how the taxonomy and weights are built, with sources
  data/
    seed_deck.json       # original (license-clean) LSAT-style items, schema-tagged
  tools/
    coverage_map.py      # coverage report + schema-ref validation (CI-able)
```

## The taxonomy is the source of truth

`taxonomy/lsat_taxonomy.json` defines every schema (flaw / question_type / trap /
rc_structure) with a stable `id` and an `exam_weight`. The schema-weighted queue
in `rslib` reads these weights (`schema_weight`); the coverage map and the three
scores key off the same ids. Never key on array order or display name — only `id`.
See [`taxonomy/methodology.md`](taxonomy/methodology.md).

## Coverage map (gates the readiness give-up rule)

The coverage tool reports how much of the exam the deck covers and whether the
readiness gate is open. Per the PRD, readiness abstains until each section reaches
the coverage line (default 50%).

```bash
python speedrun/tools/coverage_map.py          # human-readable report
python speedrun/tools/coverage_map.py --json    # machine-readable
```

It exits non-zero if the deck references a schema id absent from the taxonomy, so
it doubles as a data-integrity check in CI.

## Seed deck and content

`data/seed_deck.json` is a small scaffold of **original** items (not real LSAT
questions) used to exercise the pipeline. Each item carries its schema tags, a
correct answer, per-choice trap tags, and a `two_answer_fork` (why the runner-up
is wrong / why the winner is right) for the slow-fading scaffolding (SPOV3).
Before any scoring, expand this from a chosen license-clean source (an open
decision in the PRD).
