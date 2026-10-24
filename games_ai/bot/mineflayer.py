import os
import json
import threading
import sys
import subprocess
import signal
import logging
import re
import time
from typing import TYPE_CHECKING

from mcdreforged.command.command_source import CommandSource
from ..ai.games_ai_tool import register_tool, register_bot_tool

if TYPE_CHECKING:
    from ..cluster.cross_server import CrossServerManager

# The action name the bot answers on the hub; the JS side uses the same string.
BOT_ACTION = "bot_action"

_active_bot_peer: "BotPeerClient | None" = None
_bot_peer_lock = threading.Lock()
_process: subprocess.Popen | None = None

_DEPS_PACKAGES = ("mineflayer", "ws", "vec3", "mineflayer-pathfinder", "mineflayer-mcefly")
_DEPS_MARKER_NAME = ".games_ai_deps_ok"
_UNSUPPORTED_VERSION_RE = re.compile(
    r"UNSUPPORTED_SERVER_VERSION|Server version .*? is not supported",
    re.IGNORECASE,
)
_DEPS_REPAIR_COOLDOWN = 600.0
_DEPS_REPAIR_MAX = 3
_deps_repair_lock = threading.Lock()
_deps_repair_count = 0
_deps_repair_last = 0.0


# The node process is a *service* process owned by the launcher, while this Python side is
# a small websocket client of it; a replacement instance may therefore handle it with a
# hard kill. The timeout is short on purpose: the only thing it buys is a clean socket
# teardown before the process dies (a hanging terminate call must not delay an unload).
_NODE_KILL_TIMEOUT = 2.0
# On Windows ``terminate()`` is ``TerminateProcess``/SIGTERM, which is already immediate;
# on POSIX SIGTERM stays catchable, so SIGKILL follows after the wait above.
_NODE_FORCE_KILL_TIMEOUT = 3.0


def is_node_running() -> bool:
    return _process is not None and _process.poll() is None


def get_mineflayer_client() -> "BotPeerClient | None":
    """The bot link of this instance, or None when no bot was ever started."""
    return _active_bot_peer


def set_bot_peer(manager: "CrossServerManager", name: str, logger: logging.Logger | None = None) -> "BotPeerClient":
    """Record where the bot is reachable once its JS process was launched.

    The bot dials the cross-server hub now, so there is no socket to open on this side:
    the name it registers with is its Minecraft username.
    """
    global _active_bot_peer
    with _bot_peer_lock:
        _active_bot_peer = BotPeerClient(manager, name, logger)
        return _active_bot_peer


def clear_bot_peer() -> None:
    """Forget the bot link (plugin unload, bot stopped)."""
    global _active_bot_peer
    with _bot_peer_lock:
        _active_bot_peer = None


class BotPeerClient:
    """Talks to the JS bot process through the cross-server hub.

    The bot is a hub client like every MCDR instance is: it registers under its Minecraft
    username and answers ``bot_action`` requests with the ``{status, data}`` payload it
    always produced. This class keeps the interface the bot tools have always used
    (``is_connected`` and ``send_command``), which is why flipping the direction of the
    connection did not touch their code.
    """

    def __init__(self, manager: "CrossServerManager", name: str, logger: logging.Logger | None = None,
                 timeout: float = 60.0):
        self.manager = manager
        self.name = name
        self.timeout = timeout
        self._log = logger or logging.getLogger(__name__)

    @property
    def uri(self) -> str:
        """Where the bot is expected to be reachable, for log messages."""
        return self.manager.peer_uri

    @property
    def is_connected(self) -> bool:
        return self.manager.connected and self.name in self.manager.peers

    def send_command(self, action: str, params: dict | None = None, timeout: float | None = None) -> dict:
        """Run one bot action and return the legacy ``{request_id, status, data}`` shape."""
        if not self.is_connected:
            raise ConnectionError("Not connected to Mineflayer bot")

        limit = timeout or self.timeout
        reply = self.manager.send_to(
            self.name,
            BOT_ACTION,
            data={"action": action, "params": params or {}},
            wait=True,
            timeout=limit,
        )
        if reply is None or not reply.get("ok"):
            # A bot that answers "this action failed" still answered: its status/error payload
            # is the tool's result, exactly as it was before the link was flipped. Only a
            # transport failure (no reply at all, unknown peer, timeout) is an exception here.
            payload = (reply or {}).get("data") or {}
            if not payload.get("status"):
                error = (reply or {}).get("error", "the bot did not answer")
                if "timeout" in error:
                    raise TimeoutError(f"Command '{action}' timed out after {limit}s")
                raise ConnectionError(f"Command '{action}' failed: {error}")

        payload = reply.get("data") or {}
        return {
            "request_id": reply.get("request_id"),
            "status": payload.get("status", "success"),
            "data": payload.get("data"),
        }


