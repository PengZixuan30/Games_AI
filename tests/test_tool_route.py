"""Cross-server tool routing: which side runs a tool, and what the model is offered.

Two real plugin instances (hub + client over a real socket) and fake servers/sources, like
test_routing.py. The AI and its tool list live on the hub; a tool that describes the asking
player's own server must run there and hand its result back.
"""
import importlib.util
import json
import logging
import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest

import games_ai
from _helpers.paths import PKG
from _helpers.wait import wait_until

# Every built-in tool that must run where the AI runs (the hub), and the ones that must run where
# the asking player is.
HUB_BOUND = [
    "ai_read_data", "ai_read_all_keys", "ai_write_data", "ai_add_data", "ai_del_data",
    "ai_read_all_data", "read_skills", "write_skills", "modify_skills", "delete_skills",
    "read_custom_tools", "modify_custom_tools", "append_custom_tools", "reload_plugin",
    "setting_timer", "run_mineflayer_bot", "stop_mineflayer_bot", "bot_chat", "bot_whisper",
    "bot_get_state", "bot_call_action", "delegate_to_bot",
]
PLAYER_SIDE = ["get_player_position", "get_online_players", "calculator", "item_caculator"]

STARTED = []        # (instance name, tool) appended when a tool starts running
FINISHED = []       # the same, appended when it returns


class FakeInfo:
    content = "!!ask where am I"


class FakeSource:
    """Stands in for a PlayerCommandSource / ConsoleCommandSource."""

    def __init__(self, who, permission=3, console=False):
        self.who = who
        self.permission = permission
        self.console = console
        self.player = None if console else who
        self.received = []

    def get_info(self):
        return FakeInfo()

    def get_permission_level(self):
        return self.permission

    @property
    def is_console(self):
        return self.console

    @property
    def is_player(self):
        return not self.console

    def reply(self, message, **kwargs):
        self.received.append(message)

    def __str__(self):
        return "console" if self.console else self.who


class FakeServer:
    """Stands in for PluginServerInterface; records what was executed and by which thread."""

    def __init__(self, name, levels=None):
        self.name = name
        self.levels = dict(levels or {})
        self.logger = logging.getLogger("fake-" + name)
        self.commands = []          # (raw, command source, thread name)
        self.router = None          # (tool, args): emulate the hub's AI loop routing one call
        self.routed = []

    def rtr(self, key, **kwargs):
        text = key.split(".")[-1]
        if kwargs:
            text += "(" + ", ".join("{}={}".format(k, v) for k, v in sorted(kwargs.items())) + ")"
        return "[" + text + "]"

    def execute_command(self, raw, source):
        self.commands.append((raw, source, threading.current_thread().name))
        if self.router is not None:
            tool, args = self.router
            # exactly what ChatParam.tool_call does for a routed tool: block, get the answer
            self.routed.append(self.hub.route_remote_tool_call(source, tool, args, "AI"))

    def get_permission_level(self, player):
        return self.levels.get(str(player), 0)


class FakeToolFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = json.dumps(arguments) if arguments is not None else ""


class FakeToolCall:
    def __init__(self, name, arguments=None, call_id="call-1"):
        self.function = FakeToolFunction(name, arguments)
        self.id = call_id


def load_instance(alias):
    """Load the plugin package a second time, under its own namespace of globals."""
    spec = importlib.util.spec_from_file_location(
        alias, os.path.join(PKG, "__init__.py"), submodule_search_locations=[PKG])
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


def unload_instance(alias):
    """Forget an instance and every submodule it registered, so nothing leaks into a later test."""
    for name in [name for name in sys.modules
                 if name == alias or name.startswith(alias + ".")]:
        del sys.modules[name]


def register_probe(instance, name, *, execute_in_hub=False, perm=0, delay=0.0, reply=""):
    """Register one probe tool that says which instance ran it."""
    def func(source, ai_prefix, **kwargs):
        STARTED.append((instance._server_ref.name, name))
        if reply:
            source.reply(reply)
        if delay:
            time.sleep(delay)
        FINISHED.append((instance._server_ref.name, name))
        return "{} from {} args={}".format(name, instance._server_ref.name, kwargs)

    func.__name__ = name
    instance.register_tool(description="probe tool " + name, perm=perm,
                           execute_in_hub=execute_in_hub)(func)
    return func


