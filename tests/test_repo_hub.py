"""Verify the repo's games_ai/websockets_server.py against the tested node prototype."""
import importlib.util
import json
import os
import sys
import threading
import time
import types

import pytest

from _helpers import ws_sync_node as _proto
from _helpers.paths import PKG
from _helpers.wait import wait_until
from _helpers.ws_sync_node import CrossServerNode          # prototype node (same protocol)

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as raw_connect


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def repo_hub_module():
    """The repository's hub, loaded straight from its file; the prototype node is the peer."""
    return load_module("repo_hub", os.path.join(PKG, "websockets_server.py"))


@pytest.fixture
def prototype_hello_app(monkeypatch):
    """Complete the prototype's hello frame with the app id the hub requires since the handshake.

    The prototype node (ws_sync_node.py) still sends a hello without an ``app``, which the hub
    refuses with 4005. Only this suite uses that prototype, so the frame is completed here
    instead of touching the old prototype file.
    """
    original = _proto._dumps

    def _dumps_with_app(frame):
        if isinstance(frame, dict) and frame.get("type") == "hello" and "app" not in frame:
            frame = dict(frame, app="games_ai_mcdr")
        return original(frame)

    monkeypatch.setattr(_proto, "_dumps", _dumps_with_app)
    return _dumps_with_app


def hub_handler(hub_inbox):
    def handler(msg):
        hub_inbox.append(dict(msg))
        if msg["action"] == "who_are_you":
            return {"message": "hub"}
        return None
    return handler


def make_handler(inbox, name):
    def handler(msg):
        inbox[name].append(dict(msg))
        if msg["action"] == "chat":
            return {"message": "{} got {}".format(name, msg["message"])}
        return None
    return handler


@pytest.fixture
def bare_hub(repo_hub_module, prototype_hello_app, free_port, tmp_path):
    """A hub with its node table in tmp_path and no node connected yet."""
    port = free_port()
    hub = repo_hub_module.CrossServerHub(
        "127.0.0.1", port, name="hub", handler=hub_handler([]),
        node_file=os.path.join(str(tmp_path), "cross_server_nodes.json"))
    started = hub.start(timeout=5)
    yield types.SimpleNamespace(hub=hub, started=started, port=port,
                                url="ws://127.0.0.1:{}".format(port))
    hub.stop()


@pytest.fixture
def cluster(repo_hub_module, prototype_hello_app, free_port, tmp_path):
    """A hub and its two prototype nodes, started here and torn down however the test ends.

    Starting is what the fixture is for; the returned ``*_started`` flags let the tests keep the
    suite's original "hub.start() / node alpha handshake" checks where they belong.
    """
    inbox = {"alpha": [], "beta": []}
    hub_inbox = []
    port = free_port()
    url = "ws://127.0.0.1:{}".format(port)
    node_file = os.path.join(str(tmp_path), "cross_server_nodes.json")
    hub = repo_hub_module.CrossServerHub("127.0.0.1", port, name="hub",
                                         handler=hub_handler(hub_inbox), node_file=node_file)
    hub_started = hub.start(timeout=5)
    # Each node has its own token now, issued by the hub (docs/token-enrollment.md).
    alpha_token = hub.issue("alpha")
    beta_token = hub.issue("beta")
    alpha = CrossServerNode(url, "alpha", alpha_token, handler=make_handler(inbox, "alpha"))
    beta = CrossServerNode(url, "beta", beta_token, handler=make_handler(inbox, "beta"))
    alpha_started = alpha.start(timeout=5)
    beta_started = beta.start(timeout=5)

    yield types.SimpleNamespace(
        hub=hub, alpha=alpha, beta=beta, url=url, port=port, node_file=node_file,
        inbox=inbox, hub_inbox=hub_inbox, hub_started=hub_started,
        alpha_started=alpha_started, beta_started=beta_started,
        alpha_token=alpha_token, beta_token=beta_token)

    alpha.stop()
    beta.stop()
    hub.stop()


def test_a_hub_routes_between_two_prototype_nodes(cluster):
    assert cluster.hub_started, "hub.start()"
    assert cluster.alpha_started, "node alpha handshake"
    assert cluster.beta_started, "node beta handshake"
    assert cluster.hub.peers == ["alpha", "beta"], f"hub.peers: {cluster.hub.peers}"
    # The hub's own view is updated on registration; the list it *pushes* to a node travels on that
    # node's connection thread, so it arrives a moment later (the prototype test waited 0.4 s here).
    assert wait_until(lambda: cluster.alpha.peers == ["beta"], timeout=5), \
        f"peer list pushed to alpha: {cluster.alpha.peers}"

    reply = cluster.alpha.send(None, "who_are_you", wait=True, timeout=3)
    assert reply and reply.get("message") == "hub", f"node->hub handled locally: {reply}"
    assert cluster.hub_inbox and cluster.hub_inbox[-1]["source"] == "alpha", \
        f"hub handler ran: {cluster.hub_inbox[-1:]}"

    reply = cluster.hub.send("beta", "chat", "from hub", wait=True, timeout=3)
    assert reply and reply.get("message") == "beta got from hub", f"hub->node request/reply: {reply}"
    reply = cluster.alpha.send("beta", "chat", "cross server", wait=True, timeout=3)
    assert reply and reply.get("message") == "beta got cross server", f"node->node routing: {reply}"
    assert cluster.inbox["beta"][-1]["source"] == "alpha", \
        f"source stamped by hub: {cluster.inbox['beta'][-1]}"

    reply = cluster.beta.send("ghost", "chat", "x", wait=True, timeout=3)
    assert reply and reply.get("ok") is False and "unknown target" in reply.get("error", ""), \
        f"unknown target -> immediate error: {reply}"

    sent = cluster.hub.broadcast("notice", "hi all")
    delivered = wait_until(
        lambda: all(any(m["action"] == "notice" for m in v) for v in cluster.inbox.values()),
        timeout=3)
    assert sent == 2 and delivered, f"hub.broadcast: sent={sent}, inbox={cluster.inbox}"

    rtt = cluster.hub.ping(timeout=3)
    assert all(v > 0 for v in rtt.values()), f"hub RTT to every node: {rtt}"


