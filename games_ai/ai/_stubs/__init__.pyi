# Generated from games_ai/__init__.py by tools/build_tool_stubs.py -- do not edit.
from mcdreforged.api.all import *
import threading
from .ai import ChatParam
from .bot import AutonomousBotController
from .cluster import CrossServerManager, WebSocketCommandSource
from .core import ChatHistoryStore, PublicDatabase as PublicDatabase, require_permission as require_permission
from .ui import send_help as send_help
from _typeshed import Incomplete

_deps_pending: Incomplete
_DEP_INSTALL_ABORT: Incomplete
_DEP_INSTALL_STARTED: bool
PLUGIN_METADATA: Incomplete
DEFAULT_WEBSOCKET_URI: str
_BOT_WS_RECONNECT_INTERVAL: int
_BOT_WS_TIMEOUT: int
all_chat_param: dict[str, 'ChatParam']
_conversations_lock: Incomplete
_player_servers: dict[str, str]
_player_servers_lock: Incomplete
CONSOLE_ACCESS_KEY: str
_HISTORY_FORMAT: int
_history_frozen: bool
_PLAYER_MESSAGE_MAX_LENGTH: int
_cross_server: CrossServerManager | None
_cross_server_thread: threading.Thread | None
_config_migration_note: str | None
_remote_sessions: Incomplete
_REMOTE_TOOL_TIMEOUT: float
_server_ref: PluginServerInterface | None
_PLUGIN_THREAD_NAMES: Incomplete
_THREAD_LIST_LIMIT: int
_autonomous_controller: AutonomousBotController | None
_BOT_STOP_GRACE: float
_BOT_UNLOAD_GRACE: float
_mineflayer_pending_abort: Incomplete
_mineflayer_wait_thread: threading.Thread | None
_mineflayer_launch_token: int
_reload_lock: Incomplete
_bot_teardown_lock: Incomplete
_bot_teardown_event: Incomplete

def _watch_thread_exit(thread: threading.Thread, server: PluginServerInterface, name: str, timeout: float = 60.0) -> None:
    """Log when an aborted leftover thread finally dies (it may still be inside a blocking call)."""
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

_previous_thread_excepthook: Incomplete

def _install_thread_excepthook(server: PluginServerInterface) -> None:
    """
    Keep the injected abort out of MCDR's console as a traceback.

    A leftover controller thread from an *older* plugin version has no handler for
    ``_ControllerAbort``, so ``threading`` would print a full traceback for a thread that is
    already gone. The hook is chained (everything else keeps its original behaviour) and is
    matched by class name, because the exception object comes from the old, already
    unloaded module instance.
    """
def _restore_thread_excepthook() -> None:
    """Give the process its original thread exception hook back."""
def _deps_log_line(server: PluginServerInterface, line: str) -> None:
    """One line of the pip child's output, so an install is visible while it runs."""
def _deps_start_install(server: PluginServerInterface) -> None:
    """The packages are missing: report them and repair them once.

    Nothing is registered and nothing else of ``on_load`` runs -- the instance is ready, but has
    no commands, no bot and no cross-server link until the packages are there. There is no switch
    and no command for this: repairing its own dependencies is the plugin's business, and the
    repair either succeeds (a self-reload follows) or is reported for the user to fix by hand.
    """
def _deps_install_thread(server: PluginServerInterface, names: list[str]) -> None:
    """Install the missing packages and ask MCDR to load the plugin again.

    Two attempts: the machine's own pip configuration first, the Aliyun mirror second. The plugin
    reloads itself only once the packages really import; a failed repair is logged together with
    the command the user can run, and nothing else happens -- no retry, no reload.

    This runs on its own thread because ``reload_plugin`` below unloads this very instance: after
    that call the module globals read earlier belong to an instance that is gone, so only this
    function's arguments and ``server`` are touched from then on.
    """
def _load_skills_index(server: PluginServerInterface, skills_path: str) -> list:
    '''Read ``skills.json``; a broken file is logged and answered with "no skills".

    The file is user-editable and is written by the AI as well (a crash during a write can
    truncate it), so a parse error must never abort ``on_load`` and keep the whole plugin from
    loading. The same rule the stored conversations follow applies here: unreadable user data
    is reported and skipped, not fatal.
    '''
def on_load(server: PluginServerInterface, _): ...
def _raw_command(source: CommandSource) -> str | None:
    """The line the user actually typed *here*, for both a player chat command and the console.

    ``PluginCommandSource`` (our own ``server.execute_command`` calls) has no Info, and a
    ``WebSocketCommandSource`` only has one rebuilt from another instance's line: neither may
    travel, or a reload would bounce around the cluster (or a cluster command fan out) forever.
    """
