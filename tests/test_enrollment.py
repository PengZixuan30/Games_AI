"""Per-node enrolment, node and command half.

Covers the last three groups of docs/token-enrollment.md §12: the node side (claim writes
the identity file and refuses a mismatched name, status hides the plaintext, forget deletes
it, 4007/4008 are not retried, a valid identity connects as a client), the commands
(permission gating, A-class only, masking) and the bot's token being provisioned without a
manual step.
"""
import io
import json
import logging
import os
import secrets

import pytest

from websockets.sync.client import connect as raw_connect

import yaml

import games_ai
from games_ai.config import plugin_config
from games_ai.cross_server import CrossServerManager
from games_ai.websockets_client import (
    APP_ID,
    APP_ID_BOT,
    ENROLMENT_REQUIRED_HINT,
    TOKEN_EXPIRED_HINT,
    CrossServerNode,
    token_fingerprint,
)
from games_ai.websockets_server import CrossServerHub

from _helpers.paths import LANG_DIR
from _helpers.pkg import module_text, package_text
from _helpers.wait import wait_until

LOG = logging.getLogger("test")


class LogCapture(logging.Handler):
    """Keeps what the plugin logged, so 'never log a token' can be checked for real."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def clear(self):
        self.records.clear()


class FakeServer:
    """The plugin's view of MCDR: a data folder, a logger and the real translation table."""

    def __init__(self, folder, lang):
        self.folder = folder
        self.lang = lang
        self.logger = logging.getLogger("fake-server")
        self.saved = None

    def rtr(self, translation_key, *args, **kwargs):
        node = self.lang
        for part in translation_key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if not isinstance(node, str):
            return translation_key       # MCDR returns the key when it is not translated
        try:
            return node.format(*args, **kwargs)
        except (IndexError, KeyError) as exc:
            return "<FORMAT ERROR {}: {}>".format(translation_key, exc)

    def get_data_folder(self):
        return self.folder

    def save_config_simple(self, config, **kwargs):
        self.saved = json.loads(json.dumps(config))

    def execute_command(self, raw, source=None):
        return None


class FakeSource:
    """A command source, bound to the server the plugin should ask about itself."""

    def __init__(self, server, who="console", permission=4, console=True):
        self.server = server
        self.player = None if console else who
        self.permission = permission
        self.console = console
        self.received = []

    def get_server(self):
        return self.server

    def get_permission_level(self):
        return self.permission

    @property
    def is_console(self):
        return self.console

    @property
    def is_player(self):
        return not self.console

    def reply(self, message, **kwargs):
        self.received.append(message)

    def __str__(self):
        return "console" if self.console else str(self.player)

    def text(self):
        return "\n".join(str(item) for item in self.received)


class Ctx(dict):
    """Stands in for MCDR's CommandContext (context.get(key))."""


class FakeManager:
    """An already-decided manager, so the hub-side commands have something to talk to."""

    def __init__(self, hub, mode="server"):
        self.hub = hub
        self.mode = mode
        self.name = hub.name if hub is not None else "hub"

    @property
    def is_server(self):
        return self.mode == "server"

    @property
    def is_client(self):
        return self.mode == "client"

    @property
    def connected(self):
        return True

    def stop(self):
        return None


class FakeConnection:
    """Just enough of a ServerConnection for the handshake decision."""

    def __init__(self, frame, ip):
        self._frame = json.dumps(frame)
        self.remote_address = (ip, 4455)
        self.closed = []

    def recv(self, timeout=None):
        frame, self._frame = self._frame, None
        if frame is None:
            raise TimeoutError("no more frames")
        return frame

    def close(self, code, reason):
        self.closed.append((code, reason))


class Capture:
    """Collects the built command tree instead of handing it to MCDR."""

    def __init__(self):
        self.roots = []

    def register_command(self, node):
        self.roots.append(node)


def plain_reply(source):
    """What a source was told, as plain text (reply objects are not strings)."""
    text = []
    for item in source.received:
        text.append(item.to_plain_text() if hasattr(item, "to_plain_text") else str(item))
    return "\n".join(text)