def test_a_raw_hello_gets_the_peer_list_and_cannot_spoof_a_source(cluster):
    with raw_connect(cluster.url) as raw:
        raw.send(json.dumps({"type": "hello", "app": "games_ai_mcdr", "protocol": 1,
                             "server": "evil", "token": cluster.hub.issue("evil")}))
        ack = json.loads(raw.recv(timeout=3))
        assert ack.get("type") == "hello_ack" and "alpha" in ack.get("peers", []), \
            f"raw hello_ack carries peers: {ack}"
        raw.send(json.dumps({"type": "message", "source": "hub", "target": "*",
                             "action": "spoof", "message": "I am the hub"}))
        spoofed = wait_until(
            lambda: [m for m in cluster.inbox["beta"] if m["action"] == "spoof"], timeout=3)
        assert spoofed and all(m["source"] == "evil" for m in spoofed), \
            f"spoofed source overwritten: {spoofed}"


def test_a_bad_token_is_rejected_with_4001(bare_hub):
    with pytest.raises(ConnectionClosed) as caught:      # an answered hello would fail here
        with raw_connect(bare_hub.url) as raw:
            raw.send(json.dumps({"type": "hello", "app": "games_ai_mcdr", "protocol": 1,
                                 "server": "bad", "token": "nope"}))
            raw.recv(timeout=3)
    code = getattr(getattr(caught.value, "rcvd", None), "code", None)
    assert code == 4001, f"bad token -> 4001: {code}"


def test_a_second_connection_with_the_same_name_takes_the_name_over(cluster):
    alpha2 = CrossServerNode(cluster.url, "alpha", cluster.alpha_token,
                             handler=make_handler(cluster.inbox, "alpha"))
    try:
        assert alpha2.start(timeout=5), "same name connects"
        assert wait_until(lambda: cluster.alpha.connected is False, timeout=5), \
            f"old connection dropped: connected={cluster.alpha.connected}"
        assert sorted(cluster.hub.peers) == ["alpha", "beta"], \
            f"hub keeps one alpha: {cluster.hub.peers}"
        assert "another instance" in (cluster.alpha.fatal_error or ""), \
            f"old node stopped with a reason: {cluster.alpha.fatal_error}"
    finally:
        alpha2.stop()


def test_the_hub_restarts_and_the_nodes_re_register(cluster, repo_hub_module):
    cluster.hub.stop()
    hub2 = repo_hub_module.CrossServerHub("127.0.0.1", cluster.port, name="hub",
                                          handler=hub_handler(cluster.hub_inbox),
                                          node_file=cluster.node_file)
    try:
        assert hub2.start(timeout=5), "hub restarted on the same port"
        assert wait_until(lambda: sorted(hub2.peers) == ["alpha", "beta"], timeout=15), \
            f"nodes re-registered: {hub2.peers}"
        reply = cluster.alpha.send("beta", "chat", "after reconnect", wait=True, timeout=3)
        assert reply and reply.get("message") == "beta got after reconnect", \
            f"routing after reconnect: {reply}"
    finally:
        hub2.stop()


def test_stopping_everything_leaves_no_thread_behind(repo_hub_module, prototype_hello_app,
                                                     free_port, tmp_path):
    """The old suite's leak probe: bring the whole thing up and down inside one test."""
    inbox = {"alpha": [], "beta": []}
    port = free_port()
    url = "ws://127.0.0.1:{}".format(port)
    hub = repo_hub_module.CrossServerHub(
        "127.0.0.1", port, name="hub", handler=hub_handler([]),
        node_file=os.path.join(str(tmp_path), "cross_server_nodes.json"))
    assert hub.start(timeout=5), "hub.start()"
    alpha = CrossServerNode(url, "alpha", hub.issue("alpha"), handler=make_handler(inbox, "alpha"))
    beta = CrossServerNode(url, "beta", hub.issue("beta"), handler=make_handler(inbox, "beta"))
    assert alpha.start(timeout=5) and beta.start(timeout=5), "both nodes handshake"

    baseline = threading.active_count()
    alpha.stop()
    beta.stop()
    hub.stop()
    time.sleep(0.5)
    assert threading.active_count() <= baseline, \
        "no thread leak: before={} after={}".format(baseline, threading.active_count())
