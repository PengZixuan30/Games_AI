"""One user's assistant can hand a message to another user's conversation -- and only that.

The tool is the plugin's only cross-user write, so the suite pins every rule around it: the
target must already have a conversation, the sender may only write to the same or a lower
permission level, the console conversation keeps the console's level without ever being looked
up as a player name, and a message that arrives while the recipient is mid-round goes through
the queue without a single message being lost.
"""
import json
import logging
import os
import threading
import time
from types import SimpleNamespace

import pytest

import games_ai
from games_ai.chat_param import ChatParam
from games_ai.config import plugin_config
from games_ai.games_ai_tool import (get_hub_tool_schemas_for_perm, get_local_tool_schemas_for_perm,
                                    get_tool_handler)

TOOL = "send_message_to_player_ai"
CONSOLE = games_ai.CONSOLE_ACCESS_KEY


class FakeOnline:
    def __init__(self, players):
        self.players = list(players)

    def get_player_list(self):
        return list(self.players)


class FakeServer:
    def __init__(self, levels=None, online=None, with_api=True):
        self.logger = logging.getLogger("gamesai_probe")
        self.levels = dict(levels or {})
        self.online = online
        self.with_api = with_api
        self.asked = []
        self.told = []

    def rtr(self, key, **kwargs):
        return key if not kwargs else key + "|" + json.dumps(kwargs, ensure_ascii=False, sort_keys=True)

    def get_permission_level(self, name):
        self.asked.append(name)
        return self.levels.get(name, 1)

    def get_plugin_instance(self, plugin_id):
        if plugin_id == "online_player_api" and self.with_api:
            return FakeOnline(self.online or [])
        return None

    def tell(self, player, text):
        self.told.append((player, str(text)))


class FakeSource:
    def __init__(self, name="Steve", level=3, server=None, console=False, origin=""):
        self.player = name
        self.level = level
        self.server = server
        self.console = console
        if origin:
            self.origin = origin
        self.shown = []

    @property
    def is_player(self):
        return not self.console

    @property
    def is_console(self):
        return self.console

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
    """One plugin load with empty conversations and a throwaway data folder."""
    server = FakeServer()
    null_handler = logging.NullHandler()
    server.logger.addHandler(null_handler)

    monkeypatch.setattr(games_ai, "all_chat_param", {}, raising=False)
    monkeypatch.setattr(games_ai, "_history_frozen", True, raising=False)
    monkeypatch.setattr(games_ai, "_cross_server", None, raising=False)
    monkeypatch.setattr(games_ai.logger, "_server", server, raising=False)
    monkeypatch.setattr(plugin_config, "all_ai", {"main": model_entry()})
    monkeypatch.setattr(plugin_config, "skills_description", {})
    monkeypatch.setattr(plugin_config, "debug_mode", False)
    monkeypatch.setattr(plugin_config, "data_path",
                        os.path.join(str(tmp_path), "public_database.db"))
    monkeypatch.setattr(plugin_config, "cross_server_name", "probe-node")
    monkeypatch.setattr(plugin_config, "prefix", "[GamesAI]")
    try:
        yield SimpleNamespace(server=server, db=os.path.join(str(tmp_path), "public_database.db"))
    finally:
        server.logger.removeHandler(null_handler)


def conversation(env, user):
    """A finished conversation: one question and its answer, so the newest message is the answer."""
    param = ChatParam(env.server, model_id="main")
    param.add_to_response_list("user", "hello")
    param.add_to_response_list("assistant", "hi there")
    games_ai.all_chat_param[user] = param
    return param


def texts(param):
    return [message.get("content") for message in param.response_list]


def plain(shown):
    return [str(item) for item in shown]


def test_the_tool_is_registered_and_hub_bound(env):
    handler = get_tool_handler(TOOL)

    assert handler is not None, "the tool is registered"
    assert handler.execute_in_hub is True, \
        f"it runs where the conversations live: {None if handler is None else handler.execute_in_hub}"
    assert handler.resolve_perm() == 0, f"it needs no permission of its own: {handler.resolve_perm()}"

    schema = handler.schema["function"]
    assert set(schema["parameters"]["properties"]) == {"target", "message"}, \
        f"the model sees both parameters: {schema['parameters']}"
    assert schema["parameters"]["required"] == ["target", "message"], \
        f"...and both are required: {schema['parameters']}"


