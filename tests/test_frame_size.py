"""P3: an oversized frame must never take the link down.

Before the fix there was no check on the sending side: the receiver closed the connection with
1009 and every conversation on it died with it.
"""
import json
import logging
import time

import pytest

from _helpers.wait import wait_until
from games_ai.websockets_client import FRAME_MARGIN, MAX_MESSAGE_SIZE, CrossServerNode
from games_ai.websockets_server import CrossServerHub

log = logging.getLogger(__name__)

BIG = "x" * (MAX_MESSAGE_SIZE + 4096)


class FakeConnection:
    """Records what a send path tried to put on the wire."""

    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, payload):
        self.sent.append(payload)

    def close(self, code=None, reason=None):
        self.closed = True


def size_of(frame):
    return len(json.dumps(frame).encode("utf-8"))


@pytest.fixture
def hub(free_port, tmp_path):
    """The hub whose send path is under test. It is never started: only ``_send`` is called."""
    return CrossServerHub("127.0.0.1", free_port(), name="hub", logger=log,
                          node_file=str(tmp_path / "nodes.json"))


@pytest.fixture
def client():
    """A node that never connects: its send path is exercised directly, too."""
    return CrossServerNode("ws://127.0.0.1:1", "node", logger=log)


def answer_big(msg):
    if msg.get("action") == "big":
        return {"ok": True, "message": "y" * (MAX_MESSAGE_SIZE + 4096), "data": {}}
    if msg.get("action") == "small":
        return {"ok": True, "message": "fine", "data": {}}
    return None


def test_the_hubs_send_path_never_puts_an_oversized_frame_on_the_wire(hub):
    """Section: the hub's send path."""
    conn = FakeConnection()
    reply = {"type": "reply", "request_id": "r1", "source": "node", "target": "hub", "ok": True,
             "message": BIG, "data": {}, "error": None}
    assert size_of(reply) > MAX_MESSAGE_SIZE, \
        f"the tool result really is over the limit: {size_of(reply)}"
    sent_ok = hub._send(conn, reply)
    assert sent_ok is True, "the frame is still 'sent' (as something else)"
    assert len(conn.sent) == 1 and size_of(json.loads(conn.sent[0])) < MAX_MESSAGE_SIZE, \
        f"...and what went out is a small reply: {[len(s) for s in conn.sent]}"
    shrunk = json.loads(conn.sent[0])
    assert shrunk.get("request_id") == "r1", f"...that keeps the request_id: {shrunk}"
    assert shrunk.get("ok") is False and "too large" in str(shrunk.get("error")), \
        f"...and says why it failed: {shrunk}"

    conn = FakeConnection()
    note = {"type": "message", "request_id": "r2", "source": "hub", "target": "node",
            "action": "command_reply", "message": "",
            "data": {"session": "s1", "text": {"text": BIG}}}
    assert size_of(note) > MAX_MESSAGE_SIZE, "an oversized streamed reply is over the limit"
    assert hub._send(conn, note) is True, "it goes out as a note"
    small = json.loads(conn.sent[0])
    assert small.get("data", {}).get("session") == "s1", f"...with the session kept: {small}"
    assert "too large" in str(small.get("data", {}).get("text")), \
        f"...and a readable text: {small}"
    assert size_of(small) < MAX_MESSAGE_SIZE, f"...under the limit: {size_of(small)}"

    conn = FakeConnection()
    other = {"type": "message", "request_id": "r3", "source": "hub", "target": "node",
             "action": "bot_action", "message": BIG, "data": {}}
    assert hub._send(conn, other) is False, \
        "an oversized frame with no smaller equivalent is dropped"
    assert conn.sent == [], f"...without sending anything: {conn.sent}"

    conn = FakeConnection()
    normal = {"type": "message", "request_id": "r4", "source": "hub", "target": "node",
              "action": "ping", "message": "hi", "data": {}}
    assert hub._send(conn, normal) is True and json.loads(conn.sent[0]).get("message") == "hi", \
        f"a normal frame is untouched: {conn.sent}"


def test_the_nodes_send_path_never_puts_an_oversized_frame_on_the_wire(client):
    """Section: the node's send path."""
    conn = FakeConnection()
    node_reply = {"type": "reply", "request_id": "n1", "source": "node", "target": "hub",
                  "ok": True, "message": "", "data": {"status": "success", "data": {"blob": BIG}}}
    assert client._send_json(conn, node_reply) is True, "an oversized tool answer is shrunk"
    small = json.loads(conn.sent[0])
    assert small.get("ok") is False and "too large" in str(small.get("error")), \
        f"...into an honest error: {small}"
    assert size_of(small) < MAX_MESSAGE_SIZE, f"...under the limit: {size_of(small)}"

    conn = FakeConnection()
    node_note = {"type": "message", "request_id": "n2", "source": "node", "target": None,
                 "action": "command_reply", "message": "",
                 "data": {"session": "s2", "text": BIG}}
    assert client._send_json(conn, node_note) is True, \
        "an oversized streamed line becomes a note"
    small = json.loads(conn.sent[0])
    assert small.get("data", {}).get("session") == "s2", f"...keeping the session: {small}"

    conn = FakeConnection()
    assert client._send_json(conn, {"type": "message", "request_id": "n3",
                                    "action": "ping"}) is True \
        and json.loads(conn.sent[0]).get("action") == "ping", "a normal client frame is untouched"

    assert MAX_MESSAGE_SIZE == 1 << 20 and FRAME_MARGIN == 1024, \
        f"both halves agree on the limit and the margin: {(MAX_MESSAGE_SIZE, FRAME_MARGIN)}"


def test_over_a_real_link_the_connection_survives(free_port, tmp_path):
    """Section: over a real link the connection survives."""
    port = free_port()
    uri = "ws://127.0.0.1:{}".format(port)
    live = CrossServerHub("127.0.0.1", port, name="hub", logger=log,
                          node_file=str(tmp_path / "live.json"))
    live.start(timeout=5)
    token = live.issue("big-node", app="games_ai_mcdr")
    node = CrossServerNode(uri, "big-node", token, handler=answer_big, logger=log)
    try:
        node.start(timeout=5)
        assert wait_until(lambda: "big-node" in live.peers, timeout=5), \
            f"the node registered with the hub: {live.peers}"
        started = time.monotonic()
        result = live.send("big-node", "big", wait=True, timeout=5)
        elapsed = time.monotonic() - started
        assert isinstance(result, dict), \
            f"the caller gets an answer instead of a dead link: {result}"
        assert result.get("ok") is False and "too large" in str(result.get("error")), \
            f"...that is an honest failure: {result}"
        assert elapsed < 3.0, f"...without waiting for the timeout: {elapsed}"
        assert node.connected, f"the node is still connected: {node.connected}"
        assert live.is_running, "the hub is still running"
        follow_up = live.send("big-node", "small", wait=True, timeout=5)
        assert bool(follow_up and follow_up.get("ok")), \
            f"...and the link still carries normal frames: {follow_up}"
    finally:
        try:
            node.stop()
        except Exception:
            pass
        live.stop()