def _should_forward(source: CommandSource) -> bool: ...
def _callback_arity(handler) -> int:
    """How many positional arguments MCDR will hand to this callback.

    MCDR slices its argument list by the callback's *declared* positional parameter count and
    subtracts one for a bound method (``command/builder/callback.py``). A wrapper that hides
    the real count behind ``*args`` would therefore be handed too few values, which is why the
    wrappers below declare exactly what the wrapped callback declares.
    """
def _normalised_command(raw: str | None) -> str:
    """The command line with its whitespace collapsed (empty string for ``None``)."""
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
def _client_link_is_down() -> bool:
    """True when this instance is a client whose link cannot carry frames right now.

    A client hands its hub-class commands to the hub, so with the link down there is nothing
    to hand them to and running them here would use this instance's own database and API key.
    Only the role matters: the hub itself, a standalone instance and a command that arrived
    from another instance never reach this check (see :func:`_route`).
    """
def _reply_hub_unavailable(source: CommandSource) -> None:
    """The one localized line a refused hub-class command is answered with."""
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
def _forward_command(kind: str, source: CommandSource, raw: str) -> None:
    """Send a command of a remote class to the hub; the answers come back as frames."""
def _fan_out_cluster(source: CommandSource, expected_command: str | None = None) -> None:
    """Let the other trusted instances run the cluster command that just ran here.

    The command is read back from the source's ``Info`` (that is how a typed command is known
    at all), so it is checked against the literal this command was registered for before
    anything is broadcast: an internal caller can execute a cluster command on a source whose
    Info is a different line, and broadcasting that instead would make every peer execute the
    wrong command (see the analysis in :func:`_route`).
    """
def _known_player_permission_level(server: ServerInterface | None, player: str) -> int:
    """This instance's permission level for a remote player, without side effects.

    ``ServerInterface.get_permission_level(name)`` goes through MCDR's ``auto_add=True`` path:
    an unknown name is appended to ``permission.yml`` at the default level and that level is
    returned, while the cross-server rule says an unknown remote player gets 0 (and the file
    must not be rewritten by a background thread). The permission manager is therefore asked
    with ``auto_add=False`` directly. Should that private member ever disappear, the fallback
    reads the value but treats a missing name as unknown instead of letting MCDR add it.
    """
def _resolve_remote_permission(data: dict) -> int:
    """How much a remote issuer is allowed to do here.

    A player gets ``min(what the origin reported, this instance's own permission.yml)`` and
    nothing at all when this instance does not know the name; a console keeps level 4, since
    whoever sits at another machine's console already controls that machine.
    """
def _send_to_peer(target: str, action: str, data: dict) -> None:
    '''Send to a named peer.

    The target name may equal ours -- two instances can still be given the same name by hand --
    so this goes through ``hub.deliver``, which never mistakes "looks like my own name" for
    "handle it myself" (that shortcut silently swallowed every answer in that setup).
    '''
def _local_sink(session: str, origin: str):
    """Where the answers of a command executed here go."""
def _execute_remote(origin: str, data: dict) -> None:
    """Run one command on behalf of another instance."""
def _run_remote_command(server: ServerInterface, raw: str, command_source: WebSocketCommandSource, origin: str, session: str) -> None:
    """Execute one forwarded command and tell the asking instance that it is done."""
def _resolve_routed_tool_permission(data: dict) -> int:
    """The origin's own verdict on a routed tool call.

    A separate entry point even though the rule matches :func:`_resolve_remote_permission`: the
    tool runs *here*, so *this* instance's own permission.yml has the final say. A hub that
    reports a level this instance does not grant must not be trusted with it.
    """
def _execute_remote_tool(origin: str, data: dict) -> dict:
    """Run one tool call for the hub and hand its result back (runs on a link thread).

    The tool is looked up in *this* instance's registry -- the hub only knows that this server
    offered it -- and it runs against a command source standing for the remote player, whose
    sink streams the tool's own replies to whoever asked.
    """
def route_remote_tool_call(source: WebSocketCommandSource, func_name: str, func_args: dict, ai_prefix: str = '') -> str:
    """Run one tool call on the instance the request came from and return its result.

    A tool that is not hub-bound describes the asking player's own server, so the hub hands the
    call over the cross-server link and waits for the answer. Blocking is only safe on the AI
    loop thread (see the deadlock note in ``_on_cross_message``). Never raises: every failure
    becomes an honest string for the model, and a timeout is an unknown outcome it must not
    retry, because the tool may well have run before the answer was lost.
    """
