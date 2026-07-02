# Launching the Speedrun LSAT mobile app

Instructions for running the iOS app on a Mac. The phone runs Anki's **shared
Rust engine** (compiled into an XCFramework), opens the bundled 64-card exam
deck, and drives a schema-weighted review session.

## Requirements

- A **Mac** with **Xcode** (install from the App Store).
- **Homebrew** and **Rust**.

One-time setup:

```bash
# Xcode toolchain
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -license accept

# tools
brew install xcodegen
brew install rustup-init && rustup-init -y      # or: curl https://sh.rustup.rs -sSf | sh
rustup target add aarch64-apple-ios aarch64-apple-ios-sim
```

## Build and run

```bash
# 1. Get the code
git clone https://github.com/arteexu/speedrun-lsat.git
cd speedrun-lsat

# 2. Build the shared Rust engine for iOS (~5–10 min the first time; ~166 MB output)
bash ios/build-xcframework.sh

# 3. Generate the Xcode project and open it
cd ios/App
xcodegen generate
open SpeedrunLSAT.xcodeproj
```

In Xcode: pick an **iPhone simulator** (e.g. iPhone 17) in the toolbar, then press
**▶ Run** (`⌘R`).

## What you should see

- **Home:** the shared-engine build hash (proof Anki's Rust engine is running on
  the device) and the exam-deck card count (64).
- Tap **Study the exam deck** → a real LSAT-style problem (stimulus, question,
  choices) ordered by the schema-weighted queue.
- Tap **Reveal answer** → the correct answer and why the runner-up is wrong.

Jump straight into review (handy for a demo):

```bash
UDID=$(xcrun simctl list devices booted | grep -oE '[0-9A-F-]{36}' | head -1)
SIMCTL_CHILD_SPEEDRUN_START_REVIEW=1 xcrun simctl launch "$UDID" com.speedrunlsat.app
```

## Verify the engine (optional)

```bash
# from the repo root
bash ios/run-tests.sh
```
Runs the Rust FFI host tests and the AnkiKit simulator tests (which open the exam
deck and build the schema-weighted queue on the shared engine).

## Running on a real iPhone

In Xcode → the target's **Signing & Capabilities** → select your Team (a free
personal Apple ID team works) → choose your connected phone as the run
destination → **Run**. First launch: on the phone, trust the developer cert under
**Settings → General → VPN & Device Management**.

## Notes

- The `AnkiFFI.xcframework` (166 MB) and the generated `.xcodeproj` are **not**
  committed, which is why the `build-xcframework.sh` and `xcodegen generate`
  steps are required.
- Two-way sync and on-device FSRS grading (Again/Good rescheduling) are not built
  yet; the phone loads and reviews the same deck as desktop on the shared engine.
- Not a developer? It's easier to watch a screen recording or have the owner run
  it and screen-share — there is no signed TestFlight build yet.
