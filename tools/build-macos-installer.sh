#!/usr/bin/env bash
# Build a double-click macOS installer for Speedrun LSAT.
#
# Produces dist/SpeedrunLSAT-macOS/ (and a .zip) containing the three wheels
# (anki, aqt, speedrun-lsat) plus install.command and README.txt. A user copies
# the folder to their Mac and double-clicks install.command - no dev toolchain
# needed on their machine, only Python 3.12+.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
OUT="$REPO/dist/SpeedrunLSAT-macOS"

echo "==> Building wheels (anki + aqt)..."
./ninja wheels

echo "==> Building the speedrun-lsat wheel..."
mkdir -p "$REPO/dist"
if command -v uv >/dev/null 2>&1; then
  uv build --wheel packaging/speedrun --out-dir "$REPO/dist"
else
  out/pyenv/bin/python -m pip install --quiet build
  out/pyenv/bin/python -m build --wheel packaging/speedrun --outdir "$REPO/dist"
fi

echo "==> Assembling installer bundle..."
rm -rf "$OUT"
mkdir -p "$OUT/wheels"
cp out/wheels/anki-*.whl out/wheels/aqt-*.whl "$REPO"/dist/speedrun_lsat-*.whl "$OUT/wheels/"
cp packaging/macos/install.command "$OUT/"
cp packaging/macos/README.txt "$OUT/"
chmod +x "$OUT/install.command"

echo "==> Zipping..."
( cd "$REPO/dist" && rm -f SpeedrunLSAT-macOS.zip && zip -qr SpeedrunLSAT-macOS.zip SpeedrunLSAT-macOS )

echo ""
echo "Done."
echo "  Folder: $OUT"
echo "  Zip:    $REPO/dist/SpeedrunLSAT-macOS.zip"
echo "Ship the zip; users unzip and double-click install.command."