def _install_tool_router() -> None:
    """Wiring for chat_param: it dispatches through the router installed here.

    Kept as a hook because the package imports chat_param: that module cannot import its own
    package back (and under the test suites each plugin instance has its own copy of both).
    """
def _render_remote_reply(msg: dict) -> None:
    '''Show one streamed answer on the instance that asked for the command.

    Only a **cluster** command labels its stream. Its output comes from every instance that ran
    it, so the ones that are not this machine are prefixed with their name. A server-class
    command (``!!ask``, ``!!data``, ...) was handed to the hub, which is answering *this*
    player\'s own command: those lines are theirs, and prefixing them with the hub\'s name --
    which is what comparing names did on a client, where the hub\'s name is always "someone
    else" -- was noise nobody asked for.
    '''
def _on_cross_message(msg: dict) -> dict | None:
    """Handle one frame addressed to this instance (runs on a link thread)."""
def register_commands(server: PluginServerInterface, config: dict):
    """
    Register all commands for the GamesAI plugin with the MCDR server.
    """
def on_server_startup(server: PluginServerInterface):
    """
    Called when the server starts up. This function is used to perform any necessary initialization for the plugin.
    """
def _disable_mineflayer_and_reload(server: PluginServerInterface): ...
def _get_minecraft_server_address() -> tuple[str, int]: ...
def _read_bot_token(path: str) -> str:
    """The token the JS bot already holds, so a config rewrite never discards its identity."""
def _store_bot_token(server: PluginServerInterface, name: str, token: str) -> None:
    '''Keep the token the hub issued to the Mineflayer bot inside the bot\'s own config.

    This is the "no human step" half of the bot provisioning: the hub hands the freshly
    issued token to the plugin (see CrossServerHub.on_bot_token), and the plugin writes it
    next to the address the bot dials. Only the fingerprint is ever logged.
    '''
def _write_mineflayer_config(server: PluginServerInterface, config: dict, peer_uri: str | None = None): ...
def run_mineflayer_bot(source: CommandSource, ai_prefix: str): ...
def stop_mineflayer_bot(source: CommandSource, ai_prefix: str): ...
def _run_mineflayer_bot(server: ServerInterface, bot_config: dict, mineflayer_init_js_path: str): ...
def _wait_server_then_launch(server: ServerInterface, bot_config: dict, mineflayer_init_js_path: str, launch_token: int): ...
def _cancel_pending_bot_launch() -> None:
    """Cancel a bot launch that is waiting for the server (or was just started).

    Called when the bot is disabled (``!!aibot leave``/config) or the plugin unloads. Without
    it, a wait thread created before the disable would still call `_launch_mineflayer_bot` after
    the server comes up: the operator disabled the bot, but a node process and an AI-burning
    controller would start anyway. The token also invalidates a thread that was superseded by a
    newer launch request before it got to its next check.
    """
def _launch_mineflayer_bot(server: ServerInterface, bot_config: dict, mineflayer_init_js_path: str): ...
def _apply_config(server: PluginServerInterface, config: dict):
    """
    Apply the configuration for the GamesAI plugin.
    """

DEFAULT_WEBSOCKET_CONFIG: dict

def _default_websocket_block() -> dict:
    """A fresh copy of the default ``websocket`` block (the list must not be shared)."""
def _migrate_config_data(raw) -> bool:
    '''Config migration hook (MCDR ``data_processor``) for the cross-server release.

    0.7.x kept the bot\'s WebSocket address in ``mineflayer_bot.websocket``; the plugin owns
    that address now, so it moves to the top-level ``websocket``. The 0.8.0 shared secret
    ``websocket.token`` is gone as well -- every node claims its own token -- so a stale key
    is dropped here rather than read anywhere. This runs on the data read from config.json
    *before* MCDR fills in the missing default keys -- which is what makes ``"websocket" in
    raw`` a reliable "the user never wrote the new key" test. MCDR saves the file when this
    returns True.
    '''

_CROSS_SERVER_DIR: str
_IDENTITY_FILE: str
_NODE_TABLE_FILE: str
_CROSS_SERVER_ROLE_FILE: str
_LEGACY_STATE_FILES: Incomplete
_state_files_lock: Incomplete
_state_files_seen: set[str]

def _cross_server_dir(server: PluginServerInterface | None = None) -> str | None:
    """The folder holding the link's runtime state, or None without a data folder."""
