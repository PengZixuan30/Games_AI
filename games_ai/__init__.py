from mcdreforged.api.all import *

# Everything comes from the packages' front doors (their ``__init__.py``): each one re-exports the
# names that need only the standard library and MCDR eagerly and the rest on first use, so these
# imports keep the promise below intact. The module objects (``deps``, ``logger``, the command
# modules) come from the same doors.
from .core import (ChatHistoryStore, PublicDatabase, TOOL_DENIED_LEVEL, TOOL_DENIED_NOT_ALLOWED,
                   clock, database, deps, has_permission, logger, plugin_config, require_permission)
from .ai import (EXTERNAL_SKILLS_LIST, REGISTER_PLUGIN_LIST, TOOL_PLUGIN_IDS,
                 get_local_tool_schemas_for_perm, get_plugin_config_perm, get_tool_handler,
                 load_external_tools, register_bot_tool, register_tool, reset_all_tools,
                 seed_tools_folder)
from .bot import (clear_bot_peer, detach_mineflayer_process, get_default_init_hash,
                  get_mineflayer_client, is_node_running, run_node, set_bot_peer,
                  stop_mineflayer_process, write_default_init, write_package_json)
from .cluster import (REMOTE_CONSOLE_LEVEL, ROUTE_CLUSTER, ROUTE_LOCAL, ROUTE_SERVER,
                      SessionRegistry, WebSocketCommandSource, decode_text, encode_text)
# The command handlers: one module per command group (see games_ai/commands/).
from .commands import aibot as aibot_commands
from .commands import clear as clear_commands
from .commands import data as data_commands
from .commands import settings as settings_commands
# Both lived in this module before the split. They are re-exported so anything that imported
# them from the package keeps working; the texts themselves live in games_ai/ui/help.py.
from .ui import gamesai_help, send_help

# Everything above this line is standard library or MCDR only, so the plugin imports even on a
# machine where none of its Python packages exists yet. The rest waits below: `on_load` aborts
# right away in that case (see _deps_start_install), which is what lets the plugin install the
# packages itself and ask MCDR to load it again. The check is three metadata lookups and three
# find_spec calls, so the normal path pays microseconds for it.
_deps_pending = bool(deps.unsatisfied())

if not _deps_pending:
    from .ai import (ChatParam, NonHistoryChatParam, describe_http_status, register_no_history,
                     set_remote_tool_router, setup_openai_logging, stop_no_history,
                     unregister_no_history)
    from .bot import (AutonomousBotController, CONTROLLER_THREAD_NAMES, force_abort_thread,
                      get_bot_controller, set_bot_controller)
    from .cluster import (MODE_CLIENT, MODE_LOCAL, MODE_SERVER, CrossServerManager,
                          token_fingerprint)
    from .update import update_round
    from .commands import node as node_commands
else:
    # The module body below reads this one at import time (_PLUGIN_THREAD_NAMES). With no
    # controller running there is no such thread to report anyway.
    CONTROLLER_THREAD_NAMES = ()

import time,os,json,threading,logging,math
import functools
import inspect
import shutil
import subprocess
import hashlib
import re

if not _deps_pending:
    # `requests` talks to other instances and the update catalogue; the exception classes are what
    # `!!ask` has to tell apart -- a wrong key, a rate limit, a broken connection and any other
    # status code all need a different sentence for the player (see _ask_error_reply).
    import requests
    from openai import APIConnectionError, APIStatusError, AuthenticationError, RateLimitError

# The repair of the missing Python packages: its pip child is killed from on_unload, and one plugin
# instance tries it at most once (an instance created by a reload may try again on purpose).
_DEP_INSTALL_ABORT = threading.Event()
_DEP_INSTALL_STARTED = False

PLUGIN_METADATA = {
    "id": "games_ai",
    "version": "0.8.1",
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

DEFAULT_WEBSOCKET_URI = "ws://127.0.0.1:8080"

# The JS bot's own reconnect knobs; the address itself is websocket.uri now, because the
# bot config block no longer carries a websocket section.
_BOT_WS_RECONNECT_INTERVAL = 10
_BOT_WS_TIMEOUT = 60

# Every users have a ChatParam Object
all_chat_param: dict[str, "ChatParam"] = {}
# One conversation per user key: atomic get-or-create, so two asks for the same player can
# never build two ChatParam objects (one of them would silently lose the history).
_conversations_lock = threading.Lock()
# Which server each player last spoke from; used to tell the model when that changes.
# The lock makes the "check what changed, remember it" step atomic: two asks that arrive at
# the same moment for one player must not both announce the same move.
_player_servers: dict[str, str] = {}
_player_servers_lock = threading.Lock()

# The user key a command source that is not a player answers to (see ``get_username``). The
# console's own conversation is stored under it, and it is **not** a player name -- asking MCDR
# for its permission level would answer with the default player level and write that name into
# ``permission.yml``.
CONSOLE_ACCESS_KEY = "Server Control Panel"

# ── stored conversations ────────────────────────────────────────────────────
# Every conversation lives in its own table of the public database file (see
# ``database.ChatHistoryStore``). MCDR never deletes a plugin's data folder, so the history
# survives a reload, an update, a restart and even removing the plugin -- only deleting
# ``config/games_ai/database/public_database.db`` loses it (together with ``!!data``).
_HISTORY_FORMAT = 1
# Set by on_unload: a round still finishing on this (already unloaded) instance must not write
# its older state over the newer one a freshly loaded instance may have produced meanwhile.
_history_frozen = False
# The longest message one user may hand to another user's conversation.
_PLAYER_MESSAGE_MAX_LENGTH = 1000

# The cross-server link of this instance. ``_cross_server`` is created on load and its role
# is decided on a background thread, so ``plugin_config.cross_server_mode`` reads "local"
# until the decision is in.
_cross_server: "CrossServerManager | None" = None
_cross_server_thread: threading.Thread | None = None
# Set by ``_migrate_config_data`` during load_config_simple and logged right after it.
_config_migration_note: str | None = None

# Commands this instance forwarded to the hub, keyed by session id, so the streamed answers
# can be delivered to whoever typed them.
_remote_sessions = SessionRegistry()
# How long the hub waits for the answer of a tool call it routed to another instance. A timeout
# is reported to the model as an unknown outcome and never retried: the tool may still be
# running, or it may already have run and only the answer was lost on the way back.
_REMOTE_TOOL_TIMEOUT = 120.0
# The MCDR server interface, kept for the background threads that execute remote commands.
_server_ref: "PluginServerInterface | None" = None
# The message prefix and the command permission level are owned by ``plugin_config`` (see
# games_ai/core/config.py), the one place that has them. That singleton carries class-level
# defaults, so a diagnostic raised outside a full plugin lifetime (a teardown on a detached
# thread, a started-but-never-loaded instance) still prints a usable prefix instead of
# raising NameError.

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
    "games_ai@bot_teardown", "games_ai@cross_server", "games_ai@ws_hub", "games_ai@ws_node",
    "games_ai@remote_command", "games_ai@update_order",
    "games_ai@data_write", "games_ai@data_add", "games_ai@data_del",
    "games_ai@data_read", "games_ai@data_list", "games_ai@data_keys",
    "games_ai@deps_install", "games_ai@deps_pip",
})

# How many entries `!!gamesai debug thread` prints per group before summarising the rest.
_THREAD_LIST_LIMIT = 12
_autonomous_controller: "AutonomousBotController | None" = None
# Grace period for the cooperative controller stop during unload/reload. An idle loop
# leaves immediately (interruptible wait), so anything longer than this means the thread is
# inside a blocking call — where waiting more rarely helps, and the forced abort follows.
_BOT_STOP_GRACE = 1.5
# How long on_unload may wait for the teardown thread before it gives up and returns. One
# synchronously killed node process costs about a second, so the ordinary case stays inside
# this window and MCDR really is unloaded with a dead bot; anything slower is left to the
# detached thread instead of blocking the reload/unload for it.
_BOT_UNLOAD_GRACE = 1.5
# Set when the plugin is unloaded, so a pending "wait for server start" bot
# launch aborts cleanly (see _wait_server_then_launch)
_mineflayer_pending_abort = threading.Event()
_mineflayer_wait_thread: threading.Thread | None = None
# A launch that is waiting for the server belongs to one decision: a disable (or a newer
# launch request) bumps this token, so the older wait thread exits instead of launching a bot
# that the operator already cancelled.
_mineflayer_launch_token: int = 0

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
        server.logger.warning(f"{plugin_config.prefix} Leftover {name} thread is still alive after {timeout:.0f}s")
    else:
        server.logger.info(f"{plugin_config.prefix} Leftover {name} thread has finished")


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
            f"{plugin_config.prefix} Leftover bot controller thread from a previous plugin instance found, aborting it"
        )
        if not force_abort_thread(thread, server.logger):
            server.logger.warning(
                f"{plugin_config.prefix} Leftover controller thread is still inside a blocking call "
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
            server.logger.info(f"{plugin_config.prefix} Leftover bot controller thread aborted")
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


def _deps_log_line(server: PluginServerInterface, line: str) -> None:
    """One line of the pip child's output, so an install is visible while it runs."""
    server.logger.info(f"{plugin_config.prefix}[deps] {line}")


def _deps_start_install(server: PluginServerInterface) -> None:
    """The packages are missing: report them and repair them once.

    Nothing is registered and nothing else of ``on_load`` runs -- the instance is ready, but has
    no commands, no bot and no cross-server link until the packages are there. There is no switch
    and no command for this: repairing its own dependencies is the plugin's business, and the
    repair either succeeds (a self-reload follows) or is reported for the user to fix by hand.
    """
    global _DEP_INSTALL_STARTED
    names = deps.unsatisfied()
    server.logger.warning(f"{plugin_config.prefix}"
                          + server.rtr("games_ai.dependency.missing_notice", packages=", ".join(names)))
    if _DEP_INSTALL_STARTED:
        return
    _DEP_INSTALL_STARTED = True
    allowed, _reason = deps.begin_install(server, names)
    if not allowed:
        server.logger.warning(f"{plugin_config.prefix}"
                              + server.rtr("games_ai.dependency.install_in_progress"))
        return
    _deps_install_thread(server, names)


@new_thread("games_ai@deps_install")
def _deps_install_thread(server: PluginServerInterface, names: list[str]) -> None:
    """Install the missing packages and ask MCDR to load the plugin again.

    Two attempts: the machine's own pip configuration first, the Aliyun mirror second. The plugin
    reloads itself only once the packages really import; a failed repair is logged together with
    the command the user can run, and nothing else happens -- no retry, no reload.

    This runs on its own thread because ``reload_plugin`` below unloads this very instance: after
    that call the module globals read earlier belong to an instance that is gone, so only this
    function's arguments and ``server`` are touched from then on.
    """
    plugin_id = str(PLUGIN_METADATA.get("id", "games_ai"))
    server.logger.info(f"{plugin_config.prefix}"
                       + server.rtr("games_ai.dependency.installing", packages=", ".join(names)))

    def _retry_notice(pending: list[str]) -> None:
        server.logger.warning(f"{plugin_config.prefix}"
                              + server.rtr("games_ai.dependency.install_retry_mirror",
                                           packages=", ".join(pending), index=deps.ALIYUN_INDEX_URL))

    try:
        ok, phase, detail = deps.install(names, lambda line: _deps_log_line(server, line),
                                         _DEP_INSTALL_ABORT, retry_log=_retry_notice)
        still = deps.unsatisfied()
    except Exception as e:
        deps.finish_install(server, False, f"{type(e).__name__}: {e}")
        server.logger.exception(f"{plugin_config.prefix}"
                                + server.rtr("games_ai.dependency.install_failed", packages=", ".join(names)))
        server.logger.error(f"{plugin_config.prefix}"
                            + server.rtr("games_ai.dependency.manual_hint",
                                         command=deps.manual_command(names)))
        return

    if not ok or still:
        deps.finish_install(server, False, detail, phase)
        server.logger.error(f"{plugin_config.prefix}"
                            + server.rtr("games_ai.dependency.install_failed",
                                         packages=", ".join(still or names)))
        server.logger.error(f"{plugin_config.prefix}"
                            + server.rtr("games_ai.dependency.manual_hint",
                                         command=deps.manual_command(still or names)))
        return

    deps.finish_install(server, True, detail, phase)
    server.logger.info(f"{plugin_config.prefix}" + server.rtr("games_ai.dependency.installed_reloading"))
    try:
        result = server.reload_plugin(plugin_id)
    except Exception as e:
        server.logger.exception(f"{plugin_config.prefix}[deps] reload_plugin failed: {e}")
        result = None
    # The return value is not proof that the plugin runs again -- MCDR reports a successful reload
    # even when the entry module of the new instance fails to import -- so it is only logged. The
    # instance that comes back announces itself with the "recovered" line in its own on_load.
    server.logger.info(f"{plugin_config.prefix}[deps] reload_plugin({plugin_id!r}) -> {result!r}")
    if result is not True:
        server.logger.error(f"{plugin_config.prefix}"
                            + server.rtr("games_ai.dependency.manual_hint",
                                         command=deps.manual_command(names)))


def _load_skills_index(server: PluginServerInterface, skills_path: str) -> list:
    """Read ``skills.json``; a broken file is logged and answered with "no skills".

    The file is user-editable and is written by the AI as well (a crash during a write can
    truncate it), so a parse error must never abort ``on_load`` and keep the whole plugin from
    loading. The same rule the stored conversations follow applies here: unreadable user data
    is reported and skipped, not fatal.
    """
    try:
        with open(skills_path, mode="r", encoding="utf-8") as handle:
            content = handle.read()
    except OSError as error:
        server.logger.warning(f"{plugin_config.prefix} Cannot read {skills_path}: {error}; "
                              f"the skill list starts empty")
        return []
    try:
        index = json.loads(content)
    except (json.JSONDecodeError, ValueError) as error:
        server.logger.warning(f"{plugin_config.prefix} {skills_path} is not valid JSON ({error}); "
                              f"the skill list starts empty")
        return []
    if not isinstance(index, list):
        server.logger.warning(f"{plugin_config.prefix} {skills_path} must hold a list; "
                              f"the skill list starts empty")
        return []
    return index


def on_load(server: PluginServerInterface, _):
    global _config_migration_note, _history_frozen

    # Without the packages the rest of this function cannot run at all, so repair them and let the
    # reload bring this instance back for real. Everything below is skipped on purpose.
    if _deps_pending or deps.unsatisfied():
        _deps_start_install(server)
        return

    recovered = deps.note_recovered(server)
    if recovered:
        server.logger.info(f"{plugin_config.prefix}"
                           + server.rtr("games_ai.dependency.recovered",
                                        packages=", ".join(recovered)))
    
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
            "bot": {
                "username": "<Your Minecraft Bot Username>",
                "password": "<Your Minecraft Bot Password>",
                "auth": "microsoft"
            }
        },
        "websocket": _default_websocket_block()
    }
    
    server.register_help_message(prefix="!!gamesai",message=server.rtr("games_ai.mcdr_help_message.gamesai_help"))
    server.register_help_message(prefix="!!ask <content>",message=server.rtr("games_ai.mcdr_help_message.gamesai_ask"))

    config = server.load_config_simple(
        file_name='config.json',
        default_config=DEFAULT_CONFIG,
        in_data_folder=True,
        data_processor=_migrate_config_data
    )
    if _config_migration_note:
        server.logger.info(f"{plugin_config.prefix} Config migrated: {_config_migration_note}")
        _config_migration_note = None

    _apply_config(server, config)
    logger.attach(server)
    # Which clock the AI is being told about: the zone is detected, never configured, so this
    # line is how an operator finds out what the readings say (see games_ai/core/clock.py).
    server.logger.info(f"{plugin_config.prefix} time zone {clock.describe()}")

    # Registered here rather than next to the other help messages: it passes
    # the configured permission level, which only lands in `plugin_config.allow_permission`
    # once the config has been applied (before that the class default, 3, would be used).
    server.register_help_message(prefix="!!data",message=server.rtr("games_ai.mcdr_help_message.data"),permission=plugin_config.allow_permission)
    
    # The OpenAI API logging is set up here because it needs the server logger, which is only
    # available after the server instance is initialized.
    setup_openai_logging(server.logger, level=logging.INFO)

    # Must run after the config is applied (this logs with `plugin_config.prefix`, which
    # _apply_config sets) and before any new bot controller starts, so a thread left over from
    # a previous plugin instance can never act alongside the new one. The exception hook goes
    # first so an abort landing in the old instance's thread is logged, not printed as a
    # traceback.
    _install_thread_excepthook(server)
    _abort_leftover_bot_threads(server)

    # Welcome message: the prefix is in the config, so it is only printed after the config is applied.
    # When Minecraft Server is running, the message is sent to the console and the players. When Minecraft Server is not running, the message is only sent to the console.
    # Minecraft Server is started after the plugin is loaded, so the message is sent to the console and the players. To :function:`on_server_startup`
    server.logger.info(f'{plugin_config.prefix}{server.rtr("games_ai.load_message.server_info")}')
    server.say(f'{plugin_config.prefix}{server.rtr("games_ai.load_message.client_info",v=PLUGIN_METADATA.get("version"))}')

    # Database
    data_path = os.path.join(server.get_data_folder(), "database", "public_database.db")
    data_dir = os.path.dirname(data_path)
    if not os.path.exists(data_dir):
        os.makedirs(data_dir, exist_ok=True)
        server.logger.info(f"{server.rtr("games_ai.load_message.server_create_data_dir")}{data_dir}")

    # Tools: the custom tools file, plus the generated type stubs an editor reads next to it
    # (both live in games_ai/ai/tools_stub_files.py, which keeps this module out of it).
    tools_path = seed_tools_folder(server, os.path.join(server.get_data_folder(), "tools"))

    # Skills. A broken or hand-edited skills.json must never keep the plugin from loading (the
    # AI writes that file too, and a crash during a write can truncate it): the helper logs and
    # falls back to "no skills", so everything else still loads.
    skills_path = os.path.join(server.get_data_folder(), "skills", "skills.json")
    skills_dir = os.path.dirname(skills_path)
    if not os.path.exists(skills_dir):
        os.makedirs(skills_dir, exist_ok=True)
    if not os.path.exists(skills_path):
        with open(skills_path, mode='w', encoding='utf-8') as f:
            f.write("[{}]")
        server.logger.info(f"{server.rtr("games_ai.load_message.server_create_data_dir")}{skills_path}")

    skills_index = _load_skills_index(server, skills_path)

    # Mineflayer
    mineflayer_path = os.path.join(server.get_data_folder(), "mineflayer", "init.js")
    mineflayer_dir = os.path.dirname(mineflayer_path)
    mineflayer_package_json_path = os.path.join(server.get_data_folder(), "mineflayer", "package.json")
    if not os.path.exists(mineflayer_dir):
        os.makedirs(mineflayer_dir, exist_ok=True)
    if not os.path.exists(mineflayer_path) or hashlib.md5(open(mineflayer_path, "rb").read()).hexdigest() != get_default_init_hash():
        write_default_init(mineflayer_path)
    if not os.path.exists(mineflayer_package_json_path):
        write_package_json(mineflayer_package_json_path)

    # Set paths in plugin_config for use in other modules
    plugin_config.data_path = data_path
    plugin_config.tools_path = tools_path
    plugin_config.skills_path = skills_path
    plugin_config.builtin_skills_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")
    plugin_config.mineflayer_init_js_path = mineflayer_path
    plugin_config.skills_description = skills_index

    # One SQLite connection for the whole plugin lifetime: `!!data` and the AI tool calls run on
    # separate threads, and a shared, locked connection is what makes `append` atomic (the
    # read-modify-write used to lose one of two concurrent appends). `_restore_all_histories`
    # below uses its own ChatHistoryStore, which is not part of this connection.
    database.open_public_database(plugin_config.data_path)

    # Every stored conversation comes back before any command can be typed: the config and the
    # data folder are applied above, and the AI entries decide whether a stored conversation can
    # be rebuilt at all. A row that cannot be restored is skipped with one log line (see
    # _restore_all_histories) -- a stored conversation must never keep the plugin from loading.
    _history_frozen = False
    _restore_all_histories(server)

    # Load external tools and register commands
    load_external_tools(log=server.logger.info)
    register_commands(server, config)

    # The bot dials the hub this instance ends up with, so its own config file can only be
    # written once the role is decided -- both happen on that background thread (see
    # _start_cross_server), which keeps the probe off the plugin load path.
    def _start_bot_link() -> None:
        manager = _cross_server
        if manager is None:
            server.logger.warning(
                f"{plugin_config.prefix} No cross-server link, so the Mineflayer bot cannot be started"
            )
            return
        _write_mineflayer_config(server, config, manager.peer_uri)
        mineflayer_cfg = config.get("mineflayer_bot", {})
        if mineflayer_cfg.get("enabled", False):
            _run_mineflayer_bot(server, mineflayer_cfg, mineflayer_path)

    # Decided on its own thread (see _start_cross_server); the role lands in
    # plugin_config.cross_server_mode once the probe is done.
    _start_cross_server(server, config, on_ready=_start_bot_link)


