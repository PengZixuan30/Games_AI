# Generated from games_ai/bot/mineflayer.py by tools/build_tool_stubs.py -- do not edit.
import logging
import subprocess
from ..ai.games_ai_tool import register_bot_tool as register_bot_tool, register_tool as register_tool
from ..cluster.cross_server import CrossServerManager as CrossServerManager
from _typeshed import Incomplete
from mcdreforged.command.command_source import CommandSource as CommandSource

BOT_ACTION: str
_active_bot_peer: BotPeerClient | None
_bot_peer_lock: Incomplete
_process: subprocess.Popen | None
_DEPS_PACKAGES: Incomplete
_DEPS_MARKER_NAME: str
_UNSUPPORTED_VERSION_RE: Incomplete
_DEPS_REPAIR_COOLDOWN: float
_DEPS_REPAIR_MAX: int
_deps_repair_lock: Incomplete
_deps_repair_count: int
_deps_repair_last: float
_NODE_KILL_TIMEOUT: float
_NODE_FORCE_KILL_TIMEOUT: float

def is_node_running() -> bool: ...
def get_mineflayer_client() -> BotPeerClient | None:
    """The bot link of this instance, or None when no bot was ever started."""
def set_bot_peer(manager: CrossServerManager, name: str, logger: logging.Logger | None = None) -> BotPeerClient:
    """Record where the bot is reachable once its JS process was launched.

    The bot dials the cross-server hub now, so there is no socket to open on this side:
    the name it registers with is its Minecraft username.
    """
def clear_bot_peer() -> None:
    """Forget the bot link (plugin unload, bot stopped)."""

class BotPeerClient:
    """Talks to the JS bot process through the cross-server hub.

    The bot is a hub client like every MCDR instance is: it registers under its Minecraft
    username and answers ``bot_action`` requests with the ``{status, data}`` payload it
    always produced. This class keeps the interface the bot tools have always used
    (``is_connected`` and ``send_command``), which is why flipping the direction of the
    connection did not touch their code.
    """
    manager: Incomplete
    name: Incomplete
    timeout: Incomplete
    _log: Incomplete
    def __init__(self, manager: CrossServerManager, name: str, logger: logging.Logger | None = None, timeout: float = 60.0) -> None: ...
    @property
    def uri(self) -> str:
        """Where the bot is expected to be reachable, for log messages."""
    @property
    def is_connected(self) -> bool: ...
    def send_command(self, action: str, params: dict | None = None, timeout: float | None = None) -> dict:
        """Run one bot action and return the legacy ``{request_id, status, data}`` shape."""

def _get_client():
    """Resolve the bot link for a tool call, or the message to report instead."""
def bot_chat(source: CommandSource, ai_prefix: str, message: str): ...
def bot_whisper(source: CommandSource, ai_prefix: str, username: str, message: str): ...
def bot_get_state(source: CommandSource, ai_prefix: str): ...
def bot_call_action(source: CommandSource, ai_prefix: str, action: str, params: dict | None = None): ...
def _install_dependencies(script_dir: str, logger=None, refresh: bool = False):
    """Install (or refresh to latest) the npm dependencies of the bot service.

    Explicit package names are always passed so that ``refresh=True`` upgrades
    every package to the current ``latest`` dist-tag even when node_modules
    already exists. ``--no-save`` keeps the plugin-owned package.json intact.
    A marker file is written on success so that a later launch can skip the
    refresh when the dependencies are already up to date.
    """
def _launch_node(init_js_path: str, logger=None) -> subprocess.Popen:
    """Launch the Node.js bot service and stream its output to the logger."""
def run_node(init_js_path: str, logger=None) -> subprocess.Popen | None:
    """Start the Mineflayer Node.js service.

    Dependencies are installed when node_modules is missing. Existing
    installations created by older plugin versions (no marker file) are
    refreshed once to the latest versions, so the bot keeps working after the
    Minecraft server is upgraded to a newer version.
    """
def _handle_version_unsupported(proc: subprocess.Popen, logger, init_js_path: str | None):
    """Auto-repair when the bot reports an unsupported server version.

    Refreshes the npm dependencies to the latest versions and restarts the
    Node.js service. Guarded by a cooldown and an attempt cap to avoid
    restart loops when the latest mineflayer still does not support the
    server version.
    """
def _stream_process_output(proc: subprocess.Popen, logger, init_js_path: str | None = None): ...
def stop_mineflayer_process(proc: subprocess.Popen | None = None, timeout: float = ...):
    """
    Kill the running node process (this module's one unless ``proc`` is passed).

    The reference is detached before it is killed, so nothing in this module can touch a
    dying process; a caller that already detached it (``detach_mineflayer_process()``) can
    hand the object back in.
    """
def detach_mineflayer_process() -> subprocess.Popen | None:
    """
    Take the node process out of this module's state and return it (no kill).

    Used by the unload path, which finishes the job on a separate thread: after the plugin
    is gone, only a plain ``Popen`` object may be touched, and the next plugin instance must
    see a clean slate instead of a process that is still shutting down.
    """
def _kill_mineflayer_process(proc: subprocess.Popen, timeout: float = ...):
    """
    Make sure one node process is gone, and keep the waits bounded.

    Python can never reap a process that ignores both signals, so the escalation ladder has
    hard limits: SIGTERM/terminate -> (POSIX only) SIGKILL -> (Windows only) taskkill /T /F,
    which also collects the child processes node may have spawned. Every wait is short,
    because the process is a service process that is being replaced or unloaded — waiting
    longer only delays the reload and the bot never disconnects more cleanly for it.
    """
