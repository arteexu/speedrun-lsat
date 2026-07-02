Speedrun LSAT - macOS installer
===============================

TO INSTALL
1. Double-click "install.command".
   - If macOS says it "cannot be opened because it is from an unidentified
     developer", right-click it -> Open -> Open. (This is because the installer
     is not code-signed.)
2. Wait a few minutes on first run (it downloads the Qt UI framework).
3. When it finishes, "Speedrun LSAT" appears in your ~/Applications folder.

TO RUN
- Open "Speedrun LSAT" from ~/Applications. The first time, right-click -> Open.
- In the app: Tools -> LSAT Speedrun -> Import seed deck, then Dashboard / Study.

REQUIREMENTS
- macOS 12+ and Python 3.12 or newer.
  Check with:  python3 --version
  If you need it: https://www.python.org/downloads/  (or: brew install python)

WHAT IT DOES / WHERE THINGS GO
- Creates a self-contained environment at:
    ~/Library/Application Support/Speedrun LSAT/venv
- Your study data lives at:
    ~/Library/Application Support/Speedrun LSAT/profile
- It does NOT touch any other Python or Anki install on your machine.

TO UNINSTALL
- Delete "~/Applications/Speedrun LSAT.app" and
  "~/Library/Application Support/Speedrun LSAT".

This is a fork of Anki (AGPL-3.0). See the project README for details.
