# Installing Speedrun LSAT on a clean machine

Speedrun LSAT is a fork of Anki: a custom Rust engine (the schema-weighted
review queue) plus a Python package (`speedrun`) that adds the three honest
scores, the evidence gate, and the learning-science drills.

Three paths: the **one-click macOS installer** (easiest for end users), the
portable **wheels** path, and the native **Briefcase** `.dmg`/`.msi`.

---

## Easiest — one-click macOS installer (for end users)

Build a distributable installer bundle (on a machine with the dev toolchain):

```bash
tools/build-macos-installer.sh
# -> dist/SpeedrunLSAT-macOS.zip
```

Send `SpeedrunLSAT-macOS.zip` to the user. They:

1. Unzip it and **double-click `install.command`** (first time, right-click ->
   Open, since it is unsigned).
2. It creates a private environment and puts **"Speedrun LSAT.app" in
   ~/Applications**. Open it (right-click -> Open the first time).
3. In the app: **Tools -> LSAT Speedrun -> Import seed deck**.

The only requirement on the user's Mac is **Python 3.12+** (the installer checks
and points them to python.org if missing). It bundles the three wheels (anki,
aqt, speedrun-lsat), installs Qt automatically, uses a dedicated profile at
`~/Library/Application Support/Speedrun LSAT/`, and never touches any other
Python/Anki install. Verified end to end by installing into a fresh HOME and
importing `aqt` + `speedrun`.

---

## Path A — Wheels (portable, verified)

Requirements on the clean machine: **Python 3.12+** and `pip`.

1. Build the three wheels on a build machine (needs the Rust toolchain):

   ```bash
   tools/build-speedrun-installer.sh
   # -> out/wheels/anki-*.whl, out/wheels/aqt-*.whl, dist/speedrun_lsat-*.whl
   ```

2. Copy those wheels to the clean machine and install into a fresh venv:

   ```bash
   python3 -m venv ~/speedrun-venv
   source ~/speedrun-venv/bin/activate       # Windows: ~\speedrun-venv\Scripts\activate
   pip install anki-*.whl aqt-*.whl speedrun_lsat-*.whl
   ```

3. Run it:

   ```bash
   python -m aqt
   ```

   Anki launches with **Tools → LSAT Speedrun**. Because `speedrun` is installed
   as a real package, the Qt shim finds it via `import speedrun` (no source
   checkout required — see `_ensure_speedrun_on_path()` in
   `qt/aqt/speedrun/__init__.py`).

4. First run: **Tools → LSAT Speedrun → Import seed deck** to load the exam deck,
   or point it at the bundled `ios/Resources/exam/SpeedrunExam.colpkg`.

The `speedrun_lsat` wheel bundles its data (taxonomy JSON, seed deck, config),
verified by `pylib/tests/test_speedrun_packaging.py`.

---

## Path B — Native installer (.dmg / .msi) via Briefcase

Anki's Briefcase pipeline is inherited by the fork. The macOS and Windows
templates are git submodules, so initialise them first:

```bash
git submodule update --init qt/installer/mac-template qt/installer/windows-template
tools/build-speedrun-installer.sh --native
```

This runs `RELEASE=2 ./ninja installer` (see `docs/development.md` for the
per-OS output locations: `.dmg` on macOS, `.msi` on Windows, tarball on Linux).

> Note: the stock Briefcase app is branded "Anki". To ship a Speedrun-branded
> bundle that also carries the `speedrun` package, include the
> `speedrun_lsat` wheel from Path A in the app's dependencies before packaging.

---

## Verifying an install

```bash
# the installed package imports and carries its data (no source tree needed)
python -c "import speedrun.scoring.memory; from importlib.resources import files; \
print((files('speedrun')/'data'/'seed_deck.json').is_file())"
```

For the full proof checklist (commit hash, tests, recordings) see
`docs/speedrun/CHECKLIST.md`.
