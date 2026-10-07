"""`!!gamesai node status` must answer according to what the instance actually is.

The reported bug: run on the hub it printed "hub: <the hub's own name>" and then told the hub
to enrol itself ("run node token, then node claim"), which a hub never does. Three roles, three
reply sets -- and the command itself is unchanged.
"""
import json
import logging
import os
import re
import time

import pytest

import games_ai
from _helpers.paths import LANG_DIR
from _helpers.wait import wait_until
from games_ai.config import plugin_config
from games_ai.websockets_client import CrossServerNode, token_fingerprint
from games_ai.websockets_server import CrossServerHub

log = logging.getLogger("gamesai-status-test")


class FakeLogger:
    def __init__(self):
        self.records = []

    def _add(self, level, msg):
        self.records.append((level, str(msg)))

    def debug(self, msg, *a, **k):
        self._add("DEBUG", msg)

    def info(self, msg, *a, **k):
        self._add("INFO", msg)

    def warning(self, msg, *a, **k):
        self._add("WARNING", msg)

    def error(self, msg, *a, **k):
        self._add("ERROR", msg)

    def exception(self, msg, *a, **k):
        self._add("ERROR", msg)


class FakeServer:
    """A plugin interface stub: data folder, logger and the two text entry points."""

    def __init__(self, root):
        self.logger = FakeLogger()
        self._folder = os.path.join(root, "config", "games_ai")
        os.makedirs(self._folder, exist_ok=True)

    def get_data_folder(self):
        return self._folder

    def rtr(self, key, **kw):
        params = ",".join("{}={}".format(k, v) for k, v in sorted(kw.items()))
        return "[{} {}]".format(key.split(".")[-1], params)

    def write_identity(self, token="tok-abc123"):
        path = os.path.join(self._folder, "cross_server", "identity.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"name": "me", "token": token, "hub": "ws://hub:1",
                       "issued_at": int(time.time())}, handle)
        return token


class FakeManager:
    def __init__(self, mode="local", hub=None, is_server=False, is_client=False, name="me",
                 hub_name="", hub_uri=None, expires_in=None):
        self.mode = mode
        self.hub = hub
        self.is_server = is_server
        self.is_client = is_client
        self.name = name
        self.hub_name = hub_name
        self.hub_uri = hub_uri
        self.token_expires_in = expires_in


class FakeSource:
    def __init__(self, server, perm=4):
        self._server = server
        self._perm = perm
        self.replies = []

    def get_server(self):
        return self._server

    def get_permission_level(self):
        return self._perm

    @property
    def is_console(self):
        return True

    def reply(self, message, **kwargs):
        self.replies.append(str(message))


@pytest.fixture
def hub(free_port, tmp_path):
    """The hub the command reports on: two enrolled nodes, nobody online, never started."""
    hub = CrossServerHub("127.0.0.1", free_port(), name="hub-1", logger=log,
                         node_file=str(tmp_path / "nodes.json"))
    hub.issue("alpha", app="games_ai_mcdr")
    hub.issue("beta", app="games_ai_mcdr")
    yield hub
    hub.stop()


@pytest.fixture
def live_link(free_port, tmp_path):
    """A hub and one node, both really started: the only way ``peers`` can move."""
    live_hub = CrossServerHub("127.0.0.1", free_port(), name="hub-live", logger=log,
                              node_file=str(tmp_path / "live_nodes.json"))
    live_token = live_hub.issue("node-a", app="games_ai_mcdr")
    node_live = CrossServerNode("ws://127.0.0.1:{}".format(live_hub.port), "node-a", live_token,
                                logger=log)
    yield live_hub, node_live
    for handle in (node_live, live_hub):
        try:
            handle.stop()
        except Exception:
            pass


