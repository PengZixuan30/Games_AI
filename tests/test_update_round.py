"""Cluster update round: the hub orders, waits, and only then updates itself.

Runs a real hub and real node connections over TCP (the plugin's own websockets modules),
with stub node handlers standing in for the download + swap, so the *ordering* can be
asserted instead of described:

* every online node gets the order, with the pinned version/url/sha256/size;
* the hub blocks until each node is staged, and until it reconnected on the new version --
  the check compares timestamps, so "the hub went last" is a measurement, not a comment;
* a node that refuses, times out, or is too old to understand the order is reported and
  never blocks the round forever;
* the node side validates the order (only its own hub, only the plugin's own release URLs)
  and answers *before* it starts downloading.
"""
import logging
import threading
import time
import types

import pytest

from _helpers.wait import wait_until
import games_ai
from games_ai import updater
from games_ai import update_round
from games_ai import websockets_client as wsc
from games_ai import websockets_server as wss

log = logging.getLogger(__name__)

TARGET = "9.9.9"
URL = updater.ALLOWED_URL_PREFIX + TARGET + "/GamesAI-v9.9.9.mcdr"
SHA = "a" * 64
RELEASE = updater.ReleaseInfo(version=TARGET, url=URL, size=1234, sha256=SHA,
                              file_name="GamesAI-v9.9.9.mcdr")

# The real threading.Thread: one case below counts the threads the round creates.
_REAL_THREAD = threading.Thread


class FakeServer:
    """What the round asks of a PluginServerInterface: a logger, say(), rtr()."""

    def __init__(self):
        self.logger = logging.getLogger("gamesai_round")
        self.said = []

    def rtr(self, key, **kwargs):
        return key + ("|" + ";".join("{}={}".format(k, v) for k, v in sorted(kwargs.items()))
                      if kwargs else "")

    def say(self, text):
        self.said.append(text)


class FakeManager:
    """A stand-in for CrossServerManager that owns a real hub (and can act as its node)."""

    def __init__(self, hub):
        self.hub = hub
        self.hub_name = hub.name
        self.is_server = True
        self.is_client = False
        self.connected = True
        self.name = hub.name

    @property
    def peer_versions(self):
        return self.hub.peer_versions

    def peer_supports(self, name, feature):
        return self.hub.peer_supports(name, feature)


class _ManagerSentinel:
    is_server = True
    hub = None
    hub_name = "sentinel"
    connected = False


class FakeNodeManager:
    """The node half: it only has to remember where commands are sent."""

    def __init__(self, hub_name, connected=True):
        self.hub_name = hub_name
        self.connected = connected
        self.sent = []
        self.is_client = True
        self.is_server = False

    def send_to_hub(self, action, message="", data=None, **kwargs):
        self.sent.append((action, dict(data or {})))


class FakeHubPeers:
    def __init__(self, apps):
        self.peer_apps = apps


