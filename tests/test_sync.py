"""End to end test: hub + two nodes over real TCP sockets, sync flavour."""
import json
import threading
import time
import types

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as raw_connect

from _helpers.wait import wait_until
from _helpers.ws_sync_hub import CrossServerHub
from _helpers.ws_sync_node import CrossServerNode

TOKEN = "s3cret"


def hub_handler(inbox):
    """Answer ``who_are_you`` on the hub and record every frame it sees."""
    def handler(msg):
        inbox.append(dict(msg))
        if msg["action"] == "who_are_you":
            return {"message": "hub", "data": {"peers": ["alpha", "beta"]}}
        return None

    return handler


def node_handler(inbox, name):
    """Answer ``chat`` for one node and record every frame it sees."""
    def handler(msg):
        inbox[name].append(dict(msg))
        if msg["action"] == "chat":
            return {"message": "{} received: {}".format(name, msg["message"])}
        return None

    return handler


@pytest.fixture
def hub_inbox():
    return []


@pytest.fixture
def node_inbox():
    return {"alpha": [], "beta": []}


@pytest.fixture
def cluster(free_port, hub_inbox, node_inbox):
    """A started hub with its two nodes; every one of them is stopped when the test ends.

    Each test gets its own network: the later sections kick a node off the hub and restart it,
    so sharing one cluster across tests would make the module order-dependent.
    """
    hub = CrossServerHub("127.0.0.1", free_port(), name="hub", token=TOKEN,
                         handler=hub_handler(hub_inbox))
    hub_started = hub.start(timeout=5)
    uri = "ws://127.0.0.1:{}".format(hub.port)
    alpha = CrossServerNode(uri, "alpha", TOKEN, version="0.7.3",
                            handler=node_handler(node_inbox, "alpha"))
    beta = CrossServerNode(uri, "beta", TOKEN, version="0.7.3",
                           handler=node_handler(node_inbox, "beta"))
    alpha_started = alpha.start(timeout=5)
    beta_started = beta.start(timeout=5)
    try:
        yield types.SimpleNamespace(hub=hub, alpha=alpha, beta=beta, uri=uri,
                                    hub_started=hub_started, alpha_started=alpha_started,
                                    beta_started=beta_started)
    finally:
        for handle in (alpha, beta, hub):
            try:
                handle.stop()
            except Exception:
                pass


@pytest.fixture
def spawn_hub(free_port, hub_inbox):
    """A factory for extra hubs (a restart on the same port); all of them stopped with the test."""
    created = []

    def spawn(port=None, handler=None, **kwargs):
        hub = CrossServerHub("127.0.0.1", port or free_port(), name="hub", token=TOKEN,
                             handler=handler or hub_handler(hub_inbox), **kwargs)
        created.append(hub)
        return hub

    yield spawn
    for hub in created:
        try:
            hub.stop()
        except Exception:
            pass


@pytest.fixture
def spawn_node(cluster):
    """A factory for extra nodes on the cluster's hub; all of them stopped with the test."""
    created = []

    def spawn(name, token=TOKEN, handler=None, **kwargs):
        node = CrossServerNode(cluster.uri, name, token, version="0.7.3",
                               handler=handler, **kwargs)
        created.append(node)
        return node

    yield spawn
    for node in created:
        try:
            node.stop()
        except Exception:
            pass


def test_start_hub_and_two_nodes(cluster):
    """Section 1: start hub + two nodes."""
    assert cluster.hub_started, f"hub.start(): {cluster.hub.is_running}"
    assert cluster.hub.is_running, "hub.is_running"
    assert cluster.alpha_started, "alpha.start() handshake"
    assert cluster.beta_started, "beta.start() handshake"
    assert wait_until(lambda: cluster.hub.peers == ["alpha", "beta"], timeout=5), \
        f"hub peers == [alpha, beta]: {cluster.hub.peers}"
    assert wait_until(lambda: cluster.alpha.peers == ["beta"], timeout=5), \
        f"alpha sees peer beta: {cluster.alpha.peers}"
    assert wait_until(lambda: cluster.beta.peers == ["alpha"], timeout=5), \
        f"beta sees peer alpha: {cluster.beta.peers}"


