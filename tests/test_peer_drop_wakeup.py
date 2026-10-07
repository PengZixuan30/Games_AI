"""P4: a dropped peer must wake the callers waiting for it, not let them time out.

Before the fix a waiting call only woke on a reply or on its own timeout, so a node that crashed
mid-tool-call stalled the hub's AI round for the full 120 seconds.
"""
import json
import logging
import threading
import time

import pytest

import games_ai
from _helpers.wait import wait_until
from games_ai.websockets_client import APP_ID, CrossServerNode
from games_ai.websockets_server import CrossServerHub

from websockets.sync.client import connect as raw_connect

log = logging.getLogger("wake-hub")

#: The old script's 30s bound: long enough that a caller left on its own timeout cannot pass.
LONG = 30.0


@pytest.fixture
def hub(free_port, tmp_path):
    """A started hub with its node table under ``tmp_path``; stopped however the test ends."""
    hub = CrossServerHub("127.0.0.1", free_port(), name="hub", logger=log,
                         node_file=str(tmp_path / "nodes.json"))
    assert hub.start(timeout=5), f"the hub starts: {hub.is_running}"
    yield hub
    hub.stop()


def test_the_hub_wakes_callers_of_a_peer_that_drops(hub):
    peer = raw_connect("ws://127.0.0.1:{}".format(hub.port), open_timeout=5)
    try:
        peer.send(json.dumps({"type": "hello", "app": APP_ID, "protocol": 1, "server": "sleeper",
                              "token": hub.issue("sleeper", app=APP_ID), "version": "0.8.0"}))
        peer.recv(timeout=5)
        results = []

        def wait_for_peer():
            started = time.monotonic()
            results.append((hub.send("sleeper", "never_answered", wait=True, timeout=LONG),
                            time.monotonic() - started))

        worker = threading.Thread(target=wait_for_peer, daemon=True)
        worker.start()
        # Instead of the old fixed sleep: the call is registered as pending once it is really
        # blocked inside send(), which is the state this test needs.
        assert wait_until(lambda: hub._pending != {}, 5), hub._pending
        assert not results, f"the call is really waiting: {results}"
        peer.close()                                   # the node "crashes"
        worker.join(5)
        assert results, f"the caller was woken instead of timing out: {results}"
        reply, elapsed = results[0]
        assert elapsed < 3.0, f"...quickly: {elapsed}"
        assert bool(reply) and reply.get("ok") is False and reply.get("unknown") is True, \
            f"...with an unknown outcome: {reply}"
        assert "sleeper" in str(reply.get("error")), f"...that names the peer: {reply}"
        assert hub._pending == {}, f"no pending entry is left behind: {hub._pending}"
    finally:
        try:
            peer.close()
        except Exception:
            pass


def test_stopping_the_hub_wakes_everyone(hub):
    peer = raw_connect("ws://127.0.0.1:{}".format(hub.port), open_timeout=5)
    try:
        peer.send(json.dumps({"type": "hello", "app": APP_ID, "protocol": 1, "server": "sleeper2",
                              "token": hub.issue("sleeper2", app=APP_ID), "version": "0.8.0"}))
        peer.recv(timeout=5)
        stopped = []

        def wait_for_peer():
            started = time.monotonic()
            stopped.append((hub.send("sleeper2", "never", wait=True, timeout=LONG),
                            time.monotonic() - started))

        worker = threading.Thread(target=wait_for_peer, daemon=True)
        worker.start()
        assert wait_until(lambda: hub._pending != {}, 5), hub._pending
        hub.stop()
        worker.join(5)
        assert stopped, f"a stopping hub wakes its waiters: {stopped}"
        reply, elapsed = stopped[0]
        assert elapsed < 3.0, f"...quickly: {elapsed}"
        assert bool(reply) and reply.get("unknown") is True, f"...as unknown: {reply}"
    finally:
        try:
            peer.close()
        except Exception:
            pass
        hub.stop()


def test_the_node_wakes_callers_when_its_link_drops():
    node = CrossServerNode("ws://127.0.0.1:1", "node", logger=log, reconnect=False)
    wake = threading.Event()
    box = {}
    node._pending["manual#1"] = (wake, box)
    assert node.send(None, "anything", wait=True, timeout=0.2).get("ok") is False, \
        "the link has no connection to send on"
    node._pending["manual#1"] = (wake, box)          # put it back for the abort
    woken = node._abort_pending("the link to the hub dropped")
    assert woken == 1, f"the abort reports what it woke: {woken}"
    assert wake.is_set(), "...and the caller is awake"
    assert box["reply"].get("unknown") is True, f"...with an unknown outcome: {box['reply']}"
    assert node._pending == {}, f"the pending map is empty: {node._pending}"


def test_a_real_node_stopping_wakes_the_hub_side_call(hub):
    def slow_handler(msg):
        """Never answer in time: the point is that the call is still pending when the node dies."""
        time.sleep(4.0)
        return {"ok": True, "message": "late"}

    node = CrossServerNode("ws://127.0.0.1:{}".format(hub.port), "node3",
                           hub.issue("node3", app=APP_ID), handler=slow_handler, logger=log,
                           reconnect=False)
    try:
        assert node.start(timeout=5), f"the node connects: {node.connected}"
        waiting = []

        def wait_again():
            started = time.monotonic()
            waiting.append((hub.send("node3", "never_answered", wait=True, timeout=LONG),
                            time.monotonic() - started))

        worker = threading.Thread(target=wait_again, daemon=True)
        worker.start()
        assert wait_until(lambda: hub._pending != {}, 5), hub._pending
        node.stop()
        worker.join(5)
        assert waiting, f"stopping the node wakes the hub: {waiting}"
        reply, elapsed = waiting[0]
        assert elapsed < 3.0, f"...quickly: {elapsed}"
        assert bool(reply) and reply.get("unknown") is True, f"...as unknown: {reply}"
    finally:
        try:
            node.stop()
        except Exception:
            pass


class FakeManager:
    is_client = True
    is_server = False
    connected = True
    hub = None
    name = "hub"
    hub_name = "hub"

    def send_to(self, target, action, data=None, wait=False, timeout=None):
        return {"ok": False, "unknown": True, "error": "the link to 'node3' dropped before it answered"}


class FakeRemoteSource:
    origin = "node3"
    player = "Steve"
    is_console = False
    session = "s1"
    tools = []

    def get_permission_level(self):
        return 3


def test_the_plugin_turns_it_into_the_honest_sentence(monkeypatch):
    monkeypatch.setattr(games_ai, "_cross_server", FakeManager(), raising=False)

    text = games_ai.route_remote_tool_call(FakeRemoteSource(), "some_tool", {})

    assert "unknown" in text.lower(), f"the model is told the outcome is unknown: {text}"
    assert "Do not retry" in text, f"...and that it must not retry: {text}"
    assert "120" not in text, f"...without naming a timeout: {text}"
