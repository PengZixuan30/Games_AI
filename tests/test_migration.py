"""Test the config migration hook and the plugin wiring of stage 1."""
import dis
import inspect
import json
import os
import re

import pytest

import games_ai
from games_ai.config import plugin_config

from _helpers.paths import PKG, REPO_ROOT
from _helpers.pkg import module_text, package_text


def unbound_local_risks(func, module_globals):
    """Names loaded from a fast-local slot that was never stored earlier in the function.

    This is the exact shape of the bug found in on_load: assigning a module global without
    a ``global`` declaration turns every earlier read of that name into an UnboundLocalError.
    Parameters are excluded -- they are always bound on entry.
    """
    code = func.__code__
    params = set(code.co_varnames[: code.co_argcount + code.co_kwonlyargcount])
    stored, risky = set(), set()
    for ins in dis.Bytecode(func):
        if ins.opname == "STORE_FAST":
            stored.add(ins.argval)
        elif ins.opname == "LOAD_FAST" and ins.argval not in stored and ins.argval not in params:
            risky.add(ins.argval)
    return risky & module_globals


def test_an_old_config_with_a_custom_bot_url(monkeypatch):
    # The migration rebinds this module global; monkeypatch puts the previous value back so no
    # later suite reads a note this test left behind.
    monkeypatch.setattr(games_ai, "_config_migration_note", games_ai._config_migration_note)
    old = {
        "prefix": "[GamesAI]",
        "permission": 3,
        "mineflayer_bot": {
            "enabled": True,
            "cycle_interval": 15.0,
            "websocket": {"url": "ws://10.0.0.5:9000", "reconnect_interval": 10,
                          "timeout": 60, "first_connect_interval": 0.5},
            "bot": {"username": "Bot", "password": "", "auth": "microsoft"},
        },
    }

    changed = games_ai._migrate_config_data(old)

    assert changed is True, "reports a change (so MCDR saves)"
    assert old.get("websocket", {}).get("uri") == "ws://10.0.0.5:9000", \
        f"url moved to websocket.uri: {old.get('websocket')}"
    assert "websocket" not in old["mineflayer_bot"], f"old block removed: {old['mineflayer_bot']}"
    assert old["mineflayer_bot"]["enabled"] is True \
        and old["mineflayer_bot"]["cycle_interval"] == 15.0, "other bot keys kept"
    assert "10.0.0.5" in games_ai._config_migration_note, \
        f"note mentions the move: {games_ai._config_migration_note}"
    assert json.loads(json.dumps(old))["websocket"]["uri"] == "ws://10.0.0.5:9000", \
        "JSON round-trip is clean"


def test_a_user_written_new_key_wins_and_the_old_block_is_dropped():
    both = {
        "websocket": {"uri": "ws://new.example:1234", "force_server": True},
        "mineflayer_bot": {"websocket": {"url": "ws://old.example:9999"}},
    }

    changed = games_ai._migrate_config_data(both)

    assert changed is True, "reports a change"
    assert both["websocket"]["uri"] == "ws://new.example:1234", \
        f"new uri kept: {both['websocket']}"
    assert both["websocket"]["force_server"] is True, "force_server kept"
    assert "websocket" not in both["mineflayer_bot"], \
        f"old block removed: {both['mineflayer_bot']}"


def test_nothing_to_migrate():
    plain = {"prefix": "[GamesAI]", "mineflayer_bot": {"enabled": False}}

    assert games_ai._migrate_config_data(plain) is False, "no change reported"
    assert "websocket" not in plain, f"dict untouched: {plain}"
    assert "websocket" not in plain.get("mineflayer_bot", {}), "no websocket key added"


def test_an_old_block_without_a_url():
    no_url = {"mineflayer_bot": {"websocket": {"reconnect_interval": 5}}}

    assert games_ai._migrate_config_data(no_url) is True, "reports a change"
    assert "websocket" not in no_url["mineflayer_bot"], f"block removed: {no_url['mineflayer_bot']}"
    assert "websocket" not in no_url, f"no uri invented: {no_url}"


