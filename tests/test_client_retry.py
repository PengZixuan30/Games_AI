"""One failed connect attempt must not strand an enrolled client in local mode.

The probe has just proved that a GamesAI hub answers at the configured uri, so the role for
this load is *client*. The connect attempt that follows can still fail on its own -- the hub
restarting, a lost packet right after `!!gamesai node claim` -- and the old code answered that
by settling `local` and starting a loopback hub, after stopping the node: the backoff retry
loop never ran, and the instance ran every hub-class command with its own state until somebody
reloaded it.

The hub used here is a stub on purpose: it answers probes like a real one, but fails the first
real connection (close code 1011, which is not a fatal GamesAI close code), which is exactly
the transient failure the real hub cannot be asked to produce on demand.
"""
import importlib.util
import json
import logging
import os
import socket
import sys
import threading

import pytest

from _helpers.paths import PKG
from _helpers.wait import wait_until

from websockets.sync.server import serve as raw_serve

log = logging.getLogger("retry-test")


def load_instance(alias):
    """Load a private copy of the plugin, so this suite cannot disturb the shared ``games_ai``."""
    spec = importlib.util.spec_from_file_location(
        alias, os.path.join(PKG, "__init__.py"), submodule_search_locations=[PKG])
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def lines(self, level=None):
        return [(record.levelname, str(record.getMessage())) for record in self.records
                if level is None or record.levelname == level]


class StubHub:
    """Answers probes like a GamesAI hub, but fails the first ``refuse_real`` real connects.

    ``refuse_real=1`` is the transient failure under test; a huge number is a hub this client
    can never connect to, which is what the unload path has to tear down cleanly.
    """

    def __init__(self, port, refuse_real=1):
        self.port = port
        self.uri = "ws://127.0.0.1:{}".format(self.port)
        self.refuse_real = refuse_real
        self.probe_answers = 0
        self.real_attempts = 0
        self.registered = threading.Event()
        self._server = raw_serve(self._handle, "127.0.0.1", self.port)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def _ack(self, **extra):
        return json.dumps({"type": "hello_ack", "app": "games_ai_mcdr", "protocol": 1,
                           "hub": "stub-hub", "peers": [], **extra})

    def _handle(self, connection):
        try:
            frame = json.loads(connection.recv(timeout=5))
        except Exception:
            return
        if frame.get("probe"):
            self.probe_answers += 1
            connection.send(self._ack())
            return
        self.real_attempts += 1
        if self.real_attempts <= self.refuse_real:
            connection.close(1011, "transient failure")
            return
        connection.send(self._ack(token_name=str(frame.get("server") or "")))
        self.registered.set()
        try:
            for _ in connection:
                pass
        except Exception:
            pass

    def stop(self):
        try:
            self._server.shutdown()
        except Exception:
            pass
        self._thread.join(5)


class BaseServer:
    def __init__(self, name):
        self.name = name
        self.logger = logging.getLogger("mcdr-" + name)

    def rtr(self, translation_key, *args, **kwargs):
        return translation_key

    def say(self, message, **kwargs):
        return None

    def execute_command(self, raw, source=None):
        return None


class PluginServer(BaseServer):
    def __init__(self, name, folder):
        super().__init__(name)
        self.folder = folder

    def get_data_folder(self):
        return self.folder


@pytest.fixture(scope="module")
def instance():
    """The plugin instance under test: one private copy, shared for the whole module.

    Loading ``games_ai/__init__.py`` again is the expensive part of this suite, and every global
    it leaves behind belongs to this copy only. The ``sys.modules`` entries go away with it.
    """
    alias = "games_ai_retry_b"
    module = load_instance(alias)
    yield module
    for name in [name for name in sys.modules if name == alias or name.startswith(alias + ".")]:
        sys.modules.pop(name, None)