def register_boom(instance, name, *, execute_in_hub=False):
    """Register one probe tool that raises, to check how a failure is reported."""
    def func(source, ai_prefix, **kwargs):
        STARTED.append((instance._server_ref.name, name))
        raise RuntimeError("boom-" + name)

    func.__name__ = name
    instance.register_tool(description="probe tool " + name, execute_in_hub=execute_in_hub)(func)
    return func


def ran(where, name):
    return any(entry == (where, name) for entry in STARTED)


def started_times(where, name):
    return sum(1 for entry in STARTED if entry == (where, name))


def plain(item):
    """One received reply as text, whatever the sender put in it."""
    return item.to_plain_text() if hasattr(item, "to_plain_text") else str(item)


def remote_source(instance, player="Steve", permission=3, session="", tools=None, console=False):
    """The source the hub builds for a request that arrived from the client."""
    return instance.WebSocketCommandSource(
        instance._server_ref, origin="host-b", player=None if console else player,
        is_console=console, permission_level=permission, sink=lambda text: None,
        tools=tools, session=session,
    )


def tool_result(param):
    return str(param.response_list[-1]["content"])


def tool_message(param):
    return param.response_list[-1]


@pytest.fixture(autouse=True)
def tool_log():
    """The probe logs are per-test: a test may run in isolation or after any other."""
    STARTED.clear()
    FINISHED.clear()


@pytest.fixture(scope="module")
def instances():
    """Both plugin instances, each with its own namespace of globals and its own tool module.

    Loading a whole package twice is the expensive part of this module, and the copies are never
    mutated by the fixtures themselves, so one pair serves every test.
    """
    a = load_instance("games_ai_route_a")          # becomes the hub, runs the AI
    b = load_instance("games_ai_route_b")          # becomes a client
    yield SimpleNamespace(a=a, b=b,
                          tools_a=sys.modules["games_ai_route_a.games_ai_tool"],
                          tools_b=sys.modules["games_ai_route_b.games_ai_tool"])
    unload_instance("games_ai_route_a")
    unload_instance("games_ai_route_b")


@pytest.fixture
def probes(instances, monkeypatch):
    """Both instances with their probe tools registered and a fake MCDR server on each end."""
    a, b = instances.a, instances.b
    monkeypatch.setattr(a, "_server_ref", FakeServer("host-a", levels={"Steve": 3, "Bob": 3}),
                        raising=False)
    monkeypatch.setattr(b, "_server_ref", FakeServer("host-b", levels={"Steve": 1, "Bob": 3}),
                        raising=False)
    a._server_ref.hub = a
    b._server_ref.hub = b
    monkeypatch.setattr(a.plugin_config, "cross_server_name", "host-a", raising=False)
    monkeypatch.setattr(b.plugin_config, "cross_server_name", "host-b", raising=False)
    monkeypatch.setattr(a, "_REMOTE_TOOL_TIMEOUT", 5.0, raising=False)

    register_probe(a, "probe_position", reply="probe working")
    register_probe(b, "probe_position", reply="probe working")
    register_probe(a, "probe_hub", execute_in_hub=True)
    register_probe(b, "probe_hub", execute_in_hub=True)
    register_probe(a, "probe_gated", perm=3)
    register_probe(b, "probe_gated", perm=3)
    register_probe(a, "probe_slow", delay=2.0)
    register_probe(b, "probe_slow", delay=2.0)
    register_probe(a, "probe_hub_only")            # only the hub knows this one
    register_probe(b, "probe_client_only")         # only the client knows this one
    register_boom(a, "probe_boom")
    register_boom(b, "probe_boom")
    register_boom(a, "probe_hub_boom", execute_in_hub=True)
    return SimpleNamespace(a=a, b=b, tools_a=instances.tools_a, tools_b=instances.tools_b)


