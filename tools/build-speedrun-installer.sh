#!/usr/bin/env bash
# Build a Speedrun LSAT distribution that installs on a clean machine.
#
# Produces:
#   1. Python wheels for the fork's engine + UI + Speedrun package:
#        out/wheels/anki-*.whl, aqt-*.whl, and dist/speedrun_lsat-*.whl
#      -> install path that works anywhere Python 3.12+ runs (see docs/speedrun/INSTALL.md).
#   2. (optional, macOS/Windows) the Briefcase native installer (.dmg / .msi),
#      which needs the platform template submodules.
#
# Usage:
#   tools/build-speedrun-installer.sh            # wheels only (default, portable)
#   tools/build-speedrun-installer.sh --native   # also build the native installer
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"
NATIVE=0
[[ "${1:-}" == "--native" ]] && NATIVE=1

echo "==> Building Anki + aqt wheels (includes the Rust schema-weighted queue)…"
./ninja wheels

echo "==> Building the speedrun-lsat wheel (scoring, drills, taxonomy, seed deck)…"
mkdir -p dist
if command -v uv >/dev/null 2>&1; then
  uv build --wheel packaging/speedrun --out-dir dist
else
  out/pyenv/bin/python -m pip install --quiet build
  out/pyenv/bin/python -m build --wheel packaging/speedrun --outdir dist
fi

echo
echo "Wheels ready:"
ls -1 out/wheels/*.whl 2>/dev/null || true
ls -1 dist/speedrun_lsat-*.whl

if [[ "$NATIVE" == "1" ]]; then
  echo
  echo "==> Initialising Briefcase platform templates (submodules)…"
  git submodule update --init qt/installer/mac-template qt/installer/windows-template || true
  echo "==> Building native installer via Briefcase…"
  RELEASE=2 ./ninja installer
  echo "Native installer artifacts are under out/ (see docs/development.md)."
fi

echo
echo "Done. See docs/speedrun/INSTALL.md for the clean-machine install steps."