def _get_client():
    """Resolve the bot link for a tool call, or the message to report instead."""
    client = get_mineflayer_client()
    if client is None:
        return None, "Mineflayer Bot was not started. Please start the bot first."
    if not client.is_connected:
        return None, ("The Mineflayer bot is not on the cross-server link. "
                      "It reconnects on its own once the hub is reachable.")
    return client, None


@register_tool(
    description="Send a message to the Minecraft chat as the Mineflayer bot",
    execute_in_hub=True,
    parameters={
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Chat message to send",
            }
        },
        "required": ["message"],
    },
)
@register_bot_tool()
def bot_chat(source: CommandSource, ai_prefix: str, message: str):
    message = re.sub(r'§.', '', message)
    server = source.get_server()
    client, err = _get_client()
    if err is not None:
        return err
    try:
        result = client.send_command("chat", {"message": message})
        source.reply(f"{ai_prefix}{server.rtr('games_ai.tools.bot_chat', message=message)}")
        return f"Bot sent the message: {message}"
    except TimeoutError:
        return "Timed out while sending the message; the bot may not be responding"
    except ConnectionError as e:
        return f"Connection error: {e}"
    except Exception as e:
        return f"Failed to send the message: {e}"


@register_tool(
    description="Send a private message from the Mineflayer bot to a player",
    execute_in_hub=True,
    parameters={
        "type": "object",
        "properties": {
            "username": {
                "type": "string",
                "description": "Name of the player to whisper",
            },
            "message": {
                "type": "string",
                "description": "Private message to send",
            },
        },
        "required": ["username", "message"],
    },
)
@register_bot_tool()
def bot_whisper(source: CommandSource, ai_prefix: str, username: str, message: str):
    message = re.sub(r'§.', '', message)
    server = source.get_server()
    client, err = _get_client()
    if err is not None:
        return err
    try:
        result = client.send_command("whisper", {"username": username, "message": message})
        source.reply(f"{ai_prefix}{server.rtr('games_ai.tools.bot_whisper')}")
        return f"Bot whispered {username}"
    except TimeoutError:
        return "Timed out while sending the whisper; the bot may not be responding"
    except ConnectionError as e:
        return f"Connection error: {e}"
    except Exception as e:
        return f"Failed to send the whisper: {e}"


@register_tool(
    description="Get the current state of the Mineflayer bot (position, health, hunger, game mode, inventory)",
    execute_in_hub=True,
)
@register_bot_tool()
def bot_get_state(source: CommandSource, ai_prefix: str):
    server = source.get_server()
    client, err = _get_client()
    if err is not None:
        return err
    try:
        result = client.send_command("get_state")
        source.reply(f"{ai_prefix}{server.rtr('games_ai.tools.bot_get_state')}")
        data = result.get("data", result)
        return json.dumps(data, ensure_ascii=False, indent=2)
    except TimeoutError:
        return "Timed out while getting the bot state; the bot may not be responding"
    except ConnectionError as e:
        return f"Connection error: {e}"
    except Exception as e:
        return f"Failed to get the bot state: {e}"


