# Mistake graph — how to make it work + test it

The **Mistake graph** is the analytics-dashboard network of the schemas you get
*wrong* (`#sr-mistake` SVG, fed by the `sr-mistake-data` JSON blob). Nodes are
schemas you've missed; edges link schemas you tend to miss *together*. This doc
explains what data it needs, why it can look empty, how to populate it (real usage
or synthetic sample data), and how to test it.

Code map:

- Graph algorithm (pure, Qt-free): `speedrun/mistake_graph.py`
  (`build_mistake_graph`, `mistake_graph_json`).
- HTML/JS rendering + empty state: `speedrun/dashboard.py`
  (`_mistake_graph_section`, `render_mistake_graph_html`, JS `srMistakeGraph()`).
- Tags are read from notes via `_schema_ids_from_tags` in `speedrun/concept_graph.py`.
- Tests: `pylib/tests/test_speedrun_mistake_graph.py`.
- Sample-data generator (new): `speedrun/tools/seed_sample_reviews.py`.

## What the graph needs

It reads the collection's **revlog** (graded reviews) joined to each card's note
tags. Only two things matter:

1. **A mistake = an `Again` grade.** In Anki a review's `ease` is `1..4`;
   `ease == 1` (Again) is the only "wrong" grade. See the SQL + `if int(ease) == 1`
   in `build_mistake_graph` (`speedrun/mistake_graph.py`).
2. **Schemas come from `sr:` tags** on the note:
   `sr:schema:*` (flaw/RC mastery units), `sr:qtype:*` (question types),
   `sr:trap:*` (traps). A review with no `sr:` tag is ignored. Seed-deck cards get
   these tags from `speedrun/tools/import_seed_deck.py`.

### Nodes

Every schema that appears on **≥1 missed** review becomes a node. Node **size** =
number of misses; **colour** = miss-rate:

- `chronic`  — miss-rate ≥ `CHRONIC_AT` (0.50)
- `shaky`    — miss-rate ≥ `SHAKY_AT` (0.25)
- `occasional` — below that

### Edges (the whole point)

Misses are grouped into **buckets**, then two schemas get an edge when they are
missed together in enough buckets *and* the correlation is positive:

- **Bucket mode** (`_bucket_mode`): if you've missed cards on **≥2 distinct study
  days**, buckets are **days** (all schemas missed that day are unioned). If it's
  all one day, mode is **event** — each missed review is its own bucket
  ("missed on the same sitting/card").
- **Edge thresholds** (`_build_edges`): need **≥2 buckets total**; a pair must
  co-occur in **≥ `MIN_CO_OCCUR` (2)** buckets; and the **phi** correlation must be
  **> `MIN_CORR` (0.0)** (strictly positive).

The subtle part: **co-occurring a lot is not enough.** A pair that appears in
*every* bucket never varies, so phi = 0 and it's dropped (see
`test_build_edges_drops_ubiquitous_zero_correlation`). To get an edge you need
buckets where the pair is *present together* **and** other buckets where it's
*absent*. In practice: miss two schemas together on a couple of days, and miss
something else on other days.

### Empty state

`_mistake_graph_section` only shows the "No mistakes recorded yet…" placeholder
when there are **zero nodes**. If you have misses but no correlation structure you
get **nodes drawn but zero edges** — which reads as "not working" even though it
is. The stats line (`… · N correlations (by day/sitting)`) will say `0
correlations`.

Everything is computed offline from `col.db`; the app does **not** need to be
running (but close it before opening the same profile from a script — SQLite lock).

## Why it's probably empty right now

The dev profile (`~/dev/speedrun-lsat/.ankidata`, i.e. `ANKI_BASE`) has very few
graded misses. Checked directly, the current profile has 45 revlog rows but only
**2 misses**, both on the **same day**, so:

- bucket mode = **event** (one day only), 2 buckets;
- the only pairs co-occurring in ≥2 buckets are traps present in *both* misses
  (`too_strong_extreme`, `out_of_scope`, `half_right`) — which are ubiquitous →
  phi = 0 → dropped.