def _raw_command(source: CommandSource) -> str | None:
    """The line the user actually typed *here*, for both a player chat command and the console.

    ``PluginCommandSource`` (our own ``server.execute_command`` calls) has no Info, and a
    ``WebSocketCommandSource`` only has one rebuilt from another instance's line: neither may
    travel, or a reload would bounce around the cluster (or a cluster command fan out) forever.
    """
    if isinstance(source, WebSocketCommandSource):
        return None
    get_info = getattr(source, "get_info", None)
    if get_info is None:
        return None
    try:
        content = (get_info().content or "").strip()
    except Exception:
        return None
    return content or None


def _should_forward(source: CommandSource) -> bool:
    manager = _cross_server
    if manager is None or not manager.is_client or not manager.connected:
        return False
    # `manager.is_client` is the single source of truth for the role: consulting
    # plugin_config.cross_server_mode as well would only add a way to get it wrong.
    # Never bounce a command that arrived from another instance, and never forward one that
    # did not come from a user (no Info to rebuild it from).
    if isinstance(source, WebSocketCommandSource):
        return False
    return _raw_command(source) is not None


def _callback_arity(handler) -> int:
    """How many positional arguments MCDR will hand to this callback.

    MCDR slices its argument list by the callback's *declared* positional parameter count and
    subtracts one for a bound method (``command/builder/callback.py``). A wrapper that hides
    the real count behind ``*args`` would therefore be handed too few values, which is why the
    wrappers below declare exactly what the wrapped callback declares.
    """
    try:
        count = len(inspect.getfullargspec(handler).args)
    except TypeError:
        return 1
    return count - 1 if inspect.ismethod(handler) else count


def _normalised_command(raw: str | None) -> str:
    """The command line with its whitespace collapsed (empty string for ``None``)."""
    return " ".join(str(raw or "").split())


def _route(kind: str, handler, expected_command: str | None = None):
    """Wrap a command callback with the cross-server routing of its class.

    ``ROUTE_LOCAL`` commands run where they were typed (help texts). ``ROUTE_SERVER`` and
    ``ROUTE_CLUSTER`` commands are handed to the hub when this instance is a client; on the
    server, and in local mode, they run here -- and a cluster command is then fanned out so
    the other trusted instances run it too. A client whose link is down has nothing to hand
    them to and must not run them with its own state, so they are refused with one localized
    line instead (see :func:`_client_link_is_down`).

    ``expected_command`` is the literal this wrapper was registered for, and every cluster
    command passes it. The fan-out reads the *source's* Info to know what to broadcast, and
    an internal caller can execute a cluster command on a source whose Info happens to be a
    different line (an AI round executing ``!!gamesai reload`` from its ``!!ask`` source used
    to broadcast that whole ``!!ask`` to every peer, which made each node run its own AI
    round). The fan-out therefore only happens when the source's line really is this command.
    """
    def dispatch(source, *args):
        if kind != ROUTE_LOCAL:
            raw = _raw_command(source)
            if raw is not None and not isinstance(source, WebSocketCommandSource):
                if _should_forward(source):
                    if (kind == ROUTE_CLUSTER and expected_command is not None
                            and _normalised_command(raw) != expected_command):
                        logger.log("warning",
                                   f"{plugin_config.prefix}Refusing to forward {raw!r} as "
                                   f"{expected_command!r}: it is not what this source typed")
                        return None
                    _forward_command(kind, source, raw)
                    return None
                if _client_link_is_down():
                    # A client whose link is down has nothing to hand this command to, and
                    # running it here would use this instance's own database and API key. The
                    # docs promise such a command does nothing and says so, so it is refused
                    # instead (and never fanned out to the cluster below either).
                    _explain_local_run(raw, will_run=False)
                    _reply_hub_unavailable(source)
                    return None
                # A command of the hub's class is about to run here instead of there: say so
                # once, so nobody has to infer it from a provider error three steps later.
                _explain_local_run(raw)
        result = handler(source, *args)
        if kind == ROUTE_CLUSTER:
            _fan_out_cluster(source, expected_command)
        return result

    if _callback_arity(handler) >= 2:
        @functools.wraps(handler)
        def wrapper(source, context):
            return dispatch(source, context)
    else:
        @functools.wraps(handler)
        def wrapper(source):
            return dispatch(source)

    return wrapper


def _client_link_is_down() -> bool:
    """True when this instance is a client whose link cannot carry frames right now.

    A client hands its hub-class commands to the hub, so with the link down there is nothing
    to hand them to and running them here would use this instance's own database and API key.
    Only the role matters: the hub itself, a standalone instance and a command that arrived
    from another instance never reach this check (see :func:`_route`).
    """
    manager = _cross_server
    return manager is not None and manager.is_client and not manager.connected


def _reply_hub_unavailable(source: CommandSource) -> None:
    """The one localized line a refused hub-class command is answered with."""
    try:
        source.reply(RText(f"{plugin_config.prefix}{source.get_server().rtr('games_ai.cross_server.link_down')}",
                           RColor.red))
    except Exception:
        pass


def _explain_local_run(raw: str, will_run: bool = True) -> None:
    """One INFO line when a command that belongs on the hub runs here instead.

    Called by :func:`_route` only for commands of the hub's class that really came from a user
    on this instance: help texts (``ROUTE_LOCAL``), internal invocations (no ``Info`` to
    rebuild the line from) and commands that arrived from another instance stay silent, because
    running those here is correct.

    It also stays silent where running here is the design rather than a failure: on the hub
    itself, and on an instance that never enrolled (whose load already says how to enrol). What
    is left is the case the operator hit -- an instance that holds an identity, so somebody
    expects it to hand commands over, but the role is local or its link is down. Without this
    line the only clue is a provider error from the wrong machine (their 401).

    ``will_run`` is False for the one case where the command is *not* run here: a client whose
    link is down (see :func:`_client_link_is_down`), where the line would otherwise claim it
    ran on this instance.
    """
    manager = _cross_server
    if manager is not None and manager.is_client:
        if manager.connected:
            return
        reason = "the cross-server link is down"
    elif manager is not None and manager.is_server:
        return                      # the hub runs every command itself: nothing travels
    elif _load_identity(_server_ref) is None:
        return                      # never enrolled: this instance is local by design
    else:
        reason = (f"the cross-server role is {manager.mode}" if manager is not None
                  else "this instance has no cross-server link")
    outcome = f"running {raw!r} here" if will_run else f"{raw!r} was not run"
    logger.log("info", f"{plugin_config.prefix}{reason}; {outcome} -- run !!gamesai node status")


def _forward_command(kind: str, source: CommandSource, raw: str) -> None:
    """Send a command of a remote class to the hub; the answers come back as frames."""
    manager = _cross_server
    session = _remote_sessions.new(source, kind)
    is_console = bool(getattr(source, "is_console", False))
    player = None if is_console else getattr(source, "player", None)
    permission = REMOTE_CONSOLE_LEVEL if is_console else int(source.get_permission_level())
    data = {
        "command": raw,
        "player": player,
        "console": is_console,
        "permission": permission,
        "session": session,
        "origin": plugin_config.cross_server_name,
        # What this instance can run on its own side: the hub adds these to the model's tool
        # list and routes the matching calls back here (see chat_param.dispatch_tool_call).
        "tools": get_local_tool_schemas_for_perm(permission),
    }
    action = "command_cluster" if kind == ROUTE_CLUSTER else "command"
    if manager is None or not manager.connected:
        _remote_sessions.drop(session)
        try:
            # "Not enrolled" is the actionable version of "the link is not running": the fix is
            # a token, not a reload.
            key = ("games_ai.cross_server.not_enrolled" if _load_identity(_server_ref) is None
                   else "games_ai.cross_server.unavailable")
            source.reply(RText(f"{plugin_config.prefix}{source.get_server().rtr(key)}", RColor.red))
        except Exception:
            pass
        return
    manager.send_to_hub(action, data=data)
    logger.debug_line(f"{plugin_config.prefix}{raw!r} from {source} handed to the cross-server link ({action})")


def _fan_out_cluster(source: CommandSource, expected_command: str | None = None) -> None:
    """Let the other trusted instances run the cluster command that just ran here.

    The command is read back from the source's ``Info`` (that is how a typed command is known
    at all), so it is checked against the literal this command was registered for before
    anything is broadcast: an internal caller can execute a cluster command on a source whose
    Info is a different line, and broadcasting that instead would make every peer execute the
    wrong command (see the analysis in :func:`_route`).
    """
    raw = _raw_command(source)
    if not raw:
        return
    if expected_command is not None and _normalised_command(raw) != expected_command:
        logger.log("warning",
                   f"{plugin_config.prefix}Not fanning out {raw!r}: the cluster command being "
                   f"executed is {expected_command!r}, so this source's line belongs to a "
                   f"different command")
        return
    manager = _cross_server
    if manager is not None and manager.hub is not None:
        # ROUTE_CLUSTER: the answers that come back from the other instances are labelled with
        # the instance that produced them (see _render_remote_reply).
        session = _remote_sessions.new(source, ROUTE_CLUSTER)
        manager.hub.broadcast("exec_cluster", apps=manager.hub.command_apps, data={
            "command": raw,
            "session": session,
            "origin": manager.name,
            "player": None if getattr(source, "is_console", False) else getattr(source, "player", None),
            "console": bool(getattr(source, "is_console", False)),
            "permission": int(source.get_permission_level()),
        })


def _known_player_permission_level(server: ServerInterface | None, player: str) -> int:
    """This instance's permission level for a remote player, without side effects.

    ``ServerInterface.get_permission_level(name)`` goes through MCDR's ``auto_add=True`` path:
    an unknown name is appended to ``permission.yml`` at the default level and that level is
    returned, while the cross-server rule says an unknown remote player gets 0 (and the file
    must not be rewritten by a background thread). The permission manager is therefore asked
    with ``auto_add=False`` directly. Should that private member ever disappear, the fallback
    reads the value but treats a missing name as unknown instead of letting MCDR add it.
    """
    manager = getattr(getattr(server, "_mcdr_server", None), "permission_manager", None)
    if manager is not None:
        try:
            level = manager.get_player_permission_level(str(player), auto_add=False)
        except TypeError:
            level = manager.get_player_permission_level(str(player))
        return 0 if level is None else int(level)
    if server is None:
        return 0
    try:
        return int(server.get_permission_level(str(player)))
    except Exception:
        return 0


def _resolve_remote_permission(data: dict) -> int:
    """How much a remote issuer is allowed to do here.

    A player gets ``min(what the origin reported, this instance's own permission.yml)`` and
    nothing at all when this instance does not know the name; a console keeps level 4, since
    whoever sits at another machine's console already controls that machine.
    """
    if data.get("console"):
        return REMOTE_CONSOLE_LEVEL
    player = data.get("player")
    if not player:
        return 0
    server = _server_ref or ServerInterface.get_instance()
    own = _known_player_permission_level(server, str(player))
    return max(0, min(int(data.get("permission") or 0), own))


def _send_to_peer(target: str, action: str, data: dict) -> None:
    """Send to a named peer.

    The target name may equal ours -- two instances can still be given the same name by hand --
    so this goes through ``hub.deliver``, which never mistakes "looks like my own name" for
    "handle it myself" (that shortcut silently swallowed every answer in that setup).
    """
    manager = _cross_server
    if manager is None or not target:
        return
    if manager.hub is not None:
        manager.hub.deliver(target, action, data=data)
        return
    manager.send_to(target, action, data=data)