class StubRig:
    """Stub nodes on one hub: what each saw, and the rejoin timeline.

    ``make_stub`` stands in for the download + swap: it answers the order and reports progress
    on its own timetable, exactly like the node's real worker does.
    """

    def __init__(self, hub, uri):
        self.hub = hub
        self.uri = uri
        self.tokens = {}
        self.recorded = {}          # name -> the order frame it received
        self.timeline = []          # (name, timestamp) of every node that reported staged
        self.nodes = {}

    def token(self, name):
        self.tokens.setdefault(name, self.hub.issue(name, app=wss.APP_ID))
        return self.tokens[name]

    def make_stub(self, name, *, ack="accepted", delay=0.0, stage_after=0.0, rejoin_after=None,
                  fail=None, apply_marks=True):
        """A node whose handler answers the order and reports progress on its own timetable."""
        def handler(msg):
            action = msg.get("action")
            if action != "plugin_update":
                return None
            self.recorded[name] = dict(msg.get("data") or {})
            if delay:
                time.sleep(delay)
            if fail:
                return {"ok": False, "error": fail}
            data = dict(msg.get("data") or {})

            def later():
                if stage_after:
                    time.sleep(stage_after)
                if apply_marks:
                    self.timeline.append((name, time.perf_counter()))
                self.nodes[name].send(None, "plugin_update_result", data={
                    "round": data.get("round"), "version": data.get("version"), "stage": "staged"})
                if rejoin_after is not None:
                    time.sleep(rejoin_after)
                    self.nodes[name].stop(timeout=3)
                    fresh = wsc.CrossServerNode(self.uri, name, self.token(name), version=TARGET,
                                                handler=handler)
                    fresh.start(timeout=5)
                    self.nodes[name] = fresh

            threading.Thread(target=later, daemon=True).start()
            return {"ok": True, "data": {"stage": ack, "round": data.get("round")}}
        return handler

    def start(self, name, version="0.7.3", handler=None):
        node = wsc.CrossServerNode(self.uri, name, self.token(name), version=version,
                                   handler=handler or self.make_stub(name))
        started = node.start(timeout=5)
        self.nodes[name] = node
        return started

    def adopt(self, name, node):
        """Take a node the test built itself under this rig's teardown."""
        self.nodes[name] = node

    def stop(self, name):
        node = self.nodes.get(name)
        if node is not None:
            node.stop(timeout=3)

    def stop_all(self):
        for node in list(self.nodes.values()):
            try:
                node.stop(timeout=3)
            except Exception:
                pass

    def wait_for_peers(self, *names):
        """The hub sees exactly these peers within the usual bound."""
        return wait_until(lambda: sorted(self.hub.peers) == sorted(names), timeout=5)

    def wait_for_version(self, name, version):
        """The hub has this peer registered on one version within the usual bound."""
        return wait_until(lambda: self.hub.peer_versions.get(name) == version, timeout=5)


def catch_up_budget(monkeypatch, apps, version):
    """Call ``_on_peer_registered`` with the live state stubbed; nothing is fetched."""
    class Mgr:
        is_server = True

        def __init__(self, apps):
            self.hub = FakeHubPeers(apps)

    started = []
    threads = []

    class Recorder(_REAL_THREAD):
        def __init__(self, *args, **kwargs):
            started.append(kwargs.get("name"))
            threads.append(self)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(games_ai, "_cross_server", Mgr(apps), raising=False)
    monkeypatch.setattr(games_ai, "_server_ref", FakeServer(), raising=False)
    # The probe must never let a real catch-up thread run: it would fetch the catalogue over
    # the network and hold the update lock for up to 30 s, starving the sections after this one.
    monkeypatch.setattr(update_round, "_own_release", lambda server: None)
    monkeypatch.setattr(threading, "Thread", Recorder)
    # "the budget was spent" = the catch-up timestamp moved, whatever it started at.
    before = update_round._last_catchup
    update_round._on_peer_registered("peer", version, ())
    spent = update_round._last_catchup != before
    for thread in threads:
        thread.join(3.0)
    return spent, started


@pytest.fixture(autouse=True)
def clean_round_state(monkeypatch):
    """The round lives in module globals; each test starts from what on_unload leaves behind."""
    monkeypatch.setattr(update_round, "_update_round", None)
    monkeypatch.setattr(update_round, "_update_rounds_seen", [])
    monkeypatch.setattr(update_round, "_update_order_thread", None)
    monkeypatch.setattr(update_round, "_update_loop_started", False)
    # "the last catch-up is over" -- spelled out instead of a bare 0.0, which would only mean
    # that on a machine whose monotonic clock is already past the interval.
    monkeypatch.setattr(update_round, "_last_catchup",
                        time.monotonic() - update_round._UPDATE_CATCHUP_INTERVAL - 1)


@pytest.fixture
def attached():
    """The plugin's live state wired into update_round the way on_load does it; put back after."""
    before = (update_round._server_of, update_round._manager_of,
              update_round._link_thread_of, update_round._version)
    update_round.attach(
        server_of=lambda: games_ai._server_ref,
        manager_of=lambda: games_ai._cross_server,
        link_thread_of=lambda: games_ai._cross_server_thread,
        version=str(games_ai.PLUGIN_METADATA["version"]),
    )
    try:
        yield
    finally:
        update_round.attach(server_of=before[0], manager_of=before[1],
                            link_thread_of=before[2], version=before[3])


@pytest.fixture
def server():
    return FakeServer()


