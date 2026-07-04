# iOS dev: build, run, and test the Speedrun LSAT app

Repo-specific guide for building, running, and testing the native iOS app in
`ios/`. Every command is grounded in the actual repo files
(`ios/build-xcframework.sh`, `ios/App/project.yml`, `ios/run-tests.sh`,
`ios/AnkiKit/`). The phone runs the **same** Anki Rust engine as the desktop,
compiled into `AnkiFFI.xcframework` and called through a single protobuf command
entrypoint — never a Swift reimplementation.

```
rslib-ffi (Rust staticlib, C ABI)  ->  AnkiFFI.xcframework  ->  AnkiKit (Swift)  ->  SwiftUI app (ios/App)
```

## Verified on this machine (2026-07-03)

All build/run/test steps below were **actually executed** on this Mac and
succeeded:

| Tool | Version detected |
|---|---|
| Xcode | **26.6** (Build 17F113), `xcode-select -p` → `/Applications/Xcode.app/Contents/Developer` |
| iOS Simulator SDK | iPhoneSimulator **26.5** |
| XcodeGen | **2.45.4** (already installed) |
| rustup Apple targets | `aarch64-apple-ios`, `aarch64-apple-ios-sim` (both **installed**) |
| Simulators available | iPhone 17, iPhone 17 Pro, iPhone 17 Pro Max, iPhone 17e, iPhone Air |
| `AnkiFFI.xcframework` | present, **166 MB** (gitignored) |

What was run vs. documented:
- **Ran:** `xcodegen generate` → `SpeedrunLSAT.xcodeproj`; `xcodebuild ... build`
  → **BUILD SUCCEEDED**; `xcodebuild test -scheme AnkiKit` → **TEST SUCCEEDED**
  (7 tests, 1 skipped — the sync test, no dev server running); `simctl install`
  + `launch` on the booted iPhone 17 → app runs and shows the shared-engine
  build hash `6770ad3e`, the exam deck, and the three-score dashboard.
- **Only documented, not run:** `bash ios/build-xcframework.sh` — the
  `AnkiFFI.xcframework` was **already built and present**, so it was not
  rebuilt. The exact command is in Step 1.
- **Automated iOS test target: YES.** `ios/AnkiKit/Tests/AnkiKitTests`
  (XCTest, scheme `AnkiKit`). The app target (`ios/App`) has **no** UI/unit test
  target — see Step 5.

---

## Prerequisites (one-time)

Already satisfied on this machine, but for a clean setup:

```bash
# 1. Xcode (from the App Store), then point the toolchain at it + accept license
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -license accept
xcodebuild -runFirstLaunch
# sanity check: prints an SDK path
xcrun --sdk iphonesimulator --show-sdk-path

# 2. XcodeGen (the .xcodeproj is generated, not committed)
brew install xcodegen

# 3. Rust Apple targets (the shared engine is cross-compiled for iOS)
rustup target add aarch64-apple-ios aarch64-apple-ios-sim
```

> Note: `ios/build-xcframework.sh` requires a **full Xcode** (not just Command
> Line Tools), because it runs `xcodebuild -create-xcframework`.

Two build artifacts are **gitignored** and must be generated locally (see
`.gitignore`): `ios/AnkiFFI.xcframework/` and `ios/App/SpeedrunLSAT.xcodeproj/`.
That is why Steps 1 and 2 exist.

---

## Step 1 — Build the shared Rust engine (`AnkiFFI.xcframework`)

```bash
# from the repo root
bash ios/build-xcframework.sh
```

What it does (see the script): builds `rslib-ffi` `--release` for
`aarch64-apple-ios` (device) and `aarch64-apple-ios-sim` (simulator) with
`IPHONEOS_DEPLOYMENT_TARGET=15.0`, then packages both static libs
(`libanki_ffi.a`) + the C headers (`rslib-ffi/include`) into:

- **Output artifact:** `ios/AnkiFFI.xcframework` (~166 MB, gitignored)

`ios/AnkiKit/Package.swift` consumes it as a `binaryTarget`. First build is
~5–10 min; skip this step if `ios/AnkiFFI.xcframework/` already exists (it did
on this machine, so it was not rebuilt).

---

## Step 2 — Generate the Xcode project

The app is defined by an **XcodeGen** spec (`ios/App/project.yml`), so no
`.xcodeproj` is committed — generate it:

```bash
cd ios/App
xcodegen generate      # -> ios/App/SpeedrunLSAT.xcodeproj
```

Verified schemes in the generated project:

```
Schemes:
    AnkiKit          # the Swift package's XCTest scheme
    SpeedrunLSAT     # the app
```

Key facts from `project.yml`: app deployment target **iOS 17.0**, bundle id
`com.speedrunlsat.app`, product name `Speedrun LSAT`, and
`GENERATE_INFOPLIST_FILE: YES` (relevant to sync — see Step 6).