def _cross_server_state_path(server: PluginServerInterface | None, name: str) -> str | None:
    """Path of one file in that folder, migrating its old location on first use.

    Returns the *old* path when the file is still there and could not be moved (an uncreatable
    folder, a locked file): losing sight of an identity file would cost the instance its
    enrolment and make an operator re-issue a token, which is a much worse outcome than using a
    file in the previous place for one more load.
    """
def _migrate_state_file(old: str, new: str) -> None:
    """Move one state file out of the data folder root; never raises, runs at most once.

    Called on every path lookup, so the work is cached per destination path and per load. Both
    existing is the one case worth a warning: nothing is deleted then, the new location simply
    wins.
    """
def _plugin_server(source: CommandSource | None = None) -> PluginServerInterface | None:
    '''The interface that can answer plugin-only questions, whatever the command source is.

    MCDR builds every command source on its **base** ``ServerInterface``:
    ``PlayerCommandSource.get_server()`` and ``ConsoleCommandSource.get_server()`` both return
    ``mcdr_server.basic_server_interface``, and only :class:`PluginServerInterface` knows this
    plugin\'s data folder (``get_data_folder()`` lives there and nowhere else). Every read or
    write of the identity file, the node table or the bot config therefore has to go through
    the interface ``on_load`` received -- asking the command source for it silently degrades to
    "this plugin has no data folder", which is how ``!!gamesai node claim`` could report
    success while writing nothing.
    '''
def _data_folder(server: PluginServerInterface | None = None) -> str | None:
    """The plugin's data folder (``config/games_ai``), or None when it cannot be asked.

    The server handed in is tried first, then the module reference ``on_load`` stored: a
    command source only ever hands back MCDR's base interface, which has no
    ``get_data_folder`` (see :func:`_plugin_server`).
    """

_INSTANCE_NAME_MAX: int
_INSTANCE_NAME_FALLBACK: str
_INSTANCE_NAME_HASH_LENGTH: int

def _instance_root(server: PluginServerInterface | None = None) -> str:
    '''This MCDR instance\'s own directory (the parent of ``config/``), or "" when unknown.

    MCDR documents the plugin data folder as ``config/<plugin_id>`` inside the instance
    directory, so two directories up from it is the instance itself -- the one path that is
    both unique per installation and independent of the machine name.
    '''
def _sanitize_instance_name(text: str) -> str:
    """Make a directory name typable in ``!!gamesai node token <name>``.

    Only letters, digits, ``-``, ``_`` and ``.`` survive; runs of anything else collapse to one
    ``-``. A name with spaces or CJK in it cannot be pasted into the command, and a name that
    contains a newline would split the log line that announces it.
    """
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
def _resolve_cross_server_name(server: PluginServerInterface | None, configured: str) -> tuple[str, bool]:
    """The name this instance registers under, and whether it had to be derived.

    ``websocket.name`` wins whenever it is set. Otherwise the name comes from this instance's
    directory (:func:`_default_instance_name`), which is what keeps two instances on one
    machine apart and survives a machine rename.
    """
def _identity_path(server: PluginServerInterface | None = None) -> str | None:
    """Where this instance keeps its own token (``websocket.identity_file`` overrides it).

    The override is taken verbatim (as an absolute path), because an operator who names a file
    means that file; the default moves with the rest of the link state.
    """
def _node_table_path(server: PluginServerInterface | None = None) -> str | None:
    """Where this instance keeps the hub-side node table."""
def _load_identity(server: PluginServerInterface | None = None) -> dict | None:
    '''Read this node\'s identity file. None when it is missing, unreadable or incomplete.

    A corrupt file is treated exactly like "no identity": the node asks to enrol again and
    logs the path, instead of failing to load.
    '''
def _save_identity(server: PluginServerInterface, name: str, token: str, hub: str) -> str | None:
    """Write this node's identity file (chmod 600 on POSIX, best effort). Returns its path."""
def _delete_identity(server: PluginServerInterface | None = None) -> str | None:
    """Delete this node's identity file. Returns the path when a file was removed."""
def _identity_token_for_link(server: PluginServerInterface, uri: str) -> str:
    '''The token this instance may present to ``uri``, or "" when it must enrol first.

    A token is bound to one name and to the hub it was issued for: a name change or a
    different hub makes the stored identity unusable, and saying so here gives the operator
    an actionable line instead of a bare rejection from the hub.
    '''
