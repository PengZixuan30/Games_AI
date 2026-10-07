"""Full end to end test of the repo files: games_ai/websockets_server.py + websockets_client.py."""
import importlib.util
import json
import os
import sys
import threading
import time
import types

import pytest

from _helpers.paths import PKG
from _helpers.wait import wait_until

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as raw_connect


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def repo_modules():
    """Both halves of the cross-server link, loaded straight from their files."""
    return types.SimpleNamespace(
        hub=load_module("repo_both_hub", os.path.join(PKG, "websockets_server.py")),
        node=load_module("repo_both_node", os.path.join(PKG, "websockets_client.py")),
    )


def hub_handler(hub_inbox):
    def handler(msg):
        hub_inbox.append(dict(msg))
        if msg["action"] == "who_are_you":
            return {"message": "hub", "data": {"peers": ["alpha", "beta"]}}
        return None
    return handler


def make_handler(inbox, name):
    def handler(msg):
        inbox[name].append(dict(msg))
        if msg["action"] == "chat":
            return {"message": "{} received: {}".format(name, msg["message"])}
        return None
    return handler


@pytest.fixture
def cluster(repo_modules, free_port, tmp_path):
    """A hub and its two nodes on a free loopback port, torn down however the test ends.

    The node table lives in a file under ``tmp_path``, so a hub restarted inside one test keeps
    every token valid -- that is exactly what a cluster reload does.
    """
    hub_inbox = []
    inbox = {"alpha": [], "beta": []}
    port = free_port()
    url = "ws://127.0.0.1:{}".format(port)
    node_file = os.path.join(str(tmp_path), "cross_server_nodes.json")
    hub = repo_modules.hub.CrossServerHub("127.0.0.1", port, name="hub",
                                          handler=hub_handler(hub_inbox), node_file=node_file)
    hub_started = hub.start(timeout=5)
    # One token per node, issued by the hub (docs/token-enrollment.md).
    alpha_token = hub.issue("alpha")
    beta_token = hub.issue("beta")
    alpha = repo_modules.node.CrossServerNode(url, "alpha", alpha_token, version="0.7.3",
                                              handler=make_handler(inbox, "alpha"))
    beta = repo_modules.node.CrossServerNode(url, "beta", beta_token, version="0.7.3",
                                             handler=make_handler(inbox, "beta"))
    alpha_started = alpha.start(timeout=5)
    beta_started = beta.start(timeout=5)

    yield types.SimpleNamespace(
        modules=repo_modules, hub=hub, alpha=alpha, beta=beta, url=url, port=port,
        node_file=node_file, inbox=inbox, hub_inbox=hub_inbox, hub_started=hub_started,
        alpha_started=alpha_started, beta_started=beta_started,
        alpha_token=alpha_token, beta_token=beta_token)

    alpha.stop()
    beta.stop()
    hub.stop()


def test_start_hub_and_two_nodes(cluster):
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


def test_node_to_hub_request_response(cluster):
    reply = cluster.alpha.send(None, "who_are_you", wait=True, timeout=3)

    assert reply and reply.get("ok") and reply.get("message") == "hub", \
        f"node->hub reply ok: {reply}"
    assert cluster.hub_inbox and cluster.hub_inbox[-1]["source"] == "alpha", \
        f"hub handler saw source=alpha: {cluster.hub_inbox[-3:]}"


def test_hub_to_node_request_response(cluster):
    reply = cluster.hub.send("beta", "chat", "hello beta", wait=True, timeout=3)

    assert reply and reply.get("ok"), f"hub->node reply ok: {reply}"
    assert reply and reply.get("message") == "beta received: hello beta", \
        f"hub->node reply body: {reply}"
    assert cluster.inbox["beta"][-1]["source"] == "hub", \
        f"beta saw source=hub: {cluster.inbox['beta'][-1]}"