@pytest.fixture
def hub(free_port, attached):
    """A real hub the round can order around; stopped when the test ends."""
    hub = wss.CrossServerHub("127.0.0.1", free_port(), name="hub",
                             handler=games_ai._on_cross_message, logger=log)
    started = hub.start(timeout=5)
    try:
        yield types.SimpleNamespace(hub=hub, started=started, port=hub.port,
                                    uri="ws://127.0.0.1:{}".format(hub.port))
    finally:
        hub.stop(timeout=3)


@pytest.fixture
def manager(hub, monkeypatch):
    """The hub-capable manager the plugin's live cross-server state points at."""
    manager = FakeManager(hub.hub)
    monkeypatch.setattr(games_ai, "_cross_server", manager, raising=False)
    return manager


@pytest.fixture
def rig(hub, monkeypatch):
    """Stub nodes on the test hub; every node started through it is stopped with the test.

    The stage deadline is shortened: the production 420s is there for a real download, while a
    probe that lost a report should fail fast instead of sitting on it.
    """
    monkeypatch.setattr(update_round, "_UPDATE_STAGE_DEADLINE", 6.0)
    rig = StubRig(hub.hub, hub.uri)
    try:
        yield rig
    finally:
        rig.stop_all()


def test_the_round_rig_comes_up(hub, rig):
    assert hub.started, f"the test hub started: {hub.hub.is_running}"
    assert rig.start("node-a"), "node-a connected"
    assert rig.start("node-b"), "node-b connected"
    assert rig.wait_for_peers("node-a", "node-b"), f"the hub sees both nodes: {hub.hub.peers}"


def test_attach_reads_the_live_manager_at_use_time(attached, monkeypatch):
    # The update path reads the entry module's live state through the getters attach() installs.
    # The probe keeps replacing games_ai._cross_server below; those assignments stay visible
    # because every getter is called at use time, never cached.
    sentinel = _ManagerSentinel()
    with monkeypatch.context() as patch:
        patch.setattr(games_ai, "_cross_server", sentinel, raising=False)
        assert update_round._manager_of() is sentinel, \
            f"attach() reads the live manager at use time, never caches it: {update_round._manager_of()}"
    assert update_round._manager_of() is games_ai._cross_server, \
        f"...and follows a replacement made after attach(): {update_round._manager_of()}"


def test_what_the_hub_knows_about_its_nodes(hub, rig, manager):
    """Section 1: what the hub knows about its nodes."""
    rig.start("node-a")
    rig.start("node-b")
    assert rig.wait_for_peers("node-a", "node-b"), f"the hub sees both nodes: {hub.hub.peers}"

    versions = hub.hub.peer_versions
    assert versions.get("node-a") == "0.7.3" and versions.get("node-b") == "0.7.3", \
        f"the hub recorded both announced versions: {versions}"
    assert hub.hub.peer_supports("node-a", wss.FEATURE_UPDATE_ORDER), \
        "the hub saw the update_order feature"
    assert manager.peer_versions == versions \
        and manager.peer_supports("node-a", wss.FEATURE_UPDATE_ORDER), \
        f"the manager exposes the same view through the plugin's accessor: {manager.peer_versions}"


def test_the_order_carries_the_pinned_artifact(hub, rig, manager, server):
    """Section 2: the order carries the pinned artifact."""
    rig.start("node-a")
    rig.start("node-b")
    assert rig.wait_for_peers("node-a", "node-b"), f"the hub sees both nodes: {hub.hub.peers}"

    state = update_round._order_cluster_update(server, RELEASE)

    assert sorted(state) == ["node-a", "node-b"], f"both nodes were ordered: {sorted(state)}"
    assert rig.recorded["node-a"] == {"round": rig.recorded["node-a"].get("round"),
                                      "version": TARGET, "url": URL, "sha256": SHA, "size": 1234}, \
        f"the order carries version, url, size and sha256: {rig.recorded['node-a']}"
    stages = {name: state[name]["stage"] for name in state}
    assert all(state[name]["stage"] in ("accepted", "staged") for name in state), \
        f"both nodes are marked accepted or already staged: {stages}"
    assert any("round_started" in line for line in server.said), \
        f"the players were told a round started: {server.said}"


