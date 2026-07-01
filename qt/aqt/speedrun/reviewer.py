# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Minimal reviewer hooks: post-review toast and optional sidebar stats."""

from __future__ import annotations

import sys
from pathlib import Path

from aqt.qt import QDockWidget, QLabel, Qt, QWidget, qconnect
from aqt.utils import tooltip


def _ensure_speedrun_on_path() -> bool:
    here = Path(__file__).resolve()
    candidates = [Path.cwd()]
    if len(here.parents) > 4:
        candidates.append(here.parents[4])
    for cand in candidates:
        if (cand / "speedrun" / "scoring" / "memory.py").exists():
            if str(cand) not in sys.path:
                sys.path.insert(0, str(cand))
            return True
    return False


def _schema_from_card(card) -> str | None:
    for tag in card.note().tags:
        if tag.startswith("sr:schema:"):
            return tag[len("sr:schema:") :]
    return None


def _section_from_note(note) -> str:
    for tag in note.tags:
        if tag.startswith("sr:section:"):
            return tag[len("sr:section:") :]
    return "LR"


def on_reviewer_did_answer(reviewer, card, ease: int) -> None:
    """Post-review feedback toast: schema, latency vs budget, retrievability."""
    if not _ensure_speedrun_on_path():
        return
    schema = _schema_from_card(card)
    if schema is None:
        return
    try:
        import time

        from speedrun.config import latency_budget_ms
        from speedrun.scoring.memory import collection_memory_records

        col = reviewer.mw.col
        section = _section_from_note(card.note())
        budget = latency_budget_ms(section)
        latency_ms = (
            int((time.time() - reviewer._speedrun_card_start) * 1000)
            if hasattr(reviewer, "_speedrun_card_start")
            else 0
        )
        on_budget = ease != 1 and latency_ms <= budget
        retr = None
        for s, r in collection_memory_records(col):
            if s == schema and r is not None:
                retr = r
                break
        parts = [schema.split(".")[-1]]
        if latency_ms:
            parts.append(f"{latency_ms // 1000}s vs {budget // 1000}s budget")
        parts.append("on-budget" if on_budget else "over budget / miss")
        if retr is not None:
            parts.append(f"R={retr:.0%}")
        tooltip("Speedrun · " + " · ".join(parts))
        if hasattr(reviewer, "_speedrun_session_stats"):
            reviewer._speedrun_session_stats["reviews"] += 1
            if ease != 1:
                reviewer._speedrun_session_stats["hits"] += 1
            _update_sidebar(reviewer)
    except Exception:
        pass


def on_reviewer_will_show_question(reviewer, card) -> None:
    import time

    reviewer._speedrun_card_start = time.time()
    if not hasattr(reviewer, "_speedrun_session_stats"):
        reviewer._speedrun_session_stats = {"reviews": 0, "hits": 0}
    _update_sidebar(reviewer, card=card)


def _update_sidebar(reviewer, card=None) -> None:
    dock = getattr(reviewer.mw, "_speedrun_sidebar", None)
    if dock is None:
        return
    label = dock.widget().findChild(QLabel, "speedrun_sidebar_label")
    if label is None:
        return
    schema = _schema_from_card(card) if card else None
    stats = getattr(reviewer, "_speedrun_session_stats", {"reviews": 0, "hits": 0})
    acc = stats["hits"] / stats["reviews"] if stats["reviews"] else 0
    label.setText(
        f"Schema: {schema or '—'}\nSession: {stats['reviews']} reviews · {acc:.0%} hits"
    )


def install_sidebar(mw) -> None:
    """Optional dock widget with current schema + session stats."""
    if getattr(mw, "_speedrun_sidebar", None) is not None:
        return
    dock = QDockWidget("Speedrun", mw)
    dock.setObjectName("SpeedrunSidebar")
    widget = QWidget()
    label = QLabel("Schema: —\nSession: 0 reviews")
    label.setObjectName("speedrun_sidebar_label")
    label.setWordWrap(True)
    from aqt.qt import QVBoxLayout

    layout = QVBoxLayout(widget)
    layout.addWidget(label)
    dock.setWidget(widget)
    mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    mw._speedrun_sidebar = dock


def hook_reviewer(reviewer) -> None:
    """Attach speedrun hooks to an open reviewer instance."""
    qconnect(
        reviewer.didAnswerCard,
        lambda ease: on_reviewer_did_answer(reviewer, reviewer.card, ease),
    )
    qconnect(
        reviewer.showQuestion,
        lambda: on_reviewer_will_show_question(reviewer, reviewer.card),
    )