def test_the_tool_description_states_its_rules(env):
    schema = get_tool_handler(TOOL).schema["function"]

    assert "one-way" in schema["description"], \
        f"the description says it is one-way: {schema['description']}"
    assert "already has a GamesAI conversation" in schema["description"], \
        f"the description names the recipient rule: {schema['description']}"
    assert ("whatever the permission levels are" in schema["description"]
            and "higher permission level" not in schema["description"]), \
        f"the description says permission does not matter: {schema['description']}"
    assert "never creates one" in schema["description"], \
        f"the description says a delivery never creates a conversation: {schema['description']}"
    assert "Server Control Panel" in schema["parameters"]["properties"]["target"]["description"], \
        "the target parameter documents the console key: {}".format(
            schema["parameters"]["properties"]["target"])


def test_the_tool_is_offered_on_the_hub_only(env):
    hub_names = {s["function"]["name"] for s in get_hub_tool_schemas_for_perm(0)}
    local_names = {s["function"]["name"] for s in get_local_tool_schemas_for_perm(0)}

    assert TOOL in hub_names, f"it is offered for every request on the hub: {sorted(hub_names)}"
    assert TOOL not in local_names, \
        f"...and never uploaded as a client-side tool: {sorted(local_names)}"


def test_an_unknown_recipient_is_refused(env):
    steve = FakeSource("Steve", level=3, server=env.server)
    result = games_ai.send_message_to_player_ai(steve, "[AI]", "Alex", "hello there")

    assert "no GamesAI conversation" in result, f"an unknown recipient is refused: {result}"
    assert "Alex" not in games_ai.all_chat_param, "...and nothing is created for them"
    assert any("no_conversation" in line for line in plain(steve.shown)), \
        f"...and the sender is told so: {plain(steve.shown)}"


def test_an_empty_target_or_message_is_refused(env):
    steve = FakeSource("Steve", level=3, server=env.server)

    assert "required" in games_ai.send_message_to_player_ai(steve, "[AI]", "  ", "hi"), \
        "an empty target is refused"
    assert "required" in games_ai.send_message_to_player_ai(steve, "[AI]", "Alex", "   "), \
        "an empty message is refused"
    assert games_ai.all_chat_param == {}, "...and no conversation was touched"


def test_a_delivery_is_reported_and_lands_in_the_recipient_history(env):
    steve = FakeSource("Steve", level=3, server=env.server)
    alex = conversation(env, "Alex")
    result = games_ai.send_message_to_player_ai(steve, "[AI]", "Alex", "meet me at the base")

    assert "Delivered to Alex's assistant" in result, f"the delivery is reported: {result}"
    assert env.server.asked == [], f"the recipient's level is never asked for: {env.server.asked}"

    last = alex.response_list[-1]
    assert (last["role"] == "user"
            and alex.response_list[0]["content"] == "hello"
            and alex.response_list[1]["content"] == "hi there"), \
        f"a user message was appended at the end: {texts(alex)}"
    assert "Steve" in last["content"], f"...carrying the sender's name: {last}"
    assert "meet me at the base" in last["content"], f"...and the text: {last}"
    assert "external_message" in last["content"], f"...wrapped in the localized frame: {last}"
    assert "probe-node" in last["content"], f"...with the origin of the sender: {last}"
    assert any("delivered" in line for line in plain(steve.shown)), \
        f"the sender is told it was delivered: {plain(steve.shown)}"


def test_every_line_the_tool_shows_the_player_carries_the_ai_prefix(env):
    prefixed = FakeSource("Steve", level=3, server=env.server)
    alex = conversation(env, "Alex")

    games_ai.send_message_to_player_ai(prefixed, "[ProbeAI]", "Nowhere", "hello")

    assert bool(plain(prefixed.shown)) and plain(prefixed.shown)[-1].startswith("[ProbeAI]"), \
        f"a refusal line starts with the AI prefix: {plain(prefixed.shown)}"
    assert not any(line.startswith("[GamesAI]") for line in plain(prefixed.shown)), \
        f"...and never with the plugin prefix: {plain(prefixed.shown)}"

    prefixed.shown.clear()
    games_ai.send_message_to_player_ai(prefixed, "[ProbeAI]", "Alex", "with the AI prefix")

    assert bool(plain(prefixed.shown)) and plain(prefixed.shown)[-1].startswith("[ProbeAI]"), \
        f"a delivered line starts with the AI prefix: {plain(prefixed.shown)}"
    assert "with the AI prefix" in texts(alex)[-1], \
        f"...and the delivery really happened: {texts(alex)}"


