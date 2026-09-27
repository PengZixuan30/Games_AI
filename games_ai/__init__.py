from mcdreforged.api.all import *

from .openai_api import setup_openai_logging
from .games_ai_tool import register_tool, register_bot_tool, get_plugin_config_perm, reset_all_tools, TOOL_PLUGIN_IDS
from .database import PublicDatabase
from .config import plugin_config
from .tools_interpreter import load_external_tools
from .mineflayer import write_default_init, write_package_json, run_node, start_mineflayer_client, stop_mineflayer_client, stop_mineflayer_process, detach_mineflayer_process, get_default_init_hash, is_node_running, MineflayerWSClient
from .mineflayer_ai import (AutonomousBotController, set_bot_controller, get_bot_controller,
                            force_abort_thread, CONTROLLER_THREAD_NAMES)
from .external_skills_loader import EXTERNAL_SKILLS_LIST
from .register_extra_plugin import REGISTER_PLUGIN_LIST
from .chat_param import ChatParam, NonHistoryChatParam, register_no_history, unregister_no_history, stop_no_history
from . import context_table

import time,os,requests,lzma,json,threading,logging,math

import shutil
import subprocess
import hashlib
import re

PLUGIN_METADATA = {
    "id": "games_ai",
    "version": "0.7.2",
    "name": "GamesAI",
    "description": {
        "zh_cn": "此插件可以让你在游戏中使用AI",
        "en_us": "This plugin allows you to use AI in the game"
        },
    "author": "yello",
    "link": "https://github.com/PengZixuan30/Games_AI",
    "dependencies": {
        "mcdreforged": ">=2.15.0"
    }
}

# Every users have a ChatParam Object
all_chat_param: dict[str, ChatParam] = {}

unload_status_code = 0
debug_mode = False
websocket_connections: dict[str, MineflayerWSClient] = {}
# Log prefix; ``_apply_config`` overwrites it with the configured value on load. Defined here
# so that diagnostics raised outside a full plugin lifetime (a teardown on a detached thread,
# a started-but-never-loaded instance) never turn into a NameError.
prefix = '[GamesAI]'

# Threads this plugin can own; used by on_unload to report leftovers instead of claiming
# a clean shutdown (Python cannot kill a thread, so a busy one is reported, not hidden).
# Every name is prefixed with ``games_ai@``; the unprefixed entries are legacy names kept
# so a thread started by an older plugin version is still recognised.
_PLUGIN_THREAD_NAMES = frozenset({
    *CONTROLLER_THREAD_NAMES,                   # games_ai@autonomous_bot (+ legacy)
    "games_ai@mineflayer_log", "MineflayerBotLog",
    "games_ai@ws_client",
    "games_ai@update_loop", "games_ai@update_timer", "games_ai@mineflayer_wait_server",
    "games_ai@ask_ai", "games_ai@switch_model", "games_ai@update", "games_ai@reloader",
    "games_ai@speed_test", "games_ai@leftover_watch", "games_ai@debug_threads",
    "games_ai@bot_teardown",
    "games_ai@data_write", "games_ai@data_add", "games_ai@data_del",
    "games_ai@data_read", "games_ai@data_list", "games_ai@data_keys",
})

# How many entries `!!gamesai debug thread` prints per group before summarising the rest.
_THREAD_LIST_LIMIT = 12
_autonomous_controller: AutonomousBotController | None = None
_aibot_lock = threading.Lock()
# Grace period for the cooperative controller stop during unload/reload. An idle loop
# leaves immediately (interruptible wait), so anything longer than this means the thread is
# inside a blocking call — where waiting more rarely helps, and the forced abort follows.
_BOT_STOP_GRACE = 1.5
# How long `!!gamesai reload` may wait for the previous teardown (the detached thread of a
# preceding unload) before it checks whether the WebSocket port has been released.
_BOT_TEARDOWN_WAIT = 5.0
# How long on_unload may wait for the teardown thread before it gives up and returns. One
# synchronously killed node process costs about a second, so the ordinary case stays inside
# this window and MCDR really is unloaded with a dead bot; anything slower is left to the
# detached thread instead of blocking the reload/unload for it.
_BOT_UNLOAD_GRACE = 1.5
# Set when the plugin is unloaded, so a pending "wait for server start" bot
# launch aborts cleanly (see _wait_server_then_launch)
_mineflayer_pending_abort = threading.Event()
_mineflayer_wait_thread: threading.Thread | None = None

# ── reload / teardown serialization ─────────────────────────────────────────
# `!!gamesai reload` reaches the same global bot state as on_unload, and a second reload
# started while the first one is still tearing the bot down used to be able to disable the
# bot entirely (the launcher saw the port of the dying node process still in use, treated it
# as a foreign program and wrote enabled=false). `_reload_lock` makes the command
# single-flight, `_teardown_event` tells a later launch when the previous teardown is done.
_reload_lock = threading.Lock()
_bot_teardown_lock = threading.Lock()
_bot_teardown_event = threading.Event()
_bot_teardown_event.set()           # nothing to wait for before the first teardown


def _watch_thread_exit(thread: threading.Thread, server: PluginServerInterface, name: str,
                       timeout: float = 60.0) -> None:
    """Log when an aborted leftover thread finally dies (it may still be inside a blocking call)."""
    thread.join(timeout)
    if thread.is_alive():
        server.logger.warning(f"{prefix} Leftover {name} thread is still alive after {timeout:.0f}s")
    else:
        server.logger.info(f"{prefix} Leftover {name} thread has finished")


def _abort_leftover_bot_threads(server: PluginServerInterface) -> None:
    """
    Kill bot-controller threads left over from a previous plugin instance.

    Python cannot kill a thread, so if an unload could not stop the controller (it was
    inside a blocking call), that old thread may still be looping. Running it again would
    mean two controllers acting on the same bot, so any controller thread that is alive
    *before* this instance starts its own is aborted here — including one named with the
    legacy ``AutonomousBotAI`` name from an older plugin version.

    An older plugin version has no handler for the injected abort, so its thread ends with
    an exception; :func:`_install_thread_excepthook` turns that into a single log line
    instead of a traceback.
    """
    for thread in threading.enumerate():
        if thread.name not in CONTROLLER_THREAD_NAMES or not thread.is_alive():
            continue
        server.logger.warning(
            f"{prefix} Leftover bot controller thread from a previous plugin instance found, aborting it"
        )
        if not force_abort_thread(thread, server.logger):
            server.logger.warning(
                f"{prefix} Leftover controller thread is still inside a blocking call "
                f"(HTTP request, socket read or its idle wait); the abort takes effect the moment "
                f"that call returns"
            )
            threading.Thread(target=_watch_thread_exit, args=(thread, server, "controller"),
                             daemon=True, name="games_ai@leftover_watch").start()


_previous_thread_excepthook = None


def _install_thread_excepthook(server: PluginServerInterface) -> None:
    """
    Keep the injected abort out of MCDR's console as a traceback.

    A leftover controller thread from an *older* plugin version has no handler for
    ``_ControllerAbort``, so ``threading`` would print a full traceback for a thread that is
    already gone. The hook is chained (everything else keeps its original behaviour) and is
    matched by class name, because the exception object comes from the old, already
    unloaded module instance.
    """
    global _previous_thread_excepthook
    if _previous_thread_excepthook is not None:
        return
    _previous_thread_excepthook = threading.excepthook

    def hook(args: threading.ExceptHookArgs) -> None:
        exc = args.exc_value
        if type(exc).__name__ == "_ControllerAbort" and (type(exc).__module__ or "").startswith("games_ai"):
            server.logger.info(f"{prefix} Leftover bot controller thread aborted")
            return
        _previous_thread_excepthook(args)

    threading.excepthook = hook


def _restore_thread_excepthook() -> None:
    """Give the process its original thread exception hook back."""
    global _previous_thread_excepthook
    if _previous_thread_excepthook is None:
        return
    threading.excepthook = _previous_thread_excepthook
    _previous_thread_excepthook = None