def _local_sink(session: str, origin: str):
    """Where the answers of a command executed here go."""
    def sink(text) -> None:
        payload = {"session": session, "text": encode_text(text)}
        # Owning the session is what makes us the origin -- comparing names does not: two
        # instances can share a name (by hand), and the hub would then mistake a client's
        # command for its own and silently drop every answer.
        source = _remote_sessions.get(session)
        if source is not None:
            try:
                source.reply(text)
            except Exception:
                logger.log("exception", "failed to show a local cluster reply")
            return
        _send_to_peer(origin, "command_reply", payload)

    return sink


def _execute_remote(origin: str, data: dict) -> None:
    """Run one command on behalf of another instance."""
    server = _server_ref or ServerInterface.get_instance()
    raw = str(data.get("command") or "").strip()
    session = str(data.get("session") or "")
    if server is None or not raw:
        return
    command_source = WebSocketCommandSource(
        server,
        origin=origin or "?",
        player=data.get("player"),
        is_console=bool(data.get("console")),
        permission_level=_resolve_remote_permission(data),
        sink=_local_sink(session, origin),
        tools=data.get("tools"),
        session=session,
        command=raw,          # what get_info() rebuilds the command's Info from
    )
    logger.debug_line(f"{plugin_config.prefix}Running {raw!r} for {command_source} "
                f"at permission {command_source.get_permission_level()}")
    # Deliberately not on this link thread: the command is often an `!!ask`, and its whole AI
    # round -- routed tool calls included -- then runs on whichever thread executes it. A routed
    # call blocks until the origin answers, and that answer is read by the very thread that
    # would be waiting here, so the link thread must stay free to receive (it is the reader of
    # this connection). See the deadlock note in _on_cross_message.
    threading.Thread(
        target=_run_remote_command,
        args=(server, raw, command_source, origin, session),
        name="games_ai@remote_command",
        daemon=True,
    ).start()


def _run_remote_command(server: ServerInterface, raw: str, command_source: WebSocketCommandSource,
                        origin: str, session: str) -> None:
    """Execute one forwarded command and tell the asking instance that it is done."""
    try:
        server.execute_command(raw, command_source)
    except Exception as e:
        logger.log("exception", f"{plugin_config.prefix}Remote command {raw!r} failed")
        command_source.reply(RText(f"command failed: {e}", RColor.red))
    _send_to_peer(origin, "command_done", {"session": session})


def _resolve_routed_tool_permission(data: dict) -> int:
    """The origin's own verdict on a routed tool call.

    A separate entry point even though the rule matches :func:`_resolve_remote_permission`: the
    tool runs *here*, so *this* instance's own permission.yml has the final say. A hub that
    reports a level this instance does not grant must not be trusted with it.
    """
    return _resolve_remote_permission(data)


def _execute_remote_tool(origin: str, data: dict) -> dict:
    """Run one tool call for the hub and hand its result back (runs on a link thread).

    The tool is looked up in *this* instance's registry -- the hub only knows that this server
    offered it -- and it runs against a command source standing for the remote player, whose
    sink streams the tool's own replies to whoever asked.
    """
    server = _server_ref or ServerInterface.get_instance()
    tool_name = str(data.get("tool") or "")
    args = data.get("args")
    if not isinstance(args, dict):
        args = {}
    manager = _cross_server
    if manager is not None:
        target = str(data.get("target") or "")
        if target and target != manager.name:
            return {"ok": False, "error": f"this instance is {manager.name!r}, not {target!r}"}
        if manager.is_server:
            # The hub owns the AI: it routes tool calls out, it never runs one for another
            # instance. Reaching this means the frame was addressed to a peer that shares the
            # hub's own name and was therefore delivered here (see route_remote_tool_call):
            # running it would answer with this server's data.
            return {"ok": False, "error": ("this is the hub, which does not execute routed tool "
                                           "calls for its own name")}
    handler = get_tool_handler(tool_name)
    if handler is None:
        return {"ok": False, "error": f"this server does not provide tool {tool_name}"}
    if server is None:
        return {"ok": False, "error": f"this instance cannot run tool {tool_name}: no server interface"}
    session = str(data.get("session") or "")
    permission = _resolve_routed_tool_permission(data)
    command_source = WebSocketCommandSource(
        server,
        origin=origin or "?",
        player=data.get("player"),
        is_console=bool(data.get("console")),
        permission_level=permission,
        sink=_local_sink(session, origin),
        session=session,
    )
    required = handler.resolve_perm()
    if permission < required:
        where = manager.name if manager is not None else "this server"
        return {"ok": False, "error": (f"permission denied on {where}: {tool_name} needs level "
                                       f"{required}, the request carries {permission}")}
    logger.debug_line(f"{plugin_config.prefix}Running tool {tool_name} for {command_source} at permission {permission}")
    try:
        result = handler.func(command_source, str(data.get("ai_prefix") or ""), **args)
    except Exception as e:
        logger.log("exception", f"{plugin_config.prefix}Routed tool {tool_name!r} failed")
        return {"ok": False, "error": f"{tool_name} failed on this server: {e}"}
    return {"ok": True, "message": "" if result is None else str(result)}


def route_remote_tool_call(source: WebSocketCommandSource, func_name: str, func_args: dict,
                           ai_prefix: str = "") -> str:
    """Run one tool call on the instance the request came from and return its result.

    A tool that is not hub-bound describes the asking player's own server, so the hub hands the
    call over the cross-server link and waits for the answer. Blocking is only safe on the AI
    loop thread (see the deadlock note in ``_on_cross_message``). Never raises: every failure
    becomes an honest string for the model, and a timeout is an unknown outcome it must not
    retry, because the tool may well have run before the answer was lost.
    """
    manager = _cross_server
    origin = str(getattr(source, "origin", "") or "")
    if manager is None or not origin:
        return f"Cannot run {func_name} on the player's own server: there is no cross-server link."
    if not manager.connected:
        return (f"Cannot run {func_name} on {origin}: the cross-server link is down, so the tool "
                f"was not executed there.")
    hub = manager.hub
    if hub is not None and origin == hub.name:
        # CrossServerHub.send reads a target equal to its own name as "handle it here", which
        # would run the tool on the hub -- exactly the wrong server, and silently so. Refuse
        # instead of answering with another server's data.
        return (f"Cannot run {func_name} on {origin}: that instance shares the hub's name on the "
                f"cross-server link, so its answer cannot be told apart from a local run.")
    data = {
        "tool": func_name,
        "args": func_args,
        "player": source.player,
        "console": bool(source.is_console),
        "permission": int(source.get_permission_level()),
        "origin": manager.name,
        "target": origin,
        "session": str(getattr(source, "session", "") or ""),
        "ai_prefix": ai_prefix,
    }
    started = time.monotonic()
    try:
        reply = manager.send_to(origin, "tool_call", data=data, wait=True, timeout=_REMOTE_TOOL_TIMEOUT)
    except Exception as e:
        logger.log("exception", f"{plugin_config.prefix}Failed to route tool {func_name!r} to {origin!r}")
        return f"Failed to run {func_name} on {origin}: {e}"
    elapsed = time.monotonic() - started
    if reply is None:
        return f"Could not hand {func_name} to {origin}: the tool was not executed there."
    if reply.get("ok"):
        result = reply.get("message")
        if result is None:
            result = (reply.get("data") or {}).get("result")
        return "" if result is None else str(result)
    error = str(reply.get("error") or "no reason was given")
    if reply.get("unknown"):
        # The link dropped while the call was in flight (the peer's disconnect wakes us instead
        # of letting the timeout run out). The tool may well have run there, so the model gets
        # the same "do not retry" answer as for a timeout -- just immediately.
        return (f"The outcome of {func_name} on {origin} is unknown: the link dropped before it "
                f"answered ({error}). Do not retry it -- the tool may still be running, or it may "
                f"already have taken effect.")
    if elapsed >= _REMOTE_TOOL_TIMEOUT or "timeout" in error.lower():
        return (f"The outcome of {func_name} on {origin} is unknown: no answer arrived within "
                f"{int(_REMOTE_TOOL_TIMEOUT)}s. Do not retry it -- the tool may still be running, or it "
                f"may already have taken effect.")
    logger.debug_line(f"{plugin_config.prefix}Tool {func_name!r} was refused by {origin!r}: {error}")
    return f"{func_name} could not be executed on {origin}: {error}"


def _install_tool_router() -> None:
    """Wiring for chat_param: it dispatches through the router installed here.

    Kept as a hook because the package imports chat_param: that module cannot import its own
    package back (and under the test suites each plugin instance has its own copy of both).
    """
    set_remote_tool_router(route_remote_tool_call)


if not _deps_pending:
    _install_tool_router()

def _render_remote_reply(msg: dict) -> None:
    """Show one streamed answer on the instance that asked for the command.

    Only a **cluster** command labels its stream. Its output comes from every instance that ran
    it, so the ones that are not this machine are prefixed with their name. A server-class
    command (``!!ask``, ``!!data``, ...) was handed to the hub, which is answering *this*
    player's own command: those lines are theirs, and prefixing them with the hub's name --
    which is what comparing names did on a client, where the hub's name is always "someone
    else" -- was noise nobody asked for.
    """
    data = msg.get("data") or {}
    session = str(data.get("session") or "")
    source = _remote_sessions.get(session)
    if source is None:
        return
    text = RTextBase.from_any(decode_text(data.get("text")))
    sender = msg.get("source")
    manager = _cross_server
    if (_remote_sessions.kind_of(session) == ROUTE_CLUSTER
            and sender and manager is not None and sender != manager.name):
        text = RTextList(RText(f"[{sender}] ", RColor.gray), text)
    try:
        source.reply(text)
    except Exception:
        logger.log("exception", "failed to deliver a remote command reply")


def _on_cross_message(msg: dict) -> dict | None:
    """Handle one frame addressed to this instance (runs on a link thread)."""
    action = msg.get("action")
    data = msg.get("data") or {}
    sender = str(msg.get("source") or "")

    if action == "command" or action == "command_cluster":
        _execute_remote(sender, data)
        if action == "command_cluster":
            manager = _cross_server
            if manager is not None and manager.hub is not None:
                # Only GamesAI instances run cluster commands; the bot must never see one.
                manager.hub.broadcast("exec_cluster", apps=manager.hub.command_apps,
                                      data={**data, "origin": sender})
        return {"ok": True}
    if action == "exec_cluster":
        # The frame comes from the hub, but the answers belong to the instance that typed the
        # command -- that is `origin`, not the sender of this broadcast.
        #
        # A node never executes a broadcast `!!ask`: the legitimate client->hub path uses the
        # `command` action (kept above), while a broadcast ask means the hub leaked an AI
        # round's source line (the reload/fan-out bug). Running it here would create an
        # independent ChatParam on this node and bill an AI round on its key, so it is refused
        # as defense in depth even if a future fan-out slips again.
        command_line = _normalised_command(str(data.get("command") or ""))
        if command_line.split(" ", 1)[0] == "!!ask":
            logger.log("warning", f"{plugin_config.prefix}Refused a broadcast !!ask from "
                                  f"{sender!r}: a node never runs another instance's AI round")
            _send_to_peer(str(data.get("origin") or sender), "command_done",
                          {"session": str(data.get("session") or "")})
            return {"ok": False, "error": "a broadcast !!ask is not executed on a node"}
        _execute_remote(str(data.get("origin") or sender), data)
        return {"ok": True}
    if action == "plugin_update":
        # The hub ordering this node to install one release. The reply is built here, on the
        # link thread, before anything is downloaded: a long handler would freeze every frame
        # of this node while the hub is waiting for the ack
        # (see update_round._on_update_order).
        return update_round._on_update_order(sender, data)
    if action == "plugin_update_result":
        # A node reporting how far it got with an order this hub sent (hub side only).
        update_round._on_update_result(sender, data)
        return None
    if action == "tool_call":
        # DEADLOCK RULE: this runs on a link/connection thread, so it only ever executes the
        # tool locally. A *routed* call must never be started from here: it blocks until the
        # origin answers, and that answer would have to be read by this very thread (it is the
        # reader of this connection), so the call would sit there until its timeout. Only the
        # AI loop thread may route one (see chat_param.dispatch_tool_call and
        # route_remote_tool_call).
        return _execute_remote_tool(sender, data)
    if action == "command_reply":
        _render_remote_reply(msg)
        return None
    if action == "command_done":
        # The session is kept until it expires: an `!!ask` streams long after this arrives.
        logger.log("debug", f"{plugin_config.prefix}remote command finished ({data.get('session')})")
        return None
    return None


def register_commands(server: PluginServerInterface, config: dict):
    """
    Register all commands for the GamesAI plugin with the MCDR server.
    """
    builder = SimpleCommandBuilder()
    data_manager = data_commands.DataManager(plugin_config.data_path)
    config_manager = settings_commands.ConfigManager(config)
    helper = gamesai_help()

    builder.command('!!gamesai', helper.all_help)
    builder.command('!!gamesai help', helper.all_help)

    builder.command('!!gamesai clear',_route(ROUTE_SERVER, clear_commands.clear_history))
    builder.command('!!gamesai clear <name>',_route(ROUTE_SERVER, clear_commands.clear_history_named))
    builder.command('!!gamesai clearall',_route(ROUTE_CLUSTER, clear_commands.clear_history_all,
                                               expected_command='!!gamesai clearall'))
    
    builder.command('!!gamesai check', _route(ROUTE_SERVER, update_round.check_update))

    builder.command('!!gamesai debug', _route(ROUTE_CLUSTER, debug,
                                              expected_command='!!gamesai debug'))
    builder.command('!!gamesai debug thread', _route(ROUTE_CLUSTER, debug_threads,
                                                     expected_command='!!gamesai debug thread'))

    builder.command('!!gamesai reload', _route(ROUTE_CLUSTER, reloader,
                                               expected_command='!!gamesai reload'))

    builder.command('!!gamesai speedtest', _route(ROUTE_SERVER, speed_test))
    builder.command('!!gamesai speedtest <model>', _route(ROUTE_SERVER, speed_test))

    builder.command('!!gamesai config', helper.config_help)
    builder.command('!!gamesai config get', helper.config_help)
    builder.command('!!gamesai config get <key>', _route(ROUTE_SERVER, config_manager.get_config))
    builder.command('!!gamesai config set', helper.config_help)
    builder.command('!!gamesai config set <key>', helper.config_help)
    builder.command('!!gamesai config set <key> <value>', _route(ROUTE_SERVER, config_manager.set_config))

    server.register_command(
        Literal("!!ask")
            .then(GreedyText("content")
                .suggests(lambda: ["-n", "-f", "switch", "stop", "compact", "context"])
                .runs(_route(ROUTE_SERVER, ask_ai_dispatcher)))
        .runs(helper.ask_help)
    )

    builder.command('!!data', helper.data_help)

    builder.command('!!data write', helper.data_write_help)
    builder.command('!!data write <key>', helper.data_write_help)
    builder.command('!!data write <key> <value>', _route(ROUTE_SERVER, data_manager.write_data))

    builder.command('!!data add', helper.data_add_help)
    builder.command('!!data add <key>', helper.data_add_help)
    builder.command('!!data add <key> <value>', _route(ROUTE_SERVER, data_manager.add_data))

    builder.command('!!data del', helper.data_del_help)
    builder.command('!!data del <key>', _route(ROUTE_SERVER, data_manager.del_data))

    builder.command('!!data read', helper.data_read_help)
    builder.command('!!data read <key>', _route(ROUTE_SERVER, data_manager.read_data))

    builder.command('!!data list', _route(ROUTE_SERVER, data_manager.read_data_list))
    builder.command('!!data list keys', _route(ROUTE_SERVER, data_manager.read_all_keys))

    builder.command('!!aibot', helper.aibot_help)
    builder.command('!!aibot join', _route(ROUTE_SERVER, aibot_commands.aibot_join))
    builder.command('!!aibot leave', _route(ROUTE_SERVER, aibot_commands.aibot_leave))
    builder.command('!!aibot set', helper.aibot_help)
    builder.command('!!aibot set <key>', helper.aibot_help)
    builder.command('!!aibot set <key> <value>', _route(ROUTE_SERVER, config_manager.aibot_config))

    # Per-node enrolment. Every one of these is registered plainly, never through
    # _route(), so it runs where it was typed and is never forwarded or fanned out to the
    # cluster (a node running `node token` would be nonsense and would leak the hub's table).
    builder.command('!!gamesai node', helper.node_help)
    builder.command('!!gamesai node pending', node_commands.pending)
    builder.command('!!gamesai node token <name>', node_commands.issue_token)
    builder.command('!!gamesai node list', node_commands.list_nodes)
    builder.command('!!gamesai node revoke <name>', node_commands.revoke)
    builder.command('!!gamesai node rotate <name>', node_commands.rotate)
    builder.command('!!gamesai node claim <token>', node_commands.claim)
    builder.command('!!gamesai node status', node_commands.status)
    builder.command('!!gamesai node forget', node_commands.forget)

    builder.arg('model', Text)
    builder.arg('content',GreedyText)

    builder.arg('key', Text)
    builder.arg('value', GreedyText)

    # `name` and `token` are single words (a node name, a 43-character url-safe token).
    builder.arg('name', Text)
    builder.arg('token', Text)

    builder.register(server)


