"""P2: the enrolment table is the one outsiders can write to, so it must have limits.

Before the fix every unauthenticated request added a row *and* rewrote the node table on disk,
with no cap, no expiry and no rate limit; every handshake of an enrolled node rewrote it too.
"""
import json
import logging
import time

import pytest
from websockets.sync.client import connect as raw_connect

from games_ai.websockets_client import APP_ID
from games_ai.websockets_server import (
    ENROL_PENDING_TTL,
    ENROL_RATE_LIMIT,
    ENROL_RATE_WINDOW,
    MAX_ENROL_PENDING,
    NODE_TABLE_SEEN_INTERVAL,
    CrossServerHub,
)

log = logging.getLogger(__name__)


@pytest.fixture
def counting_hub(tmp_path, free_port):
    """A factory for hubs whose node-table writes are counted instead of hitting the disk twice.

    Every hub it built lives under ``tmp_path`` and is stopped when the test ends, so no test can
    leave a listening socket or a node table behind.
    """
    created = []

    def make(name, **kwargs):
        hub = CrossServerHub("127.0.0.1", free_port(), name="hub", logger=log,
                             node_file=str(tmp_path / name), **kwargs)
        writes = {"n": 0}
        real = hub._save_node_table

        def counted():
            writes["n"] += 1
            return real()

        hub._save_node_table = counted
        hub.writes = writes
        created.append(hub)
        return hub

    yield make
    for hub in created:
        try:
            hub.stop()
        except Exception:
            pass


def flood(hub, count=40, ip="10.0.0.9"):
    """Enrol ``count`` fresh names from one address and return the ones that got in."""
    return [name for name in ("flood-%d" % i for i in range(count))
            if not hub.enrol(name, app=APP_ID, ip=ip).get("refused")]


def test_the_constants_are_the_documented_ones():
    """Section: the constants are the documented ones."""
    assert MAX_ENROL_PENDING == 32, f"the waiting list is capped: {MAX_ENROL_PENDING}"
    assert ENROL_PENDING_TTL == 7 * 24 * 3600, f"requests expire: {ENROL_PENDING_TTL}"
    assert (ENROL_RATE_LIMIT, ENROL_RATE_WINDOW) == (10, 60.0), \
        f"one address is rate limited: {(ENROL_RATE_LIMIT, ENROL_RATE_WINDOW)}"
    assert NODE_TABLE_SEEN_INTERVAL == 600.0, \
        f"last_seen is written at most every 10 minutes: {NODE_TABLE_SEEN_INTERVAL}"


def test_a_flood_of_new_names_from_one_address_is_limited(counting_hub):
    """Section: a flood of new names from one address is limited."""
    hub = counting_hub("nodes.json")
    accepted = flood(hub)
    assert len(accepted) == ENROL_RATE_LIMIT, f"only the rate limit's worth got in: {len(accepted)}"
    assert all(hub.enrol("late-%d" % i, app=APP_ID, ip="10.0.0.9").get("refused") == "rate"
               for i in range(3)), "the rest were refused for that reason"
    assert hub.writes["n"] == len(accepted), \
        f"a refused request writes nothing new: {(hub.writes['n'], len(accepted))}"
    assert len(hub.pending_requests) == len(accepted), \
        f"the table holds exactly the accepted names: {len(hub.pending_requests)}"


def test_asking_again_for_a_name_that_already_waits(counting_hub):
    """Section: asking again for a name that already waits."""
    hub = counting_hub("nodes.json")
    accepted = flood(hub)
    before = hub.writes["n"]
    for _ in range(5):
        entry = hub.enrol(accepted[0], app=APP_ID, ip="10.0.0.9")
    assert not entry.get("refused"), f"a retry of an existing name is never refused: {entry}"
    assert hub.writes["n"] == before, \
        f"...and does not rewrite the table: {(before, hub.writes['n'])}"
    assert entry["requests"] == 6, f"...but still counts the requests: {entry}"
    assert len([n for n in hub.pending_requests if n.startswith("later-")]) == 0, \
        "...and it does not consume the rate budget"
    assert hub.enrol("later-1", app=APP_ID, ip="10.0.0.9").get("refused") == "rate", \
        "a fresh name from that address is still refused"


def test_a_new_window_lets_that_address_ask_again(counting_hub):
    """Section: a new window lets that address ask again."""
    hub = counting_hub("nodes.json")
    flood(hub)
    with hub._nodes_lock:
        started, count = hub._enrol_rate["10.0.0.9"]
        hub._enrol_rate["10.0.0.9"] = (started - ENROL_RATE_WINDOW - 1, count)
    assert not hub.enrol("window-1", app=APP_ID, ip="10.0.0.9").get("refused"), \
        "after the window rolls over a new name is accepted again"
    assert not hub.enrol("other-1", app=APP_ID, ip="10.0.0.10").get("refused"), \
        "a different address is unaffected"