def on_load(server: PluginServerInterface, old):
    global prefix,allow_permission,mcdr_lang,_timer,ai_dict,default_ai,name_to_id,data_path,skills
    _timer = None
    
    DEFAULT_CONFIG = {
        "prefix": "[GamesAI]",
        "permission": 3,
        "all_ai": {
            "<Your AI ID>":{
                "prompt": str(server.rtr("games_ai.system_message.default")),
                "ai_name": "[GamesAI]",
                "base_url": "<Your API Base URL>",
                "ai_model": "<Your AI Model>",
                "api_key": "<Your API Key>",
                "extra_body": {},
            }
        },
        "default_ai": "<Your AI ID>",
        "mineflayer_bot": {
            "enabled": False,
            "cycle_interval": 15.0,
            "websocket": {
                "url": "ws://127.0.0.1:8080",
                "reconnect_interval": 10,
                "timeout": 60,
                # Retry gap used only until the first successful connection, so the bot does
                # not wait a whole reconnect_interval just because node is still booting.
                "first_connect_interval": 0.5
            },
            "bot": {
                "username": "<Your Minecraft Bot Username>",
                "password": "<Your Minecraft Bot Password>",
                "auth": "microsoft"
            }
        }
    }
    
    server.register_help_message(prefix="!!gamesai",message=server.rtr("games_ai.mcdr_help_message.gamesai_help"))
    server.register_help_message(prefix="!!ask <content>",message=server.rtr("games_ai.mcdr_help_message.gamesai_ask"))

    config = server.load_config_simple(
        file_name='config.json',
        default_config=DEFAULT_CONFIG,
        in_data_folder=True
    )

    _apply_config(server, config)
    setup_openai_logging(server.logger, level=logging.INFO)

    # Must run after the config is applied (this logs with `prefix`, which _apply_config
    # sets) and before any new bot controller starts, so a thread left over from a previous
    # plugin instance can never act alongside the new one. The exception hook goes first so
    # an abort landing in the old instance's thread is logged, not printed as a traceback.
    _install_thread_excepthook(server)
    _abort_leftover_bot_threads(server)

    server.register_help_message(prefix="!!data",message=server.rtr("games_ai.mcdr_help_message.data"),permission=allow_permission)

    server.logger.info(f'{prefix}{server.rtr("games_ai.load_message.server_info")}')
    server.say(f'{prefix}{server.rtr("games_ai.load_message.client_info",v=PLUGIN_METADATA.get("version"))}')

    data_path = os.path.join(server.get_data_folder(), "database", "public_database.db")
    data_dir = os.path.dirname(data_path)
    if not os.path.exists(data_dir):
        os.makedirs(data_dir, exist_ok=True)
        server.logger.info(f"{server.rtr("games_ai.load_message.server_create_data_dir")}{data_dir}")

    tools_path = os.path.join(server.get_data_folder(), "tools", "tools.py")
    tools_dir = os.path.dirname(tools_path)
    if not os.path.exists(tools_dir):
        os.makedirs(tools_dir, exist_ok=True)
    if not os.path.exists(tools_path):
        with open(tools_path, mode='w', encoding='utf-8') as f:
            f.write(
'''from mcdreforged.command.command_source import CommandSource
from games_ai.games_ai_tool import register_tool

@register_tool(description="My Custom Tool")
def my_custom_tool(source: CommandSource, ai_prefix: str):
    return "Tool execution completed"
''')
        server.logger.info(f"{server.rtr("games_ai.load_message.server_create_data_dir")}{tools_path}")

    skills_path = os.path.join(server.get_data_folder(), "skills", "skills.json")
    skills_dir = os.path.dirname(skills_path)
    if not os.path.exists(skills_dir):
        os.makedirs(skills_dir, exist_ok=True)
    if not os.path.exists(skills_path):
        with open(skills_path, mode='w', encoding='utf-8') as f:
            f.write("[{}]")
        server.logger.info(f"{server.rtr("games_ai.load_message.server_create_data_dir")}{skills_path}")

    with open(skills_path, mode="r", encoding="utf-8") as f:
        content = f.read()
        skills = json.loads(content)

    mineflayer_path = os.path.join(server.get_data_folder(), "mineflayer", "init.js")
    mineflayer_dir = os.path.dirname(mineflayer_path)
    mineflayer_package_json_path = os.path.join(server.get_data_folder(), "mineflayer", "package.json")
    if not os.path.exists(mineflayer_dir):
        os.makedirs(mineflayer_dir, exist_ok=True)
    if not os.path.exists(mineflayer_path) or hashlib.md5(open(mineflayer_path, "rb").read()).hexdigest() != get_default_init_hash():
        write_default_init(mineflayer_path)
    if not os.path.exists(mineflayer_package_json_path):
        write_package_json(mineflayer_package_json_path)

    plugin_config.data_path = data_path
    plugin_config.tools_path = tools_path
    plugin_config.skills_path = skills_path
    plugin_config.builtin_skills_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")
    plugin_config.mineflayer_init_js_path = mineflayer_path
    plugin_config.skills_description = skills

    # Written only after the paths above are applied: it derives its target directory from
    # plugin_config.mineflayer_init_js_path, whose class default is a relative path.
    _write_mineflayer_config(server, config)

    load_external_tools(log=server.logger.info)

    mineflayer_cfg = config.get("mineflayer_bot", {})
    if mineflayer_cfg.get("enabled", False):
        _run_mineflayer_bot(server, mineflayer_cfg, mineflayer_path)

    register_commands(server, config)

    # Startup + 24h loop: checks plugin updates and refreshes the remote
    # context-window table (non-blocking, silently falls back to the bundled one).
    threading.Thread(target=cyclic_check_updates, daemon=True, args=(server,),
                     name="games_ai@update_loop").start()


def register_commands(server: PluginServerInterface, config: dict):
    builder = SimpleCommandBuilder()
    data_manager = DataManager(data_path)
    config_manager = ConfigManager(config)
    helper = gamesai_help()

    builder.command('!!gamesai', helper.all_help)
    builder.command('!!gamesai help', helper.all_help)

    builder.command('!!gamesai clear',clear_history)
    builder.command('!!gamesai clearall',clear_history_all)
    
    builder.command('!!gamesai check', check_update)

    builder.command('!!gamesai debug', debug)
    builder.command('!!gamesai debug thread', debug_threads)

    builder.command('!!gamesai reload', reloader)

    builder.command('!!gamesai speedtest', speed_test)
    builder.command('!!gamesai speedtest <model>', speed_test)

    builder.command('!!gamesai config', helper.config_help)
    builder.command('!!gamesai config get', helper.config_help)
    builder.command('!!gamesai config get <key>', config_manager.get_config)
    builder.command('!!gamesai config set', helper.config_help)
    builder.command('!!gamesai config set <key>', helper.config_help)
    builder.command('!!gamesai config set <key> <value>', config_manager.set_config)

    server.register_command(
        Literal("!!ask")
            .then(GreedyText("content")
                .suggests(lambda: ["-n", "-f", "switch", "stop", "compact", "context"])
                .runs(ask_ai_dispatcher))
        .runs(helper.ask_help)
    )

    builder.command('!!data', helper.data_help)

    builder.command('!!data write', helper.data_write_help)
    builder.command('!!data write <key>', helper.data_write_help)
    builder.command('!!data write <key> <value>', data_manager.write_data)

    builder.command('!!data add', helper.data_add_help)
    builder.command('!!data add <key>', helper.data_add_help)
    builder.command('!!data add <key> <value>', data_manager.add_data)

    builder.command('!!data del', helper.data_del_help)
    builder.command('!!data del <key>', data_manager.del_data)

    builder.command('!!data read', helper.data_read_help)
    builder.command('!!data read <key>', data_manager.read_data)

    builder.command('!!data list', data_manager.read_data_list)
    builder.command('!!data list keys', data_manager.read_all_keys)

    builder.command('!!aibot', helper.aibot_help)
    builder.command('!!aibot join', aibot_join)
    builder.command('!!aibot leave', aibot_leave)
    builder.command('!!aibot set', helper.aibot_help)
    builder.command('!!aibot set <key>', helper.aibot_help)
    builder.command('!!aibot set <key> <value>', config_manager.aibot_config)

    builder.arg('model', Text)
    builder.arg('content',GreedyText)

    builder.arg('key', Text)
    builder.arg('value', GreedyText)

    builder.register(server)


def on_server_startup(server: PluginServerInterface):
    server.say(f'{prefix}{server.rtr("games_ai.load_message.client_info", v=PLUGIN_METADATA.get('version'))}')


