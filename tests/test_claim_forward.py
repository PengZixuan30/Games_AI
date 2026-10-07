"""Runtime enrolment: after a successful claim the instance must forward, not run locally.

The bug this suite pins down lives in the difference between two MCDR interfaces:

* ``on_load`` receives a :class:`PluginServerInterface`, the only object with
  ``get_data_folder()``;
* every command source hands back the **base** ``ServerInterface``
  (``PlayerCommandSource.get_server()`` / ``ConsoleCommandSource.get_server()`` return
  ``mcdr_server.basic_server_interface``), which has no such method.

``!!gamesai node claim`` used the latter to write the identity file, so ``get_data_folder()``
raised, the plugin swallowed it and wrote nothing -- while still answering "Enrolled as ...".
The restarted link then had no token, re-sent an enrolment request, got 4007 and settled on
local mode *with a loopback hub*, whose liveness hid the failure: ``is_client`` stayed False,
``_should_forward`` returned False for every command, and each one ran on that instance (the
operator's `!!ask` used the wrong local API key; the hub never saw the command).

This suite therefore always speaks to the plugin through a command source whose ``get_server()``
is the base interface, exactly like MCDR does.
"""
import importlib.util
import json
import logging
import os
import socket
import sys
import time
from types import SimpleNamespace

import pytest
import yaml

from _helpers.paths import LANG_DIR, PKG
from _helpers.wait import wait_until
from mcdreforged.api.all import RText
from mcdreforged.command.builder.callback import DirectCallbackInvoker, ScheduledCallback


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def lines(self, level=None):
        return [(record.levelname, str(record.getMessage())) for record in self.records
                if level is None or record.levelname == level]

    def text(self):
        return "\n".join(str(record.getMessage()) for record in self.records)


class BaseServer:
    """MCDR's ``ServerInterface``: rtr/logger/say/execute_command -- and no data folder."""

    def __init__(self, name, lang):
        self.name = name
        self.lang = lang
        self.logger = logging.getLogger("mcdr-" + name)
        self.executed = []
        self.answer = "hub answer"

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

    def get_permission_level(self, player):
        return 4

    def say(self, message, **kwargs):
        return None

    def register_command(self, node):
        return None

    def register_help_message(self, **kwargs):
        return None

    def execute_command(self, raw, source=None):
        self.executed.append(raw)
        if source is not None:
            source.reply(RText("{} ran {}".format(self.answer, raw)))


class PluginServer(BaseServer):
    """What ``on_load`` receives: the same, plus this plugin's own data folder."""

    def __init__(self, name, folder, lang):
        super().__init__(name, lang)
        self.folder = folder

    def get_data_folder(self):
        return self.folder


class Source:
    """A player/console source; ``get_server()`` is the base interface, as in MCDR."""

    def __init__(self, base, who="Steve", permission=4, console=False, command="!!data read key1"):
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
        return "\n".join(str(item) for item in self.received)

    def __str__(self):
        return "console" if self.console else str(self.player)


class Ctx(dict):
    """Stands in for MCDR's CommandContext (context.get(key))."""


class Capture:
    def __init__(self):
        self.roots = []

    def register_command(self, node):
        self.roots.append(node)

    def register_help_message(self, **kwargs):
        return None


def registered_callbacks(server_tree):
    """The registered subcommands of the built tree, keyed by their literal."""
    found = {}
    for root in server_tree.roots:
        for literal in getattr(root, "literals", set()):
            found[literal] = root
    return found


def invoke(callback, source, context):
    ScheduledCallback(callback, (source, context), lambda e: e).invoke(DirectCallbackInvoker())


def load_instance(alias):
    """Load the plugin package again under its own namespace of globals."""
    spec = importlib.util.spec_from_file_location(
        alias, os.path.join(PKG, "__init__.py"), submodule_search_locations=[PKG])
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


def unload_instance(alias):
    """Forget an instance and every submodule it registered, so nothing leaks into a later test."""
    for name in [name for name in sys.modules
                 if name == alias or name.startswith(alias + ".")]:
        del sys.modules[name]


