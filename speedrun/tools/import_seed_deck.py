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

Each machine tag also gets a friendly, hierarchical companion for the Browse
sidebar, e.g. ``LSAT::Traps::Too_strong_extreme`` (the engine only reads the
``sr:*`` tags; the ``LSAT::*`` tags are display-only).

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

import re

from speedrun.taxonomy.labels import normalize_schema_id, schema_label

NOTETYPE_NAME = "LSAT Speedrun"
DECK_NAME = "LSAT Speedrun"
# Dedicated options group for the Speedrun deck, so raising its daily limits
# never touches Anki's shared global "Default" config (id 1) or any other deck.
DECK_CONFIG_NAME = "LSAT Speedrun"
DEFAULT_DECK_CONF_ID = 1
# High daily caps so the schema-weighted "Study now" queue can serve all 166
# items in priority order instead of Anki's stock 20 new/day.
HIGH_NEW_PER_DAY = 9999
HIGH_REV_PER_DAY = 9999
# Records the daily-limit values import last wrote, so a value the student later
# changed by hand is detected and never clobbered on a re-import.
_LIMIT_SENTINEL_KEY = "srSpeedrunDailyLimits"
SCHEMA_TAG = "sr:schema:"

# Friendly, human-readable display values for the card faces. The engine keys off
# the machine `sr:*` tags (see build_tags); these fields are display-only, so we
# store readable labels instead of raw ids like `flaw.causal`.
SECTION_LABELS = {
    "LR": "Logical Reasoning",
    "RC": "Reading Comprehension",
    "LG": "Logic Games",
}


def _section_label(section: str) -> str:
    return SECTION_LABELS.get(section, section)


def _qtype_label(stem_type: str) -> str:
    """`qt.weaken` -> `Weaken`, `necessary_assumption` -> `Necessary Assumption`."""
    if not stem_type:
        return ""
    raw = stem_type
    # Drop a leading axis token (e.g. `qt.`, `lg.`) so we show just the type.
    if "." in raw:
        raw = raw.split(".", 1)[1]
    return raw.replace("_", " ").replace(".", " ").strip().title()


def _schema_display(item: dict[str, Any]) -> str:
    primary = _primary_schema(item)
    return schema_label(primary) if primary else ""
QTYPE_TAG = "sr:qtype:"
TRAP_TAG = "sr:trap:"
SECTION_TAG = "sr:section:"
UNIT_TAG = "sr:unit:"
LESSON_TAG = "sr:lesson:"
ORDER_TAG = "sr:order:"

# Friendly, hierarchical Browse tags shown alongside the machine `sr:*` tags.
# Anki tags cannot contain spaces (it splits on them), so names are slugged with
# underscores. The engine ignores these; only tags starting with `sr:` are read.
FRIENDLY_ROOT = "LSAT"
FRIENDLY_AXIS_GROUP = {
    "flaw": "Flaws",
    "rc": "Reading",
    "qt": "Question_Types",
    "trap": "Traps",
    "lg": "Logic_Games",
}


def _slug(text: str) -> str:
    """`Too strong / extreme` -> `Too_strong_extreme` (space/punct-safe for tags)."""
    return re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_")


def _friendly_name(schema_id: str) -> str:
    """Specific taxonomy name without the axis prefix, e.g. `Causal reasoning`."""
    label = schema_label(schema_id)
    return label.split("·", 1)[1].strip() if "·" in label else label


def _friendly_schema_tag(schema_id: str) -> str:
    raw = normalize_schema_id(schema_id)
    axis = raw.split(".", 1)[0]
    group = FRIENDLY_AXIS_GROUP.get(axis, axis.title())
    return f"{FRIENDLY_ROOT}::{group}::{_slug(_friendly_name(raw))}"