@pytest.fixture
def plugin_env(instance, tmp_path, monkeypatch):
    """Instance ``B`` wired to its own plugin server, data folder and log capture."""
    module = instance
    plugin = PluginServer("node-b", str(tmp_path / "node-b"))
    os.makedirs(plugin.folder, exist_ok=True)
    capture = LogCapture()
    plugin.logger.addHandler(capture)
    plugin.logger.setLevel(logging.INFO)

    monkeypatch.setattr(module, "_server_ref", plugin, raising=False)
    monkeypatch.setattr(module.plugin_config, "allow_permission", 3)
    monkeypatch.setattr(module.plugin_config, "websocket_name", "survival")
    monkeypatch.setattr(module.plugin_config, "cross_server_name", "survival")
    monkeypatch.setattr(module.plugin_config, "websocket_force_server", False)
    monkeypatch.setattr(module.plugin_config, "websocket_identity_file", "")
    monkeypatch.setattr(module.plugin_config, "websocket_auto_enroll", True)
    monkeypatch.setattr(module.plugin_config, "websocket_token_ttl_hours", -1)
    monkeypatch.setattr(module, "_config_ref", {}, raising=False)

    yield plugin, capture

    module._stop_cross_server(plugin)
    plugin.logger.removeHandler(capture)
    shared = logging.getLogger("games_ai")
    if capture in shared.handlers:
        shared.removeHandler(capture)


def test_a_failed_first_connect_keeps_the_client_role(instance, free_port):
    """Section 1: the probe proves a hub, the first connect fails -> the role stays client."""
    module = instance
    stub = StubHub(free_port(), refuse_real=1)
    manager = module.CrossServerManager(stub.uri, name="host-b", token="stub-token", logger=log)
    try:
        mode = manager.start(timeout=5)

        assert stub.probe_answers >= 1, f"the probe really proved a hub: {stub.probe_answers}"
        assert mode == module.MODE_CLIENT, \
            f"start() still reports the client role: {(mode, manager.reason)}"
        assert manager.is_client, f"is_client is True: {manager.mode}"
        assert "the link failed" in manager.reason, \
            f"the failure is reported in the reason: {manager.reason}"
        assert manager.hub is None and manager.hub_uri is None, \
            f"no loopback hub was started: {(manager.hub, manager.hub_uri)}"
        assert manager.peer_uri == stub.uri, \
            f"local peers are pointed at the remote hub: {manager.peer_uri}"
        node = manager.node
        assert node is not None, "the node object was kept, not stopped"
        assert node is not None and node._thread is not None and node._thread.is_alive(), \
            f"its retry loop is alive: {None if node is None else node._thread}"
        assert manager.is_client and (not manager.connected or stub.registered.is_set()), \
            f"the manager is a client while the failed attempt is still the latest one: " \
            f"{(manager.mode, manager.connected, stub.real_attempts)}"
        assert wait_until(lambda: manager.connected, 10), \
            f"the retry really happens and the link comes back on its own: {manager.reason}"
        assert stub.real_attempts >= 2, f"the second attempt reached the stub: {stub.real_attempts}"
        assert stub.registered.is_set(), "the stub registered the node"
        assert manager.is_client and manager.connected, "and it is a live connection now"
    finally:
        manager.stop()
        stub.stop()


def test_the_plugin_keeps_the_client_role_after_a_failed_connect(instance, plugin_env, free_port,
                                                                 monkeypatch):
    """Section 2: the same through the plugin (the claim -> restart path)."""
    module = instance
    plugin, capture = plugin_env
    stub = StubHub(free_port(), refuse_real=1)
    monkeypatch.setattr(module.plugin_config, "websocket_uri", stub.uri)
    module._save_identity(plugin, "survival", "stub-token", stub.uri)
    capture.records.clear()
    module._start_cross_server(plugin, {})
    try:
        assert wait_until(lambda: module.plugin_config.cross_server_mode != "pending", 20), \
            module.plugin_config.cross_server_mode
        assert module.plugin_config.cross_server_mode == "client", \
            f"the plugin reports the client role: {module.plugin_config.cross_server_mode}"
        manager = module._cross_server
        assert manager is not None and manager.is_client, \
            f"the manager is a client: {None if manager is None else manager.mode}"
        assert manager.node is not None, "it kept the node for its reconnect loop"
        assert manager.hub is None and manager.hub_uri is None, \
            f"no loopback hub was started for the bot: {(manager.hub, manager.hub_uri)}"
        assert (manager.node._thread is not None and manager.node._thread.is_alive()) \
            or manager.connected, \
            f"the node's retry loop is alive or already reconnected: {manager.connected}"
        errors = [line for _, line in capture.lines("ERROR")]
        assert len([line for line in errors if "link failed" in line]) == 1, \
            f"the failure is logged honestly once: {capture.lines()}"
        assert any("keeping the client role" in line for line in errors), \
            f"and the log says the client role is kept: {capture.lines()}"
        assert module._read_cross_server_role(plugin) == "client", \
            f"the role memory for the next load says client: {module._read_cross_server_role(plugin)}"
        assert wait_until(lambda: manager.connected, 10), \
            f"the link comes back without a reload: {manager.reason}"
        module._stop_cross_server(plugin)
        assert module._cross_server is None \
            and module.plugin_config.cross_server_mode == "local", \
            f"unload takes the recovered client down: {module.plugin_config.cross_server_mode}"
    finally:
        module._stop_cross_server(plugin)
        stub.stop()