def _disable_mineflayer_and_reload(server: PluginServerInterface):
    config_path = os.path.join(os.path.dirname(os.path.dirname(plugin_config.skills_path)), "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    config.setdefault("mineflayer_bot", {})["enabled"] = False
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    server.execute_command("!!gamesai reload")


def _get_minecraft_server_address() -> tuple[str, int]:
    host = "127.0.0.1"
    port = 25565
    for candidate in ("server.properties", "server/server.properties"):
        if os.path.isfile(candidate):
            with open(candidate, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("server-ip="):
                        v = line.split("=", 1)[1].strip()
                        if v:
                            host = v
                    elif line.startswith("server-port="):
                        try:
                            port = int(line.split("=", 1)[1].strip())
                        except ValueError:
                            pass
            break
    return host, port


def _write_mineflayer_config(server: PluginServerInterface, config: dict):
    mineflayer_dir = os.path.dirname(plugin_config.mineflayer_init_js_path)
    mineflayer_config_path = os.path.join(mineflayer_dir, "config.json")
    cfg = dict(config.get("mineflayer_bot", {}))
    host, port = _get_minecraft_server_address()
    cfg.setdefault("bot", {})
    cfg["bot"]["server_host"] = host
    cfg["bot"]["server_port"] = port
    os.makedirs(mineflayer_dir, exist_ok=True)      # never depend on the caller's cwd
    with open(mineflayer_config_path, mode='w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


@register_tool(
    description="Start the Mineflayer bot so that it joins the Minecraft server. Does nothing when the bot is already running.",
    perm=get_plugin_config_perm,
)
def run_mineflayer_bot(source: CommandSource, ai_prefix: str):
    server = source.get_server()
    if source.get_permission_level() < plugin_config.allow_permission:
        return "Permission denied: this tool requires a higher permission level than the requesting player has"
    if is_node_running():
        return f"The Mineflayer bot is already running ({plugin_config.bot_username})"
    source.reply(f"{ai_prefix}{server.rtr('games_ai.tools.bot_start')}")
    _toggle_aibot(server, True)
    return "Starting the Mineflayer bot..."


@register_tool(
    description="Stop the Mineflayer bot so that it leaves the Minecraft server.",
    perm=get_plugin_config_perm,
)
@register_bot_tool()
def stop_mineflayer_bot(source: CommandSource, ai_prefix: str):
    server = source.get_server()
    if source.get_permission_level() < plugin_config.allow_permission:
        return "Permission denied: this tool requires a higher permission level than the requesting player has"
    if not is_node_running():
        return "The Mineflayer bot is not running"
    source.reply(f"{ai_prefix}{server.rtr('games_ai.tools.bot_stop')}")
    _toggle_aibot(server, False)
    return "Stopping the Mineflayer bot..."

def _run_mineflayer_bot(server: ServerInterface, bot_config: dict, mineflayer_init_js_path: str):
    if not server.is_server_running():
        global _mineflayer_wait_thread
        if _mineflayer_wait_thread is not None and _mineflayer_wait_thread.is_alive():
            server.logger.info(f"{prefix} Minecraft server is not running, already waiting for it to start...")
            return
        server.logger.info(f"{prefix} Minecraft server is not running, Mineflayer bot will launch automatically after the server starts")
        _mineflayer_wait_thread = _wait_server_then_launch(server, bot_config, mineflayer_init_js_path)
        return
    _launch_mineflayer_bot(server, bot_config, mineflayer_init_js_path)


@new_thread("games_ai@mineflayer_wait_server")
def _wait_server_then_launch(server: ServerInterface, bot_config: dict, mineflayer_init_js_path: str):
    while not server.is_server_running():
        if _mineflayer_pending_abort.is_set():
            server.logger.info(f"{prefix} Plugin unloaded, Mineflayer bot launch cancelled")
            return
        time.sleep(2)
    if _mineflayer_pending_abort.is_set():
        server.logger.info(f"{prefix} Plugin unloaded, Mineflayer bot launch cancelled")
        return
    server.logger.info(f"{prefix} Minecraft server started, launching Mineflayer bot...")
    _launch_mineflayer_bot(server, bot_config, mineflayer_init_js_path)


def _wait_for_bot_teardown(timeout: float = _BOT_TEARDOWN_WAIT) -> bool:
    """
    Wait until the previous bot teardown has released its resources.

    The unload path finishes the node shutdown on a detached thread, so a launch that starts
    right afterwards (a reload immediately after an unload, or two reloads in a row) may still
    find the old process holding the WebSocket port. Waiting here is what keeps that from
    being misread as a foreign program.

    :return: True when no teardown is running any more.
    """
    return _bot_teardown_event.wait(timeout)


def _launch_mineflayer_bot(server: ServerInterface, bot_config: dict, mineflayer_init_js_path: str):
    node_path = shutil.which("node")
    if not node_path:
        server.logger.warning(f"{prefix} Mineflayer bot is enabled but Node.js was not found. Disabling and reloading...")
        _disable_mineflayer_and_reload(server)
    else:
        ws_cfg = bot_config.get("websocket", {})
        ws_url = ws_cfg.get("url", "ws://127.0.0.1:8080")
        try:
            import socket as _socket
            m = re.match(r'^ws://([^/:]+)(?::(\d+))?', ws_url)
            host = m.group(1) if m else "127.0.0.1"
            port = int(m.group(2)) if m and m.group(2) else 8080
            # A previous teardown may still be stopping the old node process; its port is not
            # a foreign program's, so wait for it before deciding anything.
            if not _wait_for_bot_teardown():
                server.logger.warning(
                    f"{prefix} The previous bot teardown is still running after "
                    f"{_BOT_TEARDOWN_WAIT:.1f}s, checking the WebSocket port anyway"
                )
            with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.bind((host, port))
        except OSError:
            server.logger.warning(
                f"{prefix} WebSocket port {port} is already in use! "
                f"Please change mineflayer_bot.websocket.url to a different port and reload."
            )
            _disable_mineflayer_and_reload(server)
            return
        try:
            version_output = subprocess.check_output([node_path, "--version"], text=True, timeout=5).strip()
            if version_output.startswith("v"):
                version_output = version_output[1:]
            major = int(version_output.split(".")[0])
            if major < 18:
                server.logger.warning(
                    f"{prefix} Mineflayer requires Node.js >= 18, but found v{version_output}. "
                    f"Disabling and reloading..."
                )
                _disable_mineflayer_and_reload(server)
            else:
                try:
                    run_node(mineflayer_init_js_path, logger=server.logger)
                except (RuntimeError, FileNotFoundError) as e:
                    server.logger.error(f"{prefix} Failed to launch Mineflayer bot: {e}")
                    return
                server.logger.info(f"{prefix} Mineflayer JS bot launched (Node.js v{version_output})")
                ws_reconnect = ws_cfg.get("reconnect_interval", 10)
                ws_timeout = ws_cfg.get("timeout", 60)
                ws_first = ws_cfg.get("first_connect_interval", 0.5)
                try:
                    client = start_mineflayer_client(ws_url, server.logger, ws_reconnect, ws_timeout,
                                                     first_connect_interval=ws_first)
                    websocket_connections["mineflayer"] = client
                    server.logger.info(f"{prefix} Mineflayer WS client started (Node.js v{version_output}), connecting to {ws_url}")

                    default_ai_info = ai_dict.get(default_ai, None)
                    if default_ai_info is not None:
                        global _autonomous_controller
                        _autonomous_controller = AutonomousBotController(
                            ws_client=client,
                            model=default_ai_info.get("ai_model", ""),
                            base_url=default_ai_info.get("base_url", ""),
                            api_key=default_ai_info.get("api_key", ""),
                            system_prompt=str(server.rtr("games_ai.autonomous_bot.default_system_prompt")),
                            chat_prompt=default_ai_info.get("prompt", ""),
                            extra_body=default_ai_info.get("extra_body", {}),
                            cycle_interval=bot_config.get("cycle_interval", 15.0),
                            bot_username=plugin_config.bot_username,
                            server=server,
                            logger=server.logger,
                            tr=lambda key, **kw: str(server.rtr(key, **kw)),
                        )
                        _autonomous_controller.start()
                        set_bot_controller(_autonomous_controller)
                        server.logger.info(f"{prefix} AutonomousBot controller started")
                    else:
                        server.logger.warning(f"{prefix} No default AI configured, AutonomousBot controller skipped")
                except Exception as e:
                    server.logger.warning(f"{prefix} Failed to start Mineflayer WS client: {e}")
        except (subprocess.TimeoutExpired, ValueError, OSError) as e:
            server.logger.warning(f"{prefix} Failed to detect Node.js version: {e}. Skipping WS client startup.")


def _apply_config(server: PluginServerInterface, config: dict):
    global prefix, allow_permission, mcdr_lang, ai_dict, default_ai, name_to_id

    prefix = config.get('prefix', '[GamesAI]')
    allow_permission = config.get('permission', 3)

    plugin_config.prefix = prefix
    plugin_config.allow_permission = allow_permission
    
    prompt_dir = os.path.join(os.path.dirname(os.path.dirname(plugin_config.skills_path)), "prompt")
    if not os.path.exists(prompt_dir):
        os.makedirs(prompt_dir, exist_ok=True)

    ai_dict = {}
    all_ai: dict = config.get('all_ai', {})
    for ai_id, ai_config in all_ai.items():
        if not isinstance(ai_config, dict):
            continue
        raw_prompt: str = ai_config.get("prompt", str(server.rtr("games_ai.system_message.default")))
        if raw_prompt.startswith("> "):
            prompt_file_path = raw_prompt[2:].strip()
            prompt_full_path = os.path.join(prompt_dir, prompt_file_path)
            try:
                with open(prompt_full_path, 'r', encoding='utf-8') as f:
                    raw_prompt = f.read()
                server.logger.info(f"{prefix} Loaded prompt from file: {prompt_full_path}")
            except FileNotFoundError:
                server.logger.warning(f"{prefix} Prompt file not found: {prompt_full_path}, using default prompt")
                raw_prompt = str(server.rtr("games_ai.system_message.default"))
        context_window = ai_config.get("context_window")
        try:
            context_window = int(context_window) if context_window is not None else None
        except (TypeError, ValueError):
            server.logger.warning(f"{prefix} Invalid context_window for AI '{ai_id}', ignoring it")
            context_window = None
        ai_dict[ai_id] = {
            "prompt": raw_prompt,
            "ai_name": ai_config.get("ai_name", "[GamesAI]"),
            "base_url": ai_config.get("base_url", ""),
            "ai_model": ai_config.get("ai_model", ""),
            "api_key": ai_config.get("api_key", ""),
            "extra_body": ai_config.get("extra_body", {}),
            "context_window": context_window,
        }

    default_ai = config.get("default_ai", list(ai_dict.keys())[0] if ai_dict else "")

    plugin_config.all_ai = ai_dict
    plugin_config.default_ai = default_ai

    name_to_id = {}
    for aid, info in ai_dict.items():
        name = info.get("ai_name")
        name_to_id[name] = aid

    mcdr_lang = str(server.rtr("games_ai.system_message.lang", lang=server.get_mcdr_language()))

    bot_cfg = config.get("mineflayer_bot", {}).get("bot", {})
    plugin_config.bot_username = bot_cfg.get("username", "Bot")

def _stop_bot_stack(server: PluginServerInterface, logger=None) -> list[str]:
    """
    Stop the autonomous bot controller, the WebSocket client and the Node process.

    Used by both plugin unload and ``!!gamesai reload``. Every step is isolated on
    purpose: a stuck or failing controller must never keep the WebSocket client, the Node
    process (the bot in the game and its WebSocket port) alive. The controller reference is
    dropped *before* it is stopped, so a failing stop cannot leave a stale controller
    registered for the next round either.

    The steps are ordered by what the bot still needs, and every wait is bounded:

    1. the controller goes first (it is the only step that talks to the WebSocket server),
    2. then the client is closed, so no in-flight command outlives the socket,
    3. the Node process is detached from :mod:`games_ai.mineflayer` and hard-killed. It may
       not be *closed* gracefully: the Python side cannot know that node is idle, and the
       process is a service process that is about to be replaced.

    The whole thing is a plain-Python (`threading`/`subprocess`) function so it stays safe to
    run on a detached thread after the plugin has been unloaded — that is how
    :func:`on_unload` uses it.

    :param logger: optional logger override; used because the detached unload thread may no
                   longer read the module global (which a new plugin instance overwrites).
    :return: names of the steps that failed (empty on a clean stop).
    """
    global _autonomous_controller

    log = logger if logger is not None else (server.logger if server is not None else None)
    failed: list[str] = []

    def step(name: str, action):
        try:
            action()
        except Exception as e:
            failed.append(name)
            if log is not None:
                log.exception(f"{prefix} Cleanup step '{name}' failed: {e}")

    controller = _autonomous_controller
    _autonomous_controller = None
    # force=True + a short grace: an idle loop leaves at once, and a busy one gets an abort
    # injected instead of blocking the unload for the whole cooperative timeout
    step("stop the autonomous bot controller",
         lambda: controller.stop(timeout=_BOT_STOP_GRACE, force=True) if controller is not None else None)
    step("clear the bot controller registry", lambda: set_bot_controller(None))
    step("stop the websocket client", stop_mineflayer_client)
    step("clear the websocket registry", websocket_connections.clear)
    # Detach first (the module global must be free for a replacement instance), then kill the
    # detached object: nothing here reaches back into this module's state.
    step("kill the mineflayer process",
         lambda: stop_mineflayer_process(detach_mineflayer_process()))
    return failed


def _run_bot_teardown(server: PluginServerInterface | None, logger) -> list[str]:
    """
    Run :func:`_stop_bot_stack` and publish the result on :data:`_bot_teardown_event`.

    ``server``/``logger`` are passed as arguments on purpose (not read from the module
    globals): this may run after the plugin was unloaded, and by then a replacement plugin
    instance owns those global names. ``_bot_teardown_lock`` serializes teardowns, so a
    reload that arrives while a detached unload is still stopping the bot waits for it (and
    then finds nothing left to do) instead of racing it.
    """
    with _bot_teardown_lock:
        try:
            failed = _stop_bot_stack(server, logger=logger)
        finally:
            _bot_teardown_event.set()
    return failed


def _teardown_bot_async(server: PluginServerInterface) -> threading.Thread:
    """
    Run the bot teardown on a detached thread (unload path).

    The thread only uses plain Python: the controller object, the WebSocket client, a
    ``Popen`` and the logger object — all captured before the plugin was unloaded, and bound
    as arguments so nothing has to be read from this module's globals afterwards.
    """
    _bot_teardown_event.clear()
    thread = threading.Thread(
        target=_run_bot_teardown,
        args=(server, getattr(server, "logger", None)),
        daemon=True,
        name="games_ai@bot_teardown",
    )
    thread.start()
    return thread


def on_unload(server: PluginServerInterface):
    """
    Tear the plugin down without waiting for the slow half of the bot shutdown.

    The synchronous part is only what the next plugin instance would race with, plus a short
    grace on the teardown itself: one hard-killed node process costs about a second, so the
    ordinary case really is finished before MCDR considers the plugin unloaded. A slower
    shutdown (a busy controller, a hanging ``terminate``) is left to the detached thread
    instead of blocking the reload/unload for it; that thread only touches plain Python
    objects captured here, never this module's globals, because a new plugin instance may
    already be running by then.

    Every cleanup is its own guarded step (see :func:`_stop_bot_stack`), and the surviving
    threads are reported honestly instead of claiming a clean shutdown.
    """
    global _mineflayer_wait_thread

    _mineflayer_pending_abort.set()             # cancels the pending "wait for server" thread
    _mineflayer_wait_thread = None
    _restore_thread_excepthook()
    if _timer is not None:
        try:
            _timer.cancel()
        except Exception as e:
            server.logger.exception(f"{prefix} Failed to cancel the 24h update timer: {e}")

    teardown = _teardown_bot_async(server)
    if not _bot_teardown_event.wait(_BOT_UNLOAD_GRACE):
        server.logger.info(
            f"{prefix} Bot teardown is still running in the background "
            f"(waited {_BOT_UNLOAD_GRACE:.1f}s); it will finish on its own"
        )

    still_alive = sorted(t.name for t in threading.enumerate() if t.name in _PLUGIN_THREAD_NAMES)
    if still_alive:
        server.logger.warning(
            f"{prefix} Threads still alive after unload: {', '.join(still_alive)} "
            f"(daemon threads; an in-flight round finishes its current API call first, then exits)"
        )
    if teardown.is_alive():
        server.logger.info(f"{prefix} Mineflayer bot stop is delegated to the background teardown thread")
    else:
        server.logger.info(f"{prefix} Mineflayer bot stopped successfully!")
    server.logger.info(f"{prefix} Mineflayer bot process has been terminated successfully!")
    server.logger.info(f"{prefix}{server.rtr("games_ai.unload_message.server_info")}")
    for plugin_id in list(REGISTER_PLUGIN_LIST.keys()):
        try:
            server.logger.info(f"{prefix} Unloading registered extension plugin '{plugin_id}'")
            result = server.unload_plugin(plugin_id)
            if result is None:
                server.logger.warning(f"{prefix} Registered plugin '{plugin_id}' not found, removed from unload list")
                REGISTER_PLUGIN_LIST.pop(plugin_id, None)
            elif not result:
                server.logger.warning(f"{prefix} Failed to unload registered plugin '{plugin_id}'")
        except Exception as e:
            server.logger.exception(f"{prefix} Error while unloading registered plugin '{plugin_id}': {e}")
    REGISTER_PLUGIN_LIST.clear()
    if unload_status_code == 0:
        server.say(f'{prefix}Bye!')
    elif unload_status_code == 1:
        server.say(f'{prefix}{server.rtr("games_ai.unload_message.after_update_restart_msg")}')

class gamesai_help:
    @staticmethod
    def ask_help(source: CommandSource):
        server = source.get_server()
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.greeting", v=PLUGIN_METADATA.get("version")))
        send_help(source, prefix, command="!!ask <content>", command_help_key="games_ai.gamesai_help_message.ask_help")
        send_help(source, prefix, command="!!ask -n <content>", command_help_key="games_ai.gamesai_help_message.ask_no_history_help")
        send_help(source, prefix, command="!!ask -f <content>", command_help_key="games_ai.gamesai_help_message.ask_force_help")
        send_help(source, prefix, command="!!ask switch <model>", command_help_key="games_ai.gamesai_help_message.switch_help")
        send_help(source, prefix, command="!!ask compact", command_help_key="games_ai.gamesai_help_message.ask_compact_help")
        send_help(source, prefix, command="!!ask context <player>", command_help_key="games_ai.gamesai_help_message.ask_context_help")
        send_help(source, prefix, command="!!ask context --all", command_help_key="games_ai.gamesai_help_message.ask_context_all_help")
        send_help(source, prefix, command="!!ask stop", command_help_key="games_ai.gamesai_help_message.ask_stop_help")
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.all_ai_model") + str(list(ai_dict.keys())))

    @staticmethod
    def switch_help(source: CommandSource):
        server = source.get_server()
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.greeting", v=PLUGIN_METADATA.get("version")))
        send_help(source, prefix, command="!!ask switch <model>", command_help_key="games_ai.gamesai_help_message.switch_help")

    @staticmethod
    def data_help(source: CommandSource):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission=allow_permission))
            return
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.greeting", v=PLUGIN_METADATA.get("version")))
        send_help(source, prefix, command="!!data write <key> <value>", command_help_key="games_ai.gamesai_help_message.data_write_help")
        send_help(source, prefix, command="!!data add <key> <value>", command_help_key="games_ai.gamesai_help_message.data_add_help")
        send_help(source, prefix, command="!!data del <key>", command_help_key="games_ai.gamesai_help_message.data_del_help")
        send_help(source, prefix, command="!!data read <key>", command_help_key="games_ai.gamesai_help_message.data_read_help")
        send_help(source, prefix, command="!!data list", command_help_key="games_ai.gamesai_help_message.data_list_help")
        send_help(source, prefix, command="!!data list keys", command_help_key="games_ai.gamesai_help_message.data_keys_help")

    @staticmethod
    def data_write_help(source: CommandSource):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission=allow_permission))
            return
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.greeting", v=PLUGIN_METADATA.get("version")))
        send_help(source, prefix, command="!!data write <key> <value>", command_help_key="games_ai.gamesai_help_message.data_write_help")

    @staticmethod
    def data_del_help(source: CommandSource):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission=allow_permission))
            return
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.greeting", v=PLUGIN_METADATA.get("version")))
        send_help(source, prefix, command="!!data del <key>", command_help_key="games_ai.gamesai_help_message.data_del_help")

    @staticmethod
    def data_read_help(source: CommandSource):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission=allow_permission))
            return
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.greeting", v=PLUGIN_METADATA.get("version")))
        send_help(source, prefix, command="!!data read <key>", command_help_key="games_ai.gamesai_help_message.data_read_help")

    @staticmethod
    def data_add_help(source: CommandSource):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission=allow_permission))
            return
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.greeting", v=PLUGIN_METADATA.get("version")))
        send_help(source, prefix, command="!!data add <key> <value>", command_help_key="games_ai.gamesai_help_message.data_add_help")


    @staticmethod
    def config_help(source: CommandSource):
        server = source.get_server()
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.greeting", v=PLUGIN_METADATA.get("version")))
        if source.get_permission_level() < allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission=allow_permission))
            return
        send_help(source, prefix, command='!!gamesai config get <key>', command_help_key="games_ai.gamesai_help_message.config_help_get")
        send_help(source, prefix, command='!!gamesai config set <key> <value>', command_help_key="games_ai.gamesai_help_message.config_help_set")


    @staticmethod
    def aibot_help(source: CommandSource):
        server = source.get_server()
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.greeting", v=PLUGIN_METADATA.get("version")))
        if source.get_permission_level() < allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission=allow_permission))
            return
        send_help(source, prefix, command="!!aibot join", command_help_key="games_ai.gamesai_help_message.aibot_join_help")
        send_help(source, prefix, command="!!aibot leave", command_help_key="games_ai.gamesai_help_message.aibot_leave_help")
        send_help(source, prefix, command="!!aibot set <key> <value>", command_help_key="games_ai.gamesai_help_message.aibot_set_help")


    @staticmethod
    def all_help(source: CommandSource):
        server = source.get_server()
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.greeting", v=PLUGIN_METADATA.get("version")))
        send_help(source, prefix, command="!!ask <content>", command_help_key="games_ai.gamesai_help_message.ask_help")
        send_help(source, prefix, command="!!gamesai clear", command_help_key="games_ai.gamesai_help_message.clear_help")
        if source.get_permission_level() >= allow_permission:
            send_help(source, prefix, command="!!gamesai clearall", command_help_key="games_ai.gamesai_help_message.clearall_help")
            send_help(source, prefix, command="!!gamesai check", command_help_key="games_ai.gamesai_help_message.check_update_help")
            send_help(source, prefix, command='!!gamesai config',command_help_key="games_ai.gamesai_help_message.config_help")
            send_help(source, prefix, command="!!data", command_help_key="games_ai.gamesai_help_message.data_help")
            send_help(source, prefix, command="!!aibot <join | leave>", command_help_key="games_ai.gamesai_help_message.aibot_help")


