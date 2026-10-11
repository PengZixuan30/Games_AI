# Generated from games_ai/bot/mineflayer_ai.py by tools/build_tool_stubs.py -- do not edit.
import logging
import queue
import threading
from ..ai.games_ai_tool import get_bot_tool_schemas as get_bot_tool_schemas, get_tool_handler as get_tool_handler, register_bot_tool as register_bot_tool, register_tool as register_tool
from ..ai.openai_api import response_chat as response_chat
from ..core import clock as clock
from .mineflayer import BotPeerClient as BotPeerClient
from _typeshed import Incomplete
from mcdreforged.command.command_source import CommandSource as CommandSource
from mcdreforged.plugin.si.server_interface import ServerInterface as ServerInterface
from typing import Callable

class _DummyServer:
    def rtr(self, key: str, **kwargs) -> str: ...
    def get_plugin_instance(self, _plugin_id: str): ...
    logger: Incomplete

_REAL_SERVER: ServerInterface

class _DummySource:
    def reply(self, _msg: str) -> None: ...
    def get_server(self): ...
    def get_permission_level(self) -> int: ...
    @property
    def is_player(self) -> bool: ...

_DUMMY_SERVER: Incomplete
_DUMMY_SOURCE: Incomplete
_controller: AutonomousBotController | None

def set_bot_controller(ctrl: AutonomousBotController | None): ...
def get_bot_controller() -> AutonomousBotController | None: ...

_MAX_CONVERSATION_MESSAGES: int
CONTROLLER_THREAD_NAME: str
CONTROLLER_THREAD_NAMES: Incomplete

class _ControllerAbort(BaseException):
    """
    Injected into a bot-controller thread by :func:`force_abort_thread` (last resort).

    Derived from ``BaseException`` on purpose: the loop's own ``except Exception`` must not
    swallow it, so the thread really dies at its next bytecode boundary.
    """

def force_abort_thread(thread: threading.Thread, logger: logging.Logger | None = None, timeout: float = 1.0) -> bool:
    """
    Kill a stuck thread the hard way: raise :class:`_ControllerAbort` inside it.

    Python cannot kill a thread, so this is the escape hatch used only after the
    cooperative stop timed out (plugin unload / reload, or a leftover thread from a
    previous plugin instance). It cannot interrupt a blocking C call — a socket read or an
    HTTP request keeps running — but the exception fires the moment that call returns, so
    the thread dies then instead of finishing its cycle.

    The controller writes no files and no database rows, so the worst case is one bot
    action left half-issued (the Node process is killed as well during unload).

    :return: True when the thread is gone.
    """

_LK: str

def delegate_to_bot(source: CommandSource, ai_prefix: str, task: str, username: str = ''): ...

class AutonomousBotController:
    _ws: Incomplete
    _model: Incomplete
    _base_url: Incomplete
    _api_key: Incomplete
    _openai_client: Incomplete
    _system_prompt: Incomplete
    _chat_prompt: Incomplete
    _extra_body: Incomplete
    _cycle_interval: Incomplete
    _bot_username: Incomplete
    _log: Incomplete
    _tr: Incomplete
    _queue: queue.Queue[dict]
    _running: bool
    _paused: Incomplete
    _stop_event: Incomplete
    _ai_timeout: float
    _thread: threading.Thread | None
    _conversation: list[dict]
    _cycle_count: int
    _error_count: int
    _last_chat_context: str
    _cycle_lock: Incomplete
    _cycle_users: set[str]
    _cycle_abort: Incomplete
    def __init__(self, ws_client: BotPeerClient | None, model: str, base_url: str, api_key: str, system_prompt: str = '', chat_prompt: str = '', extra_body: dict | None = None, cycle_interval: float = 15.0, bot_username: str = 'Bot', server: ServerInterface = None, logger: logging.Logger | None = None, tr: Callable[[str, ...], str] | None = None, ai_timeout: float = 120.0) -> None: ...
    def stop_user_task(self, username: str) -> bool:
        """
        Drop a player's queued task and abort the cycle that is executing it, if any.

        Pending queue entries of that player are removed; when the running cycle is
        handling a task from that player, the cycle stops at its next checkpoint and the
        messages it produced are discarded instead of being appended to the conversation.

        :return: True when something was actually stopped.
        """
    def _cycle_stopped(self) -> bool: ...
    def start(self) -> None: ...
    def stop(self, timeout: float = 10.0, force: bool = False) -> bool:
        """
        Stop the loop: cooperatively first, then (with ``force``) immediately.

        Never raises, so plugin unload cannot be blocked by a busy controller.

        1. ``_stop_event`` wakes the idle wait between cycles, and ``_cycle_abort`` makes a
           running cycle wind down at its next checkpoint (before the next AI call, or
           between two tool calls);
        2. if the thread is still alive after ``timeout`` and ``force`` is set, an abort is
           injected into it (:func:`force_abort_thread`) so it dies at its next bytecode
           boundary instead of finishing the cycle. That is what unload / reload use.

        :return: True when the thread has really finished. False only when it is still
                 blocked inside a C call (socket read / HTTP request); it dies right after
                 that call returns, or together with the MCDR process.
        """
    def send_user_message(self, username: str, content: str): ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    @property
    def is_paused(self) -> bool: ...
    @property
    def is_running(self) -> bool: ...
    def reload_config(self, model: str, base_url: str, api_key: str, system_prompt: str = '', chat_prompt: str = '', extra_body: dict | None = None, cycle_interval: float = 15.0, bot_username: str = 'Bot') -> None:
        """
        Update controller config in-place. Used on plugin hot-reload so that
        the running controller picks up AI/bot config changes without a full
        Mineflayer restart. Safe to call while the loop is running: the next
        cycle reads the new attributes.
        """
    def _run_loop(self) -> None:
        """
        Controller loop. Wrapped as a whole so an injected forced abort (see
        :func:`force_abort_thread`) is reported as a log line instead of an ugly traceback
        printed by ``threading``.
        """
    def _one_cycle(self) -> None: ...
    def _drain_queue(self) -> list[dict]: ...
    def _get_bot_state(self) -> dict | None: ...
    def _build_messages(self, state: dict | None, user_msgs: list[dict]) -> list[dict]: ...
    def _get_chat_messages(self) -> str: ...
    def _call_ai_with_tools(self, messages: list[dict]) -> dict | None: ...
    def _execute_tool(self, func_name: str, arguments: str) -> str: ...
    def _trim_conversation(self) -> None: ...
