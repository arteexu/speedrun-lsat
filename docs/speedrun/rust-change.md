# The Rust engine change: schema-weighted "points-at-stake" queue

This is the required brownfield change inside Anki's Rust engine (`rslib`). It adds
a new review ordering that surfaces the highest-value LSAT schema practice first,
exposed as a new protobuf RPC and called from Python (and, via the shared engine,
from the future iOS build).

## What it does

For each due card, the engine computes a value-at-stake priority:

```text
priority = schema_weight * student_weakness * time_pressure_factor
```

- `schema_weight` — how much the card's schema matters on the exam (from
  `speedrun/taxonomy/lsat_taxonomy.json`).
- `student_weakness` — 1 - transfer estimate for that schema (from the
  performance model); unknown schemas fall back to a caller-supplied default so
  uncovered/unseen schemas still surface instead of vanishing.
- `time_pressure_factor` — an optional boost for schemas the student is
  accurate-but-slow on (BrainLift SPOV4).

Cards are returned in descending priority, ties broken by ascending card id for
determinism. A card's schema is read from a note tag with a configurable prefix
(default `sr:schema:`), e.g. `sr:schema:flaw.causal`.

The weights and weaknesses are passed in by the caller rather than hard-coded, so
the taxonomy and the performance model remain the single sources of truth and the
engine stays policy-free.

## Why this belongs in Rust, not Python

1. **Hot path at scale.** Ordering the due queue runs every session and must hit
   the p95 "next card < 100 ms" target on a 50,000-card deck. The scoring and
   sort are tight numeric work over every due card; doing it in Rust avoids
   per-card Python round-trips across the FFI boundary.
2. **Shared by both apps.** The engine is shared. Implementing the ordering in
   `rslib` behind a protobuf RPC means the desktop (via `pylib/rsbridge`) and the
   iOS companion (via the C/FFI bridge) get the _same_ ordering with no
   reimplementation — the project's core "one engine" requirement. A JavaScript
   or Swift reimplementation would not count and would drift.
3. **Determinism and testability.** The core ordering is a pure function in Rust
   with exhaustive unit tests; identical inputs always yield identical output,
   which matters for reproducible study sessions and for the study-feature
   experiment's ablation.
4. **Type-safe boundary.** The request/response are protobuf messages generated
   for Rust, Python, and TypeScript from one schema, so the boundary can't drift.

## Read-only and undo-safe

The RPC only reads (`search_cards` + `get_card`/`get_note`); it opens no
transaction and writes nothing. It therefore cannot corrupt the collection and
does not touch the undo stack. The Python test asserts `undo_status().last_step`
is unchanged across the call.

## Tests

- **5 Rust unit tests** in `rslib/src/scheduler/schema_weighted.rs`:
  descending-priority ordering, deterministic tie-break by card id, unknown-schema
  defaults, the time-pressure boost, and limit truncation.
- **1 Python integration test** in `pylib/tests/test_schema_weighted_queue.py`:
  builds a real collection with schema-tagged notes, calls
  `col._backend.build_schema_weighted_queue(...)`, and checks ordering, the limit,
  the default fallback, and read-only behavior.

Run them:

```bash
cargo test -p anki schema_weighted           # Rust unit tests
just test-rust                               # full Rust suite (540 pass)
PYTHONPATH=out/pylib out/pyenv/bin/python -m pytest pylib/tests/test_schema_weighted_queue.py -v
```

## How it is called

Python (desktop):

```python
scored = col._backend.build_schema_weighted_queue(
    search="is:due",
    limit=50,
    schema_tag_prefix="sr:schema:",
    schema_weight={...},      # from speedrun/taxonomy
    schema_weakness={...},    # from the performance model
    time_pressured_schemas=[...],
    time_pressure_factor=1.5,
    default_weight=0.05,
    default_weakness=1.0,
)
# scored is a list of ScoredCard(card_id, note_id, schema, schema_weight, weakness, priority)
```

iOS reaches the identical RPC through the C/FFI bridge (see the architecture doc).

## Upstream files touched (merge-difficulty assessment)

| File                                 | Change                                                             | Merge risk                                                                                                      |
| ------------------------------------ | ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------- |
| `proto/anki/scheduler.proto`         | Appended 1 RPC to `SchedulerService` and 4 messages at end of file | Low — additive, at the end; the RPC is the last method so existing method indices are unchanged                 |
| `rslib/src/scheduler/mod.rs`         | Added `pub mod schema_weighted;`                                   | Low — one line among module decls                                                                               |
| `rslib/src/scheduler/service/mod.rs` | Added one method to `impl SchedulerService for Collection`         | Low-Medium — only conflicts if upstream rewrites this impl block; method appended after `studied_today_message` |

New files (no conflict possible):

| File                                        | Purpose                             |
| ------------------------------------------- | ----------------------------------- |
| `rslib/src/scheduler/schema_weighted.rs`    | Pure ordering function + unit tests |
| `pylib/tests/test_schema_weighted_queue.py` | Python RPC integration test         |

Non-engine assets live under `speedrun/` and `docs/speedrun/` and do not touch
upstream code. Overall a future rebase onto Anki `main` should be
straightforward: the engine footprint is three small, mostly additive edits plus
one new module.