def send_help(source: CommandSource, prefix: str, message: str|None = None, command: str|None = None, command_help_key: str|None = None):
    server = source.get_server()
    if command and message is None:
        source.reply(RTextList(
            prefix,
            server.rtr("games_ai.gamesai_help_message.help_prefix"),
            RText(command, RColor.gray).c(RAction.suggest_command, command[:command.find(' <')] + ' ' if ' <' in command else command + ' '),
            server.rtr(command_help_key)
        ))
        return
    else:
        source.reply(RTextList(
            prefix,
            message,
        ))
        return


def _chat_log(server: ServerInterface, msg: str) -> None:
    """Debug-mode logging: INFO level when !!gamesai debug is on, DEBUG otherwise."""
    if plugin_config.debug_mode:
        server.logger.info(f"[GamesAI]{msg}")
    else:
        server.logger.debug(f"[GamesAI]{msg}")


def ask_ai_dispatcher(source: CommandSource, context: dict):
    content: str = context.get("content", "").strip()
    if content.startswith("-n ") or content.startswith("--no-history "):
        ask_ai(source, {"content": content.split(" ", 1)[1]}, no_history=True)
    elif content.startswith("-f ") or content.startswith("--forced "):
        ask_ai(source, {"content": content.split(" ", 1)[1]}, forced=True)
    elif content == "switch":
        gamesai_help.switch_help(source)
    elif content.startswith("switch ") and len(content.split()) == 2:
        switch_model(source, {"model": content.split(None, 1)[1]})
    elif content == "stop":
        ask_stop(source, {})
    elif content == "compact":
        username = get_username(source)
        user_chat_param = all_chat_param.get(username)
        if user_chat_param is None:
            source.reply(f"{prefix}{source.get_server().rtr('games_ai.user_message.compact_no_history')}")
            return
        # deferred like the model-switch hand-off: the summarizing request is sent by the
        # next round, so this command returns at once instead of blocking the server thread
        result = user_chat_param.compact_history()
        key = {
            "scheduled": "games_ai.user_message.compact_success",
            "empty": "games_ai.user_message.compact_no_history",
            "running": "games_ai.user_message.compact_failed_running",
        }.get(result, "games_ai.user_message.compact_failed_running")
        source.reply(f"{prefix}{source.get_server().rtr(key)}")
    elif content == "context --all":
        ask_context_server(source)
    elif content != "" and content.split(None, 1)[0] == "context":
        # exactly the word "context", optionally followed by one player name; anything else
        # (e.g. "contextual") is an ordinary question and belongs to the AI
        rest = content.split(None, 1)[1:]
        ask_context(source, rest[0] if rest else None)
    else:
        ask_ai(source, context)


