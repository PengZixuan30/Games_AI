"""Round ownership: one AI round at a time per conversation, queued asks merged afterwards.

An ``!!ask`` used to guard only with ``is_stopped`` (an Event), which two threads can both see
as "clear": two rounds then appended their questions and answers to the same history, queued
``!!ask -f`` messages could be merged into a half-written tool-call group, and ``!!ask stop``
only marked the event instead of the round. The conversation object now has an explicit round
owner (a lock + an active flag): the owner drains questions that arrived meanwhile and sends
them as one merged follow-up round, while ``!!ask stop`` keeps them queued (operator choice).
"""
import logging
import os
import threading

import pytest

import games_ai
import games_ai.ai.chat_param as chat_param
from games_ai.ai.chat_param import ChatParam
from games_ai.core import database
from games_ai.core.config import plugin_config

import test_ask_errors as base

MODEL = "test-model"


class Provider:
    """A provider stub that records every request and waits at scripted points."""

    def __init__(self):
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block_first = True
        self.lock = threading.Lock()

    def __call__(self, client, *, model, response_list, tools, extra_body):
        with self.lock:
            self.calls.append(list(response_list))
            number = len(self.calls)
        if number == 1 and self.block_first:
            self.entered.set()
            assert self.release.wait(10), "the test never released the first provider call"
        reply = type("Reply", (), {
            "content": "ANSWER {}".format(number),
            "tool_calls": None,
        })()
        return reply, {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}


@pytest.fixture
def env(tmp_path, monkeypatch, english):
    server = base.FakeServer(str(tmp_path), english)
    capture = base.LogCapture()
    server.logger.addHandler(capture)
    server.logger.setLevel(logging.DEBUG)
    server.logger.propagate = False
    monkeypatch.setattr(games_ai.core.logger, "_server", server, raising=False)
    monkeypatch.setattr(games_ai, "_server_ref", server, raising=False)
    monkeypatch.setattr(games_ai, "all_chat_param", {}, raising=False)
    monkeypatch.setattr(games_ai, "_history_frozen", False, raising=False)
    monkeypatch.setattr(games_ai, "_cross_server", None, raising=False)
    monkeypatch.setattr(games_ai, "_player_servers", {}, raising=False)
    monkeypatch.setattr(plugin_config, "prefix", "[GamesAI]")
    monkeypatch.setattr(plugin_config, "data_path", os.path.join(str(tmp_path), "public_database.db"))
    monkeypatch.setattr(plugin_config, "default_ai", MODEL)
    monkeypatch.setattr(plugin_config, "all_ai", {MODEL: {
        "ai_name": "[AI] ", "ai_model": "gpt-test", "base_url": "https://api.example.invalid/v1",
        "api_key": "sk-test", "prompt": "you are a test", "extra_body": {}}})
    monkeypatch.setattr(plugin_config, "skills_description", [])
    monkeypatch.setattr(plugin_config, "allow_permission", 3)
    monkeypatch.setattr(plugin_config, "debug_mode", False)
    database.open_public_database(os.path.join(str(tmp_path), "public_database.db"))
    try:
        yield base.SimpleNamespace(server=server, capture=capture, folder=str(tmp_path))
    finally:
        database.close_public_database()
        server.logger.removeHandler(capture)
        server.logger.setLevel(logging.NOTSET)
        server.logger.propagate = True


def english_lang():
    return base.read_lang("en_us")


@pytest.fixture(scope="module")
def english():
    return english_lang()


def run_ask(source, content):
    games_ai.ask_ai.original(source, {"content": content})


def wait_for(condition, timeout=10.0):
    deadline = threading.Event()
    waited = 0.0
    while not condition() and waited < timeout:
        deadline.wait(0.01)
        waited += 0.01
    return condition()


