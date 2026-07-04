# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the device-local AI settings store and its precedence over env vars.

Covers:
  * env override precedence (SPEEDRUN_AI_OFF wins when explicitly set),
  * stored-setting enable when the env var is unset,
  * OpenAILLMClient preferring the stored key/model/base_url with env fallback,
  * the API key is stored device-local and never written to the collection.

All offline; no network (uses the settings file + Stub/OpenAI clients only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.ai import settings as ai_settings  # noqa: E402
from speedrun.ai.client import OpenAILLMClient  # noqa: E402
from speedrun.ai.config import ai_enabled  # noqa: E402


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Point the settings store at an isolated temp file and clear AI env vars."""
    path = tmp_path / "ai_settings.json"
    monkeypatch.setenv(ai_settings.PATH_ENV, str(path))
    monkeypatch.delenv("SPEEDRUN_AI_OFF", raising=False)
    for var in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    return path


# --------------------------------------------------------------------------- #
# Store round-trip
# --------------------------------------------------------------------------- #


def test_defaults_when_no_file(store):
    cfg = ai_settings.load_settings()
    assert cfg["ai_enabled"] is False
    assert cfg["openai_api_key"] == ""
    assert cfg["openai_model"] == ai_settings.DEFAULT_MODEL
    assert cfg["openai_base_url"] == ai_settings.DEFAULT_BASE_URL


def test_save_round_trips(store):
    ai_settings.save_settings(
        {
            "ai_enabled": True,
            "openai_api_key": "sk-stored-123456",
            "openai_model": "gpt-4o",
            "openai_base_url": "https://proxy.example/v1",
        }
    )
    cfg = ai_settings.load_settings()
    assert cfg["ai_enabled"] is True
    assert cfg["openai_api_key"] == "sk-stored-123456"
    assert cfg["openai_model"] == "gpt-4o"
    assert cfg["openai_base_url"] == "https://proxy.example/v1"


def test_masked_hint_never_reveals_full_key(store):
    ai_settings.save_settings({"openai_api_key": "sk-abcdef7890"})
    hint = ai_settings.masked_key_hint()
    assert hint.endswith("7890")
    assert "sk-abcdef" not in hint


# --------------------------------------------------------------------------- #
# Precedence: env override vs stored setting
# --------------------------------------------------------------------------- #


def test_env_override_wins_over_store_off(store, monkeypatch):
    # Store says ON, but env explicitly forces OFF -> OFF.
    ai_settings.save_settings({"ai_enabled": True})
    monkeypatch.setenv("SPEEDRUN_AI_OFF", "1")
    assert ai_enabled() is False


def test_env_override_wins_over_store_on(store, monkeypatch):
    # Store says OFF, but env explicitly forces ON -> ON.
    ai_settings.save_settings({"ai_enabled": False})
    monkeypatch.setenv("SPEEDRUN_AI_OFF", "0")
    assert ai_enabled() is True


def test_stored_setting_enables_when_env_unset(store):
    ai_settings.save_settings({"ai_enabled": True})
    assert ai_enabled() is True


def test_stored_setting_disables_when_env_unset(store):
    ai_settings.save_settings({"ai_enabled": False})
    assert ai_enabled() is False


def test_default_off_when_nothing_set(store):
    assert ai_enabled() is False


# --------------------------------------------------------------------------- #
# Client: stored config preferred, env fallback, no-key safety
# --------------------------------------------------------------------------- #


def test_client_prefers_stored_key_model_url(store):
    ai_settings.save_settings(
        {
            "openai_api_key": "sk-from-store",
            "openai_model": "gpt-4o",
            "openai_base_url": "https://proxy.example/v1/",
        }
    )
    client = OpenAILLMClient()
    assert client._api_key == "sk-from-store"
    assert client.model == "gpt-4o"
    assert client.base_url == "https://proxy.example/v1"  # trailing slash trimmed


def test_client_falls_back_to_env_when_store_empty(store, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-env-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example/v1")
    client = OpenAILLMClient()
    assert client._api_key == "sk-from-env"
    assert client.model == "gpt-env-model"
    assert client.base_url == "https://env.example/v1"


def test_client_stored_key_beats_env_key(store, monkeypatch):
    ai_settings.save_settings({"openai_api_key": "sk-from-store"})
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    assert OpenAILLMClient()._api_key == "sk-from-store"


def test_client_no_key_anywhere_is_stub_no_key(store, monkeypatch):
    monkeypatch.setenv("SPEEDRUN_AI_OFF", "0")  # AI on, but no key anywhere
    resp = OpenAILLMClient().complete("hi")
    assert resp.source == "stub-no-key"
    assert resp.ok is False


# --------------------------------------------------------------------------- #
# Security: key is device-local, never written to the collection config
# --------------------------------------------------------------------------- #


class _FakeCol:
    """Records anything written via set_config so we can assert the key isn't."""

    def __init__(self) -> None:
        self._conf: dict[str, object] = {}

    def set_config(self, key: str, val: object) -> None:
        self._conf[key] = val

    def get_config(self, key: str, default: object = None) -> object:
        return self._conf.get(key, default)


def test_key_saved_to_device_file_not_collection(store):
    col = _FakeCol()
    path = ai_settings.save_settings({"openai_api_key": "sk-secret-999"})

    # (a) The key lives in the device-local file...
    on_disk = json.loads(Path(path).read_text(encoding="utf-8"))
    assert on_disk["openai_api_key"] == "sk-secret-999"

    # (b) ...and nothing was ever written to the (synced) collection config.
    assert col._conf == {}
    for key in ("openai_api_key", "ai_enabled", "openai_model", "openai_base_url"):
        assert col.get_config(key) is None


def test_settings_module_never_touches_collection():
    """Guard: the store never calls the collection API nor imports anki.

    Uses the AST so prose in the docstring (which mentions ``col.set_config``)
    can't cause false positives — we only look at real imports and call sites.
    """
    import ast

    tree = ast.parse((REPO_ROOT / "speedrun/ai/settings.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("anki"), alias.name
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("anki"), node.module
        elif isinstance(node, ast.Attribute):
            assert node.attr not in ("set_config", "get_config"), node.attr
