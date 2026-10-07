"""Per-node enrolment, hub half: the node table and the handshake rules.

Covers the first two groups of docs/token-enrollment.md §12: issue/verify/expire/revoke/
rotate, hash-at-rest, TTL -1 vs N, entries surviving expiry, name binding, and the handshake
answers (enrol -> pending + 4007, probe never pends, ok / expired / revoked, expires_in).
"""
import hashlib
import json
import logging
import os
import time

import pytest

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as raw_connect

from games_ai.websockets_client import APP_ID, APP_ID_BOT, probe_hub_detail
from games_ai.websockets_server import CrossServerHub

from _helpers.wait import wait_until

LOG = logging.getLogger("hub")


def hello(name, app=APP_ID, token=None, enroll=False, probe=False):
    frame = {"type": "hello", "app": app, "protocol": 1, "server": name, "version": "0.8.0"}
    if token is not None:
        frame["token"] = token
    if enroll:
        frame["enroll"] = True
    if probe:
        frame["probe"] = True
    return frame


def close_code(exc):
    """The close code of a refused handshake."""
    return getattr(getattr(exc, "rcvd", None), "code", None)


class Sink(logging.Handler):
    """Keeps the warning lines of one logger, so "warned once" can be counted."""

    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@pytest.fixture
def node_file(tmp_path):
    """The hub's node table, in the test's own folder (never inside the repository)."""
    return str(tmp_path / "cross_server_nodes.json")


@pytest.fixture
def hub(free_port, node_file):
    """A hub on its own node table; stopped however the test ends."""
    hub = CrossServerHub("127.0.0.1", free_port(), name="host-a", logger=LOG, node_file=node_file)
    yield hub
    hub.stop()


@pytest.fixture
def make_hub(free_port):
    """Build extra hubs (a ttl one, a second reader of the same table); all are stopped."""
    created = []

    def _make(name="host-b", **kwargs):
        kwargs.setdefault("logger", LOG)
        extra = CrossServerHub("127.0.0.1", free_port(), name=name, **kwargs)
        created.append(extra)
        return extra

    yield _make
    for extra in created:
        extra.stop()


@pytest.fixture
def enrolled(hub):
    """The state section 1 leaves behind: ``survival`` enrolled by a console-issued token."""
    hub.enrol("survival", app=APP_ID, ip="10.0.0.4")
    token = hub.issue("survival", app=APP_ID, issued_by="console", require_pending=True)
    assert token is not None, "a name that is waiting gets a token"
    return token


@pytest.fixture
def live_hub(hub):
    """The hub sections 5-9 connect to: started, on the same per-test node table."""
    assert hub.start(timeout=5), "hub started"
    return hub


@pytest.fixture
def live_uri(live_hub):
    return "ws://127.0.0.1:{}".format(live_hub.port)


@pytest.fixture
def open_peer():
    """Open a raw peer, send one frame, and close it however the test ends."""
    opened = []

    def _open(uri, frame):
        conn = raw_connect(uri)
        opened.append(conn)
        conn.send(json.dumps(frame))
        return conn

    yield _open
    for conn in opened:
        conn.close()


def test_the_node_table_enrols_issues_and_verifies(hub):
    assert hub.nodes == {} and hub.pending_requests == {}, \
        f"a fresh hub has no nodes and no pending requests: {(hub.nodes, hub.pending_requests)}"

    entry = hub.enrol("survival", app=APP_ID, ip="10.0.0.4")
    assert hub.is_pending("survival"), f"enrol records a pending request: {hub.pending_requests}"
    assert entry["app"] == APP_ID and entry["ip"] == "10.0.0.4" and entry["requests"] == 1, \
        f"the entry carries app, ip and a request count: {entry}"

    hub.enrol("survival", app=APP_ID, ip="10.0.0.9")
    assert list(hub.pending_requests) == ["survival"] and hub.pending_requests["survival"]["requests"] == 2, \
        f"a second request refreshes it instead of adding a row: {hub.pending_requests}"
    assert not hub.is_enrolled("survival"), "pending is not enrolment"
    assert hub.issue("creative", require_pending=True) is None and not hub.is_enrolled("creative"), \
        "strict issuance refuses a name nobody is waiting for"
    token = hub.issue("survival", app=APP_ID, issued_by="console", require_pending=True)
    assert token is not None, "a name that is waiting gets a token"

    assert hub.is_enrolled("survival"), "issuing a token enrols the node"
    assert not hub.is_pending("survival"), f"the pending row is consumed: {hub.pending_requests}"
    # V3: the table holds one entry per name, so a second issuance would knock this node offline.
    # It is refused, and the deliberate replacement path is `node rotate` (checked further down).
    assert hub.issue("survival", app=APP_ID, issued_by="console") is None, \
        "a second issuance for an enrolled name is refused"
    assert hub.verify("survival", APP_ID, token) == "ok", "...and the enrolled token is untouched"
    assert len(token) == 43, f"a 32-byte url-safe token is 43 characters: {len(token)}"
    assert hub.verify("survival", APP_ID, token) == "ok", "verify accepts the token itself"
    assert hub.verify("survival", APP_ID, "nope") == "unknown", "verify rejects a wrong token"
    assert hub.verify("creative", APP_ID, token) == "unknown", "verify rejects a token for another name"
    assert hub.verify("survival", APP_ID_BOT, token) == "unknown", \
        "verify rejects a token presented by another app"
    assert hub.verify("survival", APP_ID, "") == "unknown", "an empty token is never accepted"
    assert hub.verify("ghost", APP_ID, token) == "unknown", "an unknown name is never accepted"
    assert hub.fingerprint("survival") == hashlib.sha256(token.encode()).hexdigest()[:6], \
        f"the fingerprint is hash[:6]: {hub.fingerprint('survival')}"
    assert hub.name_for_token(token) == "survival", "the hub can tell which node a token belongs to"
    assert hub.name_for_token("nope") is None, "and nothing for a token it never issued"