def _identity_fingerprint(server: PluginServerInterface | None = None) -> str | None:
    """The fingerprint of this instance's own token (never the token itself)."""
def _cross_server_role_path(server: PluginServerInterface) -> str | None:
    """Where the last decided role is remembered; None when there is no data folder.

    Goes through :func:`_data_folder` like the identity file: both are plugin data, and only
    the plugin interface knows where that lives.
    """
def _read_cross_server_role(server: PluginServerInterface) -> str | None:
    """The role held on the last load, so a reload cannot swap the hub and a client.

    Two instances on one machine share one address: without this memory, whichever loads first
    after a cluster reload binds the port and the other becomes its client, which sticks.
    """
def _save_cross_server_role(server: PluginServerInterface, role: str) -> None: ...

_config_ref: dict | None

def _start_cross_server(server: PluginServerInterface, config: dict, on_ready=None) -> None:
    """Create this instance's cross-server link, deciding the role on a background thread.

    The probe dials the configured uri, so it must not run inside ``on_load``: MCDR would
    wait for the connection attempt before the plugin is considered loaded. ``on_ready`` runs
    on that same thread once the role is settled -- that is when the bot's address is known.
    """
def _repoint_bot_after_role_change(server: PluginServerInterface, config: dict, previous_peer_uri: str, bot_was_running: bool) -> None:
    """Point the Mineflayer bot at the hub this instance ended up with.

    The bot is a client of whichever hub this instance has, so its address is
    ``manager.peer_uri``: the loopback hub this instance hosts in local mode (a random
    ``127.0.0.1`` port), or the hub it dials as a client. A runtime claim moves the instance
    from the first to the second, and a bot left dialling the old port registers nowhere --
    its JS config still names that port on the next start, too. Only a real change is acted
    on, and a bot that was not running is never started here.
    """
def _restart_cross_server(server: PluginServerInterface) -> None:
    """Rebuild the link after the identity file changed (``node claim`` / ``node forget``).

    The role is decided again from scratch: an instance that was unenrolled was in local
    mode, so only a fresh decision can turn it into a client of the hub it just claimed.

    The bot follows that decision: a local -> client transition moves its hub from the
    loopback address this instance hosted to the remote one (and back on client -> local), so
    once the new role is in its config is rewritten and a running bot process is restarted
    (see :func:`_repoint_bot_after_role_change`).
    """
def _stop_cross_server(server: PluginServerInterface | None = None) -> None:
    """Stop the link synchronously: it holds a port (hub) or a socket (node)."""
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
def _run_bot_teardown(server: PluginServerInterface | None, logger) -> list[str]:
    """
    Run :func:`_stop_bot_stack` and publish the result on :data:`_bot_teardown_event`.

    ``server``/``logger`` are passed as arguments on purpose (not read from the module
    globals): this may run after the plugin was unloaded, and by then a replacement plugin
    instance owns those global names. ``_bot_teardown_lock`` serializes teardowns, so a
    reload that arrives while a detached unload is still stopping the bot waits for it (and
    then finds nothing left to do) instead of racing it.
    """
def _teardown_bot_async(server: PluginServerInterface) -> threading.Thread:
    """
    Run the bot teardown on a detached thread (unload path).

    The thread only uses plain Python: the controller object, the WebSocket client, a
    ``Popen`` and the logger object — all captured before the plugin was unloaded, and bound
    as arguments so nothing has to be read from this module's globals afterwards.
    """
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
def _history_store() -> ChatHistoryStore | None:
    """The conversation store, or None while this instance has no data folder yet."""
def _restore_all_histories(server: PluginServerInterface) -> None:
    """Bring every stored conversation back into ``all_chat_param``.

    Runs once per load, after the config is applied (the AI entries decide whether a stored
    conversation can be rebuilt at all) and before any command can be typed. Every row stands on
    its own: a conversation whose model was removed from the config, whose JSON is unreadable or
    whose format is newer than this build is skipped with one log line, and a stored conversation
    never keeps the plugin from loading.
    """
def _save_history(username: str, chat_param: ChatParam) -> None:
    """Store one conversation, or drop its row when nothing is left of it.

    Called right after every finished round and after a message was handed to another user.
    Nothing is buffered, so an unload has nothing to flush: what is stored is the state of the
    last completed round. Only a round still in flight when the plugin unloads is left out --
    ``_history_frozen`` then also keeps that late thread from overwriting newer data.
    """
