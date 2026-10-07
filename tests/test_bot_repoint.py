"""A runtime role change must re-point the Mineflayer bot at the hub it now belongs to.

`!!gamesai node claim` restarts the cross-server link, and on a local -> client transition that
moves `manager.peer_uri` from the loopback hub this instance hosted (a random 127.0.0.1 port)
to the remote hub. The bot is a client of that address like every peer, so a bot left dialling
the dead loopback port registers nowhere -- and its JS config still names that port on the next
start. The reverse transition (client -> local) moves the address back the same way.

`_restart_cross_server` used to keep the bot where it was ("the address it dials did not
change"), which is wrong exactly here. This suite pins the three outcomes:

* a transition that changes the address rewrites the config, and restarts a running bot;
* a transition that changes the address does **not** start a bot that was not running;
* no transition means no rewrite and no restart, even with a running bot.

It drives the real `!!gamesai node claim` path, with `is_node_running`/`_stop_bot_stack`/
`_run_mineflayer_bot`/`_write_mineflayer_config` spied on so nothing real is launched (the
original `_write_mineflayer_config` still runs, so the written file is the real one).

The whole scenario is one test: every step builds on the previous one (B is enrolled, then C is,
then C is claimed again, then B moves back), so splitting it would only multiply the expensive
hub handshakes while pretending the steps are independent.
"""
import contextlib
import importlib.util
import io
import json
import logging
import os
import socket
import sys

import pytest
import yaml

from _helpers.paths import LANG_DIR, PKG
from _helpers.wait import wait_until


def load_instance(alias):
    """Load the plugin package again under its own namespace of globals."""
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


class BaseServer:
    """MCDR's ``ServerInterface``: rtr/logger/say/execute_command -- and no data folder."""

    def __init__(self, name, lang):
        self.name = name
        self.lang = lang
        self.logger = logging.getLogger("mcdr-" + name)

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
        return None


class PluginServer(BaseServer):
    """What ``on_load`` receives: the same, plus this plugin's own data folder."""

    def __init__(self, name, folder, lang):
        super().__init__(name, lang)
        self.folder = folder

    def get_data_folder(self):
        return self.folder


class Source:
    def __init__(self, base, who="console", permission=4, console=True):
        self.base = base
        self.player = None if console else who
        self.permission = permission
        self.console = console
        self.received = []

    def get_server(self):
        return self.base

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
    pass