def ask_context(source: CommandSource, player: str | None = None):
    """
    ``!!ask context [player]`` — show how full one conversation is (own by default).

    Read-only: nothing is created and no round is started, so asking about a player who has
    never chatted simply reports that there is nothing to show. The card is a handful of chat
    lines with the details on hover (:meth:`ChatParam.context_view`), because the numbers
    alone (window, usage, distance to the next compression) do not fit next to them.
    """
    server = source.get_server()
    username = get_username(source)
    target = player or username
    user_chat_param = all_chat_param.get(target)
    if user_chat_param is None:
        source.reply(f"{prefix}{server.rtr('games_ai.context_view.missing', player=target)}")
        return
    lines = user_chat_param.context_view()
    source.reply(RTextList(prefix, RText(
        server.rtr("games_ai.context_view.header", player=target), RColor.gold)))
    for index, (line, hover) in enumerate(lines):
        source.reply(RText(f"{prefix}{line}", RColor.white if index == 0 else RColor.gray).h(hover))
    source.reply(f"{prefix}{server.rtr('games_ai.context_view.hover_hint')}")


def aggregate_context_usage() -> tuple[list[dict], dict, list[str]]:
    """
    Sum the context usage of every chatted player, grouped by the model they are on.

    Reads :meth:`ChatParam.context_usage` for every entry of ``all_chat_param`` and adds the
    plain numbers up, so nothing here can block on a running round. Two groups of numbers are
    kept apart on purpose:

    * ``estimate`` / ``round_*`` — what is *currently* held or was spent in the last round.
      They shrink when a history is compressed or ``!!ask clear`` drops an object.
    * ``total_*`` — spent since the plugin was loaded, accumulated inside ``ChatParam`` and
      never reset, so a compression does not erase the record of what it summarized away.

    :return: ``(models, totals, broken)`` — one dict per model that has any non-zero usage,
             sorted by the currently held context (then by lifetime spend); one dict with the
             sums over all models; and the names whose usage could not be read.
    """
    groups: dict[str, dict] = {}
    broken: list[str] = []
    totals = {
        "players": 0, "active_players": 0, "estimate": 0, "round_prompt": 0,
        "round_max_total": 0, "total_prompt": 0, "total_completion": 0,
        "total_cached": 0, "total_reasoning": 0, "models": 0,
    }
    for username, chat_param in list(all_chat_param.items()):
        if chat_param is None:
            continue
        try:
            usage = chat_param.context_usage()
        except Exception:
            # one broken conversation (e.g. an AI config removed by a reload) must not hide
            # the whole server-wide view
            broken.append(username)
            continue
        key = usage.get("model") or usage.get("label") or "?"
        group = groups.get(key)
        if group is None:
            group = groups[key] = {
                "model": key, "label": usage.get("label") or key, "window": 0, "players": 0,
                "estimate": 0, "round_prompt": 0, "round_max_total": 0,
                "total_prompt": 0, "total_completion": 0, "total_cached": 0,
                "total_reasoning": 0,
            }
        group["players"] += 1
        # the smallest window of the group is the honest denominator: two players on the same
        # model id may still have different windows (per-AI config override)
        window = int(usage.get("window") or 0)
        if window and (not group["window"] or window < group["window"]):
            group["window"] = window
        for field in ("estimate", "round_prompt", "round_max_total",
                      "total_prompt", "total_completion", "total_cached", "total_reasoning"):
            group[field] += int(usage.get(field) or 0)
            totals[field] += int(usage.get(field) or 0)
        totals["players"] += 1
        # "active" = holds context or has spent something; every other tracked object is a
        # player who merely typed !!ask once and whose history was compressed/cleared away
        if any(int(usage.get(f) or 0) for f in
               ("estimate", "total_prompt", "total_completion")):
            totals["active_players"] += 1
            group["active"] = group.get("active", 0) + 1

    for group in groups.values():
        group.setdefault("active", 0)

    models = [g for g in groups.values() if any(
        g[f] for f in ("estimate", "round_prompt", "round_max_total",
                       "total_prompt", "total_completion")
    )]
    models.sort(key=lambda g: (-g["estimate"], -g["total_prompt"], g["label"]))
    totals["models"] = len(models)
    return models, totals, broken


def ask_context_server(source: CommandSource):
    """
    ``!!ask context --all`` — the context usage of the whole server, grouped by model.

    Numbers only (no player names): the point is the server-wide picture — which model is
    carrying how much context, how much of it is billed, and how much was served from cache.
    Hidden are the models nobody is currently using, i.e. every counter is zero.
    """
    server = source.get_server()
    models, totals, broken = aggregate_context_usage()
    if not models:
        source.reply(f"{prefix}{server.rtr('games_ai.context_all.empty')}")
        return
    source.reply(RTextList(prefix, RText(
        server.rtr("games_ai.context_all.header", players=totals["active_players"],
                   models=totals["models"]), RColor.gold)))
    for group in models:
        window = max(int(group["window"] or 0), 1)
        share = round(100 * group["estimate"] / window)
        cached_rate = (f"{math.floor(1000 * min(group['total_cached'], group['total_prompt'])
                                  / group['total_prompt']) / 10:.1f}%"
                       if group["total_prompt"] else "—")
        line = str(server.rtr(
            "games_ai.context_all.line",
            model=group["label"], players=group["players"], window=f"{window:,}",
            estimate=f"{group['estimate']:,}", share=share,
            round_prompt=f"{group['round_prompt']:,}",
            round_max=f"{group['round_max_total']:,}",
        ))
        hover = str(server.rtr(
            "games_ai.context_all.hover",
            prompt=f"{group['total_prompt']:,}", completion=f"{group['total_completion']:,}",
            total=f"{group['total_prompt'] + group['total_completion']:,}",
            cached=f"{group['total_cached']:,}", cached_percent=cached_rate,
            reasoning=f"{group['total_reasoning']:,}",
        ))
        source.reply(RText(f"{prefix}{line}", RColor.gray).h(hover))
    held = f"{totals['estimate']:,}"
    source.reply(f"{prefix}{server.rtr('games_ai.context_all.total', estimate=held)}")
    source.reply(f"{prefix}{server.rtr('games_ai.context_all.hover_hint')}")


@new_thread("games_ai@switch_model")
def switch_model(source: CommandSource, context: dict):
    server = source.get_server()

    username = get_username(source)

    user_input = context.get("model", default_ai)
    model_id = name_to_id.get(user_input, user_input)
    ai_info = ai_dict.get(model_id)
    may_user_ai = []
    if ai_info is None:
        for ai_id,ai_config in ai_dict.items():
            name = ai_config.get("ai_name", "")
            if user_input.lower() in name.lower() or user_input.lower() in ai_id.lower():
                may_user_ai.append(ai_id)
        if len(may_user_ai) == 1:
            model_id = may_user_ai[0]
        elif len(may_user_ai) > 1:
            source.reply(f"{prefix}{server.rtr("games_ai.user_message.model_more")}{may_user_ai}")
            return
        else:
            source.reply(f"{prefix}{server.rtr("games_ai.user_message.model_error")}{list(ai_dict.keys())}")
            return

    ai_name = ai_dict.get(model_id, {}).get("ai_name", model_id)

    if username in all_chat_param and all_chat_param.get(username) is not None:
        # v0.7.1 policy: summary hand-off (option B1 of issue #20). The old model
        # summarizes the conversation right before the next request, so the switch itself
        # never blocks and costs nothing until the player asks something.
        result = all_chat_param[username].change_model(source, model_id)
    else:
        all_chat_param[username] = ChatParam(server, model_id=model_id)
        result = "empty"

    _chat_log(server, f"[switch] {username} -> model_id={model_id}, hand-off={result}")

    if result == "same":
        source.reply(f"{prefix}{server.rtr('games_ai.user_message.switch_same_model', model=ai_name)}")
    elif result == "scheduled":
        source.reply(f"{prefix}{server.rtr('games_ai.user_message.switch_summary', model=ai_name)}")
    else:
        source.reply(f"{prefix}{server.rtr('games_ai.user_message.switch_success', model=ai_name)}")


