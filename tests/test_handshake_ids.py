"""Handshake identities: games_ai vs mineflayer_bot, and the hub adapting to each."""
import json
import logging

import pytest

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as raw_connect

from games_ai.websockets_client import APP_ID, APP_ID_BOT, CrossServerNode
from games_ai.websockets_server import CrossServerHub

from _helpers.wait import wait_until

LOG = logging.getLogger("hub")


def close_code(exc):
    """The close code of a refused handshake."""
    return getattr(getattr(exc, "rcvd", None), "code", None)


def join(uri, hub, name, app, probe=False):
    """Register a raw peer and return (connection, hello_ack).

    A node needs its own token now (docs/token-enrollment.md): the hub issues one per name,
    and this helper asks for it the way `!!gamesai node token <name>` does.
    """
    conn = raw_connect(uri)
    frame = {"type": "hello", "protocol": 1, "server": name, "version": "0.8.0"}
    if app is not None:
        frame["app"] = app
    if probe:
        frame["probe"] = True
    else:
        frame["token"] = hub.issue(name, app=app or APP_ID)
    conn.send(json.dumps(frame))
    return conn, json.loads(conn.recv(timeout=3))


def collect(peers, seen, timeout=0.3):
    """Move whatever each peer was sent into ``seen``, for the old ``sleep(0.3)`` worth of time.

    ``wait_until`` cannot be told that a frame will *not* arrive, so the poll keeps returning
    False and simply uses the bound up: an absence after it is as strong as it was in the
    stand-alone script, and a positive case still reads everything that did arrive.
    """
    def drain(conn, into):
        try:
            while True:
                into.append(json.loads(conn.recv(timeout=0.1)).get("action"))
        except Exception:
            return                      # nothing more waiting on this connection

    def poll():
        for name, (conn, _) in peers.items():
            drain(conn, seen[name])
        return False

    wait_until(poll, timeout=timeout)
    return seen


@pytest.fixture
def hub(free_port):
    """A hub on an in-memory node table (nothing to clean up beyond the listener)."""
    hub = CrossServerHub("127.0.0.1", free_port(), name="host-a", logger=LOG)
    assert hub.start(timeout=5), "hub started"
    yield hub
    hub.stop()


@pytest.fixture
def uri(hub):
    return "ws://127.0.0.1:{}".format(hub.port)


@pytest.fixture
def peers(hub, uri):
    """``host-b`` as a GamesAI instance and ``Steve`` as a bot, closed however the test ends."""
    opened = {"host-b": join(uri, hub, "host-b", APP_ID),
              "Steve": join(uri, hub, "Steve", APP_ID_BOT)}
    yield opened
    for conn, _ in opened.values():
        conn.close()


def test_the_two_identities_are_accepted(hub, peers):
    _, server_ack = peers["host-b"]
    assert server_ack.get("type") == "hello_ack", f"a GamesAI instance is accepted: {server_ack}"
    assert server_ack.get("app") == APP_ID, f"hello_ack identifies the hub as games_ai: {server_ack}"
    assert server_ack.get("you") == APP_ID, \
        f"hello_ack tells the peer what it was taken for: {server_ack}"

    _, bot_ack = peers["Steve"]
    assert bot_ack.get("type") == "hello_ack", f"a Mineflayer bot is accepted: {bot_ack}"
    assert bot_ack.get("you") == APP_ID_BOT, f"the bot is told it was taken for a bot: {bot_ack}"
    assert bot_ack.get("app") == APP_ID, f"the hub still identifies itself as games_ai: {bot_ack}"

    assert wait_until(lambda: sorted(hub.peers) == ["Steve", "host-b"], timeout=0.3), \
        f"both peers are online: {hub.peers}"
    assert hub.peer_apps == {"host-b": APP_ID, "Steve": APP_ID_BOT}, \
        f"the hub recorded the identities: {hub.peer_apps}"
    assert hub.peers_of(APP_ID_BOT) == ["Steve"], \
        f"peers can be filtered by identity: {hub.peers_of(APP_ID_BOT)}"
    assert hub.peers_of(APP_ID) == ["host-b"], f"and the other way round: {hub.peers_of(APP_ID)}"


def test_an_unknown_identity_is_refused(hub, uri, peers):
    try:
        with raw_connect(uri) as conn:
            conn.send(json.dumps({"type": "hello", "app": "some_other_plugin", "protocol": 1,
                                  "server": "intruder"}))
            conn.recv(timeout=3)
    except ConnectionClosed as exc:
        code = close_code(exc)
    else:
        pytest.fail("an unknown app id is closed: the frame was answered")
    assert code == 4005, f"an unknown app id -> close 4005: {code}"

    try:
        with raw_connect(uri) as conn:
            conn.send(json.dumps({"type": "hello", "protocol": 1, "server": "no-app"}))
            conn.recv(timeout=3)
    except ConnectionClosed as exc:
        no_app_code = close_code(exc)
    else:
        pytest.fail("a hello without an app id is closed: the frame was answered")
    assert no_app_code == 4005, f"a hello without an app id -> close 4005: {no_app_code}"

    assert wait_until(lambda: sorted(hub.peers) == ["Steve", "host-b"], timeout=0.3), \
        f"the refused peers never registered: {hub.peers}"


def test_the_hub_adapts_its_fan_out(hub, peers):
    seen = {"host-b": [], "Steve": []}

    def send_and_collect(action, app):
        hub.broadcast(action, data={"n": action}, apps=app)
        collect(peers, seen)

    send_and_collect("exec_cluster", APP_ID)
    assert "exec_cluster" in seen["host-b"], \
        f"a cluster command reaches the GamesAI instance: {seen}"
    assert "exec_cluster" not in seen["Steve"], f"a cluster command never reaches the bot: {seen}"

    seen["host-b"].clear()
    seen["Steve"].clear()
    send_and_collect("bot_action", APP_ID_BOT)
    assert "bot_action" in seen["Steve"], f"a bot frame reaches the bot: {seen}"
    assert "bot_action" not in seen["host-b"], f"a bot frame does not reach the instance: {seen}"


def test_a_probe_is_answered_but_never_registered(hub, uri, peers):
    probe, probe_ack = join(uri, hub, "probe", APP_ID_BOT, probe=True)
    try:
        assert probe_ack.get("type") == "hello_ack", f"the probe got an ack: {probe_ack}"
        assert probe_ack.get("you") == APP_ID_BOT, \
            f"the probe is told what it was taken for: {probe_ack}"
        assert wait_until(lambda: sorted(hub.peers) == ["Steve", "host-b"], timeout=0.2), \
            f"the probe did not join: {hub.peers}"
    finally:
        probe.close()


def test_the_node_can_announce_the_bot_identity(hub, uri):
    node = CrossServerNode(uri, "BotNode", hub.issue("BotNode", app=APP_ID_BOT), app=APP_ID_BOT,
                           logger=LOG)
    try:
        assert node.start(timeout=5), "the node connects with the bot identity"
        assert wait_until(lambda: hub.peer_apps.get("BotNode") == APP_ID_BOT, timeout=0.3), \
            f"the hub sees it as a bot: {hub.peer_apps}"
        default_app = CrossServerNode(uri, "unused").app
        assert default_app == "games_ai_mcdr", f"default identity is still games_ai: {default_app}"
    finally:
        node.stop()