def test_hash_at_rest_the_plaintext_never_reaches_the_file(hub, node_file, enrolled):
    token = enrolled
    raw = open(node_file, encoding="utf-8").read()
    assert hashlib.sha256(token.encode()).hexdigest() in raw, "the file holds the hash"
    assert token not in raw, "the file does not hold the token"
    assert "survival" in raw and '"pending"' in raw, \
        f"the file keeps no pending row for the issued node: {raw[:120]}"
    assert set(json.loads(raw)) == {"nodes", "pending"}, \
        f"the JSON shape matches the design doc: {list(json.loads(raw))}"
    stored = json.loads(raw)["nodes"]["survival"]
    assert set(stored) == {"app", "hash", "issued_at", "ttl_hours", "last_seen", "last_ip", "issued_by"}, \
        f"the stored fields are the documented ones: {sorted(stored)}"
    assert stored["ttl_hours"] == -1, f"ttl_hours is copied in at issuance: {stored}"
    assert stored["issued_by"] == "console", f"issued_by is recorded: {stored}"


def test_ttl_minus_one_is_unlimited_n_expires_and_the_entry_survives(hub, node_file, enrolled, make_hub):
    assert hub.expires_in("survival") is None, f"ttl -1 reports no expiry: {hub.expires_in('survival')}"
    reloaded = make_hub("host-a", node_file=node_file)
    assert reloaded.verify("survival", APP_ID, enrolled) == "ok", \
        "a node loaded from the file keeps working"

    ttl_hub = make_hub("host-b", ttl_hours=3)
    short = ttl_hub.issue("creative", app=APP_ID)
    assert ttl_hub.nodes["creative"]["ttl_hours"] == 3, \
        f"a positive ttl is stored on the entry: {ttl_hub.nodes['creative']}"
    remaining = ttl_hub.expires_in("creative")
    assert remaining is not None and 3 * 3600 - 5 <= remaining <= 3 * 3600, \
        f"expires_in counts down from the ttl: {remaining}"
    assert ttl_hub.verify("creative", APP_ID, short) == "ok", "verify accepts it while it is valid"
    with ttl_hub._nodes_lock:
        ttl_hub._nodes["creative"]["issued_at"] -= 4 * 3600            # backdate it past the TTL
    assert ttl_hub.verify("creative", APP_ID, short) == "expired", \
        "an expired token verifies as expired"
    assert ttl_hub.is_enrolled("creative"), f"expiry does not delete the entry: {ttl_hub.nodes}"
    assert ttl_hub.expires_in("creative") < 0, \
        f"a negative expires_in says how long ago it lapsed: {ttl_hub.expires_in('creative')}"
    rotated = ttl_hub.rotate("creative")
    assert bool(rotated), f"rotate re-issues after expiry without a new enrolment request: {rotated}"
    assert ttl_hub.verify("creative", APP_ID, rotated) == "ok", "rotate applies the current ttl"
    assert ttl_hub.verify("creative", APP_ID, short) == "unknown", \
        "the expired token is dead after the rotation"


