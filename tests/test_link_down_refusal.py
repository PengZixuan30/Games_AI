"""With the link down, a hub-class command must be refused instead of run locally.

docs/{zh_cn,en_us,zh_tw}/cross-server.md says it plainly in the troubleshooting table:

    |Commands do nothing and say the link is unavailable|This instance is a client whose link
    is currently down; wait for the reconnect or check the hub.|

The code used to run `ROUTE_SERVER` / `ROUTE_CLUSTER` commands locally in that state -- with
this instance's own database and API key, which is exactly the wrong state the operator
reported (an empty local database, the wrong OpenAI key). What must NOT change:

* a genuine standalone instance (no identity, link never established, local mode) keeps
  running these commands here;
* the hub itself keeps executing them locally, it is the executor;
* a command that arrived from another instance (`WebSocketCommandSource`) is never refused;
* `ROUTE_LOCAL` commands (help texts) never change.

The client below is a real hub + real node pair, so "client whose link is down" is the real
state and not a hand-made stub: the hub is stopped, the node keeps its client role and the
backoff loop, and only then is a command typed.
"""
import importlib.util
import logging
import os
import socket
import sys

import pytest
import yaml

from _helpers.paths import LANG_DIR, PKG
from _helpers.wait import wait_until


def load_instance(alias):
    """Load a private copy of the plugin: this suite needs three *separate* instances."""
    spec = importlib.util.spec_from_file_location(
        alias, os.path.join(PKG, "__init__.py"), submodule_search_locations=[PKG])
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


def plain(items):
    return "\n".join(item.to_plain_text() if hasattr(item, "to_plain_text") else str(item)
                     for item in items)


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def lines(self, level=None):
        return [(record.levelname, str(record.getMessage())) for record in self.records
                if level is None or record.levelname == level]


class BaseServer:
    """MCDR's base ``ServerInterface``: rtr/logger/say/execute_command, no data folder."""

    def __init__(self, name, lang):
        self.name = name
        self.logger = logging.getLogger("mcdr-" + name)
        self.lang = lang
        self.executed = []

    def rtr(self, translation_key, *args, **kwargs):
        node = self.lang
        for part in translation_key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if not isinstance(node, str):
            return translation_key
        try:
            return node.format(*args, **kwargs)
        except (IndexError, KeyError) as exc:
            return "<FORMAT ERROR {}: {}>".format(translation_key, exc)

    def say(self, message, **kwargs):
        return None

    def execute_command(self, raw, source=None):
        self.executed.append(raw)
        if source is not None:
            source.reply("[{} ran {}]".format(self.name, raw))


class PluginServer(BaseServer):
    def __init__(self, name, folder, lang):
        super().__init__(name, lang)
        self.folder = folder

    def get_data_folder(self):
        return self.folder


class Source:
    """A player/console source whose ``get_server()`` is the base interface, as in MCDR."""

    def __init__(self, base, who="Steve", permission=3, console=False, command="!!data read key1"):
        self.base = base
        self.player = None if console else who
        self.permission = permission
        self.console = console
        self.command = command
        self.received = []

    def get_server(self):
        return self.base

    def get_info(self):
        return type("Info", (), {"content": self.command})()

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

    def text(self):
        return plain(self.received)

    def __str__(self):
        return "console" if self.console else str(self.player)


class Instances:
    """The three loaded plugin copies this suite works with (see the ``instances`` fixture)."""

    def __init__(self, hub, client, standalone):
        self.hub = hub
        self.client = client
        self.standalone = standalone


class Pair:
    """One real hub instance (``A``) and one real client instance (``B``), plus their captures."""

    def __init__(self, A, B, lang, uri, hub_server, node_server, hub_log, node_log,
                 manager_a, manager_b, mode_a, mode_b):
        self.A = A
        self.B = B
        self.lang = lang
        self.uri = uri
        self.hub_server = hub_server
        self.node_server = node_server
        self.hub_log = hub_log
        self.node_log = node_log
        self.manager_a = manager_a
        self.manager_b = manager_b
        self.mode_a = mode_a
        self.mode_b = mode_b
        #: The one localized line a refused hub-class command is answered with.
        self.refusal = lang["games_ai"]["cross_server"]["link_down"]
        # Every routing decision below is about *where* the command goes; the actual hand-over is
        # spied on so no cluster traffic is needed to see it.
        self.forwarded = []
        self.fanned = []


class Standalone:
    """Instance ``S``: its module, its plugin server, its log capture and a base interface."""

    def __init__(self, module, plugin, capture, base):
        self.module = module
        self.plugin = plugin
        self.capture = capture
        self.base = base