def test_node_to_hub_request_response(cluster, hub_inbox):
    """Section 2: node -> hub request/response."""
    reply = cluster.alpha.send(None, "who_are_you", wait=True, timeout=3)
    assert reply and reply.get("ok") and reply.get("message") == "hub", \
        f"node->hub reply ok: {reply}"
    assert hub_inbox and hub_inbox[-1]["source"] == "alpha", \
        f"hub handler saw source=alpha: {hub_inbox[-3:]}"


def test_hub_to_node_request_response(cluster, node_inbox):
    """Section 3: hub -> node request/response."""
    reply = cluster.hub.send("beta", "chat", "hello beta", wait=True, timeout=3)
    assert reply and reply.get("ok"), f"hub->node reply ok: {reply}"
    assert reply and reply.get("message") == "beta received: hello beta", \
        f"hub->node reply body: {reply}"
    assert node_inbox["beta"][-1]["source"] == "hub", \
        f"beta saw source=hub: {node_inbox['beta'][-1]}"


def test_node_to_node_request_response(cluster, node_inbox):
    """Section 4: node -> node (the cross-server case)."""
    reply = cluster.alpha.send("beta", "chat", "hi from alpha", wait=True, timeout=3)
    assert reply and reply.get("ok"), f"alpha->beta reply ok: {reply}"
    assert reply and reply.get("message") == "beta received: hi from alpha", \
        f"alpha->beta reply body: {reply}"
    assert node_inbox["beta"][-1]["source"] == "alpha", \
        f"beta saw source=alpha: {node_inbox['beta'][-1]}"


def test_broadcast_reaches_every_node_but_not_the_sender(cluster, node_inbox):
    """Section 5: broadcast."""
    cluster.alpha.send("*", "shout", "everyone", wait=True, timeout=3)
    assert wait_until(lambda: any(m["action"] == "shout" for m in node_inbox["beta"]), timeout=3), \
        f"'*' reached beta: {node_inbox['beta']}"
    assert not any(m["action"] == "shout" for m in node_inbox["alpha"]), \
        f"'*' not echoed to sender: {node_inbox['alpha']}"

    cluster.alpha.send("*", "shout2", "again", event=True)
    assert wait_until(lambda: any(m["action"] == "shout2" for m in node_inbox["beta"]), timeout=3), \
        f"event frame reached beta: {node_inbox['beta']}"

    sent = cluster.hub.broadcast("notice", "restart in 5 min")
    delivered = wait_until(lambda: all(any(m["action"] == "notice" for m in v)
                                       for v in node_inbox.values()), timeout=3)
    assert sent == 2 and delivered, f"hub.broadcast reached both: {sent}"


def test_an_unknown_target_answers_immediately(cluster):
    """Section 6: unknown target answers immediately, no hang."""
    started = time.perf_counter()
    reply = cluster.beta.send("ghost", "chat", "anyone?", wait=True, timeout=3)
    elapsed = time.perf_counter() - started
    assert reply and reply.get("ok") is False and "unknown target" in reply.get("error", ""), \
        f"unknown target -> explicit error: {reply}"
    assert elapsed < 1.0, f"unknown target did not wait for the timeout: {elapsed}"


def test_ping_round_trips(cluster):
    """Section 7: ping / rtt."""
    rtt = cluster.alpha.ping("beta", timeout=3)
    assert rtt > 0, f"node ping peer > 0: {rtt}"
    pings = cluster.hub.ping(timeout=3)
    assert all(v > 0 for v in pings.values()), f"hub pings every node: {pings}"