def _friendly_tags(machine_tags: list[str]) -> list[str]:
    """Derive readable hierarchical tags from the machine `sr:*` tags."""
    out: list[str] = []
    for t in machine_tags:
        if t.startswith(SECTION_TAG):
            sec = _section_label(t[len(SECTION_TAG) :])
            if sec:
                out.append(f"{FRIENDLY_ROOT}::Section::{_slug(sec)}")
        elif t.startswith((SCHEMA_TAG, QTYPE_TAG, TRAP_TAG)):
            _, _, sid = t.partition(":")  # drop 'sr'
            _, _, sid = sid.partition(":")  # drop axis
            if sid:
                out.append(_friendly_schema_tag(sid))
    return out

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
    relabeled: int = 0
    limits_applied: bool = False


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
    # Course grouping (optional, additive): machine tags for the module, lesson,
    # and in-lesson order so the dashboard/queue can group per-module without any
    # scheduler change. Absent on unassigned items -> no unit tags emitted.
    unit = item.get("unit")
    if unit:
        tags.append(UNIT_TAG + str(unit))
        lesson = item.get("lesson")
        if lesson is not None:
            tags.append(LESSON_TAG + f"{unit}:{lesson}")
        order = item.get("order")
        if order is not None:
            tags.append(ORDER_TAG + str(order))
        tags.append(f"{FRIENDLY_ROOT}::Unit::{_slug(str(unit))}")
        if lesson is not None:
            tags.append(f"{FRIENDLY_ROOT}::Unit::{_slug(str(unit))}::L{lesson}")
    # Add friendly, hierarchical Browse tags alongside the machine tags.
    tags.extend(_friendly_tags(tags))
    # de-duplicate, preserve order
    seen = set()
    out = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _apply_perday_limit(bucket: dict, target: int, last: int | None) -> tuple[bool, int]:
    """Set ``bucket['perDay']`` to ``target`` unless the student changed it.

    ``last`` is the value import wrote previously (from the sentinel), or None if
    import has never set it. We treat a current value that differs from ``last``
    as a deliberate user change and leave it alone. Returns (changed, value_now).
    """
    current = bucket.get("perDay")
    if last is not None and current != last:
        # Student deliberately changed it since our last import -> respect it.
        return False, current
    if current == target:
        return False, current
    bucket["perDay"] = target
    return True, target


def ensure_deck_daily_limits(
    col,
    deck_id: int,
    *,
    new_per_day: int = HIGH_NEW_PER_DAY,
    rev_per_day: int = HIGH_REV_PER_DAY,
) -> bool:
    """Give the Speedrun deck its own options group with high daily limits.

    Scoped strictly to the Speedrun deck. If the deck still shares Anki's global
    ``Default`` config (id 1), we clone that config into a dedicated
    ``LSAT Speedrun`` group and reassign the deck, so the global config and every
    other deck are left untouched. Then we raise New cards/day and Maximum
    reviews/day so the schema-weighted queue isn't capped at 20.

    Idempotent (a second import is a no-op) and it won't clobber a value the
    student deliberately changed, detected via a sentinel recording the last
    value import wrote. Returns True if anything changed. Never raises out on a
    filtered/dynamic deck (it has no options group).
    """
    decks = col.decks
    deck = decks.get(deck_id, default=False)
    if not deck or deck.get("dyn"):
        return False

    changed = False
    conf_id = int(deck.get("conf", 0) or 0)
    if conf_id == 0 or conf_id == DEFAULT_DECK_CONF_ID:
        # Don't mutate the shared global Default: clone it into a dedicated group.
        base = decks.get_config(conf_id) if conf_id else None
        new_conf = decks.add_config(DECK_CONFIG_NAME, clone_from=base)
        decks.set_config_id_for_deck_dict(deck, new_conf["id"])
        conf_id = int(new_conf["id"])
        changed = True

    conf = decks.get_config(conf_id)
    if conf is None:
        return changed

    sentinel = dict(conf.get(_LIMIT_SENTINEL_KEY) or {})
    new_changed, new_now = _apply_perday_limit(
        conf.setdefault("new", {}), new_per_day, sentinel.get("new")
    )
    rev_changed, rev_now = _apply_perday_limit(
        conf.setdefault("rev", {}), rev_per_day, sentinel.get("rev")
    )
    updated_sentinel = {"new": new_now, "rev": rev_now}
    if new_changed or rev_changed or sentinel != updated_sentinel:
        conf[_LIMIT_SENTINEL_KEY] = updated_sentinel
        decks.update_config(conf)
        changed = changed or new_changed or rev_changed
    return changed