@new_thread("games_ai@ask_ai")
def ask_ai(source: CommandSource, context: dict, no_history: bool = False, forced: bool = False):
    server = source.get_server()

    data = DataManager(data_path).ask_ai_read_data()
    username = get_username(source)
    content: str = context['content']

    user_message = f'{str(server.rtr("games_ai.user_message.username"))}{username}\n{str(server.rtr("games_ai.user_message.message"))}{content}'

    if username not in all_chat_param.keys():
        all_chat_param[username] = ChatParam(server, model_id=default_ai)
    user_chat_param = all_chat_param.get(username)
    model_id = user_chat_param.get_model_id or default_ai
    ai_prefix = ai_dict.get(model_id, {}).get("ai_name")

    if no_history:
        # stateless one-shot: no history, no context management (see NonHistoryChatParam)
        chat_param = NonHistoryChatParam(server, model_id=model_id)
        chat_param.add_to_response_list("user", user_message)
        source.reply(f"{ai_prefix}{server.rtr("games_ai.user_message.thinking")}")
        register_no_history(username, chat_param)
        try:
            chat_param.response_ai(source, data)
        finally:
            unregister_no_history(username, chat_param)
        return

    default_skills = [
        {"file": "skills_management.md", "description": str(server.rtr("games_ai.builtin_skills.skills_management"))},
        {"file": "custom_tools_management.md", "description": str(server.rtr("games_ai.builtin_skills.custom_tools_management"))},
    ]
    if is_node_running() and _autonomous_controller is not None and _autonomous_controller.is_running:
        default_skills.append({"file": "mineflayer_bot_guide.md", "description": str(server.rtr("games_ai.builtin_skills.mineflayer_bot_guide", username=plugin_config.bot_username))})

    external_skills: list[dict[str, str]] = []
    if EXTERNAL_SKILLS_LIST:
        for i in EXTERNAL_SKILLS_LIST:
            file = i.get("file")
            description = i.get("description")
            if file is None or description is None:
                continue
            external_skills.append({"file": file, "description": description})

    skills_file: str | None = None
    if content.strip().startswith("/"):
        skill_name = content.strip().split(" ")[0][1:]
        if not skill_name.endswith(".md"):
            skill_name += ".md"

        all_skill_files: list[str] = [
            f.get("file", "") for f in [*skills, *default_skills]
            if f.get("file")
        ]
        for es in external_skills:
            f = es.get("file")
            if f:
                all_skill_files.append(f)

        if skill_name in all_skill_files:
            skills_file = skill_name
            source.reply(f"{ai_prefix}{server.rtr('games_ai.user_message.skill_selected', skill=skill_name)}")
        else:
            source.reply(f"{ai_prefix}{server.rtr('games_ai.user_message.skill_not_found', skill=skill_name)}")

    if forced and not user_chat_param.get_is_stopped:
        if skills_file:
            user_chat_param.forced_add_to_response_list("system", str(server.rtr('games_ai.user_message.skill_injected', skill=skills_file)))

        user_chat_param.forced_add_to_response_list("user", user_message)
        _chat_log(server, f"[ask -f] {username} message queued (running round active)")

        source.reply(f"{ai_prefix}{server.rtr("games_ai.user_message.thinking")}")

        user_chat_param.wait_until_stop()
        if user_chat_param.get_response_queue:
            _chat_log(server, f"[ask -f] {username} round ended without consuming queue, starting supplement round")
            user_chat_param.response_ai(source, data)
        else:
            _chat_log(server, f"[ask -f] {username} queue consumed by running round")
    else:
        user_chat_param.wait_until_stop()
        
        if skills_file:
            user_chat_param.add_to_response_list("system", str(server.rtr('games_ai.user_message.skill_injected', skill=skills_file)))

        user_chat_param.add_to_response_list("user", user_message)

        source.reply(f"{ai_prefix}{server.rtr("games_ai.user_message.thinking")}")

        user_chat_param.response_ai(source, data)

def get_username(source: CommandSource) -> str:
    if source.is_player:
        return source.player
    else:
        return "Server Control Panel"


def ask_stop(source: CommandSource, context: dict):
    """
    ``!!ask stop`` — abort everything this player has in flight.

    * the running round of the player's conversation (tool calls included); the step that
      was interrupted is dropped from the history, and queued ``!!ask -f`` messages are
      discarded;
    * a running ``!!ask -n`` request (stateless: the answer is simply thrown away);
    * a task the player delegated to the autonomous Mineflayer bot.
    """
    server = source.get_server()
    username = get_username(source)
    stopped: list[str] = []

    user_chat_param = all_chat_param.get(username)
    if user_chat_param is not None and user_chat_param.request_stop():
        stopped.append("games_ai.user_message.stop_round")

    if stop_no_history(username):
        stopped.append("games_ai.user_message.stop_no_history")

    bot_controller = get_bot_controller()
    if bot_controller is not None and bot_controller.is_running and bot_controller.stop_user_task(username):
        stopped.append("games_ai.user_message.stop_bot_task")

    _chat_log(server, f"[stop] {username} stopped: {stopped or 'nothing running'}")
    if not stopped:
        source.reply(f"{prefix}{server.rtr('games_ai.user_message.stop_none')}")
        return
    for key in stopped:
        source.reply(f"{prefix}{server.rtr(key)}")

def clear_history(source: CommandSource,context: dict):
    server = source.get_server()
    username = get_username(source)
    if username in all_chat_param:
        del all_chat_param[username]
        source.reply(f'{prefix}{server.rtr("games_ai.clear_history_message.success",username=username)}')
    else:
        source.reply(f'{prefix}{server.rtr("games_ai.clear_history_message.no_history",username=username)}')

def clear_history_all(source: CommandSource,context: dict):
    server = source.get_server()
    if source.get_permission_level() < allow_permission:
        source.reply(f'{prefix}{server.rtr("games_ai.no_permission",permission=allow_permission)}')
    else:
        count = len(all_chat_param)
        all_chat_param.clear()
        source.reply(f'{prefix}{server.rtr("games_ai.clear_history_message.clearall_success",count=count)}')

class DataManager:
    def __init__(self,db_path: str):
        if db_path.endswith(".db"):
            self.db = PublicDatabase(db_path)
        else:
            self.db = PublicDatabase(db_path + "/public_database.db")

    @new_thread("games_ai@data_write")
    def write_data(self, source: CommandSource, context: dict):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            return source.reply(f'{prefix}{server.rtr("games_ai.no_permission",permission = allow_permission)}')
        else:
            key = context.get("key")
            value = context.get("value")
            self.db.write_data(key, value)
            return source.reply(f'{prefix}{server.rtr("games_ai.data.write_message.success",key=key,value=value)}')
        
    @new_thread("games_ai@data_add")
    def add_data(self, source: CommandSource, context: dict):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            return source.reply(f'{prefix}{server.rtr("games_ai.no_permission",permission = allow_permission)}')
        else:
            key = context.get("key")
            value = context.get("value")
            old_value = self.db.read_data(key)
            if old_value == None:
                new_value = value
            else:
                new_value = old_value + value
            self.db.write_data(key, new_value)
            return source.reply(f'{prefix}{server.rtr("games_ai.data.add_message.success", key=key, value=new_value)}')

    @new_thread("games_ai@data_del")
    def del_data(self, source: CommandSource, context: dict):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            return source.reply(f'{prefix}{server.rtr("games_ai.no_permission",permission = allow_permission)}')
        else:
            key = context.get("key")
            self.db.delete_data(key)
            return source.reply(f'{prefix}{server.rtr("games_ai.data.del_message.success",key=key)}')

    @new_thread("games_ai@data_read")
    def read_data(self, source: CommandSource, context: dict):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            return source.reply(f'{prefix}{server.rtr("games_ai.no_permission",permission = allow_permission)}')
        else:
            key = context.get("key")
            value = self.db.read_data(key)
            if value is None:
                return source.reply(f'{prefix}{server.rtr("games_ai.data.read_message.no_key",key=key)}')
            else:
                message_part = RTextList(
                    prefix,
                    server.rtr("games_ai.data.read_message.success",key=key,value=value),
                    "\n",
                    RText(server.rtr("games_ai.data.read_message.write_button"), RColor.gray).h(server.rtr("games_ai.data.read_message.write_hover")).c(RAction.suggest_command, f"!!data write {key} {value}"),
                    "  OR  ",
                    RText(server.rtr("games_ai.data.read_message.copy_button"), RColor.blue).h(server.rtr("games_ai.data.read_message.copy_hover")).c(RAction.copy_to_clipboard, value)
                )
                return source.reply(message_part)

    @new_thread("games_ai@data_list")
    def read_data_list(self, source: CommandSource, context: dict):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            return source.reply(f'{prefix}{server.rtr("games_ai.no_permission",permission = allow_permission)}')
        else:
            value = self.db.data_list()
            return source.reply(f'{prefix}{server.rtr("games_ai.data.read_list_message")}\n{value}')

    @new_thread("games_ai@data_keys")
    def read_all_keys(self, source: CommandSource, context: dict):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            return source.reply(f'{prefix}{server.rtr("games_ai.no_permission",permission = allow_permission)}')
        else:
            keys = self.db.get_all_key()
            return source.reply(f'{prefix}{server.rtr("games_ai.data.read_keys_message")}\n{keys}')

    def ask_ai_read_data(self) -> list[tuple[str, str]]:
        value = self.db.data_list()
        return value

class AiDataManager:
    @staticmethod
    @register_tool(description="Read one key/value pair from the public database. Listing the existing keys first is recommended.", parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Key to read"
            }
        },
        "required": ["key"]
    })
    def ai_read_data(source: CommandSource, ai_prefix: str, key: str):
        server = source.get_server()
        source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.reading_data",key=key)}')
        result = PublicDatabase(data_path).read_data(key)
        if result is None:
            return f"Key '{key}' does not exist"
        else:
            return f"The value of key '{key}' is {result}"

    @staticmethod
    @register_tool(description="List every key of the public database")
    def ai_read_all_keys(source: CommandSource, ai_prefix: str):
        server = source.get_server()
        source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.reading_all_keys")}')
        keys = PublicDatabase(data_path).get_all_key()
        return f"All current keys: {keys}"

    @staticmethod
    @register_tool(description="Write a key/value pair into the public database (create or overwrite). The value is overwritten, so avoid clobbering important data; a missing key is created automatically.", perm=get_plugin_config_perm, parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Key to write"
            },
            "value": {
                "type": "string",
                "description": "Value to write"
            }
        },
        "required": ["key", "value"]
    })
    def ai_write_data(source: CommandSource, ai_prefix: str, key: str, value: str):
        server = source.get_server()
        source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.writing_data",key=key,value=value)}')
        if source.get_permission_level() < allow_permission:
            return "Permission denied: the requesting player is not allowed to use this tool"
        PublicDatabase(data_path).write_data(key, value)
        return f"Wrote the value of key '{key}': {value}"

    @staticmethod
    @register_tool(description="Append a value to the public database (create or append). The value is appended to the end of the existing one; a missing key is created automatically.", perm=get_plugin_config_perm, parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Key to append to"
            },
            "value": {
                "type": "string",
                "description": "Value to append"
            }
        },
        "required": ["key", "value"]
    })
    def ai_add_data(source: CommandSource, ai_prefix: str, key: str, value: str):
        server = source.get_server()
        source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.adding_data",key=key,value=value)}')
        if source.get_permission_level() < allow_permission:
            return "Permission denied: the requesting player is not allowed to use this tool"
        old_value = PublicDatabase(data_path).read_data(key)
        if old_value == None:
            new_value = value
        else:
            new_value = old_value + value
        PublicDatabase(data_path).write_data(key, new_value)
        return f"Appended {value} to key '{key}', current value: {new_value}"

    @staticmethod
    @register_tool(description="Delete a key from the public database. Deletion cannot be undone, and it succeeds even when the key does not exist.", perm=get_plugin_config_perm, parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Key to delete"
            }
        },
        "required": ["key"]
    })
    def ai_del_data(source: CommandSource, ai_prefix: str, key: str):
        server = source.get_server()
        source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.deleting_data",key=key)}')
        if source.get_permission_level() < allow_permission:
            return "Permission denied: the requesting player is not allowed to use this tool"
        PublicDatabase(data_path).delete_data(key)
        return f"Deleted the data of key '{key}'"
    
    @staticmethod
    @register_tool(description="List every key/value pair of the public database")
    def ai_read_all_data(source: CommandSource, ai_prefix: str):
        server = source.get_server()
        source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.reading_all_data")}')
        value = PublicDatabase(data_path).data_list()
        return f"All data in the public database: {value}"