def test_the_hub_blocks_until_the_nodes_are_done(hub, rig, manager, server):
    """Section 3: the hub blocks until the nodes are done, then waits for the rejoin."""
    for name, stage_after, rejoin_after in (("node-a", 0.8, 0.4), ("node-b", 1.4, 0.4)):
        rig.start(name, handler=rig.make_stub(name, stage_after=stage_after,
                                              rejoin_after=rejoin_after))
    assert rig.wait_for_peers("node-a", "node-b"), f"the hub sees both nodes: {hub.hub.peers}"

    state = update_round._order_cluster_update(server, RELEASE)
    t0 = time.perf_counter()
    update_round._wait_for_cluster_update(server, state, RELEASE)
    hub_finished = time.perf_counter() - t0
    applied = [t for name, t in rig.timeline]

    assert hub_finished >= 1.4, \
        f"the hub waited for the slower node instead of racing ahead: {round(hub_finished, 2)}"
    assert all(t - t0 < hub_finished for t in applied), \
        f"the hub went last: it finished after every node reported staged: {(applied, hub_finished)}"
    assert all(hub.hub.peer_versions.get(n) == TARGET for n in ("node-a", "node-b")), \
        f"both nodes came back on the new version: {hub.hub.peer_versions}"
    stages = {name: state[name]["stage"] for name in state}
    assert stages == {"node-a": "staged", "node-b": "staged"}, \
        f"no node is left as a problem: {stages}"

    update_round._report_cluster_update(server, state, RELEASE)
    assert any("round_summary" in line and "ok=2" in line and "failed=0" in line
               for line in server.said), \
        f"the round summary is told to the players: {server.said[-3:]}"


def test_a_refusing_node_is_reported_and_does_not_block(hub, rig, manager, server):
    """Section 4: a node that refuses, and one that never answers the ack."""
    rig.start("refusing", handler=rig.make_stub("refusing",
                                                fail="the artifact is not for this plugin"))
    assert rig.wait_for_peers("refusing"), f"the refusing node connected: {hub.hub.peers}"

    state = update_round._order_cluster_update(server, RELEASE)
    assert state["refusing"]["stage"] == "failed", f"a refusing node is recorded as failed: {state}"
    assert "not for this plugin" in state["refusing"]["error"], \
        f"its reason is kept: {state['refusing']['error']}"

    update_round._wait_for_cluster_update(server, state, RELEASE)
    assert state["refusing"]["stage"] == "failed", f"a failed node does not block the round: {state}"

    server.said.clear()
    update_round._report_cluster_update(server, state, RELEASE)
    assert any("round_summary" in line and "1" in line for line in server.said), \
        f"the failure is reported to the players: {server.said}"


def test_a_legacy_node_is_reported_not_ordered(hub, rig, manager, server, monkeypatch):
    """Section 5: an old node cannot be ordered (and is not lied to)."""
    monkeypatch.setattr(wsc, "FEATURES", ())
    assert rig.start("legacy"), "the legacy node connected"
    assert rig.wait_for_peers("legacy"), f"the hub sees the legacy node: {hub.hub.peers}"

    assert not hub.hub.peer_supports("legacy", wss.FEATURE_UPDATE_ORDER), \
        "the hub does not see the feature on it"

    state = update_round._order_cluster_update(server, RELEASE)
    assert state["legacy"]["stage"] == "unsupported", \
        f"a legacy node is reported, not ordered: {state}"
    assert "legacy" not in rig.recorded, f"no order frame was sent to it: {rig.recorded.get('legacy')}"