@pytest.fixture(scope="module")
def langs():
    """The three language files, read once for the module (never at import time)."""
    return {name: yaml.safe_load(open(os.path.join(LANG_DIR, name + ".yml"),
                                      encoding="utf-8").read())
            for name in ("en_us", "zh_cn", "zh_tw")}


@pytest.fixture(scope="module")
def instances(tmp_path_factory):
    """Three separate plugin copies: the hub, the client and the standalone instance.

    Loading ``games_ai/__init__.py`` once per instance is what makes three real plugin
    instances in one process -- each with its own ``_cross_server``, ``plugin_config`` and
    logger. It is the expensive part of this suite, so it is shared for the whole module; the
    ``sys.modules`` entries are removed again on the way out.

    ``skills_path`` is moved out of the repository *for good* (not per test): the standalone
    sections start the real cross-server link, and with it the 24h update loop, which refreshes
    the context-window cache derived from ``skills_path`` on a background thread that can
    outlive the test that started it. A ``monkeypatch`` would be undone before that thread gets
    to write, and the cache would land in the checkout.
    """
    aliases = {"hub": "games_ai_down_hub",
               "client": "games_ai_down_client",
               "standalone": "games_ai_down_standalone"}
    loaded = Instances(**{role: load_instance(alias) for role, alias in aliases.items()})
    scratch = tmp_path_factory.mktemp("link-down")
    loaded.standalone.plugin_config.skills_path = str(scratch / "skills" / "skills.json")
    yield loaded
    for alias in aliases.values():
        for name in [name for name in sys.modules
                     if name == alias or name.startswith(alias + ".")]:
            sys.modules.pop(name, None)


def _capture(plugin):
    """Send everything this plugin server logs into a buffer the test can read."""
    capture = LogCapture()
    plugin.logger.addHandler(capture)
    plugin.logger.setLevel(logging.INFO)
    return capture


def _release(plugin, capture):
    plugin.logger.removeHandler(capture)
    shared = logging.getLogger("games_ai")
    if capture in shared.handlers:
        shared.removeHandler(capture)


def _boot_pair(instances, langs, tmp_path, port, monkeypatch):
    """Boot a real hub and a real client over one port and wait for both links.

    The three setup checks of the old section 0 are asserted here, with their own wording:
    every test that needs the pair shares this boot, so a link that never came up must fail
    loudly instead of turning into a confusing assertion further down.
    """
    A, B = instances.hub, instances.client
    en = langs["en_us"]
    uri = "ws://127.0.0.1:{}".format(port)
    hub_server = PluginServer("hub", str(tmp_path / "hub"), en)
    node_server = PluginServer("node-b", str(tmp_path / "node-b"), en)
    os.makedirs(hub_server.folder, exist_ok=True)
    os.makedirs(node_server.folder, exist_ok=True)
    hub_log = _capture(hub_server)
    node_log = _capture(node_server)

    monkeypatch.setattr(A, "_server_ref", hub_server, raising=False)
    A.logger.attach(hub_server)                    # on_load does this: the log target for this load
    manager_a = A.CrossServerManager(uri, name="host-a", handler=A._on_cross_message,
                                     logger=hub_server.logger)
    mode_a = manager_a.start(timeout=5)
    assert mode_a == A.MODE_SERVER, f"the hub started: {manager_a.reason}"
    monkeypatch.setattr(A, "_cross_server", manager_a, raising=False)

    monkeypatch.setattr(B, "_server_ref", node_server, raising=False)
    B.logger.attach(node_server)
    monkeypatch.setattr(B.plugin_config, "allow_permission", 3)
    monkeypatch.setattr(B.plugin_config, "cross_server_name", "host-b")
    monkeypatch.setattr(B.plugin_config, "websocket_uri", uri)
    b_token = manager_a.hub.issue("host-b")
    manager_b = B.CrossServerManager(uri, name="host-b", token=b_token,
                                     handler=B._on_cross_message, logger=node_server.logger)
    mode_b = manager_b.start(timeout=5)
    assert mode_b == B.MODE_CLIENT, f"the client connected: {manager_b.reason}"
    monkeypatch.setattr(B, "_cross_server", manager_b, raising=False)
    assert manager_b.connected, f"the client link is up: {manager_b.connected}"

    pair = Pair(A, B, en, uri, hub_server, node_server, hub_log, node_log,
                manager_a, manager_b, mode_a, mode_b)
    monkeypatch.setattr(B, "_forward_command",
                        lambda kind, source, raw: pair.forwarded.append((kind, raw)),
                        raising=False)
    monkeypatch.setattr(B, "_fan_out_cluster",
                        lambda source: pair.fanned.append(source), raising=False)
    return pair


