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

from aqt import gui_hooks
from aqt.qt import QAction, QKeySequence, QMenu, QShortcut, qconnect
from aqt.utils import showInfo, showText, tooltip

DECK_NAME = "LSAT Speedrun"
_score_action: QAction | None = None


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


def _refresh_score_badge(mw) -> None:
    global _score_action
    if _score_action is None or not mw.col:
        return
    try:
        from speedrun.dashboard import dashboard_summary

        s = dashboard_summary(mw.col)
        _score_action.setText(
            f"M {s['memory']} · P {s['performance']} · R {s['readiness']}"
        )
    except Exception:
        _score_action.setText("Scores: —")


def setup_menu(mw) -> None:
    global _score_action
    _ensure_speedrun_on_path()
    menu = QMenu("LSAT Speedrun", mw)
    mw.form.menuTools.addMenu(menu)

    dashboard = QAction("Dashboard", mw)
    dashboard.setShortcut(QKeySequence("Ctrl+Shift+L"))
    qconnect(dashboard.triggered, lambda: _show_dashboard(mw))
    menu.addAction(dashboard)

    study = QAction("Study now", mw)
    qconnect(study.triggered, lambda: _start_study(mw))
    menu.addAction(study)

    queue = QAction("Schema-weighted queue", mw)
    qconnect(queue.triggered, lambda: _show_queue(mw))
    menu.addAction(queue)

    drill = QAction("Schema drill (weakest)", mw)
    qconnect(drill.triggered, lambda: _show_drill(mw))
    menu.addAction(drill)

    export = QAction("Export offline report", mw)
    qconnect(export.triggered, lambda: _export_report(mw))
    menu.addAction(export)

    config = QAction("Settings", mw)
    qconnect(config.triggered, lambda: _show_config(mw))
    menu.addAction(config)

    sidebar = QAction("Show reviewer sidebar", mw)
    qconnect(sidebar.triggered, lambda: _toggle_sidebar(mw))
    menu.addAction(sidebar)

    explain = QAction("Explain this schema", mw)
    qconnect(explain.triggered, lambda: _explain_schema(mw))
    menu.addAction(explain)

    menu.addSeparator()

    from speedrun.dashboard import (
        render_calibration_html,
        render_memory_report_html,
        render_performance_report_html,
        render_readiness_report_html,
        render_transfer_gap_html,
    )

    for label, fn in (
        ("Memory report", render_memory_report_html),
        ("Performance report", render_performance_report_html),
        ("Readiness report", render_readiness_report_html),
        ("Transfer gap report", render_transfer_gap_html),
        ("Calibration report", render_calibration_html),
    ):
        act = QAction(label, mw)
        qconnect(
            act.triggered, lambda _mw=mw, _fn=fn, _t=label: _show_report(_mw, _fn, _t)
        )
        menu.addAction(act)

    menu.addSeparator()

    ai_action = QAction("AI: OFF (default)", mw)
    ai_action.setEnabled(False)
    try:
        from speedrun.ai.config import ai_enabled

        ai_action.setText(f"AI: {'ON' if ai_enabled() else 'OFF (default)'}")
    except Exception:
        pass
    menu.addAction(ai_action)

    _score_action = QAction("Scores: —", mw)
    _score_action.setEnabled(False)
    menu.addAction(_score_action)

    menu.addSeparator()

    do_import = QAction("Import seed deck", mw)
    qconnect(do_import.triggered, lambda: _import_seed(mw))
    menu.addAction(do_import)

    health = QAction("Health check", mw)
    qconnect(health.triggered, lambda: _health_check(mw))
    menu.addAction(health)

    reminder = QAction("Daily study goal (stub)", mw)
    qconnect(
        reminder.triggered,
        lambda: tooltip(
            "OS notifications not wired yet. Track progress on the dashboard daily goal card."
        ),
    )
    menu.addAction(reminder)

    sc = QShortcut(QKeySequence("Ctrl+Shift+L"), mw)
    qconnect(sc.activated, lambda: _show_dashboard(mw))

    gui_hooks.collection_did_load.append(lambda _col: _refresh_score_badge(mw))
    gui_hooks.state_did_change.append(
        lambda state, _old: _refresh_score_badge(mw) if state == "overview" else None
    )
    _refresh_score_badge(mw)


def _require_col(mw) -> bool:
    if not mw.col:
        tooltip("Open a profile first.")
        return False
    if not _ensure_speedrun_on_path():
        tooltip("Speedrun package not found on disk.")
        return False
    return True


def _show_report(mw, renderer, title: str) -> None:
    if not _require_col(mw):
        return
    try:
        html = renderer(mw.col)
    except Exception as exc:  # pragma: no cover
        tooltip(f"{title} error: {exc}")
        return
    showText(
        html, type="html", title=f"LSAT Speedrun — {title}", minWidth=720, minHeight=640
    )