def populate_note(note, item: dict[str, Any]):
    """Fill a fresh note's display fields from a seed item.

    Shared by the seed importer and the big-deck generator so the field-mapping
    logic (friendly labels, the two-answer fork, paraphrases) lives in one place.
    Tags are handled separately via :func:`build_tags`.
    """
    note["ItemId"] = item["id"]
    note["Section"] = _section_label(item.get("section", ""))
    note["QuestionType"] = _qtype_label(item.get("stem_type", ""))
    note["Schema"] = _schema_display(item)
    note["Difficulty"] = str(item.get("difficulty", ""))
    note["Stimulus"] = item.get("stimulus") or item.get("passage", "")
    note["Question"] = item.get("question", "")
    note["Choices"] = _render_choices(item)
    fork = item.get("two_answer_fork", {})
    correct = next((c["id"] for c in item.get("choices", []) if c.get("correct")), "")
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
    return note


def import_seed_deck(
    col, deck_json: Path = DEFAULT_DECK_JSON, *, backup: bool = True
) -> ImportResult:
    backup_path = backup_collection(col) if backup else None
    data = json.loads(Path(deck_json).read_text(encoding="utf-8"))
    nt, created = ensure_notetype(col)
    deck_id = col.decks.id(DECK_NAME)
    limits_applied = ensure_deck_daily_limits(col, deck_id)

    added = 0
    skipped = 0
    relabeled = 0
    for item in data["items"]:
        item_id = item["id"]
        # idempotency: skip if an ItemId note already exists, but refresh its
        # display fields so decks imported before friendly labels get upgraded.
        existing = col.find_notes(f'"note:{NOTETYPE_NAME}" "ItemId:{item_id}"')
        if existing:
            skipped += 1
            if _relabel_note(col, existing[0], item):
                relabeled += 1
            continue
        note = col.new_note(nt)
        populate_note(note, item)
        col.add_note(note, deck_id)
        added += 1

    return ImportResult(
        added,
        skipped,
        created,
        deck_id,
        backup_path=str(backup_path) if backup_path else None,
        relabeled=relabeled,
        limits_applied=limits_applied,
    )


def ensure_friendly_tags(col) -> int:
    """Backfill friendly LSAT:: tags on notes that predate the friendly-tag feature.

    Older collections have only the machine ``sr:*`` tags. Because the editor hides
    those, such notes appear to have "N tags" but show no chips. This derives the
    friendly companions from each note's existing machine tags and adds the missing
    ones. Idempotent and cheap: the ``-tag:LSAT::*`` filter skips already-migrated
    notes, so re-running does nothing. Returns the number of notes updated.
    """
    try:
        todo = col.find_notes(f'"note:{NOTETYPE_NAME}" -tag:LSAT::*')
    except Exception:
        return 0
    changed = 0
    for nid in todo:
        note = col.get_note(nid)
        machine = [t for t in note.tags if t.startswith("sr:")]
        missing = [t for t in _friendly_tags(machine) if t not in note.tags]
        if missing:
            note.tags = list(note.tags) + missing
            col.update_note(note)
            changed += 1
    return changed


def _relabel_note(col, note_id: int, item: dict[str, Any]) -> bool:
    """Refresh display fields + add missing friendly tags. Returns True if changed."""
    note = col.get_note(note_id)
    updates = {
        "Section": _section_label(item.get("section", "")),
        "QuestionType": _qtype_label(item.get("stem_type", "")),
        "Schema": _schema_display(item),
    }
    changed = False
    for field, value in updates.items():
        if field in note and note[field] != value:
            note[field] = value
            changed = True
    # Add any missing friendly tags without disturbing existing tags.
    existing = set(note.tags)
    missing = [t for t in build_tags(item) if t not in existing]
    if missing:
        note.tags = note.tags + missing
        changed = True
    if changed:
        col.update_note(note)
    return changed


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
        f"skipped (already present), {result.relabeled} relabeled to friendly "
        f"names. Note type {'created' if result.notetype_created else 'reused'}."
    )
    print(
        f"Daily limits {'set' if result.limits_applied else 'already set'} on the "
        f"'{DECK_CONFIG_NAME}' options group "
        f"(new/day={HIGH_NEW_PER_DAY}, rev/day={HIGH_REV_PER_DAY}); "
        "global Default config untouched."
    )
    if result.backup_path:
        print(f"Backup: {result.backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