def run_status(monkeypatch, server, manager, perm=4):
    """Call the command with `_cross_server` replaced, and return the replies.

    ``_server_ref`` and the identity-file override are pinned to the state this module's old
    stand-alone process had: the plugin instance behind the command is the fake server handed in
    here, and nothing another suite left on the shared config may redirect it.
    """
    monkeypatch.setattr(games_ai, "_cross_server", manager, raising=False)
    monkeypatch.setattr(games_ai, "_server_ref", None, raising=False)
    monkeypatch.setattr(plugin_config, "websocket_identity_file", "")
    monkeypatch.setattr(plugin_config, "allow_permission", 3)
    source = FakeSource(server, perm=perm)
    games_ai._node_status(source)
    return source.replies


def reply_with(replies, key):
    """Lines rendered by that exact key (the fake renders ``[<key> <params>]``)."""
    needle = "[{}".format(key)
    return [line for line in replies if needle in line]


def test_the_hub_reports_itself_and_never_enrols(monkeypatch, hub, tmp_path):
    """Section 1: on the hub."""
    hub_server = FakeServer(str(tmp_path / "hub"))
    hub_manager = FakeManager(mode="server", hub=hub, is_server=True, name="wanghai-5798d3",
                              hub_uri="ws://0.0.0.0:8765")
    replies = run_status(monkeypatch, hub_server, hub_manager)

    assert len(replies) == 2, f"the hub gets its own two lines: {replies}"
    assert "hub_status_line" in replies[0], f"the hub line is the hub one: {replies}"
    assert "name=wanghai-5798d3" in replies[0] and "hub=" not in replies[0], \
        f"...and names this instance, not a hub it dialled: {replies[0]}"
    assert "uri=ws://0.0.0.0:8765" in replies[0], f"...with the address it listens on: {replies[0]}"
    assert "nodes=2" in replies[0], f"...and how many nodes are enrolled: {replies[0]}"
    assert "peers=0" in replies[0], f"...and how many are online: {replies[0]}"
    assert "hub_hint" in replies[1], f"the second line is the hub hint: {replies}"
    assert not any("node claim" in line or "not_enrolled_hint" in line for line in replies), \
        f"the hub is never told to enrol itself: {replies}"
    assert not reply_with(replies, "status_line"), \
        f"the client status line is not used on the hub: {replies}"


def test_an_identity_file_does_not_turn_the_hub_into_a_node(monkeypatch, hub, tmp_path):
    hub_server = FakeServer(str(tmp_path / "hub"))
    hub_server.write_identity()
    hub_manager = FakeManager(mode="server", hub=hub, is_server=True, name="wanghai-5798d3",
                              hub_uri="ws://0.0.0.0:8765")

    replies = run_status(monkeypatch, hub_server, hub_manager)

    assert "hub_status_line" in replies[0] and len(replies) == 2, \
        f"an identity file does not turn the hub into a node: {replies}"


def test_the_online_count_follows_the_live_link(monkeypatch, live_link, tmp_path):
    live_hub, node_live = live_link

    assert live_hub.start(timeout=5), f"the hub starts: {live_hub.is_running}"
    assert node_live.start(timeout=5), f"a node connects: {node_live.connected}"
    assert wait_until(lambda: len(live_hub.peers) >= 1, 5), live_hub.peers

    hub_server = FakeServer(str(tmp_path / "hub"))
    live_manager = FakeManager(mode="server", hub=live_hub, is_server=True, name="hub-live",
                               hub_uri="ws://127.0.0.1:{}".format(live_hub.port))
    replies = run_status(monkeypatch, hub_server, live_manager)

    assert "peers=1" in replies[0], f"the online count follows the live link: {replies[0]}"
    assert "hub_status_line" in replies[0], f"...and the hub line still leads: {replies}"


