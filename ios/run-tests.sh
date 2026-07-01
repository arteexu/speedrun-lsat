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

echo "PASS: simulator target links anki_buildhash (compile-only; run via Xcode XCTest)"

echo "All iOS engine checks passed."
echo "For XCTest: open ios/AnkiKit in Xcode, select an iOS Simulator, run AnkiKitTests."
