# Cross-device sync — decision-ready plan

**Goal:** a user's study progress/state syncs across desktop, iOS, and (future) web.

**TL;DR:** The hard part is largely already built. Study progress lives *inside*
the Anki collection and already rides Anki's own sync protocol. What's missing is
(1) a real hosted server + accounts, (2) the phone actually *writing* graded
reviews so it has something to sync, and (3) there is no website at all yet.

---

## 1. Current architecture (what exists today)

### Desktop (Anki fork)
- Full Anki sync stack is intact under `rslib/src/sync/` (`login.rs`,
  `collection/`, `http_client/`, `http_server/`, `request/`, `response.rs`).
- A standalone self-hosted sync server crate exists: `rslib/sync/` →
  binary `anki-sync-server` (`rslib/sync/Cargo.toml`, `rslib/sync/main.rs`).
  Also runnable as `python -m anki.syncserver`.
- Sync unit = the `.anki2` collection (notes, cards, revlog, deck/notetype
  config, media). Merge rules: cards/notes by USN + mtime; **revlog keyed by
  unique id → no lost/double-counted reviews**; clock skew >300s aborts.
  (See `rslib/src/sync/collection/chunks.rs`, documented in
  `docs/speedrun/SYNC.md`.)
- Desktop sync UI/menu is inherited from upstream Anki (Preferences → Syncing).

### Where Speedrun state actually lives — the crux
- **Inside the collection (syncs automatically):** all real study progress.
  - Reviews/attempts → Anki `revlog`.
  - Per-schema performance / weakness / readiness / memory are **derived** from
    `revlog` + note `sr:schema:` tags, not stored separately. Python source:
    `speedrun/scoring/performance.py` (`collection_attempts` reads `col.db`
    revlog), `memory.py`, `readiness.py`, `queue.py`. Rust parity port:
    `rslib/src/scheduler/speedrun_scores.rs` (RPC `ComputeSpeedrunScores`,
    service 13 / method 40) and the schema-weighted queue (method 39).
  - The schema-weighted queue is computed on demand from the collection; there
    is no separate queue-state store to sync.
- **Outside the collection (does NOT sync, but is not per-user progress):**
  - `speedrun/config.json` — app thresholds/toggles (latency budgets, guardrail,
    fading). Repo-relative app config, not user history. (`speedrun/config.py`)
  - `~/.speedrun/sessions.jsonl` — a reproducibility event log
    (`speedrun/session_logger.py`). Supplementary; derivable from revlog.
  - AI tutor (`speedrun/ai/`) makes live LLM calls; no persisted per-user study
    state (only session_logger writes outside the collection).

**Conclusion:** native Anki sync already carries the source-of-truth study
progress. There is no separate Speedrun progress store that gets stranded.

### iOS / mobile
- Native **SwiftUI** app (`ios/App/*.swift`) on a shared Rust engine via an
  xcframework (`ios/AnkiFFI.xcframework`, `ios/AnkiKit/Sources/AnkiKit/`).
- Reads a bundled exam deck (`ios/Resources/exam/collection.anki2`,
  `ios/AnkiKit/.../Resources/collection.anki2`), copied once into Documents as a
  writable collection (`SpeedrunEngine.init(persistent:)`).
- Uses the **same protobuf sync RPCs as desktop**: `SpeedrunEngine.sync()` calls
  `BackendSyncService` (service 1) — SyncLogin/SyncCollection/FullUploadOrDownload.
  UI in `ios/App/SyncView.swift`. So the phone is already a real Anki-sync client.
- **Gap:** `ios/App/ReviewView.swift` `advance()` (both "Again"/"Good") only
  increments a local counter — it never calls an answer/grade RPC.
  `SpeedrunEngine` exposes queue/noteContent/computeScores/sync but **no
  `answerCard`**. So the phone currently produces no revlog entries → nothing
  meaningful to upload yet.

### Web surface
- **There is no website or web backend in this repo.** `ts/` is Anki's built-in
  Svelte reviewer/editor rendered *inside the desktop webviews*; `qt/aqt/
  mediasrv.py` is a localhost media server, not a hosted site. There is no
  FastAPI/Flask/Node service, no API routes, no deployment.
- The dev sync server runs only on `127.0.0.1` (`docs/speedrun/SYNC-SERVER.md`),
  auth is env-var users (`SYNC_USER1=dev:pass`). No accounts, no hosting.

---

## 2. Problem statement
Which state must sync, and what already covers it:

| State | Where | Synced today? |
|---|---|---|
| Reviews / attempts (revlog) | collection | ✅ Anki sync |
| Per-schema performance / weakness / readiness / memory | derived from collection | ✅ (rides revlog+tags) |
| Schema-weighted queue | computed on demand | ✅ (no separate state) |
| Cards / notes / deck / notetype | collection | ✅ Anki sync |
| App config/thresholds (`config.json`) | repo file | ❌ (but not per-user progress) |
| `sessions.jsonl` repro log | `~/.speedrun` | ❌ (derivable; optional) |