@pytest.mark.parametrize("garbage", [None, [], "text", 42, {"mineflayer_bot": "nope"},
                                     {"mineflayer_bot": {"websocket": []}}],
                         ids=["None", "a list", "a string", "a number", "a bot string",
                              "a websocket list"])
def test_garbage_input_never_raises(garbage):
    try:
        result = games_ai._migrate_config_data(garbage)
        ok = result is False
    except Exception as exc:
        ok, result = False, exc

    assert ok, f"garbage {garbage!r} -> False: {result}"


def test_the_plugin_module_loads_and_exposes_the_new_surface():
    assert hasattr(games_ai, "CrossServerManager"), "cross-server manager exported"
    assert callable(getattr(games_ai, "_start_cross_server", None)), "start helper exists"
    assert callable(getattr(games_ai, "_stop_cross_server", None)), "stop helper exists"
    assert (games_ai.MODE_SERVER, games_ai.MODE_CLIENT, games_ai.MODE_LOCAL) == \
        ("server", "client", "local"), "mode constants exported"
    assert {"games_ai@cross_server", "games_ai@ws_hub", "games_ai@ws_node"} \
        <= set(games_ai._PLUGIN_THREAD_NAMES), \
        f"thread names registered: {sorted(games_ai._PLUGIN_THREAD_NAMES)}"
    assert plugin_config.cross_server_mode == "local", "config defaults are local"
    assert hasattr(plugin_config, "websocket_uri") \
        and hasattr(plugin_config, "websocket_force_server"), \
        f"config has the new fields: {dir(plugin_config)}"


def test_no_function_reads_a_local_slot_before_assigning_it():
    module_globals = set(vars(games_ai))
    offenders = []
    for name, obj in list(vars(games_ai).items()):
        if not inspect.isfunction(obj) or obj.__module__ != "games_ai":
            continue
        risk = unbound_local_risks(obj, module_globals)
        if risk:
            offenders.append((name, sorted(risk)))

    assert not offenders, f"no function reads a global as an unassigned local: {offenders}"
    assert '_config_migration_note' not in games_ai.on_load.__code__.co_varnames, \
        "on_load reads _config_migration_note as a global"


def test_loader_order_guards():
    _config_src = module_text("config")
    assert "prefix: str = " in _config_src and "allow_permission: int = " in _config_src, \
        f"the canonical defaults live in config.py (class attributes of SyncPluginConfig): " \
        f"{_config_src[:200]}"
    assert plugin_config.prefix == "[GamesAI]" and plugin_config.allow_permission == 3, \
        f"...so a diagnostic before on_load still prints a prefix: " \
        f"{(plugin_config.prefix, plugin_config.allow_permission)}"

    _init_src = module_text("__init__.py")
    _package_src = package_text()
    _logger_src = module_text("logger")
    _apply = _init_src.index("    _apply_config(server, config)")
    _data_help = _init_src.index('register_help_message(prefix="!!data"')
    assert "peer_uri: str | None = None" in _package_src, \
        "_write_mineflayer_config tolerates a missing peer_uri (the reload path relies on it)"
    assert "plugin_logger.propagate = False" in _logger_src \
        and "logger.attach(server)" in _init_src, \
        "the plugin logger is cut off from the root logger"
    assert not any(name in _init_src for name in
                   ("def _link_log", "def _link_debug", "def _setup_plugin_logger",
                    "def _chat_log", "def _update_log")) \
        and "def verbose(" in _logger_src and "def safe(" in _logger_src \
        and "def step(" in _logger_src, \
        "the log helpers live in logger.py, not in __init__.py"
    assert _apply < _data_help, \
        f"the !!data registration runs after the config is applied: apply at {_apply}, " \
        f"help at {_data_help}"
    # the eight shadow globals were removed: plugin_config owns every one of these values now
    for name in ("prefix", "allow_permission", "ai_dict", "default_ai", "data_path", "name_to_id",
                 "debug_mode", "skills"):
        assert re.search(r"(?m)^{} = ".format(name), _package_src) is None \
            and not hasattr(games_ai, name), \
            "{} is not a module-level global of the package any more".format(name)
    assert "plugin_config.allow_permission" in _package_src \
        and "plugin_config.all_ai" in _package_src \
        and "plugin_config.skills_description" in _package_src \
        and "plugin_config.data_path" in _package_src, \
        "the surfaces that read them were redirected"