def test_without_evidence_of_a_hub_the_instance_stays_local(instance, free_port):
    """Section 3: without evidence of a hub the instance still goes local + loopback."""
    module = instance
    raw = socket.socket()
    raw.bind(("127.0.0.1", free_port()))
    raw.listen(5)
    occupied_uri = "ws://127.0.0.1:{}".format(raw.getsockname()[1])
    manager_c = module.CrossServerManager(occupied_uri, name="host-c", logger=log)
    try:
        assert manager_c.start(timeout=5) == module.MODE_LOCAL, \
            f"an occupied, silent address stays local: {manager_c.reason}"
        assert manager_c.hub is not None \
            and (manager_c.hub_uri or "").startswith("ws://127.0.0.1:"), \
            f"and still hosts a loopback hub for the bot: {manager_c.hub_uri}"
        assert manager_c.peer_uri == manager_c.hub_uri, \
            f"its local peer_uri is the loopback hub: {manager_c.peer_uri}"
    finally:
        manager_c.stop()
        raw.close()

    manager_d = module.CrossServerManager("wss://example.invalid:9443", name="host-d", logger=log)
    try:
        assert manager_d.start(timeout=5) == module.MODE_LOCAL, \
            f"an address this machine cannot serve stays local: {manager_d.reason}"
        assert manager_d.hub is not None \
            and (manager_d.hub_uri or "").startswith("ws://127.0.0.1:"), \
            f"with a loopback hub as before: {manager_d.hub_uri}"
    finally:
        manager_d.stop()


def test_stop_clears_a_client_that_never_connected(instance, free_port):
    """Section 4: unload tears down a client that never connected."""
    module = instance
    stub = StubHub(free_port(), refuse_real=10 ** 9)
    manager = module.CrossServerManager(stub.uri, name="host-e", token="stub-token", logger=log)
    try:
        assert manager.start(timeout=5) == module.MODE_CLIENT, \
            f"a hub that never accepts still leaves the client role: " \
            f"{(manager.mode, manager.reason)}"
        assert not manager.connected, "nothing ever connected"
        never = manager.node
        never_thread = None if never is None else never._thread
        assert never_thread is not None and never_thread.is_alive(), \
            f"its retry loop was running: {never_thread}"
        manager.stop()
        assert manager.node is None and manager.hub is None, \
            f"stop() cleared the node and the role object: {(manager.node, manager.hub)}"
        assert never_thread is not None and not never_thread.is_alive(), \
            f"the retry thread is gone: {never_thread}"
        assert not manager.connected, "nothing is connected after stop"
    finally:
        manager.stop()
        stub.stop()


def test_the_plugin_unload_stops_a_client_that_never_connected(instance, plugin_env, free_port,
                                                               monkeypatch):
    module = instance
    plugin, _ = plugin_env
    stub = StubHub(free_port(), refuse_real=10 ** 9)
    monkeypatch.setattr(module.plugin_config, "websocket_uri", stub.uri)
    module._save_identity(plugin, "survival", "stub-token", stub.uri)
    module._start_cross_server(plugin, {})
    try:
        assert wait_until(lambda: module.plugin_config.cross_server_mode != "pending", 20), \
            module.plugin_config.cross_server_mode
        manager = module._cross_server
        never = None if manager is None else manager.node
        never_thread = None if never is None else never._thread
        assert manager is not None and manager.is_client and not manager.connected, \
            f"the plugin-side client never connected either: " \
            f"{None if manager is None else (manager.mode, manager.connected)}"
        module._stop_cross_server(plugin)
        assert module._cross_server is None \
            and module.plugin_config.cross_server_mode == "local", \
            f"its unload path stops the link: {module.plugin_config.cross_server_mode}"
        assert never_thread is not None and wait_until(lambda: not never_thread.is_alive(), 5), \
            f"and the retry thread ends with it: {never_thread}"
    finally:
        module._stop_cross_server(plugin)
        stub.stop()
