# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the RC AI commentator.

The commentator must stay grounded: the offline path reads only the passage, the
AI path is gated behind the (default-off) AI switch, and questions are answered
from the passage text -- never invented.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.rc_commentator import (  # noqa: E402
    Passage,
    analyze_passage,
    answer_question,
    build_commentary_prompt,
    commentate,
    commentator_payload,
    extractive_answer,
    load_passages,
    render_rc_commentator_html,
    resolve_passage_text,
)

PASSAGE = (
    "Historians once treated early cartography as a straightforward record of "
    "geographic knowledge. Recent scholarship complicates this view. Maps, these "
    "scholars argue, were also instruments of persuasion. Yet the revisionists "
    "sometimes overreach, implying that accuracy was never a mapmaker's goal. The "
    "evidence suggests a middle position: cartographers pursued utility and "
    "rhetoric together, and the balance shifted with a map's purpose."
)


class _FakeResp:
    def __init__(self, text: str, source: str = "fake") -> None:
        self.text = text
        self.source = source

    @property
    def ok(self) -> bool:
        # Mirror LLMResponse.ok: usable text from a real, named source.
        return bool(self.text.strip()) and not self.source.startswith(
            ("stub", "openai-error")
        )


class _FakeClient:
    def __init__(self, text: str) -> None:
        self._text = text
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, max_tokens: int = 512) -> _FakeResp:
        self.prompts.append(prompt)
        return _FakeResp(self._text)


# --------------------------------------------------------------------------- #
# Loading / resolution
# --------------------------------------------------------------------------- #


def test_load_passages_from_seed():
    passages = load_passages()
    assert passages, "seed deck should contain RC passages"
    assert all(isinstance(p, Passage) for p in passages)
    for p in passages:
        assert p.text and not p.text.startswith("(see")
        assert p.schemas
        assert p.questions


def test_resolve_follows_see_references():
    items = [
        {"passage_id": "rc-x", "passage": "Full text here.", "section": "RC"},
        {"passage_id": "rc-x", "passage": "(see rc-x)", "section": "RC"},
    ]
    assert resolve_passage_text(items, "rc-x") == "Full text here."
    assert resolve_passage_text(items, "missing") == ""


# --------------------------------------------------------------------------- #
# Deterministic analysis
# --------------------------------------------------------------------------- #


def test_analysis_is_grounded_in_passage():
    c = analyze_passage(PASSAGE, passage_id="rc-0001", schemas=["rc.main_point"])
    # Main point should be a sentence lifted from the passage, not invented.
    assert c.main_point in PASSAGE
    # The author's synthesis sentence is the middle-position one.
    assert "middle position" in c.main_point
    roles = {s["role"] for s in c.structure}
    assert "Setup / traditional view" in roles
    assert "Author's synthesis" in roles
    assert c.tone != ""
    assert c.reading_tips


def test_analysis_detects_viewpoints_and_transitions():
    c = analyze_passage(PASSAGE, schemas=["rc.viewpoint_attribution"])
    holders = {v["holder"] for v in c.viewpoints}
    assert "The author's own position" in holders
    words = {t["word"] for t in c.transitions}
    assert "yet" in words or "recent" in words
    # schema-targeted tip is appended
    assert any("Attribute" in t for t in c.reading_tips)


def test_analysis_deterministic():
    a = analyze_passage(PASSAGE, passage_id="p", schemas=["rc.main_point"]).to_dict()
    b = analyze_passage(PASSAGE, passage_id="p", schemas=["rc.main_point"]).to_dict()
    assert a == b


# --------------------------------------------------------------------------- #
# Extractive answering (grounded, no invention)
# --------------------------------------------------------------------------- #


def test_extractive_answer_returns_passage_sentences():
    ev = extractive_answer(PASSAGE, "What is the author's overall position?")
    assert ev
    for sent in ev:
        assert sent in PASSAGE


def test_extractive_answer_empty_on_no_overlap():
    assert extractive_answer(PASSAGE, "zzz qqq xylophone") == []


# --------------------------------------------------------------------------- #
# AI gate on/off
# --------------------------------------------------------------------------- #


def test_commentate_offline_when_ai_off(monkeypatch):
    monkeypatch.setenv("SPEEDRUN_AI_OFF", "1")
    fake = _FakeClient("SHOULD NOT BE USED")
    res = commentate(PASSAGE, passage_id="rc-0001", schemas=["rc.main_point"], client=fake)
    assert res.ai_used is False
    assert res.source == "offline"
    assert res.ai_text == ""
    assert fake.prompts == []  # AI never called
    assert res.analysis.main_point in PASSAGE


def test_commentate_uses_ai_when_enabled(monkeypatch):
    monkeypatch.setenv("SPEEDRUN_AI_OFF", "0")
    fake = _FakeClient("A grounded AI reading.")
    res = commentate(PASSAGE, client=fake)
    assert res.ai_used is True
    assert res.ai_text == "A grounded AI reading."
    assert fake.prompts and PASSAGE in fake.prompts[0]
    # Offline analysis is still attached as a fallback view.
    assert res.analysis.structure


def test_commentate_falls_back_when_ai_returns_empty(monkeypatch):
    monkeypatch.setenv("SPEEDRUN_AI_OFF", "0")
    res = commentate(PASSAGE, client=_FakeClient("   "))
    assert res.ai_used is False
    assert res.source == "offline"


def test_answer_question_offline(monkeypatch):
    monkeypatch.setenv("SPEEDRUN_AI_OFF", "1")
    out = answer_question(PASSAGE, "What did historians once treat cartography as?")
    assert out["ai_used"] is False
    assert out["source"] == "offline-extractive"
    assert out["evidence"]
    assert all(s in PASSAGE for s in out["evidence"])


def test_answer_question_ai(monkeypatch):
    monkeypatch.setenv("SPEEDRUN_AI_OFF", "0")
    fake = _FakeClient("Grounded answer.")
    out = answer_question(PASSAGE, "What is the main point?", client=fake)
    assert out["ai_used"] is True
    assert out["answer"] == "Grounded answer."


# --------------------------------------------------------------------------- #
# Prompt grounding
# --------------------------------------------------------------------------- #


def test_prompt_contains_grounding_rules_and_passage():
    prompt = build_commentary_prompt(PASSAGE, "What is the tone?")
    assert PASSAGE in prompt
    assert "ONLY information stated in the passage" in prompt
    assert "Quote" in prompt
    assert "What is the tone?" in prompt


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def test_payload_is_json_serialisable():
    payload = commentator_payload()
    json.dumps(payload)  # must not raise
    assert payload["passages"]
    assert "ai_enabled" in payload
    assert payload["passages"][0]["commentary"]["main_point"]


def test_render_full_and_embed():
    full = render_rc_commentator_html()
    assert "<!DOCTYPE html>" in full or "<html" in full
    assert "RC AI commentator" in full
    assert "sr-rc-data" in full

    embed = render_rc_commentator_html(embed=True)
    assert "sr-dash" in embed
    assert "<!DOCTYPE html>" not in embed


def test_render_empty(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"items": []}), encoding="utf-8")
    html = render_rc_commentator_html(path=empty)
    assert "No reading-comprehension passages" in html