def on_server_startup(server: PluginServerInterface):
    """
    Called when the server starts up. This function is used to perform any necessary initialization for the plugin.
    """
    if _deps_pending:
        return  # the packages are still missing; on_load has already said everything about it
    server.say(f'{plugin_config.prefix}{server.rtr("games_ai.load_message.client_info", v=PLUGIN_METADATA.get('version'))}')


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


def _read_bot_token(path: str) -> str:
    """The token the JS bot already holds, so a config rewrite never discards its identity."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return ""
    ws_cfg = data.get("websocket") if isinstance(data, dict) else None
    return str(ws_cfg.get("token") or "") if isinstance(ws_cfg, dict) else ""


def _store_bot_token(server: PluginServerInterface, name: str, token: str) -> None:
    """Keep the token the hub issued to the Mineflayer bot inside the bot's own config.

    This is the "no human step" half of the bot provisioning: the hub hands the freshly
    issued token to the plugin (see CrossServerHub.on_bot_token), and the plugin writes it
    next to the address the bot dials. Only the fingerprint is ever logged.
    """
    if name != plugin_config.bot_username:
        server.logger.info(
            f"{plugin_config.prefix} The hub provisioned the bot {name!r} (fingerprint "
            f"{hashlib.sha256(token.encode('utf-8')).hexdigest()[:6]}), which is not the "
            f"configured bot {plugin_config.bot_username!r}; nothing was written"
        )
        return
    path = os.path.join(os.path.dirname(plugin_config.mineflayer_init_js_path), "config.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    ws_cfg = data.get("websocket")
    if not isinstance(ws_cfg, dict):
        ws_cfg = {}
    ws_cfg["token"] = str(token)
    data["websocket"] = ws_cfg
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=4, ensure_ascii=False)
    except OSError:
        server.logger.exception(f"{plugin_config.prefix} Failed to write the bot's token into {path}")
        return
    server.logger.info(
        f"{plugin_config.prefix} The hub issued a token to the Mineflayer bot {name!r} automatically "
        f"(fingerprint {hashlib.sha256(token.encode('utf-8')).hexdigest()[:6]})"
    )


def _write_mineflayer_config(server: PluginServerInterface, config: dict, peer_uri: str | None = None):
    mineflayer_dir = os.path.dirname(plugin_config.mineflayer_init_js_path)
    mineflayer_config_path = os.path.join(mineflayer_dir, "config.json")
    cfg = dict(config.get("mineflayer_bot", {}))
    host, port = _get_minecraft_server_address()
    cfg.setdefault("bot", {})
    cfg["bot"]["server_host"] = host
    cfg["bot"]["server_port"] = port
    # The bot's own config file keeps the knobs the JS side reads. The address is not a bot
    # setting any more: it is where this instance hosts (or reached) the GamesAI hub, handed
    # to the bot so it can register there as a client.
    # A missing peer_uri falls back to whatever this instance would dial itself: the hub it
    # runs, the hub it reached, or the configured address. This keeps an omitted argument from
    # crashing a reload path (it is the bot's address, not a per-call decision).
    if not peer_uri:
        peer_uri = (_cross_server.peer_uri if _cross_server is not None else "") or \
            plugin_config.websocket_uri or DEFAULT_WEBSOCKET_URI
    cfg["websocket"] = {
        "url": peer_uri or DEFAULT_WEBSOCKET_URI,
        # The bot has no identity file of its own: the hub issues its token at the handshake
        # and the plugin stores it here, so a rewrite has to keep the value it finds.
        "token": _read_bot_token(mineflayer_config_path),
        "reconnect_interval": _BOT_WS_RECONNECT_INTERVAL,
        "timeout": _BOT_WS_TIMEOUT,
        "version": str(PLUGIN_METADATA.get("version", "")),
    }
    os.makedirs(mineflayer_dir, exist_ok=True)      # never depend on the caller's cwd
    with open(mineflayer_config_path, mode='w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


@register_tool(
    description="Start the Mineflayer bot so that it joins the Minecraft server. Does nothing when the bot is already running.",
    perm=get_plugin_config_perm,
    execute_in_hub=True,
)
def run_mineflayer_bot(source: CommandSource, ai_prefix: str):
    server = source.get_server()
    if not has_permission(source):
        return TOOL_DENIED_LEVEL
    if is_node_running():
        return f"The Mineflayer bot is already running ({plugin_config.bot_username})"
    source.reply(f"{ai_prefix}{server.rtr('games_ai.tools.bot_start')}")
    # force: the config value may already be `enabled: true` while the process is dead (it
    # crashed, or its first launch failed) -- without the forced reload nothing would happen.
    aibot_commands._toggle_aibot(server, True, force=True)
    return "Starting the Mineflayer bot..."


@register_tool(
    description="Stop the Mineflayer bot so that it leaves the Minecraft server.",
    perm=get_plugin_config_perm,
    execute_in_hub=True,
)
@register_bot_tool()
def stop_mineflayer_bot(source: CommandSource, ai_prefix: str):
    server = source.get_server()
    if not has_permission(source):
        return TOOL_DENIED_LEVEL
    if not is_node_running():
        return "The Mineflayer bot is not running"
    source.reply(f"{ai_prefix}{server.rtr('games_ai.tools.bot_stop')}")
    aibot_commands._toggle_aibot(server, False, force=True)
    return "Stopping the Mineflayer bot..."

def _run_mineflayer_bot(server: ServerInterface, bot_config: dict, mineflayer_init_js_path: str):
    global _mineflayer_launch_token
    # A new launch intent: cancel whatever a previous disable/unload cancelled, so the wait
    # thread this call may create is not killed by the stale abort flag.
    _mineflayer_pending_abort.clear()
    _mineflayer_launch_token += 1
    launch_token = _mineflayer_launch_token
    # The bot connects to the hub, so the role must be known before its config is written.
    if plugin_config.cross_server_mode == "pending" and _cross_server_thread is not None:
        _cross_server_thread.join(15.0)
    manager = _cross_server
    if manager is None:
        server.logger.error(f"{plugin_config.prefix} No cross-server link, cannot start the Mineflayer bot")
        return
    _write_mineflayer_config(server, {"mineflayer_bot": bot_config}, manager.peer_uri)
    if not server.is_server_running():
        global _mineflayer_wait_thread
        if _mineflayer_wait_thread is not None and _mineflayer_wait_thread.is_alive():
            server.logger.info(f"{plugin_config.prefix} Minecraft server is not running, already waiting for it to start...")
            return
        server.logger.info(f"{plugin_config.prefix} Minecraft server is not running, Mineflayer bot will launch automatically after the server starts")
        _mineflayer_wait_thread = _wait_server_then_launch(server, bot_config, mineflayer_init_js_path,
                                                          launch_token)
        return
    _launch_mineflayer_bot(server, bot_config, mineflayer_init_js_path)


@new_thread("games_ai@mineflayer_wait_server")
def _wait_server_then_launch(server: ServerInterface, bot_config: dict, mineflayer_init_js_path: str,
                             launch_token: int):
    while not server.is_server_running():
        if _mineflayer_pending_abort.is_set() or launch_token != _mineflayer_launch_token:
            server.logger.info(f"{plugin_config.prefix} Mineflayer bot launch cancelled: the bot was disabled")
            return
        time.sleep(2)
    if _mineflayer_pending_abort.is_set() or launch_token != _mineflayer_launch_token:
        server.logger.info(f"{plugin_config.prefix} Mineflayer bot launch cancelled: the bot was disabled")
        return
    server.logger.info(f"{plugin_config.prefix} Minecraft server started, launching Mineflayer bot...")
    _launch_mineflayer_bot(server, bot_config, mineflayer_init_js_path)


def _cancel_pending_bot_launch() -> None:
    """Cancel a bot launch that is waiting for the server (or was just started).

    Called when the bot is disabled (``!!aibot leave``/config) or the plugin unloads. Without
    it, a wait thread created before the disable would still call `_launch_mineflayer_bot` after
    the server comes up: the operator disabled the bot, but a node process and an AI-burning
    controller would start anyway. The token also invalidates a thread that was superseded by a
    newer launch request before it got to its next check.
    """
    global _mineflayer_wait_thread, _mineflayer_launch_token
    _mineflayer_pending_abort.set()
    _mineflayer_launch_token += 1
    _mineflayer_wait_thread = None


def _launch_mineflayer_bot(server: ServerInterface, bot_config: dict, mineflayer_init_js_path: str):
    if _mineflayer_pending_abort.is_set():
        server.logger.info(f"{plugin_config.prefix} Mineflayer bot launch cancelled before it started")
        return
    node_path = shutil.which("node")
    if not node_path:
        server.logger.warning(f"{plugin_config.prefix} Mineflayer bot is enabled but Node.js was not found. Disabling and reloading...")
        _disable_mineflayer_and_reload(server)
    else:
        ws_cfg = bot_config.get("websocket", {})
        ws_url = plugin_config.websocket_uri or ws_cfg.get("url") or DEFAULT_WEBSOCKET_URI
        server.logger.info(f"{plugin_config.prefix} Mineflayer bot will register on the cross-server hub at {ws_url}")
        try:
            version_output = subprocess.check_output([node_path, "--version"], text=True, timeout=5).strip()
            if version_output.startswith("v"):
                version_output = version_output[1:]
            major = int(version_output.split(".")[0])
            if major < 18:
                server.logger.warning(
                    f"{plugin_config.prefix} Mineflayer requires Node.js >= 18, but found v{version_output}. "
                    f"Disabling and reloading..."
                )
                _disable_mineflayer_and_reload(server)
            else:
                try:
                    run_node(mineflayer_init_js_path, logger=server.logger)
                except (RuntimeError, FileNotFoundError) as e:
                    server.logger.error(f"{plugin_config.prefix} Failed to launch Mineflayer bot: {e}")
                    return
                if _mineflayer_pending_abort.is_set():
                    # The plugin was unloaded (or the bot disabled) while `run_node` was installing
                    # dependencies: the process it just created must not outlive this decision.
                    server.logger.info(f"{plugin_config.prefix} Mineflayer bot launch cancelled after "
                                       f"the node process started; stopping it")
                    stop_mineflayer_process()
                    return
                server.logger.info(f"{plugin_config.prefix} Mineflayer JS bot launched (Node.js v{version_output})")
                manager = _cross_server
                if manager is None:
                    server.logger.warning(
                        f"{plugin_config.prefix} No cross-server link is running, so the bot has nothing to "
                        f"connect to and its tools stay unavailable"
                    )
                else:
                    set_bot_peer(manager, plugin_config.bot_username, server.logger)
                    server.logger.info(
                        f"{plugin_config.prefix} The bot is expected on {manager.peer_uri} as {plugin_config.bot_username!r}"
                    )
                if _mineflayer_pending_abort.is_set():
                    server.logger.info(f"{plugin_config.prefix} Mineflayer bot launch cancelled before the "
                                       f"controller started; stopping the node process")
                    clear_bot_peer()
                    stop_mineflayer_process()
                    return
                try:
                    default_ai_info = plugin_config.all_ai.get(plugin_config.default_ai, None)
                    if default_ai_info is not None:
                        global _autonomous_controller
                        _autonomous_controller = AutonomousBotController(
                            ws_client=get_mineflayer_client(),
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
                        server.logger.info(f"{plugin_config.prefix} AutonomousBot controller started")
                    else:
                        server.logger.warning(f"{plugin_config.prefix} No default AI configured, AutonomousBot controller skipped")
                except Exception as e:
                    server.logger.warning(f"{plugin_config.prefix} Failed to start the autonomous bot controller: {e}")
        except (subprocess.TimeoutExpired, ValueError, OSError) as e:
            server.logger.warning(f"{plugin_config.prefix} Failed to detect Node.js version: {e}. Skipping bot startup.")


def _apply_config(server: PluginServerInterface, config: dict):
    """
    Apply the configuration for the GamesAI plugin.
    """
    plugin_config.prefix = config.get('prefix', '[GamesAI]')
    plugin_config.allow_permission = config.get('permission', 3)

    ws_cfg = config.get("websocket", {}) or {}
    plugin_config.websocket_uri = str(ws_cfg.get("uri", "") or "").strip()
    plugin_config.websocket_force_server = bool(ws_cfg.get("force_server", False))
    plugin_config.websocket_name = str(ws_cfg.get("name", "") or "").strip()
    # Hub side: validity of the tokens this instance issues. -1 = unlimited; anything else
    # that is not a positive number falls back to -1 instead of failing the load.
    try:
        ttl_hours = int(ws_cfg.get("token_ttl_hours", -1))
    except (TypeError, ValueError):
        server.logger.warning(
            f"{plugin_config.prefix} websocket.token_ttl_hours must be a whole number of hours, "
            f"using -1 (unlimited)"
        )
        ttl_hours = -1
    if ttl_hours == 0 or ttl_hours < -1:
        server.logger.warning(
            f"{plugin_config.prefix} websocket.token_ttl_hours={ttl_hours} is not usable, using -1 (unlimited)"
        )
        ttl_hours = -1
    plugin_config.websocket_token_ttl_hours = ttl_hours
    plugin_config.websocket_auto_enroll = bool(ws_cfg.get("auto_enroll", True))
    plugin_config.websocket_identity_file = str(ws_cfg.get("identity_file", "") or "").strip()
    # The peer name is the configured one, or one derived from this instance's own directory
    # (see _default_instance_name). The hostname is not usable as a default: every instance on
    # one machine shares it, and it changes when the machine is renamed -- while an enrolment
    # is bound to the name, so either way the link breaks for reasons the operator never chose.
    plugin_config.cross_server_name, name_is_derived = _resolve_cross_server_name(
        server, plugin_config.websocket_name)
    if name_is_derived:
        server.logger.info(
            f"{plugin_config.prefix} websocket.name is empty, so this instance is "
            f"{plugin_config.cross_server_name!r} (derived from "
            f"{_instance_root(server) or 'the current directory'}); set websocket.name to "
            f"choose a name you can read at a glance"
        )

    extra_apps: list[str] = []
    raw_apps = ws_cfg.get("allow_app_id", [])
    if isinstance(raw_apps, str):                     # tolerate a single string
        raw_apps = [raw_apps]
    if isinstance(raw_apps, list):
        for entry in raw_apps:
            if not isinstance(entry, str) or not entry.strip():
                server.logger.warning(f"{plugin_config.prefix} Ignoring an invalid websocket.allow_app_id entry: {entry!r}")
                continue
            app_id = entry.strip()
            if app_id in extra_apps:
                continue
            extra_apps.append(app_id)
    elif raw_apps:
        server.logger.warning(f"{plugin_config.prefix} websocket.allow_app_id must be a list, ignoring {raw_apps!r}")
    plugin_config.websocket_allow_app_id = extra_apps

    prompt_dir = os.path.join(os.path.dirname(os.path.dirname(plugin_config.skills_path)), "prompt")
    if not os.path.exists(prompt_dir):
        os.makedirs(prompt_dir, exist_ok=True)

    ai_models = {}
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
                server.logger.info(f"{plugin_config.prefix} Loaded prompt from file: {prompt_full_path}")
            except FileNotFoundError:
                server.logger.warning(f"{plugin_config.prefix} Prompt file not found: {prompt_full_path}, using default prompt")
                raw_prompt = str(server.rtr("games_ai.system_message.default"))
        context_window = ai_config.get("context_window")
        try:
            context_window = int(context_window) if context_window is not None else None
        except (TypeError, ValueError):
            server.logger.warning(f"{plugin_config.prefix} Invalid context_window for AI '{ai_id}', ignoring it")
            context_window = None
        ai_models[ai_id] = {
            "prompt": raw_prompt,
            "ai_name": ai_config.get("ai_name", "[GamesAI]"),
            "base_url": ai_config.get("base_url", ""),
            "ai_model": ai_config.get("ai_model", ""),
            "api_key": ai_config.get("api_key", ""),
            "extra_body": ai_config.get("extra_body", {}),
            "context_window": context_window,
        }

    plugin_config.all_ai = ai_models
    plugin_config.default_ai = config.get("default_ai",
                                          list(ai_models.keys())[0] if ai_models else "")

    bot_cfg = config.get("mineflayer_bot", {}).get("bot", {})
    plugin_config.bot_username = bot_cfg.get("username", "Bot")

#: Every key of the ``websocket`` block with its default, as one literal. Referenced by both the
#: default config and the migration below so the two can never drift apart: a migration that only
#: wrote the keys it happened to know about left users with a config whose every other documented
#: key looked missing.
DEFAULT_WEBSOCKET_CONFIG: dict = {
    "uri": "ws://127.0.0.1:8080",
    "force_server": False,
    "allow_app_id": [],
    "name": "",
    "token_ttl_hours": -1,
    "auto_enroll": True,
    "identity_file": "",
}


def _default_websocket_block() -> dict:
    """A fresh copy of the default ``websocket`` block (the list must not be shared)."""
    block = dict(DEFAULT_WEBSOCKET_CONFIG)
    block["allow_app_id"] = list(DEFAULT_WEBSOCKET_CONFIG["allow_app_id"])
    return block


def _migrate_config_data(raw) -> bool:
    """Config migration hook (MCDR ``data_processor``) for the cross-server release.

    0.7.x kept the bot's WebSocket address in ``mineflayer_bot.websocket``; the plugin owns
    that address now, so it moves to the top-level ``websocket``. The 0.8.0 shared secret
    ``websocket.token`` is gone as well -- every node claims its own token -- so a stale key
    is dropped here rather than read anywhere. This runs on the data read from config.json
    *before* MCDR fills in the missing default keys -- which is what makes ``"websocket" in
    raw`` a reliable "the user never wrote the new key" test. MCDR saves the file when this
    returns True.
    """
    global _config_migration_note
    if not isinstance(raw, dict):
        return False
    changed = False
    notes: list[str] = []

    ws_block = raw.get("websocket")
    if isinstance(ws_block, dict):
        if "token" in ws_block:
            # Never read again: a shared secret cannot be turned into per-node tokens, and
            # silently keeping it in the file would only invite a user to trust it.
            ws_block.pop("token", None)
            changed = True
            notes.append("dropped the obsolete websocket.token (each node claims its own token "
                         "with !!gamesai node claim)")
        # Complete the block instead of patching one key: a ``websocket`` block that carries only
        # ``uri`` makes every other key the documentation lists look missing to the user.
        missing = [key for key in DEFAULT_WEBSOCKET_CONFIG if key not in ws_block]
        if missing:
            defaults = _default_websocket_block()
            for key in missing:
                ws_block[key] = defaults[key]
            changed = True
            notes.append("added the missing websocket keys: " + ", ".join(sorted(missing)))

    bot_block = raw.get("mineflayer_bot")
    if isinstance(bot_block, dict):
        old_ws = bot_block.get("websocket")
        if isinstance(old_ws, dict):
            bot_block.pop("websocket")
            old_url = str(old_ws.get("url", "") or "").strip()
            if "websocket" not in raw and old_url:
                # Complete block, not just the key that moved; an absent address is not invented.
                block = _default_websocket_block()
                block["uri"] = old_url
                raw["websocket"] = block
                notes.append(f"mineflayer_bot.websocket.url -> websocket.uri ({old_url})")
                notes.append("wrote the websocket block with its defaults")
            else:
                notes.append("removed the obsolete mineflayer_bot.websocket block")
            changed = True

    if notes:
        _config_migration_note = "; ".join(notes)
    return changed


# ── node enrolment: this instance's identity file and the hub's node table ──────────────
# The hub keeps hashes only (websockets_server.py owns the format); a node keeps its own
# token in plain text, because there is no portable way to bind it to the OS account.
#
# All of the link's runtime state lives in one sub-folder of the data folder, so the data folder
# root stays readable: the node's own token, the hub's node table, and the role memory. The
# names below are the files *inside* ``cross_server/``; ``_LEGACY_STATE_FILES`` maps the places
# they used to have (0.8.0-SNAPSHOT-8 and earlier) onto them, and :func:`_migrate_state_file`
# moves them over once, so an installation that is already enrolled keeps its token.
_CROSS_SERVER_DIR = "cross_server"
_IDENTITY_FILE = "identity.json"
_NODE_TABLE_FILE = "nodes.json"
_CROSS_SERVER_ROLE_FILE = "role.json"
_LEGACY_STATE_FILES = {
    "cross_server_identity.json": _IDENTITY_FILE,
    "cross_server_nodes.json": _NODE_TABLE_FILE,
    "cross_server_role.json": _CROSS_SERVER_ROLE_FILE,
}
_state_files_lock = threading.Lock()
#: Destination paths whose migration was already attempted in this load (the lookup runs often;
#: a second look would only repeat the same checks and log lines).
_state_files_seen: set[str] = set()


def _cross_server_dir(server: PluginServerInterface | None = None) -> str | None:
    """The folder holding the link's runtime state, or None without a data folder."""
    folder = _data_folder(server)
    return os.path.join(folder, _CROSS_SERVER_DIR) if folder else None


