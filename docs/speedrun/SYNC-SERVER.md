# Running the dev sync server

Speedrun LSAT syncs desktop and phone through a **self-hosted Anki sync server**
built from `rslib` (no AnkiWeb account needed). Both clients point at it.

## Start the server

```bash
# from the repo root, after a build (./run once)
SYNC_USER1=dev:pass \
SYNC_HOST=127.0.0.1 \
SYNC_PORT=8080 \
SYNC_BASE="$HOME/.speedrun-syncserver" \
PYTHONPATH=out/pylib out/pyenv/bin/python -m anki.syncserver
```

- `SYNC_USER1` is `username:password` (add `SYNC_USER2=...` for more users).
- `SYNC_BASE` is where the server stores each user's collection.
- Leave it running; it logs requests.

Alternative (standalone Rust binary, no Python):

```bash
cargo run -p anki-sync-server   # honors the same SYNC_* env vars
```

## Point the desktop at it

Anki -> Preferences -> **Syncing** -> "self-hosted sync server" ->
`http://127.0.0.1:8080/`. Then Sync (Y). First sync uploads the collection.

## Point the phone at it

In the app's **Sync** screen enter:
- Server URL: `http://127.0.0.1:8080/` (simulator shares the host network; on a
  real device use the Mac's LAN IP, e.g. `http://192.168.1.20:8080/`)
- Username / password: `dev` / `pass`

Tap **Sync**. The phone logs in (`SyncLogin`), checks status (`SyncStatus`), then
runs `SyncCollection` (full up/download on first run).

## Verify end to end

```bash
PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/sync_test.py
```

This starts its own server instance and proves two-way merge with no lost or
double-counted reviews. For the phone->desktop demo: review a card on the phone,
Sync; then Sync on the desktop and confirm the review appears.

## Notes
- Client and server clocks must be within 300s or the sync aborts (`ClockIncorrect`).
- The server data dir (`SYNC_BASE`) is separate from your normal `.ankidata`
  profile, so dev sync never touches your real collection.
