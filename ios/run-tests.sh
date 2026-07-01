#!/usr/bin/env bash
# Verify iOS engine artifacts, host FFI tests, and simulator buildHash smoke.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
XCFW="$REPO_ROOT/ios/AnkiFFI.xcframework"

if [[ ! -d "$XCFW" ]]; then
  echo "ERROR: $XCFW not found. Run: bash ios/build-xcframework.sh" >&2
  exit 1
fi
echo "OK: AnkiFFI.xcframework present"

echo "Running rslib-ffi host tests (C boundary + buildHash)..."
cd "$REPO_ROOT"
cargo test -p rslib-ffi --quiet

SDK="$(xcrun --sdk iphonesimulator --show-sdk-path)"
DEST="arm64-apple-ios15.0-simulator"
SIM_LIB="$XCFW/ios-arm64-simulator"

cat > /tmp/ffi_smoke.c <<'EOF'
#include "anki_ffi.h"
#include <stdio.h>
int main(void) {
  AnkiBytes b = anki_buildhash();
  if (b.len == 0) {
    return 1;
  }
  fwrite(b.ptr, 1, b.len, stdout);
  anki_bytes_free(b);
  return 0;
}
EOF

cc -isysroot "$SDK" -target "$DEST" \
  -I"$SIM_LIB/Headers" \
  -L"$SIM_LIB" \
  -lanki_ffi \
  -framework CoreFoundation \
  -lobjc \
  /tmp/ffi_smoke.c -o /tmp/ffi_smoke

echo "PASS: simulator target links anki_buildhash (compile-only)"

# Full XCTest on a simulator: opens the bundled exam deck and builds the
# schema-weighted queue on the shared engine (SpeedrunEngineTests).
SIM_NAME="${SIM_NAME:-iPhone 17}"
if xcrun simctl list devices available | grep -q "$SIM_NAME ("; then
  echo "Running AnkiKit XCTest on simulator '$SIM_NAME'..."
  ( cd "$REPO_ROOT/ios/AnkiKit" && \
    xcodebuild test -scheme AnkiKit \
      -destination "platform=iOS Simulator,name=$SIM_NAME" 2>&1 | tail -8 )
  echo "PASS: AnkiKit simulator tests (exam deck + shared-engine queue)"
else
  echo "SKIP: no '$SIM_NAME' simulator; open ios/AnkiKit in Xcode and run AnkiKitTests."
fi

echo "All iOS engine checks passed."
