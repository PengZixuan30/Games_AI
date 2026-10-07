"""Conversations are stored in their own table and must survive an unload / restart / update.

Everything here runs against a throwaway SQLite file: the plugin's real data folder is never
touched. The point of the suite is the promise the feature makes -- a conversation that a player
had before a reload, an update or a restart is still there afterwards, ``!!data`` is not mixed
into it, and one unreadable row can never stop the plugin from loading.
"""
import json
import logging
import os
from types import SimpleNamespace

import pytest
from openai.types.chat.chat_completion_message import ChatCompletionMessage

import games_ai
from games_ai.chat_param import ChatParam, json_to_message, message_to_json
from games_ai.config import plugin_config
from games_ai.database import ChatHistoryStore, PublicDatabase


class FakeServer:
    """What ChatParam asks of a server: a logger and the localized strings."""

    def __init__(self):
        self.logger = logging.getLogger("gamesai_probe")

    def rtr(self, key, **kwargs):
        return key if not kwargs else key + "|" + json.dumps(kwargs, ensure_ascii=False, sort_keys=True)


class FakeSource:
    def __init__(self, name="Steve", level=3, server=None):
        self.player = name
        self.level = level
        self.server = server
        self.shown = []

    @property
    def is_player(self):
        return True

    def get_permission_level(self):
        return self.level

    def get_server(self):
        return self.server

    def reply(self, message, **kwargs):
        self.shown.append(str(message))