def test_node_to_node_routing(cluster):
    reply = cluster.alpha.send("beta", "chat", "hi from alpha", wait=True, timeout=3)

    assert reply and reply.get("ok"), f"alpha->beta reply ok: {reply}"
    assert reply and reply.get("message") == "beta received: hi from alpha", \
        f"alpha->beta reply body: {reply}"
    assert cluster.inbox["beta"][-1]["source"] == "alpha", \
        f"beta saw source=alpha: {cluster.inbox['beta'][-1]}"


def test_broadcast(cluster):
    cluster.alpha.send("*", "shout", "everyone", wait=True, timeout=3)
    assert wait_until(lambda: any(m["action"] == "shout" for m in cluster.inbox["beta"]), timeout=3), \
        f"'*' reached beta: {cluster.inbox['beta']}"
    assert not any(m["action"] == "shout" for m in cluster.inbox["alpha"]), \
        f"'*' not echoed to sender: {cluster.inbox['alpha']}"

    cluster.alpha.send("*", "shout2", "again", event=True)
    assert wait_until(lambda: any(m["action"] == "shout2" for m in cluster.inbox["beta"]), timeout=3), \
        f"event frame reached beta: {cluster.inbox['beta']}"

    sent = cluster.hub.broadcast("notice", "restart in 5 min")
    delivered = wait_until(lambda: all(any(m["action"] == "notice" for m in v)
                                       for v in cluster.inbox.values()), timeout=3)
    assert sent == 2 and delivered, f"hub.broadcast reached both: {sent}"


def test_an_unknown_target_answers_immediately(cluster):
    t0 = time.perf_counter()
    reply = cluster.beta.send("ghost", "chat", "anyone?", wait=True, timeout=3)
    dt = time.perf_counter() - t0

    assert reply and reply.get("ok") is False and "unknown target" in reply.get("error", ""), \
        f"unknown target -> explicit error: {reply}"
    assert dt < 1.0, f"unknown target did not wait for the timeout: {dt}"


def test_ping_round_trips(cluster):
    rtt = cluster.alpha.ping("beta", timeout=3)
    assert rtt > 0, f"node ping peer > 0: {rtt}"

    pings = cluster.hub.ping(timeout=3)
    assert all(v > 0 for v in pings.values()), f"hub pings every node: {pings}"


def test_a_raw_peer_is_relabelled_by_the_hub(cluster):
    with raw_connect(cluster.url) as raw:
        raw.send(json.dumps({"type": "hello", "app": "games_ai_mcdr", "protocol": 1,
                             "server": "evil", "token": cluster.hub.issue("evil")}))
        ack = json.loads(raw.recv(timeout=3))
        assert ack.get("type") == "hello_ack", f"raw client got hello_ack: {ack}"
        assert ack.get("app") == "games_ai_mcdr", f"hello_ack carries the app id: {ack}"
        raw.send(json.dumps({"type": "message", "source": "hub", "target": "*",
                             "action": "spoof", "message": "I am the hub"}))

    spoofed = wait_until(
        lambda: [m for m in cluster.inbox["beta"] + cluster.inbox["alpha"]
                 if m["action"] == "spoof"], timeout=3)
    assert spoofed and all(m["source"] == "evil" for m in spoofed), \
        f"spoof frame delivered but relabelled: {spoofed}"


def test_a_client_without_the_app_id_is_refused_with_4005(cluster):
    with pytest.raises(ConnectionClosed) as caught:      # an answered frame would fail here
        with raw_connect(cluster.url) as raw:
            raw.send(json.dumps({"type": "hello", "protocol": 1, "server": "foreign"}))
            raw.recv(timeout=3)
    code = getattr(getattr(caught.value, "rcvd", None), "code", None)
    assert code == 4005, f"hello without app id -> close 4005: {code}"


def test_a_probe_never_joins_the_online_list(cluster):
    peers_before = cluster.hub.peers

    probe_result, probe_peers, _probe_hub_name = cluster.modules.node.probe_hub(
        cluster.url, timeout=3, token=cluster.alpha_token)
    time.sleep(0.3)

    assert probe_result == "games_ai", f"probe recognised the hub: {probe_result}"
    assert sorted(probe_peers) == ["alpha", "beta"], f"probe reports the peers: {probe_peers}"
    assert cluster.hub.peers == peers_before, f"probe did not register: {cluster.hub.peers}"