def test_the_hub_warns_before_a_token_runs_out_once_an_hour_at_most(make_hub):
    warn_log = logging.getLogger("warning-hub")
    sink = Sink()
    warn_log.addHandler(sink)
    level = warn_log.level
    warn_log.setLevel(logging.INFO)
    try:
        warning_hub = make_hub("host-w", logger=warn_log, ttl_hours=2)
        warning_hub.issue("soon", app=APP_ID)
        warning_hub._last_expiry_warning = 0.0
        warning_hub._warn_expiring()
        assert any("expires in" in line for line in sink.lines), \
            f"a token expiring within 24h is warned about: {sink.lines}"
        assert any("soon" in line and "node rotate soon" in line for line in sink.lines), \
            f"the warning names the node and the rotation command: {sink.lines}"
        before = len(sink.lines)
        warning_hub._warn_expiring()
        assert len(sink.lines) == before, f"the warning is rate limited to once per hour: {sink.lines}"

        unlimited_hub = make_hub("host-u", logger=warn_log)
        unlimited_hub.issue("forever", app=APP_ID)
        unlimited_hub._last_expiry_warning = 0.0
        unlimited_hub._warn_expiring()
        assert not any("expires in" in line and "forever" in line for line in sink.lines), \
            f"an unlimited token is never warned about: {sink.lines}"
    finally:
        warn_log.removeHandler(sink)
        warn_log.setLevel(level)


def test_rotate_and_revoke(hub, node_file):
    first = hub.issue("creative", app=APP_ID)
    second = hub.rotate("creative")
    assert bool(second) and second != first, "rotate returns a new token"
    assert hub.verify("creative", APP_ID, first) == "unknown", "the old token dies immediately"
    assert hub.verify("creative", APP_ID, second) == "ok", "the new one works"
    assert hub.rotate("nobody") is None, "rotate refuses a name that is not enrolled"
    assert hub.revoke("creative") is True, "revoke drops the entry"
    assert hub.verify("creative", APP_ID, second) == "unknown", "the revoked token is unknown"
    assert hub.revoke("creative") is False, "revoking twice reports nothing to do"
    nodes = json.load(open(node_file, encoding="utf-8"))["nodes"]
    assert "creative" not in nodes, f"the file no longer lists the revoked node: {nodes}"
    assert not os.path.exists(node_file + ".tmp"), \
        "a coroutined node table is written atomically (no .tmp left)"


def test_an_enrolment_request_pends_and_closes_with_4007(live_hub, live_uri, open_peer):
    conn = open_peer(live_uri, hello("alpha", enroll=True))
    first_frame = json.loads(conn.recv(timeout=3))
    assert first_frame.get("type") == "enroll_pending" and first_frame.get("name") == "alpha", \
        f"the hub answers enroll_pending before closing: {first_frame}"
    try:
        conn.recv(timeout=3)
    except ConnectionClosed as exc:
        code = close_code(exc)
    else:
        pytest.fail("the enrolment request is closed with 4007: still open")
    assert code == 4007, f"the enrolment request is closed with 4007: {code}"

    assert wait_until(lambda: live_hub.is_pending("alpha"), timeout=0.2), \
        f"the request landed in pending: {live_hub.pending_requests}"
    assert live_hub.pending_requests["alpha"]["app"] == APP_ID, \
        f"pending recorded the app and the source: {live_hub.pending_requests['alpha']}"
    assert live_hub.enrol("alpha")["requests"] == 2, "asking again only counts up"
    assert live_hub.peers == [], f"pending alone authorises nothing: {live_hub.peers}"

    try:
        with raw_connect(live_uri) as anon:
            anon.send(json.dumps(hello("bravo")))
            anon.recv(timeout=3)
    except ConnectionClosed as exc:
        anon_code = close_code(exc)
    else:
        pytest.fail("a hello without a token and without enroll is refused too: answered")
    assert anon_code == 4007, f"a hello without a token and without enroll -> 4007: {anon_code}"


def test_a_probe_never_pends_and_never_issues(live_hub, live_uri):
    live_hub.enrol("alpha")             # the pending row section 5 leaves, so "only alpha" means something
    probe_result, probe_info = probe_hub_detail(live_uri, timeout=3)
    assert probe_result == "games_ai", \
        f"an anonymous probe is still recognised as a GamesAI hub: {(probe_result, probe_info)}"
    assert probe_info["peers"] == [], f"it learns no peers without a token: {probe_info}"
    assert probe_info["token_name"] is None, f"it learns no token name without a token: {probe_info}"
    try:
        with raw_connect(live_uri) as probe_conn:
            probe_conn.send(json.dumps({**hello("probe", enroll=True), "probe": True}))
            ack = json.loads(probe_conn.recv(timeout=3))
    except ConnectionClosed as exc:
        pytest.fail("a probe that also asks to enrol is answered: {}".format(close_code(exc)))
    assert ack.get("type") == "hello_ack", f"a probe that also asks to enrol is answered: {ack}"
    assert list(live_hub.pending_requests) == ["alpha"], \
        f"a probe never creates a pending row: {live_hub.pending_requests}"
    assert live_hub.peers == [], f"a probe never registers: {live_hub.peers}"