@register_tool(
    description=(
        "Send any action to the Mineflayer bot. Available actions:\n"
        "- get_state: full bot state, params: {}\n"
        "- goto: pathfind to coordinates, params: {x, y, z, range?}\n"
        "- efly: fly to coordinates with an elytra (an elytra must be equipped and flight already started), params: {x, y, z}\n"
        "- stopEfly: stop elytra flight, params: {}\n"
        "- stop: stop all movement, params: {}\n"
        "- lookAt: look at coordinates or set the view rotation, params: {x, y, z, force?: bool} or {yaw, pitch, force?: bool}. Direction reference (radians): south=0, west=1.57(pi/2), north=3.14(pi), east=-1.57(-pi/2); pitch: up=-1.57, down=1.57, horizontal=0\n"
        "- dig: break a block, params: {x, y, z}\n"
        "- place: place a block, params: {x, y, z, face?: {x, y, z}}\n"
        "- activateBlock: right-click a block (open a chest, press a button, ...), params: {x, y, z}\n"
        "- equip: equip an item, params: {itemName: string, destination?: string}. destination: hand/head/torso/legs/feet/off-hand"
        "- unequip: take equipment off, params: {destination?: string}. destination: head/torso/chest/legs/feet, default torso\n"
        "- toss: drop items, params: {itemName?: string, amount?: int}\n"
        "- setQuickBarSlot: switch the hotbar slot, params: {slot: int(0-8)}\n"
        "- attack: attack an entity, params: {entityName?: string, range?: float}\n"
        "- useOn: use an item on an entity, params: {entityName: string}\n"
        "- activateItem: use the held item (for example eat), params: {}\n"
        "- deactivateItem: stop using the held item, params: {}\n"
        "- nearbyEntities: list nearby entities, params: {maxDistance?: float, limit?: int}\n"
        "- findBlocks: search for nearby blocks, params: {blockName: string, maxDistance?: float, count?: int}\n"
        "- getBlock: get block information at coordinates, params: {x, y, z}\n"
        "- sleep: sleep in a nearby bed, params: {}\n"
        "- wake: wake up, params: {}\n"
        "- mount: ride an entity (minecart/boat/horse, ...), params: {entityName?: string} (the nearest one is used when omitted)\n"
        "- dismount: leave the ridden entity, params: {}\n"
        "- setControlState: control the ridden entity (forward/back/left/right/jump/sneak/sprint), params: {control: string, state?: bool}\n"
        "- findContainers: find nearby containers, params: {maxDistance?: float, count?: int}\n"
        "- viewContainer: view the contents of a container, params: {x, y, z}\n"
        "- takeFromContainer: take items from a container into the inventory, params: {x, y, z, itemName: string, count?: int}\n"
        "- putToContainer: put items from the inventory into a container, params: {x, y, z, itemName: string, count?: int}\n"
        "- openFurnace: open a furnace and view its state, params: {x, y, z}\n"
        "- furnacePutInput: put items into a furnace to smelt them, params: {x, y, z, itemName: string, count?: int}\n"
        "- furnacePutFuel: put fuel into a furnace, params: {x, y, z, itemName: string, count?: int}\n"
        "- furnaceTakeOutput: take the smelted output out of a furnace, params: {x, y, z}\n"
        "- craft: craft an item (inventory or crafting table), params: {itemName: string, count?: int, x?, y?, z?} (crafts in the inventory when no coordinates are given)"
    ),
    execute_in_hub=True,
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Action name to run, e.g. 'goto' or 'get_state'. Note: send messages with bot_chat or bot_whisper instead of this tool",
            },
            "params": {
                "type": "object",
                "description": "Parameters for the action, as a JSON object, e.g. {'message': 'hello'} or {}",
            },
        },
        "required": ["action"],
    },
)
@register_bot_tool()
def bot_call_action(source: CommandSource, ai_prefix: str, action: str, params: dict | None = None):
    if action in ("chat", "whisper"):
        return "Do not send messages through bot_call_action; use the dedicated bot_chat or bot_whisper tool instead"
    server = source.get_server()
    client, err = _get_client()
    if err is not None:
        return err
    try:
        timeout = 90 if action == 'goto' else None
        result = client.send_command(action, params or {}, timeout=timeout)
        source.reply(f"{ai_prefix}{server.rtr('games_ai.tools.bot_call_action', action=action)}")
        data = result.get("data", result)
        status = result.get("status", "unknown")
        if status == "error":
            return f"The bot returned an error: {data.get('error', data)}"
        return json.dumps(data, ensure_ascii=False, indent=2)
    except TimeoutError:
        return f"Action '{action}' timed out; the bot may not be responding"
    except ConnectionError as e:
        return f"Connection error: {e}"
    except Exception as e:
        return f"Failed to run action '{action}': {e}"