def _cross_server_state_path(server: PluginServerInterface | None, name: str) -> str | None:
    """Path of one file in that folder, migrating its old location on first use.

    Returns the *old* path when the file is still there and could not be moved (an uncreatable
    folder, a locked file): losing sight of an identity file would cost the instance its
    enrolment and make an operator re-issue a token, which is a much worse outcome than using a
    file in the previous place for one more load.
    """
    folder = _cross_server_dir(server)
    if not folder:
        return None
    path = os.path.join(folder, name)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        pass                                    # the writers report their own failure
    legacy = None
    for old_name, target in _LEGACY_STATE_FILES.items():
        if target == name:
            root = _data_folder(server)
            legacy = os.path.join(root, old_name) if root else None
            break
    if legacy is not None:
        _migrate_state_file(legacy, path)
        if not os.path.exists(path) and os.path.isfile(legacy):
            return legacy
    return path


def _migrate_state_file(old: str, new: str) -> None:
    """Move one state file out of the data folder root; never raises, runs at most once.

    Called on every path lookup, so the work is cached per destination path and per load. Both
    existing is the one case worth a warning: nothing is deleted then, the new location simply
    wins.
    """
    with _state_files_lock:
        if new in _state_files_seen:
            return
        _state_files_seen.add(new)
    try:
        if not os.path.isfile(old):
            return
        if os.path.exists(new):
            logger.log("warning", f"{plugin_config.prefix}Both {old} and {new} exist; using {new} and leaving "
                                  f"the old file alone")
            return
        try:
            os.replace(old, new)
        except OSError:
            shutil.copy2(old, new)              # a locked source still lets the move finish
            try:
                os.remove(old)
            except OSError:
                pass
        logger.log("info", f"{plugin_config.prefix}Cross-server state moved: {old} -> {new}")
    except OSError as e:
        logger.log("warning", f"{plugin_config.prefix}Could not move {old} into {new}: {e}")


def _plugin_server(source: CommandSource | None = None) -> PluginServerInterface | None:
    """The interface that can answer plugin-only questions, whatever the command source is.

    MCDR builds every command source on its **base** ``ServerInterface``:
    ``PlayerCommandSource.get_server()`` and ``ConsoleCommandSource.get_server()`` both return
    ``mcdr_server.basic_server_interface``, and only :class:`PluginServerInterface` knows this
    plugin's data folder (``get_data_folder()`` lives there and nowhere else). Every read or
    write of the identity file, the node table or the bot config therefore has to go through
    the interface ``on_load`` received -- asking the command source for it silently degrades to
    "this plugin has no data folder", which is how ``!!gamesai node claim`` could report
    success while writing nothing.
    """
    if _server_ref is not None:
        return _server_ref
    if source is None:
        return None
    try:
        return source.get_server()
    except Exception:
        return None


def _data_folder(server: PluginServerInterface | None = None) -> str | None:
    """The plugin's data folder (``config/games_ai``), or None when it cannot be asked.

    The server handed in is tried first, then the module reference ``on_load`` stored: a
    command source only ever hands back MCDR's base interface, which has no
    ``get_data_folder`` (see :func:`_plugin_server`).
    """
    for target in (server, _server_ref):
        if target is None:
            continue
        try:
            folder = target.get_data_folder()
        except Exception:
            continue
        if folder:
            return str(folder)
    return None


_INSTANCE_NAME_MAX = 40
_INSTANCE_NAME_FALLBACK = "gamesai"
_INSTANCE_NAME_HASH_LENGTH = 6


def _instance_root(server: PluginServerInterface | None = None) -> str:
    """This MCDR instance's own directory (the parent of ``config/``), or "" when unknown.

    MCDR documents the plugin data folder as ``config/<plugin_id>`` inside the instance
    directory, so two directories up from it is the instance itself -- the one path that is
    both unique per installation and independent of the machine name.
    """
    folder = _data_folder(server)
    if folder:
        root = os.path.dirname(os.path.dirname(os.path.abspath(folder)))
        if os.path.isdir(root):
            return root
    try:
        return os.path.abspath(os.getcwd())
    except OSError:
        return ""


def _sanitize_instance_name(text: str) -> str:
    """Make a directory name typable in ``!!gamesai node token <name>``.

    Only letters, digits, ``-``, ``_`` and ``.`` survive; runs of anything else collapse to one
    ``-``. A name with spaces or CJK in it cannot be pasted into the command, and a name that
    contains a newline would split the log line that announces it.
    """
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "-", str(text or "")).strip("-._")
    return cleaned[:_INSTANCE_NAME_MAX].strip("-._")


def _default_instance_name(server: PluginServerInterface | None = None) -> str:
    """A name for this instance that needs no configuration and cannot collide on one machine.

    ``websocket.name`` is the documented way to name an instance; the *default* used to be
    ``socket.gethostname()``, which is wrong in two ways. Every instance on one machine shares
    it -- and the hub keys its node table by name, so the second enrolment silently takes the
    first node's token away (close code 4001, not retryable, so that node stays down until
    somebody reloads it). And it changes when the machine is renamed (cloud instance, domain
    join, container), while the identity file is bound to the name, so the link breaks for a
    reason the operator never chose.

    The instance directory has neither problem: its basename is the readable half
    (``survival``) and a short hash of the absolute path is the unique half
    (``survival-9f31ab``), so two installations that are both called ``server`` still differ.
    Renaming the directory does change the name -- and that needs a new enrolment, exactly
    like editing ``websocket.name`` does; the existing warning about a mismatched identity
    file says what to do.
    """
    root = _instance_root(server)
    base = _sanitize_instance_name(os.path.basename(root)) if root else ""
    if not base:
        base = _INSTANCE_NAME_FALLBACK
    # normcase so that the same directory written with different letter case on Windows keeps
    # producing the same name.
    digest = hashlib.sha256(os.path.normcase(root or base).encode("utf-8")).hexdigest()
    return f"{base}-{digest[:_INSTANCE_NAME_HASH_LENGTH]}"


def _resolve_cross_server_name(server: PluginServerInterface | None,
                               configured: str) -> tuple[str, bool]:
    """The name this instance registers under, and whether it had to be derived.

    ``websocket.name`` wins whenever it is set. Otherwise the name comes from this instance's
    directory (:func:`_default_instance_name`), which is what keeps two instances on one
    machine apart and survives a machine rename.
    """
    configured = str(configured or "").strip()
    if configured:
        return configured, False
    return _default_instance_name(server), True


def _identity_path(server: PluginServerInterface | None = None) -> str | None:
    """Where this instance keeps its own token (``websocket.identity_file`` overrides it).

    The override is taken verbatim (as an absolute path), because an operator who names a file
    means that file; the default moves with the rest of the link state.
    """
    override = (plugin_config.websocket_identity_file or "").strip()
    if override:
        return os.path.abspath(override)
    return _cross_server_state_path(server, _IDENTITY_FILE)


def _node_table_path(server: PluginServerInterface | None = None) -> str | None:
    """Where this instance keeps the hub-side node table."""
    return _cross_server_state_path(server, _NODE_TABLE_FILE)


def _load_identity(server: PluginServerInterface | None = None) -> dict | None:
    """Read this node's identity file. None when it is missing, unreadable or incomplete.

    A corrupt file is treated exactly like "no identity": the node asks to enrol again and
    logs the path, instead of failing to load.
    """
    path = _identity_path(server)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            identity = json.load(handle)
    except (OSError, ValueError):
        logger.log("warning", f"{plugin_config.prefix} Cannot read the identity file {path}; treating this "
                             f"instance as not enrolled")
        return None
    if not isinstance(identity, dict) or not str(identity.get("token") or "").strip():
        logger.log("warning", f"{plugin_config.prefix} The identity file {path} carries no token; treating "
                             f"this instance as not enrolled")
        return None
    return identity


def _save_identity(server: PluginServerInterface, name: str, token: str, hub: str) -> str | None:
    """Write this node's identity file (chmod 600 on POSIX, best effort). Returns its path."""
    path = _identity_path(server)
    if not path:
        return None
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    payload = {
        "name": str(name),
        "token": str(token),
        "hub": str(hub),
        "issued_at": int(time.time()),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass                                     # Windows and odd filesystems: best effort
    return path


def _delete_identity(server: PluginServerInterface | None = None) -> str | None:
    """Delete this node's identity file. Returns the path when a file was removed."""
    path = _identity_path(server)
    if not path or not os.path.isfile(path):
        return None
    try:
        os.remove(path)
    except OSError:
        logger.log("exception", f"{plugin_config.prefix} Failed to delete the identity file {path}")
        return None
    return path


def _identity_token_for_link(server: PluginServerInterface, uri: str) -> str:
    """The token this instance may present to ``uri``, or "" when it must enrol first.

    A token is bound to one name and to the hub it was issued for: a name change or a
    different hub makes the stored identity unusable, and saying so here gives the operator
    an actionable line instead of a bare rejection from the hub.
    """
    identity = _load_identity(server)
    if identity is None:
        return ""
    stored_name = str(identity.get("name") or "")
    if stored_name != plugin_config.cross_server_name:
        logger.log("warning",
                  f"{plugin_config.prefix} The identity file is bound to node {stored_name!r}, but this "
                  f"instance is {plugin_config.cross_server_name!r}; run !!gamesai node forget "
                  f"and claim a token for this name")
        return ""
    stored_hub = str(identity.get("hub") or "")
    if stored_hub and uri and stored_hub != uri:
        logger.log("warning",
                  f"{plugin_config.prefix} The identity file was issued by the hub at {stored_hub}, not "
                  f"{uri}; run !!gamesai node forget and claim a token from this hub")
        return ""
    return str(identity.get("token") or "")


def _identity_fingerprint(server: PluginServerInterface | None = None) -> str | None:
    """The fingerprint of this instance's own token (never the token itself)."""
    identity = _load_identity(server)
    if identity is None:
        return None
    return token_fingerprint(str(identity.get("token") or ""))


def _cross_server_role_path(server: PluginServerInterface) -> str | None:
    """Where the last decided role is remembered; None when there is no data folder.

    Goes through :func:`_data_folder` like the identity file: both are plugin data, and only
    the plugin interface knows where that lives.
    """
    return _cross_server_state_path(server, _CROSS_SERVER_ROLE_FILE)


def _read_cross_server_role(server: PluginServerInterface) -> str | None:
    """The role held on the last load, so a reload cannot swap the hub and a client.

    Two instances on one machine share one address: without this memory, whichever loads first
    after a cluster reload binds the port and the other becomes its client, which sticks.
    """
    path = _cross_server_role_path(server)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            role = str(json.load(handle).get("role") or "").strip()
    except (OSError, ValueError):
        return None
    return role if role in (MODE_SERVER, MODE_CLIENT, MODE_LOCAL) else None


def _save_cross_server_role(server: PluginServerInterface, role: str) -> None:
    path = _cross_server_role_path(server)
    if not path or role not in (MODE_SERVER, MODE_CLIENT, MODE_LOCAL):
        return
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"role": role}, handle)
    except OSError:
        logger.log("exception", "failed to remember the cross-server role")


_config_ref: dict | None = None