def ask_ai_dispatcher(source: CommandSource, context: dict): ...
def ask_context(source: CommandSource, player: str | None = None):
    """
    ``!!ask context [player]`` — show how full one conversation is (own by default).

    Read-only: nothing is created and no round is started, so asking about a player who has
    never chatted simply reports that there is nothing to show. The card is a handful of chat
    lines with the details on hover (:meth:`ChatParam.context_view`), because the numbers
    alone (window, usage, distance to the next compression) do not fit next to them.
    """
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
def _ai_id_for(name_or_id: str) -> str:
    '''The AI id behind a configured ``ai_name``, or the input unchanged when nothing matches.

    This replaces the "name_to_id" map that used to be built beside the config: the map had to
    be kept in step with ``plugin_config.all_ai`` by hand, and a reader had to know where it came
    from. A duplicate ``ai_name`` resolves to the last matching entry, exactly as the map did.
    '''
def switch_model(source: CommandSource, context: dict): ...
def _note_player_server(source: CommandSource, chat_param: ChatParam) -> None:
    """Tell the model when a player shows up on a different server.

    Only the *change* is written into the history -- never a tag on every message. A per-message
    tag would grow every request, while a note is added once and then stays part of the prefix,
    so nothing here can invalidate the provider's prefix cache between rounds.

    It runs on the caller's thread: :func:`ask_ai` calls it immediately before it appends the
    question, so the note is in the list first and reads as context for it. Like every other
    helper here it must stay synchronous -- a ``@new_thread`` decorator would let the question
    land first, and a note that arrives after the question explains the wrong thing.
    """
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
def _run_ai_round(source: CommandSource, chat_param: ChatParam, data: list[tuple[str, str]] | None, model: str) -> None:
    """Run one ``!!ask`` round so that no API failure can escape into MCDR's error path.

    The conversation is stored in the ``finally`` branch, i.e. after a finished round, an
    interrupted one (``!!ask stop``) and a failed one alike: whatever the player's history looks
    like afterwards is what the next load restores. A ``!!ask -n`` round carries a
    ``NonHistoryChatParam``, which :func:`_save_history` skips by type.
    """
def ask_ai(source: CommandSource, context: dict, no_history: bool = False, forced: bool = False): ...
def get_username(source: CommandSource) -> str: ...
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
def _notify_relayed_message(server: ServerInterface, target: str, sender: str) -> None:
    """Tell the recipient in game that a message reached their assistant (best effort).

    Only sent when the player is known to be online **on this instance's** Minecraft server: a hub
    cannot see the players of the other instances, and a `/tell` for somebody who is not here
    would only print an error into the console. When the online list cannot be obtained (no
    ``online_player_api``), nothing is sent and the delivery is merely logged.
    """
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

class AiDataManager:
    @staticmethod
    def ai_read_data(source: CommandSource, ai_prefix: str, key: str): ...
    @staticmethod
    def ai_read_all_keys(source: CommandSource, ai_prefix: str): ...
    @staticmethod
    def ai_write_data(source: CommandSource, ai_prefix: str, key: str, value: str): ...
    @staticmethod
    def ai_add_data(source: CommandSource, ai_prefix: str, key: str, value: str): ...
    @staticmethod
    def ai_del_data(source: CommandSource, ai_prefix: str, key: str): ...
    @staticmethod
    def ai_read_all_data(source: CommandSource, ai_prefix: str): ...

def debug(source: CommandSource, context: dict): ...
def debug_threads(source: CommandSource, context: dict):
    """
    ``!!gamesai debug thread`` — list the threads GamesAI holds, with their ids.

    Only the plugin's own threads are listed (everything matching
    :data:`_PLUGIN_THREAD_NAMES`), because that is where a leftover controller from an
    older plugin instance shows up — its name is then the legacy one, not ``games_ai@...``.
    ``#id`` is the id Python uses internally (the one a forced abort targets); ``native=``
    is the operating system's thread id; ``(current)`` marks the thread running the command.
    """
def _format_thread(thread: threading.Thread) -> str:
    """One ``#id name [daemon] native=…`` line for the ``!!gamesai debug thread`` listing."""
def reloader(source: CommandSource, context: dict):
    """
    ``!!gamesai reload`` — reload the config, the tools and the Mineflayer bot.

    Single-flight: two reloads running at the same time used to fight over the same global
    bot state (the launcher of the second one saw the WebSocket port of the first one's dying
    node process still in use and disabled the bot entirely). A reload is never queued,
    because reloading a config twice has no meaning; the later command is rejected instead.
    """
def _reload_body(source: CommandSource, context: dict): ...
def speed_test(source: CommandSource, context: dict): ...