@pytest.fixture
def cluster(probes, monkeypatch, free_port):
    """The two instances of :func:`probes`, linked over a real socket.

    The fixture *is* the boot step the old script ran once at module level, so its two boot
    checks -- "A is the hub" and "B is a client" -- are asserted here, with the same wording:
    every linked test below needs a live cluster, and a hub that cannot start has to say so.
    """
    a, b = probes.a, probes.b
    managers = []
    try:
        uri = "ws://127.0.0.1:{}".format(free_port())
        manager_a = a.CrossServerManager(uri, name="host-a", handler=a._on_cross_message)
        managers.append(manager_a)
        assert manager_a.start(timeout=5) == a.MODE_SERVER, f"A is the hub: {manager_a.reason}"
        # Every node carries its own token now; the hub issues it per name
        # (docs/token-enrollment.md).
        host_b_token = manager_a.hub.issue("host-b")
        manager_b = b.CrossServerManager(uri, name="host-b", token=host_b_token,
                                         handler=b._on_cross_message)
        managers.append(manager_b)
        assert manager_b.start(timeout=5) == b.MODE_CLIENT, f"B is a client: {manager_b.reason}"
        monkeypatch.setattr(a, "_cross_server", manager_a, raising=False)
        monkeypatch.setattr(b, "_cross_server", manager_b, raising=False)
        yield SimpleNamespace(a=a, b=b, tools_a=probes.tools_a, tools_b=probes.tools_b,
                              hub=manager_a, client=manager_b, uri=uri)
    finally:
        for manager in reversed(managers):
            manager.stop()


@pytest.fixture
def new_param(cluster):
    """A ChatParam whose OpenAI client is never needed: only tool_call() is exercised."""
    a = cluster.a

    class ProbeParam(a.ChatParam):
        def build_openai_client(self):
            self.openai_client = None

    def make():
        return ProbeParam(a._server_ref, model_id="probe-model")

    return make


def test_boot_two_instances(cluster):
    assert cluster.a is not cluster.b and cluster.tools_a is not cluster.tools_b, \
        f"two isolated namespaces: {(cluster.tools_a, cluster.tools_b)}"
    assert (cluster.a.chat_param._remote_tool_router is not None
            and cluster.b.chat_param._remote_tool_router is not None), \
        "the router hook is installed per instance"


def test_a_false_scope_tool_runs_on_the_origin(cluster, new_param):
    a, b = cluster.a, cluster.b
    steve = FakeSource("Steve", permission=3)
    session_a = b._remote_sessions.new(steve)
    source_a = remote_source(a, "Steve", 3, session=session_a,
                             tools=cluster.tools_b.get_local_tool_schemas_for_perm(3))
    param_a = new_param()
    param_a.tool_call(source_a, [FakeToolCall("probe_position", {"player": "Steve"}, "call-a")])

    assert ran("host-b", "probe_position"), f"the origin executed it: {STARTED}"
    assert not ran("host-a", "probe_position"), f"the hub did not execute it: {STARTED}"
    assert "from host-b" in tool_result(param_a), \
        f"the result reached the hub's AI loop: {tool_result(param_a)}"
    assert "'player': 'Steve'" in tool_result(param_a), \
        f"the arguments arrived on the origin: {tool_result(param_a)}"
    assert (tool_message(param_a).get("role") == "tool"
            and tool_message(param_a).get("tool_call_id") == "call-a"), \
        f"the AI loop stored it as the answer to that call: {tool_message(param_a)}"
    assert any("probe working" in plain(text) for text in steve.received), \
        ("the tool's own reply reached the player on the origin: "
         f"{[plain(text) for text in steve.received]}")


def test_a_local_request_runs_the_same_tool_here(cluster, new_param):
    before = list(STARTED)
    local_source = FakeSource("Steve", permission=3)
    param_local = new_param()
    param_local.tool_call(local_source,
                          [FakeToolCall("probe_position", {"player": "Steve"}, "call-local")])
    delta = [entry for entry in STARTED if entry not in before]

    assert ("host-a", "probe_position") in delta, f"the hub ran it for its own player: {delta}"
    assert ("host-b", "probe_position") not in delta, f"nothing was routed to the client: {delta}"
    assert "from host-a" in tool_result(param_local), \
        f"the local result is the hub's own: {tool_result(param_local)}"


