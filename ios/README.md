# iOS companion — shared Rust engine

The iOS app runs the **same** Anki Rust engine as the desktop (never a Swift
reimplementation). The engine is compiled into an XCFramework and called through
a single protobuf command entrypoint, mirroring `pylib/rsbridge` on desktop.

```
rslib-ffi (Rust staticlib, C ABI)  ->  AnkiFFI.xcframework  ->  AnkiKit (Swift)  ->  SwiftUI app
```

## Status

- [x] `rslib-ffi` C/FFI bridge (open backend + `runCommand` over protobuf bytes),
      with host tests that open a collection and run the schema-weighted queue
      **across the C boundary** (`cargo test -p rslib-ffi`), including opening the
      **real exam deck** (`open_exam_deck_and_queue_over_ffi`).
- [x] iOS Rust targets installed (`aarch64-apple-ios`, `aarch64-apple-ios-sim`).
- [x] Swift wrapper (`AnkiKit/AnkiBackend`) + `SpeedrunEngine` (open deck +
      schema-weighted queue) + bundled exam deck resource.
- [x] **XCFramework build** — `bash ios/build-xcframework.sh` (requires full Xcode).
- [x] **AnkiKitTests** — `testBuildHashNonEmpty` **plus** `SpeedrunEngineTests`
      (opens the exam deck + builds the schema-weighted queue on the shared
      engine), passing on the iOS 26.5 simulator.
- [x] **Runnable SwiftUI app** (`ios/App`, XcodeGen `project.yml`): dashboard +
      review session over the shared engine. Builds, launches, and reviews the
      exam deck on the simulator (see `ios/screenshot-*.png`).
- [ ] Full FSRS grading UI on the phone (engine supports it; desktop has it).
- [ ] Two-way sync with desktop.

## Prerequisite (one-time): Xcode

1. Install **Xcode** from the App Store.
2. Point the toolchain at it and accept the license:
   ```bash
   sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
   sudo xcodebuild -license accept
   xcodebuild -runFirstLaunch
   ```
3. Verify: `xcrun --sdk iphonesimulator --show-sdk-path` prints a path.

## Build the engine framework

```bash
bash ios/build-xcframework.sh    # produces ios/AnkiFFI.xcframework (~166 MB, gitignored)
```

Deployment target: **iOS 15** (set in `.cargo/config.toml` and the build script).

## Verify (no Xcode GUI required)

```bash
bash ios/run-tests.sh
```

This checks:

1. `AnkiFFI.xcframework` exists.
2. `cargo test -p rslib-ffi` (host C-boundary tests).
3. Simulator target compiles and links `anki_buildhash`.

## Run XCTest on simulator (Xcode)

1. Open `ios/AnkiKit` in Xcode (File → Open → select the folder with `Package.swift`).
2. Select an **iOS Simulator** destination (iPhone 15 or similar).
3. Product → Test (⌘U), or run the **AnkiKitTests** scheme.
4. `testBuildHashNonEmpty` should pass — non-empty engine build hash.

## Build & run the app (simulator or device)

The app target is defined by [`App/project.yml`](App/project.yml) (XcodeGen), so
no `.xcodeproj` is committed — generate it once:

```bash
brew install xcodegen                 # one-time
bash ios/build-xcframework.sh         # build the shared engine (if not already)
cd ios/App && xcodegen generate       # -> SpeedrunLSAT.xcodeproj
```

Then either open it in Xcode and press **Run**, or from the CLI:

```bash
# build for the simulator
xcodebuild -project SpeedrunLSAT.xcodeproj -scheme SpeedrunLSAT \
  -destination 'platform=iOS Simulator,name=iPhone 17' -derivedDataPath build build

# launch it
UDID=$(xcrun simctl list devices available | grep -m1 'iPhone 17 ' | grep -oE '[0-9A-F-]{36}')
xcrun simctl boot "$UDID"; sleep 5
xcrun simctl install "$UDID" "build/Build/Products/Debug-iphonesimulator/Speedrun LSAT.app"
xcrun simctl launch "$UDID" com.speedrunlsat.app
```

The home screen shows the shared engine build hash and the exam-deck card count;
**Study the exam deck** opens the review session driven by the schema-weighted
queue (service `13`, method `39` — the same Rust ordering the desktop uses).
Launch straight into review with `SIMCTL_CHILD_SPEEDRUN_START_REVIEW=1`.

## How the review path works (no SwiftProtobuf dependency)

`AnkiBackend.runCommand(service:method:input:)` takes/returns protobuf bytes.
`SpeedrunEngine` (in `AnkiKit`) encodes the few flat messages it needs with a
tiny built-in codec (`Protobuf.swift`) — the same wire format the desktop uses:

1. `BackendInit` → `AnkiBackend(initBytes:)`.
2. `OpenCollectionRequest` → `runCommand(service: 3, method: 0, …)` on a writable
   copy of the bundled exam deck (`AnkiKit/Sources/AnkiKit/Resources/collection.anki2`).
3. `SchemaWeightedQueueRequest` → `runCommand(service: 13, method: 39, …)`, decode
   `SchemaWeightedQueueResponse`.

For richer messages (full FSRS grading UI), swap in
[SwiftProtobuf](https://github.com/apple/swift-protobuf) and generate from
`proto/anki/*.proto`.