def test_the_update_path_lives_in_its_own_module():
    _update_src = module_text("update_round")
    _init_src = module_text("__init__.py")
    _package_src = package_text()

    assert re.search(r"(?m)^\s*(import games_ai\b|from games_ai\b)", _update_src) is None, \
        "the update module does not import the entry package"
    assert all(("def " + name) in _update_src for name in
               ("check_update", "update", "self_update", "_settled_role", "_order_cluster_update",
                "_wait_for_cluster_update", "_on_update_order", "_node_update_worker",
                "_start_update_loop", "_on_peer_registered", "_catch_up_round", "get_main_version")), \
        "...and holds the whole cluster"
    assert not any(("def " + name) in _init_src for name in
                   ("check_update", "update", "self_update", "_settled_role",
                    "_order_cluster_update", "_start_update_loop", "_catch_up_round")), \
        "the entry module no longer defines them"
    assert "update_round.attach(" in _package_src \
        and "update_round._on_update_order(sender, data)" in _package_src \
        and "update_round.unload_status()" in _package_src \
        and "update_round.stop_timer()" in _package_src, \
        "the plugin wires the update path instead"
    assert all(token in _update_src for token in
               ("_manager_of()", "_server_of()", "_link_thread_of()")), \
        "the module reads the live state through the getters"
    assert hasattr(games_ai.update_round.check_update, "__wrapped__"), \
        "check_update kept its @new_thread wrapper (the check fetches over the network)"
    assert not hasattr(games_ai.debug, "__wrapped__"), \
        "...and no decorator was left behind on the entry module's debug()"


def test_the_help_texts_live_in_their_own_module():
    _help_src = module_text("help")
    _init_src = module_text("__init__.py")

    assert "class gamesai_help" in _help_src and "def send_help(" in _help_src, \
        "help.py holds the class and its helper"
    assert re.search(r"(?m)^class gamesai_help\b", _init_src) is None \
        and re.search(r"(?m)^def send_help\(", _init_src) is None, \
        "the entry module defines neither any more"
    assert "from .help import gamesai_help, send_help" in _init_src, \
        "...but still re-exports them"
    assert re.search(r"(?m)^\s*(import games_ai\b|from games_ai\b|from \. import)", _help_src) is None, \
        "the help module does not import the entry package"
    assert games_ai.gamesai_help is games_ai.help.gamesai_help \
        and games_ai.send_help is games_ai.help.send_help, \
        "the package exposes them from help.py"


class _HelpServer:
    """Just what a help method touches: the localized strings and this plugin's metadata."""

    class _Metadata:
        version = "9.9.9-probe"

    def rtr(self, key, **kwargs):
        return key + ("|" + json.dumps(kwargs, sort_keys=True) if kwargs else "")

    def get_plugin_metadata(self, plugin_id):
        # The plain ServerInterface that every command source hands out has exactly this method.
        if plugin_id != "games_ai":
            return None
        return self._Metadata()


class _HelpSource:
    def __init__(self, level=4):
        self._server, self.level, self.shown = _HelpServer(), level, []

    def get_server(self):
        return self._server

    def get_permission_level(self):
        return self.level

    def reply(self, message, **kwargs):
        self.shown.append(str(message))