def test_a_spoofed_source_is_relabelled_by_the_hub(cluster, node_inbox):
    """Section 8: spoofed source is overwritten by the hub."""
    with raw_connect(cluster.uri) as raw:
        raw.send(json.dumps({"type": "hello", "protocol": 1, "server": "evil", "token": TOKEN}))
        ack = json.loads(raw.recv(timeout=3))
        assert ack.get("type") == "hello_ack", f"raw client got hello_ack: {ack}"
        raw.send(json.dumps({"type": "message", "source": "hub", "target": "*",
                             "action": "spoof", "message": "I am the hub"}))
        assert wait_until(lambda: any(m["action"] == "spoof"
                                      for m in node_inbox["beta"] + node_inbox["alpha"]), timeout=3), \
            "the spoof frame reached a node"
    spoofed = [m for m in node_inbox["beta"] + node_inbox["alpha"] if m["action"] == "spoof"]
    assert spoofed and all(m["source"] == "evil" for m in spoofed), \
        f"spoof frame delivered but relabelled: {spoofed}"


def test_a_bad_token_is_refused_and_is_fatal(cluster, spawn_node):
    """Section 9: bad token is refused with 4001 and retrying is fatal."""
    try:
        with raw_connect(cluster.uri) as raw:
            raw.send(json.dumps({"type": "hello", "protocol": 1, "server": "bad",
                                 "token": "nope"}))
            raw.recv(timeout=3)
    except ConnectionClosed as exc:
        code = getattr(getattr(exc, "rcvd", None), "code", None)
        assert code == 4001, f"bad token -> close 4001: {code}"
    else:
        pytest.fail("bad token closed the connection: the frame was answered")

    bad = spawn_node("bad", token="nope", reconnect=True)
    assert bad.start(timeout=3) is False, "bad-token node never connects"
    assert wait_until(lambda: "token" in (bad.fatal_error or ""), timeout=5), \
        f"bad-token node gave up instead of looping: {bad.fatal_error}"


def test_the_same_name_replaces_the_old_connection(cluster, node_inbox, spawn_node):
    """Section 10: same name -> the old connection is replaced (4003)."""
    alpha2 = spawn_node("alpha", handler=node_handler(node_inbox, "alpha"))
    assert alpha2.start(timeout=5), "second 'alpha' connects"
    assert wait_until(lambda: not cluster.alpha.connected, timeout=5), \
        f"old alpha was dropped: {cluster.alpha.connected}"
    assert sorted(cluster.hub.peers) == ["alpha", "beta"], \
        f"hub still has one alpha: {cluster.hub.peers}"
    assert wait_until(lambda: "another instance" in (cluster.alpha.fatal_error or ""), timeout=5), \
        f"old alpha stopped with a clear reason: {cluster.alpha.fatal_error}"


def test_a_restarted_hub_gets_both_nodes_back(cluster, spawn_hub):
    """Section 11: hub restart -> node reconnects by itself."""
    hub2 = spawn_hub(port=cluster.hub.port)
    cluster.hub.stop()
    assert wait_until(lambda: not cluster.alpha.connected and not cluster.beta.connected, timeout=3), \
        "nodes noticed the hub is gone"
    assert hub2.start(timeout=5), "new hub on the same port"
    assert wait_until(lambda: sorted(hub2.peers) == ["alpha", "beta"], timeout=15), \
        f"both nodes re-registered: {hub2.peers}"

    reply = cluster.alpha.send("beta", "chat", "after reconnect", wait=True, timeout=3)
    assert reply and reply.get("ok") and reply.get("message") == "beta received: after reconnect", \
        f"routing works again after reconnect: {reply}"


def test_clean_shutdown(cluster):
    """Section 12: clean shutdown."""
    baseline = threading.active_count()
    cluster.alpha.stop()
    cluster.beta.stop()
    cluster.hub.stop()
    assert wait_until(lambda: threading.active_count() <= baseline, timeout=5), \
        "no threads leaked: before={} after={}".format(baseline, threading.active_count())
    assert not cluster.alpha.connected and not cluster.beta.connected, "nodes report disconnected"