def test_an_enrolled_client_reports_the_hub_and_its_token(monkeypatch, tmp_path):
    """Section 2: on a client."""
    client_server = FakeServer(str(tmp_path / "client"))
    client_manager = FakeManager(mode="client", is_client=True, hub_name="hub-1",
                                 expires_in=3600)
    token = client_server.write_identity()

    replies = run_status(monkeypatch, client_server, client_manager)

    assert len(replies) == 1, f"an enrolled client gets one line: {replies}"
    assert "status_line" in replies[0], f"the client line is the client one: {replies}"
    assert "hub=hub-1" in replies[0], f"...naming the hub it dialled: {replies[0]}"
    assert "state_yes" in replies[0], f"...and reporting it as enrolled: {replies[0]}"
    assert token_fingerprint(token) in replies[0], \
        f"...with the token fingerprint: {replies[0]}"
    assert "expires=" in replies[0] and "unknown" not in replies[0].split("expires=")[1], \
        f"...and the time the hub reported: {replies[0]}"


def test_a_client_without_a_token_gets_the_enrolment_hint(monkeypatch, tmp_path):
    client_server = FakeServer(str(tmp_path / "client"))
    client_manager = FakeManager(mode="client", is_client=True, hub_name="hub-1",
                                 expires_in=3600)

    replies = run_status(monkeypatch, client_server, client_manager)

    assert len(replies) == 2 and "not_enrolled_hint" in replies[1], \
        f"a client without a token gets the enrolment hint: {replies}"
    assert "state_no" in replies[0], f"...and says it is not enrolled: {replies[0]}"


def test_an_unlimited_token_is_reported_as_such(monkeypatch, tmp_path):
    client_server = FakeServer(str(tmp_path / "client"))
    client_server.write_identity()
    unlimited = FakeManager(mode="client", is_client=True, hub_name="hub-1", expires_in=None)

    replies = run_status(monkeypatch, client_server, unlimited)

    assert "unlimited" in replies[0], f"an unlimited token is reported as such: {replies[0]}"


def test_without_a_hub_name_the_configured_uri_is_shown(monkeypatch, tmp_path):
    client_server = FakeServer(str(tmp_path / "client"))
    client_server.write_identity()
    fallback = FakeManager(mode="client", is_client=True, hub_name="", expires_in=5)

    replies = run_status(monkeypatch, client_server, fallback)

    assert "hub={}".format(plugin_config.websocket_uri) in replies[0], \
        f"without a hub name the configured uri is shown: {replies[0]}"


def test_local_mode_gets_its_own_line(monkeypatch, free_port, tmp_path):
    """Section 3: in local mode."""
    local_server = FakeServer(str(tmp_path / "local"))
    loopback = CrossServerHub("127.0.0.1", free_port(), name="local", logger=log,
                              node_file=str(tmp_path / "loop_nodes.json"))
    local_manager = FakeManager(mode="local", hub=loopback, is_server=False, is_client=False,
                                name="local-1", hub_uri="ws://127.0.0.1:1")

    replies = run_status(monkeypatch, local_server, local_manager)

    assert "local_status_line" in replies[0], f"local mode gets its own line: {replies}"
    assert "hub=" not in replies[0], f"...without a hub field: {replies[0]}"
    assert "state_no" in replies[0], f"...and says it is not enrolled: {replies[0]}"
    assert "local_hint" in replies[1], f"...plus a hint about the missing link: {replies}"
    assert not reply_with(replies, "hub_status_line"), \
        f"the loopback hub for the bot does not make it a hub: {replies}"
    assert not reply_with(replies, "status_line"), \
        f"a local instance is not told it is a client: {replies}"