def test_anyone_may_write_to_anyone(env):
    steve = FakeSource("Steve", level=3, server=env.server)
    alex = conversation(env, "Alex")

    env.server.levels = {"Alex": 1}
    result = games_ai.send_message_to_player_ai(steve, "[AI]", "Alex", "second message")
    assert result.startswith("Delivered"), f"a lower level is allowed: {result}"

    env.server.levels = {"Alex": 4}
    before = len(alex.response_list)
    steve.shown.clear()
    result = games_ai.send_message_to_player_ai(steve, "[AI]", "Alex", "should arrive now")

    assert result.startswith("Delivered"), f"a higher level is allowed too: {result}"
    assert len(alex.response_list) == before + 1, f"...and it really landed: {texts(alex)}"
    assert "Steve" in alex.response_list[-1]["content"], \
        f"...with the sender named: {alex.response_list[-1]}"
    assert "ermission" not in result, f"...and nothing about permission in the result: {result}"
    assert env.server.asked == [], f"the recipient's level is never looked up: {env.server.asked}"

    weak = FakeSource("Newbie", level=0, server=env.server)
    result = games_ai.send_message_to_player_ai(weak, "[AI]", "Alex", "from a level 0 player")

    assert result.startswith("Delivered"), \
        f"a level 0 sender reaches a level 4 conversation: {result}"
    assert env.server.asked == [], f"...and still nothing was looked up: {env.server.asked}"
    assert "from a level 0 player" in texts(alex)[-1], \
        f"the sender's own level is not needed either: {texts(alex)[-1]}"

    env.server.levels = {}


def test_the_console_conversation_is_a_target_like_any_other(env):
    steve = FakeSource("Steve", level=3, server=env.server)
    console_param = conversation(env, CONSOLE)
    steve.shown.clear()
    env.server.asked.clear()

    result = games_ai.send_message_to_player_ai(steve, "[AI]", CONSOLE, "for the operator")

    assert result.startswith("Delivered"), \
        f"a player may write to the console conversation: {result}"
    assert "for the operator" in console_param.response_list[-1]["content"], \
        f"...and the message is there: {console_param.response_list[-1]}"
    assert "Steve" in console_param.response_list[-1]["content"], \
        f"...naming the sender: {console_param.response_list[-1]}"
    assert env.server.asked == [], \
        f"the console name is still never looked up as a player: {env.server.asked}"

    operator = FakeSource("Server Control Panel", level=4, server=env.server, console=True)
    result = games_ai.send_message_to_player_ai(operator, "[AI]", CONSOLE, "restart at midnight")

    assert "Delivered" in result, f"the console itself may: {result}"
    assert "restart at midnight" in console_param.response_list[-1]["content"], \
        f"...and the message is there: {console_param.response_list[-1]}"


def test_a_user_may_message_their_own_conversation(env):
    steve = FakeSource("Steve", level=3, server=env.server)
    own = conversation(env, "Steve")
    result = games_ai.send_message_to_player_ai(steve, "[AI]", "Steve", "note to self")

    assert "Delivered" in result, f"self-delivery is allowed (same level): {result}"
    assert "note to self" in own.response_list[-1]["content"], \
        f"...and lands in the sender's own history: {own.response_list[-1]}"


def test_the_length_limit(env):
    steve = FakeSource("Steve", level=3, server=env.server)
    env.server.levels = {"Alex": 1}
    measured = conversation(env, "Measured")

    result = games_ai.send_message_to_player_ai(steve, "[AI]", "Measured", "x" * 1000)
    assert result.startswith("Delivered"), f"1000 characters are accepted: {result}"
    assert "x" * 1000 in texts(measured)[-1], \
        f"...and stored in full: {len(texts(measured)[-1])}"

    steve.shown.clear()
    result = games_ai.send_message_to_player_ai(steve, "[AI]", "Measured", "x" * 1001)

    assert "1001 characters" in result, f"1001 characters are refused: {result}"
    assert any("too_long" in line for line in plain(steve.shown)), \
        f"...and the sender is told the limit: {plain(steve.shown)}"
    assert len(measured.response_list) == 3, \
        f"...and nothing extra was delivered: {texts(measured)}"


def test_an_idle_conversation_stores_the_delivery_as_its_newest_message(env):
    steve = FakeSource("Steve", level=3, server=env.server)
    idle = conversation(env, "Idle")
    games_ai.send_message_to_player_ai(steve, "[AI]", "Idle", "idle target")

    assert "idle target" in idle.response_list[-1]["content"] and not idle.response_queue, \
        f"an idle conversation stores it as its newest message: {texts(idle)}"