def _start_study(mw) -> None:
    if not _require_col(mw):
        return
    try:
        deck_id = mw.col.decks.id(DECK_NAME)
        mw.col.decks.select(deck_id)
        mw.col.startTimebox()
        mw.moveToState("review")
    except Exception as exc:  # pragma: no cover
        tooltip(f"Study error: {exc}")


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
        title="LSAT Speedrun — Dashboard",
        minWidth=820,
        minHeight=720,
    )
    _refresh_score_badge(mw)


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
        title="LSAT Speedrun — Study queue",
        minWidth=620,
        minHeight=520,
    )


def _show_drill(mw) -> None:
    if not _require_col(mw):
        return
    try:
        from speedrun.tools.schema_drill import schema_drill_queue

        schemas, cards = schema_drill_queue(mw.col)
        rows = "".join(
            f"<tr><td>{c.schema}</td><td align='right'>{c.priority:.3f}</td></tr>"
            for c in cards[:20]
        )
        html = (
            "<div style='font-family:system-ui,sans-serif'>"
            f"<h3>Weakest schemas: {', '.join(schemas)}</h3>"
            f"<table width='100%' cellpadding='4'>{rows}</table></div>"
        )
    except Exception as exc:  # pragma: no cover
        tooltip(f"Drill error: {exc}")
        return
    showText(html, type="html", title="Schema drill", minWidth=560, minHeight=480)


def _export_report(mw) -> None:
    if not _require_col(mw):
        return
    try:
        from speedrun.export import render_full_export_html

        html = render_full_export_html(mw.col)
    except Exception as exc:  # pragma: no cover
        tooltip(f"Export error: {exc}")
        return
    showText(
        html, type="html", title="LSAT Speedrun — Export", minWidth=800, minHeight=720
    )


def _show_config(mw) -> None:
    _ensure_speedrun_on_path()
    try:
        from speedrun.dashboard import render_config_editor_html

        html = render_config_editor_html()
    except Exception as exc:  # pragma: no cover
        tooltip(f"Config error: {exc}")
        return
    showText(html, type="html", title="Speedrun settings", minWidth=520, minHeight=480)


def _toggle_sidebar(mw) -> None:
    try:
        from aqt.speedrun.reviewer import install_sidebar

        install_sidebar(mw)
        tooltip("Speedrun sidebar enabled.")
    except Exception as exc:  # pragma: no cover
        tooltip(f"Sidebar error: {exc}")


def _health_check(mw) -> None:
    if not _require_col(mw):
        return
    try:
        from speedrun.tools.health_check import run_checks

        results = run_checks(mw.col)
        lines = "<br>".join(
            f"{'✓' if ok else '✗'} {name}: {detail}" for name, ok, detail in results
        )
        html = f"<div style='font-family:system-ui,sans-serif'>{lines}</div>"
    except Exception as exc:  # pragma: no cover
        tooltip(f"Health check error: {exc}")
        return
    showText(
        html, type="html", title="Speedrun health check", minWidth=480, minHeight=320
    )


def _explain_schema(mw) -> None:
    if not _require_col(mw):
        return
    reviewer = mw.reviewer
    if reviewer is None or reviewer.card is None:
        tooltip("Open the reviewer first.")
        return
    try:
        from aqt.speedrun.reviewer import _schema_from_card
        from speedrun.insights import explain_schema

        schema = _schema_from_card(reviewer.card)
        if not schema:
            tooltip("No schema on this card.")
            return
        text = explain_schema(schema)
        showText(
            f"<div style='font-family:system-ui,sans-serif'><b>{schema}</b><p>{text}</p></div>",
            type="html",
            title="Explain this schema",
            minWidth=420,
            minHeight=200,
        )
    except Exception as exc:  # pragma: no cover
        tooltip(str(exc))


def _import_seed(mw) -> None:
    if not _require_col(mw):
        return
    try:
        from speedrun.tools import import_seed_deck as importer

        if importer.is_seed_deck_imported(mw.col):
            showInfo(
                "The LSAT Speedrun seed deck is already imported "
                f"({importer.SEED_ITEM_COUNT} notes).",
                title="Already imported",
            )
            return

        result = importer.import_seed_deck(mw.col)
    except Exception as exc:  # pragma: no cover - defensive
        tooltip(f"Import error: {exc}")
        return
    mw.reset()
    msg = (
        f"LSAT Speedrun: {result.added} card(s) imported, "
        f"{result.skipped} already present."
    )
    if result.backup_path:
        msg += f" Backup: {result.backup_path}"
    tooltip(msg)
    _refresh_score_badge(mw)


def setup_reviewer_hooks(reviewer) -> None:
    """Called when reviewer opens — attach post-review toast + sidebar updates."""
    try:
        from aqt.speedrun.reviewer import hook_reviewer

        hook_reviewer(reviewer)
    except Exception:
        pass