def test_a_bad_token_is_fatal(cluster):
    with pytest.raises(ConnectionClosed) as caught:      # an answered frame would fail here
        with raw_connect(cluster.url) as raw:
            raw.send(json.dumps({"type": "hello", "app": "games_ai_mcdr", "protocol": 1,
                                 "server": "bad", "token": "nope"}))
            raw.recv(timeout=3)
    code = getattr(getattr(caught.value, "rcvd", None), "code", None)
    assert code == 4001, f"bad token -> close 4001: {code}"

    bad = cluster.modules.node.CrossServerNode(cluster.url, "bad", "nope", reconnect=True)
    try:
        assert bad.start(timeout=3) is False, "bad-token node never connects"
        assert wait_until(lambda: "token" in (bad.fatal_error or ""), timeout=5), \
            f"bad-token node gave up instead of looping: {bad.fatal_error}"
    finally:
        bad.stop()


def test_a_second_connection_with_the_same_name_replaces_the_old_one(cluster):
    alpha2 = cluster.modules.node.CrossServerNode(cluster.url, "alpha", cluster.alpha_token,
                                                  handler=make_handler(cluster.inbox, "alpha"))
    try:
        assert alpha2.start(timeout=5), "second 'alpha' connects"
        assert wait_until(lambda: cluster.alpha.connected is False, timeout=5), \
            f"old alpha was dropped: connected={cluster.alpha.connected}"
        assert sorted(cluster.hub.peers) == ["alpha", "beta"], \
            f"hub still has one alpha: {cluster.hub.peers}"
        assert "another instance" in (cluster.alpha.fatal_error or ""), \
            f"old alpha stopped with a clear reason: {cluster.alpha.fatal_error}"
    finally:
        alpha2.stop()
        cluster.alpha.stop()


def test_the_hub_restart_makes_the_nodes_reconnect(cluster):
    alpha2 = cluster.modules.node.CrossServerNode(cluster.url, "alpha", cluster.alpha_token,
                                                  handler=make_handler(cluster.inbox, "alpha"))
    hub2 = None
    try:
        assert alpha2.start(timeout=5), "second 'alpha' connects"
        assert wait_until(lambda: sorted(cluster.hub.peers) == ["alpha", "beta"], timeout=5), \
            f"the hub has alpha again: {cluster.hub.peers}"
        cluster.alpha.stop()                   # the replaced node is gone, as after section 10

        cluster.hub.stop()
        assert wait_until(lambda: not alpha2.connected and not cluster.beta.connected, timeout=5), \
            "nodes noticed the hub is gone: alpha2={} beta={}".format(
                alpha2.connected, cluster.beta.connected)

        hub2 = cluster.modules.hub.CrossServerHub("127.0.0.1", cluster.port, name="hub",
                                                  handler=hub_handler(cluster.hub_inbox),
                                                  node_file=cluster.node_file)
        assert hub2.start(timeout=5), "new hub on the same port"
        assert wait_until(lambda: sorted(hub2.peers) == ["alpha", "beta"], timeout=15), \
            f"both nodes re-registered: {hub2.peers}"

        reply = alpha2.send("beta", "chat", "after reconnect", wait=True, timeout=3)
        assert reply and reply.get("ok") and reply.get("message") == "beta received: after reconnect", \
            f"routing works again after reconnect: {reply}"
    finally:
        if hub2 is not None:
            hub2.stop()
        alpha2.stop()


def test_a_clean_shutdown_leaves_no_thread_behind(cluster):
    baseline = threading.active_count()

    cluster.alpha.stop()
    cluster.beta.stop()
    cluster.hub.stop()
    time.sleep(0.5)

    after = threading.active_count()
    assert after <= baseline, "no threads leaked: before={} after={}".format(baseline, after)
    assert not cluster.alpha.connected and not cluster.beta.connected, "nodes report disconnected"