@pytest.fixture(scope="module")
def lang():
    """MCDR's en_us table, so the fake server translates exactly like the real one."""
    with io.open(os.path.join(LANG_DIR, "en_us.yml"), encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@pytest.fixture(scope="module")
def fake_server(lang, tmp_path_factory):
    """The plugin's view of MCDR: a data folder outside the repository, its logger, the table."""
    return FakeServer(str(tmp_path_factory.mktemp("gamesai_enrol")), lang)


@pytest.fixture
def source(fake_server):
    """Build a command source like MCDR hands the plugin one."""
    def _source(who="console", permission=4, console=True):
        return FakeSource(fake_server, who=who, permission=permission, console=console)

    return _source


@pytest.fixture
def make_hub(free_port, tmp_path):
    """Start hubs on this test's own node tables; every one of them is stopped at teardown."""
    created = []

    def _make(tag="hub", **kwargs):
        port = free_port()
        hub = CrossServerHub("127.0.0.1", port, name="host-a", logger=LOG,
                             node_file=str(tmp_path / (tag + "_nodes.json")), **kwargs)
        assert hub.start(timeout=5), "the hub did not start"
        created.append(hub)
        return hub, "ws://127.0.0.1:{}".format(port)

    yield _make
    for hub in created:
        hub.stop()


@pytest.fixture
def command_hub(make_hub):
    """The hub the plugin-side sections talk to."""
    return make_hub("command")[0]


@pytest.fixture
def command_uri(command_hub):
    return "ws://127.0.0.1:{}".format(command_hub.port)


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


@pytest.fixture
def plugin_logger_state():
    """Put the plugin's stdlib logger back after a test that made the plugin attach itself.

    ``_start_cross_server`` calls ``logger.attach(server)``: it copies MCDR's handlers onto the
    ``games_ai`` logger and cuts its propagation to root. Right in production, wrong to keep
    feeding the next suite in this pytest process, so the state is snapshotted here.
    """
    plugin_logger = logging.getLogger("games_ai")
    handlers = list(plugin_logger.handlers)
    propagate = plugin_logger.propagate
    level = plugin_logger.level
    yield plugin_logger
    plugin_logger.handlers = handlers
    plugin_logger.propagate = propagate
    plugin_logger.setLevel(level)


@pytest.fixture
def update_round_state(monkeypatch):
    """Pin the updater module's attach targets: ``_start_cross_server`` rebinds them.

    ``monkeypatch`` records today's values and puts them back even though the code under test
    changed them, so a later suite never inherits a link that is already stopped.
    """
    module = games_ai.update_round
    for name in ("_server_of", "_manager_of", "_link_thread_of", "_version"):
        monkeypatch.setattr(module, name, getattr(module, name, None), raising=False)
    return module


@pytest.fixture(autouse=True)
def plugin_config_state():
    """Leave ``plugin_config`` exactly as it was found.

    ``monkeypatch`` puts a patched field back by *setting* it, which turns a class default
    into an instance attribute that stays behind for every later suite in this process. The
    fields are snapshotted here too (an autouse fixture is finalised after ``monkeypatch``),
    so the next suite sees the object the module was imported with.
    """
    saved = dict(vars(plugin_config))
    yield
    for key in [key for key in vars(plugin_config) if key not in saved]:
        delattr(plugin_config, key)
    vars(plugin_config).update(saved)


@pytest.fixture
def log_capture(fake_server, plugin_logger_state):
    """Keep what the fake server's logger sees while the test runs."""
    capture = LogCapture()
    fake_server.logger.addHandler(capture)
    level = fake_server.logger.level
    fake_server.logger.setLevel(logging.DEBUG)
    yield capture
    fake_server.logger.removeHandler(capture)
    fake_server.logger.setLevel(level)
    plugin_logger_state.removeHandler(capture)


@pytest.fixture
def wired(monkeypatch, fake_server, command_uri, plugin_logger_state, update_round_state):
    """The module-level view MCDR gives the plugin, pointed at this test's fake server.

    ``node claim`` reaches through ``_server_ref``, ``plugin_config`` and the plugin's logger
    and then starts a *real* link, so every global it writes is pinned with ``monkeypatch``;
    the link itself is stopped in teardown -- a live client would keep re-registering on the
    shared hub after the test is over.
    """
    monkeypatch.setattr(games_ai, "_server_ref", fake_server, raising=False)
    monkeypatch.setattr(games_ai, "_config_ref", {}, raising=False)
    monkeypatch.setattr(games_ai, "_cross_server", None, raising=False)
    monkeypatch.setattr(games_ai, "_cross_server_thread", None, raising=False)
    monkeypatch.setattr(games_ai.logger, "_server", fake_server, raising=False)
    monkeypatch.setattr(plugin_config, "prefix", "[GamesAI]")
    monkeypatch.setattr(plugin_config, "allow_permission", 3)
    monkeypatch.setattr(plugin_config, "websocket_uri", command_uri)
    monkeypatch.setattr(plugin_config, "websocket_name", "survival")
    monkeypatch.setattr(plugin_config, "cross_server_name", "survival")
    monkeypatch.setattr(plugin_config, "cross_server_mode", "local")
    monkeypatch.setattr(plugin_config, "websocket_identity_file", "")
    monkeypatch.setattr(plugin_config, "websocket_auto_enroll", True)
    monkeypatch.setattr(plugin_config, "websocket_token_ttl_hours", -1)
    monkeypatch.setattr(plugin_config, "skills_path",
                        os.path.join(fake_server.folder, "skills", "skills.json"))
    yield fake_server
    games_ai._stop_cross_server(fake_server)


def test_a_node_without_a_token_asks_to_enrol_then_gives_up(make_hub):
    hub, uri = make_hub("plain")
    node = CrossServerNode(uri, "alpha", "", logger=LOG, reconnect=True, reconnect_delays=(0.05,))
    try:
        assert node.start(timeout=5) is False, "the handshake does not succeed"
        assert node.fatal_error == ENROLMENT_REQUIRED_HINT, \
            f"the node reports the enrolment hint: {node.fatal_error}"
        assert "not enrolled" in node.fatal_error and "node claim" in node.fatal_error, \
            f"the actionable words are in it: {node.fatal_error}"
        assert node.enrol_requested, "the node knows it asked to enrol"
        assert hub.is_pending("alpha"), f"the hub lists it as pending: {hub.pending_requests}"
        assert hub.pending_requests["alpha"]["app"] == APP_ID, \
            f"pending carries the requesting app: {hub.pending_requests}"
        assert wait_until(lambda: not node._thread.is_alive() if node._thread is not None else True,
                          timeout=0.4), "it does not reconnect in a loop (one attempt, then done)"
        assert not hub.is_enrolled("alpha"), "nothing was issued"
    finally:
        node.stop()


def test_without_auto_enroll_4007_is_still_fatal_and_nothing_is_recorded(make_hub):
    hub, uri = make_hub("plain")
    quiet = CrossServerNode(uri, "quiet", "", logger=LOG, reconnect=True, reconnect_delays=(0.05,),
                            auto_enroll=False)
    try:
        assert quiet.start(timeout=5) is False, "the handshake does not succeed"
        assert quiet.fatal_error == ENROLMENT_REQUIRED_HINT, \
            f"the close code is reported as the enrolment hint: {quiet.fatal_error}"
        assert not hub.is_pending("quiet"), f"no pending row was created: {hub.pending_requests}"
        assert wait_until(lambda: not quiet._thread.is_alive(), timeout=0.4), \
            "no reconnect loop either"
    finally:
        quiet.stop()


def test_an_expired_token_is_4008_fatal_and_not_retried(make_hub):
    ttl_hub, ttl_uri = make_hub("ttl", ttl_hours=1)
    expired_token = ttl_hub.issue("alpha", app=APP_ID)
    with ttl_hub._nodes_lock:
        ttl_hub._nodes["alpha"]["issued_at"] -= 3 * 3600
    stale = CrossServerNode(ttl_uri, "alpha", expired_token, logger=LOG, reconnect_delays=(0.05,))
    try:
        assert stale.start(timeout=5) is False, "the handshake does not succeed"
        assert stale.fatal_error == TOKEN_EXPIRED_HINT, \
            f"the node says the token expired: {stale.fatal_error}"
        assert "node rotate" in stale.fatal_error and "node claim" in stale.fatal_error, \
            f"and points at node rotate / node claim: {stale.fatal_error}"
        assert wait_until(lambda: not stale._thread.is_alive(), timeout=0.4), \
            "it stops instead of retrying"
    finally:
        stale.stop()


def test_a_revoked_token_is_4001_and_fatal(make_hub):
    ttl_hub, ttl_uri = make_hub("ttl", ttl_hours=1)
    revoked_token = ttl_hub.issue("beta", app=APP_ID)
    ttl_hub.revoke("beta")
    gone = CrossServerNode(ttl_uri, "beta", revoked_token, logger=LOG, reconnect_delays=(0.05,))
    try:
        assert gone.start(timeout=5) is False, "the handshake does not succeed"
        assert "token" in (gone.fatal_error or ""), f"the reason mentions the token: {gone.fatal_error}"
        assert wait_until(lambda: not gone._thread.is_alive(), timeout=0.4), \
            "no retry for a dead token"
    finally:
        gone.stop()


def test_a_node_with_a_valid_identity_connects_as_a_client(make_hub):
    ttl_hub, ttl_uri = make_hub("ttl", ttl_hours=1)
    good_token = ttl_hub.issue("gamma", app=APP_ID)
    good = CrossServerNode(ttl_uri, "gamma", good_token, logger=LOG)
    try:
        assert good.start(timeout=5) is True, "the handshake succeeds"
        assert 0 < (good.expires_in or 0) <= 3600, f"the hub reports the ttl in the ack: {good.expires_in}"
        assert good.hub_name == "host-a", f"the node remembers the hub name: {good.hub_name}"
        assert wait_until(lambda: "gamma" in ttl_hub.peers, timeout=0.2), \
            f"the hub has it online: {ttl_hub.peers}"
        assert not ttl_hub.is_pending("gamma"), \
            f"no enrolment request was made: {ttl_hub.pending_requests}"
    finally:
        good.stop()


def test_the_identity_file_and_the_node_side_commands(wired, command_hub, command_uri, source,
                                                      monkeypatch, free_port):
    identity_path = os.path.join(wired.folder, "cross_server", "identity.json")
    if os.path.isfile(identity_path):
        os.remove(identity_path)

    console = source("console", permission=4, console=True)
    games_ai._node_status(console)
    assert "enrolled: no" in console.text() and "not enrolled" in console.text(), \
        f"status reports this instance as not enrolled: {console.text()}"
    assert "fingerprint: -" in console.text(), \
        f"status does not invent a fingerprint: {console.text()}"

    survival_token = command_hub.issue("survival", app=APP_ID)
    other_token = command_hub.issue("creative", app=APP_ID)

    stranger = source("Steve", permission=4, console=False)
    games_ai._node_claim(stranger, Ctx(token=other_token))
    assert "creative" in stranger.text() and "survival" in stranger.text(), \
        f"a token for another name is refused: {stranger.text()}"
    assert not os.path.isfile(identity_path), f"and nothing was written: {os.listdir(wired.folder)}"

    games_ai._node_claim(stranger, Ctx(token="not-a-real-token"))
    assert "does not know" in stranger.text(), \
        f"a token the hub does not know is refused: {stranger.text()}"
    assert not os.path.isfile(identity_path), "still nothing written"

    with monkeypatch.context() as patch:
        patch.setattr(plugin_config, "websocket_uri", "ws://127.0.0.1:{}".format(free_port()))
        games_ai._node_claim(stranger, Ctx(token=survival_token))
    assert "did not answer" in stranger.text(), \
        f"an unreachable hub refuses the claim: {stranger.text()}"

    games_ai._node_claim(console, Ctx(token=survival_token))
    assert "Enrolled as survival" in console.text(), f"the claim is accepted: {console.text()}"
    assert os.path.isfile(identity_path), "the identity file exists"
    identity = json.load(open(identity_path, encoding="utf-8"))
    assert identity.get("name") == "survival", f"it carries the right name: {identity}"
    assert identity.get("token") == survival_token, f"it carries the token: {identity}"
    assert identity.get("hub") == command_uri, f"it records the hub it was issued for: {identity}"
    assert isinstance(identity.get("issued_at"), int), f"it records when it was issued: {identity}"
    if os.name == "posix":
        assert oct(os.stat(identity_path).st_mode & 0o777) == "0o600", \
            f"the file is chmod 600: {oct(os.stat(identity_path).st_mode & 0o777)}"

    assert wait_until(lambda: plugin_config.cross_server_mode == "client"
                              and games_ai._cross_server is not None
                              and games_ai._cross_server.is_client, timeout=10), \
        f"the claim reconnects immediately and the instance becomes a client: " \
        f"{plugin_config.cross_server_mode}"
    assert "survival" in command_hub.peers, f"the hub sees the claimed node: {command_hub.peers}"

    status = source("console", permission=4, console=True)
    games_ai._node_status(status)
    text = status.text()
    assert "enrolled: yes" in text, f"status now reports enrolled: {text}"
    assert token_fingerprint(survival_token) in text, \
        f"status shows the fingerprint: {(text, token_fingerprint(survival_token))}"
    assert survival_token not in text, f"status hides the plaintext token: {text}"
    assert other_token not in text, f"status hides every plaintext token: {text}"

    forget = source("console", permission=4, console=True)
    games_ai._node_forget(forget)
    assert not os.path.isfile(identity_path), \
        f"forget deletes the identity file: {os.listdir(wired.folder)}"
    assert "Deleted the identity file" in forget.text(), f"forget says what it did: {forget.text()}"
    assert games_ai._cross_server is None and plugin_config.cross_server_mode == "local", \
        f"forget stops the link: {plugin_config.cross_server_mode}"
    games_ai._node_forget(forget)
    assert "no identity file" in forget.text(), f"forgetting twice is harmless: {forget.text()}"


def test_hub_side_commands_permission_strict_issuance_and_masking(wired, command_hub, source,
                                                                 monkeypatch):
    monkeypatch.setattr(games_ai, "_cross_server", FakeManager(command_hub), raising=False)
    command_hub.enrol("newbie", app=APP_ID, ip="10.0.0.7")
    command_hub.enrol("second", app=APP_ID, ip="10.0.0.8")

    low = source("Steve", permission=1, console=False)
    games_ai._node_pending(low)
    assert "permission" in low.text().lower(), f"a low permission level is refused: {low.text()}"
    games_ai._node_token(low, Ctx(name="newbie"))
    assert not command_hub.is_enrolled("newbie"), "and cannot issue a token"
    assert "Permission level 3" in low.text(), f"the refusal is the standard one: {low.text()}"

    admin = source("console", permission=4, console=True)
    games_ai._node_pending(admin)
    assert "newbie" in admin.text() and "second" in admin.text(), \
        f"pending lists the waiting names: {admin.text()}"
    assert "10.0.0.7" in admin.text() and APP_ID in admin.text(), \
        f"pending shows the source address and the app: {admin.text()}"

    admin.received.clear()
    games_ai._node_token(admin, Ctx(name="ghost"))
    assert "has not asked to enrol" in admin.text(), \
        f"issuing for a name nobody is waiting for is refused: {admin.text()}"
    assert not command_hub.is_enrolled("ghost"), "and no token was created"

    admin.received.clear()
    games_ai._node_token(admin, Ctx(name="newbie"))
    issued_text = admin.text()
    assert command_hub.is_enrolled("newbie"), f"the waiting name gets a token: {command_hub.nodes}"
    assert not command_hub.is_pending("newbie"), "the pending row is consumed"
    printed = [chunk for chunk in issued_text.split() if len(chunk) == 43]
    assert bool(printed) and command_hub.verify("newbie", APP_ID, printed[0]) == "ok", \
        f"the printed value is the token that verifies at the hub: {printed}"
    if printed:
        assert issued_text.count(printed[0]) == 1, \
            f"the token appears in exactly that one reply: {issued_text}"
    else:
        pytest.fail("the token appears in exactly that one reply: no token was printed")
    assert command_hub.fingerprint("newbie") in issued_text, \
        f"the reply carries the fingerprint too: {issued_text}"
    assert command_hub.nodes["newbie"]["issued_by"] == "console", \
        f"issued_by records who asked: {command_hub.nodes['newbie']}"

    admin.received.clear()
    games_ai._node_list(admin)
    listed = admin.text()
    assert "newbie" in listed, f"node list shows the enrolled node: {listed}"
    assert command_hub.fingerprint("newbie") in listed, f"node list shows a fingerprint: {listed}"
    assert printed[0] not in listed, f"node list never shows the plaintext: {listed}"
    assert "unlimited" in listed, f"node list shows the ttl: {listed}"

    admin.received.clear()
    games_ai._node_rotate(admin, Ctx(name="second"))
    assert "not enrolled" in admin.text(), \
        f"rotate refuses a name that is not enrolled yet: {admin.text()}"
    second_token = command_hub.issue("second", app=APP_ID)
    admin.received.clear()
    games_ai._node_rotate(admin, Ctx(name="second"))
    assert command_hub.verify("second", APP_ID, second_token) == "unknown", \
        f"rotate prints a new token: {admin.text()}"
    rotated_printed = [chunk for chunk in admin.text().split() if len(chunk) == 43]
    assert bool(rotated_printed) and command_hub.verify("second", APP_ID, rotated_printed[0]) == "ok", \
        f"the new token works: {rotated_printed}"

    admin.received.clear()
    games_ai._node_revoke(admin, Ctx(name="second"))
    assert not command_hub.is_enrolled("second"), "revoke drops the node"
    assert "4001" in admin.text(), f"revoke says what happens next: {admin.text()}"
    admin.received.clear()
    games_ai._node_revoke(admin, Ctx(name="second"))
    assert "not enrolled" in admin.text(), f"revoking an unknown node says so: {admin.text()}"

    monkeypatch.setattr(games_ai, "_cross_server", FakeManager(command_hub, mode="client"),
                        raising=False)
    admin.received.clear()
    games_ai._node_pending(admin)
    assert "not the hub" in admin.text(), f"a client instance is not the hub: {admin.text()}"
    monkeypatch.setattr(games_ai, "_cross_server", None, raising=False)
    admin.received.clear()
    games_ai._node_list(admin)
    assert "not the hub" in admin.text(), f"no link at all is not the hub either: {admin.text()}"


def test_every_node_command_is_a_class_registered_plainly_never_routed(source, monkeypatch, tmp_path):
    node_source = module_text("__init__.py")
    node_lines = [line for line in node_source.splitlines() if "builder.command('!!gamesai node" in line]
    assert len(node_lines) == 9, f"all nine registrations are present: {node_lines}"
    assert all("_route(" not in line for line in node_lines), \
        f"none of them goes through _route(): {node_lines}"
    assert "ROUTE_CLUSTER" not in "".join(node_lines) and "ROUTE_SERVER" not in "".join(node_lines), \
        f"none of them mentions a cluster route: {node_lines}"

    monkeypatch.setattr(plugin_config, "data_path", str(tmp_path / "public_database.db"))
    capture = Capture()
    games_ai.register_commands(capture, {})
    node_root = None
    for root in capture.roots:
        if "!!gamesai" in getattr(root, "literals", set()):
            node_root = root
    assert node_root is not None, "the command tree built"
    node_literal = None
    for child in (node_root.get_children() if node_root is not None else []):
        if "node" in getattr(child, "literals", set()):
            node_literal = child
    assert node_literal is not None, "the !!gamesai node group exists"

    callbacks = {}
    if node_literal is not None:
        for child in node_literal.get_children():
            name = sorted(getattr(child, "literals", []))[0] if getattr(child, "literals", None) \
                else "arg"
            callbacks[name] = child
    assert {"pending", "token", "list", "revoke", "rotate", "claim", "status", "forget"} \
        <= set(callbacks), f"every subcommand node is registered: {sorted(callbacks)}"
    assert all(getattr(node_callbacks._callback, "__wrapped__", None) is None
               for node_callbacks in callbacks.values() if node_callbacks._callback is not None), \
        "their callbacks are the plain handlers, not _route wrappers: {}".format(
            {name: getattr(cb._callback, "__wrapped__", None) for name, cb in callbacks.items()})

    # The arguments have to survive MCDR's own parsers: a 43-character url-safe token, a node
    # name, and the literal subcommand (checked through the nodes MCDR will really use).
    real_token = secrets.token_urlsafe(32)
    claim_arg = callbacks["claim"].get_children()[0]
    parsed_token = claim_arg.parse(real_token)
    assert parsed_token.value == real_token and parsed_token.char_read == len(real_token), \
        f"a 43-character url-safe token parses as the claim argument: {parsed_token}"
    name_arg = callbacks["token"].get_children()[0]
    parsed_name = name_arg.parse("survival")
    assert parsed_name.value == "survival" and parsed_name.char_read == 8, \
        f"a node name parses as the name argument: {parsed_name}"
    parsed_literal = callbacks["status"].parse("status")
    assert parsed_literal.char_read == 6, f"the literal subcommands parse: {parsed_literal}"

    forwarded = []

    class FakeClientManager:
        mode = "client"
        is_client = True
        is_server = False
        connected = True
        name = "host-b"
        node = None
        hub = None
        hub_name = "host-a"
        token_expires_in = None

        def send_to_hub(self, *args, **kwargs):
            forwarded.append(args)
            return None

    monkeypatch.setattr(games_ai, "_forward_command",
                        lambda *args, **kwargs: forwarded.append(args), raising=False)
    monkeypatch.setattr(games_ai, "_cross_server", FakeClientManager(), raising=False)
    routed_source = source("Steve", permission=4, console=False)
    info = type("Info", (), {"content": "!!gamesai node status"})()
    routed_source.get_info = lambda: info
    from mcdreforged.command.builder.callback import DirectCallbackInvoker, ScheduledCallback
    ScheduledCallback(callbacks["status"]._callback, (routed_source,),
                      lambda e: e).invoke(DirectCallbackInvoker())
    assert "role:" in routed_source.text(), \
        f"the command ran where it was typed, on a client: {routed_source.text()}"
    assert forwarded == [], f"and it was not forwarded to the hub: {forwarded}"


def test_masking_in_config_get_and_the_stale_key_is_dropped_on_migration(wired, source, monkeypatch):
    config_path = os.path.join(wired.folder, "config.json")
    with open(config_path, "w", encoding="utf-8") as handle:
        json.dump({"prefix": "[GamesAI]",
                   "websocket": {"uri": "ws://127.0.0.1:8080", "token": "stale-shared-secret"}},
                  handle)
    reader = games_ai.ConfigManager({"prefix": "[GamesAI]"})
    admin = source("console", permission=4, console=True)
    admin.received.clear()
    reader.get_config(admin, Ctx(key="websocket"))
    assert "ws://127.0.0.1:8080" in admin.text(), f"config get renders the block: {admin.text()}"
    assert "stale-shared-secret" not in admin.text() and "<masked>" in admin.text(), \
        f"config get masks a stale websocket.token: {admin.text()}"
    admin.received.clear()
    reader.get_config(source("Steve", permission=1, console=False), Ctx(key="websocket"))
    assert "<masked>" not in admin.text(), f"config get is permission gated: {admin.text()}"

    stale = {"prefix": "[GamesAI]", "websocket": {"uri": "ws://x:1", "token": "leftover"}}
    assert games_ai._migrate_config_data(stale) is True, "migration reports the change"
    assert "token" not in stale["websocket"], f"migration drops websocket.token: {stale}"
    assert stale["websocket"]["uri"] == "ws://x:1", f"migration keeps the rest of the block: {stale}"
    assert "websocket.token" in (games_ai._config_migration_note or ""), \
        f"migration explains itself: {games_ai._config_migration_note}"
    monkeypatch.setattr(games_ai, "_config_migration_note", None, raising=False)
    assert games_ai._migrate_config_data({"websocket": {"uri": "ws://x:1"}}) is True, \
        "an incomplete websocket block is completed (MCDR does not fill nested defaults)"
    defaults = package_text()
    defaults = defaults.split("DEFAULT_WEBSOCKET_CONFIG: dict = ")[1].split("def _default_websocket_block")[0]
    assert '"token":' not in defaults, f"the default schema has no shared token: {defaults}"
    assert not hasattr(plugin_config, "websocket_token"), \
        f"and no shared-token field survived on the config object: {dir(plugin_config)}"
    assert '"token_ttl_hours": -1' in defaults and '"auto_enroll": True' in defaults \
        and '"identity_file": ""' in defaults, f"the new keys are in the default schema: {defaults}"


def test_the_bot_is_provisioned_by_the_hub_without_a_human_step(make_hub, tmp_path, open_peer):
    bot_calls = []
    bot_hub, bot_uri = make_hub("bot", on_bot_token=lambda name, token: bot_calls.append((name, token)))
    assert bot_hub._bot_auto_issue_allowed("127.0.0.1"), \
        "loopback is trusted for automatic issuance"
    assert not bot_hub._bot_auto_issue_allowed("203.0.113.9"), \
        "an unenrolled stranger address is not"
    assert not bot_hub._bot_auto_issue_allowed("198.51.100.7"), \
        "nor is a documentation-range address"
    bot_hub.enrol("peer-host", app=APP_ID, ip="203.0.113.9")
    bot_hub.issue("peer-host", app=APP_ID, ip="203.0.113.9")
    bot_hub.record_seen("peer-host", "203.0.113.9")
    assert bot_hub._bot_auto_issue_allowed("203.0.113.9"), "an enrolled node's address is trusted"
    assert not bot_hub._bot_auto_issue_allowed(""), "an empty address is never trusted"

    stranger_conn = FakeConnection({"type": "hello", "app": APP_ID_BOT, "protocol": 1,
                                    "server": "Steve", "version": "0.8.0", "enroll": True},
                                   "198.51.100.7")
    verdict = bot_hub._handshake(stranger_conn)
    assert verdict.name is None and verdict.issued_token is None, \
        f"a bot from an unknown address is not issued a token: {verdict}"
    assert [code for code, _ in stranger_conn.closed] == [4007], \
        f"it is closed with 4007: {stranger_conn.closed}"
    assert bot_hub.is_pending("Steve") and not bot_hub.is_enrolled("Steve"), \
        f"and it is only recorded as pending: {bot_hub.pending_requests}"

    local_conn = FakeConnection({"type": "hello", "app": APP_ID_BOT, "protocol": 1,
                                 "server": "Steve", "version": "0.8.0"}, "127.0.0.1")
    verdict = bot_hub._handshake(local_conn)
    assert bool(verdict.issued_token), f"a bot on the hub's machine is issued a token: {verdict}"
    assert bot_hub.verify("Steve", APP_ID_BOT, verdict.issued_token) == "ok", \
        "the hub knows that token"
    assert bot_calls and bot_calls[-1][0] == "Steve", \
        f"the plugin was told, so it can store it: {bot_calls}"
    assert bot_hub.nodes["Steve"]["app"] == APP_ID_BOT, \
        f"the bot entry is marked as a bot: {bot_hub.nodes['Steve']}"
    assert not bot_hub.is_pending("Steve"), "the bot never needed a pending row"

    bot_conn = open_peer(bot_uri, {"type": "hello", "app": APP_ID_BOT, "protocol": 1, "server": "Alex",
                                   "version": "0.8.0", "enroll": True})
    bot_ack = json.loads(bot_conn.recv(timeout=3))
    assert bool(bot_ack.get("token")), \
        f"a real loopback bot handshake gets a token in the ack: {bot_ack}"
    first_issued = bot_ack.get("token")
    assert bot_hub.verify("Alex", APP_ID_BOT, first_issued) == "ok", "that token verifies"
    assert "Alex" in bot_hub.peers, f"the hub registered the bot: {bot_hub.peers}"

    again = open_peer(bot_uri, {"type": "hello", "app": APP_ID_BOT, "protocol": 1, "server": "Alex",
                                "version": "0.8.0", "token": first_issued})
    again_ack = json.loads(again.recv(timeout=3))
    assert again_ack.get("type") == "hello_ack" and "token" not in again_ack, \
        f"a bot that brings its token is accepted without a new one: {again_ack}"
    assert wait_until(lambda: token_fingerprint(first_issued) == bot_hub.fingerprint("Alex"), timeout=0.2), \
        f"the second connect was not a new issuance: {bot_hub.nodes['Alex']}"
    assert json.load(open(tmp_path / "bot_nodes.json", encoding="utf-8"))["nodes"]["Alex"]["hash"] \
        == bot_hub.nodes["Alex"]["hash"], "the hash is what the file holds"


def test_the_bots_config_keeps_the_token_the_hub_issued(wired, command_hub, source, monkeypatch,
                                                        log_capture):
    bot_dir = os.path.join(wired.folder, "mineflayer")
    os.makedirs(bot_dir, exist_ok=True)
    bot_config_path = os.path.join(bot_dir, "config.json")
    monkeypatch.setattr(plugin_config, "mineflayer_init_js_path", os.path.join(bot_dir, "init.js"))
    with open(bot_config_path, "w", encoding="utf-8") as handle:
        json.dump({"enabled": True, "websocket": {"url": "ws://127.0.0.1:1", "token": "old-bot-token"}},
                  handle)
    games_ai._write_mineflayer_config(wired, {"mineflayer_bot": {"enabled": True}},
                                      "ws://127.0.0.1:2")
    written = json.load(open(bot_config_path, encoding="utf-8"))
    assert written["websocket"]["token"] == "old-bot-token", \
        f"a config rewrite keeps the bot's token: {written['websocket']}"
    assert written["websocket"]["url"] == "ws://127.0.0.1:2", f"and updates the address: {written}"

    log_capture.clear()
    games_ai._store_bot_token(wired, "Steve", "wrong-bot-name-token")
    assert json.load(open(bot_config_path, encoding="utf-8"))["websocket"]["token"] == "old-bot-token", \
        "a token for another bot name is not stored here"
    monkeypatch.setattr(plugin_config, "bot_username", "Bot")
    games_ai._store_bot_token(wired, "Bot", "the-issued-bot-token")
    assert json.load(open(bot_config_path, encoding="utf-8"))["websocket"]["token"] == "the-issued-bot-token", \
        f"the issued token is written next to the address: {json.load(open(bot_config_path, encoding='utf-8'))}"
    assert all("the-issued-bot-token" not in str(record.getMessage())
               for record in log_capture.records), \
        "the plugin never logs the bot token itself: {}".format(
            [record.getMessage() for record in log_capture.records])
    assert any(token_fingerprint("the-issued-bot-token") in str(record.getMessage())
               for record in log_capture.records), \
        "it logs the fingerprint instead: {}".format(
            [record.getMessage() for record in log_capture.records])

    # The bot cannot type `node claim`: issuing or rotating its token on this machine has to keep
    # the bot's config in step, or the "no human step" provisioning would only work once.
    command_hub.enrol("Bot", app=APP_ID_BOT)
    monkeypatch.setattr(games_ai, "_cross_server", FakeManager(command_hub), raising=False)
    admin = source("console", permission=4, console=True)
    admin.received.clear()
    games_ai._node_token(admin, Ctx(name="Bot"))
    bot_printed = [chunk for chunk in admin.text().split() if len(chunk) == 43]
    assert bool(bot_printed) \
        and json.load(open(bot_config_path, encoding="utf-8"))["websocket"]["token"] == bot_printed[0], \
        "issuing the local bot's token writes it into the bot config: {}".format(
            (bot_printed, json.load(open(bot_config_path, encoding="utf-8"))["websocket"]))
    admin.received.clear()
    games_ai._node_rotate(admin, Ctx(name="Bot"))
    rotated_bot = [chunk for chunk in admin.text().split() if len(chunk) == 43]
    assert bool(rotated_bot) and rotated_bot[0] != bot_printed[0] \
        and json.load(open(bot_config_path, encoding="utf-8"))["websocket"]["token"] == rotated_bot[0], \
        "rotating it does too: {}".format(
            (rotated_bot, json.load(open(bot_config_path, encoding="utf-8"))["websocket"]))
    assert command_hub.verify("Bot", APP_ID_BOT, bot_printed[0]) == "unknown", \
        "the earlier bot token is dead at the hub"


def test_reading_the_identity_file_corrupt_and_mismatched_files(wired, command_uri, log_capture,
                                                                monkeypatch, tmp_path):
    identity_path = os.path.join(wired.folder, "cross_server", "identity.json")
    os.makedirs(os.path.dirname(identity_path), exist_ok=True)
    monkeypatch.setattr(games_ai, "_cross_server", None, raising=False)
    with open(identity_path, "w", encoding="utf-8") as handle:
        handle.write("{ not json")
    log_capture.clear()
    assert games_ai._load_identity(wired) is None, "a corrupt identity file reads as no identity"
    assert any(identity_path in str(record.getMessage()) for record in log_capture.records), \
        "and the file path is logged: {}".format([record.getMessage() for record in log_capture.records])
    assert games_ai._identity_token_for_link(wired, command_uri) == "", \
        "and no token is handed to the link"
    with open(identity_path, "w", encoding="utf-8") as handle:
        json.dump({"name": "creative", "token": "some-token", "hub": command_uri}, handle)
    assert games_ai._identity_token_for_link(wired, command_uri) == "", \
        "a token bound to another name is not used"
    with open(identity_path, "w", encoding="utf-8") as handle:
        json.dump({"name": "survival", "token": "some-token", "hub": "ws://elsewhere:9"}, handle)
    assert games_ai._identity_token_for_link(wired, command_uri) == "", \
        "a token from another hub is not used"
    with open(identity_path, "w", encoding="utf-8") as handle:
        json.dump({"name": "survival", "token": "some-token", "hub": command_uri}, handle)
    assert games_ai._identity_token_for_link(wired, command_uri) == "some-token", \
        "a matching identity is used"
    assert games_ai._identity_fingerprint() == token_fingerprint("some-token"), \
        f"the fingerprint helper hides the token: {games_ai._identity_fingerprint()}"

    custom_path = str(tmp_path / "elsewhere" / "my_identity.json")
    with monkeypatch.context() as patch:
        patch.setattr(plugin_config, "websocket_identity_file", custom_path)
        saved = games_ai._save_identity(wired, "survival", "another-token", command_uri)
        assert saved == custom_path and os.path.isfile(custom_path), \
            f"websocket.identity_file overrides the location: {saved}"
        assert games_ai._load_identity(wired)["token"] == "another-token", "the override is read back"
        assert games_ai._delete_identity(wired) == custom_path and not os.path.isfile(custom_path), \
            "forget deletes the overridden file"


def test_an_unenrolled_instance_stays_local_and_says_what_to_do(wired, command_hub, command_uri,
                                                                source, monkeypatch):
    unenrolled = CrossServerManager(command_uri, name="unlisted", token="", logger=LOG)
    try:
        assert unenrolled.start(timeout=10) == "local", \
            f"the hub is found but the instance stays local: {unenrolled.mode}"
        assert "not enrolled" in unenrolled.reason, \
            f"the reason says it is not enrolled: {unenrolled.reason}"
        assert "node claim" in unenrolled.reason, f"and points at node claim: {unenrolled.reason}"
        assert command_hub.is_pending("unlisted"), \
            f"the one enrolment request reached the hub: {command_hub.pending_requests}"
        assert not command_hub.is_enrolled("unlisted"), "no token was issued by itself"
        assert unenrolled.enrolled is False and unenrolled.enrol_requested is True, \
            f"the manager exposes the enrolment state: {(unenrolled.enrolled, unenrolled.enrol_requested)}"
    finally:
        unenrolled.stop()

    # §11: while there is no identity, every cluster feature has to say that this instance is not
    # enrolled -- "the link is unavailable" would hide the one thing the operator can act on.
    games_ai._delete_identity(wired)
    monkeypatch.setattr(games_ai, "_cross_server", None, raising=False)
    feature = source("Steve", permission=3, console=False)
    games_ai._forward_command(games_ai.ROUTE_SERVER, feature, "!!data read key1")
    assert "not enrolled" in plain_reply(feature) and "node claim" in plain_reply(feature), \
        f"a cluster feature says this instance is not enrolled: {plain_reply(feature)}"

    games_ai._save_identity(wired, "survival", "some-token", command_uri)
    linked = source("Steve", permission=3, console=False)
    games_ai._forward_command(games_ai.ROUTE_SERVER, linked, "!!data read key1")
    assert "unavailable" in plain_reply(linked), \
        f"with an identity but no link it stays the generic message: {plain_reply(linked)}"
    games_ai._delete_identity(wired)