def _start_cross_server(server: PluginServerInterface, config: dict, on_ready=None) -> None:
    """Create this instance's cross-server link, deciding the role on a background thread.

    The probe dials the configured uri, so it must not run inside ``on_load``: MCDR would
    wait for the connection attempt before the plugin is considered loaded. ``on_ready`` runs
    on that same thread once the role is settled -- that is when the bot's address is known.
    """
    global _cross_server, _cross_server_thread, _config_ref, _server_ref

    _config_ref = config
    _server_ref = server
    logger.attach(server)
    # What the update path may read, and when: see games_ai/update/update_round.py.
    update_round.attach(
        server_of=_plugin_server,
        manager_of=lambda: _cross_server,
        link_thread_of=lambda: _cross_server_thread,
        version=str(PLUGIN_METADATA.get("version", "")),
    )
    uri = plugin_config.websocket_uri
    manager = None
    if not uri:
        server.logger.error(
            f"{plugin_config.prefix} Cross-server is off: websocket.uri is empty, so the Mineflayer bot has "
            f"nothing to connect to either"
        )
    else:
        manager = CrossServerManager(
            uri,
            name=plugin_config.cross_server_name,
            version=str(PLUGIN_METADATA.get("version", "")),
            force_server=plugin_config.websocket_force_server,
            handler=_on_cross_message,
            allow_app_id=plugin_config.websocket_allow_app_id,
            # The node's own token, from its identity file; "" means "enrol first".
            token=_identity_token_for_link(server, uri),
            auto_enroll=plugin_config.websocket_auto_enroll,
            # Hub side: the node table and the TTL of everything this instance issues.
            node_file=_node_table_path(server),
            ttl_hours=plugin_config.websocket_token_ttl_hours,
            on_bot_token=lambda name, token: _store_bot_token(server, name, token),
            on_peer_registered=update_round._on_peer_registered,
            logger=server.logger,
        )
        _cross_server = manager
        plugin_config.cross_server_mode = "pending"

    def _decide() -> None:
        try:
            if manager is not None:
                manager.role_hint = _read_cross_server_role(server)
                manager.start()
                if _cross_server is not manager:
                    # Unloaded (or replaced) while deciding: stop() already ran, so leave the
                    # globals of the new instance alone.
                    return
                if manager.is_server:
                    server.logger.info(
                        f"{plugin_config.prefix} This instance is the cross-server hub; a node enrols with "
                        f"!!gamesai node pending on this instance and !!gamesai node token <name>"
                    )
                elif not manager.enrolled:
                    # start() already logged the actionable line; this is the short form for
                    # the log tail.
                    server.logger.info(
                        f"{plugin_config.prefix} Cross-server stays local: this instance is not enrolled "
                        f"(!!gamesai node claim <token>)"
                    )
        except Exception:
            server.logger.exception(f"{plugin_config.prefix} The cross-server decision failed")
        finally:
            if _cross_server is manager:
                plugin_config.cross_server_mode = manager.mode if manager is not None else MODE_LOCAL
                # Remember how this load ended: the next one starts from it instead of racing
                # the other instance for the port (see decide_mode's previous_role).
                _save_cross_server_role(server, plugin_config.cross_server_mode)
                # Started here rather than in on_load: the role decides whether this instance
                # may check for updates at all (a client never does), and this block is the one
                # place that always runs once the role is settled.
                update_round._start_update_loop(server)
        if on_ready is not None and _cross_server is manager:
            try:
                on_ready()
            except Exception:
                server.logger.exception(f"{plugin_config.prefix} Failed to bring up the Mineflayer bot link")

    _cross_server_thread = threading.Thread(
        target=_decide, name="games_ai@cross_server", daemon=True
    )
    _cross_server_thread.start()


def _repoint_bot_after_role_change(server: PluginServerInterface, config: dict,
                                   previous_peer_uri: str, bot_was_running: bool) -> None:
    """Point the Mineflayer bot at the hub this instance ended up with.

    The bot is a client of whichever hub this instance has, so its address is
    ``manager.peer_uri``: the loopback hub this instance hosts in local mode (a random
    ``127.0.0.1`` port), or the hub it dials as a client. A runtime claim moves the instance
    from the first to the second, and a bot left dialling the old port registers nowhere --
    its JS config still names that port on the next start, too. Only a real change is acted
    on, and a bot that was not running is never started here.
    """
    if not config:
        # A rewrite from an empty config would drop every bot setting it does not carry
        # (enabled, cycle_interval): leave the file alone rather than damage it.
        server.logger.warning(
            f"{plugin_config.prefix} No loaded config, so the Mineflayer bot's address was not rewritten"
        )
        return
    manager = _cross_server
    if manager is None:
        return
    peer_uri = manager.peer_uri
    if not peer_uri or peer_uri == previous_peer_uri:
        return                      # the address did not change: the bot is still right
    _write_mineflayer_config(server, config, peer_uri)
    server.logger.info(
        f"{plugin_config.prefix} The Mineflayer bot's hub address changed to {peer_uri} "
        f"(it was {previous_peer_uri or 'unset'}); its config was rewritten"
    )
    if not bot_was_running:
        return                      # nothing was running: this path never starts a bot
    failed = _stop_bot_stack(server)
    if failed:
        server.logger.warning(
            f"{plugin_config.prefix} Failed to stop the running Mineflayer bot before re-pointing it: "
            f"{', '.join(failed)}"
        )
    try:
        _run_mineflayer_bot(server, config.get("mineflayer_bot", {}),
                            plugin_config.mineflayer_init_js_path)
    except Exception as e:
        server.logger.exception(f"{plugin_config.prefix} Failed to restart the Mineflayer bot on {peer_uri}: {e}")


def _restart_cross_server(server: PluginServerInterface) -> None:
    """Rebuild the link after the identity file changed (``node claim`` / ``node forget``).

    The role is decided again from scratch: an instance that was unenrolled was in local
    mode, so only a fresh decision can turn it into a client of the hub it just claimed.

    The bot follows that decision: a local -> client transition moves its hub from the
    loopback address this instance hosted to the remote one (and back on client -> local), so
    once the new role is in its config is rewritten and a running bot process is restarted
    (see :func:`_repoint_bot_after_role_change`).
    """
    manager = _cross_server
    previous_peer_uri = manager.peer_uri if manager is not None else ""
    bot_was_running = is_node_running()
    config = _config_ref or {}

    def _on_ready() -> None:
        _repoint_bot_after_role_change(server, config, previous_peer_uri, bot_was_running)

    _stop_cross_server(server)
    _start_cross_server(server, config, on_ready=_on_ready)


def _stop_cross_server(server: PluginServerInterface | None = None) -> None:
    """Stop the link synchronously: it holds a port (hub) or a socket (node)."""
    global _cross_server, _cross_server_thread
    manager, _cross_server = _cross_server, None
    thread, _cross_server_thread = _cross_server_thread, None
    plugin_config.cross_server_mode = MODE_LOCAL
    _remote_sessions.clear()
    with _player_servers_lock:
        _player_servers.clear()
    if manager is None:
        return
    manager.stop()
    # The probe can still be in flight; a short join keeps the ordinary unload synchronous,
    # and anything it builds afterwards stops itself (see CrossServerManager.stop).
    if thread is not None and thread.is_alive():
        thread.join(2.0)
        if thread.is_alive() and server is not None:
            server.logger.info(
                f"{plugin_config.prefix} The cross-server decision is still finishing in the background; "
                f"it will stop whatever it built on its own"
            )
    if server is not None:
        server.logger.info(f"{plugin_config.prefix} Cross-server link stopped")


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
    3. the Node process is detached from :mod:`games_ai.bot.mineflayer` and hard-killed. It may
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

    # A launch that is still waiting for the server (or blocked in `run_node`) belongs to the
    # bot this call is shutting down: cancel it before touching the parts it may create.
    _cancel_pending_bot_launch()

    log = logger if logger is not None else (server.logger if server is not None else None)
    failed: list[str] = []

    def step(name: str, action):
        try:
            action()
        except Exception as e:
            failed.append(name)
            if log is not None:
                log.exception(f"{plugin_config.prefix} Cleanup step '{name}' failed: {e}")

    controller = _autonomous_controller
    _autonomous_controller = None
    # force=True + a short grace: an idle loop leaves at once, and a busy one gets an abort
    # injected instead of blocking the unload for the whole cooperative timeout
    step("stop the autonomous bot controller",
         lambda: controller.stop(timeout=_BOT_STOP_GRACE, force=True) if controller is not None else None)
    step("clear the bot controller registry", lambda: set_bot_controller(None))
    step("clear the bot link", clear_bot_peer)
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
    global _history_frozen

    # Nothing of this instance was started, so nothing has to be torn down -- but a pip child of
    # the dependency repair may still be running and must not outlive the plugin.
    if _deps_pending:
        _DEP_INSTALL_ABORT.set()
        server.logger.info(f"{plugin_config.prefix}Dependencies are still missing; nothing to tear down")
        return

    # From here on this instance stores nothing any more: a round that is still finishing on
    # this very thread would otherwise write its (older) state over what a freshly loaded
    # instance may already have produced. Everything up to the last completed round is already
    # on disk, so there is nothing to flush either.
    _history_frozen = True

    _mineflayer_pending_abort.set()             # cancels the pending "wait for server" thread
    _mineflayer_wait_thread = None
    _restore_thread_excepthook()
    _stop_cross_server(server)                  # holds a port / socket: stop it before anything slow
    update_round.stop_timer()

    teardown = _teardown_bot_async(server)
    if not _bot_teardown_event.wait(_BOT_UNLOAD_GRACE):
        server.logger.info(
            f"{plugin_config.prefix} Bot teardown is still running in the background "
            f"(waited {_BOT_UNLOAD_GRACE:.1f}s); it will finish on its own"
        )

    still_alive = sorted(t.name for t in threading.enumerate() if t.name in _PLUGIN_THREAD_NAMES)
    if still_alive:
        server.logger.warning(
            f"{plugin_config.prefix} Threads still alive after unload: {', '.join(still_alive)} "
            f"(daemon threads; an in-flight round finishes its current API call first, then exits)"
        )
    if teardown.is_alive():
        server.logger.info(f"{plugin_config.prefix} Mineflayer bot stop is delegated to the background teardown thread")
    else:
        server.logger.info(f"{plugin_config.prefix} Mineflayer bot stopped successfully!")
    server.logger.info(f"{plugin_config.prefix} Mineflayer bot process has been terminated successfully!")
    server.logger.info(f"{plugin_config.prefix}{server.rtr("games_ai.unload_message.server_info")}")
    
    # Unload the extensions this instance registered. This runs inside MCDR's own plugin
    # manipulation chain (on_unload is called from __unload_plugin), so a nested unload is
    # queued instead of executed and MCDR's unload_plugin answers None for both "queued" and
    # "plugin not found". A plugin that is still loaded therefore means "queued" -- the actual
    # unload follows right after this operation, and MCDR's dependency collection also unloads
    # dependents -- while only a really missing plugin is reported as not found and dropped.
    for plugin_id in list(REGISTER_PLUGIN_LIST.keys()):
        try:
            server.logger.info(f"{plugin_config.prefix} Unloading registered extension plugin '{plugin_id}'")
            result = server.unload_plugin(plugin_id)
            if result is None:
                try:
                    still_loaded = server.get_plugin_instance(plugin_id) is not None
                except Exception:
                    still_loaded = False
                if still_loaded:
                    server.logger.info(
                        f"{plugin_config.prefix} Unload of '{plugin_id}' queued by MCDR (chained plugin "
                        f"operation); it runs after the current one")
                else:
                    server.logger.warning(f"{plugin_config.prefix} Registered plugin '{plugin_id}' not found, removed from unload list")
                    REGISTER_PLUGIN_LIST.pop(plugin_id, None)
            elif not result:
                server.logger.warning(f"{plugin_config.prefix} Failed to unload registered plugin '{plugin_id}'")
        except Exception as e:
            server.logger.exception(f"{plugin_config.prefix} Error while unloading registered plugin '{plugin_id}': {e}")
    REGISTER_PLUGIN_LIST.clear()
    # The one public-database connection of this plugin load is closed here. A thread that is
    # still finishing calls public_database() and gets a clear "not open" error (tool errors
    # are reported as tool results), instead of touching a closed SQLite handle.
    database.close_public_database()
    unload_status = update_round.unload_status()
    if unload_status == 0:
        server.say(f'{plugin_config.prefix}Bye!')
    elif unload_status == 1:
        server.say(f'{plugin_config.prefix}{server.rtr("games_ai.unload_message.after_update_restart_msg")}')


def _history_store() -> ChatHistoryStore | None:
    """The conversation store, or None while this instance has no data folder yet."""
    path = str(plugin_config.data_path or "")
    if not path:
        return None
    return ChatHistoryStore(path)


def _restore_all_histories(server: PluginServerInterface) -> None:
    """Bring every stored conversation back into ``all_chat_param``.

    Runs once per load, after the config is applied (the AI entries decide whether a stored
    conversation can be rebuilt at all) and before any command can be typed. Every row stands on
    its own: a conversation whose model was removed from the config, whose JSON is unreadable or
    whose format is newer than this build is skipped with one log line, and a stored conversation
    never keeps the plugin from loading.
    """
    store = _history_store()
    if store is None:
        return
    started = time.monotonic()
    try:
        rows = store.load_all()
    except Exception as e:
        logger.log("exception", f"{plugin_config.prefix}Failed to read the stored conversations: {e}")
        return

    restored = 0
    for row in rows:
        user = str(row.get("user") or "")
        if not user or user in all_chat_param:
            continue
        try:
            if int(row.get("format") or 0) != _HISTORY_FORMAT:
                logger.log("warning", f"{plugin_config.prefix}Skipping the stored conversation of {user!r}: "
                                     f"format {row.get('format')!r} is not {_HISTORY_FORMAT}")
                continue
            record = json.loads(str(row.get("payload") or ""))
            if not isinstance(record, dict):
                raise ValueError("the stored payload is not an object")
            stored_model = str(row.get("model_id") or "")
            model_id = stored_model if stored_model in plugin_config.all_ai else plugin_config.default_ai
            if model_id != stored_model:
                logger.log("warning",
                          f"{plugin_config.prefix}The stored conversation of {user!r} used model "
                          f"{stored_model!r}, which is not configured; continuing it with "
                          f"{model_id!r}")
            if model_id not in plugin_config.all_ai:
                logger.log("warning", f"{plugin_config.prefix}Skipping the stored conversation of {user!r}: "
                                     f"no usable AI entry")
                continue
            chat_param = ChatParam(server, model_id=model_id)
            kept = chat_param.restore(record)
            if not chat_param.has_history():
                store.delete(user)              # an empty conversation is the same as none
                continue
            all_chat_param[user] = chat_param
            restored += 1
            logger.verbose(server, f"[history] {user} restored: {kept} message(s), "
                              f"{len(chat_param.get_response_queue)} queued, model={model_id}")
        except Exception as e:
            logger.log("exception",
                      f"{plugin_config.prefix}Failed to restore the stored conversation of {user!r}: {e}")

    elapsed = (time.monotonic() - started) * 1000
    if rows:
        logger.log("info", f"{plugin_config.prefix}Restored {restored} of {len(rows)} stored conversation(s) "
                          f"from {store.db_path} in {elapsed:.0f} ms")


