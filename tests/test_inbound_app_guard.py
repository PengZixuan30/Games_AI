"""P1: a bot identity may only answer bot_action -- never command or route anything.

The audit found that a peer which registered as `mineflayer_bot` (which the hub provisions
automatically over loopback -- and a tunnel makes every peer look like loopback) could send
`command` / `exec_cluster` frames that the hub executed as a level 4 console command. These
checks pin the fix, and pin that the legitimate traffic is untouched.
"""
import json
import logging
import threading
import time
import types

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as raw_connect

from _helpers.wait import wait_until
import games_ai
from games_ai.websockets_client import APP_ID, APP_ID_BOT
from games_ai.websockets_server import CrossServerHub

log = logging.getLogger(__name__)


class FakePluginServer:
    def __init__(self):
        self.executed = []

    def execute_command(self, raw, source):
        self.executed.append((raw, source.get_permission_level()))
        source.reply("executed")


def hello(name, app, token=None):
    frame = {"type": "hello", "app": app, "protocol": 1, "server": name, "version": "0.8.0"}
    if token:
        frame["token"] = token
    return frame


def command_frame(action, request_id, command="!!gamesai config set permission 0"):
    return {"type": "message", "request_id": request_id, "action": action, "message": "",
            "data": {"command": command, "player": None, "console": True, "permission": 4,
                     "session": "s-evil", "origin": "hub"}}


def recv_json(conn, timeout=2.0):
    """The next frame as a dict, or None when nothing arrives in time."""
    try:
        raw = conn.recv(timeout=timeout)
    except ConnectionClosed:
        return None
    except Exception:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def drain(conn, seconds=0.6):
    """Swallow the frames the hub pushes on registration (hello_ack, peers event)."""
    deadline = time.time() + seconds
    seen = []
    while time.time() < deadline:
        frame = recv_json(conn, timeout=0.2)
        if frame is None:
            break
        seen.append(frame)
    return seen


@pytest.fixture
def guarded_hub(free_port, tmp_path, monkeypatch):
    """A started hub wired to a fake plugin instance, the way the plugin wires ``_on_cross_message``.

    ``monkeypatch`` rebinds ``games_ai._server_ref`` and restores it however the test ends, so the
    fake instance cannot leak into the next test.
    """
    fake = FakePluginServer()
    monkeypatch.setattr(games_ai, "_server_ref", fake, raising=False)
    hub = CrossServerHub("127.0.0.1", free_port(), name="hub", logger=log,
                         node_file=str(tmp_path / "nodes.json"),
                         handler=games_ai._on_cross_message)
    assert hub.start(timeout=5), "the hub started"
    try:
        yield hub, fake
    finally:
        hub.stop()


@pytest.fixture
def bot_peer(guarded_hub):
    """A raw peer that registered under the bot app id, and the hello_ack it got."""
    hub, _fake = guarded_hub
    conn = raw_connect("ws://127.0.0.1:{}".format(hub.port), open_timeout=5)
    try:
        conn.send(json.dumps(hello("not-a-real-bot", APP_ID_BOT)))
        ack = recv_json(conn)
        drain(conn)
        yield types.SimpleNamespace(conn=conn, ack=ack)
    finally:
        try:
            conn.close()
        except Exception:
            pass


@pytest.fixture
def instance(guarded_hub):
    """A factory for raw peers registered as real GamesAI instances; all closed with the test."""
    hub, _fake = guarded_hub
    created = []

    def join(name):
        conn = raw_connect("ws://127.0.0.1:{}".format(hub.port), open_timeout=5)
        created.append(conn)
        conn.send(json.dumps(hello(name, APP_ID, hub.issue(name, app=APP_ID))))
        recv_json(conn)
        drain(conn)
        return conn

    yield join
    for conn in created:
        try:
            conn.close()
        except Exception:
            pass