So the real remaining work is **operational** (hosting + accounts), a **mobile
write-back gap** (phone can't record reviews yet), and the **absence of a web
surface** — not a new progress-sync data model.

---

## 3. Candidate approaches

### (A) Lean fully on Anki sync (RECOMMENDED)
Keep the collection as the single synced unit; host the existing
`anki-sync-server`; make iOS write real reviews; treat web as a later thin
client. Anything worth syncing already lives in the collection.
- **Desktop:** ~none for core (already syncs). Optionally fold `config.json`
  into `col` config (`col.set_config`) so preferences sync too.
- **iOS:** add `answerCard` to `SpeedrunEngine` + wire `ReviewView.advance()`;
  auto-sync on background/foreground. (Sync plumbing already done.)
- **Server:** deploy `anki-sync-server` (or `python -m anki.syncserver`) behind
  HTTPS with a real user store; keep desktop/iOS pointed at it.
- **Conflict:** already handled by Anki (USN+mtime; unique-id revlog merge).
- **Offline:** already offline-first (pending USN -1 uploads next sync).
- **Effort:** Low–Medium. Mostly the iOS write-back + ops/accounts.

### (B) Dedicated Speedrun sync backend (FastAPI + Postgres/SQLite)
Build a new REST/delta service; push/pull Speedrun state as records with
per-record versioning; all clients implement a new protocol.
- **Cost:** re-invents revlog merge, conflict resolution, offline queue, auth —
  all of which Anki already solves and both clients already speak.
- **When justified:** only if you need server-side analytics/multi-tenant
  dashboards, LSAT-scale leaderboards, or web-first without an Anki engine.
- **Effort:** High. Not warranted given current findings.

### (C) Hybrid
Anki sync for study progress (as A) **plus** a tiny side service for non-
collection extras (e.g. a leaderboard, or `sessions.jsonl`/config). Adopt only
if a specific extra appears that genuinely can't live in `col` config.
- **Effort:** Medium; adds a second system to run.

---

## 4. Recommendation
**Approach (A).** The collection already is the sync unit, both native clients
already speak the protocol, and merge/offline/conflict are solved and tested
(`speedrun/tools/sync_test.py`). Reserve a side service (C) only if a concrete
non-collection need emerges. Avoid (B).

---

## 5. Phased plan

**Phase 0 — Accounts + hosting (server).** Deploy `anki-sync-server` behind
HTTPS; replace env-var users with a real credential store; document the prod URL.
Touches: `rslib/sync/` (deploy only), `docs/speedrun/SYNC-SERVER.md`, infra.
*Decision-gated (see open questions).*

**Phase 1 — iOS write-back (the actual functional gap).** Add `answerCard`
(BackendSyncService/scheduler answer RPC) to
`ios/AnkiKit/Sources/AnkiKit/SpeedrunEngine.swift`; call it from
`ios/App/ReviewView.swift` `advance()` with the real ease/latency; auto-sync on
app background/foreground in `ios/App/SpeedrunSession.swift`. Extend
`speedrun/tools/sync_test.py`-style coverage to a phone-writes → desktop-reads
round trip.

**Phase 2 — Desktop polish.** Point desktop at the prod server by default;
optionally migrate `speedrun/config.json` into `col.set_config` so preferences
sync too (`speedrun/config.py` + call sites). Verify existing menu/auto-sync.

**Phase 3 — Web surface (net-new).** Decide web scope. Cheapest path that reuses
everything: compile `rslib` to WASM and run the same engine + sync RPCs in the
browser against the same server (mirrors the iOS client). A separate REST
backend (B) is only needed if web must work without the engine.

**Phase 4 — Conflict/robustness hardening.** Mostly inherited; add clock-skew UX,
sync-failure surfacing on iOS (`SyncView` status), and multi-device tests.

---

## 6. Open questions (need your call before implementing)
- **Hosting & accounts:** self-host `anki-sync-server` (recommended, no AnkiWeb)
  vs AnkiWeb? Do you already have hosting? What account/auth model (email+pw,
  SSO)? Single-user/dev vs real multi-user at LSAT scale?
- **iOS reviews:** confirm the phone should record graded reviews now (Phase 1).
  Any custom grading beyond Again/Good (e.g. latency-aware ease)?
- **Web:** is "the website" a real requirement, and does it need to work without
  the Anki engine (→ pushes toward B/C) or can it be a WASM engine client (A)?
- **Config sync:** should per-user preferences (`config.json`) sync too, or stay
  device-local app config?
- **Privacy/compliance:** study data at rest/in transit — any requirements
  (encryption, region, retention) that affect where the server runs?
- **Media/AI:** do AI-generated cards/explanations need to sync? (If written as
  notes/media they ride along; if only in `sessions.jsonl`/LLM calls they don't.)
