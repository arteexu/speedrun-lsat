# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""JSON study session logger for experiment reproducibility."""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

DEFAULT_LOG = Path.home() / ".speedrun" / "sessions.jsonl"


@dataclass
class SessionEvent:
    ts: int
    event: str
    card_id: int | None = None
    schema: str | None = None
    ease: int | None = None
    latency_ms: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StudySession:
    session_id: str
    started_at: int
    ended_at: int | None = None
    events: list[SessionEvent] = field(default_factory=list)
    mode: str = "review"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["events"] = [e.to_dict() for e in self.events]
        return d


class SessionLogger:
    def __init__(self, log_path: Path = DEFAULT_LOG) -> None:
        self.log_path = log_path
        self._current: StudySession | None = None

    def start(self, *, mode: str = "review") -> StudySession:
        sid = f"s-{int(time.time())}"
        self._current = StudySession(session_id=sid, started_at=int(time.time()), mode=mode)
        self._append({"type": "session_start", "session": self._current.to_dict()})
        return self._current

    def log_review(
        self,
        *,
        card_id: int,
        schema: str | None,
        ease: int,
        latency_ms: int,
    ) -> None:
        if self._current is None:
            self.start()
        assert self._current is not None
        ev = SessionEvent(
            ts=int(time.time()),
            event="review",
            card_id=card_id,
            schema=schema,
            ease=ease,
            latency_ms=latency_ms,
        )
        self._current.events.append(ev)
        self._append({"type": "review", "session_id": self._current.session_id, **ev.to_dict()})

    def end(self) -> StudySession | None:
        if self._current is None:
            return None
        self._current.ended_at = int(time.time())
        self._append({"type": "session_end", "session": self._current.to_dict()})
        finished = self._current
        self._current = None
        return finished

    def _append(self, record: dict[str, Any]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")


def load_sessions(log_path: Path = DEFAULT_LOG, *, limit: int = 50) -> list[dict[str, Any]]:
    if not log_path.is_file():
        return []
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