def test_the_ack_and_rejoin_timeouts(hub, rig, manager, server, monkeypatch):
    """Section 6: timeouts -- the ack, and the rejoin."""
    monkeypatch.setattr(update_round, "_UPDATE_ACK_TIMEOUT", 0.4)
    rig.start("slow", handler=rig.make_stub("slow", delay=1.2))
    assert rig.wait_for_peers("slow"), f"the slow node connected: {hub.hub.peers}"

    state = update_round._order_cluster_update(server, RELEASE)
    assert state["slow"]["stage"] == "failed" or state["slow"]["stage"] == "timeout", \
        f"a node that does not answer the ack in time is timed out: {state}"

    rig.stop("slow")
    rig.recorded.clear()
    monkeypatch.setattr(update_round, "_UPDATE_ACK_TIMEOUT", 5.0)
    monkeypatch.setattr(update_round, "_UPDATE_REJOIN_DEADLINE", 0.8)
    rig.start("node-a", handler=rig.make_stub("node-a", stage_after=0.1, rejoin_after=None))
    assert rig.wait_for_peers("node-a"), f"the node connected: {hub.hub.peers}"

    state = update_round._order_cluster_update(server, RELEASE)
    update_round._wait_for_cluster_update(server, state, RELEASE)
    assert state["node-a"]["stage"] == "stale", \
        f"a node that never comes back is a problem, not a success: {state}"
    assert "did not come back" in state["node-a"]["error"], \
        f"the timeout says what was missing: {state['node-a']['error']}"


def test_an_up_to_date_node_is_not_ordered(hub, rig, manager, server):
    """Section 7: a node that is already up to date is skipped."""
    rig.start("node-b", version=TARGET)
    assert rig.wait_for_version("node-b", TARGET), \
        f"the up-to-date node connected: {hub.hub.peer_versions}"

    state = update_round._order_cluster_update(server, RELEASE)
    assert state == {} and "node-b" not in rig.recorded, \
        f"an up-to-date node is not ordered: {(state, rig.recorded)}"


def test_a_node_sharing_the_hub_name_is_skipped(hub, rig, manager, server):
    """Section 8: a node that shares the hub's name cannot be addressed."""
    rig.start("hub", handler=rig.make_stub("same-name"))
    assert rig.wait_for_peers("hub"), f"the hub really has a peer named like itself: {hub.hub.peers}"

    state = update_round._order_cluster_update(server, RELEASE)
    assert state == {} and "same-name" not in rig.recorded, \
        f"the same-name node is skipped instead of updating the hub by accident: {(state, rig.recorded)}"


def test_the_stage_ladder_never_moves_backwards():
    """Section 9: the stage ladder -- a late answer corrects this side's guesses."""
    entry = {"stage": "pending", "error": "", "event": threading.Event()}
    update_round._set_node_stage(entry, "accepted")
    update_round._set_node_stage(entry, "staged")
    update_round._set_node_stage(entry, "accepted")
    assert entry["stage"] == "staged", f"a late 'accepted' cannot hide a 'staged': {entry}"
    assert entry["event"].is_set(), "the waiter was woken"
    update_round._set_node_stage(entry, "timeout", "too slow")
    assert entry["stage"] == "staged", \
        f"a clock-out cannot overwrite what the node reported: {entry}"

    # The reverse case: the hub gives up on the ack (its clock), then the node answers late --
    # the node's own report has to win, otherwise a node that is updating right now is treated
    # as done.
    late = {"stage": "pending", "error": "", "event": threading.Event()}
    update_round._set_node_stage(late, "timeout", "no ack within 10s")
    update_round._set_node_stage(late, "staged")
    assert late["stage"] == "staged", \
        f"a node that answers after the timeout is recorded as staged: {late}"
    assert late["event"].is_set(), "and the waiter is woken for it"

    guessed = {"stage": "pending", "error": "", "event": threading.Event()}
    update_round._set_node_stage(guessed, "unsupported")
    update_round._set_node_stage(guessed, "staged")
    assert guessed["stage"] == "staged", \
        f"a peer that does answer overrides the 'no feature' guess: {guessed}"

    failed = {"stage": "pending", "error": "", "event": threading.Event()}
    update_round._set_node_stage(failed, "failed", "boom")
    update_round._set_node_stage(failed, "staged")
    assert failed["stage"] == "failed", f"a reported failure is final: {failed}"

    update_round._on_update_result("node-a", {"round": "nope", "stage": "staged"})
    assert update_round._update_round is None, "a result for an unknown round is ignored"


def test_the_hub_deadline_outlives_the_node_download_budget():
    """Section 9b: the hub's deadline outlives a node's own download budget."""
    assert update_round._UPDATE_STAGE_DEADLINE > updater.DOWNLOAD_DEADLINE + 30, \
        ("the stage deadline is comfortably above the node's download deadline: "
         f"{(update_round._UPDATE_STAGE_DEADLINE, updater.DOWNLOAD_DEADLINE)}")


