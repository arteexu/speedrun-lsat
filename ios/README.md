# iOS companion — shared Rust engine

The iOS app runs the **same** Anki Rust engine as the desktop (never a Swift
reimplementation). The engine is compiled into an XCFramework and called through
a single protobuf command entrypoint, mirroring `pylib/rsbridge` on desktop.

```
rslib-ffi (Rust staticlib, C ABI)  ->  AnkiFFI.xcframework  ->  AnkiKit (Swift)  ->  SwiftUI app
```

## Status

- [x] `rslib-ffi` C/FFI bridge (open backend + `run_command` over protobuf bytes),
      with host tests that open a collection and run the schema-weighted queue
      **across the C boundary** (`cargo test -p rslib-ffi`).
- [x] iOS Rust targets installed (`aarch64-apple-ios`, `aarch64-apple-ios-sim`).
- [x] Swift wrapper (`AnkiKit/AnkiBackend`) + sample `ContentView`.
- [ ] **XCFramework build — blocked on a full Xcode install** (see prerequisite).
- [ ] SwiftUI review session + three-score dashboard (built on `AnkiBackend`).

## Prerequisite (one-time): install Xcode

This machine currently has only the Command Line Tools, which have no iOS SDK, so
`xcodebuild`/simulator builds fail with `SDK "iphonesimulator" cannot be located`.

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
bash ios/build-xcframework.sh    # produces ios/AnkiFFI.xcframework
```

## Run the app

1. In Xcode: File → New → Project → iOS App (SwiftUI). Name it `SpeedrunLSAT`.
2. Replace the generated `ContentView.swift` with [`App/ContentView.swift`](App/ContentView.swift).
3. File → Add Package Dependencies → Add Local… → select [`ios/AnkiKit`](AnkiKit).
   (AnkiKit references `../AnkiFFI.xcframework`, so build the framework first.)
4. Run on a simulator. The screen shows the Anki engine build hash — proof the
   shared Rust engine loads and runs on the device.

## Next: the review session (uses SwiftProtobuf)

`AnkiBackend.runCommand(service:method:input:)` takes/returns protobuf bytes.
Generate Swift types from `proto/anki/*.proto` with
[SwiftProtobuf](https://github.com/apple/swift-protobuf) (add the SPM plugin), then:

1. Build `BackendInit` → `AnkiBackend(initBytes:)`.
2. `OpenCollectionRequest` → `runCommand(service: 3, method: 0, …)` (indices
   mirror `out/pylib/anki/_backend_generated.py`).
3. Sync the shared deck, then drive the review loop with the scheduler service and
   render the three scores. The **schema-weighted queue** is service `13`,
   method `39` — the same Rust ordering the desktop uses.