def model_entry():
    return {"api_key": "probe-key", "base_url": "http://127.0.0.1:9/v1", "ai_model": "probe-model",
            "ai_name": "[AI]", "prompt": "probe prompt"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """One plugin load against a database file of this test's own temp folder."""
    db = os.path.join(str(tmp_path), "public_database.db")
    server = FakeServer()
    null_handler = logging.NullHandler()
    server.logger.addHandler(null_handler)

    monkeypatch.setattr(games_ai, "all_chat_param", {}, raising=False)
    monkeypatch.setattr(games_ai, "_history_frozen", False, raising=False)
    monkeypatch.setattr(games_ai, "_cross_server", None, raising=False)
    monkeypatch.setattr(games_ai.logger, "_server", server, raising=False)
    monkeypatch.setattr(plugin_config, "all_ai", {"main": model_entry(), "other": model_entry()})
    monkeypatch.setattr(plugin_config, "skills_description", {})
    monkeypatch.setattr(plugin_config, "debug_mode", False)
    monkeypatch.setattr(plugin_config, "data_path", db)
    monkeypatch.setattr(plugin_config, "cross_server_name", "probe-node")
    monkeypatch.setattr(plugin_config, "default_ai", "main")
    monkeypatch.setattr(plugin_config, "allow_permission", 3)
    monkeypatch.setattr(plugin_config, "prefix", "[GamesAI]")
    try:
        yield SimpleNamespace(db=db, server=server)
    finally:
        server.logger.removeHandler(null_handler)


def new_param(env, model_id="main"):
    return ChatParam(env.server, model_id=model_id)


def store(env):
    return ChatHistoryStore(env.db)


def sdk_message():
    return ChatCompletionMessage.model_validate({
        "role": "assistant", "content": "let me check", "reasoning_content": "because",
        "tool_calls": [{"id": "call_1", "type": "function",
                        "function": {"name": "get_online_players", "arguments": "{}"}}],
    })


def test_the_store_is_a_table_of_the_public_database(env):
    PublicDatabase(env.db).write_data("shared", "value")

    assert PublicDatabase(env.db).read_data("shared") == "value", \
        "the public data survives a history write"
    assert PublicDatabase(env.db).get_all_key() == ["shared"], \
        f"the public database lists only its own key: {PublicDatabase(env.db).get_all_key()}"

    store(env).save("Steve", 1, "main", 111, 0, "{}")

    assert PublicDatabase(env.db).get_all_key() == ["shared"], \
        f"the history is not listed as public data: {PublicDatabase(env.db).get_all_key()}"

    rows = store(env).load_all()
    assert len(rows) == 1 and rows[0]["user"] == "Steve", f"the row is readable: {rows}"
    assert (rows[0]["format"], rows[0]["model_id"], rows[0]["saved_at"]) == (1, "main", 111), \
        f"...with its format, model and time: {rows[0]}"

    store(env).save("Steve", 1, "other", 222, 4, "{\"x\": 1}")

    rows = store(env).load_all()
    assert len(rows) == 1 and rows[0]["saved_at"] == 222, \
        f"saving again overwrites the same row: {rows}"
    assert json.loads(rows[0]["payload"]) == {"x": 1}, \
        f"...and keeps the new payload: {rows[0]['payload']}"

    store(env).delete("Steve")
    assert store(env).load_all() == [], "delete removes the row"

    store(env).save("A", 1, "main", 1, 0, "{}")
    store(env).save("B", 1, "main", 1, 0, "{}")
    store(env).delete_all()
    assert store(env).load_all() == [], "delete_all removes every row"
    assert PublicDatabase(env.db).read_data("shared") == "value", \
        f"the public data is still intact: {PublicDatabase(env.db).data_list()}"


def test_what_one_message_looks_like_on_disk():
    flat = message_to_json(sdk_message())

    assert isinstance(flat, dict) and flat["role"] == "assistant", \
        f"the SDK object becomes a plain dict: {flat}"
    assert flat["tool_calls"][0]["id"] == "call_1" \
        and flat["tool_calls"][0]["function"]["name"] == "get_online_players", \
        f"its tool call is kept: {flat}"
    assert flat.get("reasoning_content") == "because", f"reasoning_content is kept: {flat}"
    assert json.loads(json.dumps(flat)) == flat, "...and the whole thing is JSON"
    assert message_to_json({"role": "user", "content": "hi"}) == {"role": "user", "content": "hi"}, \
        "a dict message passes through"
    assert message_to_json({"role": "tool", "content": "42", "tool_call_id": "call_1"}) \
        == {"role": "tool", "content": "42", "tool_call_id": "call_1"}, \
        "a tool result keeps its call id"
    assert json_to_message({"role": "boss", "content": "hi"}) is None, \
        "an unknown role is refused on the way back"
    assert json_to_message("hello") is None and json_to_message(None) is None, \
        "a non-message is refused"
    assert json_to_message({"role": "tool", "content": "42"}) is None, \
        "a tool result without a call id is refused"
    assert json_to_message({"role": "user", "content": "hi"}) == {"role": "user", "content": "hi"}, \
        "a valid message comes back"


def test_a_round_trip_through_the_database_keeps_everything(env):
    sdk = sdk_message()
    param = new_param(env)
    param.add_to_response_list("user", "hello")
    param.response_list.append(sdk)
    param.add_to_response_list("tool", "2 players", args={"tool_call_id": "call_1"})
    param.forced_add_to_response_list("user", "queued while running")
    param._total_prompt_tokens = 1200
    param._total_completion_tokens = 340
    param._total_cached_tokens = 900
    param._total_reasoning_tokens = 12
    param._rounds_since_time = 7
    games_ai.all_chat_param["Steve"] = param
    games_ai._save_history("Steve", param)

    rows = store(env).load_all()
    assert len(rows) == 1 and rows[0]["user"] == "Steve", f"the conversation was stored: {rows}"
    assert rows[0]["format"] == games_ai._HISTORY_FORMAT, \
        f"...under the current format: {rows[0]}"
    assert rows[0]["model_id"] == "main", f"...with its model: {rows[0]}"
    assert rows[0]["rounds_since_time"] == 7, f"...and its round counter: {rows[0]}"

    games_ai.all_chat_param.clear()
    games_ai._restore_all_histories(env.server)
    back = games_ai.all_chat_param.get("Steve")

    assert back is not None, \
        f"the conversation is back in memory after a 'restart': {list(games_ai.all_chat_param)}"
    assert [m["role"] for m in back.response_list] == ["user", "assistant", "tool"], \
        f"...with every message: {[m['role'] for m in back.response_list]}"
    assert back.response_list[1]["tool_calls"][0]["id"] == "call_1", \
        f"...with the tool call intact: {back.response_list[1]}"
    assert back.response_list[1].get("reasoning_content") == "because", \
        f"...with reasoning_content intact: {back.response_list[1]}"
    assert back.response_list[2]["tool_call_id"] == "call_1", \
        f"...with the tool result linked to it: {back.response_list[2]}"
    assert [m["content"] for m in back.response_queue] == ["queued while running"], \
        f"...with the queued message: {back.response_queue}"
    assert (back._total_prompt_tokens, back._total_completion_tokens, back._total_cached_tokens,
            back._total_reasoning_tokens) == (1200, 340, 900, 12), \
        "...and with the lifetime counters: {}".format(
            (back._total_prompt_tokens, back._total_completion_tokens))
    assert back._rounds_since_time == 7, f"...and the round counter: {back._rounds_since_time}"
    assert back.get_model_id == "main", f"...on the stored model: {back.get_model_id}"
    assert back.is_stopped.is_set(), "a restored conversation is idle"


def test_an_empty_conversation_has_no_row(env):
    empty = new_param(env)
    games_ai.all_chat_param["Ghost"] = empty
    games_ai._save_history("Ghost", empty)

    assert all(row["user"] != "Ghost" for row in store(env).load_all()), \
        f"nothing was stored for it: {store(env).load_all()}"

    store(env).save("Ghost", 1, "main", 1, 0,
                    json.dumps({"messages": [{"role": "user", "content": "x"}]}))
    empty.response_list.clear()
    games_ai._save_history("Ghost", empty)

    assert all(row["user"] != "Ghost" for row in store(env).load_all()), \
        f"an existing row is dropped when the conversation is emptied: {store(env).load_all()}"


def test_a_broken_row_is_skipped_never_fatal(env):
    healthy = new_param(env)
    healthy.add_to_response_list("user", "still here")
    games_ai.all_chat_param["Steve"] = healthy
    games_ai._save_history("Steve", healthy)

    store(env).save("Bad1", 99, "main", 1, 0, json.dumps({"messages": []}))
    store(env).save("Bad2", 1, "main", 1, 0, "{not json")
    store(env).save("Bad3", 1, "main", 1, 0,
                    json.dumps({"messages": [{"role": "boss", "content": "hi"}]}))
    store(env).save("Gone", 1, "deleted-model", 1, 0,
                    json.dumps({"messages": [{"role": "user", "content": "still here"}]}))
    games_ai.all_chat_param.pop("Steve", None)
    games_ai._restore_all_histories(env.server)

    assert "Bad1" not in games_ai.all_chat_param, "a newer format is skipped"
    assert "Bad2" not in games_ai.all_chat_param, "unreadable JSON is skipped"
    assert "Bad3" not in games_ai.all_chat_param, \
        "a row with only unusable messages counts as empty"
    assert all(row["user"] != "Bad3" for row in store(env).load_all()), \
        f"...and its row is removed: {store(env).load_all()}"

    fallen = games_ai.all_chat_param.get("Gone")
    assert fallen is not None and fallen.get_model_id == plugin_config.default_ai, \
        "a removed model falls back to the default AI: {}".format(
            None if fallen is None else fallen.get_model_id)
    assert fallen is not None and fallen.response_list[0]["content"] == "still here", \
        "...and its conversation is kept"
    assert "Steve" in games_ai.all_chat_param, "the healthy rows came back too"


def test_the_usage_view_survives_the_restart_too(env):
    source_param = new_param(env)
    source_param.add_to_response_list("user", "how much context am I holding?")
    source_param.add_to_response_list("assistant", "let me count")
    source_param._last_usage = {"prompt_tokens": 1234, "completion_tokens": 56,
                                "total_tokens": 1290,
                                "prompt_tokens_details": {"cached_tokens": 900},
                                "completion_tokens_details": {"reasoning_tokens": 7}}
    source_param._last_prompt_tokens = 1234
    source_param._round_max_total_tokens = 1290
    source_param._round_prompt_tokens = 1300
    source_param._round_cached_tokens = 900
    source_param._round_reasoning_tokens = 7
    source_param._last_compress = {"time": "12:00:00", "rounds": 2, "before": 9, "after": 5,
                                   "ok": True, "forced": False}
    source_param._total_prompt_tokens = 4321
    games_ai.all_chat_param["Usage"] = source_param
    games_ai._save_history("Usage", source_param)

    stored = json.loads([row for row in store(env).load_all()
                         if row["user"] == "Usage"][0]["payload"])
    assert {"messages", "queue", "totals", "rounds_since_time"} <= set(stored), \
        f"the record still carries the keys an older build reads: {sorted(stored)}"
    assert (stored["usage"]["last_prompt"] == 1234
            and stored["usage"]["round_max_total"] == 1290
            and stored["usage"]["round_prompt"] == 1300
            and stored["usage"]["round_cached"] == 900
            and stored["usage"]["round_reasoning"] == 7
            and stored["usage"]["last_usage"]["prompt_tokens_details"]["cached_tokens"] == 900), \
        f"...plus this round's counters and the last usage dict: {stored.get('usage')}"
    assert stored["last_compress"]["rounds"] == 2, \
        f"...and the last compression: {stored.get('last_compress')}"

    games_ai.all_chat_param.clear()
    games_ai._restore_all_histories(env.server)
    usage_back = games_ai.all_chat_param.get("Usage")

    assert usage_back is not None, "the conversation came back"
    assert usage_back is not None and usage_back._last_prompt_tokens == 1234, \
        "the real input size of the last request came back"
    assert (usage_back._round_max_total_tokens, usage_back._round_prompt_tokens,
            usage_back._round_cached_tokens, usage_back._round_reasoning_tokens) \
        == (1290, 1300, 900, 7), \
        "this round's counters came back: {}".format(
            (usage_back._round_max_total_tokens, usage_back._round_prompt_tokens))
    assert usage_back._last_usage == source_param._last_usage, \
        f"the raw usage dict came back (the cache hit share): {usage_back._last_usage}"
    assert usage_back._last_compress == source_param._last_compress, \
        f"the last compression came back: {usage_back._last_compress}"
    assert usage_back._total_prompt_tokens == 4321, "the lifetime totals still came back"
    assert usage_back._last_estimate > 0 and usage_back._last_base_estimate > 0, \
        "the held context is recomputed instead of restored: {}".format(
            (usage_back._last_estimate, usage_back._last_base_estimate))
    assert "games_ai.context_view.card_usage_none" not in usage_back.context_view()[1][0], \
        "`!!ask context` no longer claims there was never a request: {}".format(
            usage_back.context_view()[1][0])
    assert (usage_back.context_usage()["estimate"] > 0
            and usage_back.context_usage()["round_prompt"] == 1300), \
        f"the server-wide view sees the held context again: {usage_back.context_usage()}"
    assert games_ai.aggregate_context_usage()[1]["estimate"] > 0, \
        f"...and the aggregate picks it up: {games_ai.aggregate_context_usage()[1]}"


def test_a_record_from_before_the_usage_block_still_restores(env):
    games_ai.all_chat_param.clear()
    store(env).delete_all()
    store(env).save("Old", 1, "main", 1, 0, json.dumps({
        "messages": [{"role": "user", "content": "older build, no usage keys"}],
        "queue": [], "totals": {"prompt": 10}, "rounds_since_time": 1}))

    games_ai._restore_all_histories(env.server)
    old_back = games_ai.all_chat_param.get("Old")

    assert old_back is not None, "the old conversation is kept"
    assert old_back is not None and old_back._total_prompt_tokens == 10, \
        "its lifetime total is kept"
    assert (old_back is not None and old_back._last_usage is None
            and old_back._last_prompt_tokens == 0 and old_back._last_compress is None), \
        "its missing counters read as zero"
    assert old_back is not None and old_back._last_estimate > 0, \
        "its held context is still recomputed"


def test_a_provider_value_that_cannot_be_encoded_is_not_a_risk(env):
    odd = new_param(env)
    odd.add_to_response_list("user", "hi")
    odd._last_usage = {"prompt_tokens": 1, "weird": {1, 2}, "obj": object()}
    odd._last_compress = {"rounds": 1}
    encoded = json.dumps(odd.to_record(), ensure_ascii=False)

    assert json.loads(encoded)["usage"]["last_usage"]["weird"] == [1, 2], \
        f"the record is JSON even when the provider value is not: {encoded[:120]}"

    wrong = new_param(env)
    wrong.restore({"messages": [{"role": "user", "content": "kept"}], "totals": ["nope"],
                   "usage": "nope", "last_compress": 5})

    assert (len(wrong.response_list) == 1 and wrong._total_prompt_tokens == 0
            and wrong._last_compress is None), \
        f"a wrong-typed block costs the counters, not the conversation: {wrong.response_list}"


def test_the_last_round_before_an_unload_is_already_on_disk(env, monkeypatch):
    games_ai.all_chat_param.clear()
    store(env).delete_all()
    writer = new_param(env)
    games_ai.all_chat_param["Writer"] = writer

    def fake_round(source, data=None):
        writer.add_to_response_list("user", "the very last question")

    writer.response_ai = fake_round
    games_ai._run_ai_round(FakeSource("Writer", server=env.server), writer, None, "main")

    assert len(store(env).load_all()) == 1 and store(env).load_all()[0]["user"] == "Writer", \
        f"_run_ai_round stores the finished round: {store(env).load_all()}"

    def failing_round(source, data=None):
        raise RuntimeError("boom")

    writer.response_ai = failing_round
    escaped = None
    try:
        games_ai._run_ai_round(FakeSource("Writer", server=env.server), writer, None, "main")
    except Exception as exc:
        escaped = exc
    assert escaped is None, f"a failing round does not escape: {escaped!r}"
    assert len(store(env).load_all()) == 1, \
        f"a failed round is stored as well: {store(env).load_all()}"

    monkeypatch.setattr(games_ai, "_history_frozen", True)
    writer.add_to_response_list("user", "written after unload")
    games_ai._save_history("Writer", writer)

    assert "written after unload" not in store(env).load_all()[0]["payload"], \
        "an unloaded instance stores nothing any more: {}".format(
            store(env).load_all()[0]["payload"])


def test_clear_and_clearall_reach_the_store(env):
    writer = new_param(env)
    writer.add_to_response_list("user", "written before the clear")
    games_ai.all_chat_param["Writer"] = writer
    games_ai._save_history("Writer", writer)

    games_ai.clear_history(FakeSource("Writer", server=env.server), {})

    assert store(env).load_all() == [], f"clear removes the row: {store(env).load_all()}"
    assert "Writer" not in games_ai.all_chat_param, "...and the object"

    owner = new_param(env)
    owner.add_to_response_list("user", "mine")
    games_ai.all_chat_param["Owner"] = owner
    games_ai._save_history("Owner", owner)
    games_ai.clear_history_all(FakeSource("Admin", level=4, server=env.server), {})

    assert store(env).load_all() == [], f"clearall removes every row: {store(env).load_all()}"
    assert games_ai.all_chat_param == {}, f"...and every object: {games_ai.all_chat_param}"

    new_param(env).add_to_response_list("user", "unrestorable")
    store(env).save("Owner2", 99, "main", 1, 0, "{}")
    games_ai.clear_history(FakeSource("Owner2", server=env.server), {})

    assert all(row["user"] != "Owner2" for row in store(env).load_all()), \
        f"a row that could not be restored is still droppable: {store(env).load_all()}"