def test_the_waiting_list_has_a_hard_cap(counting_hub):
    """Section: the waiting list has a hard cap."""
    capped = counting_hub("capped.json")
    for index in range(MAX_ENROL_PENDING):
        capped.enrol("fill-%d" % index, app=APP_ID, ip="10.1.%d.%d" % (index // 250, index % 250))
    assert len(capped.pending_requests) == MAX_ENROL_PENDING, \
        f"the list is full: {len(capped.pending_requests)}"
    writes_before = capped.writes["n"]
    extra = capped.enrol("overflow", app=APP_ID, ip="10.9.9.9")
    assert extra.get("refused") == "full", f"one more is refused as full: {extra}"
    assert not capped.is_pending("overflow"), "...and it is not in the list"
    assert capped.writes["n"] == writes_before, f"...and nothing was written: {capped.writes}"


def test_stale_requests_disappear(counting_hub):
    """Section: stale requests disappear."""
    stale = counting_hub("stale.json")
    stale.enrol("old-one", app=APP_ID, ip="10.2.0.1")
    stale.enrol("fresh-one", app=APP_ID, ip="10.2.0.2")
    with stale._nodes_lock:
        stale._enrol_pending["old-one"]["requested_at"] = int(time.time()) - ENROL_PENDING_TTL - 60
    assert not stale.is_pending("old-one"), "the expired name is gone from the list"
    assert "old-one" not in stale.pending_requests, \
        f"...and from what the operator sees: {sorted(stale.pending_requests)}"
    assert stale.is_pending("fresh-one"), "the fresh one is still there"
    assert stale.issue("old-one", require_pending=True) is None, \
        "a strict issuance for an expired name is refused"
    assert bool(stale.issue("fresh-one", require_pending=True)), \
        "...and for the fresh one it works"


def test_last_seen_no_longer_rewrites_the_table_on_every_handshake(counting_hub):
    """Section: last_seen no longer rewrites the table on every handshake."""
    seen = counting_hub("seen.json")
    seen.enrol("node-a", app=APP_ID, ip="10.3.0.1")
    token = seen.issue("node-a", app=APP_ID, ip="10.3.0.1", require_pending=True)
    assert seen.verify("node-a", APP_ID, token) == "ok", "the node is enrolled"
    first = seen.writes["n"]
    seen.record_seen("node-a", "10.3.0.1")
    assert seen.writes["n"] == first + 1, \
        f"the first handshake records last_seen (one write): {(first, seen.writes['n'])}"
    before = seen.writes["n"]
    seen.record_seen("node-a", "10.3.0.1")
    seen.record_seen("node-a", "10.3.0.1")
    assert seen.writes["n"] == before, \
        f"later handshakes in the same window write nothing: {(before, seen.writes['n'])}"
    seen.record_seen("node-a", "10.3.0.99")
    assert seen.writes["n"] == before + 1, f"a new source address is material: {seen.writes}"
    with seen._nodes_lock:
        seen._nodes["node-a"]["last_seen"] = int(time.time()) - NODE_TABLE_SEEN_INTERVAL - 5
    seen.record_seen("node-a", "10.3.0.99")
    assert seen.writes["n"] == before + 2, f"an old timestamp is material too: {seen.writes}"


def test_the_handshake_path_says_why_it_refused(counting_hub):
    """Section: the handshake path says why it refused."""
    wire = counting_hub("wire.json")
    wire.start(timeout=5)
    for index in range(MAX_ENROL_PENDING):
        wire.enrol("fill-%d" % index, app=APP_ID, ip="10.4.0.%d" % (index % 250))
    conn = None
    try:
        conn = raw_connect("ws://127.0.0.1:{}".format(wire.port), open_timeout=5)
        conn.send(json.dumps({"type": "hello", "app": APP_ID, "protocol": 1,
                              "server": "one-too-many", "enroll": True}))
        frame = json.loads(conn.recv(timeout=5))
        assert frame.get("refused") == "full", f"the peer is told the list is full: {frame}"
        assert "full" in str(frame.get("message")).lower(), \
            f"...and the message says what to do: {frame}"
        assert not wire.is_pending("one-too-many"), "...and it is not registered"
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def test_the_limiters_own_map_cannot_grow_without_bound(counting_hub):
    """Section: the limiter's own map cannot grow without bound."""
    many = counting_hub("many.json")
    for index in range(400):
        many.enrol("ip-%d" % index, app=APP_ID, ip="10.5.%d.%d" % (index // 250, index % 250))
    assert len(many._enrol_rate) <= 256 + 1, \
        f"the rate map is trimmed back to live windows: {len(many._enrol_rate)}"
    assert len(many.pending_requests) <= MAX_ENROL_PENDING, \
        f"...while the names that were accepted are still waiting: {len(many.pending_requests)}"