def _save_history(username: str, chat_param: "ChatParam") -> None:
    """Store one conversation, or drop its row when nothing is left of it.

    Called right after every finished round and after a message was handed to another user.
    Nothing is buffered, so an unload has nothing to flush: what is stored is the state of the
    last completed round. Only a round still in flight when the plugin unloads is left out --
    ``_history_frozen`` then also keeps that late thread from overwriting newer data.
    """
    if _history_frozen or not isinstance(chat_param, ChatParam):
        return
    if all_chat_param.get(username) is not chat_param:
        # The conversation was cleared (``!!gamesai clear``) or replaced while a round of it was
        # still in flight: that detached round must not write the history back. Without this
        # check a clear could be undone a few seconds later by the round it interrupted.
        logger.debug_line(f"{plugin_config.prefix}[history] {username} is no longer the registered "
                          f"conversation; not stored")
        return
    store = _history_store()
    if store is None:
        return
    try:
        if not chat_param.has_history():
            store.delete(username)
            logger.debug_line(f"{plugin_config.prefix}[history] {username} has nothing left, stored row deleted")
            return
        record = chat_param.to_record()
        store.save(username, _HISTORY_FORMAT, chat_param.get_model_id, int(time.time()),
                   record.get("rounds_since_time") or 0,
                   json.dumps(record, ensure_ascii=False))
        logger.debug_line(f"{plugin_config.prefix}[history] {username} stored: "
                    f"{len(record.get('messages') or [])} message(s), "
                    f"{len(record.get('queue') or [])} queued, model={chat_param.get_model_id}")
    except Exception as e:
        logger.log("exception", f"{plugin_config.prefix}Failed to store the conversation of {username!r}: {e}")


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
            source.reply(f"{plugin_config.prefix}{source.get_server().rtr('games_ai.user_message.compact_no_history')}")
            return
        # deferred like the model-switch hand-off: the summarizing request is sent by the
        # next round, so this command returns at once instead of blocking the server thread
        result = user_chat_param.compact_history()
        key = {
            "scheduled": "games_ai.user_message.compact_success",
            "empty": "games_ai.user_message.compact_no_history",
            "running": "games_ai.user_message.compact_failed_running",
        }.get(result, "games_ai.user_message.compact_failed_running")
        source.reply(f"{plugin_config.prefix}{source.get_server().rtr(key)}")
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
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.context_view.missing', player=target)}")
        return
    lines = user_chat_param.context_view()
    source.reply(RTextList(plugin_config.prefix, RText(
        server.rtr("games_ai.context_view.header", player=target), RColor.gold)))
    for index, (line, hover) in enumerate(lines):
        source.reply(RText(f"{plugin_config.prefix}{line}", RColor.white if index == 0 else RColor.gray).h(hover))
    source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.context_view.hover_hint')}")


def aggregate_context_usage() -> tuple[list[dict], dict, list[str]]:
    """
    Sum the context usage of every chatted player, grouped by the configured AI they are on.

    The group is the ``all_ai`` entry (its ``model_id``), not the upstream ``ai_model``: two
    configured AIs may point at the same upstream model and still be two different assistants
    (different ``ai_name``/prompt/key), so they are reported on separate lines. The upstream
    model of each group is carried along for the hover, because that is what the provider bills.

    Reads :meth:`ChatParam.context_usage` for every entry of ``all_chat_param`` and adds the
    plain numbers up, so nothing here can block on a running round. Two groups of numbers are
    kept apart on purpose:

    * ``estimate`` / ``round_*`` — what is *currently* held or was spent in the last round.
      They shrink when a history is compressed or ``!!gamesai clear`` drops an object.
    * ``total_*`` — spent since these conversations were created, accumulated inside
      ``ChatParam`` and stored with the conversation (a restart does not zero them), so a
      compression does not erase the record of what it summarized away.

    :return: ``(models, totals, broken)`` — one dict per configured AI that has any non-zero
             usage, sorted by the currently held context (then by lifetime spend); one dict with
             the sums over all models; and the names whose usage could not be read.
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
        key = str(usage.get("model_id") or usage.get("model") or "?")
        group = groups.get(key)
        if group is None:
            group = groups[key] = {
                "model_id": key, "label": str(usage.get("label") or key),
                "models": set(), "window": 0, "players": 0,
                "estimate": 0, "round_prompt": 0, "round_max_total": 0,
                "total_prompt": 0, "total_completion": 0, "total_cached": 0,
                "total_reasoning": 0,
            }
        if group["label"] == key and usage.get("label"):
            # the first conversation of a group may carry a stale/empty ai_name; a later one
            # with the real name should still name the row
            group["label"] = str(usage["label"])
        upstream = str(usage.get("model") or "")
        if upstream:
            group["models"].add(upstream)
        group["players"] += 1
        # the smallest window of the group is the honest denominator: conversations of the same
        # configured AI may still carry different windows (the entry was edited, or a stored
        # conversation was restored before the reload refreshed its info)
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
    models.sort(key=lambda g: (-g["estimate"], -g["total_prompt"], g["label"], g["model_id"]))
    totals["models"] = len(models)
    return models, totals, broken


def ask_context_server(source: CommandSource):
    """
    ``!!ask context --all`` — the context usage of the whole server, per configured AI.

    Numbers only (no player names): the point is the server-wide picture — which configured AI
    is carrying how much context, how much of it is billed, and how much was served from cache.
    The row is named by the entry's ``ai_name``; the hover names the ``all_ai`` id and the
    upstream ``ai_model`` it actually calls, because several configured AIs may share one
    upstream model (grouping by that model would merge them into one misleading row).

    Hidden are the configured AIs nobody is currently using, i.e. every counter is zero.
    A conversation whose numbers cannot be read is logged and left out; it never hides the rest.
    """
    server = source.get_server()
    models, totals, broken = aggregate_context_usage()
    if broken:
        server.logger.warning(
            f"{plugin_config.prefix} Context usage of {len(broken)} conversation(s) could not be "
            f"read and is not counted: {', '.join(sorted(broken))}")
    if not models:
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.context_all.empty')}")
        return
    source.reply(RTextList(plugin_config.prefix, RText(
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
        label = str(group["label"])
        if "§" in label:
            # ``ai_name`` may carry Minecraft formatting codes of its own (configuration.md
            # allows them). Inside this gray row they override the row color, and a trailing
            # §r leaves everything after the name at the default white. Reset and re-assert the
            # row color right after the name, so only the name keeps its configured formatting.
            line = line.replace(label, f"{label}§r§7", 1)
        upstream = ", ".join(sorted(group["models"])) or group["model_id"]
        hover = str(server.rtr(
            "games_ai.context_all.hover",
            model_id=group["model_id"], model=upstream,
            prompt=f"{group['total_prompt']:,}", completion=f"{group['total_completion']:,}",
            total=f"{group['total_prompt'] + group['total_completion']:,}",
            cached=f"{group['total_cached']:,}", cached_percent=cached_rate,
            reasoning=f"{group['total_reasoning']:,}",
        ))
        source.reply(RText(f"{plugin_config.prefix}{line}", RColor.gray).h(hover))
    held = f"{totals['estimate']:,}"
    source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.context_all.total', estimate=held)}")
    source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.context_all.hover_hint')}")


def _ai_id_for(name_or_id: str) -> str:
    """The AI id behind a configured ``ai_name``, or the input unchanged when nothing matches.

    This replaces the "name_to_id" map that used to be built beside the config: the map had to
    be kept in step with ``plugin_config.all_ai`` by hand, and a reader had to know where it came
    from. A duplicate ``ai_name`` resolves to the last matching entry, exactly as the map did.
    """
    resolved = name_or_id
    for ai_id, info in plugin_config.all_ai.items():
        if info.get("ai_name") == name_or_id:
            resolved = ai_id
    return resolved


@new_thread("games_ai@switch_model")
def switch_model(source: CommandSource, context: dict):
    server = source.get_server()

    username = get_username(source)

    user_input = context.get("model", plugin_config.default_ai)
    model_id = _ai_id_for(user_input)
    ai_info = plugin_config.all_ai.get(model_id)
    may_user_ai = []
    if ai_info is None:
        for ai_id,ai_config in plugin_config.all_ai.items():
            name = ai_config.get("ai_name", "")
            if user_input.lower() in name.lower() or user_input.lower() in ai_id.lower():
                may_user_ai.append(ai_id)
        if len(may_user_ai) == 1:
            model_id = may_user_ai[0]
        elif len(may_user_ai) > 1:
            source.reply(f"{plugin_config.prefix}{server.rtr("games_ai.user_message.model_more")}{may_user_ai}")
            return
        else:
            source.reply(f"{plugin_config.prefix}{server.rtr("games_ai.user_message.model_error")}{list(plugin_config.all_ai.keys())}")
            return

    ai_name = plugin_config.all_ai.get(model_id, {}).get("ai_name", model_id)

    with _conversations_lock:
        conversation = all_chat_param.get(username)
        if conversation is None:
            conversation = ChatParam(server, model_id=model_id)
            all_chat_param[username] = conversation
            created = True
        else:
            created = False
    if created:
        result = "empty"
    else:
        # v0.7.1 policy: summary hand-off (option B1 of issue #20). The old model summarizes
        # the conversation right before the next request, so the switch itself never blocks and
        # costs nothing until the player asks something.
        result = conversation.change_model(source, model_id)
        # The raw history is gone from here on (the summary is written right before the next
        # question), so the stored conversation is updated to match what this instance holds.
        _save_history(username, conversation)

    logger.verbose(server, f"[switch] {username} -> model_id={model_id}, hand-off={result}")

    if result == "same":
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.user_message.switch_same_model', model=ai_name)}")
    elif result == "scheduled":
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.user_message.switch_summary', model=ai_name)}")
    else:
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.user_message.switch_success', model=ai_name)}")


def _note_player_server(source: CommandSource, chat_param: 'ChatParam') -> None:
    """Tell the model when a player shows up on a different server.

    Only the *change* is written into the history -- never a tag on every message. A per-message
    tag would grow every request, while a note is added once and then stays part of the prefix,
    so nothing here can invalidate the provider's prefix cache between rounds.

    It runs on the caller's thread: :func:`ask_ai` calls it immediately before it appends the
    question, so the note is in the list first and reads as context for it. Like every other
    helper here it must stay synchronous -- a ``@new_thread`` decorator would let the question
    land first, and a note that arrives after the question explains the wrong thing.
    """
    manager = _cross_server
    if manager is None or not (manager.is_client or manager.peers):
        return                       # a single instance has nothing to announce
    player = getattr(source, "player", None)
    if not player:
        return                       # the console has no stable identity to track
    server_name = getattr(source, "origin", None) or manager.name
    if not server_name:
        return
    with _player_servers_lock:
        previous = _player_servers.get(player)
        if previous == server_name:
            return
        # Remembered inside the lock, so a second ask of the same moment finds the new server
        # already recorded and stays silent instead of announcing the same move again.
        _player_servers[player] = server_name
    try:
        rtr = source.get_server().rtr
        if previous:
            note = str(rtr("games_ai.user_message.server_moved", player=player,
                           previous=previous, server=server_name))
        else:
            note = str(rtr("games_ai.user_message.server_here", player=player, server=server_name))
        chat_param.add_to_response_list("user", note)
    except Exception:
        logger.log("exception", "failed to add the server-change note")


def _ask_error_reply(source: CommandSource, error: Exception, model: str) -> None:
    """Turn one failed AI request into a localized, actionable reply and a full traceback.

    A provider failure used to leave the ``!!ask`` path as an exception: MCDR then crashed
    while formatting its own error (``'GreedyText' object has no attribute
    '_TextNode__name'``) and the player never learned what actually went wrong. The player gets
    one line that says what to do, the operator gets the traceback in the log, and nothing
    escapes.

    The buckets are deliberately coarse: they are the ones with a different fix. What the status
    code itself means is not repeated per bucket: for a provider answer it is added to the
    sentence from the same table the operator's log line uses (see
    :func:`chat_param.describe_http_status`), so the player learns *insufficient balance* or
    *model not found* instead of only a number. A status this build has no text for simply leaves
    the parenthesis out.
    """
    if isinstance(error, AuthenticationError):
        key = "games_ai.ask_error.authentication"
    elif isinstance(error, RateLimitError):
        key = "games_ai.ask_error.rate_limit"
    elif isinstance(error, APIConnectionError):          # also covers APITimeoutError
        key = "games_ai.ask_error.connection"
    elif isinstance(error, APIStatusError):
        key = "games_ai.ask_error.api_status"
    else:
        key = "games_ai.ask_error.unexpected"
    status = getattr(error, "status_code", None)
    where = f", HTTP {status}" if status is not None else ""
    description = describe_http_status(source.get_server(), status)
    detail = f" ({description})" if description else ""
    # The full traceback goes to the plugin's own logger (bridged into MCDR's by
    # logger.attach); the reply carries the status and what it means, plus what to act on.
    logger.log("exception",
              f"{plugin_config.prefix}The AI request failed ({type(error).__name__}{where}): {error}")
    try:
        source.reply(f"{plugin_config.prefix}{source.get_server().rtr(key, model=model, code=status,
                                                        error=error, detail=detail)}")
    except Exception:
        logger.log("exception", "failed to report an AI error to the command source")


def _run_ai_round(source: CommandSource, chat_param: "ChatParam", data: list[tuple[str, str]] | None, model: str) -> None:
    """Run one ``!!ask`` round so that no API failure can escape into MCDR's error path.

    The conversation is stored in the ``finally`` branch, i.e. after a finished round, an
    interrupted one (``!!ask stop``) and a failed one alike: whatever the player's history looks
    like afterwards is what the next load restores. A ``!!ask -n`` round carries a
    ``NonHistoryChatParam``, which :func:`_save_history` skips by type.
    """
    try:
        chat_param.response_ai(source, data)
    except Exception as error:
        _ask_error_reply(source, error, model)
    finally:
        _save_history(get_username(source), chat_param)


@new_thread("games_ai@ask_ai")
def ask_ai(source: CommandSource, context: dict, no_history: bool = False, forced: bool = False):
    # The whole entry point is guarded: data-path reads, conversation/model setup and anything
    # else that happens before a round used to raise out of this thread unnoticed, which left
    # the player with no reply at all. Every failure now ends in the same localized error line.
    model_for_error = plugin_config.default_ai
    try:
        server = source.get_server()

        # None when the public database holds nothing: no data message is attached then.
        # A database that cannot be read (not open yet, a locked file) must not take the
        # question down with it: the data block is optional context, so the round runs
        # without it and the failure is logged.
        try:
            data = data_commands.DataManager(plugin_config.data_path).ask_ai_read_data() or None
        except Exception as exc:
            logger.log("warning", f"{plugin_config.prefix}The public database could not be read; "
                                  f"asking without the data context: {exc}")
            data = None
        username = get_username(source)
        content: str = context['content']

        user_message = f'{str(server.rtr("games_ai.user_message.username"))}{username}\n{str(server.rtr("games_ai.user_message.message"))}{content}'

        with _conversations_lock:
            user_chat_param = all_chat_param.get(username)
            if user_chat_param is None:
                user_chat_param = ChatParam(server, model_id=plugin_config.default_ai)
                all_chat_param[username] = user_chat_param
        model_id = user_chat_param.get_model_id or plugin_config.default_ai
        model_for_error = model_id
        ai_prefix = plugin_config.all_ai.get(model_id, {}).get("ai_name")

        if no_history:
            # stateless one-shot: no history, no context management (see NonHistoryChatParam)
            chat_param = NonHistoryChatParam(server, model_id=model_id)
            chat_param.add_to_response_list("user", user_message)
            source.reply(f"{ai_prefix}{server.rtr("games_ai.user_message.thinking")}")
            register_no_history(username, chat_param)
            try:
                _run_ai_round(source, chat_param, data, model_id)
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
                f.get("file", "") for f in [*plugin_config.skills_description, *default_skills]
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

        # One round at a time per conversation. A question asked while another round owns the
        # conversation is queued (forced messages go through the response queue, which the
        # running round may still merge); the owner then sends the queued questions in arrival
        # order as one merged follow-up round.
        if not user_chat_param.try_claim_round():
            if forced:
                if skills_file:
                    user_chat_param.forced_add_to_response_list(
                        "user", str(server.rtr('games_ai.user_message.skill_injected', skill=skills_file)))
                user_chat_param.forced_add_to_response_list("user", user_message)
                logger.verbose(server, f"[ask -f] {username} message queued (running round active)")
            else:
                user_chat_param.queue_pending_ask(source, user_message)
                logger.verbose(server, f"[ask] {username} question queued behind the running round")
            source.reply(f"{ai_prefix}{server.rtr("games_ai.user_message.thinking")}")
            return

        owner_source = source
        pending: list[tuple[CommandSource, str]] | None = [(source, user_message)]
        first_round = True
        try:
            while pending is not None:
                if pending:
                    if first_round and skills_file:
                        user_chat_param.add_to_response_list(
                            "user", str(server.rtr('games_ai.user_message.skill_injected', skill=skills_file)))
                    for queued_source, message in pending:
                        # We own the round here, so the server-change note can never land in the
                        # middle of a tool-call group (the bug that used to corrupt the history).
                        _note_player_server(queued_source, user_chat_param)
                        user_chat_param.add_to_response_list("user", message)
                if first_round:
                    source.reply(f"{ai_prefix}{server.rtr("games_ai.user_message.thinking")}")
                    first_round = False
                _run_ai_round(owner_source, user_chat_param, data, model_id)
                next_round = user_chat_param.finish_round_or_take_next()
                pending = None if next_round is None else next_round[0]
        finally:
            user_chat_param.release_round()
    except Exception as exc:
        logger.log("exception", f"{plugin_config.prefix}!!ask failed: {exc}")
        try:
            _ask_error_reply(source, exc, model_for_error)
        except Exception:
            logger.log("exception", f"{plugin_config.prefix}!!ask error reply failed: {exc}")

def get_username(source: CommandSource) -> str:
    if source.is_player:
        return source.player
    else:
        return CONSOLE_ACCESS_KEY


# ── handing a message to another user's conversation ────────────────────────
# One user's assistant can leave a message for another user's assistant, and anyone may write to
# anyone: the only gate is that the recipient already has a conversation (a ``ChatParam``), so a
# message can never create one. Permission levels are deliberately not compared -- the recipient
# is not being acted upon, they are being left a note that names the sender, and that note is
# only read at their own next question (see the tool function).


@register_tool(
    description=(
        "Send a message from the current user to anyone else's GamesAI conversation. The "
        "recipient's assistant reads it as part of that conversation at their next question, so "
        "this is one-way: no answer comes back and the recipient is not woken up. Use it to hand "
        "information over to another user's assistant. Any existing conversation may be written "
        "to, whatever the permission levels are; the only requirement is that the recipient "
        "already has a GamesAI conversation, because a message never creates one. The server "
        "console's own conversation is addressed by the exact target \"Server Control Panel\"."
    ),
    execute_in_hub=True,
    parameters={
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": ("Exact name of the receiving conversation: a Minecraft player "
                                "name such as Steve, or the server console's key "
                                "\"Server Control Panel\""),
            },
            "message": {
                "type": "string",
                "description": ("Text delivered verbatim to that player's assistant. Write it as "
                                "information for that assistant, not as an instruction to obey. "
                                "At most 1000 characters."),
            },
        },
        "required": ["target", "message"],
    },
)
def send_message_to_player_ai(source: CommandSource, ai_prefix: str, target: str, message: str):
    """Hand one message to another user's conversation (see the tool description above).

    Runs where the conversations live: ``!!ask`` is a server-class command, so in a cluster every
    ``ChatParam`` -- the sender's and the recipient's -- is on the hub. A tool that is not
    hub-bound would be routed back to the asking instance, which holds neither of them.

    Anyone may write to anyone: the recipient's ``ChatParam`` only has to exist, and no
    permission level is compared -- neither side's level is looked up here, so a delivery cannot
    write a name into ``permission.yml``. What protects the recipient is visibility rather than a
    gate: the message lands in their own history, names the sender in the text, and they read it
    at their next question.
    """
    server = source.get_server()
    sender = get_username(source)
    target = str(target or "").strip()
    text = str(message or "").strip()
    if not target or not text:
        source.reply(f"{ai_prefix}{server.rtr('games_ai.player_message.empty')}")
        return "Both target and message are required; nothing was delivered."
    if len(text) > _PLAYER_MESSAGE_MAX_LENGTH:
        source.reply(f"{ai_prefix}{server.rtr('games_ai.player_message.too_long', limit=_PLAYER_MESSAGE_MAX_LENGTH)}")
        return (f"The message has {len(text)} characters, more than the "
                f"{_PLAYER_MESSAGE_MAX_LENGTH} allowed; nothing was delivered.")
    recipient = all_chat_param.get(target)
    if recipient is None:
        source.reply(f"{ai_prefix}{server.rtr('games_ai.player_message.no_conversation', target=target)}")
        return (f"{target} has no GamesAI conversation, so nothing was delivered. Only a user (or "
                f"the console) who has already talked to GamesAI can receive a message; a "
                f"delivery never creates a conversation.")
    origin = str(getattr(source, "origin", "") or plugin_config.cross_server_name or "")
    try:
        recipient.add_external_message(sender, text, origin=origin)
    except Exception as e:
        logger.log("exception", f"{plugin_config.prefix}Failed to hand a message from {sender} to {target}: {e}")
        return f"Failed to deliver the message to {target}: {e}"
    # Stored right away: a message waiting in the recipient's queue has to survive a restart too.
    _save_history(target, recipient)
    _notify_relayed_message(server, target, sender)
    logger.verbose(server, f"[player message] {sender} -> {target} ({len(text)} chars, origin={origin or '-'})")
    source.reply(f"{ai_prefix}{server.rtr('games_ai.player_message.delivered', target=target)}")
    return (f"Delivered to {target}'s assistant ({len(text)} characters). It will read the "
            f"message at its next question.")


def _notify_relayed_message(server: ServerInterface, target: str, sender: str) -> None:
    """Tell the recipient in game that a message reached their assistant (best effort).

    Only sent when the player is known to be online **on this instance's** Minecraft server: a hub
    cannot see the players of the other instances, and a `/tell` for somebody who is not here
    would only print an error into the console. When the online list cannot be obtained (no
    ``online_player_api``), nothing is sent and the delivery is merely logged.
    """
    if target == CONSOLE_ACCESS_KEY:
        return
    try:
        api = server.get_plugin_instance("online_player_api")
        if api is None:
            logger.verbose(server, f"[player message] {sender} -> {target}: no online_player_api, no notice")
            return
        online = [str(name) for name in (api.get_player_list() or [])]
        if target not in online:
            logger.verbose(server, f"[player message] {sender} -> {target}: not online here, no notice")
            return
        server.tell(target, RText(f"{plugin_config.prefix}{server.rtr('games_ai.player_message.notice', sender=sender)}"))
    except Exception:
        logger.log("exception", f"{plugin_config.prefix}Failed to notify {target} about a relayed message")


def ask_stop(source: CommandSource, context: dict):
    """
    ``!!ask stop`` — abort everything this player has in flight.

    * the running round of the player's conversation (tool calls included): it stops at its
      next checkpoint, and **what it already wrote stays in the history** — the question, the
      injected notes and every finished tool call keep their place. Only a trailing tool call
      whose result never arrived is dropped (see ``ChatParam._drop_unanswered_tool_call``);
      queued ``!!ask -f`` messages stay queued and are merged by the next round as usual;
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

    logger.verbose(server, f"[stop] {username} stopped: {stopped or 'nothing running'}")
    if not stopped:
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.user_message.stop_none')}")
        return
    for key in stopped:
        source.reply(f"{plugin_config.prefix}{server.rtr(key)}")