@pytest.fixture
def live_link(instances, langs, tmp_path, free_port, monkeypatch):
    """A real hub and a real client with both links up (the old sections 0-2)."""
    pair = _boot_pair(instances, langs, tmp_path, free_port(), monkeypatch)
    yield pair
    pair.manager_b.stop()
    pair.manager_a.stop()
    _release(pair.hub_server, pair.hub_log)
    _release(pair.node_server, pair.node_log)


@pytest.fixture
def down_link(instances, langs, tmp_path, free_port, monkeypatch):
    """The same pair after the hub went away: a real client whose link is down (sections 3-6)."""
    pair = _boot_pair(instances, langs, tmp_path, free_port(), monkeypatch)
    pair.manager_a.stop()
    assert wait_until(lambda: not pair.manager_b.connected, 10), \
        f"the client keeps its role but loses the link: " \
        f"{(pair.manager_b.mode, pair.manager_b.connected)}"
    monkeypatch.setattr(instances.hub, "_cross_server", None, raising=False)
    yield pair
    pair.manager_b.stop()
    pair.manager_a.stop()
    _release(pair.hub_server, pair.hub_log)
    _release(pair.node_server, pair.node_log)


@pytest.fixture
def standalone(instances, langs, tmp_path, monkeypatch):
    """Instance ``S`` wired to its own plugin server, data folder and log capture."""
    module = instances.standalone
    plugin = PluginServer("standalone", str(tmp_path / "standalone"), langs["en_us"])
    os.makedirs(plugin.folder, exist_ok=True)
    capture = _capture(plugin)
    module.logger.attach(plugin)
    monkeypatch.setattr(module, "_server_ref", plugin, raising=False)
    monkeypatch.setattr(module.plugin_config, "allow_permission", 3)
    monkeypatch.setattr(module.plugin_config, "websocket_identity_file", "")
    monkeypatch.setattr(module, "_config_ref", {}, raising=False)
    monkeypatch.setattr(module, "_cross_server", None, raising=False)
    yield Standalone(module, plugin, capture, BaseServer("standalone-base", langs["en_us"]))
    _release(plugin, capture)


def test_a_real_hub_and_a_real_client_come_up(live_link):
    """Section 0: boot a real hub and a real client."""
    assert live_link.mode_a == live_link.A.MODE_SERVER, \
        f"the hub started: {live_link.manager_a.reason}"
    assert live_link.mode_b == live_link.B.MODE_CLIENT, \
        f"the client connected: {live_link.manager_b.reason}"
    assert live_link.manager_b.connected, f"the client link is up: {live_link.manager_b.connected}"


def test_the_hub_keeps_executing_hub_class_commands_locally(live_link):
    """Section 1: the hub keeps executing hub-class commands locally."""
    A, hub_log = live_link.A, live_link.hub_log
    hub_base = BaseServer("hub-base", live_link.lang)

    hub_log.records.clear()
    hub_ran = []
    A._route(A.ROUTE_SERVER, lambda src: hub_ran.append(src))(Source(hub_base))
    assert len(hub_ran) == 1, f"ROUTE_SERVER ran on the hub: {hub_ran}"
    assert not hub_log.lines("INFO"), f"nothing was refused on the hub: {hub_log.lines()}"
    assert not any(live_link.refusal in line for _, line in hub_log.lines()), \
        f"and no refusal text was logged: {hub_log.lines()}"

    hub_ran.clear()
    cluster_source = Source(hub_base, command="!!gamesai check")
    A._route(A.ROUTE_CLUSTER, lambda src: hub_ran.append(src))(cluster_source)
    assert len(hub_ran) == 1, f"ROUTE_CLUSTER ran on the hub: {hub_ran}"
    assert not [line for _, line in hub_log.lines("INFO") if "cross-server link" in line], \
        f"and was not refused there either: {hub_log.lines()}"


def test_a_client_with_a_live_link_still_forwards(live_link):
    """Section 2: a client with a live link still forwards (the control case)."""
    B = live_link.B
    b_base = BaseServer("node-b-base", live_link.lang)

    live_link.forwarded.clear()
    ran = []
    up_source = Source(b_base)
    B._route(B.ROUTE_SERVER, lambda src: ran.append(src))(up_source)
    assert live_link.forwarded == [(B.ROUTE_SERVER, "!!data read key1")], \
        f"the command was forwarded, not run here: {live_link.forwarded}"
    assert ran == [], f"the local handler did not run: {ran}"
    assert not up_source.received, f"the player was not told anything: {up_source.text()}"


