"""P6: ``!!ask stop`` keeps the round's history, and ``!!gamesai clear <name>`` drops one player's.

Two promises are pinned here:

* ``!!ask stop`` stops the running round at its next checkpoint but does **not** throw away what
  the round already wrote -- the question, the injected notes and every finished tool call stay.
  Only a trailing tool call whose result never arrived is dropped (and an incomplete batch is
  removed as a whole, because a half-answered tool-call group cannot be sent to a provider).
  Queued ``!!ask -f`` messages are no longer discarded either: the next round merges them.
* ``!!gamesai clear <name>`` is the management form of ``!!gamesai clear``: gated by the configured
  permission level, it stops a round the target still has in flight, removes the conversation from
  memory and deletes the stored row -- and the detached round must not write that history back.
"""
import json
import logging
import os
import re
from types import SimpleNamespace

import pytest
from mcdreforged.command.builder.nodes.basic import ArgumentNode, Literal

import games_ai
from _helpers.paths import DOCS_DIR, LANG_DIR, REPO_ROOT
from _helpers.pkg import module_text, package_text
from games_ai.chat_param import ChatParam
from games_ai.config import plugin_config
from games_ai.database import ChatHistoryStore


class FakeServer:
    def __init__(self):
        self.logger = logging.getLogger("gamesai_probe_stop")

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
    monkeypatch.setattr(games_ai.logger, "_server", server, raising=False)
    monkeypatch.setattr(plugin_config, "all_ai", {"main": model_entry()})
    monkeypatch.setattr(plugin_config, "skills_description", {})
    monkeypatch.setattr(plugin_config, "debug_mode", False)
    monkeypatch.setattr(plugin_config, "data_path", db)
    monkeypatch.setattr(plugin_config, "default_ai", "main")
    monkeypatch.setattr(plugin_config, "allow_permission", 3)
    monkeypatch.setattr(plugin_config, "prefix", "[GamesAI]")
    try:
        yield SimpleNamespace(db=db, server=server)
    finally:
        server.logger.removeHandler(null_handler)


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def store(env):
    return ChatHistoryStore(env.db)


def new_param(env):
    return ChatParam(env.server, model_id="main")