def test_a_node_ahead_of_the_hub_is_never_pushed_backwards(hub, rig, manager, server):
    """Section 9c: a node that is ahead of the hub is never pushed backwards."""
    rig.start("node-a", version="99.0.0")
    assert rig.wait_for_version("node-a", "99.0.0"), \
        f"the ahead node connected: {hub.hub.peer_versions}"

    state = update_round._order_cluster_update(server, RELEASE)
    assert state == {} and "node-a" not in rig.recorded, \
        f"it is not ordered to install the hub's older release: {(state, rig.recorded.get('node-a'))}"


@pytest.mark.parametrize("label, apps, version, expected_spend", [
    ("a Mineflayer bot does not spend the catch-up budget", {"peer": wss.APP_ID_BOT}, "0.1", False),
    ("a node that is newer than the hub does not spend it", {"peer": wss.APP_ID}, "99.0.0", False),
    ("a node on the hub's own version does not spend it", {"peer": wss.APP_ID},
     games_ai.PLUGIN_METADATA["version"], False),
    ("a node that is behind does spend it", {"peer": wss.APP_ID}, "0.0.1", True),
], ids=["bot", "newer", "same-version", "behind"])
def test_the_catch_up_budget_is_only_spent_on_a_node_that_is_behind(
        attached, monkeypatch, label, apps, version, expected_spend):
    """Section 9d: the catch-up budget is only spent on a GamesAI node that is behind."""
    spent, started = catch_up_budget(monkeypatch, apps, version)
    assert spent == expected_spend and bool(started) == expected_spend, \
        f"{label}: {(spent, started)}"


def test_the_node_side_validates_the_order_and_answers_first(attached, monkeypatch):
    """Section 10: the node side -- validate the order, answer before working."""
    monkeypatch.setattr(games_ai, "_cross_server", FakeNodeManager("hub"), raising=False)
    monkeypatch.setattr(games_ai, "_server_ref", FakeServer(), raising=False)

    order = {"round": "r1", "version": TARGET, "url": URL, "sha256": SHA, "size": 1234}
    reply = update_round._on_update_order("someone-else", order)
    assert reply.get("ok") is False and "hub" in reply.get("error", ""), \
        f"an order from anyone but our hub is refused: {reply}"
    for name, broken in [
        ("no round", {"version": TARGET, "url": URL, "sha256": SHA, "size": 1234}),
        ("foreign url", dict(order, url="https://example.com/evil.mcdr")),
        ("bad size", dict(order, size=0)),
        ("bad sha", dict(order, sha256="zz")),
    ]:
        reply = update_round._on_update_order("hub", broken)
        assert reply.get("ok") is False, f"refused: {name}: {reply}"

    reply = update_round._on_update_order(
        "hub", dict(order, version=games_ai.PLUGIN_METADATA["version"]))
    assert reply.get("ok") and reply["data"].get("already"), \
        f"an order for the version we already run is a no-op: {reply}"

    started = []

    def sleepy_worker(round_id, version, url, sha256, size):
        started.append((round_id, version, url, sha256, size))
        time.sleep(0.6)

    monkeypatch.setattr(update_round, "_node_update_worker", sleepy_worker)
    valid = dict(order, round="r-valid")
    t0 = time.perf_counter()
    reply = update_round._on_update_order("hub", valid)
    dt = time.perf_counter() - t0
    assert reply.get("ok") and reply["data"]["stage"] == "accepted", \
        f"a good order is accepted: {reply}"
    assert dt < 0.2, f"the ack does not wait for the download: {round(dt, 3)}"

    time.sleep(0.15)                       # the worker runs on its own thread
    assert started == [("r-valid", TARGET, URL, SHA, 1234)], \
        f"the worker got the pinned artifact: {started}"
    reply = update_round._on_update_order("hub", dict(order, round="r-busy"))
    assert reply.get("ok") is False and "already" in reply.get("error", ""), \
        f"a second order while one is running is refused: {reply}"
    time.sleep(0.7)
    reply = update_round._on_update_order("hub", valid)
    assert reply.get("ok") and reply["data"].get("duplicate") and len(started) == 1, \
        f"the same round id is not applied twice: {reply}"


