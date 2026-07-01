#!/usr/bin/env python3
"""Build a portable exam deck for the mobile app (and demos).

Creates a fresh Anki collection, imports the Speedrun seed deck into it, and
writes two artifacts:

  * ``collection.anki2`` -- a raw collection the iOS app opens directly through
    the shared Rust engine (``anki_backend_run_command`` -> OpenCollection).
  * ``SpeedrunExam.colpkg`` -- a portable collection package for desktop import
    or archival.

Usage:
    PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/export_exam_deck.py
    # custom output dir:
    ... speedrun/tools/export_exam_deck.py --out ios/Resources/exam
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_OUT = REPO_ROOT / "ios" / "Resources" / "exam"


def build(out_dir: Path) -> tuple[Path, Path]:
    from anki.collection import Collection

    from speedrun.tools.import_seed_deck import DECK_NAME, import_seed_deck

    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="speedrun-exam-"))
    col_path = work / "collection.anki2"
    col = Collection(str(col_path))
    try:
        result = import_seed_deck(col, backup=False)
        n = col.db.scalar(f'select count() from cards')
        print(f"Imported {result.added} notes into '{DECK_NAME}' ({n} cards).")
        colpkg = out_dir / "SpeedrunExam.colpkg"
        col.export_collection_package(str(colpkg), include_media=False, legacy=False)
    finally:
        col.close()

    # Copy the raw collection file (post-close: clean, checkpointed) for iOS.
    raw_dest = out_dir / "collection.anki2"
    shutil.copy2(col_path, raw_dest)
    shutil.rmtree(work, ignore_errors=True)
    return raw_dest, out_dir / "SpeedrunExam.colpkg"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory")
    args = ap.parse_args(argv)
    raw, pkg = build(args.out)
    print(f"Raw collection: {raw}  ({raw.stat().st_size} bytes)")
    print(f"Portable package: {pkg}  ({pkg.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