@new_thread("games_ai@update")
def check_update(source: CommandSource, context: dict):
    server = source.get_server()
    try:
        update(server, force_table=True)
    except Exception as e:
        server.say(f"{prefix}{server.rtr("games_ai.update.no_metadata")}")
        server.logger.warning(f"{prefix}{server.rtr("games_ai.update.no_metadata")}")

def cyclic_check_updates(server: PluginServerInterface):
    global _timer
    try:
        update(server)
    except Exception as e:
        server.say(f"{prefix}{server.rtr("games_ai.update.no_metadata")}")
        server.logger.warning(f"{prefix}{server.rtr("games_ai.update.no_metadata")}")
    finally:
        _timer = threading.Timer(86400, cyclic_check_updates, args=(server,))
        _timer.name = "games_ai@update_timer"
        _timer.daemon = True
        _timer.start()

def update(server: PluginServerInterface, force_table: bool = False):
    global unload_status_code
    unload_status_code = 0

    # Refresh the context-window table as part of the same startup/24h run.
    # Keep this the very first statement: the branches below return early.
    # Manual `!!gamesai check` passes force_table=True to bypass the 24h TTL.
    try:
        context_table.refresh_table(server, force=force_table)
    except Exception as e:
        server.logger.debug(f"{prefix} Context window table refresh failed: {e}")

    server.say(f"{prefix}{server.rtr("games_ai.update.checking_update")}")
    server.logger.info(f"{prefix}{server.rtr("games_ai.update.checking_update")}")
    response = requests.get("https://api.mcdreforged.com/catalogue/everything_slim.json.xz")
    if response.status_code == 200:
        compress_data = response.content
        decompress_data = lzma.decompress(compress_data)
        json_data = json.loads(decompress_data.decode('utf-8'))
        try:
            new_version = json_data.get("plugins").get("games_ai").get("release").get("releases")[0].get("meta").get("version")
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            server.say(f"{prefix}{server.rtr("games_ai.update.no_metadata")}")
            server.logger.warning(f"{prefix}{server.rtr("games_ai.update.no_metadata")}")
            return e
        if get_main_version(new_version) <= get_main_version(PLUGIN_METADATA["version"]):
            server.logger.info(f"{prefix}{server.rtr("games_ai.update.no_update")}")
            server.say(f"{prefix}{server.rtr("games_ai.update.no_update")}")
            return
        else:
            server.say(f"{prefix}{server.rtr("games_ai.update.new_update",version = new_version)}")
            server.logger.info(f"{prefix}{server.rtr("games_ai.update.new_update",version = new_version)}")
            time.sleep(5)
            server.execute_command("!!MCDR plugin install -U -y games_ai")
            server.say(f"{prefix}{server.rtr("games_ai.update.update_ok")}")
            unload_status_code = 1
            return
    else:
        server.say(f"{prefix}{server.rtr("games_ai.update.no_metadata")}")
        server.logger.warning(f"{prefix}{server.rtr("games_ai.update.no_metadata")}")
        return
    
def get_main_version(ver: str):
    main_part = ver.split('-')[0]
    major, minor, patch = main_part.split('.')
    is_release = 1 if ver == main_part else 0
    return (int(major), int(minor), int(patch), is_release)

def debug(source: CommandSource, context: dict):
    server = source.get_server()
    global debug_mode
    if debug_mode:
        debug_mode = False
        plugin_config.debug_mode = False
        server.say(f"{prefix}{server.rtr("games_ai.debug.disable")}")
        server.logger.info(f"{prefix}{server.rtr("games_ai.debug.disable")}")
        return
    else:
        debug_mode = True
        plugin_config.debug_mode = True
        server.say(f"{prefix}{server.rtr("games_ai.debug.enable")}")
        server.logger.info(f"{prefix}{server.rtr("games_ai.debug.enable")}")
        return

@new_thread("games_ai@debug_threads")
def debug_threads(source: CommandSource, context: dict):
    """
    ``!!gamesai debug thread`` — list the threads GamesAI holds, with their ids.

    Only the plugin's own threads are listed (everything matching
    :data:`_PLUGIN_THREAD_NAMES`), because that is where a leftover controller from an
    older plugin instance shows up — its name is then the legacy one, not ``games_ai@...``.
    ``#id`` is the id Python uses internally (the one a forced abort targets); ``native=``
    is the operating system's thread id; ``(current)`` marks the thread running the command.
    """
    server = source.get_server()
    own = sorted((t for t in threading.enumerate() if t.name in _PLUGIN_THREAD_NAMES),
                 key=lambda t: t.ident or 0)

    source.reply(f"{prefix}{server.rtr('games_ai.debug.threads_header', count=len(own))}")
    for thread in own[:_THREAD_LIST_LIMIT]:
        source.reply(f"{prefix}  {_format_thread(thread)}")
    if len(own) > _THREAD_LIST_LIMIT:
        source.reply(f"{prefix}  ... +{len(own) - _THREAD_LIST_LIMIT}")


def _format_thread(thread: threading.Thread) -> str:
    """One ``#id name [daemon] native=…`` line for the ``!!gamesai debug thread`` listing."""
    marks: list[str] = []
    if thread is threading.current_thread():
        marks.append("current")
    if not thread.is_alive():
        marks.append("dead")
    suffix = f"  ({', '.join(marks)})" if marks else ""
    state = "daemon" if thread.daemon else "non-daemon"
    return f"#{thread.ident}  {thread.name}  [{state}]  native={thread.native_id}{suffix}"


@new_thread("games_ai@reloader")
def reloader(source: CommandSource, context: dict):
    """
    ``!!gamesai reload`` — reload the config, the tools and the Mineflayer bot.

    Single-flight: two reloads running at the same time used to fight over the same global
    bot state (the launcher of the second one saw the WebSocket port of the first one's dying
    node process still in use and disabled the bot entirely). A reload is never queued,
    because reloading a config twice has no meaning; the later command is rejected instead.
    """
    global skills, _autonomous_controller
    server = source.get_server()

    if not _reload_lock.acquire(blocking=False):
        source.reply(f'{prefix}{server.rtr("games_ai.user_message.reload_in_progress")}')
        _chat_log(server, "[reload] rejected: another reload is still running")
        return
    try:
        _reload_body(source, context)
    finally:
        _reload_lock.release()


def _reload_body(source: CommandSource, context: dict):
    global skills, _autonomous_controller
    server = source.get_server()

    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(plugin_config.skills_path)), 'config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        _apply_config(server, config)

        for user_chat_param in all_chat_param.values():
            user_chat_param.reload_ai_info()

        tool_plugin_ids = set(TOOL_PLUGIN_IDS)

        reset_all_tools()

        try:
            with open(plugin_config.skills_path, mode="r", encoding="utf-8") as f:
                skills = json.loads(f.read())
                plugin_config.skills_description = skills
        except Exception as e:
            server.logger.warning(f"{prefix} Failed to reload skills: {e}")

        load_external_tools(log=server.logger.info)

        _write_mineflayer_config(server, config)
        mineflayer_dir = os.path.dirname(plugin_config.mineflayer_init_js_path)
        mineflayer_package_json_path = os.path.join(mineflayer_dir, "package.json")
        if not os.path.exists(mineflayer_package_json_path):
            write_package_json(mineflayer_package_json_path)

        init_js_changed = False
        if not os.path.exists(plugin_config.mineflayer_init_js_path) or hashlib.md5(open(plugin_config.mineflayer_init_js_path, "rb").read()).hexdigest() != get_default_init_hash():
            write_default_init(plugin_config.mineflayer_init_js_path)
            init_js_changed = True

        mineflayer_cfg = config.get("mineflayer_bot", {})
        new_enabled = mineflayer_cfg.get("enabled", False)
        was_running = is_node_running()

        if new_enabled and was_running and not init_js_changed:
            server.logger.info(f"{prefix} Config hot-reloaded, JS bot will pick up changes automatically")
            default_ai_info = ai_dict.get(default_ai, None)
            if _autonomous_controller is not None and _autonomous_controller.is_running and default_ai_info is not None:
                _autonomous_controller.reload_config(
                    model=default_ai_info.get("ai_model", ""),
                    base_url=default_ai_info.get("base_url", ""),
                    api_key=default_ai_info.get("api_key", ""),
                    system_prompt=str(server.rtr("games_ai.autonomous_bot.default_system_prompt")),
                    chat_prompt=default_ai_info.get("prompt", ""),
                    extra_body=default_ai_info.get("extra_body", {}),
                    cycle_interval=mineflayer_cfg.get("cycle_interval", 15.0),
                    bot_username=plugin_config.bot_username,
                )
                server.logger.info(f"{prefix} AutonomousBot controller config reloaded")
            elif default_ai_info is None:
                server.logger.warning(f"{prefix} No default AI configured, AutonomousBot controller config skipped")
        else:
            failed = _stop_bot_stack(server)
            if failed:
                server.logger.warning(f"{prefix} Failed to stop existing Mineflayer bot! ({', '.join(failed)})")
            else:
                server.logger.info(f"{prefix} Mineflayer bot stopped successfully!")
            server.logger.info(f"{prefix} Mineflayer bot process has been terminated successfully!")

            if new_enabled:
                try:
                    _run_mineflayer_bot(server, mineflayer_cfg, plugin_config.mineflayer_init_js_path)
                except Exception as e:
                    server.logger.exception(f"{prefix} Failed to start Mineflayer bot: {e}")

        plugin_reload_map = dict(REGISTER_PLUGIN_LIST)
        for plugin_id in tool_plugin_ids:
            if plugin_id != PLUGIN_METADATA["id"] and plugin_id not in plugin_reload_map:
                plugin_reload_map[plugin_id] = None

        for plugin_id, reloader in plugin_reload_map.items():
            if reloader is None:
                _reload_plugin = server.reload_plugin(plugin_id)
                if _reload_plugin is None:
                    server.logger.warning(f"{prefix} Plugin '{plugin_id}' (registered tools) not found")
                    REGISTER_PLUGIN_LIST.pop(plugin_id, None)
                    TOOL_PLUGIN_IDS.discard(plugin_id)
                elif not _reload_plugin:
                    server.unload_plugin(plugin_id)
                    server.logger.warning(f"{prefix} Failed to reload plugin '{plugin_id}', unloaded and removed from reload list")
                    REGISTER_PLUGIN_LIST.pop(plugin_id, None)
                    TOOL_PLUGIN_IDS.discard(plugin_id)
                else:
                    server.logger.info(f"{prefix} Successfully reloaded plugin '{plugin_id}'")
            else:
                try:
                    reloader(source)
                    server.logger.info(f"{prefix} Successfully reloaded registered plugin '{plugin_id}'")
                except Exception as e:
                    server.unload_plugin(plugin_id)
                    server.logger.warning(f"{prefix} Failed to reload registered plugin '{plugin_id}', unloaded and removed from reload list, reason: {e}")
                    REGISTER_PLUGIN_LIST.pop(plugin_id, None)
                    TOOL_PLUGIN_IDS.discard(plugin_id)
    except Exception as e:
        server.logger.exception(f"{prefix} Reload failed: {e}")
        source.reply(f"{prefix}Reload failed: {e}")

    server.dispatch_event(LiteralEvent("games_ai.reload"), (source,))

    server.say(f'{prefix}{server.rtr("games_ai.unload_message.reloader_msg")}')
    server.logger.info(f'{prefix}{server.rtr("games_ai.unload_message.reloader_msg")}')
    return

