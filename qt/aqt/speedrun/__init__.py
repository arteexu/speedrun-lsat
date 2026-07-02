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
from aqt.utils import (
    disable_help_button,
    ensureWidgetInScreenBoundaries,
    restoreGeom,
    saveGeom,
    showInfo,
    tooltip,
)

DECK_NAME = "LSAT Speedrun"
_score_action: QAction | None = None


def _ensure_speedrun_on_path() -> bool:
    """Make the `speedrun` package importable across dev *and* packaged layouts.

    Resolution order:
      1. Already importable (installed as a wheel, e.g. `pip install speedrun-lsat`
         on a clean machine) -> nothing to do.
      2. A copy bundled next to the `aqt` package (what the installer ships).
      3. The repo-root `speedrun/` (the dev layout, `./run`).
    """
    # 1. Installed / already on sys.path.
    try:
        import speedrun.scoring.memory  # noqa: F401

        return True
    except Exception:
        pass

    here = Path(__file__).resolve()
    candidates: list[Path] = [Path.cwd()]
    # 2. Bundled beside aqt: .../site-packages/speedrun (parent of the aqt pkg).
    #    here = .../aqt/speedrun/__init__.py -> parents[2] == site-packages root.
    if len(here.parents) > 2:
        candidates.append(here.parents[2])
    # 3. Dev layout: out/qt/_aqt/speedrun -> repo root.
    if len(here.parents) > 4:
        candidates.append(here.parents[4])
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

    contrast = QAction("Contrasting-pairs drill", mw)
    qconnect(contrast.triggered, lambda: _show_contrasting_drill(mw))
    menu.addAction(contrast)

    cold_open = QAction("Predict-the-schema cold-open", mw)
    qconnect(cold_open.triggered, lambda: _show_cold_open(mw))
    menu.addAction(cold_open)

    fork = QAction("Two-answer fork trainer", mw)
    qconnect(fork.triggered, lambda: _show_fork_trainer(mw))
    menu.addAction(fork)

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

    explain_problem = QAction("Explain this problem", mw)
    qconnect(explain_problem.triggered, lambda: _explain_problem(mw))
    menu.addAction(explain_problem)

    menu.addSeparator()

    from speedrun.dashboard import (
        render_calibration_html,
        render_concept_map_html,
        render_memory_report_html,
        render_mistake_graph_html,
        render_performance_report_html,
        render_readiness_report_html,
        render_transfer_gap_html,
    )
    from speedrun.confidence_calibration import render_confidence_calibration_html
    from speedrun.confusion import render_confusion_report_html
    from speedrun.explanations import render_explanations_report_html
    from speedrun.fading import render_mastery_ladder_html
    from speedrun.logic_diagram import render_logic_diagram_html
    from speedrun.rc_commentator import render_rc_commentator_html

    for label, fn in (
        ("Problem explanations", render_explanations_report_html),
        ("Mastery ladder (adaptive fading)", render_mastery_ladder_html),
        ("Confusion-pair interleaving", render_confusion_report_html),
        ("Confidence calibration", render_confidence_calibration_html),
        ("Concept map", render_concept_map_html),
        ("Mistake graph", render_mistake_graph_html),
        ("Conditional logic visualizer", render_logic_diagram_html),
        ("RC AI commentator", render_rc_commentator_html),
        ("Memory report", render_memory_report_html),
        ("Performance report", render_performance_report_html),
        ("Readiness report", render_readiness_report_html),
        ("Transfer gap report", render_transfer_gap_html),
        ("Calibration report", render_calibration_html),
    ):
        act = QAction(label, mw)
        qconnect(
            act.triggered,
            lambda _checked=False, _fn=fn, _t=label: _show_report(mw, _fn, _t),
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


_GEOM_KEY = "speedrunHtml"


def _profile_has_saved_geom(key: str) -> bool:
    import aqt
    from aqt.utils import _qt_state_key, _QtStateKeyKind

    assert aqt.mw.pm.profile is not None
    geom_key = _qt_state_key(_QtStateKeyKind.GEOMETRY, key)
    return bool(aqt.mw.pm.profile.get(geom_key))


def _center_dialog_on_primary_screen(diag, minWidth: int, minHeight: int) -> None:
    from aqt.qt import QApplication
    from speedrun.dialog_geometry import centered_in_available_geometry

    screen = QApplication.primaryScreen()
    if screen is None:
        diag.resize(minWidth, minHeight)
        return
    geom = screen.availableGeometry()
    x, y, width, height = centered_in_available_geometry(
        geom.x(),
        geom.y(),
        geom.width(),
        geom.height(),
        minWidth,
        minHeight,
    )
    diag.setGeometry(x, y, width, height)


class SpeedrunHtmlDialog:
    """Non-modal HTML dialog using QWebEngineView (Anki stats/emptycards pattern)."""

    def __init__(
        self,
        mw,
        html: str,
        *,
        title: str,
        minWidth: int,
        minHeight: int,
        bridge=None,
    ) -> None:
        from aqt.qt import (
            QDialog,
            QDialogButtonBox,
            Qt,
            QUrl,
            QVBoxLayout,
            QWebEngineView,
        )

        class _Dialog(QDialog):
            silentlyClose = True

            def closeWithCallback(self, callback) -> None:
                self.reject()
                callback()

        self.mw = mw
        self._dialog = _Dialog(mw, Qt.WindowType.Window)
        diag = self._dialog
        diag.setWindowTitle(title)
        diag.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        disable_help_button(diag)
        mw.garbage_collect_on_dialog_finish(diag)

        layout = QVBoxLayout(diag)
        if bridge is not None:
            # An interactive page needs the pycmd bridge, which only AnkiWebView
            # provides; `html` here is body-only markup (embed=True).
            from aqt.webview import AnkiWebView

            self._web = AnkiWebView(diag)
            self._web.set_bridge_command(bridge, self)
            self._web.stdHtml(html, context=self)
        else:
            self._web = QWebEngineView(diag)
            self._web.setHtml(html, QUrl("about:blank"))
        layout.addWidget(self._web)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        layout.addWidget(box)
        qconnect(box.rejected, diag.reject)
        qconnect(box.accepted, diag.accept)

        diag.setMinimumWidth(minWidth)
        diag.setMinimumHeight(minHeight)
        restoreGeom(diag, _GEOM_KEY, default_size=(minWidth, minHeight))
        if not _profile_has_saved_geom(_GEOM_KEY):
            _center_dialog_on_primary_screen(diag, minWidth, minHeight)

        qconnect(diag.finished, self._on_finished)

    def _on_finished(self) -> None:
        if self._web is not None:
            cleanup = getattr(self._web, "cleanup", None)
            if callable(cleanup):
                cleanup()
            else:
                self._web.setHtml("")
            self._web.deleteLater()
            self._web = None
        saveGeom(self._dialog, _GEOM_KEY)

    def show(self) -> None:
        self._dialog.show()
        ensureWidgetInScreenBoundaries(self._dialog)
        self._dialog.activateWindow()
        self._dialog.raise_()

    def close(self) -> None:
        self._dialog.close()


def _show_html(
    mw,
    html: str,
    *,
    title: str = "LSAT Speedrun",
    minWidth: int = 720,
    minHeight: int = 640,
    bridge=None,
) -> None:
    """Show self-contained HTML in a dialog using QWebEngineView.

    Anki's showText(type=\"html\") uses QTextBrowser, which strips <style> tags
    and ignores most CSS — the Speedrun dashboard relies on a <style> block.

    When ``bridge`` is provided the dialog uses an AnkiWebView so the page can
    post results back via ``pycmd`` (``html`` must then be body-only markup).
    """
    existing = getattr(mw, "_speedrun_html_dialog", None)
    if existing is not None:
        existing.close()

    dialog = SpeedrunHtmlDialog(
        mw,
        html,
        title=title,
        minWidth=minWidth,
        minHeight=minHeight,
        bridge=bridge,
    )
    mw._speedrun_html_dialog = dialog

    def on_finished(_code: int) -> None:
        if getattr(mw, "_speedrun_html_dialog", None) is dialog:
            mw._speedrun_html_dialog = None

    qconnect(dialog._dialog.finished, on_finished)
    dialog.show()


def _show_report(mw, renderer, title: str) -> None:
    if not _require_col(mw):
        return
    try:
        html = renderer(mw.col)
    except Exception as exc:  # pragma: no cover
        tooltip(f"{title} error: {exc}")
        return
    _show_html(
        mw,
        html,
        title=f"LSAT Speedrun — {title}",
        minWidth=720,
        minHeight=640,
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
    _show_html(
        mw,
        html,
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
    _show_html(
        mw,
        html,
        title="LSAT Speedrun — Study queue",
        minWidth=620,
        minHeight=520,
    )


def _show_drill(mw) -> None:
    if not _require_col(mw):
        return
    try:
        from speedrun.taxonomy.labels import schema_display_html
        from speedrun.tools.schema_drill import schema_drill_queue

        schemas, cards = schema_drill_queue(mw.col)
        schema_labels = ", ".join(schema_display_html(s, compact=True) for s in schemas)
        rows = "".join(
            f"<tr><td>{schema_display_html(c.schema)}</td><td align='right'>{c.priority:.3f}</td></tr>"
            for c in cards[:20]
        )
        html = (
            "<div style='font-family:system-ui,sans-serif'>"
            f"<h3>Weakest schemas: {schema_labels}</h3>"
            f"<table width='100%' cellpadding='4'>{rows}</table></div>"
        )
    except Exception as exc:  # pragma: no cover
        tooltip(f"Drill error: {exc}")
        return
    _show_html(mw, html, title="Schema drill", minWidth=560, minHeight=480)


def _contrast_logger(mw):
    """One SessionLogger per app run for contrasting-pairs self-ratings."""
    logger = getattr(mw, "_speedrun_contrast_logger", None)
    if logger is None:
        from speedrun.session_logger import SessionLogger

        logger = SessionLogger()
        mw._speedrun_contrast_logger = logger
    return logger


def _show_contrasting_drill(mw) -> None:
    if not _require_col(mw):
        return
    try:
        from speedrun.contrasting import (
            build_contrasting_pairs,
            render_contrasting_drill_html,
        )

        cset = build_contrasting_pairs(mw.col)
        html = render_contrasting_drill_html(cset, embed=True)
    except Exception as exc:  # pragma: no cover - defensive
        tooltip(f"Contrasting drill error: {exc}")
        return

    def bridge(cmd: str):
        if cmd == "close":
            dialog = getattr(mw, "_speedrun_html_dialog", None)
            if dialog is not None:
                dialog.close()
            return
        prefix = "speedrun:contrast:"
        if cmd.startswith(prefix):
            import json

            from speedrun.contrasting import record_contrast_result

            try:
                payload = json.loads(cmd[len(prefix) :])
                record_contrast_result(_contrast_logger(mw), payload)
            except Exception:  # pragma: no cover - never break the drill on logging
                pass
        return

    _show_html(
        mw,
        html,
        title="LSAT Speedrun — Contrasting pairs",
        minWidth=780,
        minHeight=680,
        bridge=bridge,
    )


def _drill_logger(mw):
    """One SessionLogger per app run for drill diagnostic results (cold-open, fork)."""
    logger = getattr(mw, "_speedrun_drill_logger", None)
    if logger is None:
        from speedrun.session_logger import SessionLogger

        logger = SessionLogger()
        mw._speedrun_drill_logger = logger
    return logger


def _show_cold_open(mw) -> None:
    if not _require_col(mw):
        return
    try:
        from speedrun.cold_open import build_cold_open_set, render_cold_open_html

        cset = build_cold_open_set(mw.col)
        html = render_cold_open_html(cset, embed=True)
    except Exception as exc:  # pragma: no cover - defensive
        tooltip(f"Cold-open error: {exc}")
        return

    def bridge(cmd: str):
        if cmd == "close":
            dialog = getattr(mw, "_speedrun_html_dialog", None)
            if dialog is not None:
                dialog.close()
            return
        prefix = "speedrun:cold_open:"
        if cmd.startswith(prefix):
            import json

            from speedrun.cold_open import record_cold_open_result

            try:
                payload = json.loads(cmd[len(prefix) :])
                record_cold_open_result(_drill_logger(mw), payload)
            except Exception:  # pragma: no cover - never break the drill on logging
                pass
        return

    _show_html(
        mw,
        html,
        title="LSAT Speedrun — Cold-open",
        minWidth=760,
        minHeight=660,
        bridge=bridge,
    )


def _show_fork_trainer(mw) -> None:
    if not _require_col(mw):
        return
    try:
        from speedrun.fork_trainer import build_fork_set, render_fork_trainer_html

        fset = build_fork_set(mw.col)
        html = render_fork_trainer_html(fset, embed=True)
    except Exception as exc:  # pragma: no cover - defensive
        tooltip(f"Fork trainer error: {exc}")
        return

    def bridge(cmd: str):
        if cmd == "close":
            dialog = getattr(mw, "_speedrun_html_dialog", None)
            if dialog is not None:
                dialog.close()
            return
        prefix = "speedrun:fork:"
        if cmd.startswith(prefix):
            import json

            from speedrun.fork_trainer import record_fork_result

            try:
                payload = json.loads(cmd[len(prefix) :])
                record_fork_result(_drill_logger(mw), payload)
            except Exception:  # pragma: no cover - never break the drill on logging
                pass
        return

    _show_html(
        mw,
        html,
        title="LSAT Speedrun — Two-answer fork",
        minWidth=780,
        minHeight=680,
        bridge=bridge,
    )


def _export_report(mw) -> None:
    if not _require_col(mw):
        return
    try:
        from speedrun.export import render_full_export_html

        html = render_full_export_html(mw.col)
    except Exception as exc:  # pragma: no cover
        tooltip(f"Export error: {exc}")
        return
    _show_html(
        mw,
        html,
        title="LSAT Speedrun — Export",
        minWidth=800,
        minHeight=720,
    )


def _show_config(mw) -> None:
    _ensure_speedrun_on_path()
    try:
        from speedrun.dashboard import render_config_editor_html

        html = render_config_editor_html()
    except Exception as exc:  # pragma: no cover
        tooltip(f"Config error: {exc}")
        return
    _show_html(mw, html, title="Speedrun settings", minWidth=520, minHeight=480)


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
    _show_html(mw, html, title="Speedrun health check", minWidth=480, minHeight=320)


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
        from speedrun.taxonomy.labels import schema_display_html, schema_label

        schema = _schema_from_card(reviewer.card)
        if not schema:
            tooltip("No schema on this card.")
            return
        text = explain_schema(schema)
        _show_html(
            mw,
            f"<div style='font-family:system-ui,sans-serif'>"
            f"{schema_display_html(schema)}<p>{text}</p></div>",
            title=schema_label(schema),
            minWidth=420,
            minHeight=200,
        )
    except Exception as exc:  # pragma: no cover
        tooltip(str(exc))


def _explain_problem(mw) -> None:
    if not _require_col(mw):
        return
    reviewer = mw.reviewer
    if reviewer is None or reviewer.card is None:
        tooltip("Open the reviewer first, then explain the current problem.")
        return
    try:
        from speedrun.explanations import (
            explain_item_by_id,
            items_by_id,
            load_items,
            render_problem_explanation_html,
        )

        note = reviewer.card.note()
        try:
            item_id = (note["ItemId"] or "").strip()
        except Exception:
            item_id = ""

        if not item_id or explain_item_by_id(item_id) is None:
            tooltip("No explanation available for this card (not a seed problem).")
            return

        items = load_items()
        item = items_by_id(items).get(item_id)
        html = render_problem_explanation_html(item, items=items)
        _show_html(
            mw,
            html,
            title="LSAT Speedrun — Why this answer",
            minWidth=640,
            minHeight=560,
        )
    except Exception as exc:  # pragma: no cover
        tooltip(f"Explain problem error: {exc}")


def _import_seed(mw) -> None:
    if not _require_col(mw):
        return
    try:
        from speedrun.tools import import_seed_deck as importer

        # Always run: it is idempotent (skips existing notes) and also refreshes
        # display fields, so re-running upgrades older decks to friendly labels.
        result = importer.import_seed_deck(mw.col)
    except Exception as exc:  # pragma: no cover - defensive
        tooltip(f"Import error: {exc}")
        return
    mw.reset()
    if result.added == 0 and result.relabeled == 0:
        msg = (
            f"LSAT Speedrun seed deck already present and up to date "
            f"({importer.SEED_ITEM_COUNT} notes)."
        )
    else:
        parts = []
        if result.added:
            parts.append(f"{result.added} card(s) imported")
        if result.skipped:
            parts.append(f"{result.skipped} already present")
        if result.relabeled:
            parts.append(f"{result.relabeled} relabeled to friendly names")
        msg = "LSAT Speedrun: " + ", ".join(parts) + "."
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