def test_the_hub_going_away_leaves_the_client_a_client(down_link):
    """Section 3: the hub goes away -- still a client, link down."""
    assert not down_link.manager_b.connected, \
        f"the client keeps its role but loses the link: " \
        f"{(down_link.manager_b.mode, down_link.manager_b.connected)}"


def test_a_hub_class_command_typed_now_is_refused(down_link):
    """Section 4: a hub-class command typed now is refused, not run here."""
    B, node_log = down_link.B, down_link.node_log
    b_base = BaseServer("node-b-base", down_link.lang)

    node_log.records.clear()
    down_link.forwarded.clear()
    ran = []
    refused = Source(b_base)
    B._route(B.ROUTE_SERVER, lambda src: ran.append(src))(refused)
    assert ran == [], f"the local handler did NOT run: {ran}"
    assert len(refused.received) == 1, f"the player got exactly one reply: {refused.text()}"
    assert down_link.refusal in refused.text(), \
        f"the reply is the localized refusal: {refused.text()}"
    assert "!!gamesai node status" in refused.text(), \
        f"and it points at !!gamesai node status: {refused.text()}"
    info_lines = [line for _, line in node_log.lines("INFO")]
    assert len(info_lines) == 1, f"one INFO line still explains the state: {node_log.lines()}"
    assert bool(info_lines) and "cross-server link is down" in info_lines[0] \
        and "!!data read key1" in info_lines[0], \
        f"it names the down link and the command: {info_lines}"
    assert bool(info_lines) and "was not run" in info_lines[0] and "running" not in info_lines[0], \
        f"and it does not claim the command ran here: {info_lines}"

    node_log.records.clear()
    down_link.fanned.clear()
    ran.clear()
    cluster_source = Source(b_base, command="!!gamesai check")
    B._route(B.ROUTE_CLUSTER, lambda src: ran.append(src))(cluster_source)
    assert ran == [] and down_link.fanned == [], \
        f"a cluster command is refused too: {(ran, down_link.fanned)}"
    assert down_link.refusal in cluster_source.text(), \
        f"its refusal is the same localized line: {cluster_source.text()}"
    assert len([line for _, line in node_log.lines("INFO")]) == 1, \
        f"and it is still the one INFO line: {node_log.lines()}"


def test_commands_from_another_instance_are_never_refused(down_link):
    """Section 5: commands from another instance are never refused."""
    B, node_log, plugin = down_link.B, down_link.node_log, down_link.node_server

    node_log.records.clear()
    remote_ran = []
    remote_source = B.WebSocketCommandSource(plugin, origin="host-a", player="Steve",
                                             is_console=False, permission_level=3,
                                             sink=lambda text: None)
    B._route(B.ROUTE_SERVER, lambda src: remote_ran.append(src))(remote_source)
    assert len(remote_ran) == 1, f"the remote command ran here: {remote_ran}"
    assert not node_log.lines("INFO"), f"nothing was refused for it: {node_log.lines()}"


def test_help_texts_are_untouched(down_link):
    """Section 6: help texts (ROUTE_LOCAL) are untouched."""
    B, node_log = down_link.B, down_link.node_log
    b_base = BaseServer("node-b-base", down_link.lang)

    node_log.records.clear()
    help_ran = []
    help_source = Source(b_base, command="!!data")
    B._route(B.ROUTE_LOCAL, lambda src: help_ran.append(src))(help_source)
    assert len(help_ran) == 1, f"the help text ran locally: {help_ran}"
    assert not help_source.received, f"and was not answered with a refusal: {help_source.text()}"
    assert not node_log.lines("INFO"), f"and logged nothing: {node_log.lines()}"


def test_a_standalone_instance_still_runs_these_commands_locally(standalone):
    """Section 7: a standalone instance still runs these commands locally."""
    S = standalone.module

    s_ran = []
    standalone_source = Source(standalone.base)
    S._route(S.ROUTE_SERVER, lambda src: s_ran.append(src))(standalone_source)
    assert len(s_ran) == 1, f"the standalone instance ran it: {s_ran}"
    assert not standalone_source.received, f"no refusal was sent: {standalone_source.text()}"
    assert not standalone.capture.lines("INFO"), \
        f"and nothing was logged (local by design): {standalone.capture.lines()}"

    s_ran.clear()
    standalone_cluster = Source(standalone.base, command="!!gamesai check")
    S._route(S.ROUTE_CLUSTER, lambda src: s_ran.append(src))(standalone_cluster)
    assert len(s_ran) == 1, f"cluster commands run locally there too: {s_ran}"
    assert not standalone_cluster.received, f"still no refusal: {standalone_cluster.text()}"