def wait_for_quiet_log(capture, timeout=5.0):
    """Wait until a log capture goes one sampling window (0.2s) without a new record."""
    def quiet():
        before = len(capture.records)
        time.sleep(0.2)
        return len(capture.records) == before

    return wait_until(quiet, timeout=timeout, interval=0.0)


@pytest.fixture(scope="module")
def lang():
    """The plugin's English strings, the way MCDR hands them to ``rtr()``."""
    with open(os.path.join(LANG_DIR, "en_us.yml"), encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@pytest.fixture(scope="module")
def instances():
    """Three copies of the plugin: the hub, the node and a standalone instance.

    A full package import is the expensive part of this module, and every test builds its own
    links and fake servers around these copies, so one set serves the whole module.
    """
    yield SimpleNamespace(a=load_instance("games_ai_claim_hub"),
                          b=load_instance("games_ai_claim_node"),
                          c=load_instance("games_ai_claim_local"))
    for alias in ("games_ai_claim_hub", "games_ai_claim_node", "games_ai_claim_local"):
        unload_instance(alias)


@pytest.fixture
def log_capture():
    """``attach(logger)`` returns a capture that is removed from the logger afterwards."""
    attached = []

    def attach(server_logger):
        capture = LogCapture()
        server_logger.addHandler(capture)
        server_logger.setLevel(logging.DEBUG)
        attached.append((server_logger, capture))
        return capture

    yield attach
    for server_logger, capture in attached:
        server_logger.removeHandler(capture)


@pytest.fixture
def hub(instances, monkeypatch, tmp_path, free_port, lang):
    """Instance A as a running hub, with a data folder of its own and a fake MCDR interface."""
    a = instances.a
    folder = tmp_path / "hub"
    folder.mkdir()
    manager = None
    try:
        monkeypatch.setattr(a, "_server_ref", PluginServer("hub", str(folder), lang),
                            raising=False)
        monkeypatch.setattr(a, "prefix", "[GamesAI]", raising=False)
        monkeypatch.setattr(a, "allow_permission", 3, raising=False)
        monkeypatch.setattr(a.plugin_config, "allow_permission", 3, raising=False)
        monkeypatch.setattr(a, "_cross_server", None, raising=False)

        uri = "ws://127.0.0.1:{}".format(free_port())
        manager = a.CrossServerManager(uri, name="host-a", handler=a._on_cross_message,
                                       logger=logging.getLogger("test"))
        assert manager.start(timeout=5) == a.MODE_SERVER, f"the hub started: {manager.reason}"
        monkeypatch.setattr(a, "_cross_server", manager, raising=False)
        yield SimpleNamespace(instance=a, manager=manager, plugin=a._server_ref,
                              base=BaseServer("hub-base", lang), uri=uri, folder=str(folder),
                              lang=lang)
    finally:
        if manager is not None:
            manager.stop()


def hub_issued_token(hub, name="host-b"):
    """The token ``!!gamesai node token <name>`` printed, and the console source that saw it."""
    admin = Source(hub.base, who="console", console=True)
    hub.instance._node_token(admin, Ctx(name=name))
    printed = [chunk for chunk in admin.text().split() if len(chunk) == 43]
    return SimpleNamespace(printed=printed, token=printed[0] if printed else "", admin=admin)


@pytest.fixture
def token(hub):
    """A real token from the hub's own token table, as ``!!gamesai node token`` would hand out."""
    return hub.manager.hub.issue("host-b")


@pytest.fixture
def node(hub, instances, monkeypatch, tmp_path, lang):
    """Instance B configured to enrol at the hub, with a data folder of its own.

    Stopped after the test: whatever link it built is torn down whether the test passed or not.
    """
    b = instances.b
    folder = tmp_path / "node"
    folder.mkdir()
    plugin = PluginServer("node", str(folder), lang)
    monkeypatch.setattr(b, "_server_ref", plugin, raising=False)
    monkeypatch.setattr(b, "prefix", "[GamesAI]", raising=False)
    monkeypatch.setattr(b, "allow_permission", 3, raising=False)
    monkeypatch.setattr(b.plugin_config, "allow_permission", 3, raising=False)
    monkeypatch.setattr(b.plugin_config, "websocket_uri", hub.uri, raising=False)
    monkeypatch.setattr(b.plugin_config, "websocket_name", "host-b", raising=False)
    monkeypatch.setattr(b.plugin_config, "cross_server_name", "host-b", raising=False)
    monkeypatch.setattr(b.plugin_config, "websocket_force_server", False, raising=False)
    monkeypatch.setattr(b.plugin_config, "websocket_identity_file", "", raising=False)
    monkeypatch.setattr(b.plugin_config, "websocket_auto_enroll", True, raising=False)
    monkeypatch.setattr(b.plugin_config, "websocket_token_ttl_hours", -1, raising=False)
    monkeypatch.setattr(b, "_config_ref", {}, raising=False)
    monkeypatch.setattr(b, "_cross_server", None, raising=False)

    data_path = os.path.join(str(folder), "database", "public_database.db")
    monkeypatch.setattr(b, "data_path", data_path, raising=False)
    os.makedirs(os.path.dirname(data_path), exist_ok=True)
    b.database.PublicDatabase(data_path).write_data("key1", "LOCAL-ONLY-VALUE")

    yield SimpleNamespace(instance=b, plugin=plugin, base=BaseServer("node-base", lang),
                          folder=str(folder),
                          identity_path=os.path.join(str(folder), "cross_server",
                                                     "identity.json"))
    b._stop_cross_server(plugin)


@pytest.fixture
def local_node(node):
    """The node after a load that found the hub but holds no token: local, enrolment requested."""
    b = node.instance
    b._start_cross_server(node.plugin, {})

    assert wait_until(lambda: b.plugin_config.cross_server_mode != "pending", timeout=20), \
        f"waiting for the node to settle out of pending: {b.plugin_config.cross_server_mode}"
    return node


@pytest.fixture
def issued(local_node, hub):
    """The hub's answer to ``!!gamesai node token host-b``, while the node is waiting for it."""
    return hub_issued_token(hub)


@pytest.fixture
def enrolled(local_node, hub, issued):
    """The node after the operator claimed its token: a live client of the hub."""
    b = local_node.instance
    console = Source(local_node.base, who="console", console=True, command="!!gamesai node claim x")
    b._node_claim(console, Ctx(token=issued.token))

    assert wait_until(lambda: b._cross_server is not None and b._cross_server.is_client
                      and b._cross_server.connected, timeout=15), \
        f"waiting for the claimed node to become a client: {b.plugin_config.cross_server_mode}"
    manager_b = b._cross_server
    assert manager_b is not None and manager_b.is_client and manager_b.connected, \
        f"the instance is a client after the claim: {b.plugin_config.cross_server_mode}"
    assert "host-b" in hub.manager.peers, f"the hub lists the claimed node: {hub.manager.peers}"
    return SimpleNamespace(instance=b, plugin=local_node.plugin, base=local_node.base,
                           manager=manager_b, console=console, token=issued.token,
                           issued=issued, identity_path=local_node.identity_path,
                           folder=local_node.folder)


@pytest.fixture
def local_instance(hub, instances, monkeypatch, tmp_path, lang):
    """Instance C: configured like a node, but it has never enrolled anywhere."""
    c = instances.c
    folder = tmp_path / "local-only"
    folder.mkdir()
    plugin = PluginServer("local-only", str(folder), lang)
    monkeypatch.setattr(c, "_server_ref", plugin, raising=False)
    monkeypatch.setattr(c, "prefix", "[GamesAI]", raising=False)
    monkeypatch.setattr(c, "allow_permission", 3, raising=False)
    monkeypatch.setattr(c.plugin_config, "allow_permission", 3, raising=False)
    monkeypatch.setattr(c.plugin_config, "websocket_name", "host-c", raising=False)
    monkeypatch.setattr(c.plugin_config, "cross_server_name", "host-c", raising=False)
    monkeypatch.setattr(c.plugin_config, "websocket_force_server", False, raising=False)
    monkeypatch.setattr(c.plugin_config, "websocket_identity_file", "", raising=False)
    monkeypatch.setattr(c.plugin_config, "websocket_auto_enroll", False, raising=False)
    monkeypatch.setattr(c, "_config_ref", {}, raising=False)
    monkeypatch.setattr(c, "_cross_server", None, raising=False)
    yield SimpleNamespace(instance=c, plugin=plugin, base=BaseServer("local-base", lang),
                          folder=str(folder),
                          identity_path=os.path.join(str(folder), "cross_server",
                                                     "identity.json"))
    c._stop_cross_server(plugin)


@pytest.fixture
def foreign_port(free_port):
    """A raw listener that is not a GamesAI hub, closed however the test ends."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", free_port()))
    listener.listen(5)
    try:
        yield listener.getsockname()[1]
    finally:
        listener.close()


def test_the_node_stays_local_before_it_is_enrolled(local_node, hub):
    b = local_node.instance

    assert b.plugin_config.cross_server_mode == "local", \
        f"the instance is local before it is enrolled: {b.plugin_config.cross_server_mode}"
    assert "host-b" in hub.manager.hub.pending_requests, \
        f"the hub recorded the enrolment request: {hub.manager.hub.pending_requests}"


def test_the_operator_claims_a_token(enrolled, hub):
    identity_path = enrolled.identity_path

    assert len(enrolled.issued.printed) == 1, \
        f"the hub issued one token: {enrolled.issued.admin.text()}"
    assert "Enrolled as host-b" in enrolled.console.text(), \
        f"the claim is accepted: {enrolled.console.text()}"
    assert os.path.isfile(identity_path), \
        ("the identity file really was written: "
         f"{enrolled.console.text()} | {os.listdir(enrolled.folder)}")
    assert identity_path in enrolled.console.text(), \
        f"the reply names the file it wrote: {enrolled.console.text()}"
    try:
        with open(identity_path, encoding="utf-8") as handle:
            identity = json.load(handle)
    except (OSError, ValueError):
        identity = {}
    assert identity.get("token") == enrolled.token, f"it carries this node's token: {identity}"
    assert identity.get("hub") == hub.uri, f"it records the hub it was issued for: {identity}"
    assert enrolled.manager is not None and enrolled.manager.is_client, \
        f"the instance is a client after the claim: {enrolled.instance.plugin_config.cross_server_mode}"
    assert enrolled.manager is not None and enrolled.manager.connected, \
        f"its link to the hub is live: {getattr(enrolled.manager, 'reason', None)}"
    assert enrolled.manager is not None and enrolled.manager.node is not None \
        and enrolled.manager.hub is None, \
        ("the live link is the node, not the local loopback hub: "
         f"{(getattr(enrolled.manager, 'node', None) is not None, getattr(enrolled.manager, 'hub', None) is not None)}")
    assert "host-b" in hub.manager.peers, f"the hub lists the claimed node: {hub.manager.peers}"


def test_data_read_runs_on_the_hub(enrolled, hub):
    b = enrolled.instance
    capture = Capture()
    b.register_commands(capture, {})
    tree = registered_callbacks(capture)

    assert "!!data" in tree and "!!ask" in tree, \
        f"the node registered !!data and !!ask: {sorted(tree)}"
    data_read = None
    for child in tree["!!data"].get_children():
        if "read" in getattr(child, "literals", set()):
            data_read = child.get_children()[0]
    assert data_read is not None, "the real !!data read callback was found"

    before = len(hub.plugin.executed)
    player = Source(enrolled.base, command="!!data read key1")
    invoke(data_read._callback, player, Ctx(key="key1"))

    assert wait_until(lambda: len(hub.plugin.executed) > before, timeout=5), \
        f"waiting for the hub to run the forwarded command: {hub.plugin.executed[before:]}"
    assert hub.plugin.executed[before:] == ["!!data read key1"], \
        f"the hub executed the forwarded command: {hub.plugin.executed[before:]}"
    assert "LOCAL-ONLY-VALUE" not in player.text(), \
        f"the local handler did not run here: {player.text()}"
    assert "hub answer" in player.text(), f"the player saw the hub's answer: {player.text()}"


def test_ask_is_forwarded_too(enrolled, hub, monkeypatch):
    b = enrolled.instance
    # A minimal AI configuration plus a provider stub: if `!!ask` ever ran here (the bug), it
    # fails fast and visibly instead of reaching the network, and the checks below report it.
    monkeypatch.setattr(b, "default_ai", "claim-test-model", raising=False)
    ai_dict = {"claim-test-model": {"ai_name": "[AI] ", "ai_model": "gpt-test",
                                    "base_url": "https://api.example.invalid/v1",
                                    "api_key": "sk-test", "prompt": "test", "extra_body": {}}}
    monkeypatch.setattr(b, "ai_dict", ai_dict, raising=False)
    monkeypatch.setattr(b.plugin_config, "all_ai", ai_dict, raising=False)

    def no_provider(*args, **kwargs):
        raise RuntimeError("this test has no AI provider")

    monkeypatch.setattr(b.chat_param, "response_chat", no_provider)

    capture = Capture()
    b.register_commands(capture, {})
    ask_callback = None
    for root in capture.roots:
        if "!!ask" in getattr(root, "literals", set()):
            for child in root.get_children():
                ask_callback = child._callback
    assert ask_callback is not None, "the real !!ask callback was found"

    before = len(hub.plugin.executed)
    b.all_chat_param.clear()
    asker = Source(enrolled.base, command="!!ask hi")
    invoke(ask_callback, asker, Ctx(content="hi"))

    assert wait_until(lambda: len(hub.plugin.executed) > before, timeout=5), \
        f"waiting for the hub to run the forwarded !!ask: {hub.plugin.executed[before:]}"
    assert hub.plugin.executed[before:] == ["!!ask hi"], \
        f"the hub executed the forwarded !!ask: {hub.plugin.executed[before:]}"
    assert b.all_chat_param == {}, \
        f"no conversation was created on this instance: {list(b.all_chat_param)}"


def test_node_status_reads_the_identity_through_the_base_source(enrolled):
    b = enrolled.instance
    status = Source(enrolled.base, who="console", console=True, command="!!gamesai node status")
    b._node_status(status)

    assert "role: client" in status.text(), f"status reports the client role: {status.text()}"
    assert "enrolled: yes" in status.text(), \
        f"status reports this instance as enrolled: {status.text()}"
    assert b.token_fingerprint(enrolled.token) in status.text(), \
        f"status shows the token fingerprint: {status.text()}"


def test_a_claim_that_cannot_work_leaves_the_instance_local(hub, token, local_instance,
                                                            monkeypatch, free_port):
    c = local_instance.instance
    local_identity = local_instance.identity_path
    monkeypatch.setattr(c.plugin_config, "websocket_uri",
                        "ws://127.0.0.1:{}".format(free_port()), raising=False)
    unreachable = Source(local_instance.base, who="console", console=True)
    c._node_claim(unreachable, Ctx(token=token))

    assert "did not answer" in unreachable.text(), \
        f"an unreachable hub refuses the claim: {unreachable.text()}"
    assert not os.path.isfile(local_identity), \
        f"and nothing was written: {os.listdir(local_instance.folder)}"

    monkeypatch.setattr(c.plugin_config, "websocket_uri", hub.uri, raising=False)
    rejected = Source(local_instance.base, who="console", console=True)
    c._node_claim(rejected, Ctx(token="not-a-real-token"))

    assert "does not know this token" in rejected.text(), \
        f"a token the hub does not know is refused: {rejected.text()}"
    c._node_claim(rejected, Ctx(token=""))
    assert "Usage: !!gamesai node claim" in rejected.text(), \
        f"an empty token only prints the usage: {rejected.text()}"
    assert not os.path.isfile(local_identity), \
        f"still nothing was written: {os.listdir(local_instance.folder)}"


def test_an_enrolled_instance_without_its_hub_says_why(local_instance, token, foreign_port,
                                                       log_capture, monkeypatch):
    c = local_instance.instance
    local_identity = local_instance.identity_path
    local_log = log_capture(local_instance.plugin.logger)
    # The identity came from an enrolment; the address it was issued for is now owned by
    # something that is not a GamesAI hub any more (a raw listener, like a service that took the
    # port over).
    uri = "ws://127.0.0.1:{}".format(foreign_port)
    monkeypatch.setattr(c.plugin_config, "websocket_uri", uri, raising=False)
    c._save_identity(local_instance.plugin, "host-c", token, uri)
    c._start_cross_server(local_instance.plugin, {})

    assert wait_until(lambda: c.plugin_config.cross_server_mode != "pending", timeout=25), \
        f"waiting for the role to settle: {c.plugin_config.cross_server_mode}"
    assert c.plugin_config.cross_server_mode == "local", \
        ("the instance stays local without its hub: "
         f"{(c.plugin_config.cross_server_mode, getattr(c._cross_server, 'reason', None))}")
    assert os.path.isfile(local_identity), \
        f"but its identity is still there: {os.listdir(local_instance.folder)}"

    # The role is settled, but the node side can still log one more line about the dead hub from
    # its own thread (a retry notice). Wait for the capture to go quiet first: the window below
    # is about the *command* path, and a background line inside it made this suite flaky under
    # load.
    wait_for_quiet_log(local_log, timeout=5.0)
    local_log.records.clear()
    spy = []
    routed = c._route(c.ROUTE_SERVER, lambda src: spy.append(src))
    user = Source(local_instance.base, command="!!ask hi")
    routed(user)

    assert spy == [user], f"the command still ran locally: {spy}"
    info_lines = [line for _, line in local_log.lines("INFO")]
    assert len(info_lines) == 1, f"one INFO line explains it: {local_log.lines()}"
    assert (bool(info_lines) and "cross-server role is local" in info_lines[0]
            and "!!ask hi" in info_lines[0]), \
        f"the line names the role and the command: {info_lines}"
    assert bool(info_lines) and "!!gamesai node status" in info_lines[0], \
        f"and points at !!gamesai node status: {info_lines}"

    local_log.records.clear()
    help_source = Source(local_instance.base, command="!!ask")
    c._route(c.ROUTE_LOCAL, lambda src: None)(help_source)
    assert not [line for _, line in local_log.lines("INFO")], \
        f"a help text says nothing (it is local by design): {local_log.lines()}"

    local_log.records.clear()
    remote_source = c.WebSocketCommandSource(local_instance.plugin, origin="host-a",
                                             player="Steve", is_console=False,
                                             permission_level=3, sink=lambda text: None)
    c._route(c.ROUTE_SERVER, lambda src: None)(remote_source)
    assert not [line for _, line in local_log.lines("INFO")], \
        f"a command that arrived from another instance says nothing either: {local_log.lines()}"


def test_a_client_whose_link_drops_says_so(hub, enrolled, log_capture):
    b = enrolled.instance
    node_log = log_capture(enrolled.plugin.logger)
    hub.manager.stop()

    assert wait_until(lambda: not enrolled.manager.connected, timeout=10), \
        ("waiting for the client's link to go down: "
         f"{(enrolled.manager.mode, enrolled.manager.connected)}")
    assert enrolled.manager.is_client and not enrolled.manager.connected, \
        ("the client is still a client but its link is down: "
         f"{(enrolled.manager.mode, enrolled.manager.connected)}")

    node_log.records.clear()
    dropped = Source(enrolled.base, command="!!data read key1")
    b._route(b.ROUTE_SERVER, lambda src: None)(dropped)

    info_lines = [line for _, line in node_log.lines("INFO")]
    assert len(info_lines) == 1, f"the downgrade is logged once: {node_log.lines()}"
    assert (bool(info_lines) and "cross-server link is down" in info_lines[0]
            and "!!data read key1" in info_lines[0]), \
        f"the line says the link is down: {info_lines}"
