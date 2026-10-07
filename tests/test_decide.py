"""Test the stage-1 lifecycle: config decision (server / client / local) and port handling."""
import json
import logging
import socket
import threading
import time

import pytest
from websockets.sync.server import serve as raw_serve

from games_ai import cross_server as cs
from games_ai.websockets_server import CrossServerHub, is_port_available

from _helpers.wait import wait_until

log = logging.getLogger("test")
HOST = "127.0.0.1"


def _reachable(port):
    """True once something accepts a TCP connection on ``port`` (the peer is up)."""
    probe = socket.socket()
    probe.settimeout(0.2)
    try:
        probe.connect((HOST, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _bindable(port):
    """True while nothing holds ``port`` on this machine."""
    probe = socket.socket()
    try:
        probe.bind((HOST, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def test_a_free_port_becomes_a_hub_and_a_second_instance_joins_it(free_port):
    port = free_port()
    uri = f"ws://{HOST}:{port}"
    mode, reason = cs.decide_mode(uri, force_server=False, logger=log)
    assert mode == cs.MODE_SERVER, f"decides server: {(mode, reason)}"

    manager = cs.CrossServerManager(uri, name="host-a", version="0.7.3", logger=log)
    manager_b = None
    try:
        assert manager.start(timeout=5) == cs.MODE_SERVER, f"manager starts a hub: {manager.reason}"
        assert manager.connected and manager.is_server, f"hub is running: {manager.mode}"
        assert manager.peers == [], f"peers empty: {manager.peers}"

        # A node needs a token of its own; the hub issues one per name (docs/token-enrollment.md).
        host_b_token = manager.hub.issue("host-b")
        manager_b = cs.CrossServerManager(uri, name="host-b", version="0.7.3",
                                          token=host_b_token, logger=log)
        assert manager_b.start(timeout=5) == cs.MODE_CLIENT, \
            f"manager becomes a client: {manager_b.reason}"
        assert manager_b.connected and manager_b.is_client, f"client connected: {manager_b.mode}"
        assert manager_b.peer_uri == uri, \
            f"in client mode local peers use the remote hub: {manager_b.peer_uri}"
        assert wait_until(lambda: manager.peers == ["host-b"], timeout=5), \
            f"hub sees the client: {manager.peers}"
        assert manager_b.peers == [], f"client sees no peer other than itself: {manager_b.peers}"
    finally:
        if manager_b is not None:
            manager_b.stop()
        manager.stop()


def test_a_foreign_websocket_server_is_local(free_port):
    foreign_port = free_port()
    foreign_uri = f"ws://{HOST}:{foreign_port}"

    def foreign_handler(connection):
        for raw in connection:
            connection.send(json.dumps({"hello": "not games_ai"}))

    foreign = raw_serve(foreign_handler, HOST, foreign_port)
    foreign_thread = threading.Thread(target=foreign.serve_forever, daemon=True)
    foreign_thread.start()
    manager_c = None
    try:
        assert wait_until(lambda: _reachable(foreign_port), timeout=5), \
            "the foreign websocket server came up"
        mode, reason = cs.decide_mode(foreign_uri, force_server=False, logger=log)
        assert mode == cs.MODE_LOCAL, f"foreign server -> local: {(mode, reason)}"
        assert "not a GamesAI" in reason, f"reason mentions it is not GamesAI: {reason}"

        manager_c = cs.CrossServerManager(foreign_uri, name="host-c", logger=log)
        assert manager_c.start(timeout=5) == cs.MODE_LOCAL, f"manager stays local: {manager_c.mode}"
        assert (manager_c.hub_uri or "").startswith("ws://127.0.0.1:"), \
            f"local mode still hosts a loopback hub for local peers: {manager_c.hub_uri}"
        assert manager_c.hub_uri != foreign_uri, \
            f"the loopback hub is not the configured uri: {manager_c.hub_uri}"
        assert manager_c.peer_uri == manager_c.hub_uri, \
            f"local peers dial the loopback hub: {manager_c.peer_uri}"

        manager_c.stop()                       # the stop() of the check below, nothing to stop yet
        assert True, "nothing to stop, still safe"
    finally:
        if manager_c is not None:
            manager_c.stop()
        foreign.shutdown()
        foreign_thread.join(5)


def test_a_raw_tcp_listener_is_local(free_port):
    raw_port = free_port()
    raw_sock = socket.socket()
    raw_sock.bind((HOST, raw_port))
    raw_sock.listen(5)
    try:
        mode, reason = cs.decide_mode(f"ws://{HOST}:{raw_port}", force_server=False, logger=log)
        assert mode == cs.MODE_LOCAL, f"raw listener -> local: {(mode, reason)}"
        assert "occupied" in reason, f"reason mentions the port is occupied: {reason}"

        mode, reason = cs.decide_mode(f"ws://{HOST}:{raw_port}", force_server=True, logger=log)
        assert mode == cs.MODE_LOCAL, f"force_server + occupied -> local: {(mode, reason)}"
    finally:
        raw_sock.close()


def test_force_server_on_a_free_port_is_a_server(free_port):
    mode, reason = cs.decide_mode(f"ws://{HOST}:{free_port()}", force_server=True, logger=log)

    assert mode == cs.MODE_SERVER, f"force_server -> server: {(mode, reason)}"


@pytest.mark.parametrize("bad", ["", "127.0.0.1:8080", "http://127.0.0.1:8080", "ws://",
                                 "ws://host:notaport"],
                         ids=["empty", "no scheme", "http scheme", "no host", "not a port"])
def test_an_unusable_uri_is_local(bad):
    mode, reason = cs.decide_mode(bad, force_server=False, logger=log)

    assert mode == cs.MODE_LOCAL, f"bad uri {bad!r} -> local: {(mode, reason)}"


def test_wss_cannot_be_served_here():
    mode, reason = cs.decide_mode("wss://example.invalid:9443", force_server=False, logger=log)
    assert mode == cs.MODE_LOCAL, f"unreachable wss -> local: {(mode, reason)}"

    mode, reason = cs.decide_mode("wss://example.invalid:9443", force_server=True, logger=log)
    assert mode == cs.MODE_LOCAL, f"force_server + wss -> local: {(mode, reason)}"


def test_stopping_the_hub_frees_the_port(free_port):
    port = free_port()
    uri = f"ws://{HOST}:{port}"
    manager = cs.CrossServerManager(uri, name="host-a", version="0.7.3", logger=log)
    manager_b = None
    try:
        assert manager.start(timeout=5) == cs.MODE_SERVER, f"manager starts a hub: {manager.reason}"
        host_b_token = manager.hub.issue("host-b")
        manager_b = cs.CrossServerManager(uri, name="host-b", version="0.7.3",
                                          token=host_b_token, logger=log)
        assert manager_b.start(timeout=5) == cs.MODE_CLIENT, \
            f"manager becomes a client: {manager_b.reason}"

        manager.stop()
        assert wait_until(lambda: _bindable(port), timeout=5), "port is free again after stop"
        assert cs.CrossServerManager(uri, name="host-a", logger=log).mode == cs.MODE_LOCAL, \
            "mode reset for a fresh start"

        manager_b.stop()
        assert wait_until(lambda: not manager_b.connected, timeout=5), \
            f"client stopped cleanly: {manager_b.connected}"
    finally:
        if manager_b is not None:
            manager_b.stop()
        manager.stop()


def test_a_hub_that_dies_makes_the_client_reconnect_instead_of_going_local(free_port):
    port = free_port()
    uri = f"ws://{HOST}:{port}"
    hub = CrossServerHub(HOST, port, name="host-a", logger=log)
    assert hub.start(timeout=5), f"hub restarted: {hub.is_running}"
    manager_d = None
    try:
        host_d_token = hub.issue("host-d")
        manager_d = cs.CrossServerManager(uri, name="host-d", token=host_d_token, logger=log)
        assert manager_d.start(timeout=5) == cs.MODE_CLIENT, \
            f"host-d becomes a client: {manager_d.reason}"

        hub.stop()
        assert wait_until(lambda: not manager_d.connected, timeout=5), \
            f"the client notices the dead hub: {manager_d.connected}"
        assert manager_d.mode == cs.MODE_CLIENT and not manager_d.connected, \
            f"client is disconnected but keeps its client role: {(manager_d.mode, manager_d.connected)}"
    finally:
        if manager_d is not None:
            manager_d.stop()
        hub.stop()

    baseline = threading.active_count()
    assert wait_until(lambda: threading.active_count() <= baseline + 1, timeout=5), \
        f"no thread leak: before={baseline} after={threading.active_count()}"


def test_unload_during_the_decision_leaves_no_listener(free_port, monkeypatch):
    race_port = free_port()
    race_uri = f"ws://{HOST}:{race_port}"
    parked = threading.Event()
    release = threading.Event()

    def parked_decide(uri, **kwargs):
        parked.set()
        release.wait(5)
        return ("server", "forced by the test")      # builds the hub only after stop()

    monkeypatch.setattr(cs, "decide_mode", parked_decide)
    raced = cs.CrossServerManager(race_uri, name="host-race", logger=log)
    raced_thread = threading.Thread(target=raced.start, name="race-start")
    raced_thread.start()
    after = None
    try:
        assert wait_until(parked.is_set, timeout=5), \
            "the decision thread is parked before it builds anything"

        raced.stop()                                  # the unload path, while start() is in flight
        release.set()
        raced_thread.join(10)

        assert raced.mode == "local", f"the abandoned manager settles on local mode: {raced.mode}"
        assert raced.hub is None, f"it keeps no hub: {raced.hub}"
        assert "unload" in raced.reason, \
            f"the reason says it was unloaded while deciding: {raced.reason}"
        assert is_port_available(HOST, race_port), "the port is not left listening"

        after = cs.CrossServerManager(race_uri, name="host-after", logger=log)
        assert after.start(timeout=5) == "server", \
            f"a later instance can still bind that port: {after.reason}"
        after.stop()
        assert is_port_available(HOST, race_port), "and releases it again"
    finally:
        release.set()
        raced_thread.join(10)
        if after is not None:
            after.stop()


def test_a_reload_must_not_swap_the_hub_and_the_client_roles(free_port, monkeypatch):
    started = time.monotonic()
    mode, reason = cs.decide_mode(f"ws://{HOST}:{free_port()}", force_server=False, logger=log,
                                  grace=5.0)
    elapsed = time.monotonic() - started
    assert mode == cs.MODE_SERVER and elapsed < 4.0, \
        f"a free local address is served without waiting for the grace period: " \
        f"{(mode, reason, round(elapsed, 2))}"

    late_port = free_port()
    late_uri = f"ws://{HOST}:{late_port}"
    late_hub = cs.CrossServerManager(late_uri, name="host-late", logger=log)

    def _bring_up_late():
        time.sleep(1.5)
        late_hub.start(timeout=5)

    late_thread = threading.Thread(target=_bring_up_late, daemon=True)
    late_thread.start()
    try:
        mode, reason = cs.decide_mode(late_uri, force_server=False, logger=log,
                                      previous_role=cs.MODE_CLIENT, grace=8.0)
        assert mode == cs.MODE_CLIENT, \
            f"a client waits for its hub and stays a client: {(mode, reason)}"
        assert late_hub.is_server, f"it is a client of the hub that came back: {late_hub.mode}"
    finally:
        late_thread.join(10)
        late_hub.stop()

    gone_port = free_port()
    mode, reason = cs.decide_mode(f"ws://{HOST}:{gone_port}", force_server=False, logger=log,
                                  previous_role=cs.MODE_CLIENT, grace=2.0)
    assert mode == cs.MODE_SERVER, \
        f"a hub that never comes back lets the waiter take over (no split cluster): {(mode, reason)}"

    monkeypatch.setattr(cs, "is_servable", lambda host: False)
    remote_uri = f"ws://{HOST}:{free_port()}"
    started = time.monotonic()
    mode, reason = cs.decide_mode(remote_uri, force_server=False, logger=log, grace=1.0)
    elapsed = time.monotonic() - started
    assert mode == cs.MODE_LOCAL, \
        f"an address this machine cannot bind is never served from here: {(mode, reason)}"
    assert "did not answer" in reason and elapsed < 4.0, \
        f"and it stops waiting after the grace period: {(reason, round(elapsed, 2))}"