def test_a_bot_peer_may_not_command(guarded_hub, bot_peer):
    """Section: a bot peer may not command."""
    hub, fake = guarded_hub
    bot = bot_peer.conn
    assert bool(bot_peer.ack and bot_peer.ack.get("token")), \
        f"the hub still auto-provisions a token for a local bot: {bot_peer.ack}"

    bot.send(json.dumps(command_frame("command", "evil#1")))
    answer = recv_json(bot)
    assert bool(answer and answer.get("ok") is False
                and "bot_action" in str(answer.get("error"))), \
        f"a command frame from a bot is refused: {answer}"
    time.sleep(0.3)
    assert fake.executed == [], f"...and nothing was executed on the hub: {fake.executed}"

    for action in ("command_cluster", "exec_cluster", "tool_call"):
        fake.executed.clear()
        bot.send(json.dumps(command_frame(action, "evil#{}".format(action))))
        recv_json(bot, timeout=1.0)
        time.sleep(0.2)
        assert fake.executed == [], f"{action} from a bot is refused too: {fake.executed}"

    bot.send(json.dumps({"type": "event", "request_id": "evil#event", "target": "*",
                         "action": "command", "message": "",
                         "data": {"command": "!!gamesai reload", "console": True,
                                  "permission": 4}}))
    time.sleep(0.3)
    assert fake.executed == [], \
        f"an event frame from a bot is dropped without executing anything: {fake.executed}"
    assert hub.peers == ["not-a-real-bot"] or "not-a-real-bot" in hub.peers, \
        f"...and the bot connection stays open: {hub.peers}"


def test_the_bots_own_traffic_still_works(guarded_hub, bot_peer):
    """Section: the bot's own traffic still works."""
    hub, _fake = guarded_hub
    bot = bot_peer.conn

    bot.send(json.dumps({"type": "message", "request_id": "ping#1", "action": "ping"}))
    pong = recv_json(bot)
    assert bool(pong and pong.get("message") == "pong"), f"a bot may still ping the hub: {pong}"

    asked = []

    def ask_bot():
        asked.append(hub.send("not-a-real-bot", "bot_action", "",
                              data={"action": "get_state"}, wait=True, timeout=5))

    worker = threading.Thread(target=ask_bot, daemon=True)
    worker.start()
    request = recv_json(bot, timeout=5)
    assert bool(request and request.get("action") == "bot_action"), \
        f"the hub still sends bot_action to the bot: {request}"
    if request:
        bot.send(json.dumps({"type": "reply", "request_id": request.get("request_id"),
                             "source": "not-a-real-bot", "target": "hub", "ok": True,
                             "data": {"status": "success"}}))
    worker.join(5)
    assert bool(asked and asked[0] and asked[0].get("ok")), \
        f"...and its reply still comes back: {asked}"


def test_a_real_instance_is_unaffected(guarded_hub, instance):
    """Section: a real instance is unaffected."""
    hub, fake = guarded_hub
    inst = instance("inst-a")
    fake.executed.clear()
    inst.send(json.dumps(command_frame("command", "ok#1", "!!gamesai speedtest")))
    answer = recv_json(inst)
    assert wait_until(lambda: bool(fake.executed), timeout=3), \
        f"the hub executed the command on the instance: {fake.executed}"
    assert fake.executed and fake.executed[0][0] == "!!gamesai speedtest", \
        f"an instance may still run commands on the hub: {fake.executed}"
    assert fake.executed and fake.executed[0][1] == 4, \
        f"...and it ran as console: {fake.executed}"
    assert bool(answer and answer.get("ok")), f"...with a normal reply: {answer}"

    # relaying between instances must survive the filter
    inst_b = instance("inst-b")
    relay = {"type": "message", "request_id": "relay#1", "target": "inst-b", "action": "command",
             "message": "", "data": {"command": "!!gamesai debug", "console": True,
                                     "permission": 4, "origin": "inst-a"}}
    inst.send(json.dumps(relay))
    forwarded = recv_json(inst_b, timeout=3)
    assert bool(forwarded), f"one instance can still address another: {forwarded}"
    assert bool(forwarded and forwarded.get("source") == "inst-a"), \
        f"...and the relayed frame keeps its sender: {forwarded}"


def test_a_bot_cannot_reach_a_peer(guarded_hub, bot_peer, instance):
    """Section: the bot cannot reach a peer."""
    hub, fake = guarded_hub
    inst_b = instance("inst-b")
    fake.executed.clear()
    bot_peer.conn.send(json.dumps({"type": "message", "request_id": "evil#relay",
                                   "target": "inst-b", "action": "command", "message": "",
                                   "data": {"command": "!!gamesai reload", "console": True,
                                            "permission": 4}}))
    time.sleep(0.4)
    assert recv_json(inst_b, timeout=0.5) is None, \
        "a bot cannot relay a command to another instance: a frame arrived"
    assert fake.executed == [], f"...and nothing was executed anywhere: {fake.executed}"
