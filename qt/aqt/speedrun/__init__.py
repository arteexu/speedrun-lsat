# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""In-app entry points for Speedrun LSAT (menu + dashboard dialogs).

This is a thin Qt shim. All non-Qt logic (scoring, ordering, HTML rendering)
lives in the repo-root `speedrun` package so it stays testable without Qt. The
menu setup is called from a single guarded line in main.py's setupMenus, so any
failure here degrades gracefully and never blocks Anki startup.
"""

from __future__ import annotations

import os
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
_ai_status_action: QAction | None = None


def _point_ai_settings_at_profile(mw) -> None:
    """Store AI settings inside the active profile's (device-local, git-ignored)
    base dir, so the app and any headless code in this process agree on the file.

    Respects an existing ``SPEEDRUN_AI_SETTINGS_PATH`` (tests/power users) and
    never overwrites it. The API key is written here, never to the collection.
    """
    if os.environ.get("SPEEDRUN_AI_SETTINGS_PATH"):
        return
    try:
        base = getattr(mw.pm, "base", None)
        if base:
            os.environ["SPEEDRUN_AI_SETTINGS_PATH"] = str(
                Path(base) / "speedrun_ai_settings.json"
            )
    except Exception:
        pass


def _refresh_ai_status(mw=None) -> None:
    global _ai_status_action
    if _ai_status_action is None:
        return
    try:
        from speedrun.ai.config import ai_enabled

        _ai_status_action.setText(f"AI: {'ON' if ai_enabled() else 'OFF (default)'}")
    except Exception:
        _ai_status_action.setText("AI: OFF (default)")


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


# The engine keys off machine tags (sr:schema:, sr:trap:, ...). They must stay in
# the collection, but users shouldn't see raw ids in the editor. Each tag chip
# carries its full name in data-addon-tag, so we hide the internal ones with CSS
# and leave the friendly LSAT:: tags visible. We also correct the editor's
# "Tags (N)" count so it matches the *visible* (friendly) chips rather than the
# raw total. Covers the reviewer Edit dialog and the Browse editor.
_HIDE_INTERNAL_TAGS_JS = r"""
(function () {
  var id = 'speedrun-hide-internal-tags';
  if (!document.getElementById(id)) {
    var s = document.createElement('style');
    s.id = id;
    s.textContent = '.tag[data-addon-tag^="sr:"]{display:none !important;}';
    (document.head || document.documentElement).appendChild(s);
  }
  function friendlyCount() {
    var n = 0;
    document.querySelectorAll('.tag[data-addon-tag]').forEach(function (c) {
      var t = c.getAttribute('data-addon-tag') || '';
      if (t && t.indexOf('sr:') !== 0) n++;
    });
    return n;
  }
  function fixCountLabel() {
    var labels = document.querySelectorAll('.collapse-label');
    if (!labels.length) return;
    var label = labels[labels.length - 1];  // the tags header is the last one
    var n = friendlyCount();
    var txt = n === 0 ? 'Tags' : (n === 1 ? '1 tag' : n + ' tags');
    var badge = label.firstElementChild;  // keep the collapse chevron
    var cur = '';
    label.childNodes.forEach(function (node) {
      if (node !== badge) cur += node.textContent || '';
    });
    if (cur.trim() === txt) return;  // already correct -> avoid observer loops
    Array.prototype.slice.call(label.childNodes).forEach(function (node) {
      if (node !== badge) label.removeChild(node);
    });
    label.appendChild(document.createTextNode(' ' + txt));
  }
  fixCountLabel();
  try {
    if (!window.__srTagObserver) {
      var host = document.querySelector('.tag-editor') || document.body;
      window.__srTagObserver = new MutationObserver(function () {
        if (window.__srTagT) return;
        window.__srTagT = setTimeout(function () {
          window.__srTagT = null;
          fixCountLabel();
        }, 60);
      });
      window.__srTagObserver.observe(host, { childList: true, subtree: true });
    }
  } catch (e) {}
})();
"""


def _hide_internal_editor_tags(editor) -> None:
    """Hide machine (sr:*) tag chips in the note editor and fix the tag count."""
    try:
        editor.web.eval(_HIDE_INTERNAL_TAGS_JS)
    except Exception:
        pass


def _backfill_friendly_tags(col) -> None:
    """Ensure existing notes have friendly LSAT:: tags so the editor shows chips.

    Older collections carry only machine sr:* tags (hidden in the editor), which
    made notes look like they had tags that never appeared. Runs once per load;
    the query skips already-migrated notes so it is a no-op afterwards."""
    if not _ensure_speedrun_on_path():
        return
    try:
        from speedrun.tools.import_seed_deck import ensure_friendly_tags

        ensure_friendly_tags(col)
    except Exception:
        pass


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
    _point_ai_settings_at_profile(mw)
    menu = QMenu("LSAT Speedrun", mw)
    mw.form.menuTools.addMenu(menu)

    dashboard = QAction("Dashboard", mw)
    dashboard.setShortcut(QKeySequence("Ctrl+Shift+L"))
    qconnect(dashboard.triggered, lambda: _show_dashboard(mw))
    menu.addAction(dashboard)

    study = QAction("Study now", mw)
    qconnect(study.triggered, lambda: _start_study(mw))
    menu.addAction(study)

    study_all = QAction("Study all (uncapped)", mw)
    qconnect(study_all.triggered, lambda: _start_study_all(mw))
    menu.addAction(study_all)

    queue = QAction("Schema-weighted queue", mw)
    qconnect(queue.triggered, lambda: _show_queue(mw))
    menu.addAction(queue)

    drill = QAction("Schema drill (weakest)", mw)
    qconnect(drill.triggered, lambda: _show_drill(mw))
    menu.addAction(drill)

    focus = QAction("Focus / study by subject", mw)
    qconnect(focus.triggered, lambda: _show_focus(mw))
    menu.addAction(focus)

    contrast = QAction("Contrasting-pairs drill", mw)
    qconnect(contrast.triggered, lambda: _show_contrasting_drill(mw))
    menu.addAction(contrast)

    cold_open = QAction("Predict-the-schema cold-open", mw)
    qconnect(cold_open.triggered, lambda: _show_cold_open(mw))
    menu.addAction(cold_open)

    fork = QAction("Two-answer fork trainer", mw)
    qconnect(fork.triggered, lambda: _show_fork_trainer(mw))
    menu.addAction(fork)

    study_next = QAction("What to study next (AI)", mw)
    qconnect(study_next.triggered, lambda: _show_recommender(mw))
    menu.addAction(study_next)

    tutor = QAction("AI Tutor (ask about a problem)", mw)
    qconnect(tutor.triggered, lambda: _show_tutor(mw))
    menu.addAction(tutor)

    ai_settings = QAction("AI Settings…", mw)
    qconnect(ai_settings.triggered, lambda: _show_ai_settings(mw))
    menu.addAction(ai_settings)

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

    global _ai_status_action
    _ai_status_action = QAction("AI: OFF (default)", mw)
    _ai_status_action.setEnabled(False)
    menu.addAction(_ai_status_action)
    _refresh_ai_status(mw)

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

    gui_hooks.collection_did_load.append(lambda col: _backfill_friendly_tags(col))
    gui_hooks.collection_did_load.append(lambda _col: _refresh_score_badge(mw))
    gui_hooks.state_did_change.append(
        lambda state, _old: _refresh_score_badge(mw) if state == "overview" else None
    )
    gui_hooks.editor_did_load_note.append(_hide_internal_editor_tags)
    if mw.col is not None:
        _backfill_friendly_tags(mw.col)
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
    """Review session launcher: show the grounded pre-set briefing first, then
    enter the reviewer on "Start set"."""
    if not _require_col(mw):
        return
    _show_preset_briefing(
        mw,
        set_kind="review",
        proceed=lambda: _launch_review(mw),
        title="LSAT Speedrun — Before you start: Review",
    )


def _launch_review(mw) -> None:
    """Enter the Speedrun-native review flow (schema-weighted priority order).

    §9/§11 blocker fix: native Anki filtered decks can't reproduce an arbitrary
    priority order, so the old path (moveToState("review")) graded cards in native
    scheduler order and never applied the schema-weighted queue. We now grade the
    `SchemaWeightedReview` queue (Rust-ordered, graded via col.sched.answerCard),
    mirroring the iOS ReviewView. On any failure we fall back to the native review
    state so studying is never blocked."""
    if not _launch_schema_weighted_review(mw, title="LSAT Speedrun — Schema-weighted review"):
        try:
            deck_id = mw.col.decks.id(DECK_NAME)
            mw.col.decks.select(deck_id)
            mw.col.startTimebox()
            mw.moveToState("review")
        except Exception as exc:  # pragma: no cover
            tooltip(f"Study error: {exc}")


def _review_bridge(mw):
    """pycmd bridge for the Speedrun-native review surface. Grades/undoes go
    straight to the stored `SchemaWeightedReview` session (the shared engine)."""

    def bridge(cmd: str):
        if cmd == "close":
            dialog = getattr(mw, "_speedrun_html_dialog", None)
            if dialog is not None:
                dialog.close()
            return True
        session = getattr(mw, "_speedrun_review_session", None)
        grade_prefix = "speedrun:review:grade:"
        if cmd.startswith(grade_prefix):
            import json

            if session is None:
                return {"ok": False}
            try:
                payload = json.loads(cmd[len(grade_prefix) :])
                session.answer_card_id(
                    int(payload["card_id"]),
                    int(payload["ease"]),
                    latency_ms=payload.get("latency_ms"),
                )
                _refresh_score_badge(mw)
                return {"ok": True}
            except Exception:  # pragma: no cover - never lose the session on one bad grade
                return {"ok": False}
        if cmd == "speedrun:review:undo":
            if session is None:
                return {"ok": False}
            try:
                ok = session.undo()
                _refresh_score_badge(mw)
                return {"ok": bool(ok)}
            except Exception:  # pragma: no cover
                return {"ok": False}
        return

    return bridge


def _launch_schema_weighted_review(
    mw, *, schemas: list | None = None, limit: int = 50, title: str
) -> bool:
    """Build and show the Speedrun-native, schema-weighted review dialog.

    Returns True if the dialog was shown (even if empty), False on any failure so
    the caller can fall back. Scopes to ``schemas`` when given (focused study)."""
    if not _require_col(mw):
        return False
    try:
        from aqt.speedrun.reviewer import (
            build_review_cards,
            render_schema_weighted_review_html,
        )
        from speedrun.scoring.queue import SchemaWeightedReview

        kwargs: dict = {}
        if schemas:
            from speedrun.focus import subject_search

            kwargs["search"] = subject_search(schemas)
        session = SchemaWeightedReview(mw.col, limit=limit, **kwargs)
        mw._speedrun_review_session = session
        cards = build_review_cards(mw.col, session)
        html = render_schema_weighted_review_html(cards, embed=True)
    except Exception as exc:  # pragma: no cover - defensive
        tooltip(f"Review error: {exc}")
        return False

    _show_html(
        mw,
        html,
        title=title,
        minWidth=780,
        minHeight=680,
        bridge=_review_bridge(mw),
    )
    return True


def _show_preset_briefing(mw, *, set_kind: str, proceed, title: str, **params) -> None:
    """Show the grounded pre-set AI readiness briefing for a set, then run
    ``proceed`` (the real set launch) when the student clicks "Start set".

    Mirrors the recommender/tutor pattern: the pure-data logic + HTML live in
    ``speedrun.preset_eval``; this thin shim drops the body-only HTML into an
    AnkiWebView dialog and relays the "Start set" command back over the pycmd
    bridge to the SAME launch handler the set already used — so no launch logic is
    duplicated. On any briefing failure we proceed directly, so a briefing error
    can never block studying."""
    if not _require_col(mw):
        return
    try:
        from speedrun.preset_eval import (
            build_preset_briefing,
            render_preset_briefing_html,
        )

        briefing = build_preset_briefing(mw.col, set_kind=set_kind, **params)
        html = render_preset_briefing_html(briefing, embed=True)
    except Exception:  # pragma: no cover - never block the set on a briefing error
        proceed()
        return

    def bridge(cmd: str):
        from speedrun.preset_eval import START_SET_CMD

        if cmd == "close":
            dialog = getattr(mw, "_speedrun_html_dialog", None)
            if dialog is not None:
                dialog.close()
            return True
        if cmd == START_SET_CMD:
            dialog = getattr(mw, "_speedrun_html_dialog", None)
            if dialog is not None:
                dialog.close()
            proceed()
            return True
        # Let launcher/focus commands fall through to the shared bridge.
        return _launch_bridge(mw)(cmd)

    _show_html(
        mw,
        html,
        title=title,
        minWidth=760,
        minHeight=680,
        bridge=bridge,
    )


def _launcher_dispatch(mw) -> dict:
    """Map each dashboard launcher key to the SAME handler the Tools menu uses.

    The keys mirror ``speedrun.dashboard.LAUNCHER_KEYS`` exactly (validated
    below); no feature logic is duplicated here — every value just re-invokes an
    existing ``_show_*`` / action handler.
    """
    from speedrun.dashboard import LAUNCHER_KEYS, render_readiness_report_html

    dispatch = {
        "study_now": lambda: _start_study(mw),
        "study_all": lambda: _start_study_all(mw),
        "study_queue": lambda: _show_queue(mw),
        "focus": lambda: _show_focus(mw),
        "schema_drill": lambda: _show_drill(mw),
        "contrasting_pairs": lambda: _show_contrasting_drill(mw),
        "cold_open": lambda: _show_cold_open(mw),
        "two_answer_fork": lambda: _show_fork_trainer(mw),
        "study_next": lambda: _show_recommender(mw),
        "ai_tutor": lambda: _show_tutor(mw),
        "ai_settings": lambda: _show_ai_settings(mw),
        "dashboard": lambda: _show_dashboard(mw),
        "scores": lambda: _show_report(
            mw, render_readiness_report_html, "Readiness report"
        ),
        "import_seed": lambda: _import_seed(mw),
        "export": lambda: _export_report(mw),
    }
    # Fail loudly during development if the launcher markup and the dispatch drift
    # apart, so a new button can never silently do nothing.
    assert set(dispatch) == set(LAUNCHER_KEYS), (
        "dashboard launcher keys out of sync with dispatch: "
        f"{sorted(set(LAUNCHER_KEYS) ^ set(dispatch))}"
    )
    return dispatch


def _launch_bridge(mw):
    """A shared pycmd bridge for the interactive HTML surfaces (dashboard,
    recommender, focus picker).

    Handles three wire commands, all routed to the SAME menu handlers so no
    feature logic is duplicated:

    * ``close`` — close the current dialog.
    * ``speedrun:open:<key>`` — a launcher key (see ``LAUNCHER_KEYS``).
    * ``speedrun:focus:<token>`` — focused study for a subject (a schema id, or
      ``__weakest__`` for the auto-selected weakest areas).
    """

    def bridge(cmd: str):
        if cmd == "close":
            dialog = getattr(mw, "_speedrun_html_dialog", None)
            if dialog is not None:
                dialog.close()
            return True
        open_prefix = "speedrun:open:"
        if cmd.startswith(open_prefix):
            key = cmd[len(open_prefix) :]
            handler = _launcher_dispatch(mw).get(key)
            if handler is not None:
                handler()
                return True
            tooltip(f"Unknown launcher action: {key}")
            return True
        focus_prefix = "speedrun:focus:"
        if cmd.startswith(focus_prefix):
            _start_focused_study(mw, cmd[len(focus_prefix) :])
            return True
        # Let anything else fall through to AnkiWebView's default handling.
        return

    return bridge


def _show_dashboard(mw) -> None:
    if not _require_col(mw):
        return
    try:
        from speedrun.dashboard import render_dashboard_html

        html = render_dashboard_html(mw.col, embed=True)
    except Exception as exc:  # pragma: no cover - defensive
        tooltip(f"Dashboard error: {exc}")
        return

    _show_html(
        mw,
        html,
        title="LSAT Speedrun — Dashboard",
        minWidth=820,
        minHeight=720,
        bridge=_launch_bridge(mw),
    )
    _refresh_score_badge(mw)


def _show_recommender(mw) -> None:
    if not _require_col(mw):
        return
    try:
        from speedrun.ai.recommender import render_recommender_html

        html = render_recommender_html(mw.col, embed=True)
    except Exception as exc:  # pragma: no cover - defensive
        tooltip(f"Recommender error: {exc}")
        return
    _show_html(
        mw,
        html,
        title="LSAT Speedrun — What to study next",
        minWidth=760,
        minHeight=680,
        bridge=_launch_bridge(mw),
    )


def _show_focus(mw) -> None:
    if not _require_col(mw):
        return
    try:
        from speedrun.focus import render_focus_html

        html = render_focus_html(mw.col, embed=True)
    except Exception as exc:  # pragma: no cover - defensive
        tooltip(f"Focus error: {exc}")
        return
    _show_html(
        mw,
        html,
        title="LSAT Speedrun — Focus / study by subject",
        minWidth=760,
        minHeight=680,
        bridge=_launch_bridge(mw),
    )


def _build_filtered_deck(
    mw, *, name: str, search: str, limit: int, order: int = 0, reschedule: bool = True
) -> int:
    """Create or rebuild a native filtered ("cram") deck and return its id (0 on
    failure / unsupported build).

    Reuses Anki's scheduler verbatim — no new scheduling logic. An existing deck
    of the same name is rebuilt in place (so re-launching is safe); cards return
    to their home deck normally when studied or when the filtered deck is
    emptied, so the home deck is never mutated."""
    col = mw.col
    get = getattr(col.sched, "get_or_create_filtered_deck", None)
    add = getattr(col.sched, "add_or_update_filtered_deck", None)
    if get is None or add is None:
        return 0
    name = name[:90]
    did = 0
    try:
        existing = col.decks.id_for_name(name)
        if existing:
            did = int(existing)
    except Exception:
        did = 0
    deck = get(deck_id=did)
    deck.name = name
    cfg = deck.config
    if len(cfg.search_terms):
        cfg.search_terms[0].search = search
        cfg.search_terms[0].limit = limit
        cfg.search_terms[0].order = order
    else:
        from anki.decks_pb2 import FilteredDeckConfig

        cfg.search_terms.append(
            FilteredDeckConfig.SearchTerm(search=search, limit=limit, order=order)
        )
    cfg.reschedule = reschedule
    out = add(deck)
    return int(getattr(out, "id", 0)) or did


def _launch_filtered_study(mw, schemas: list, label: str) -> bool:
    """Best-effort: build a native filtered deck scoped to the subject so the
    student studies ONLY those items in the real reviewer, reusing Anki's
    scheduler. Returns True if study was launched. Never raises out."""
    from speedrun.focus import subject_search

    new_did = _build_filtered_deck(
        mw,
        name=f"LSAT Focus: {label}",
        search=subject_search(schemas),
        limit=200,
        order=0,
    )
    if not new_did:
        return False
    mw.col.decks.select(new_did)
    mw.col.startTimebox()
    mw.moveToState("review")
    tooltip(f"Focused study: {label}")
    return True


def _start_study_all(mw) -> None:
    """Uncapped "Study all": build/rebuild a filtered ("cram") deck holding the
    WHOLE Speedrun deck so students can grind past the per-deck daily new-card
    cap in one sitting.

    Uses the shared filtered-deck builder (Anki's scheduler, no new logic).
    Handles the empty-deck case (seed deck not imported) and rebuild-if-exists
    gracefully. Cards return to the home deck normally when done."""
    if not _require_col(mw):
        return
    try:
        from speedrun.focus import study_all_spec

        name, search, limit, order = study_all_spec()
        new_did = _build_filtered_deck(
            mw, name=name, search=search, limit=limit, order=order
        )
        if not new_did:
            tooltip("Study all isn't supported on this Anki build.")
            return
        gathered = len(mw.col.find_cards(f'deck:"{name}"'))
        if gathered == 0:
            mw.col.decks.select(new_did)
            mw.moveToState("overview")
            tooltip("Nothing to study yet — import the seed deck first.")
            return
        mw.col.decks.select(new_did)
        mw.col.startTimebox()
        mw.moveToState("review")
        tooltip(f"Study all: {gathered} card(s), uncapped.")
    except Exception as exc:  # pragma: no cover - defensive
        tooltip(f"Study all error: {exc}")


def _start_focused_study(mw, token: str) -> None:
    """Focus launcher (from the pycmd bridge): show the grounded pre-set briefing
    for the chosen subject first, then launch focused study on "Start set".

    ``token`` is a schema id, or ``__weakest__`` for the auto-selected weakest
    areas."""
    if not _require_col(mw):
        return
    token = (token or "").strip()
    if not token:
        tooltip("No subject selected.")
        return
    _show_preset_briefing(
        mw,
        set_kind="focus",
        schema=token,
        proceed=lambda: _launch_focused_study(mw, token),
        title="LSAT Speedrun — Before you start: Focus",
    )


def _launch_focused_study(mw, token: str) -> None:
    """Launch focused study for a subject token.

    ``token`` is a schema id, or ``__weakest__`` for the auto-selected weakest
    areas. Tries a real filtered-deck reviewer session; on any failure falls back
    to the filtered schema-weighted queue view (always works, headless-safe)."""
    if not _require_col(mw):
        return
    from speedrun.focus import WEAKEST_TOKEN, weakest_subjects

    token = (token or "").strip()
    if token == WEAKEST_TOKEN:
        try:
            schemas = weakest_subjects(mw.col)
        except Exception:
            schemas = []
        label = "your weakest areas"
    elif token:
        schemas = [token]
        try:
            from speedrun.taxonomy.labels import schema_label

            label = schema_label(token)
        except Exception:
            label = token
    else:
        tooltip("No subject selected.")
        return
    if not schemas:
        tooltip("No subject to focus on yet — practice a little first.")
        return

    # Prefer the Speedrun-native review so focused study also grades in
    # schema-weighted priority order (not native scheduler order).
    try:
        if _launch_schema_weighted_review(
            mw, schemas=schemas, title=f"LSAT Speedrun — Focus: {label}"
        ):
            return
    except Exception:
        pass  # fall through to filtered-deck / queue view

    try:
        if _launch_filtered_study(mw, schemas, label):
            return
    except Exception:
        pass  # fall through to the queue view

    try:
        from speedrun.focus import render_focus_queue_html

        html = render_focus_queue_html(
            mw.col, schemas, title=f"LSAT Speedrun — Focus: {label}"
        )
    except Exception as exc:  # pragma: no cover - defensive
        tooltip(f"Focus error: {exc}")
        return
    _show_html(
        mw,
        html,
        title=f"LSAT Speedrun — Focus: {label}",
        minWidth=620,
        minHeight=520,
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
    """Contrasting-pairs launcher: show the grounded pre-set briefing first, then
    open the drill on "Start set"."""
    if not _require_col(mw):
        return
    _show_preset_briefing(
        mw,
        set_kind="contrasting",
        proceed=lambda: _launch_contrasting_drill(mw),
        title="LSAT Speedrun — Before you start: Contrasting pairs",
    )


def _launch_contrasting_drill(mw) -> None:
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
        compare_prefix = "speedrun:compare:"
        if cmd.startswith(compare_prefix):
            from speedrun.ai.pair_compare import compare_for_bridge

            try:
                # Wire form: speedrun:compare:<item_id>:<chosen_id>. Item ids carry
                # no colon, so split the choice id off the right.
                rest = cmd[len(compare_prefix) :]
                item_id, chosen_id = rest.rsplit(":", 1)
                return compare_for_bridge(item_id, chosen_id)
            except Exception:  # pragma: no cover - never break the drill
                return {
                    "comparison": "Sorry — I could not compare that.",
                    "source": "offline",
                    "ai_used": False,
                    "citations": [],
                }
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
    """Cold-open launcher: show the grounded pre-set briefing first, then open the
    cold-open on "Start set"."""
    if not _require_col(mw):
        return
    _show_preset_briefing(
        mw,
        set_kind="cold_open",
        proceed=lambda: _launch_cold_open(mw),
        title="LSAT Speedrun — Before you start: Cold-open",
    )


def _launch_cold_open(mw) -> None:
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
        reason_prefix = "speedrun:reasoning:"
        if cmd.startswith(reason_prefix):
            import json

            from speedrun.ai.reasoning_evaluator import record_reasoning_result

            try:
                payload = json.loads(cmd[len(reason_prefix) :])
                # Grades the explanation (AI when enabled, offline heuristic
                # otherwise) and persists it as diagnostic-only signal.
                return record_reasoning_result(_drill_logger(mw), payload)
            except Exception:  # pragma: no cover - never break the drill
                return {
                    "feedback": "Explanation recorded.",
                    "score": None,
                    "source": "offline",
                    "weakness_patterns": [],
                    "ai_used": False,
                }
        return

    _show_html(
        mw,
        html,
        title="LSAT Speedrun — Two-answer fork",
        minWidth=780,
        minHeight=680,
        bridge=bridge,
    )


def _show_tutor(mw) -> None:
    _ensure_speedrun_on_path()
    try:
        from speedrun.ai.tutor import render_tutor_html

        html = render_tutor_html(embed=True)
    except Exception as exc:  # pragma: no cover - defensive
        tooltip(f"Tutor error: {exc}")
        return

    def bridge(cmd: str):
        if cmd == "close":
            dialog = getattr(mw, "_speedrun_html_dialog", None)
            if dialog is not None:
                dialog.close()
            return
        prefix = "speedrun:tutor:"
        if cmd.startswith(prefix):
            import json

            from speedrun.ai.tutor import answer_for_bridge

            try:
                payload = json.loads(cmd[len(prefix) :])
                # Returned dict is JSON-encoded once by the webview bridge and
                # decoded once by pycmd, so the JS callback receives an object.
                return answer_for_bridge(
                    payload.get("item_id", ""),
                    payload.get("question", ""),
                    history=payload.get("history"),
                )
            except Exception:  # pragma: no cover - never break the chat
                return {
                    "answer": "Sorry — I could not answer that.",
                    "source": "offline",
                    "ai_used": False,
                    "citations": [],
                }
        return

    _show_html(
        mw,
        html,
        title="LSAT Speedrun — AI Tutor",
        minWidth=780,
        minHeight=720,
        bridge=bridge,
    )


def _show_ai_settings(mw) -> None:
    """Modal dialog to enable/configure the AI Tutor without editing env vars.

    Writes to the device-local settings store (never the synced collection).
    Applies immediately: ``default_client()`` reads the store fresh each call,
    so no relaunch is needed. The ``SPEEDRUN_AI_OFF`` env var still overrides
    everything for tests / CI / power users.
    """
    _ensure_speedrun_on_path()
    _point_ai_settings_at_profile(mw)
    try:
        from speedrun.ai.settings import (
            DEFAULT_BASE_URL,
            DEFAULT_MODEL,
            load_settings,
            masked_key_hint,
            save_settings,
            settings_path,
        )
    except Exception as exc:  # pragma: no cover - defensive
        tooltip(f"AI Settings unavailable: {exc}")
        return

    from aqt.qt import (
        QCheckBox,
        QDialog,
        QDialogButtonBox,
        QLabel,
        QLineEdit,
        QVBoxLayout,
        Qt,
    )

    env_forced = os.environ.get("SPEEDRUN_AI_OFF") is not None
    cur = load_settings()

    diag = QDialog(mw)
    diag.setWindowTitle("LSAT Speedrun — AI Settings")
    disable_help_button(diag)
    layout = QVBoxLayout(diag)

    enable = QCheckBox("Enable AI Tutor (opt-in)")
    enable.setChecked(bool(cur.get("ai_enabled", False)))
    layout.addWidget(enable)

    layout.addWidget(QLabel("OpenAI API key"))
    key_edit = QLineEdit()
    key_edit.setEchoMode(QLineEdit.EchoMode.Password)
    key_edit.setText(str(cur.get("openai_api_key", "")))
    hint = masked_key_hint()
    key_edit.setPlaceholderText(
        f"Stored: {hint}" if hint else "sk-… (stored locally on this device)"
    )
    layout.addWidget(key_edit)

    layout.addWidget(QLabel("Model"))
    model_edit = QLineEdit()
    model_edit.setText(str(cur.get("openai_model", DEFAULT_MODEL)))
    model_edit.setPlaceholderText(DEFAULT_MODEL)
    layout.addWidget(model_edit)

    layout.addWidget(QLabel("Base URL (optional — for a proxy/local server)"))
    url_edit = QLineEdit()
    url_edit.setText(str(cur.get("openai_base_url", DEFAULT_BASE_URL)))
    url_edit.setPlaceholderText(DEFAULT_BASE_URL)
    layout.addWidget(url_edit)

    note = QLabel(
        "The API key is stored locally on this device only — it is never synced "
        "to AnkiWeb or written into your collection. Setting the SPEEDRUN_AI_OFF "
        "environment variable still overrides this."
    )
    note.setWordWrap(True)
    note.setStyleSheet("color: palette(mid); font-size: 11px;")
    layout.addWidget(note)

    if env_forced:
        warn = QLabel(
            "Note: SPEEDRUN_AI_OFF is currently set in the environment, so it "
            "overrides the checkbox above until you unset it."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color: palette(mid); font-size: 11px;")
        layout.addWidget(warn)

    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
    )
    layout.addWidget(box)
    qconnect(box.accepted, diag.accept)
    qconnect(box.rejected, diag.reject)

    diag.setMinimumWidth(420)
    if diag.exec() != QDialog.DialogCode.Accepted:
        return

    try:
        path = save_settings(
            {
                "ai_enabled": enable.isChecked(),
                "openai_api_key": key_edit.text().strip(),
                "openai_model": model_edit.text().strip() or DEFAULT_MODEL,
                "openai_base_url": url_edit.text().strip() or DEFAULT_BASE_URL,
            }
        )
    except Exception as exc:  # pragma: no cover - defensive
        tooltip(f"Could not save AI settings: {exc}")
        return

    _refresh_ai_status(mw)
    from speedrun.ai.config import ai_enabled

    if enable.isChecked() and not ai_enabled() and env_forced:
        tooltip("Saved. AI stays OFF because SPEEDRUN_AI_OFF is set in the environment.")
    else:
        tooltip(f"AI settings saved ({'ON' if ai_enabled() else 'OFF'}).")
    _ = path  # path intentionally not shown/logged (may sit beside the key file)


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
