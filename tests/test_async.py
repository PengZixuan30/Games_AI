"""End to end test for the asyncio flavour."""
import json
import threading
import types

import pytest

from _helpers.wait import wait_until
from _helpers.ws_async import AsyncHub, AsyncNode

TOKEN = "s3cret"


def hub_handler(msg):
    """Answer ``who`` on the hub."""
    return {"message": "hub here"} if msg["action"] == "who" else None


def make_handler(inbox, name):
    """Answer ``chat`` for one node and record every frame it sees."""
    def handler(msg):
        inbox[name].append(dict(msg))
        if msg["action"] == "chat":
            return {"message": "{} got {}".format(name, msg["message"])}
        return None

    return handler


@pytest.fixture
def inbox():
    return {"alpha": [], "beta": []}


@pytest.fixture
def cluster(free_port, inbox):
    """A started asyncio hub with its two nodes; all three are stopped when the test ends."""
    hub = AsyncHub("127.0.0.1", free_port(), name="hub", token=TOKEN, handler=hub_handler)
    hub_started = hub.start(timeout=5)
    uri = "ws://127.0.0.1:{}".format(hub.port)
    alpha = AsyncNode(uri, "alpha", TOKEN, handler=make_handler(inbox, "alpha"))
    beta = AsyncNode(uri, "beta", TOKEN, handler=make_handler(inbox, "beta"))
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


def test_hub_and_two_nodes_handshake(cluster):
    assert cluster.hub_started, "hub.start()"
    assert cluster.alpha_started, "alpha handshake"
    assert cluster.beta_started, "beta handshake"
    assert wait_until(lambda: cluster.hub.peers == ["alpha", "beta"], timeout=5), \
        f"hub.peers: {cluster.hub.peers}"
    assert wait_until(lambda: cluster.alpha.peers == ["beta"], timeout=5), \
        f"alpha.peers (pushed): {cluster.alpha.peers}"


def test_frames_route_through_the_hub(cluster, inbox):
    r = cluster.alpha.send(None, "who", wait=True, timeout=3)
    assert r and r.get("ok") and r.get("message") == "hub here", f"node->hub: {r}"

    r = cluster.hub.send("beta", "chat", "from hub", wait=True, timeout=3)
    assert r and r.get("message") == "beta got from hub", f"hub->node: {r}"

    r = cluster.alpha.send("beta", "chat", "cross server", wait=True, timeout=3)
    assert r and r.get("message") == "beta got cross server", f"node->node: {r}"
    assert inbox["beta"][-1]["source"] == "alpha", f"source stamped: {inbox['beta'][-1]}"

    r = cluster.beta.send("ghost", "chat", "x", wait=True, timeout=3)
    assert r and r.get("ok") is False and "unknown target" in r.get("error", ""), \
        f"unknown target error: {r}"


def test_broadcast_and_ping(cluster, inbox):
    sent = cluster.hub.broadcast("notice", "hi all")
    delivered = wait_until(lambda: all(any(m["action"] == "notice" for m in v)
                                       for v in inbox.values()), timeout=3)
    assert sent == 2 and delivered, f"hub.broadcast: {sent}"

    rtt = cluster.alpha.ping("beta", timeout=3)
    assert rtt > 0, f"ping rtt: {rtt}"


def test_a_bad_token_never_connects(cluster):
    bad = AsyncNode(cluster.uri, "bad", "nope")
    try:
        assert bad.start(timeout=3) is False, "bad token never connects"
        assert wait_until(lambda: "bad token" in (bad.fatal_error or ""), timeout=5), \
            f"bad token fatal: {bad.fatal_error}"
    finally:
        bad.stop()


def test_the_nodes_reconnect_to_a_new_hub(cluster):
    cluster.hub.stop()
    assert wait_until(lambda: not cluster.alpha.connected and not cluster.beta.connected, timeout=3), \
        "nodes saw the hub go"

    hub2 = AsyncHub("127.0.0.1", cluster.hub.port, name="hub", token=TOKEN,
                    handler=lambda m: None)
    try:
        assert hub2.start(timeout=5), "hub2.start()"
        assert wait_until(lambda: sorted(hub2.peers) == ["alpha", "beta"], timeout=20), \
            f"auto reconnect: {hub2.peers}"

        r = cluster.alpha.send("beta", "chat", "after reconnect", wait=True, timeout=3)
        assert r and r.get("message") == "beta got after reconnect", \
            f"routing after reconnect: {r}"
    finally:
        hub2.stop()


def test_stopping_leaves_no_threads(cluster):
    baseline = threading.active_count()
    cluster.alpha.stop()
    cluster.beta.stop()
    cluster.hub.stop()
    assert wait_until(lambda: threading.active_count() <= baseline, timeout=5), \
        "no thread leak: before={} after={}".format(baseline, threading.active_count())