Result: **7 nodes, 0 edges.** The graph renders, but with no connections. Desktop
reviews *are* being recorded (the revlog is populating); there just isn't enough
correlated-miss structure yet. (The recently-fixed iOS write-back is a separate
concern and doesn't affect desktop.)

## How to populate it

### Path 1 — real usage

Study the LR deck and answer **Again** on cards across **several different
schemas**, ideally over **≥2 days**:

1. `Tools → LSAT Speedrun → Study` (or the dashboard quick-launch), study the
   `LSAT Speedrun` deck.
2. Answer **Again (1)** on cards. To form edges, miss cards that **share** a
   flaw/trap on more than one occasion, and miss some **different** schemas on
   others so the shared pair *varies*.

Rules of thumb from the thresholds:

- **First nodes:** a single miss.
- **First edge, same day (event mode):** miss ~**3+ cards** where **2 of them
  share** a specific schema pair and **≥1 is different** — that yields 2 co-occur
  buckets + 1 "absent" bucket → phi > 0.
- **Most robust:** miss on **≥2 days**; on 2 of the days miss the same
  pair together, on the other day(s) miss something else. Because seed cards carry
  several overlapping `sr:trap:*` tags, ~**6–10 deliberate wrong answers spread
  over 2 days** typically lights up multiple edges.

### Path 2 — synthetic sample data (fast)

Use the new generator to inject a realistic hit/miss pattern with built-in
correlated mistakes so the graph renders edges immediately. It **requires an
explicit target** (never touches real data by default), backs up first, and is
idempotent (re-running replaces its own rows; `--clear` removes them).

```bash
# safest: run against a COPY of a collection
cp "~/dev/speedrun-lsat/.ankidata/User 1/collection.anki2" /tmp/collection.anki2
PYTHONPATH=out/pylib out/pyenv/bin/python \
  speedrun/tools/seed_sample_reviews.py --col /tmp/collection.anki2

# or against a profile dir (CLOSE the app first so the db isn't locked)
PYTHONPATH=out/pylib out/pyenv/bin/python \
  speedrun/tools/seed_sample_reviews.py --base ~/dev/speedrun-lsat/.ankidata

# undo (removes only the synthetic rows it created)
PYTHONPATH=out/pylib out/pyenv/bin/python \
  speedrun/tools/seed_sample_reviews.py --col /tmp/collection.anki2 --clear
```

It imports the seed deck if needed, picks a correlated schema pair + a distractor,
and writes `Again`/`Good` reviews across `--days` (default 4) days. It prints the
resulting node/edge counts so you can confirm it's non-empty. Verified output on a
copy of the dev profile:

```
Mistake graph now: 13 nodes, 16 edges (bucket_mode=day, buckets=4, total_misses=36).
Strongest edge: flaw.conditional.mistaken_reversal <-> qt.inference_must_be_true (phi=1.0, co-missed in 2 buckets).
```

## How to test it

### Automated

```bash
PYTHONPATH=out/pylib:pylib out/pyenv/bin/python \
  -m pytest pylib/tests/test_speedrun_mistake_graph.py -q
```

This covers phi math, status thresholds, the `MIN_CO_OCCUR` gate, the "ubiquitous →
no edge" case, bucket modes, the empty collection, node creation after real misses
(driving `col.sched.answerCard(card, 1)`), and full/empty HTML render. It's the
template for synthesizing revlog data in tests.

### Manual

1. Populate data (Path 1 or 2).
2. Relaunch: `ANKI_BASE=~/dev/speedrun-lsat/.ankidata ./run`.
3. Open the dashboard → Mistake graph (or the standalone Mistake-graph page).
4. You should see: schema **nodes** (sized by misses, red=chronic → green=occasional),
   **edges** between co-missed schemas, and a summary like `… · N correlations`.
5. **Click the map once to activate** (the "Click to interact" lock) before it will
   pan/zoom; then click a node to see its correlated mistakes in the side panel.