def test_a_true_scope_tool_runs_on_the_hub(cluster, new_param):
    a, b = cluster.a, cluster.b
    session_b = b._remote_sessions.new(FakeSource("Steve", permission=3))
    source_b = remote_source(a, "Steve", 3, session=session_b,
                             tools=cluster.tools_b.get_local_tool_schemas_for_perm(3))
    param_b = new_param()
    param_b.tool_call(source_b, [FakeToolCall("probe_hub", {}, "call-b")])

    assert ran("host-a", "probe_hub"), f"the hub executed it: {STARTED}"
    assert not ran("host-b", "probe_hub"), f"the client never saw the call: {STARTED}"
    assert "from host-a" in tool_result(param_b), \
        f"the result came from the hub: {tool_result(param_b)}"
    assert all(entry != ("host-b", "probe_hub") for entry in STARTED), \
        "nothing was recorded on the client's side"


def test_a_tool_the_origin_lacks_fails_with_a_clear_string(cluster, new_param):
    a, b = cluster.a, cluster.b
    session_c = b._remote_sessions.new(FakeSource("Steve", permission=3))
    source_c = remote_source(a, "Steve", 3, session=session_c,
                             tools=cluster.tools_b.get_local_tool_schemas_for_perm(3))
    param_c = new_param()
    param_c.tool_call(source_c, [FakeToolCall("probe_hub_only", {}, "call-c")])
    text_c = tool_result(param_c)

    assert "probe_hub_only" in text_c, f"the answer names the missing tool: {text_c}"
    assert "does not provide" in text_c, f"and says this server does not provide it: {text_c}"
    assert tool_message(param_c).get("tool_call_id") == "call-c", \
        f"the AI loop kept its tool message: {tool_message(param_c)}"
    assert not ran("host-a", "probe_hub_only"), \
        f"the hub did not silently run the tool itself: {STARTED}"
    assert not ran("host-b", "probe_hub_only"), f"the client did not run it either: {STARTED}"


def test_a_tool_only_the_client_has_is_routed_to_it(cluster, new_param):
    a, b = cluster.a, cluster.b
    uploaded_b = cluster.tools_b.get_local_tool_schemas_for_perm(3)
    session_c2 = b._remote_sessions.new(FakeSource("Steve", permission=3))
    source_c2 = remote_source(a, "Steve", 3, session=session_c2, tools=uploaded_b)
    param_c2 = new_param()
    param_c2.tool_call(source_c2, [FakeToolCall("probe_client_only", {}, "call-c2")])

    assert ran("host-b", "probe_client_only"), \
        f"the client ran the tool the hub does not know: {STARTED}"
    assert "from host-b" in tool_result(param_c2), \
        f"its result reached the hub's AI loop: {tool_result(param_c2)}"


def test_an_exception_inside_a_routed_tool_is_a_string(cluster, new_param):
    a, b = cluster.a, cluster.b
    uploaded_b = cluster.tools_b.get_local_tool_schemas_for_perm(3)
    session_c3 = b._remote_sessions.new(FakeSource("Steve", permission=3))
    source_c3 = remote_source(a, "Steve", 3, session=session_c3, tools=uploaded_b)
    param_c3 = new_param()
    param_c3.tool_call(source_c3, [FakeToolCall("probe_boom", {}, "call-c3")])
    text_c3 = tool_result(param_c3)

    assert "boom-probe_boom" in text_c3, f"the failure is reported as text: {text_c3}"
    assert tool_message(param_c3).get("tool_call_id") == "call-c3", \
        f"the AI loop kept its tool message: {tool_message(param_c3)}"
    assert ran("host-b", "probe_boom"), f"the tool ran on the origin: {STARTED}"


def test_an_exception_inside_a_hub_bound_tool_is_a_string(cluster, new_param):
    a, b = cluster.a, cluster.b
    session_c4 = b._remote_sessions.new(FakeSource("Steve", permission=3))
    source_c4 = remote_source(a, "Steve", 3, session=session_c4,
                              tools=cluster.tools_b.get_local_tool_schemas_for_perm(3))
    param_c4 = new_param()
    param_c4.tool_call(source_c4, [FakeToolCall("probe_hub_boom", {}, "call-c4")])
    text_c4 = tool_result(param_c4)

    assert "Error while executing function probe_hub_boom" in text_c4, \
        f"the local failure is reported as text: {text_c4}"
    assert tool_message(param_c4).get("tool_call_id") == "call-c4", \
        f"the AI loop survived it: {tool_message(param_c4)}"


