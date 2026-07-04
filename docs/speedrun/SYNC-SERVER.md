# Self-hosting the Speedrun LSAT sync server

Desktop and iOS sync through a **self-hosted Anki sync server** built from this
repo (no AnkiWeb account needed). Both clients point at the same URL. This guide
is grounded in the actual code:

- Server binary crate: `rslib/sync/` → `anki-sync-server` (`rslib/sync/Cargo.toml`,
  entrypoint `rslib/sync/main.rs`).
- Server implementation + config: `rslib/src/sync/http_server/mod.rs`.
- Python launcher: `pylib/anki/syncserver.py` (`python -m anki.syncserver`).
- Routes served: `/sync/*` (collection), `/msync/*` (media), `/health`
  (`make_server` in `rslib/src/sync/http_server/mod.rs`).

> Web UI is out of scope. This is the sync backend for the desktop + phone apps only.

---

## 1. Prerequisites

You need one of:
- **The Python build env already in the repo** (`out/pyenv` + `out/pylib`),
  produced by running `./run` once. This is the quickest path and what's verified
  below.
- **or the Rust toolchain** (`rust-toolchain.toml` pins `1.92.0`, `cargo` on PATH)
  to build the standalone binary.

---

## 2. Get the server

### Option A — Python launcher (no compile; recommended for a quick start)
Uses the prebuilt backend in `out/pylib`:

```bash
PYTHONPATH=out/pylib out/pyenv/bin/python -m anki.syncserver
```

### Option B — standalone Rust binary (best for a headless home server / VPS)

```bash
cargo build --release -p anki-sync-server
# → target/release/anki-sync-server
```

Run it with `./target/release/anki-sync-server`. Both options read the exact same
`SYNC_*` env vars and behave identically (the Python launcher just calls the same
Rust `SimpleServer`).

---

## 3. Configure it (environment variables)

Config is read from the environment via `envy` (prefix `SYNC_`) plus a few extras.
Source: `rslib/src/sync/http_server/mod.rs`, `rslib/src/sync/request/mod.rs`.

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `SYNC_USER1` | **Yes** | – | First account, `"username:password"`. Server refuses to start with no users. |
| `SYNC_USER2`, `SYNC_USER3`, … | No | – | More accounts; scanned sequentially until the first gap. |
| `SYNC_BASE` | No | `~/.syncserver` | Data dir. Each user gets `SYNC_BASE/<username>/` (collection + media). |
| `SYNC_HOST` | No | `0.0.0.0` | Bind address. Use `127.0.0.1` to keep it local-only behind a proxy. |
| `SYNC_PORT` | No | `8080` | Listen port. |
| `SYNC_IP_HEADER` | No | `ConnectInfo` | Where to read the client IP (e.g. behind a proxy). |
| `PASSWORDS_HASHED` | No | unset | If set, `SYNC_USERn` passwords are treated as pre-hashed instead of plaintext. |
| `MAX_SYNC_PAYLOAD_MEGS` | No | `100` | Max collection upload size (MB). |
| `RUST_LOG` | No | `anki=info` | Log verbosity. |

Notes from the code:
- Passwords are hashed with a **fixed salt** unless `PASSWORDS_HASHED` is set, so
  treat the server as trusted infrastructure and protect it with TLS + network
  controls; don't rely on the hashing for confidentiality.
- The account hkey is derived from `username:password`; **changing a password
  invalidates existing client logins** (they must log in again).

Concrete example (a real cross-device setup on a home server):

```bash
export SYNC_USER1="arthur:choose-a-strong-pass"
export SYNC_BASE="/var/lib/speedrun-sync"
export SYNC_HOST="127.0.0.1"   # only the reverse proxy talks to it
export SYNC_PORT="8080"
```

---

## 4. Run it (foreground)

Python launcher:

```bash
SYNC_USER1="arthur:strong-pass" \
SYNC_BASE="/var/lib/speedrun-sync" \
SYNC_HOST="127.0.0.1" SYNC_PORT="8080" \
PYTHONPATH=out/pylib out/pyenv/bin/python -m anki.syncserver
```

Rust binary:

```bash
SYNC_USER1="arthur:strong-pass" SYNC_BASE="/var/lib/speedrun-sync" \
SYNC_HOST="127.0.0.1" SYNC_PORT="8080" \
./target/release/anki-sync-server
```

It logs `INFO listening addr=...` on startup. Health check any time:

```bash
curl -sS -w '\n%{http_code}\n' http://127.0.0.1:8080/health   # → 200
```

### Run it persistently

**systemd (Linux, using the Rust binary):** `/etc/systemd/system/speedrun-sync.service`

```ini
[Unit]
Description=Speedrun LSAT sync server
After=network.target

[Service]
Environment=SYNC_USER1=arthur:strong-pass
Environment=SYNC_BASE=/var/lib/speedrun-sync
Environment=SYNC_HOST=127.0.0.1
Environment=SYNC_PORT=8080
ExecStart=/opt/speedrun/anki-sync-server
Restart=on-failure
User=speedrun

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now speedrun-sync
sudo journalctl -u speedrun-sync -f
```

