#!/usr/bin/env bash
# Build Anki's Rust engine (rslib-ffi) into an XCFramework for iOS device +
# simulator. Requires a FULL Xcode install (not just Command Line Tools):
#   xcode-select -p   ->  should be /Applications/Xcode.app/Contents/Developer
#
# Run from anywhere; paths are resolved relative to the repo root.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

CRATE="rslib-ffi"
LIB="libanki_ffi.a"
HEADERS="$REPO_ROOT/$CRATE/include"
OUT="$REPO_ROOT/ios/AnkiFFI.xcframework"

# Preconditions -------------------------------------------------------------
if ! xcrun --sdk iphonesimulator --show-sdk-path >/dev/null 2>&1; then
  echo "ERROR: iOS SDK not found. Install Xcode from the App Store, then run:" >&2
  echo "  sudo xcode-select -s /Applications/Xcode.app/Contents/Developer" >&2
  echo "  sudo xcodebuild -license accept" >&2
  exit 1
fi

rustup target add aarch64-apple-ios aarch64-apple-ios-sim >/dev/null

# Build ---------------------------------------------------------------------
echo "Building device (aarch64-apple-ios)…"
cargo build -p "$CRATE" --release --target aarch64-apple-ios
echo "Building simulator (aarch64-apple-ios-sim)…"
cargo build -p "$CRATE" --release --target aarch64-apple-ios-sim

TARGET_DIR="$(cargo metadata --format-version=1 \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["target_directory"])')"

DEVICE_LIB="$TARGET_DIR/aarch64-apple-ios/release/$LIB"
SIM_LIB="$TARGET_DIR/aarch64-apple-ios-sim/release/$LIB"

# Package -------------------------------------------------------------------
rm -rf "$OUT"
xcodebuild -create-xcframework \
  -library "$DEVICE_LIB" -headers "$HEADERS" \
  -library "$SIM_LIB" -headers "$HEADERS" \
  -output "$OUT"

echo "Created $OUT"
echo "Open ios/AnkiKit in Xcode, or add it as a local Swift package to an app."