def _install_dependencies(script_dir: str, logger=None, refresh: bool = False):
    """Install (or refresh to latest) the npm dependencies of the bot service.

    Explicit package names are always passed so that ``refresh=True`` upgrades
    every package to the current ``latest`` dist-tag even when node_modules
    already exists. ``--no-save`` keeps the plugin-owned package.json intact.
    A marker file is written on success so that a later launch can skip the
    refresh when the dependencies are already up to date.
    """
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    if logger:
        logger.info("[Mineflayer] Installing/updating npm dependencies, this may take a while...")
    try:
        result = subprocess.run(
            [npm_cmd, "install", "--no-save", "--no-audit", "--no-fund", *list(_DEPS_PACKAGES)],
            cwd=script_dir,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if logger:
            for line in (result.stdout + result.stderr).splitlines():
                line = line.strip()
                if line:
                    logger.info(f"[Mineflayer] {line}")
        if result.returncode != 0:
            msg = f"npm install failed (exit {result.returncode}): {result.stderr[-500:]}"
            if logger:
                logger.error(f"[Mineflayer] {msg}")
            raise RuntimeError(msg)
        with open(os.path.join(script_dir, _DEPS_MARKER_NAME), "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
        if logger:
            logger.info("[Mineflayer] npm dependencies installed successfully")
    except FileNotFoundError:
        msg = "npm is not installed or not in PATH"
        if logger:
            logger.error(f"[Mineflayer] {msg}")
        raise RuntimeError(msg) from None


def _launch_node(init_js_path: str, logger=None) -> subprocess.Popen:
    """Launch the Node.js bot service and stream its output to the logger."""
    global _process
    script_dir = os.path.dirname(os.path.abspath(init_js_path))
    abs_init_js = os.path.abspath(init_js_path)
    if not os.path.isfile(abs_init_js):
        raise FileNotFoundError(f"init.js not found at {abs_init_js}")

    if logger:
        logger.info(f"[Mineflayer] Launching node {abs_init_js}")

    node_cmd = "node"
    use_output = logger is not None
    if sys.platform == "win32":
        _process = subprocess.Popen(
            [node_cmd, abs_init_js],
            cwd=script_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if use_output else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if use_output else subprocess.DEVNULL,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        _process = subprocess.Popen(
            [node_cmd, abs_init_js],
            cwd=script_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if use_output else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if use_output else subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
    if use_output:
        threading.Thread(
            target=_stream_process_output,
            args=(_process, logger, abs_init_js),
            daemon=True,
            name="games_ai@mineflayer_log",
        ).start()

    return _process


def run_node(init_js_path: str, logger=None) -> subprocess.Popen | None:
    """Start the Mineflayer Node.js service.

    Dependencies are installed when node_modules is missing. Existing
    installations created by older plugin versions (no marker file) are
    refreshed once to the latest versions, so the bot keeps working after the
    Minecraft server is upgraded to a newer version.
    """
    global _process
    with _deps_repair_lock:
        _kill_mineflayer_process(_process)
        script_dir = os.path.dirname(os.path.abspath(init_js_path))

        node_modules_dir = os.path.join(script_dir, "node_modules")
        marker_path = os.path.join(script_dir, _DEPS_MARKER_NAME)

        if not os.path.isdir(node_modules_dir):
            _install_dependencies(script_dir, logger, refresh=False)
        elif not os.path.isfile(marker_path):
            # node_modules exists but was installed by an older plugin version
            # (or manually): refresh it once so the installed mineflayer
            # supports the current server version.
            try:
                _install_dependencies(script_dir, logger, refresh=True)
            except RuntimeError as e:
                if logger:
                    logger.warning(
                        f"[Mineflayer] Could not refresh npm dependencies ({e}), "
                        "starting with the existing dependencies..."
                    )

        return _launch_node(init_js_path, logger)


def _handle_version_unsupported(proc: subprocess.Popen, logger, init_js_path: str | None):
    """Auto-repair when the bot reports an unsupported server version.

    Refreshes the npm dependencies to the latest versions and restarts the
    Node.js service. Guarded by a cooldown and an attempt cap to avoid
    restart loops when the latest mineflayer still does not support the
    server version.
    """
    global _process, _deps_repair_count, _deps_repair_last
    with _deps_repair_lock:
        if _process is not proc:
            return  # the process was already replaced or stopped; nothing to repair here
        now = time.time()
        if _deps_repair_count >= _DEPS_REPAIR_MAX:
            if logger:
                logger.error(
                    "[Mineflayer] Server version is not supported by mineflayer and the "
                    f"dependency refresh was already attempted {_deps_repair_count} time(s). "
                    "Please update this plugin or wait for a newer mineflayer release on npm."
                )
            return
        if now - _deps_repair_last < _DEPS_REPAIR_COOLDOWN:
            if logger:
                logger.warning(
                    "[Mineflayer] Unsupported server version detected again, "
                    "will retry the dependency refresh later..."
                )
            return
        _deps_repair_count += 1
        _deps_repair_last = now
        if logger:
            logger.warning(
                "[Mineflayer] Detected unsupported server version. Updating npm "
                "dependencies and restarting the bot..."
            )
        try:
            # Install first so a failed refresh does not kill the (broken but
            # alive) old process.
            script_dir = os.path.dirname(os.path.abspath(init_js_path)) if init_js_path else None
            if script_dir:
                _install_dependencies(script_dir, logger, refresh=True)
            _kill_mineflayer_process(_process)
            if init_js_path:
                _launch_node(init_js_path, logger)
        except Exception as e:
            if logger:
                logger.error(f"[Mineflayer] Failed to update dependencies and restart the bot: {e}")


def _stream_process_output(proc: subprocess.Popen, logger, init_js_path: str | None = None):
    try:
        for line in iter(proc.stdout.readline, ''):
            if not line:
                break
            line = line.rstrip('\n\r')
            if line:
                logger.info(f"[Mineflayer] {line}")
                if _UNSUPPORTED_VERSION_RE.search(line):
                    _handle_version_unsupported(proc, logger, init_js_path)
    except (ValueError, OSError):
        pass
    finally:
        try:
            proc.stdout.close()
        except (ValueError, OSError):
            pass


def stop_mineflayer_process(proc: subprocess.Popen | None = None, timeout: float = _NODE_KILL_TIMEOUT):
    """
    Kill the running node process (this module's one unless ``proc`` is passed).

    The reference is detached before it is killed, so nothing in this module can touch a
    dying process; a caller that already detached it (``detach_mineflayer_process()``) can
    hand the object back in.
    """
    global _process
    target = proc
    if target is None:
        target = _process
        _process = None
    if target is None:
        return
    _kill_mineflayer_process(target, timeout)


def detach_mineflayer_process() -> subprocess.Popen | None:
    """
    Take the node process out of this module's state and return it (no kill).

    Used by the unload path, which finishes the job on a separate thread: after the plugin
    is gone, only a plain ``Popen`` object may be touched, and the next plugin instance must
    see a clean slate instead of a process that is still shutting down.
    """
    global _process
    proc = _process
    _process = None
    return proc


def _kill_mineflayer_process(proc: subprocess.Popen, timeout: float = _NODE_KILL_TIMEOUT):
    """
    Make sure one node process is gone, and keep the waits bounded.

    Python can never reap a process that ignores both signals, so the escalation ladder has
    hard limits: SIGTERM/terminate -> (POSIX only) SIGKILL -> (Windows only) taskkill /T /F,
    which also collects the child processes node may have spawned. Every wait is short,
    because the process is a service process that is being replaced or unloaded — waiting
    longer only delays the reload and the bot never disconnects more cleanly for it.
    """
    if proc is None:
        return
    pid = proc.pid
    if pid is None:
        return

    if proc.poll() is None:
        try:
            proc.terminate()
        except OSError:
            pass
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # SIGTERM was not enough. On Windows TerminateProcess is already unconditional,
            # so this is usually a process stuck in the kernel; taskkill /T /F collects the
            # tree. On POSIX SIGKILL is the last resort.
            if sys.platform == "win32":
                try:
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                                   capture_output=True, timeout=10)
                except (OSError, subprocess.SubprocessError):
                    pass
            else:
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
            try:
                proc.wait(timeout=_NODE_FORCE_KILL_TIMEOUT)
            except subprocess.TimeoutExpired:
                pass
    try:
        proc.stdout.close()
    except (AttributeError, ValueError, OSError):
        pass