def test_a_question_asked_during_a_round_is_merged_after_it(env, monkeypatch):
    lang = env.server.lang
    provider = Provider()
    monkeypatch.setattr(chat_param, "response_chat", provider)
    first = base.FakeSource(env.server, who="Steve")
    second = base.FakeSource(env.server, who="Steve")

    first_thread = threading.Thread(target=run_ask, args=(first, "first question"))
    first_thread.start()
    assert provider.entered.wait(10), "the first round never reached the provider"
    conversation = games_ai.all_chat_param["Steve"]

    second_thread = threading.Thread(target=run_ask, args=(second, "second question"))
    second_thread.start()
    assert wait_for(lambda: len(conversation._pending_asks) == 1), \
        "the question asked during the round is queued instead of starting a second round"
    assert conversation.try_claim_round() is False, \
        "a second round cannot claim the conversation while the first one owns it"

    provider.release.set()
    first_thread.join(15)
    second_thread.join(15)
    assert not first_thread.is_alive() and not second_thread.is_alive(), "both asks finished"

    assert len(provider.calls) == 2, "one merged follow-up round ran (two provider calls in total)"
    question_lines = [str(message.get("content")) for message in conversation.response_list
                      if isinstance(message, dict) and message.get("role") == "user"]
    first_at = next(i for i, line in enumerate(question_lines) if "first question" in line)
    second_at = next(i for i, line in enumerate(question_lines) if "second question" in line)
    assert first_at < second_at, "the merged round sends the questions in arrival order"

    thinking = str(lang["games_ai"]["user_message"]["thinking"])
    assert second.text().count(thinking) == 1, "the queued asker is told it is waiting"
    assert "ANSWER 1" in first.text(), "the owner sees the first answer"
    assert "ANSWER 2" in first.text(), "the merged answer streams to the round owner"
    assert "ANSWER" not in second.text(), "the queued asker does not receive the merged answer"
    assert conversation.is_round_active() is False, "the ownership is released at the end"


def test_stop_keeps_queued_questions_and_sends_them_afterwards(env, monkeypatch):
    lang = env.server.lang
    provider = Provider()
    monkeypatch.setattr(chat_param, "response_chat", provider)
    first = base.FakeSource(env.server, who="Steve")
    second = base.FakeSource(env.server, who="Steve")

    first_thread = threading.Thread(target=run_ask, args=(first, "long question"))
    first_thread.start()
    assert provider.entered.wait(10)
    conversation = games_ai.all_chat_param["Steve"]

    second_thread = threading.Thread(target=run_ask, args=(second, "queued while stopping"))
    second_thread.start()
    assert wait_for(lambda: len(conversation._pending_asks) == 1)
    assert conversation.request_stop() is True

    provider.release.set()
    first_thread.join(15)
    second_thread.join(15)
    assert not first_thread.is_alive() and not second_thread.is_alive()

    assert len(provider.calls) == 2, "the kept question still gets its merged round after the stop"
    question_lines = [str(message.get("content")) for message in conversation.response_list
                      if isinstance(message, dict) and message.get("role") == "user"]
    assert any("queued while stopping" in line for line in question_lines), \
        "!!ask stop keeps the queued question instead of dropping it"
    assert "ANSWER 2" in first.text()


def test_response_ai_setup_failure_does_not_leave_the_conversation_running(env, monkeypatch):
    source = base.FakeSource(env.server, who="Steve")
    conversation = ChatParam(env.server, model_id=MODEL)

    def explode():
        raise RuntimeError("setup broke")

    monkeypatch.setattr(conversation, "_inject_time", explode)
    with pytest.raises(RuntimeError):
        conversation.response_ai(source)
    assert conversation.is_stopped.is_set(), \
        "a failing setup releases the round state (is_stopped set) instead of leaving it running"
    assert conversation.try_claim_round() is True, "the conversation can be used again"
    conversation.release_round()


def test_ask_ai_reports_an_unexpected_setup_failure(env, monkeypatch):
    source = base.FakeSource(env.server, who="Steve")

    class BrokenChatParam(ChatParam):
        def __init__(self, *args, **kwargs):
            raise RuntimeError("cannot build the conversation")

    monkeypatch.setattr(games_ai, "ChatParam", BrokenChatParam)
    run_ask(source, "hello")                 # must not raise out of the thread body
    assert "[GamesAI]" in source.text() and MODEL in source.text(), \
        "the player gets the localized ask error instead of silence"
