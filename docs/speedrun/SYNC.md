# Sync and conflict resolution (Speedrun LSAT)

**Status:** Desktop sync works (inherited from Anki). The self-hosted server and
a two-collection sync test are wired below. iOS has a sync client
(`ios/AnkiKit` `SpeedrunSync`); a phone <-> desktop round-trip is verified on a
device/simulator against the dev server.

## Mechanism

Both desktop and iOS use **Anki's existing sync protocol** via a self-hosted sync
server built from `rslib` (`anki-sync-server` / `python -m anki.syncserver`). The
phone reaches the engine through the same protobuf RPCs as the desktop
(`BackendSyncService`, service `1`): `SyncLogin` (m3), `SyncStatus` (m4),
`SyncCollection` (m5), `FullUploadOrDownload` (m6).

## Conflict rule (how Anki merges)

**The rule:** for the same card reviewed on two devices offline, the **later
real-timestamp review wins** the card's scheduling state. This is implemented via
Anki's **USN + modification-time** merge, so **both revlog rows are kept and none
are double-counted**. The mechanism, precisely:

- **Cards / notes:** merged by **USN + modification time**. A record is taken
  from the incoming side when it is newer (`existing.usn.is_pending_sync(...)` is
  false, or `existing.mtime < incoming.mtime`). See
  `rslib/src/sync/collection/chunks.rs` (`add_or_update_card_if_newer`).
- **Revlog (review history):** entries are keyed by their unique id and added if
  not already present (`merge_revlog`, `uniquify: false`). Reviews from **both**
  devices are preserved, and because ids are unique there is **no double-count**.
- **Card scheduling state** follows the newer card mtime, so a card reviewed on
  two devices ends in one consistent state (no duplicated FSRS state), while both
  review rows remain in history.
- **Clock safety:** if client/server clocks differ by > 300s the server aborts
  the sync (`ClockIncorrect`) rather than guessing an order; fix the clock and
  retry. Normal sync is wrapped in a DB transaction (atomic; mid-sync disconnect
  rolls back).

Net effect required by the milestone: **no reviews lost, none double-counted.**
`speedrun/tools/sync_test.py` verifies this against a live server.

## Offline-first

- iOS reviews offline; pending changes carry USN `-1` and upload on the next sync.
- A mid-sync disconnect leaves the collection consistent (atomic sync).

## Dev sync server

See [SYNC-SERVER.md](SYNC-SERVER.md) for the runbook. Quick start:

```bash
SYNC_USER1=dev:pass SYNC_HOST=127.0.0.1 SYNC_PORT=8080 \
  PYTHONPATH=out/pylib out/pyenv/bin/python -m anki.syncserver
```

Point the desktop at it: Preferences -> Syncing -> self-hosted sync server URL
`http://127.0.0.1:8080/`. Point the phone at the same URL in the app's sync screen.

## Automated test

```bash
PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/sync_test.py
```

Creates two collections (a "desktop" and a "phone"), full-syncs the exam deck up
and down, reviews different cards on each, syncs both, and asserts every review
lands exactly once; then reviews the same card on both and asserts a single
consistent card state with both review rows preserved.
