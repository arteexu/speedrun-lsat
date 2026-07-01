# Installing Speedrun LSAT on a clean machine

Speedrun LSAT is a fork of Anki: a custom Rust engine (the schema-weighted
review queue) plus a Python package (`speedrun`) that adds the three honest
scores, the evidence gate, and the learning-science drills.

There are two supported install paths. **Path A (wheels)** is the portable,
scriptable "installer that runs on a clean machine" and is what the automated
checks exercise. **Path B (native installer)** produces a double-clickable
`.dmg` / `.msi` via Briefcase.

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