def test_a_hallucinated_name_is_still_an_unknown_function(cluster, new_param):
    a, b = cluster.a, cluster.b
    session_c5 = b._remote_sessions.new(FakeSource("Steve", permission=3))
    source_c5 = remote_source(a, "Steve", 3, session=session_c5,
                              tools=cluster.tools_b.get_local_tool_schemas_for_perm(3))
    param_c5 = new_param()
    param_c5.tool_call(source_c5, [FakeToolCall("probe_never_heard_of", {}, "call-c5")])

    assert "Unknown function: probe_never_heard_of" == tool_result(param_c5), \
        f"it is not routed: {tool_result(param_c5)}"
    assert not ran("host-b", "probe_never_heard_of"), \
        f"and nothing executed it: {STARTED}"


def test_the_origins_own_permission_table_decides(cluster, new_param):
    a, b = cluster.a, cluster.b
    session_d = b._remote_sessions.new(FakeSource("Steve", permission=3))
    source_a = remote_source(a, "Steve", 3, session=session_d,
                             tools=cluster.tools_b.get_local_tool_schemas_for_perm(3))

    assert source_a.get_permission_level() == 3, \
        f"the hub believes the player is level 3: {source_a.get_permission_level()}"
    assert b._server_ref.get_permission_level("Steve") == 1, "the origin's table says level 1"

    source_d = remote_source(a, "Steve", 3, session=session_d,
                             tools=cluster.tools_b.get_local_tool_schemas_for_perm(3))
    param_d = new_param()
    param_d.tool_call(source_d, [FakeToolCall("probe_gated", {}, "call-d")])
    text_d = tool_result(param_d)

    assert "permission denied" in text_d, f"the origin refused it: {text_d}"
    assert "host-b" in text_d, f"the refusal names the origin: {text_d}"
    assert "carries 1" in text_d, f"the origin's level is the one that counted: {text_d}"
    assert not ran("host-a", "probe_gated") and not ran("host-b", "probe_gated"), \
        f"the tool never ran anywhere: {STARTED}"
    assert b._server_ref.get_permission_level("Bob") == 3, \
        "a player the origin trusts is allowed through"

    source_d2 = remote_source(a, "Bob", 3, session=session_d,
                              tools=cluster.tools_b.get_local_tool_schemas_for_perm(3))
    param_d2 = new_param()
    param_d2.tool_call(source_d2, [FakeToolCall("probe_gated", {}, "call-d2")])

    assert ran("host-b", "probe_gated"), f"and then the tool runs on the origin: {STARTED}"


def test_an_origin_timeout_is_an_unknown_outcome(cluster, new_param, monkeypatch):
    a, b = cluster.a, cluster.b
    monkeypatch.setattr(a, "_REMOTE_TOOL_TIMEOUT", 1.0, raising=False)
    session_e = b._remote_sessions.new(FakeSource("Steve", permission=3))
    source_e = remote_source(a, "Steve", 3, session=session_e,
                             tools=cluster.tools_b.get_local_tool_schemas_for_perm(3))
    param_e = new_param()
    started_at = time.time()
    param_e.tool_call(source_e, [FakeToolCall("probe_slow", {}, "call-e")])
    elapsed = time.time() - started_at
    text_e = tool_result(param_e)

    assert elapsed < 1.9, f"the hub gave up at its timeout: {round(elapsed, 2)}"
    assert "unknown" in text_e.lower(), f"the model is told the outcome is unknown: {text_e}"
    assert "do not retry" in text_e.lower(), f"and is told not to retry: {text_e}"
    assert tool_message(param_e).get("tool_call_id") == "call-e", \
        f"the AI loop kept its tool message: {tool_message(param_e)}"
    assert ran("host-b", "probe_slow"), \
        f"the origin really did run it (a retry would run it twice): {STARTED}"
    assert wait_until(lambda: ("host-b", "probe_slow") in FINISHED, timeout=5.0), \
        f"waiting for the origin's slow tool to finish: {FINISHED}"
    time.sleep(0.2)
    assert started_times("host-b", "probe_slow") == 1, f"exactly one call was made: {STARTED}"
    assert not ran("host-a", "probe_slow"), f"the hub did not run it locally either: {STARTED}"


