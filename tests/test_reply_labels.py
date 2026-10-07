"""The grey `[instance]` prefix must only mark a *cluster* command's output.

Reported symptom: on a sub-server (client) every single reply of an A-class command came back
prefixed with `[<hub name>]`. The rule compared names -- on a client the hub's name always
differs from its own -- so the hub's answer to the player's own command was labelled as if it
were another instance's broadcast output. The class of the command decides now.
"""
import pytest

import games_ai
from games_ai.ws_command import (
    MAX_SESSIONS,
    ROUTE_CLUSTER,
    ROUTE_SERVER,
    SessionRegistry,
    encode_text,
)


class FakeSource:
    """A player command source that records what it was shown."""

    def __init__(self):
        self.shown = []
        self.player = "Steve"

    @property
    def is_console(self):
        return False

    def get_permission_level(self):
        return 3

    def reply(self, message, **kwargs):
        self.shown.append(message)


class FakeManager:
    """A client that records what it hands to the hub."""

    is_client = True
    is_server = False
    connected = True
    hub = None
    mode = "client"

    def __init__(self, name="survival-abc123", hub_name="hub-main"):
        self.name = name
        self.hub_name = hub_name
        self.sent = []

    def send_to_hub(self, action, data=None, wait=False, timeout=None):
        self.sent.append((action, data))
        return {"ok": True}


def plain(shown):
    return [item.to_plain_text() if hasattr(item, "to_plain_text") else str(item)
            for item in shown]


def feed(session, sender, text="hello from afar"):
    games_ai._render_remote_reply({
        "type": "message", "source": sender, "action": "command_reply",
        "data": {"session": session, "text": encode_text(text)},
    })


@pytest.fixture
def client(monkeypatch):
    """One client instance's plugin globals: a fresh session table and a fake hub link.

    ``monkeypatch`` rebinds both globals and restores them however the test ends, so no test
    can leak a fake manager or a session table into the next one.
    """
    monkeypatch.setattr(games_ai, "_remote_sessions", SessionRegistry(), raising=False)
    manager = FakeManager()
    monkeypatch.setattr(games_ai, "_cross_server", manager, raising=False)
    return manager


def test_an_a_class_commands_answers_carry_no_label(client):
    player = FakeSource()
    games_ai._forward_command(ROUTE_SERVER, player, "!!ask 你好")

    assert len(client.sent) == 1, f"the command was handed to the hub: {client.sent}"
    action, payload = client.sent[0]
    session = payload.get("session")
    assert action == "command" and bool(session), \
        f"...as a server-class command: {(action, payload)}"
    assert games_ai._remote_sessions.kind_of(session) == ROUTE_SERVER, \
        f"...and the session remembers its class: {games_ai._remote_sessions.kind_of(session)}"

    for _ in range(3):                       # a streamed answer has many lines
        feed(session, client.hub_name)
    assert len(player.shown) == 3, f"the hub's answer is shown: {plain(player.shown)}"
    assert all(line == "hello from afar" for line in plain(player.shown)), \
        f"...unlabelled: {plain(player.shown)}"
    assert not any(client.hub_name in line for line in plain(player.shown)), \
        f"...and without the hub's name anywhere: {plain(player.shown)}"

    player.shown.clear()
    feed(session, "other-instance")
    assert plain(player.shown) == ["hello from afar"], \
        f"a server-class stream is never labelled, whoever sent it: {plain(player.shown)}"


def test_a_c_class_command_keeps_the_labels_the_docs_promise(client):
    player = FakeSource()
    games_ai._forward_command(ROUTE_CLUSTER, player, "!!gamesai reload")
    action, payload = client.sent[-1]
    session = payload.get("session")
    assert action == "command_cluster", f"...is forwarded as a cluster command: {action}"
    assert games_ai._remote_sessions.kind_of(session) == ROUTE_CLUSTER, \
        f"...and the session knows that too: {games_ai._remote_sessions.kind_of(session)}"

    feed(session, client.hub_name, "hub reloaded")
    feed(session, client.name, "this machine reloaded")
    feed(session, "third-instance", "third reloaded")
    shown = plain(player.shown)
    assert shown[0] == f"[{client.hub_name}] hub reloaded", \
        f"the hub's line is labelled with the hub's name: {shown}"
    assert shown[1] == "this machine reloaded", f"our own line stays unlabelled: {shown}"
    assert shown[2] == "[third-instance] third reloaded", \
        f"another instance is labelled too: {shown}"


def test_the_hub_itself_keeps_its_old_behaviour(client, monkeypatch):
    monkeypatch.setattr(games_ai, "_cross_server",
                        FakeManager(name="hub-main", hub_name=""), raising=False)
    hub_player = FakeSource()
    hub_session = games_ai._remote_sessions.new(hub_player, ROUTE_CLUSTER)
    feed(hub_session, "hub-main", "local line")
    feed(hub_session, "client-b", "remote line")
    shown = plain(hub_player.shown)
    assert shown[0] == "local line", f"the hub's own output is unlabelled: {shown}"
    assert shown[1] == "[client-b] remote line", f"a client's output is labelled: {shown}"


def test_the_session_bookkeeping_holds(client):
    watcher = FakeSource()
    games_ai._render_remote_reply({"source": "x", "data": {
        "session": "nope", "text": encode_text("hi")}})

    assert watcher.shown == [], f"an unknown session renders nothing: {plain(watcher.shown)}"
    assert games_ai._remote_sessions.kind_of("nope") == ROUTE_SERVER, \
        "kind_of defaults to the server class"
    assert len(games_ai._remote_sessions._sessions) <= MAX_SESSIONS, \
        f"the registry still bounds itself: {len(games_ai._remote_sessions._sessions)}"
    fresh = games_ai._remote_sessions.new(FakeSource(), ROUTE_CLUSTER)
    assert games_ai._remote_sessions.kind_of(fresh) == ROUTE_CLUSTER, \
        "a new session keeps its class after the sweep"


def test_rich_text_survives_the_label_decision(client):
    rich = FakeSource()
    rich_session = games_ai._remote_sessions.new(rich, ROUTE_CLUSTER)
    games_ai._render_remote_reply({
        "source": "client-c", "data": {"session": rich_session,
                                       "text": {"text": "coloured", "color": "gold"}},
    })
    assert "coloured" in plain(rich.shown)[0], \
        f"the coloured body is still there: {plain(rich.shown)}"
    assert plain(rich.shown)[0].startswith("[client-c] "), \
        f"...behind the grey label: {plain(rich.shown)}"