def test_the_help_answers_carry_the_version_and_the_localized_keys():
    _help_source = _HelpSource()
    games_ai.help.gamesai_help.switch_help(_help_source)
    assert any("9.9.9-probe" in line for line in _help_source.shown), \
        f"the greeting prints the version MCDR reports: {_help_source.shown}"
    assert games_ai.help.plugin_version(object()) == "?", \
        f"a server that cannot answer falls back to ?: {games_ai.help.plugin_version(object())}"
    assert any("!!ask switch <model>" in line and "switch_help" in line
               for line in _help_source.shown), \
        f"a help line carries the command and its localized key: {_help_source.shown}"

    _help_source = _HelpSource(level=0)
    games_ai.help.gamesai_help.data_help(_help_source)
    assert any("no_permission" in line for line in _help_source.shown), \
        f"a gated help group answers with no_permission: {_help_source.shown}"


def test_the_migration_writes_a_complete_websocket_block():
    defs = games_ai.DEFAULT_WEBSOCKET_CONFIG
    old_cfg = {"mineflayer_bot": {"websocket": {"url": "ws://10.0.0.1:9000"}}}

    changed = games_ai._migrate_config_data(old_cfg)
    block = old_cfg.get("websocket", {})

    assert changed is True, f"the migration reports a change so MCDR saves the file: {changed}"
    assert set(block) == set(defs), \
        f"every documented websocket key is present: {sorted(set(defs) - set(block))}"
    assert block.get("uri") == "ws://10.0.0.1:9000", \
        f"the migrated address is kept: {block.get('uri')}"
    assert all(block.get(k) == v for k, v in defs.items() if k != "uri"), \
        f"the other keys carry their defaults: {block}"
    assert block.get("allow_app_id") is not defs["allow_app_id"], \
        "allow_app_id is not the shared default list"

    half_cfg = {"websocket": {"uri": "ws://10.0.0.2:9000", "force_server": True,
                              "allow_app_id": ["x"]}}
    games_ai._migrate_config_data(half_cfg)
    assert set(half_cfg["websocket"]) == set(defs), \
        f"a block left half-written by an older build is topped up: {sorted(half_cfg['websocket'])}"
    assert half_cfg["websocket"]["uri"] == "ws://10.0.0.2:9000" \
        and half_cfg["websocket"]["force_server"] is True \
        and half_cfg["websocket"]["allow_app_id"] == ["x"], \
        f"the user's own values survive the top-up: {half_cfg['websocket']}"

    complete_cfg = {"websocket": dict(defs)}
    assert games_ai._migrate_config_data(complete_cfg) is False, \
        f"a complete block is left alone: {complete_cfg}"


def test_the_dependency_gate_of_the_entry_module():
    entry_src = module_text("__init__.py")
    _package_src = package_text()

    assert "from __future__" not in entry_src, \
        "no 'from __future__ import annotations' in the entry module (forward refs are strings)"
    assert "_deps_pending = bool(deps.unsatisfied())" in entry_src \
        and "    from .openai_api import" in entry_src \
        and "\nfrom .openai_api import" not in entry_src, \
        "the third-party imports are gated behind _deps_pending"
    assert 'dict[str, "ChatParam"]' in _package_src \
        and '"CrossServerManager | None"' in _package_src \
        and '"AutonomousBotController | None"' in _package_src, \
        "the gated names inside annotations are string forward references"
    assert "CONTROLLER_THREAD_NAMES = ()" in entry_src, \
        "the controller thread names have a value without the packages"
    assert not os.path.exists(os.path.join(REPO_ROOT, "requirements.txt")) \
        and os.path.isfile(os.path.join(PKG, "requirements.txt")), \
        "the dependency manifest moved into the package"
    assert "games_ai@deps_install" in games_ai._PLUGIN_THREAD_NAMES \
        and "games_ai@deps_pip" in games_ai._PLUGIN_THREAD_NAMES, \
        "the repair threads are listed for the debug listing"