def test_what_the_model_is_offered(probes):
    tools_a, tools_b = probes.tools_a, probes.tools_b
    uploaded_b = tools_b.get_local_tool_schemas_for_perm(3)
    uploaded_names = {s["function"]["name"] for s in uploaded_b}

    assert {"probe_position", "probe_gated", "probe_client_only"} <= uploaded_names, \
        f"the upload holds the origin's own tools: {sorted(uploaded_names)}"
    assert not ({"probe_hub", "ai_read_data", "setting_timer", "bot_get_state"} & uploaded_names), \
        f"the upload holds no hub-bound tool: {sorted(uploaded_names)}"
    assert "probe_gated" not in {s["function"]["name"]
                                 for s in tools_b.get_local_tool_schemas_for_perm(1)}, \
        "the upload is permission-filtered"

    union = tools_a.get_request_tool_schemas(4, uploaded_b)
    names = [s["function"]["name"] for s in union]
    assert {"probe_hub", "ai_read_data", "read_skills", "setting_timer", "bot_chat"} <= set(names), \
        f"the hub's own hub-bound tools are offered: {sorted(names)}"
    assert {"probe_position", "probe_client_only", "get_player_position"} <= set(names), \
        f"the origin's own tools are offered: {sorted(names)}"
    assert "probe_hub_only" not in names, \
        f"a tool neither side can run is never offered: {sorted(names)}"
    assert len(names) == len(set(names)), f"no tool name is offered twice: {sorted(names)}"
    assert ("ai_write_data" not in {s["function"]["name"]
                                    for s in tools_a.get_request_tool_schemas(1, uploaded_b)}
            and "read_skills" in {s["function"]["name"]
                                  for s in tools_a.get_request_tool_schemas(1, uploaded_b)}), \
        ("the hub's own permission filter still applies: "
         f"{[s['function']['name'] for s in tools_a.get_request_tool_schemas(1, uploaded_b)]}")
    assert {"probe_position", "probe_hub", "get_player_position", "ai_read_data"} <= \
        {s["function"]["name"] for s in tools_a.get_request_tool_schemas(4, None)}, \
        "a local request is offered everything"
    fake_upload = [{"type": "function",
                    "function": {"name": "ai_read_data", "description": "fake upload"}}]
    copies = [s for s in tools_a.get_request_tool_schemas(4, fake_upload)
              if s["function"]["name"] == "ai_read_data"]
    assert len(copies) == 1 and copies[0]["function"].get("description") != "fake upload", \
        f"an uploaded copy never shadows the hub's own tool: {copies}"


@pytest.mark.parametrize("tool_name", HUB_BOUND)
def test_a_builtin_hub_bound_tool_keeps_its_flag(instances, tool_name):
    handler = instances.tools_a.get_tool_handler(tool_name)

    assert handler is not None and handler.execute_in_hub is True, \
        f"{tool_name} is hub-bound: {None if handler is None else handler.execute_in_hub}"


@pytest.mark.parametrize("tool_name", PLAYER_SIDE)
def test_a_builtin_player_side_tool_keeps_its_flag(instances, tool_name):
    handler = instances.tools_a.get_tool_handler(tool_name)

    assert handler is not None and handler.execute_in_hub is False, \
        f"{tool_name} runs where the player is: {None if handler is None else handler.execute_in_hub}"


def test_re_registration_keeps_the_flag():
    """The real package, real module names: reset_all_tools re-runs every registration."""
    games_ai.reset_all_tools()

    assert games_ai.get_tool_handler("read_skills").execute_in_hub is True, \
        "read_skills is still hub-bound after re-registration"
    assert games_ai.get_tool_handler("ai_read_data").execute_in_hub is True, \
        "ai_read_data is still hub-bound after re-registration"
    assert games_ai.get_tool_handler("get_player_position").execute_in_hub is False, \
        "get_player_position still runs where the player is after re-registration"