def tool_call(call_id="call_1", name="get_online_players"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": "{}"}}


def texts(param):
    return [str(m.get("content")) if isinstance(m, dict) else str(m) for m in param.response_list]


def test_the_source_carries_the_new_rules():
    package_src = package_text()
    init_src = module_text("__init__")
    param_src = module_text("chat_param")
    help_src = module_text("help")

    assert "_truncate_interrupted_step" not in param_src, "the truncating helper is gone"
    assert "def _drop_unanswered_tool_call" in param_src, "the tool-call helper is there"

    request_stop_src = param_src.split("def request_stop", 1)[1].split("def begin_round", 1)[0]
    assert "response_queue.clear()" not in request_stop_src, \
        f"request_stop no longer clears the queue: {request_stop_src[:400]}"
    assert "is no longer the registered" in package_src, "the save guard is in _save_history"
    assert "'!!gamesai clear <name>'" in init_src and "clear_history_named" in init_src, \
        "the named clear is registered"
    assert re.search(r"'!!gamesai clear <name>',\s*(?:[A-Za-z_]\w*\.)?_route\(ROUTE_SERVER,\s*"
                     r"(?:[A-Za-z_]\w*\.)?clear_history_named\)", init_src) is not None, \
        "the named clear is routed like the bare one"
    assert "clear_other_help" in help_src, \
        "the help lists the named form for permitted sources"


def test_ask_stop_keeps_what_the_round_wrote(env):
    question = new_param(env)
    question.add_to_response_list("user", "are you there?")

    unanswered = new_param(env)
    unanswered.add_to_response_list("user", "are you there?")
    unanswered.add_to_response_list("assistant", "let me check", args={"tool_calls": [tool_call()]})

    assert (unanswered._drop_unanswered_tool_call(), len(unanswered.response_list)) == (1, 1), \
        f"an unanswered tool call is dropped: {texts(unanswered)}"
    assert texts(unanswered) == ["are you there?"], f"...and the question stays: {texts(unanswered)}"
    assert question._drop_unanswered_tool_call() == 0 and len(question.response_list) == 1, \
        "nothing else is dropped when there is no tool call"

    complete = new_param(env)
    complete.add_to_response_list("user", "how many players?")
    complete.add_to_response_list("assistant", "checking", args={"tool_calls": [tool_call()]})
    complete.add_to_response_list("tool", "3", args={"tool_call_id": "call_1"})
    complete.add_to_response_list("assistant", "there are 3 players")
    complete._abort_interrupted_round()

    assert len(complete.response_list) == 4 and complete.response_list[-1]["role"] == "assistant", \
        f"a finished tool call and the answer stay: {texts(complete)}"
    assert complete.is_stopped.is_set(), "the round is marked stopped"

    late = new_param(env)
    late.add_to_response_list("user", "one more question")
    late.add_to_response_list("assistant", "the answer that had already arrived")
    late._abort_interrupted_round()

    assert texts(late)[-1] == "the answer that had already arrived", \
        f"an answer that already arrived is kept: {texts(late)}"

    partial = new_param(env)
    partial.add_to_response_list("user", "do two things")
    partial.add_to_response_list("assistant", "on it",
                                 args={"tool_calls": [tool_call("call_1"), tool_call("call_2")]})
    partial.add_to_response_list("tool", "first result", args={"tool_call_id": "call_1"})
    partial._abort_interrupted_round()

    assert texts(partial) == ["do two things"], \
        f"a half-answered batch is dropped as a whole: {texts(partial)}"
    assert all(m.get("role") != "tool" for m in partial.response_list), \
        f"...so no orphan tool message survives: {partial.response_list}"


def test_ask_stop_is_announced_honestly(env):
    running = new_param(env)
    running.add_to_response_list("user", "a question with a running round")
    running.add_to_response_list("assistant", "partial answer")
    running.is_stopped.clear()
    games_ai.all_chat_param["Steve"] = running
    running.forced_add_to_response_list("user", "a queued forced message")
    source = FakeSource("Steve", server=env.server)
    games_ai.ask_stop(source, {})

    assert any("games_ai.user_message.stop_round" in line for line in source.shown), \
        f"the player is told the round stopped: {source.shown}"
    assert all("delete" not in line for line in source.shown), \
        f"...and not that a step was deleted: {source.shown}"
    assert [m["content"] for m in running.response_queue] == ["a queued forced message"], \
        f"the queue survives the stop: {running.response_queue}"

    running._abort_interrupted_round()

    assert texts(running)[:2] == ["a question with a running round", "partial answer"], \
        f"the round's history survives the stop: {texts(running)}"


def test_gamesai_clear_named(env):
    steve = new_param(env)
    steve.add_to_response_list("user", "steve's secret question")
    games_ai.all_chat_param["Steve"] = steve
    games_ai._save_history("Steve", steve)

    assert len(store(env).load_all()) == 1, \
        f"the conversation is stored first: {store(env).load_all()}"

    low = FakeSource("Alex", level=2, server=env.server)
    games_ai.clear_history_named(low, {"name": "Steve"})

    assert any("games_ai.no_permission" in line for line in low.shown), \
        f"a player below the configured level is refused: {low.shown}"
    assert "Steve" in games_ai.all_chat_param and len(store(env).load_all()) == 1, \
        f"...and nothing was cleared: {store(env).load_all()}"

    admin = FakeSource("Admin", level=3, server=env.server)
    games_ai.clear_history_named(admin, {"name": "Steve"})

    assert "Steve" not in games_ai.all_chat_param, \
        f"the permitted source clears the conversation: {list(games_ai.all_chat_param)}"
    assert store(env).load_all() == [], f"...and the stored row: {store(env).load_all()}"
    assert any("games_ai.clear_history_message.success_other" in line and "Steve" in line
               for line in admin.shown), f"...and is told so: {admin.shown}"


def test_clearing_a_player_whose_round_is_still_running(env):
    busy = new_param(env)
    busy.add_to_response_list("user", "a running question")
    busy.is_stopped.clear()
    games_ai.all_chat_param["Busy"] = busy
    games_ai._save_history("Busy", busy)
    admin2 = FakeSource("Admin", level=4, server=env.server)
    games_ai.clear_history_named(admin2, {"name": "Busy"})

    assert busy.stop_requested(), "the round was asked to stop"
    assert "Busy" not in games_ai.all_chat_param, "the conversation is gone from memory"
    assert store(env).load_all() == [], f"...and from the store: {store(env).load_all()}"
    assert any("games_ai.clear_history_message.success_other_stopped" in line
               for line in admin2.shown), f"the reply says the round was stopped: {admin2.shown}"

    games_ai._save_history("Busy", busy)

    assert store(env).load_all() == [], \
        f"the detached round cannot write the history back: {store(env).load_all()}"


def test_names_with_nothing_to_clear(env):
    games_ai._save_history("Ghost", new_param(env))
    admin3 = FakeSource("Admin", level=4, server=env.server)
    games_ai.clear_history_named(admin3, {"name": "Ghost"})

    assert any("games_ai.clear_history_message.no_history_other" in line
               for line in admin3.shown), f"an unknown name is reported honestly: {admin3.shown}"

    orphan = new_param(env)
    games_ai.all_chat_param["Orphan"] = orphan
    store(env).save("Orphan", 99, "main", 1, 0, "{}")
    del games_ai.all_chat_param["Orphan"]
    admin4 = FakeSource("Admin", level=4, server=env.server)
    games_ai.clear_history_named(admin4, {"name": "Orphan"})

    assert store(env).load_all() == [], \
        f"a row that could not be restored is still droppable: {store(env).load_all()}"
    assert any("success_other" in line for line in admin4.shown), \
        f"...and that counts as cleared: {admin4.shown}"


def test_the_bare_form_keeps_its_own_meaning(env):
    own = new_param(env)
    own.add_to_response_list("user", "my own question")
    games_ai.all_chat_param["Owner"] = own
    games_ai._save_history("Owner", own)
    owner_source = FakeSource("Owner", level=0, server=env.server)
    games_ai.clear_history(owner_source, {})

    assert any("games_ai.clear_history_message.success" in line for line in owner_source.shown), \
        f"a player may clear their own history without any level: {owner_source.shown}"
    assert store(env).load_all() == [], f"...and it is gone: {store(env).load_all()}"

    again = FakeSource("Owner", level=0, server=env.server)
    games_ai.clear_history(again, {})

    assert any("games_ai.clear_history_message.no_history" in line for line in again.shown), \
        f"clearing nothing says nothing was there: {again.shown}"


def test_the_pages_describe_the_new_behaviour():
    old_stop_phrases = {
        "en_us": ("interrupted step is deleted", "interrupted step dropped",
                  "queued `!!ask -f` messages are discarded"),
        "zh_cn": ("删除未完成的一步", "丢弃排队的 `!!ask -f`"),
        "zh_tw": ("刪除未完成的一步", "丟棄排隊的 `!!ask -f`"),
    }
    for lang, phrases in old_stop_phrases.items():
        page = read(os.path.join(DOCS_DIR, lang, "ai-request-pipeline.md"))
        stale = [p for p in phrases if p in page]
        assert not stale, f"{lang}: the stop section no longer promises a deletion: {stale}"

        readme = read(os.path.join(REPO_ROOT, "README.md" if lang == "en_us" else
                                   ("README.zh-CN.md" if lang == "zh_cn" else "README.zh-TW.md")))
        assert "ask stop" in readme and "discarded" not in readme.split("ask stop", 1)[1][:400], \
            f"{lang}: the README stop row tells the same story"

    for lang in ("en_us", "zh_cn", "zh_tw"):
        changelog = read(os.path.join(DOCS_DIR, lang, "changelog.md"))
        section = changelog.split("## Version 0.8.0", 1)[1].split("## Version 0.7.3", 1)[0]
        assert "clear <name>" in section, \
            f"{lang}: the 0.8.0 notes mention the named clear"
        assert (("keeps what the round wrote" in section)
                or ("保留" in section and "历史" in section)
                or ("保留" in section and "歷史" in section)), \
            f"{lang}: the 0.8.0 notes mention the kept history: {section[:200]}"


@pytest.mark.parametrize("lang", ["en_us", "zh_cn", "zh_tw"])
def test_the_translations_say_the_same_thing(lang):
    text = read(os.path.join(LANG_DIR, lang + ".yml"))

    for key in ("clear_other_help", "success_other", "success_other_stopped",
                "no_history_other", "name_required"):
        assert (key + ":") in text, f"{lang}: {key} exists"

    stop_line = next((l for l in text.splitlines() if "stop_round:" in l), "")
    assert (stop_line and "delet" not in stop_line and "删除" not in stop_line
            and "刪除" not in stop_line), \
        f"{lang}: stop_round no longer promises a deletion: {stop_line}"


class StubServer:
    def __init__(self):
        self.roots = []

    def register_command(self, node):
        self.roots.append(node)


def literal_child(node, name):
    for child in node.get_children():
        if isinstance(child, Literal) and name in child.literals:
            return child
    return None


def test_the_command_tree_really_parses_both_forms(env):
    stub = StubServer()
    config = {"prefix": "[GamesAI]", "permission": 3, "all_ai": {}, "default_ai": "",
              "mineflayer_bot": {}, "websocket": {}}
    built = True
    build_error = None
    try:
        games_ai.register_commands(stub, config)
    except Exception as error:
        built = False
        build_error = error

    assert built and len(stub.roots) >= 1, \
        f"the whole command tree builds and registers: {len(stub.roots)} ({build_error!r})"

    root = next((node for node in stub.roots
                 if "!!gamesai" in getattr(node, "literals", set())), None)
    assert root is not None, "!!gamesai is a root literal"

    clear = literal_child(root, "clear") if root is not None else None
    assert clear is not None, "!!gamesai clear is there"
    assert root is not None and literal_child(root, "clearall") is not None, \
        "!!gamesai clearall is still its own command"

    names = [child.get_name() for child in clear.get_children()
             if isinstance(child, ArgumentNode)] if clear is not None else []
    assert names == ["name"], f"!!gamesai clear takes a <name> argument: {names}"
    assert clear is not None and clear._callback is not None, \
        f"the bare clear keeps running without an argument: {getattr(clear, '_callback', None)}"
