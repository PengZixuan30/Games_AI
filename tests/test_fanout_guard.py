"""Cluster fan-out only ever broadcasts the command that was actually registered.

The reload tool used to execute ``!!gamesai reload`` with the AI round's command source, whose
``Info.content`` is the ``!!ask ...`` line: the cluster fan-out then broadcast that ask to every
node, and each node ran its own AI round (its own ChatParam, its own key). The route wrapper now
compares the source's line with the registered literal, a node refuses a broadcast ``!!ask``
anyway, and the reload tool no longer passes the round's source at all.
"""
import logging
from types import SimpleNamespace

import pytest

import games_ai
from games_ai.cluster.ws_command import ROUTE_CLUSTER, SessionRegistry

log = logging.getLogger("fanout-guard")


class FakeHub:
    def __init__(self):
        self.broadcasts = []
        self.command_apps = {"games_ai"}

    def broadcast(self, action, *, apps, data):
        self.broadcasts.append((action, set(apps), dict(data)))


class FakeManager:
    def __init__(self, *, server=True, client=False, connected=True):
        self.is_server = server
        self.is_client = client
        self.connected = connected
        self.mode = "server" if server else "client"
        self.name = "hub-name"
        self.hub = FakeHub() if server else None


class FakeSource:
    def __init__(self, content):
        self.content = content
        self.player = "Steve"
        self.is_console = False
        self.received = []

    def get_info(self):
        return SimpleNamespace(content=self.content)

    def get_permission_level(self):
        return 4

    def reply(self, message, **kwargs):
        self.received.append(str(message))


@pytest.fixture
def local_hub(monkeypatch):
    manager = FakeManager(server=True)
    monkeypatch.setattr(games_ai, "_cross_server", manager, raising=False)
    monkeypatch.setattr(games_ai, "_remote_sessions", SessionRegistry(), raising=False)
    return manager


def test_a_stale_source_line_cannot_fan_out_a_cluster_command(local_hub):
    calls = []
    wrapper = games_ai._route(ROUTE_CLUSTER, lambda source, context: calls.append(source.content),
                              expected_command="!!gamesai reload")
    source = FakeSource("!!ask tell everyone the server is back")

    wrapper(source, {})

    assert calls == [source.content], "the command really ran here"
    assert local_hub.hub.broadcasts == [], \
        "nothing was broadcast: the source's line is not the registered cluster command"


def test_the_registered_line_still_fans_out(local_hub):
    wrapper = games_ai._route(ROUTE_CLUSTER, lambda source, context: None,
                              expected_command="!!gamesai reload")
    source = FakeSource("!!gamesai reload")

    wrapper(source, {})

    assert len(local_hub.hub.broadcasts) == 1, "a typed reload still reaches the other instances"
    action, apps, data = local_hub.hub.broadcasts[0]
    assert action == "exec_cluster" and data["command"] == "!!gamesai reload"
    assert data["origin"] == "hub-name"
    assert data["session"], "the broadcast carries a session id"


def test_a_stale_line_is_not_forwarded_to_the_hub(monkeypatch):
    forwarded = []
    monkeypatch.setattr(games_ai, "_cross_server", FakeManager(server=False, client=True), raising=False)
    monkeypatch.setattr(games_ai, "_forward_command", lambda kind, source, raw: forwarded.append(raw),
                        raising=False)
    wrapper = games_ai._route(ROUTE_CLUSTER, lambda source, context: None,
                              expected_command="!!gamesai reload")

    wrapper(FakeSource("!!ask something else"), {})
    assert forwarded == [], "a stale line is refused instead of being sent as a cluster command"

    wrapper(FakeSource("!!gamesai  reload"), {})
    assert forwarded == ["!!gamesai  reload"], "the typed command is still forwarded (whitespace is normalised)"


def test_a_node_refuses_a_broadcast_ask(monkeypatch):
    executed = []
    sent = []
    monkeypatch.setattr(games_ai, "_execute_remote", lambda origin, data: executed.append((origin, data)),
                        raising=False)
    monkeypatch.setattr(games_ai, "_send_to_peer", lambda target, action, data: sent.append((target, action, data)),
                        raising=False)
    monkeypatch.setattr(games_ai, "_server_ref", object(), raising=False)

    refused = games_ai._on_cross_message({
        "action": "exec_cluster", "source": "hub",
        "data": {"command": "!!ask hi", "session": "remote-1", "origin": "hub"},
    })
    assert refused and refused.get("ok") is False
    assert executed == [], "a node never runs another instance's AI round"
    assert sent and sent[0][1] == "command_done" and sent[0][2]["session"] == "remote-1"

    accepted = games_ai._on_cross_message({
        "action": "command", "source": "hub",
        "data": {"command": "!!ask hi", "session": "remote-2", "origin": "hub"},
    })
    assert accepted and accepted.get("ok") is True
    assert executed and executed[0][1]["command"] == "!!ask hi", \
        "the legitimate client->hub forward is still executed"


def test_session_ids_are_unique_across_registries():
    first = SessionRegistry(log)
    second = SessionRegistry(log)
    source = FakeSource("!!gamesai reload")
    first_ids = {first.new(source, ROUTE_CLUSTER) for _ in range(20)}
    second_ids = {second.new(source, ROUTE_CLUSTER) for _ in range(20)}
    assert len(first_ids) == 20 and len(second_ids) == 20
    assert not first_ids & second_ids, "two instances can mint the same id no more"


def test_the_reload_tool_does_not_pass_the_round_source():
    from games_ai.ai import games_ai_tool

    calls = []

    class ToolServer:
        def rtr(self, key, **kwargs):
            return key

        def execute_command(self, raw, source=None):
            calls.append((raw, source))

    class ToolSource:
        def __init__(self):
            self.server = ToolServer()
            self.received = []

        def get_server(self):
            return self.server

        def get_permission_level(self):
            return 4

        def reply(self, message, **kwargs):
            self.received.append(str(message))

    source = ToolSource()
    result = games_ai_tool.reload_plugin(source, "[AI] ")
    assert calls == [("!!gamesai reload", None)], \
        "MCDR's own PluginCommandSource is used (no Info), so nothing can be fanned out"
    assert result == "Plugin reloaded"