@new_thread("games_ai@speed_test")
def speed_test(source: CommandSource, context: dict):
    server = source.get_server()
    test_url = []

    user_input = context.get("model")
    if user_input is not None:
        user_input_id = name_to_id.get(user_input, user_input)
        ai_info = ai_dict.get(user_input_id)

        if ai_info is None:
            may_user_ai = []
            for ai_id, ai_config in ai_dict.items():
                name = ai_config.get("ai_name", "")
                if user_input.lower() in name.lower() or user_input.lower() in ai_id.lower():
                    may_user_ai.append(ai_id)
            if len(may_user_ai) == 1:
                ai_info = ai_dict.get(may_user_ai[0])
            elif len(may_user_ai) > 1:
                source.reply(f"{prefix}{server.rtr('games_ai.user_message.model_more')}{may_user_ai}")
                return
            else:
                source.reply(f"{prefix}{server.rtr('games_ai.user_message.model_error')}{list(ai_dict.keys())}")
                return

        ai_prefix = ai_info.get("ai_name")
        base_url = ai_info.get("base_url")
        api_key = ai_info.get("api_key")
        test_url.append((ai_prefix, base_url, api_key))
    else:
        test_url = [(ai_info.get("ai_name"), ai_info.get("base_url"), ai_info.get("api_key")) for ai_info in ai_dict.values()]

    for ai_prefix, base_url, api_key in test_url:
        source.reply(f'{ai_prefix}{server.rtr("games_ai.speed_test.testing", url=base_url)}')

        try:
            start_time = time.time()
            response = requests.get(
                base_url.rstrip("/") + "/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10
            )
            elapsed = (time.time() - start_time) * 1000

            if response.status_code in (200, 401):
                source.reply(
                    f'{ai_prefix}✅ {server.rtr("games_ai.speed_test.success")}\n{ai_prefix}{server.rtr("games_ai.speed_test.latency", latency=f"{elapsed:.0f}")}\n{ai_prefix}{server.rtr("games_ai.speed_test.status_code", code=response.status_code)}'
                )
            else:
                source.reply(
                    f'{ai_prefix}⚠️ {server.rtr("games_ai.speed_test.partial", latency=f"{elapsed:.0f}", code=response.status_code)}'
                )
        except requests.exceptions.Timeout:
            source.reply(f'{ai_prefix}❌ {server.rtr("games_ai.speed_test.timeout")}')
        except requests.exceptions.ConnectionError as e:
            source.reply(f'{ai_prefix}❌ {server.rtr("games_ai.speed_test.connection_error", error=str(e))}')
        except Exception as e:
            source.reply(f'{ai_prefix}❌ {server.rtr("games_ai.speed_test.error", error=str(e))}')
    return


def _toggle_aibot(server: PluginServerInterface, enabled: bool) -> bool:
    config_path = os.path.join(os.path.dirname(os.path.dirname(plugin_config.skills_path)), "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    current = config.get("mineflayer_bot", {}).get("enabled", False)
    if current == enabled:
        return True
    config.setdefault("mineflayer_bot", {})["enabled"] = enabled
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    server.execute_command("!!gamesai reload")
    return False


def aibot_join(source: CommandSource, context: dict):
    with _aibot_lock:
        server = source.get_server()
        if source.get_permission_level() < plugin_config.allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission=plugin_config.allow_permission))
            return
        if not re.fullmatch(r'[a-zA-Z0-9_]+', plugin_config.bot_username):
            source.reply(f"{prefix}{server.rtr('games_ai.aibot.invalid_bot_username', username=plugin_config.bot_username)}")
            return
        if _toggle_aibot(server, True):
            server.say(f"{prefix}{server.rtr('games_ai.aibot.already_joined', username=plugin_config.bot_username)}")
        else:
            source.reply(f"{prefix}{server.rtr('games_ai.aibot.join', username=plugin_config.bot_username)}")


def aibot_leave(source: CommandSource, context: dict):
    with _aibot_lock:
        server = source.get_server()
        if source.get_permission_level() < plugin_config.allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission=plugin_config.allow_permission))
            return
        if _toggle_aibot(server, False):
            server.say(f"{prefix}{server.rtr('games_ai.aibot.already_left', username=plugin_config.bot_username)}")
        else:
            source.reply(f"{prefix}{server.rtr('games_ai.aibot.leave', username=plugin_config.bot_username)}")


class ConfigManager:
    def __init__(self, config: dict):
        self.config = config
        self.config_path = os.path.join(os.path.dirname(os.path.dirname(plugin_config.skills_path)), "config.json")


    def get_config(self, source: CommandSource, context: CommandContext):
        server = source.get_server()
        if source.get_permission_level() < plugin_config.allow_permission:
            source.reply(f"{prefix}{server.rtr("games_ai.no_permission", permission=plugin_config.allow_permission)}")
            return

        config_key = context.get("key")
        if config_key is None:
            source.reply(f"{prefix}{server.rtr('games_ai.config_manager.no_key')}")
            return
        with open(self.config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        content = config.get(config_key)
        if content is None:
            source.reply(f"{prefix}{server.rtr('games_ai.config_manager.key_not_found', key=config_key)}")
            return
        source.reply(f"{prefix}{server.rtr('games_ai.config_manager.get_success', key=config_key, value=json.dumps(content, ensure_ascii=False, indent=2))}")
        return


    def set_config(self, source: CommandSource, context: CommandContext):
        server = source.get_server()
        if source.get_permission_level() < plugin_config.allow_permission:
            source.reply(f"{prefix}{server.rtr("games_ai.no_permission", permission=plugin_config.allow_permission)}")
            return

        config_key = context.get("key")
        new_value = context.get("value")
        if config_key is None or new_value is None:
            source.reply(f"{prefix}{server.rtr('games_ai.config_manager.missing_args')}")
            return
        if config_key in ("all_ai", "mineflayer_bot"):
            source.reply(f"{prefix}{server.rtr('games_ai.config_manager.complex_key_denied', key=config_key)}")
            return

        with open(self.config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        old_value = config.get(config_key)

        try:
            parsed_value = json.loads(new_value)
        except (json.JSONDecodeError, ValueError):
            parsed_value = new_value

        if old_value is not None and not isinstance(parsed_value, type(old_value)):
            try:
                if isinstance(old_value, bool):
                    parsed_value = parsed_value not in (False, 0, '', 'false', 'False', '0')
                else:
                    parsed_value = type(old_value)(parsed_value)
            except (ValueError, TypeError):
                source.reply(f"{prefix}{server.rtr('games_ai.config_manager.type_mismatch', key=config_key, old_type=type(old_value).__name__, new_type=type(parsed_value).__name__)}")
                return

        config[config_key] = parsed_value
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

        source.reply(f"{prefix}{server.rtr('games_ai.config_manager.set_success', key=config_key, value=new_value)}")
        server.execute_command("!!gamesai reload")
        return


    def aibot_config(self, source: CommandSource, context: CommandContext):
        server = source.get_server()
        if source.get_permission_level() < plugin_config.allow_permission:
            source.reply(f"{prefix}{server.rtr("games_ai.no_permission", permission=plugin_config.allow_permission)}")
            return

        config_key = context.get("key")
        config_value = context.get("value")
        if config_key is None or config_value is None:
            source.reply(f"{prefix}{server.rtr('games_ai.config_manager.missing_args')}")
            return
        if config_key not in ("username", "password", "auth"):
            source.reply(f"{prefix}{server.rtr('games_ai.aibot.invalid_key', key=config_key)}")
            return

        if config_key in ("username", "password"):
            if not re.fullmatch(r'[a-zA-Z0-9_]+', config_value):
                source.reply(f"{prefix}{server.rtr('games_ai.aibot.invalid_format', key=config_key)}")
                return
        if config_key == "auth" and config_value not in ("microsoft", "mojang", "offline"):
            source.reply(f"{prefix}{server.rtr('games_ai.aibot.invalid_auth')}")
            return

        with open(self.config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        bot_section = config.setdefault("mineflayer_bot", {}).setdefault("bot", {})
        bot_section[config_key] = config_value

        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

        source.reply(f"{prefix}{server.rtr('games_ai.aibot.set_success', key=config_key, value=config_value)}")
        server.execute_command("!!gamesai reload")
        return

