#!/bin/bash
# Speedrun LSAT - double-click installer for macOS.
# Installs the app into your user Library and puts "Speedrun LSAT.app" in
# ~/Applications. Requires Python 3.12+ (see README.txt if you don't have it).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "== Speedrun LSAT installer =="

# 1. Find a Python 3.12+
PY=""
for c in python3.13 python3.12 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,12) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo ""
  echo "ERROR: Python 3.12 or newer is required and was not found."
  echo "Install it from https://www.python.org/downloads/ (or run 'brew install python'),"
  echo "then double-click this installer again."
  read -r -p "Press Return to close. "
  exit 1
fi
echo "Using $("$PY" --version) at $(command -v "$PY")"

APP_SUPPORT="$HOME/Library/Application Support/Speedrun LSAT"
VENV="$APP_SUPPORT/venv"
mkdir -p "$APP_SUPPORT"

echo "Creating a private environment (this downloads Qt the first time; give it a few minutes)..."
"$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet "$DIR"/wheels/*.whl

# 2. Create a double-clickable app in ~/Applications
APPDIR="$HOME/Applications/Speedrun LSAT.app"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/Contents/MacOS"
cat > "$APPDIR/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Speedrun LSAT</string>
  <key>CFBundleDisplayName</key><string>Speedrun LSAT</string>
  <key>CFBundleIdentifier</key><string>com.speedrunlsat.desktop</string>
  <key>CFBundleVersion</key><string>0.1.0</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>run</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
</dict></plist>
PLIST

# The launcher uses a dedicated profile so it never touches a dev .ankidata.
cat > "$APPDIR/Contents/MacOS/run" <<RUN
#!/bin/bash
export ANKI_BASE="\$HOME/Library/Application Support/Speedrun LSAT/profile"
mkdir -p "\$ANKI_BASE"
exec "$VENV/bin/python" -m aqt
RUN
chmod +x "$APPDIR/Contents/MacOS/run"

echo ""
echo "Installed. 'Speedrun LSAT' is now in ~/Applications."
echo "First launch: right-click it -> Open (it is unsigned, so macOS asks once)."
echo "Then in the app: Tools -> LSAT Speedrun -> Import seed deck."
open "$HOME/Applications" >/dev/null 2>&1 || true
read -r -p "Press Return to close. "