def test_the_plugins_own_handler_answers_a_real_order_over_a_link(hub, rig, manager, server,
                                                                  monkeypatch):
    """Section 11: the node's real handler over a real link.

    Sections 2-8 use stub handlers; this one lets the plugin's own ``_on_update_order`` answer a
    real hub over a real connection, which is the only way to prove the "sender is our hub" check
    matches the names that actually travel on the wire.
    """
    order_answers = []

    def real_order_handler(msg):
        if msg.get("action") != "plugin_update":
            return None
        answer = update_round._on_update_order(str(msg.get("source") or ""),
                                               dict(msg.get("data") or {}))
        order_answers.append(answer)
        return answer

    started_real = []
    monkeypatch.setattr(update_round, "_node_update_worker",
                        lambda *args: started_real.append(args))

    node = wsc.CrossServerNode(rig.uri, "node-a", rig.token("node-a"), version="0.7.3",
                               handler=real_order_handler)
    assert node.start(timeout=5), "the real-handler node connected"
    rig.adopt("node-a", node)
    assert rig.wait_for_peers("node-a"), f"the hub sees the node: {hub.hub.peers}"

    state = update_round._order_cluster_update(server, RELEASE)
    round_id = str((update_round._update_round or {}).get("id") or "")

    assert bool(order_answers) and order_answers[-1].get("ok") is True, \
        f"the plugin's own handler accepted a real order: {order_answers[-1:]}"
    assert bool(order_answers) and order_answers[-1]["data"].get("round") == round_id, \
        f"the answer carries the round the hub sent: {(order_answers[-1:], round_id)}"
    assert state["node-a"]["stage"] == "accepted", \
        f"the hub recorded it as working on this round: {state['node-a']}"
    wait_until(lambda: len(started_real) == 1, timeout=2)
    assert len(started_real) == 1 and started_real[0][1] == TARGET, \
        f"the real worker got the pinned artifact: {started_real}"


def test_a_node_that_missed_the_round_is_caught_up(hub, rig, manager, server, monkeypatch):
    """Section 12: a node that missed the round is caught up to the hub's own version.

    The checker only acts on a release *newer* than the one we run, so this case has to be driven
    by the hub itself: a node reconnecting with an older version is ordered to install exactly
    the version the hub is on. The catalogue lookup is stubbed -- no network in the probe.
    """
    catch_up_orders = []
    monkeypatch.setattr(update_round, "_own_release", lambda server: RELEASE)
    monkeypatch.setattr(update_round, "update",
                        lambda server, force_table=False: catch_up_orders.append("catalogue-check"))

    rig.start("node-b", version="0.7.3",
              handler=rig.make_stub("node-b", stage_after=0.1, rejoin_after=0.2))
    assert rig.wait_for_version("node-b", "0.7.3"), \
        f"the behind node reconnected: {hub.hub.peer_versions}"
    assert wait_until(lambda: not updater.update_lock.locked(), timeout=5), \
        "no other update holds the lock before the catch-up"

    update_round._catch_up_round(server)

    assert rig.recorded.get("node-b", {}).get("version") == TARGET, \
        f"the hub ordered its own version to the node: {rig.recorded.get('node-b')}"
    assert catch_up_orders == [], f"the catch-up did not touch the update checker: {catch_up_orders}"
    assert bool(rig.timeline), f"the catch-up waited for the node: {rig.timeline}"
    assert hub.hub.peer_versions.get("node-b") == TARGET, \
        f"the caught-up node came back on the hub's version: {hub.hub.peer_versions}"

    rig.stop("node-b")
    assert wait_until(lambda: "node-b" not in hub.hub.peers, timeout=5), \
        f"the caught-up node left before the second half: {hub.hub.peers}"
    rig.recorded.clear()
    rig.start("node-b", version=TARGET)
    assert rig.wait_for_version("node-b", TARGET), \
        f"the node that is already current connected: {hub.hub.peer_versions}"

    update_round._catch_up_round(server)
    assert rig.recorded == {}, \
        f"a node already on the hub's version is not ordered again: {rig.recorded}"