class AiDataManager:
    @staticmethod
    @register_tool(description="Read one key/value pair from the public database. Listing the existing keys first is recommended.", execute_in_hub=True, parameters={
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
        result = database.public_database().read_data(key)
        if result is None:
            return f"Key '{key}' does not exist"
        else:
            return f"The value of key '{key}' is {result}"

    @staticmethod
    @register_tool(description="List every key of the public database", execute_in_hub=True)
    def ai_read_all_keys(source: CommandSource, ai_prefix: str):
        server = source.get_server()
        source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.reading_all_keys")}')
        keys = database.public_database().get_all_key()
        return f"All current keys: {keys}"

    @staticmethod
    @register_tool(description="Write a key/value pair into the public database (create or overwrite). The value is overwritten, so avoid clobbering important data; a missing key is created automatically.", perm=get_plugin_config_perm, execute_in_hub=True, parameters={
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
        if not has_permission(source):
            return TOOL_DENIED_NOT_ALLOWED
        database.public_database().write_data(key, value)
        return f"Wrote the value of key '{key}': {value}"

    @staticmethod
    @register_tool(description="Append a value to the public database (create or append). The value is appended to the end of the existing one; a missing key is created automatically.", perm=get_plugin_config_perm, execute_in_hub=True, parameters={
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
        if not has_permission(source):
            return TOOL_DENIED_NOT_ALLOWED
        new_value = database.public_database().append(key, value)
        return f"Appended {value} to key '{key}', current value: {new_value}"

    @staticmethod
    @register_tool(description="Delete a key from the public database. Deletion cannot be undone, and it succeeds even when the key does not exist.", perm=get_plugin_config_perm, execute_in_hub=True, parameters={
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
        if not has_permission(source):
            return TOOL_DENIED_NOT_ALLOWED
        database.public_database().delete_data(key)
        return f"Deleted the data of key '{key}'"
    
    @staticmethod
    @register_tool(description="List every key/value pair of the public database", execute_in_hub=True)
    def ai_read_all_data(source: CommandSource, ai_prefix: str):
        server = source.get_server()
        source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.reading_all_data")}')
        value = database.public_database().data_list()
        return f"All data in the public database: {value}"

def debug(source: CommandSource, context: dict):
    server = source.get_server()
    if plugin_config.debug_mode:
        plugin_config.debug_mode = False
        server.say(f"{plugin_config.prefix}{server.rtr("games_ai.debug.disable")}")
        server.logger.info(f"{plugin_config.prefix}{server.rtr("games_ai.debug.disable")}")
        return
    else:
        plugin_config.debug_mode = True
        server.say(f"{plugin_config.prefix}{server.rtr("games_ai.debug.enable")}")
        server.logger.info(f"{plugin_config.prefix}{server.rtr("games_ai.debug.enable")}")
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

    source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.debug.threads_header', count=len(own))}")
    for thread in own[:_THREAD_LIST_LIMIT]:
        source.reply(f"{plugin_config.prefix}  {_format_thread(thread)}")
    if len(own) > _THREAD_LIST_LIMIT:
        source.reply(f"{plugin_config.prefix}  ... +{len(own) - _THREAD_LIST_LIMIT}")


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
    global _autonomous_controller
    server = source.get_server()

    if not _reload_lock.acquire(blocking=False):
        source.reply(f'{plugin_config.prefix}{server.rtr("games_ai.user_message.reload_in_progress")}')
        logger.verbose(server, "[reload] rejected: another reload is still running")
        return
    try:
        _reload_body(source, context)
    finally:
        _reload_lock.release()


def _reload_body(source: CommandSource, context: dict):
    global _autonomous_controller
    server = source.get_server()

    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(plugin_config.skills_path)), 'config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        _apply_config(server, config)

        with _conversations_lock:
            conversations = list(all_chat_param.values())
        for user_chat_param in conversations:
            # A conversation whose model was removed from the config keeps its previous client
            # and info (reload_ai_info returns False); a conversation mid-round is skipped so
            # the client it is using cannot be swapped under it. Either way the reload itself
            # continues -- its errors are log-only, like the rest of the reload path.
            if user_chat_param.is_round_active():
                server.logger.info(f"{plugin_config.prefix} A conversation is answering; its model "
                                   f"configuration is refreshed by the next reload")
                continue
            try:
                user_chat_param.reload_ai_info()
            except Exception as e:                  # noqa: BLE001 - never abort the reload for it
                server.logger.warning(f"{plugin_config.prefix} A conversation kept its previous "
                                      f"model configuration: {e}")

        tool_plugin_ids = set(TOOL_PLUGIN_IDS)

        reset_all_tools()

        try:
            with open(plugin_config.skills_path, mode="r", encoding="utf-8") as f:
                plugin_config.skills_description = json.loads(f.read())
        except Exception as e:
            server.logger.warning(f"{plugin_config.prefix} Failed to reload skills: {e}")

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
            server.logger.info(f"{plugin_config.prefix} Config hot-reloaded, JS bot will pick up changes automatically")
            default_ai_info = plugin_config.all_ai.get(plugin_config.default_ai, None)
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
                server.logger.info(f"{plugin_config.prefix} AutonomousBot controller config reloaded")
            elif default_ai_info is None:
                server.logger.warning(f"{plugin_config.prefix} No default AI configured, AutonomousBot controller config skipped")
        else:
            failed = _stop_bot_stack(server)
            if failed:
                server.logger.warning(f"{plugin_config.prefix} Failed to stop existing Mineflayer bot! ({', '.join(failed)})")
            else:
                server.logger.info(f"{plugin_config.prefix} Mineflayer bot stopped successfully!")
            server.logger.info(f"{plugin_config.prefix} Mineflayer bot process has been terminated successfully!")

            if new_enabled:
                try:
                    _run_mineflayer_bot(server, mineflayer_cfg, plugin_config.mineflayer_init_js_path)
                except Exception as e:
                    server.logger.exception(f"{plugin_config.prefix} Failed to start Mineflayer bot: {e}")

        plugin_reload_map = dict(REGISTER_PLUGIN_LIST)
        for plugin_id in tool_plugin_ids:
            if plugin_id != PLUGIN_METADATA["id"] and plugin_id not in plugin_reload_map:
                plugin_reload_map[plugin_id] = None

        for plugin_id, reloader in plugin_reload_map.items():
            if reloader is None:
                _reload_plugin = server.reload_plugin(plugin_id)
                if _reload_plugin is None:
                    server.logger.warning(f"{plugin_config.prefix} Plugin '{plugin_id}' (registered tools) not found")
                    REGISTER_PLUGIN_LIST.pop(plugin_id, None)
                    TOOL_PLUGIN_IDS.discard(plugin_id)
                elif not _reload_plugin:
                    server.unload_plugin(plugin_id)
                    server.logger.warning(f"{plugin_config.prefix} Failed to reload plugin '{plugin_id}', unloaded and removed from reload list")
                    REGISTER_PLUGIN_LIST.pop(plugin_id, None)
                    TOOL_PLUGIN_IDS.discard(plugin_id)
                else:
                    server.logger.info(f"{plugin_config.prefix} Successfully reloaded plugin '{plugin_id}'")
            else:
                try:
                    reloader(source)
                    server.logger.info(f"{plugin_config.prefix} Successfully reloaded registered plugin '{plugin_id}'")
                except Exception as e:
                    server.unload_plugin(plugin_id)
                    server.logger.warning(f"{plugin_config.prefix} Failed to reload registered plugin '{plugin_id}', unloaded and removed from reload list, reason: {e}")
                    REGISTER_PLUGIN_LIST.pop(plugin_id, None)
                    TOOL_PLUGIN_IDS.discard(plugin_id)
    except Exception as e:
        server.logger.exception(f"{plugin_config.prefix} Reload failed: {e}")
        source.reply(f"{plugin_config.prefix}Reload failed: {e}")

    server.dispatch_event(LiteralEvent("games_ai.reload"), (source,))

    server.say(f'{plugin_config.prefix}{server.rtr("games_ai.unload_message.reloader_msg")}')
    server.logger.info(f'{plugin_config.prefix}{server.rtr("games_ai.unload_message.reloader_msg")}')
    return

@new_thread("games_ai@speed_test")
def speed_test(source: CommandSource, context: dict):
    server = source.get_server()
    test_url = []

    user_input = context.get("model")
    if user_input is not None:
        user_input_id = _ai_id_for(user_input)
        ai_info = plugin_config.all_ai.get(user_input_id)

        if ai_info is None:
            may_user_ai = []
            for ai_id, ai_config in plugin_config.all_ai.items():
                name = ai_config.get("ai_name", "")
                if user_input.lower() in name.lower() or user_input.lower() in ai_id.lower():
                    may_user_ai.append(ai_id)
            if len(may_user_ai) == 1:
                ai_info = plugin_config.all_ai.get(may_user_ai[0])
            elif len(may_user_ai) > 1:
                source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.user_message.model_more')}{may_user_ai}")
                return
            else:
                source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.user_message.model_error')}{list(plugin_config.all_ai.keys())}")
                return

        ai_prefix = ai_info.get("ai_name")
        base_url = ai_info.get("base_url")
        api_key = ai_info.get("api_key")
        test_url.append((ai_prefix, base_url, api_key))
    else:
        test_url = [(ai_info.get("ai_name"), ai_info.get("base_url"), ai_info.get("api_key")) for ai_info in plugin_config.all_ai.values()]

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


if not _deps_pending:
    # The handlers under games_ai/commands/ read this instance's live state and call back into
    # this module; bind them once everything they may reach exists. Bound at import time, not at
    # load time, so the handlers work for any caller -- a load, a copy of the package, or a test
    # that calls one directly. The getters and callbacks are read at *use* time, so a manager that
    # `node claim` replaced is still the current one.
    node_commands.attach(
        server_of=_plugin_server,
        manager_of=lambda: _cross_server,
        restart_link=_restart_cross_server,
        stop_link=_stop_cross_server,
        store_bot_token=_store_bot_token,
        identity_path=_identity_path,
        load_identity=_load_identity,
        save_identity=_save_identity,
        delete_identity=_delete_identity,
        identity_fingerprint=_identity_fingerprint,
    )
    # What `!!gamesai clear` may drop: the live conversations, the history store and the helper
    # that names a command source.
    clear_commands.attach(
        conversations=lambda: all_chat_param,
        history_store=_history_store,
        username_of=get_username,
    )

