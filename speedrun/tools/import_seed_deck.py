#!/usr/bin/env python3
"""Import the LSAT Speedrun seed deck into an Anki collection.

Creates (idempotently) an "LSAT Speedrun" note type whose cards carry schema
metadata, plus an "LSAT Speedrun" deck, then imports each item from
speedrun/data/seed_deck.json. A card's schema is stored both in a field and as
note tags so the schema-weighted queue (which reads the `sr:schema:` tag) and the
coverage/scoring layer can find it.

Tag conventions:
    sr:schema:<id>   primary mastery unit (flaw.* and rc.* ids)
    sr:qtype:<id>    question type (qt.* ids)
    sr:trap:<id>     trap types (item schemas + per-choice traps)
    sr:section:<LR|RC>

Usage:
    # against a specific collection file
    python speedrun/tools/import_seed_deck.py --col /path/to/collection.anki2

    # against a running dev profile's data dir (close Anki first!)
    python speedrun/tools/import_seed_deck.py --base ~/dev/speedrun-lsat/.ankidata
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DECK_JSON = REPO_ROOT / "speedrun" / "data" / "seed_deck.json"
SEED_ITEM_COUNT = len(
    json.loads(DEFAULT_DECK_JSON.read_text(encoding="utf-8"))["items"]
)

NOTETYPE_NAME = "LSAT Speedrun"
DECK_NAME = "LSAT Speedrun"
SCHEMA_TAG = "sr:schema:"
QTYPE_TAG = "sr:qtype:"
TRAP_TAG = "sr:trap:"
SECTION_TAG = "sr:section:"

FIELDS = [
    "ItemId",
    "Section",
    "QuestionType",
    "Schema",
    "Difficulty",
    "Stimulus",
    "Question",
    "Choices",
    "Correct",
    "RunnerUp",
    "WhyRunnerUpWrong",
    "Source",
    "ParaphraseStimulus",
    "ParaphraseQuestion",
]

FRONT_TEMPLATE = """<div class="section">{{Section}} · {{QuestionType}}</div>
<div class="stimulus">{{Stimulus}}</div>
<div class="question">{{Question}}</div>
<div class="choices">{{Choices}}</div>
"""

BACK_TEMPLATE = """{{FrontSide}}
<hr id="answer">
<div class="correct">Correct: {{Correct}}</div>
<div class="fork"><b>Why the runner-up ({{RunnerUp}}) is wrong:</b> {{WhyRunnerUpWrong}}</div>
<div class="schema">Schema: {{Schema}}</div>
"""

CSS = """.card { font-family: system-ui, sans-serif; font-size: 18px; color: #202020; }
.section { color: #777; font-size: 13px; text-transform: uppercase; letter-spacing: .04em; }
.stimulus { margin: 12px 0; }
.question { font-weight: 600; margin: 12px 0; }
.choices { white-space: pre-line; }
.correct { color: #1a7f37; font-weight: 600; margin-top: 8px; }
.fork { margin-top: 8px; }
.schema { color: #777; font-size: 13px; margin-top: 8px; }
"""


@dataclass
class ImportResult:
    added: int
    skipped: int
    notetype_created: bool
    deck_id: int
    backup_path: str | None = None


def is_seed_deck_imported(col) -> bool:
    """True when the full seed deck is already present in the collection."""
    return len(col.find_notes(f'"note:{NOTETYPE_NAME}"')) >= SEED_ITEM_COUNT


def _checkpoint_collection_db(col_path: Path, col) -> bool:
    """Flush WAL pages into the main db file before a filesystem copy."""
    db = getattr(col, "db", None)
    if db is not None:
        try:
            db.execute("PRAGMA wal_checkpoint(FULL)")
            return True
        except Exception as exc:
            logger.warning("WAL checkpoint via collection failed: %s", exc)
    try:
        with sqlite3.connect(str(col_path), timeout=5.0) as conn:
            conn.execute("PRAGMA wal_checkpoint(FULL)")
        return True
    except sqlite3.Error as exc:
        logger.warning(
            "Skipping collection backup: cannot checkpoint %s (%s)", col_path, exc
        )
        return False


def backup_collection(col) -> Path | None:
    """Copy the collection file before a bulk import."""
    col_path = Path(col.path)
    if not col_path.is_file():
        return None
    if not _checkpoint_collection_db(col_path, col):
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = col_path.with_name(f"{col_path.stem}.speedrun-backup-{stamp}{col_path.suffix}")
    shutil.copy2(col_path, dest)
    return dest


def _axis_tags(schema_id: str) -> list[str]:
    """Route a taxonomy id to the right tag namespace(s)."""
    if schema_id.startswith(("flaw.", "rc.")):
        return [SCHEMA_TAG + schema_id]
    if schema_id.startswith("qt."):
        return [QTYPE_TAG + schema_id]
    if schema_id.startswith("trap."):
        return [TRAP_TAG + schema_id]
    return [SCHEMA_TAG + schema_id]


def _primary_schema(item: dict[str, Any]) -> str:
    for sid in item.get("schemas", []):
        if sid.startswith(("flaw.", "rc.")):
            return sid
    # fall back to the first schema of any axis
    schemas = item.get("schemas", [])
    return schemas[0] if schemas else ""


def _render_choices(item: dict[str, Any]) -> str:
    lines = []
    for ch in item.get("choices", []):
        lines.append(f"({ch['id']}) {ch['text']}")
    return "\n".join(lines)


def ensure_notetype(col) -> tuple[Any, bool]:
    existing = col.models.by_name(NOTETYPE_NAME)
    if existing:
        return existing, False
    mm = col.models
    nt = mm.new(NOTETYPE_NAME)
    for fname in FIELDS:
        mm.add_field(nt, mm.new_field(fname))
    tmpl = mm.new_template("LSAT Card")
    tmpl["qfmt"] = FRONT_TEMPLATE
    tmpl["afmt"] = BACK_TEMPLATE
    mm.add_template(nt, tmpl)
    nt["css"] = CSS
    mm.add(nt)
    return mm.by_name(NOTETYPE_NAME), True


def build_tags(item: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    # Guarantee exactly one primary schema tag (the unit of mastery) so every
    # card is visible to the schema-weighted queue and memory score: flaw/rc if
    # present, otherwise the question-type procedure (e.g. paradox).
    primary = _primary_schema(item)
    if primary:
        tags.append(SCHEMA_TAG + primary)
    for sid in item.get("schemas", []):
        tags.extend(_axis_tags(sid))
    for ch in item.get("choices", []):
        trap = ch.get("trap")
        if trap:
            tags.append(TRAP_TAG + trap)
    tags.append(SECTION_TAG + item.get("section", ""))
    # de-duplicate, preserve order
    seen = set()
    out = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def import_seed_deck(
    col, deck_json: Path = DEFAULT_DECK_JSON, *, backup: bool = True
) -> ImportResult:
    backup_path = backup_collection(col) if backup else None
    data = json.loads(Path(deck_json).read_text(encoding="utf-8"))
    nt, created = ensure_notetype(col)
    deck_id = col.decks.id(DECK_NAME)

    added = 0
    skipped = 0
    for item in data["items"]:
        item_id = item["id"]
        # idempotency: skip if an ItemId note already exists
        if col.find_notes(f'"note:{NOTETYPE_NAME}" "ItemId:{item_id}"'):
            skipped += 1
            continue
        note = col.new_note(nt)
        note["ItemId"] = item_id
        note["Section"] = item.get("section", "")
        note["QuestionType"] = item.get("stem_type", "")
        note["Schema"] = _primary_schema(item)
        note["Difficulty"] = str(item.get("difficulty", ""))
        note["Stimulus"] = item.get("stimulus") or item.get("passage", "")
        note["Question"] = item.get("question", "")
        note["Choices"] = _render_choices(item)
        fork = item.get("two_answer_fork", {})
        correct = next(
            (c["id"] for c in item.get("choices", []) if c.get("correct")), ""
        )
        note["Correct"] = correct
        note["RunnerUp"] = fork.get("runner_up", "")
        note["WhyRunnerUpWrong"] = fork.get("why_runner_up_wrong", "")
        note["Source"] = item.get("source", "")
        paraphrases = item.get("paraphrases") or []
        if paraphrases:
            note["ParaphraseStimulus"] = paraphrases[0].get("stimulus", "")
            note["ParaphraseQuestion"] = paraphrases[0].get("question", "")
        else:
            note["ParaphraseStimulus"] = ""
            note["ParaphraseQuestion"] = ""
        note.tags = build_tags(item)
        col.add_note(note, deck_id)
        added += 1

    return ImportResult(
        added, skipped, created, deck_id, backup_path=str(backup_path) if backup_path else None
    )


def _open_collection(args):
    from anki.collection import Collection

    if args.col:
        return Collection(args.col)
    if args.base:
        # find the collection.anki2 inside the profile folder
        base = Path(args.base).expanduser()
        matches = list(base.glob("**/collection.anki2"))
        if not matches:
            raise SystemExit(f"No collection.anki2 found under {base}")
        return Collection(str(matches[0]))
    raise SystemExit("Pass --col PATH or --base PROFILE_DIR")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--col", help="path to a collection.anki2 file")
    ap.add_argument("--base", help="an ANKI_BASE profile dir (close Anki first)")
    ap.add_argument("--deck-json", type=Path, default=DEFAULT_DECK_JSON)
    ap.add_argument("--no-backup", action="store_true", help="skip auto-backup")
    args = ap.parse_args(argv)

    col = _open_collection(args)
    try:
        result = import_seed_deck(col, args.deck_json, backup=not args.no_backup)
    finally:
        col.close()
    print(
        f"Imported into '{DECK_NAME}': {result.added} added, {result.skipped} "
        f"skipped (already present). Note type "
        f"{'created' if result.notetype_created else 'reused'}."
    )
    if result.backup_path:
        print(f"Backup: {result.backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
