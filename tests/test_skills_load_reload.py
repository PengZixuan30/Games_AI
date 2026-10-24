"""A broken ``skills.json`` must not abort ``on_load``; a removed model must not abort a reload."""
import json
import logging
import os

import pytest

import games_ai
from games_ai.ai.chat_param import ChatParam
from games_ai.core.config import plugin_config

MODEL = "test-model"


class FakeServer:
    def __init__(self):
        self.logger = logging.getLogger("skills-load-server")


@pytest.fixture
def skills_server(monkeypatch):
    monkeypatch.setattr(plugin_config, "prefix", "[GamesAI]")
    return FakeServer()


def test_a_missing_skills_file_loads_with_no_skills(tmp_path, skills_server):
    assert games_ai._load_skills_index(skills_server, str(tmp_path / "missing.json")) == []


def test_a_broken_skills_file_loads_with_no_skills(tmp_path, skills_server):
    broken = tmp_path / "skills.json"
    broken.write_text("{not json", encoding="utf-8")
    assert games_ai._load_skills_index(skills_server, str(broken)) == []


def test_a_skills_file_that_is_not_a_list_loads_with_no_skills(tmp_path, skills_server):
    wrong = tmp_path / "skills.json"
    wrong.write_text(json.dumps({"file": "x.md"}), encoding="utf-8")
    assert games_ai._load_skills_index(skills_server, str(wrong)) == []


def test_a_valid_skills_file_comes_back(tmp_path, skills_server):
    valid = tmp_path / "skills.json"
    payload = [{"file": "demo.md", "description": "one line"}]
    valid.write_text(json.dumps(payload), encoding="utf-8")
    assert games_ai._load_skills_index(skills_server, str(valid)) == payload


@pytest.fixture
def reload_env(monkeypatch):
    monkeypatch.setattr(plugin_config, "prefix", "[GamesAI]")
    monkeypatch.setattr(plugin_config, "all_ai", {MODEL: {"ai_model": "gpt-test"}})
    return None


def _bare_param(monkeypatch, calls):
    param = ChatParam.__new__(ChatParam)
    param.model_id = MODEL
    param.ai_info = {"ai_model": "old"}
    param.server = type("S", (), {"rtr": lambda self, key, **kw: key})()
    monkeypatch.setattr(param, "build_openai_client", lambda: calls.append("client"))
    monkeypatch.setattr(param, "build_system_message", lambda: calls.append("system"))
    return param


def test_a_removed_model_keeps_the_previous_client_and_config(monkeypatch, reload_env):
    calls = []
    param = _bare_param(monkeypatch, calls)
    monkeypatch.setattr(plugin_config, "all_ai", {})

    assert param.reload_ai_info() is False, "the removed model is reported, not raised"
    assert param.ai_info == {"ai_model": "old"}, "the previous config is kept"
    assert calls == [], "the client is not rebuilt with a missing model"


def test_a_configured_model_is_reloaded(monkeypatch, reload_env):
    calls = []
    param = _bare_param(monkeypatch, calls)

    assert param.reload_ai_info() is True
    assert param.ai_info == {"ai_model": "gpt-test"}
    assert calls == ["client", "system"]