**macOS / quick option:** run it inside `tmux`/`screen`, or write a `launchd`
plist under `~/Library/LaunchAgents/` with the same env vars and
`ProgramArguments` pointing at the binary. `--healthcheck` (see `rslib/sync/main.rs`)
exits 0/1 for liveness probes.

---

## 5. Expose it safely over HTTPS

Mobile clients should **not** sync over plaintext (see the iOS ATS note in §7).
Bind the server to `127.0.0.1` and put a TLS reverse proxy in front, or use a
private mesh.

### Option A — Caddy (automatic HTTPS with a real domain)

```caddyfile
sync.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

`caddy run` (or as a service) gets a Let's Encrypt cert automatically. Clients
then use `https://sync.example.com/`. (nginx works too; just proxy_pass to
`127.0.0.1:8080` and allow large bodies to cover `MAX_SYNC_PAYLOAD_MEGS`.)

### Option B — Tailscale (private mesh, no public exposure)

Install Tailscale on the server and each device; point clients at the server's
tailnet name (`http://server-name:8080/`), optionally with `tailscale serve` for
TLS. Nothing is exposed to the public internet.

---

## 6. Point the clients at it

### Desktop
Anki → **Preferences → Syncing → self-hosted sync server** and enter the URL
(with a **trailing slash**), e.g. `https://sync.example.com/`. Mechanism:
`qt/aqt/preferences.py` writes `custom_sync_url`, stored as `customSyncUrl` and
read by `Profile.sync_endpoint()` (`qt/aqt/profiles.py`). Then Sync (Y).

### iOS
Open the app's **Sync** screen and set **Server URL** (trailing slash),
Username, Password. No rebuild needed — the URL is a runtime setting:
`ios/App/SyncView.swift` stores it via `@AppStorage("sync.url")` (defaults to
`http://127.0.0.1:8080/`) and calls `SpeedrunEngine.sync(url:username:password:)`
(`ios/AnkiKit/Sources/AnkiKit/SpeedrunEngine.swift`), which uses the same
`BackendSyncService` RPCs as the desktop.

**Endpoint format:** the client joins `sync/` onto your base URL
(`as_sync_endpoint` in `rslib/src/sync/collection/protocol.rs` does
`base.join("sync/")`), so always give the **base** URL ending in `/`
(e.g. `https://sync.example.com/`) — do **not** append `/sync/` yourself.

---

## 7. First sync (seed the collection — read this before connecting the phone)

The first time a device talks to an empty server, Anki asks whether to **upload**
(push this device's collection to the server) or **download** (replace this
device with the server's). Choose deliberately so nothing is clobbered:

1. **Pick the source of truth** — normally the **desktop**, which has your real
   study history in `.ankidata`.
2. On that device, sync first and choose **Upload** to seed the server.
3. Only then connect the **other** device (phone / second desktop) and choose
   **Download** so it pulls the seeded collection.
4. After both sides have synced once, subsequent syncs are automatic two-way
   merges (USN + mtime for cards/notes; revlog merged by unique id → no reviews
   lost or double-counted; see `SYNC.md`).

> Caution: choosing **Upload** on an empty/fresh device, or **Download** on the
> device that holds your real history, will overwrite the good data. When in
> doubt, back up (`.ankidata/User 1/backups/` holds `.colpkg` snapshots).

---

## 8. Verify end to end

Automated two-collection round trip (starts its own server instance):

```bash
PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/sync_test.py
```

Manual: review a card on the phone → Sync; then Sync on desktop and confirm the
review appears.

---

## 9. Troubleshooting

- **`No users defined; SYNC_USER1 env var should be set.`** — you started the
  server without `SYNC_USER1`. Set at least one `username:password`.
- **Login fails / 403** — wrong credentials, or the password was changed on the
  server (the hkey is derived from `username:password`, so re-enter it on the
  client). Usernames/passwords are case-sensitive and split on the first `:`.
- **`/sync/hostKey` returns 400 to curl** — expected; the endpoint requires a
  proper multipart sync request, not a bare POST. Use `/health` for a plain
  liveness check.
- **Trailing-slash / 404s** — give clients the **base** URL ending in `/`
  (`https://host/`), never `https://host/sync/`.
- **iOS can't connect to a plaintext LAN server (real device):** iOS App
  Transport Security blocks non-HTTPS except `localhost`. The project uses
  `GENERATE_INFOPLIST_FILE: YES` with **no ATS exception** (`ios/App/project.yml`),
  so on a physical device you must use **HTTPS** (Caddy/Tailscale, §5) — or add an
  `NSAppTransportSecurity` exception and rebuild. The **simulator** can use
  `http://127.0.0.1:PORT/` because it shares the Mac's localhost.
- **`ClockIncorrect` / sync aborts** — client and server clocks must be within
  **300s**; fix the clock and retry.
- **Self-signed cert errors** — use a real cert (Caddy/Let's Encrypt) or
  Tailscale; clients validate TLS.
- **Large collection upload rejected** — raise `MAX_SYNC_PAYLOAD_MEGS` (default
  100 MB) and make sure the reverse proxy allows a matching request body size.
- **Data location** — each user's collection/media live under
  `SYNC_BASE/<username>/`; this is separate from your normal `.ankidata` profile,
  so the dev server never touches your real desktop collection.
