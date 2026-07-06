# Architecture

This repository is **Speedrun LSAT**, a brownfield fork of Anki. This file has
two parts: the **Speedrun LSAT architecture** (the system this fork adds) and
the **upstream Anki architecture notes** it builds on. The Speedrun sync and
conflict-rule details ([§13](speedrun/PRD.md#13-sync-and-the-conflict-rule)) are
in [Speedrun sync and the conflict rule](#speedrun-sync-and-the-conflict-rule-prd-13)
further down.

## Speedrun LSAT architecture

The PRD's companion link `docs/architecture.md` points here. The **full Speedrun
system architecture** — one Rust engine behind a desktop and an iOS front end,
the protobuf command pattern, the schema-weighted queue, the three scores, iOS
XCFramework packaging, and the failure-mode table — lives in
[`docs/speedrun/docs/architecture.md`](speedrun/docs/architecture.md). The
product spec is [`docs/speedrun/PRD.md`](speedrun/PRD.md).

In brief (see that doc for the diagrams and detail):

- **One engine, two front ends.** There is exactly one implementation of the
  scheduler, FSRS, the collection format, sync, and the new schema-weighted queue
  — in `rslib`. The desktop reaches it through `pylib/rsbridge` (PyO3); the iOS
  companion reaches the **same** `anki::backend::Backend` through `rslib-ffi`
  (a C-ABI staticlib packaged as an XCFramework). Neither front end
  re-implements engine logic.
- **The protobuf command pattern.** Both front ends send the identical
  `(service, method, request_bytes)` protobuf command and decode `response_bytes`,
  so the schema-weighted queue and all three scores behave identically on desktop
  and phone.
- **The brownfield Rust change.** A schema-weighted "points-at-stake" study queue
  in `rslib/src/scheduler/schema_weighted.rs`, exposed as a new protobuf RPC —
  see [`docs/speedrun/rust-change.md`](speedrun/rust-change.md).
- **Three scores, honestly reported.** Memory, performance, and readiness, each
  with a range and a give-up rule — see [`docs/models/`](models/).
- **Sync and the conflict rule.** Anki's own sync protocol against a self-hosted
  `rslib` server; the merge behaviour is documented below and in
  [`docs/speedrun/SYNC.md`](speedrun/SYNC.md).

---

# Anki Architecture (upstream notes)

Very brief notes for now.

## Backend/GUI

At the highest level, Anki is logically separated into two parts.

A neat visualization of the file layout is available here:
<https://mango-dune-07a8b7110.1.azurestaticapps.net/?repo=ankitects%2Fanki>
(or go to <https://githubnext.com/projects/repo-visualization#explore-for-yourself> and enter `ankitects/anki`).

### Library (rslib & pylib)

The Python library (pylib) exports "backend" methods - opening collections,
fetching and answering cards, and so on. It is used by Anki’s GUI, and can also
be included in command line programs to access Anki decks without the GUI.

The library is accessible in Python with "import anki". Its code lives in
the `pylib/anki/` folder.

These days, the majority of backend logic lives in a Rust library (rslib, located in `rslib/`). Calls to pylib proxy requests to rslib, and return the results.

pylib contains a private Python module called rsbridge (`pylib/rsbridge/`) that wraps the Rust code, making it accessible in Python.

### GUI (aqt & ts)

Anki's _GUI_ is a mix of Qt (via the PyQt Python bindings for Qt), and
TypeScript/HTML/CSS. The Qt code lives in `qt/aqt/`, and is importable in Python
with "import aqt". The web code is split between `qt/aqt/data/web/` and `ts/`,
with the majority of new code being placed in the latter, and copied into the
former at build time.

## Protobuf

Anki uses Protocol Buffers to define backend methods, and the storage format of
some items in a collection file. The definitions live in `proto/anki/`.

The Python/Rust bridge uses them to pass data back and forth, and some of the
TypeScript code also makes use of them, allowing data to be communicated in a
type-safe manner between the different languages.

At the moment, the protobuf is not considered public API. Some pylib methods
expose a protobuf object directly to callers, but when they do so, they use a
type alias, so callers outside pylib should never need to import a generated
\_pb2.py file.

## Speedrun sync and the conflict rule (PRD §13)

The desktop and iOS companion share the same collection and reach the engine the
same way (`pylib/rsbridge` on desktop, `rslib-ffi` on iOS). They sync through
Anki's existing sync protocol against a self-hosted server built from `rslib`
(`python -m anki.syncserver`). The milestone requires that reviews flow both
ways with **none lost and none double-counted**, and that the **same card
reviewed on two devices offline** resolves to a single, deterministic winner.

### What the engine actually does when it merges

The PRD states the rule as "the review with the later real timestamp wins." That
is the observable behavior, but the engine does not compare wall-clock stamps
directly; it merges by **USN + modification time**, and it stores every review as
an immutable, uniquely-keyed row. The two mechanisms combine to give the
timestamp-wins behavior with no double-count. The relevant code:

- **Review history (`revlog`) — every review is kept, keyed by a unique id.**
  During an incremental sync, incoming revlog entries are inserted with
  `INSERT OR IGNORE` on the row's `id`
  (`merge_revlog` → `Storage::add_revlog_entry(entry, uniquify: false)` →
  `rslib/src/storage/revlog/add.sql`). A revlog `id` is the epoch-millisecond
  timestamp at which the card was answered. Because two reviews on two devices
  happen at two different instants, they have two different ids, so **both rows
  survive** the merge. Re-syncing a row that is already present matches an
  existing `id` and is ignored, so a review is **never inserted twice** — this is
  what prevents double-counting on repeated syncs.

- **Card scheduling state — the newer modification time wins, once.**
  A card row is a single record that holds the card's current scheduling state
  (interval, due date, queue, reps, FSRS memory state). On merge, the incoming
  card replaces the local one only when the incoming side is newer
  (`add_or_update_card_if_newer` in
  `rslib/src/sync/collection/chunks.rs`): it proceeds when the local card is not
  a pending local change (`!existing.usn.is_pending_sync(pending_usn)`) **or**
  when `existing.mtime < incoming.mtime`. A card's `mtime` is bumped to the
  moment it is answered, so the device that reviewed the card **later** carries
  the later `mtime` and its scheduling state is the one that is kept. Notes merge
  by the same rule.

### Reconciling "later timestamp wins" with "USN + mtime"

For the same card reviewed on two devices while offline:

1. Both reviews are written to the shared review history and both are kept — no
   history is lost. Because each has a unique millisecond id, neither is counted
   twice, no matter how many times the clients re-sync.
2. The card's **single** scheduling state is taken from the review with the later
   modification time — i.e., the later real review. The earlier review remains in
   history but does **not** advance the card's schedule a second time, so the
   card's FSRS/interval state is not double-applied. The card is counted once.

So "the later real-timestamp review wins" is exactly what a user observes: the
card ends up scheduled as the later device left it, while both reviews are still
visible in the card's history. There is one winner for scheduling and zero lost
reviews.

### Edge cases and safety

- **Clock skew.** If a client's clock differs from the server's by more than
  ~300s the server aborts with `ClockIncorrect` rather than guessing an order;
  the user fixes the clock and retries. This keeps "later timestamp" meaningful.
- **`mtime` granularity is seconds.** The card comparison uses a strict `<`, so
  two reviews that land in the *same* second do not overwrite each other and the
  already-applied record is kept — still deterministic, just decided by which
  arrived first rather than by sub-second order. In practice two human reviews of
  the same card are essentially never in the same second; the automated test
  (below) forces a >1s gap so the "later wins" outcome is unambiguous.
- **Atomicity / offline.** A normal sync runs inside a DB transaction, so a
  mid-sync disconnect rolls back and cannot corrupt or half-apply a merge.
  Offline edits carry USN `-1` (pending) and upload on the next sync.

### Verification

`speedrun/tools/sync_test.py` proves this end to end against a live, self-hosted
server. It (A) reviews 10 cards on a "desktop" collection and 10 **different**
cards on a "phone" collection, syncs both ways, and asserts the merged revlog is
exactly the sum, each reviewed card is counted once, and no card row was
duplicated; then (B) reviews the **same** card on both, with the phone's review
at a strictly later timestamp, syncs, and asserts both clients converge to the
phone's scheduling state (later wins) while **both** review rows are preserved,
finishing with Anki's own database check to confirm neither collection is
corrupt. See also [docs/speedrun/SYNC.md](speedrun/SYNC.md) for the runbook.