def read_json(path):
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def read_text(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def prepare(module, plugin, base, folder, name, config, uri):
    """The common per-instance setup: identity-free, local mode, a bot that can be re-pointed."""
    module._server_ref = plugin
    module.prefix = "[GamesAI]"
    module.allow_permission = 3
    module.plugin_config.allow_permission = 3
    module.plugin_config.websocket_uri = uri
    module.plugin_config.websocket_name = name
    module.plugin_config.cross_server_name = name
    module.plugin_config.websocket_force_server = False
    module.plugin_config.websocket_identity_file = ""
    module.plugin_config.websocket_auto_enroll = True
    module.plugin_config.websocket_token_ttl_hours = -1
    module.data_path = os.path.join(folder, "database", "public_database.db")
    os.makedirs(os.path.dirname(module.data_path), exist_ok=True)
    bot_dir = os.path.join(folder, "mineflayer")
    os.makedirs(bot_dir, exist_ok=True)
    module.plugin_config.mineflayer_init_js_path = os.path.join(bot_dir, "init.js")
    module.plugin_config.skills_path = os.path.join(folder, "skills", "skills.json")
    with io.open(os.path.join(bot_dir, "config.json"), "w", encoding="utf-8") as handle:
        json.dump({"enabled": True, "bot": {"username": "Bot"},
                   "websocket": {"url": "ws://127.0.0.1:1", "token": "keep-this-bot-token"}},
                  handle, indent=4)
    module._config_ref = config
    return os.path.join(bot_dir, "config.json")


def spy_bot_paths(module, state):
    """Record what the re-point path does, without starting or killing a real process."""
    real_write = module._write_mineflayer_config

    def spy_write(server, config, peer_uri=None):
        state["calls"].append(("write", peer_uri))
        return real_write(server, config, peer_uri)

    def spy_stop(server, logger=None):
        state["calls"].append(("stop", None))
        return []

    def spy_start(server, bot_config, path):
        state["calls"].append(("start", None))

    module._write_mineflayer_config = spy_write
    module._stop_bot_stack = spy_stop
    module._run_mineflayer_bot = spy_start
    # the restart path reads the package's own imported name, so the spy goes there
    module.is_node_running = lambda: state["running"]
    real_repoint = module._repoint_bot_after_role_change

    def spy_repoint(server, config, previous_peer_uri, bot_was_running):
        # Appended *after* the real helper ran: a non-empty "ready" list then means the config
        # was written and the bot was stopped/started, so the checks cannot race the callback.
        try:
            return real_repoint(server, config, previous_peer_uri, bot_was_running)
        finally:
            state["ready"].append(previous_peer_uri)

    module._repoint_bot_after_role_change = spy_repoint


@pytest.fixture
def instances():
    """Three separately loaded copies of the plugin package: the hub and its two nodes."""
    return (load_instance("games_ai_repoint_hub"),
            load_instance("games_ai_repoint_b"),
            load_instance("games_ai_repoint_c"))


def test_a_role_change_re_points_the_bot(instances, free_port, tmp_path):
    A, B, C = instances
    lang = yaml.safe_load(io.open(os.path.join(LANG_DIR, "en_us.yml"), encoding="utf-8").read())
    uri = "ws://127.0.0.1:{}".format(free_port())
    folders = {}
    for name in ("hub", "node-b", "node-c"):
        folders[name] = os.path.join(str(tmp_path), name)
        os.makedirs(folders[name], exist_ok=True)

    hub_plugin = PluginServer("hub", folders["hub"], lang)
    b_plugin = PluginServer("node-b", folders["node-b"], lang)
    c_plugin = PluginServer("node-c", folders["node-c"], lang)
    b_base = BaseServer("node-b-base", lang)
    c_base = BaseServer("node-c-base", lang)
    b_log = LogCapture()
    raw = None
    manager_a = None

    try:
        # === 1. the hub is up; both nodes are unenrolled and therefore local ===
        A._server_ref = hub_plugin
        A.prefix = "[GamesAI]"
        manager_a = A.CrossServerManager(uri, name="host-a", handler=A._on_cross_message,
                                         logger=logging.getLogger("hub"))
        assert manager_a.start(timeout=5) == A.MODE_SERVER, \
            f"the hub started: {manager_a.reason}"
        A._cross_server = manager_a

        B_CONFIG = {"mineflayer_bot": {"enabled": True, "cycle_interval": 10.0,
                                       "bot": {"username": "Bot"}}}
        C_CONFIG = {"mineflayer_bot": {"enabled": True, "cycle_interval": 10.0,
                                       "bot": {"username": "Bot"}}}
        b_config_path = prepare(B, b_plugin, b_base, folders["node-b"], "host-b", B_CONFIG, uri)
        c_config_path = prepare(C, c_plugin, c_base, folders["node-c"], "host-c", C_CONFIG, uri)

        B._start_cross_server(b_plugin, B_CONFIG)
        C._start_cross_server(c_plugin, C_CONFIG)
        for label, module in (("B", B), ("C", C)):
            wait_until(lambda m=module: m.plugin_config.cross_server_mode != "pending", timeout=20)
            assert module.plugin_config.cross_server_mode == "local", \
                "{} is local before it is enrolled: {}".format(
                    label, (module.plugin_config.cross_server_mode,
                            getattr(module._cross_server, "reason", None)))

        old_b_peer = B._cross_server.peer_uri
        assert old_b_peer.startswith("ws://127.0.0.1:"), \
            f"the local peer_uri is a loopback address: {old_b_peer}"
        assert read_json(b_config_path)["websocket"]["url"] == "ws://127.0.0.1:1", \
            "the bot's config starts on another address"

        # === 2. local -> client on a claim re-points a running bot ===
        b_state = {"calls": [], "ready": [], "running": True}
        spy_bot_paths(B, b_state)
        b_plugin.logger.addHandler(b_log)
        b_plugin.logger.setLevel(logging.DEBUG)

        b_token = manager_a.hub.issue("host-b")
        console_b = Source(b_base)
        B._node_claim(console_b, Ctx(token=b_token))
        assert "Enrolled as host-b" in console_b.text(), f"the claim is accepted: {console_b.text()}"
        assert wait_until(lambda: b_state["ready"], timeout=20), \
            f"the re-point path ran: {b_state}"
        assert B._cross_server is not None and B._cross_server.is_client, \
            f"the node became a client: {B.plugin_config.cross_server_mode}"
        wait_until(lambda: B._cross_server.connected, timeout=10)
        assert B._cross_server.connected, f"the client link is live: {B._cross_server.reason}"
        assert B._cross_server.peer_uri == uri, \
            f"the new peer_uri is the remote hub: {B._cross_server.peer_uri}"

        written = read_json(b_config_path)
        assert written["websocket"]["url"] == uri, \
            f"the bot's config was rewritten to the new address: {written['websocket']}"
        assert written["websocket"]["token"] == "keep-this-bot-token", \
            f"the rewrite kept the bot's own token: {written['websocket']}"
        assert written["websocket"]["url"] == B._cross_server.peer_uri, \
            f"the rewrite names the address the manager reports: {written['websocket']}"
        assert b_state["calls"] == [("write", uri), ("stop", None), ("start", None)], \
            f"the running bot was stopped and started again, after the rewrite: {b_state['calls']}"
        assert B._cross_server.hub is None and B._cross_server.hub_uri is None, \
            "the old local loopback hub was torn down: {}".format(
                (B._cross_server.hub, B._cross_server.hub_uri))
        info_lines = [line for _, line in b_log.lines("INFO")]
        assert len([line for line in info_lines if "hub address changed" in line]) == 1, \
            f"the address change is logged once: {info_lines}"
        assert any("hub address changed" in line and uri in line and old_b_peer in line
                   for line in info_lines), f"and the line names both addresses: {info_lines}"
        assert "did not change" not in (B._restart_cross_server.__doc__ or ""), \
            "_restart_cross_server no longer claims the address cannot change: " \
            f"{B._restart_cross_server.__doc__}"

        # === 3. local -> client re-points the config but starts no bot that was not running ===
        c_state = {"calls": [], "ready": [], "running": False}
        spy_bot_paths(C, c_state)
        c_token = manager_a.hub.issue("host-c")
        console_c = Source(c_base)
        C._node_claim(console_c, Ctx(token=c_token))
        assert "Enrolled as host-c" in console_c.text(), f"the claim is accepted: {console_c.text()}"
        assert wait_until(lambda: c_state["ready"], timeout=20), \
            f"the re-point path ran: {c_state}"
        assert C._cross_server is not None and C._cross_server.is_client, \
            f"the node became a client: {C.plugin_config.cross_server_mode}"
        wait_until(lambda: C._cross_server.connected, timeout=10)
        written_c = read_json(c_config_path)
        assert written_c["websocket"]["url"] == uri, \
            f"the config was rewritten even without a running bot: {written_c['websocket']}"
        assert c_state["calls"] == [("write", uri)], \
            f"no bot was stopped and none was started: {c_state['calls']}"

        # === 4. no transition -> no rewrite and no restart, even with a running bot ===
        c_state["calls"], c_state["ready"] = [], []
        c_state["running"] = True
        before_c = read_text(c_config_path)
        c_peer_before = C._cross_server.peer_uri
        console_c2 = Source(c_base)
        C._node_claim(console_c2, Ctx(token=c_token))
        assert "Enrolled as host-c" in console_c2.text(), \
            f"the claim is accepted again: {console_c2.text()}"
        assert wait_until(lambda: c_state["ready"], timeout=20), \
            f"the re-point path ran again: {c_state}"
        assert C._cross_server.peer_uri == c_peer_before == uri, \
            f"the role did not change: {(c_peer_before, C._cross_server.peer_uri)}"
        assert c_state["calls"] == [], f"the bot's config was not rewritten: {c_state['calls']}"
        assert read_text(c_config_path) == before_c, "the config file is untouched"

        # === 5. client -> local re-points back to the loopback hub ===
        # The reverse transition: the address stops being a GamesAI hub (a service took the port
        # over, or the hub moved), so the next load settles local again -- with a fresh loopback
        # hub. The helper the claim path uses has to move the bot back to that address too.
        raw = socket.socket()
        raw.bind(("127.0.0.1", free_port()))
        raw.listen(5)
        B._stop_cross_server(b_plugin)
        B._delete_identity(b_plugin)
        B._save_cross_server_role(b_plugin, B.MODE_LOCAL)      # no 15s client grace in this test
        B.plugin_config.websocket_uri = "ws://127.0.0.1:{}".format(raw.getsockname()[1])
        b_state["calls"], b_state["ready"] = [], []
        b_state["running"] = True
        B._start_cross_server(b_plugin, B_CONFIG)
        wait_until(lambda: B.plugin_config.cross_server_mode != "pending", timeout=20)
        manager_b = B._cross_server
        assert manager_b.mode == B.MODE_LOCAL, \
            "B is local again (the address is occupied but silent): {}".format(
                (manager_b.mode, manager_b.reason))
        local_uri = manager_b.peer_uri
        assert local_uri.startswith("ws://127.0.0.1:"), \
            f"its local peer_uri is a loopback address again: {local_uri}"
        assert local_uri != uri, f"the address really changed: {(uri, local_uri)}"
        B._repoint_bot_after_role_change(b_plugin, B_CONFIG, uri, True)
        assert b_state["calls"] == [("write", local_uri), ("stop", None), ("start", None)], \
            f"the helper rewrote the config for the local hub: {b_state['calls']}"
        assert read_json(b_config_path)["websocket"]["url"] == local_uri, \
            "and the file names the loopback hub: {}".format(
                read_json(b_config_path)["websocket"])
    finally:
        if raw is not None:
            raw.close()
        for module, plugin in ((B, b_plugin), (C, c_plugin)):
            with contextlib.suppress(Exception):
                module._stop_cross_server(plugin)
        if manager_a is not None:
            with contextlib.suppress(Exception):
                manager_a.stop()
        with contextlib.suppress(Exception):
            b_plugin.logger.removeHandler(b_log)