def test_a_valid_token_registers_with_expires_in_as_appropriate(live_hub, live_uri, open_peer, make_hub):
    alpha_token = live_hub.issue("alpha", app=APP_ID, ip="127.0.0.1")
    member = open_peer(live_uri, hello("alpha", token=alpha_token))
    ack = json.loads(member.recv(timeout=3))
    assert ack.get("type") == "hello_ack", f"the member got a hello_ack: {ack}"
    assert "expires_in" not in ack, f"the unlimited token sends no expires_in: {ack}"
    assert wait_until(lambda: live_hub.peers == ["alpha"], timeout=0.2), \
        f"the member is registered: {live_hub.peers}"
    assert live_hub.nodes["alpha"]["last_seen"] and live_hub.nodes["alpha"]["last_ip"] == "127.0.0.1", \
        f"last_seen and last_ip were recorded: {live_hub.nodes['alpha']}"

    limited = make_hub("host-c", ttl_hours=12)
    limited_token = limited.issue("beta", app=APP_ID)
    assert limited.start(timeout=5), "the ttl hub started"
    limited_conn = open_peer("ws://127.0.0.1:{}".format(limited.port), hello("beta", token=limited_token))
    limited_ack = json.loads(limited_conn.recv(timeout=3))
    assert 12 * 3600 - 5 <= limited_ack.get("expires_in", 0) <= 12 * 3600, \
        f"a ttl token reports expires_in: {limited_ack}"


def test_expired_revoked_and_unknown_tokens(live_hub, live_uri, open_peer):
    alpha_token = live_hub.issue("alpha", app=APP_ID, ip="127.0.0.1")
    member = open_peer(live_uri, hello("alpha", token=alpha_token))
    assert json.loads(member.recv(timeout=3)).get("type") == "hello_ack", "the member registered first"
    assert wait_until(lambda: live_hub.peers == ["alpha"], timeout=0.2), \
        f"the member is online: {live_hub.peers}"

    with live_hub._nodes_lock:
        live_hub._nodes["alpha"]["ttl_hours"] = 1
        live_hub._nodes["alpha"]["issued_at"] = int(time.time()) - 10 * 3600
    assert live_hub.verify("alpha", APP_ID, alpha_token) == "expired", \
        "verify agrees the token is expired"
    assert live_hub.peers == ["alpha"], f"expiry never interrupts the live session: {live_hub.peers}"
    try:
        with raw_connect(live_uri) as expired_conn:
            expired_conn.send(json.dumps(hello("alpha", token=alpha_token)))
            expired_conn.recv(timeout=3)
    except ConnectionClosed as exc:
        expired_code = close_code(exc)
    else:
        pytest.fail("an expired token is refused: answered")
    assert expired_code == 4008, f"an expired token -> close 4008: {expired_code}"
    with live_hub._nodes_lock:
        live_hub._nodes["alpha"]["ttl_hours"] = -1                       # unlimited again
    assert live_hub.verify("alpha", APP_ID, alpha_token) == "ok", "an unlimited entry never expires"

    live_hub.revoke("alpha")
    try:
        with raw_connect(live_uri) as revoked_conn:
            revoked_conn.send(json.dumps(hello("alpha", token=alpha_token)))
            revoked_conn.recv(timeout=3)
    except ConnectionClosed as exc:
        revoked_code = close_code(exc)
    else:
        pytest.fail("a revoked token is refused: answered")
    assert revoked_code == 4001, f"a revoked token -> close 4001: {revoked_code}"

    try:
        with raw_connect(live_uri) as wrong_conn:
            wrong_conn.send(json.dumps(hello("alpha", token="not-a-token")))
            wrong_conn.recv(timeout=3)
    except ConnectionClosed as exc:
        wrong_code = close_code(exc)
    else:
        pytest.fail("an unknown token is refused: answered")
    assert wrong_code == 4001, f"an unknown token -> close 4001: {wrong_code}"


def test_probes_and_app_ids_keep_their_old_behaviour(live_hub, live_uri):
    try:
        with raw_connect(live_uri) as foreign:
            foreign.send(json.dumps({"type": "hello", "app": "not_games_ai", "protocol": 1,
                                     "server": "x"}))
            foreign.recv(timeout=3)
    except ConnectionClosed as exc:
        app_code = close_code(exc)
    else:
        pytest.fail("an unknown app id is refused: answered")
    assert app_code == 4005, f"an unknown app id -> 4005: {app_code}"

    try:
        with raw_connect(live_uri) as no_name:
            no_name.send(json.dumps(hello("", token="whatever")))
            no_name.recv(timeout=3)
    except ConnectionClosed as exc:
        name_code = close_code(exc)
    else:
        pytest.fail("a hello without a name is refused: answered")
    assert name_code == 4002, f"a hello without a name -> 4002: {name_code}"
