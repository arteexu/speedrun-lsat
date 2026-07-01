# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""In-app entry points for Speedrun LSAT (menu + dashboard dialogs).

This is a thin Qt shim. All non-Qt logic (scoring, ordering, HTML rendering)
lives in the repo-root `speedrun` package so it stays testable without Qt. The
menu setup is called from a single guarded line in main.py's setupMenus, so any
failure here degrades gracefully and never blocks Anki startup.
"""

from __future__ import annotations

import sys
from pathlib import Path

from aqt.qt import QAction, QMenu, qconnect
from aqt.utils import showText, tooltip


def _ensure_speedrun_on_path() -> bool:
    """Make the repo-root `speedrun` package importable in the dev layout."""
    here = Path(__file__).resolve()
    candidates = [Path.cwd()]
    if len(here.parents) > 4:
        candidates.append(here.parents[4])  # out/qt/_aqt/speedrun -> repo root
    for cand in candidates:
        if (cand / "speedrun" / "scoring" / "memory.py").exists():
            if str(cand) not in sys.path:
                sys.path.insert(0, str(cand))
            return True
    return False


def setup_menu(mw) -> None:
    _ensure_speedrun_on_path()
    menu = QMenu("LSAT Speedrun", mw)
    mw.form.menuTools.addMenu(menu)

    dashboard = QAction("Dashboard (three scores)", mw)
    qconnect(dashboard.triggered, lambda: _show_dashboard(mw))
    menu.addAction(dashboard)

    queue = QAction("Schema-weighted queue", mw)
    qconnect(queue.triggered, lambda: _show_queue(mw))
    menu.addAction(queue)

    menu.addSeparator()

    do_import = QAction("Import seed deck", mw)
    qconnect(do_import.triggered, lambda: _import_seed(mw))
    menu.addAction(do_import)


def _require_col(mw) -> bool:
    if not mw.col:
        tooltip("Open a profile first.")
        return False
    if not _ensure_speedrun_on_path():
        tooltip("Speedrun package not found on disk.")
        return False
    return True


def _show_dashboard(mw) -> None:
    if not _require_col(mw):
        return
    try:
        from speedrun.dashboard import render_dashboard_html

        html = render_dashboard_html(mw.col)
    except Exception as exc:  # pragma: no cover - defensive
        tooltip(f"Dashboard error: {exc}")
        return
    showText(
        html,
        type="html",
        title="LSAT Speedrun — Scores",
        minWidth=680,
        minHeight=620,
    )


def _show_queue(mw) -> None:
    if not _require_col(mw):
        return
    try:
        from speedrun.dashboard import render_study_list_html

        html = render_study_list_html(mw.col, limit=25)
    except Exception as exc:  # pragma: no cover - defensive
        tooltip(f"Queue error: {exc}")
        return
    showText(
        html,
        type="html",
        title="LSAT Speedrun — Schema-weighted queue",
        minWidth=620,
        minHeight=520,
    )


def _import_seed(mw) -> None:
    if not _require_col(mw):
        return
    try:
        from speedrun.tools.import_seed_deck import import_seed_deck

        result = import_seed_deck(mw.col)
    except Exception as exc:  # pragma: no cover - defensive
        tooltip(f"Import error: {exc}")
        return
    mw.reset()
    tooltip(
        f"LSAT Speedrun: {result.added} card(s) imported, "
        f"{result.skipped} already present."
    )