def test_the_forwarded_command_carries_the_upload(cluster):
    a, b = cluster.a, cluster.b
    steve2 = FakeSource("Steve", permission=3)
    b._forward_command(b.ROUTE_SERVER, steve2, "!!ask where is Steve")

    assert wait_until(lambda: len(a._server_ref.commands) >= 1, timeout=5.0), \
        f"the hub received the command: {a._server_ref.commands}"
    raw, remote_command_source, thread_name = a._server_ref.commands[-1]
    assert raw == "!!ask where is Steve", f"the raw line survived the link: {raw}"
    assert "sock_handler" not in thread_name, f"it runs off the link reader thread: {thread_name}"
    assert type(remote_command_source).__name__ == "WebSocketCommandSource", \
        "the source is a WebSocketCommandSource"
    assert {"probe_position", "probe_gated"} <= {s["function"]["name"]
                                                 for s in remote_command_source.tools}, \
        ("the frame carried the client's own tools: "
         f"{[s['function']['name'] for s in remote_command_source.tools]}")
    assert "ai_read_data" not in {s["function"]["name"] for s in remote_command_source.tools}, \
        "the frame carried no hub-bound tool"
    assert (remote_command_source.session
            and b._remote_sessions.get(remote_command_source.session) is steve2), \
        f"the request remembers the session it answers to: {remote_command_source.session}"


def test_a_routed_call_from_the_hubs_command_thread_comes_back(cluster):
    a, b = cluster.a, cluster.b
    # Section (a) had already routed one probe_position call by the time the old suite reached
    # this check; this test runs on its own, so it counts the "one more" itself.
    ran_before = started_times("host-b", "probe_position")
    a._server_ref.router = ("probe_position", {"player": "Steve"})
    steve3 = FakeSource("Steve", permission=3)
    b._forward_command(b.ROUTE_SERVER, steve3, "!!ask second question")

    assert wait_until(lambda: len(a._server_ref.routed) >= 1, timeout=8.0), \
        f"the routed result came back: {a._server_ref.routed}"
    assert bool(a._server_ref.routed) and "from host-b" in a._server_ref.routed[-1], \
        f"it is the origin's answer: {a._server_ref.routed}"
    assert bool(a._server_ref.routed) and "unknown" not in a._server_ref.routed[-1].lower(), \
        f"it was not reported as a timeout: {a._server_ref.routed}"
    assert started_times("host-b", "probe_position") == ran_before + 1, \
        f"the client ran it once more: {STARTED}"


def test_a_peer_that_shares_the_hubs_name_is_refused(cluster, monkeypatch):
    a, b = cluster.a, cluster.b
    steve4 = FakeSource("Steve", permission=3)
    session_f = b._remote_sessions.new(steve4)
    source_f = remote_source(a, "Steve", 3, session=session_f,
                             tools=cluster.tools_b.get_local_tool_schemas_for_perm(3))
    before_started = list(STARTED)
    # the samename setup: hub and client share one name
    monkeypatch.setattr(cluster.hub, "name", "host-b")
    monkeypatch.setattr(cluster.hub.hub, "name", "host-b")
    shortcut = cluster.hub.send_to("host-b", "tool_call", wait=True, timeout=3.0, data={
        "tool": "probe_position", "args": {}, "player": "Steve", "console": False,
        "permission": 3, "origin": "host-b", "session": session_f, "ai_prefix": "AI",
    })

    assert bool(shortcut), \
        f"a call to a peer with the hub's own name never leaves the hub: {shortcut}"
    assert "this is the hub" in str((shortcut or {}).get("error")), \
        f"and is refused there instead of answered with the hub's own data: {shortcut}"

    same_name_text = a.route_remote_tool_call(source_f, "probe_position", {}, "AI")
    delta = [entry for entry in STARTED if entry not in before_started]

    assert "shares the hub's name" in same_name_text, \
        f"the router refuses the same-name target: {same_name_text}"
    assert ("host-a", "probe_position") not in delta, f"nothing ran on the hub for it: {delta}"
    assert ("host-b", "probe_position") not in delta, \
        f"nothing was routed to the client either: {delta}"