def test_an_unanswered_question_keeps_the_delivery_in_order(env):
    steve = FakeSource("Steve", level=3, server=env.server)
    pending = ChatParam(env.server, model_id="main")
    pending.add_to_response_list("user", "a question that was never answered")
    games_ai.all_chat_param["Pending"] = pending
    games_ai.send_message_to_player_ai(steve, "[AI]", "Pending", "arrived before the answer")

    assert (pending.response_list[0]["content"] == "a question that was never answered"
            and "arrived before the answer" in pending.response_list[1]["content"]), \
        f"an unanswered question keeps its place, the message follows it: {texts(pending)}"
    assert (games_ai.send_message_to_player_ai(steve, "[AI]", "Pending", "and a third one"),
            "arrived before the answer" in pending.response_list[-2]["content"]
            and "and a third one" in pending.response_list[-1]["content"])[1], \
        f"...and a second delivery keeps the order of the first: {texts(pending)}"


def test_a_running_round_takes_the_delivery_into_the_queue(env):
    steve = FakeSource("Steve", level=3, server=env.server)
    running = conversation(env, "Running")
    running.is_stopped.clear()                     # a round is in flight
    games_ai.send_message_to_player_ai(steve, "[AI]", "Running", "while you are busy")

    assert (len(running.response_queue) == 1 and running.response_queue[0]["role"] == "user"
            and "while you are busy" in running.response_queue[0]["content"]), \
        f"a running round takes it into the queue: {running.response_queue}"
    assert len(running.response_list) == 2, \
        f"...and the history is untouched until the round merges it: {texts(running)}"

    merged = running._merge_response_queue_locked()

    assert merged == 1 and "while you are busy" in running.response_list[-1]["content"], \
        f"the round merges it at a safe point: {texts(running)}"
    assert running.response_queue == [], "...and the queue is empty afterwards"

    running.forced_add_to_response_list("user", "queued")

    assert running.request_stop() and [m["content"] for m in running.response_queue] == ["queued"], \
        f"a queued delivery survives !!ask stop: {running.response_queue}"
    assert running._merge_response_queue_locked() == 1 \
        and running.response_list[-1]["content"] == "queued", \
        f"...and the next round merges it into the history: {texts(running)}"
    running.is_stopped.set()


def test_a_concurrent_delivery_is_never_swallowed_by_the_drain(env):
    busy = ChatParam(env.server, model_id="main")
    total = 800
    per_thread = total // 4

    def producer(index):
        for i in range(per_thread):
            busy.forced_add_to_response_list("user", "m{}-{}".format(index, i))

    threads = [threading.Thread(target=producer, args=(index,)) for index in range(4)]
    for thread in threads:
        thread.start()
    merged_total = 0
    while any(thread.is_alive() for thread in threads) or busy.response_queue:
        merged_total += busy._merge_response_queue_locked()
        time.sleep(0)
    for thread in threads:
        thread.join()
    merged_total += busy._merge_response_queue_locked()

    assert merged_total == total, f"every queued message reached the history: {merged_total}"
    assert len(busy.response_list) == total, \
        f"...and none was lost in the drain: {len(busy.response_list)}"


def test_the_recipient_is_told_in_game(env):
    steve = FakeSource("Steve", level=3, server=env.server)
    conversation(env, "Alex")
    conversation(env, CONSOLE)

    env.server.online = ["Alex"]
    env.server.told.clear()
    games_ai.send_message_to_player_ai(steve, "[AI]", "Alex", "with a notice")

    assert len(env.server.told) == 1 and env.server.told[0][0] == "Alex", \
        f"an online recipient is told: {env.server.told}"
    assert "Steve" in env.server.told[0][1], \
        f"...and the notice names the sender: {env.server.told}"

    env.server.online = ["Someone Else"]
    env.server.told.clear()
    games_ai.send_message_to_player_ai(steve, "[AI]", "Alex", "no notice")

    assert env.server.told == [], \
        f"a recipient who is not here gets no notice: {env.server.told}"

    env.server.with_api = False
    env.server.told.clear()
    games_ai.send_message_to_player_ai(steve, "[AI]", "Alex", "still no notice")

    assert env.server.told == [], \
        f"without the online list nothing is claimed: {env.server.told}"

    env.server.with_api = True
    env.server.told.clear()
    games_ai.send_message_to_player_ai(steve, "[AI]", CONSOLE, "operator message")

    assert env.server.told == [], f"the console gets no in-game notice: {env.server.told}"


def test_a_cross_server_sender_keeps_its_origin(env):
    alex = conversation(env, "Alex")
    remote = FakeSource("Steve", level=3, server=env.server, origin="survival-9f31ab")
    games_ai.send_message_to_player_ai(remote, "[AI]", "Alex", "from another instance")

    assert "survival-9f31ab" in alex.response_list[-1]["content"], \
        f"the origin on the wire is what the frame says: {alex.response_list[-1]}"
    assert "Steve" in alex.response_list[-1]["content"], \
        f"...and the sender's name is still the player, not the instance: {alex.response_list[-1]}"