def test_local_mode_with_a_loopback_hub_behaves_the_same(standalone, free_port, monkeypatch):
    """Section 8: local mode with a loopback hub behaves the same (no identity)."""
    S, plugin, capture = standalone.module, standalone.plugin, standalone.capture
    raw = socket.socket()
    raw.bind(("127.0.0.1", free_port()))
    raw.listen(5)
    monkeypatch.setattr(S.plugin_config, "websocket_uri",
                        "ws://127.0.0.1:{}".format(raw.getsockname()[1]))
    monkeypatch.setattr(S.plugin_config, "websocket_name", "standalone")
    monkeypatch.setattr(S.plugin_config, "cross_server_name", "standalone")
    monkeypatch.setattr(S.plugin_config, "websocket_identity_file", "")
    S._start_cross_server(plugin, {})
    try:
        assert wait_until(lambda: S.plugin_config.cross_server_mode != "pending", 20), \
            S.plugin_config.cross_server_mode
        assert S.plugin_config.cross_server_mode == "local" and S._cross_server.hub is not None, \
            f"the instance is local with a loopback hub: {S.plugin_config.cross_server_mode}"

        capture.records.clear()
        s_ran = []
        local_source = Source(standalone.base)
        S._route(S.ROUTE_SERVER, lambda src: s_ran.append(src))(local_source)
        assert len(s_ran) == 1, f"it still runs the command locally: {s_ran}"
        assert not local_source.received, f"with no refusal: {local_source.text()}"
        assert not capture.lines("INFO"), \
            f"and no diagnostic (never enrolled): {capture.lines()}"
    finally:
        S._stop_cross_server(plugin)
        raw.close()


def test_enrolled_but_local_keeps_running_locally(standalone, free_port, monkeypatch):
    """Section 9: enrolled but local (the documented boundary) keeps running locally + one line."""
    S, plugin, capture = standalone.module, standalone.plugin, standalone.capture
    raw = socket.socket()
    raw.bind(("127.0.0.1", free_port()))
    raw.listen(5)
    uri = "ws://127.0.0.1:{}".format(raw.getsockname()[1])
    monkeypatch.setattr(S.plugin_config, "websocket_uri", uri)
    monkeypatch.setattr(S.plugin_config, "websocket_identity_file", "")
    monkeypatch.setattr(S.plugin_config, "cross_server_name", "standalone")
    S._save_identity(plugin, "standalone", "some-token", uri)
    S._save_cross_server_role(plugin, S.MODE_LOCAL)
    S._start_cross_server(plugin, {})
    try:
        assert wait_until(lambda: S.plugin_config.cross_server_mode != "pending", 20), \
            S.plugin_config.cross_server_mode
        assert S.plugin_config.cross_server_mode == "local" \
            and S._cross_server.is_client is False, \
            f"an enrolled instance without a hub stays local: {S.plugin_config.cross_server_mode}"

        capture.records.clear()
        s_ran = []
        enrolled_local = Source(standalone.base)
        S._route(S.ROUTE_SERVER, lambda src: s_ran.append(src))(enrolled_local)
        assert len(s_ran) == 1, f"it runs the command locally (unchanged behaviour): {s_ran}"
        assert not enrolled_local.received, f"no refusal for a non-client: {enrolled_local.text()}"
        info_lines = [line for _, line in capture.lines("INFO")]
        assert len(info_lines) == 1, \
            f"the existing INFO diagnostic is still there: {capture.lines()}"
        assert bool(info_lines) and "cross-server role is local" in info_lines[0], \
            f"and it says the role is local: {info_lines}"
    finally:
        S._stop_cross_server(plugin)
        S._delete_identity(plugin)
        raw.close()


def test_the_refusal_is_localized_in_all_three_languages(langs):
    """Section 10: the refusal is localized in all three languages."""
    texts = {name: data["games_ai"]["cross_server"]["link_down"] for name, data in langs.items()}

    assert all(isinstance(text, str) and text.strip() for text in texts.values()), \
        f"the key exists in all three files: {texts}"
    assert len(set(texts.values())) == 3, f"the three lines are different translations: {texts}"
    assert all("!!gamesai node status" in text for text in texts.values()), \
        f"they all point at !!gamesai node status: {texts}"
    assert all(any("\u4e00" <= ch <= "\u9fff" for ch in texts[name])
               for name in ("zh_cn", "zh_tw")), f"the characters are the language's own: {texts}"