---

## Step 3 — Open in Xcode, or build+run from the CLI

Open in Xcode:

```bash
open ios/App/SpeedrunLSAT.xcodeproj
```

Pick an **iPhone simulator** (e.g. iPhone 17) in the toolbar and press **▶ Run**
(`⌘R`).

Command-line equivalent (this is the exact command that produced **BUILD
SUCCEEDED** here — `iPhone 17` is an available simulator on this machine):

```bash
cd ios/App
xcodebuild -project SpeedrunLSAT.xcodeproj -scheme SpeedrunLSAT \
  -destination 'platform=iOS Simulator,name=iPhone 17' \
  -derivedDataPath build build
# -> build/Build/Products/Debug-iphonesimulator/Speedrun LSAT.app
```

Harmless warnings observed (safe to ignore): `UIDeviceFamily key ... will be
overwritten` and `MinimumOSVersion of '15.0' is less than
IPHONEOS_DEPLOYMENT_TARGET '17.0' - setting to '17.0'` (the AnkiKit package
targets iOS 15, the app targets iOS 17).

Install + launch on a booted simulator:

```bash
cd ios/App
UDID=$(xcrun simctl list devices booted | grep -oE '[0-9A-F-]{36}' | head -1)
# or boot one first: xcrun simctl boot "iPhone 17"; open -a Simulator
xcrun simctl install "$UDID" "build/Build/Products/Debug-iphonesimulator/Speedrun LSAT.app"
xcrun simctl launch  "$UDID" com.speedrunlsat.app
```

---

## Step 4 — What to expect in the simulator

Verified by launching on iPhone 17 (screenshot captured):

- **Home** (`ContentView.swift`): the **shared-engine build hash** (proof Anki's
  Rust engine runs on the device — showed `6770ad3e`), a daily-goal progress
  bar, the **Three scores** (Memory / Performance / Readiness — all "No score
  yet" on the fresh deck), and the **weakest schemas** list
  (e.g. `flaw.causal.correlation_causation`).
- **Study the exam deck** → `ReviewView.swift`: a real LSAT-style problem
  (stimulus, question, choices) ordered by the **schema-weighted queue** built by
  the shared Rust engine (scheduler service `13`, method `39` — the same ordering
  the desktop uses). **Reveal answer** shows the correct choice and why the
  runner-up is wrong.
- Jump straight into review (demo hook):
  ```bash
  UDID=$(xcrun simctl list devices booted | grep -oE '[0-9A-F-]{36}' | head -1)
  SIMCTL_CHILD_SPEEDRUN_START_REVIEW=1 xcrun simctl launch "$UDID" com.speedrunlsat.app
  ```

**Where the deck comes from:** the app bundles
`ios/AnkiKit/Sources/AnkiKit/Resources/collection.anki2` (packaged via
`AnkiKit/Package.swift`). `SpeedrunSession` opens a **persistent** writable copy
in the app's Documents dir, seeded once from that bundled deck. The
human-readable source deck lives in `ios/Resources/exam/`
(`SpeedrunExam.colpkg` + `collection.anki2`).

### Known limitation (do not expect graded reviews to persist yet)

`ReviewView.advance()` only advances the on-screen index — the **Again** and
**Good** buttons both call it and **do not write a graded review back to the
engine**:

```115:119:ios/App/ReviewView.swift
    private func advance() {
        reviewed += 1
        revealed = false
        index = (index + 1) % max(1, queue.count)
    }
```

Consequences until on-device FSRS grading lands (Phase 1):
- The dashboard scores stay "No score yet" no matter how many cards you tap
  through (the collection gets no new revlog entries).
- **Sync has nothing new to upload** from phone reviews, so review write-back /
  round-trip sync isn't functional yet even though the sync client works
  (Step 6). The `SyncView` plumbing and `SpeedrunEngine.sync(...)` are real and
  exercised by tests, but there are no on-device grades to carry.

---

## Step 5 — Run the test suite

There **is** an automated iOS test target: `AnkiKitTests` (XCTest), scheme
`AnkiKit`. It opens the bundled exam deck and drives the shared engine over the
C boundary. Run it exactly as `ios/run-tests.sh` does:

```bash
cd ios/AnkiKit
xcodebuild test -scheme AnkiKit \
  -destination 'platform=iOS Simulator,name=iPhone 17'
```

Verified result here — **TEST SUCCEEDED**, 7 tests, 1 skipped:

- `AnkiBackendTests.testBuildHashNonEmpty` — engine build hash is non-empty.
- `SpeedrunEngineTests`: opens the exam deck + builds the schema-weighted queue
  (`testOpensExamDeckAndBuildsSchemaWeightedQueue`), steps through engine-ordered
  cards, attaches readable card content, computes the three scores over the
  shared RPC, and confirms the bundled deck is present.
- `SpeedrunEngineTests.testSyncAgainstLocalServerIfAvailable` — **skipped**
  ("no dev sync server reachable: Login failed"); it only runs when a dev server
  is up at `127.0.0.1:8080` (Step 6).

Or run the whole repo's iOS verification wrapper (checks the xcframework exists,
runs `cargo test -p rslib-ffi` host C-boundary tests, a simulator link smoke
test, then the XCTest above). It defaults to `SIM_NAME=iPhone 17`:

```bash
bash ios/run-tests.sh
```

**The app target (`ios/App`) has no test target** — there is no XCUITest / app
unit-test bundle in `project.yml`. Practical testing of app-level UI is
**manual in the simulator** (Step 4), plus the engine-level XCTest above which
covers the shared-engine review logic that the UI renders.

You can also open `ios/AnkiKit` directly in Xcode (File → Open → the folder with
`Package.swift`) and run **Product → Test** (`⌘U`).

---

## Step 6 — Test sync from the simulator against a local server

Full sync setup is in [`SYNC-SERVER.md`](SYNC-SERVER.md). The short path for a
local test from the **simulator**:

1. Start a dev sync server (from the repo root — needs `./run` to have built the
   Python env once):
   ```bash
   SYNC_USER1="dev:pass" SYNC_HOST="127.0.0.1" SYNC_PORT="8080" \
   PYTHONPATH=out/pylib out/pyenv/bin/python -m anki.syncserver
   # health check: curl -sS http://127.0.0.1:8080/health   # -> 200
   ```
2. In the running app, open the **Sync** tab. It defaults to
   `http://127.0.0.1:8080/`, user `dev`, password `pass`
   (`ios/App/SyncView.swift`, `@AppStorage("sync.url")`). Tap **Sync now**.
3. Re-running `SpeedrunEngineTests.testSyncAgainstLocalServerIfAvailable` will
   now execute instead of skip.

### ATS: simulator works over HTTP, a physical device needs HTTPS

`ios/App/project.yml` uses `GENERATE_INFOPLIST_FILE: YES` with **no
`NSAppTransportSecurity` exception**. iOS App Transport Security blocks plaintext
HTTP except to `localhost`:

- **Simulator:** `http://127.0.0.1:PORT/` works — the simulator shares the Mac's
  localhost, so it reaches the dev server directly.
- **Physical device:** plaintext to a LAN IP is **blocked**. Use **HTTPS**
  (Caddy or Tailscale, see `SYNC-SERVER.md` §5), or add an
  `NSAppTransportSecurity` exception and rebuild.

Also note the review write-back limitation from Step 4: until on-device grading
lands, a phone sync won't carry new phone reviews (there are none), though the
login/collection-sync RPCs themselves are functional.

---

## Quick reference (all steps, happy path)

```bash
# from repo root
bash ios/build-xcframework.sh                 # Step 1 (skip if xcframework exists)
cd ios/App && xcodegen generate               # Step 2
xcodebuild -project SpeedrunLSAT.xcodeproj -scheme SpeedrunLSAT \
  -destination 'platform=iOS Simulator,name=iPhone 17' \
  -derivedDataPath build build                # Step 3
open SpeedrunLSAT.xcodeproj                    # or run from Xcode
cd ../AnkiKit && xcodebuild test -scheme AnkiKit \
  -destination 'platform=iOS Simulator,name=iPhone 17'   # Step 5
```

## Known issues & likely fixes

| Symptom | Cause | Fix |
|---|---|---|
| `ERROR: iOS SDK not found` from `build-xcframework.sh` | Command Line Tools selected, not full Xcode | `sudo xcode-select -s /Applications/Xcode.app/Contents/Developer` |
| `xcodegen: command not found` | XcodeGen not installed | `brew install xcodegen` |
| Cargo error: target `aarch64-apple-ios` not installed | Rust Apple targets missing | `rustup target add aarch64-apple-ios aarch64-apple-ios-sim` |
| `xcodebuild` can't find scheme `SpeedrunLSAT` | Project not generated | run Step 2 (`xcodegen generate`) |
| Linker can't find `AnkiFFI` / `libanki_ffi` | `AnkiFFI.xcframework` missing | run Step 1 (`bash ios/build-xcframework.sh`) |
| `platform=iOS Simulator,name=iPhone 17` not found | that simulator isn't installed | `xcrun simctl list devices available` and substitute an available name |
| Graded reviews / scores don't persist | `ReviewView.advance()` doesn't write back yet (Step 4) | expected until Phase 1 on-device grading |
| Physical device can't reach the sync server | ATS blocks plaintext HTTP off-localhost | use HTTPS (Caddy/Tailscale) — see `SYNC-SERVER.md` §5 |