def test_an_enrolled_local_instance_is_reported_as_enrolled(monkeypatch, free_port, tmp_path):
    local_server = FakeServer(str(tmp_path / "local"))
    loopback = CrossServerHub("127.0.0.1", free_port(), name="local", logger=log,
                              node_file=str(tmp_path / "loop_nodes.json"))
    local_manager = FakeManager(mode="local", hub=loopback, is_server=False, is_client=False,
                                name="local-1", hub_uri="ws://127.0.0.1:1")
    token = local_server.write_identity()

    replies = run_status(monkeypatch, local_server, local_manager)

    assert "state_yes" in replies[0], \
        f"an enrolled local instance is reported as enrolled: {replies[0]}"
    assert token_fingerprint(token) in replies[0], f"...with its fingerprint: {replies[0]}"
    assert "local_enrolled_hint" in replies[1] and "not_enrolled_hint" not in replies[1], \
        f"...and is not asked to claim a token again: {replies}"


def test_no_manager_at_all_is_local_too(monkeypatch, tmp_path):
    local_server = FakeServer(str(tmp_path / "local"))

    replies = run_status(monkeypatch, local_server, None)

    assert "local_status_line" in replies[0], f"no manager at all is local too: {replies}"
    assert bool(reply_with(replies, "local_hint")) and not reply_with(replies, "local_enrolled_hint"), \
        f"...and still answers with the local hint: {replies}"
    assert not reply_with(replies, "hub_status_line"), "...and never with the hub line"


def test_below_the_permission_level_nothing_is_reported(monkeypatch, hub, tmp_path):
    """Section 4: permissions."""
    hub_server = FakeServer(str(tmp_path / "hub"))
    hub_manager = FakeManager(mode="server", hub=hub, is_server=True, name="wanghai-5798d3",
                              hub_uri="ws://0.0.0.0:8765")

    replies = run_status(monkeypatch, hub_server, hub_manager, perm=1)

    assert len(replies) == 1 and "no_permission" in replies[0], \
        f"below the permission level nothing is reported: {replies}"
    assert not reply_with(replies, "status_line"), f"...and no role line leaks: {replies}"


@pytest.mark.parametrize("lang", ["en_us", "zh_cn", "zh_tw"])
def test_the_language_file_is_still_crlf_only(lang):
    """Section 5: the three languages."""
    raw = open(os.path.join(LANG_DIR, lang + ".yml"), "rb").read()

    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""), \
        f"{lang}: still CRLF only"


def test_the_three_languages_share_the_new_keys():
    texts, values, counts = {}, {}, {}
    new_keys = ("hub_status_line", "hub_hint", "local_status_line", "local_hint",
                "local_enrolled_hint")
    for lang in ("en_us", "zh_cn", "zh_tw"):
        path = os.path.join(LANG_DIR, lang + ".yml")
        raw = open(path, "rb").read()
        texts[lang] = raw.decode("utf-8")
        counts[lang] = len(re.findall(r"^\s+[A-Za-z0-9_]+:", texts[lang], re.M))
        for key in new_keys:
            found = re.search(r'{}: "(.*)"'.format(key), texts[lang])
            values[(lang, key)] = found.group(1) if found else ""

    assert all(values[(lang, key)] for lang in texts for key in new_keys), \
        f"every language has all five keys: {[k for k, v in values.items() if not v]}"
    assert len(set(counts.values())) == 1, f"the key sets still match: {counts}"
    assert all(all(token in values[(lang, "hub_status_line")]
                   for token in ("{name}", "{uri}", "{nodes}", "{peers}"))
               for lang in texts), "the hub line names the numbers it shows"
    assert all("node claim" not in values[(lang, "hub_hint")] for lang in texts), \
        "the hub hint never asks the hub to claim"
    assert all("node claim" in values[(lang, "local_hint")] for lang in texts), \
        "the local hint explains how to join"
    assert all("reload" in values[(lang, "local_enrolled_hint")] for lang in texts), \
        "the local enrolled hint points at a reload"
    assert all(any("\u4e00" <= ch <= "\u9fff" for ch in values[(lang, key)])
               for lang in ("zh_cn", "zh_tw") for key in new_keys), "the CJK texts are CJK"
    assert all("{hub}" not in values[(lang, "local_status_line")] for lang in texts), \
        "the local line has no hub placeholder"
