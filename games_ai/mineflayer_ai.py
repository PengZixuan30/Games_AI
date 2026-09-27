import queue
import threading
import time
import json
import logging
import datetime
from typing import Callable

from .openai_api import response_chat
from .games_ai_tool import get_tool_handler, register_tool, register_bot_tool, get_bot_tool_schemas
from .mineflayer import MineflayerWSClient
from openai import OpenAI
from mcdreforged.command.command_source import CommandSource
from mcdreforged.plugin.si.server_interface import ServerInterface


class _DummyServer:
    def rtr(self, key: str, **kwargs) -> str:
        return key
    def get_plugin_instance(self, _plugin_id: str):
        return None
    logger = logging.getLogger("_DummyServer")


_REAL_SERVER: 'ServerInterface' = None


class _DummySource:
    def reply(self, _msg: str) -> None:
        pass
    def get_server(self):
        return _REAL_SERVER if _REAL_SERVER is not None else _DUMMY_SERVER
    def get_permission_level(self) -> int:
        return 4
    @property
    def is_player(self) -> bool:
        return False


_DUMMY_SERVER = _DummyServer()
_DUMMY_SOURCE = _DummySource()


_controller: "AutonomousBotController | None" = None


def set_bot_controller(ctrl: "AutonomousBotController | None"):
    global _controller
    _controller = ctrl


def get_bot_controller() -> "AutonomousBotController | None":
    return _controller


_MAX_CONVERSATION_MESSAGES = 30

# Every thread this plugin creates is named ``games_ai@...``. The controller thread also
# accepts its legacy name so an instance started by an older version is still recognised.
CONTROLLER_THREAD_NAME = "games_ai@autonomous_bot"
CONTROLLER_THREAD_NAMES = (CONTROLLER_THREAD_NAME, "AutonomousBotAI")


class _ControllerAbort(BaseException):
    """
    Injected into a bot-controller thread by :func:`force_abort_thread` (last resort).

    Derived from ``BaseException`` on purpose: the loop's own ``except Exception`` must not
    swallow it, so the thread really dies at its next bytecode boundary.
    """


def force_abort_thread(thread: threading.Thread, logger: logging.Logger | None = None,
                       timeout: float = 1.0) -> bool:
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
    log = logger or logging.getLogger(__name__)
    if thread is None or not thread.is_alive() or thread.ident is None:
        return True
    try:
        import ctypes
        affected = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_ulong(thread.ident), ctypes.py_object(_ControllerAbort)
        )
    except Exception as e:                                  # pragma: no cover - defensive
        log.error("[AutonomousBot] async abort failed for %s: %s", thread.name, e)
        return not thread.is_alive()
    if affected > 1:                                        # never leave more than one hit
        try:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(thread.ident), None)
        except Exception:
            pass
        log.error("[AutonomousBot] async abort touched %d threads, rolled back", affected)
        return not thread.is_alive()
    log.warning("[AutonomousBot] forced abort sent to thread '%s' (it exits as soon as its "
                "current blocking call returns)", thread.name)
    thread.join(timeout=timeout)
    return not thread.is_alive()


_LK = "games_ai.autonomous_bot"


@register_tool(
    description=(
        "Hand a complex Minecraft-bot task over to the autonomous bot controller, which decides "
        "and performs the individual steps (navigation, digging, placing, ...) in its own thread. "
        "Only call this when the task really requires the bot to act in the Minecraft world; "
        "plain questions do not need it."
    ),
    parameters={
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Natural-language description of the task for the bot, including positions and goals when known",
            },
            "username": {
                "type": "string",
                "description": "Name of the player who requested the task",
            },
        },
        "required": ["task"],
    },
)
@register_bot_tool()
def delegate_to_bot(source: CommandSource, ai_prefix: str, task: str, username: str = ""):
    ctrl = get_bot_controller()
    if ctrl is None or not ctrl.is_running:
        return "The autonomous bot controller is not running; check that mineflayer_bot.enabled is on and the bot has been started."

    if not username:
        try:
            username = source.player if source.is_player else "Server"
        except Exception:
            username = "Unknown"

    ctrl.send_user_message(username, task)
    return f"Task delegated to the autonomous bot controller: {task}"


class AutonomousBotController:

    def __init__(
        self,
        ws_client: 'MineflayerWSClient | None',
        model: str,
        base_url: str,
        api_key: str,
        system_prompt: str = "",
        chat_prompt: str = "",
        extra_body: dict | None = None,
        cycle_interval: float = 15.0,
        bot_username: str = "Bot",
        server: 'ServerInterface' = None,
        logger: logging.Logger | None = None,
        tr: Callable[[str, ...], str] | None = None,
        ai_timeout: float = 120.0,
    ):
        global _REAL_SERVER
        if server is not None:
            _REAL_SERVER = server
        self._ws = ws_client
        self._model = model
        self._base_url = base_url
        self._api_key = api_key
        self._openai_client = OpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
        )
        self._system_prompt = system_prompt
        self._chat_prompt = chat_prompt
        self._extra_body = extra_body or {}
        self._cycle_interval = cycle_interval
        self._bot_username = bot_username
        self._log = logger or logging.getLogger(__name__)
        self._tr = tr or (lambda key, **kw: key)

        self._queue: queue.Queue[dict] = queue.Queue()

        self._running = False
        self._paused = threading.Event()
        self._paused.set()
        # Set by stop(): interrupts the idle wait between cycles immediately, so a quiet
        # controller ends right away instead of after one full cycle_interval.
        self._stop_event = threading.Event()
        # Upper bound for one AI request of the controller: without it a stuck request
        # could hold the thread for the full SDK default (up to 10 minutes) after unload.
        self._ai_timeout: float = ai_timeout
        self._thread: threading.Thread | None = None

        self._conversation: list[dict] = []

        self._cycle_count = 0
        self._error_count = 0
        self._last_chat_context: str = ""

        # `!!ask stop` support: usernames whose task is being executed in this cycle,
        # plus a cycle-wide abort flag checked between API calls and tool calls.
        self._cycle_lock = threading.Lock()
        self._cycle_users: set[str] = set()
        self._cycle_abort = threading.Event()

    def stop_user_task(self, username: str) -> bool:
        """
        Drop a player's queued task and abort the cycle that is executing it, if any.

        Pending queue entries of that player are removed; when the running cycle is
        handling a task from that player, the cycle stops at its next checkpoint and the
        messages it produced are discarded instead of being appended to the conversation.

        :return: True when something was actually stopped.
        """
        dropped = 0
        kept: list[dict] = []
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item.get("username") == username:
                dropped += 1
            else:
                kept.append(item)
        for item in kept:
            self._queue.put(item)

        with self._cycle_lock:
            running = username in self._cycle_users
            if running:
                self._cycle_abort.set()

        if dropped or running:
            self._log.info(
                "[AutonomousBot] stop requested for %s (queued=%d, running=%s)", username, dropped, running
            )
            return True
        return False

    def _cycle_stopped(self) -> bool:
        return self._cycle_abort.is_set()

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._paused.set()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name=CONTROLLER_THREAD_NAME)
        self._thread.start()
        self._log.info("[AutonomousBot] Controller started")

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
        self._running = False
        self._paused.set()
        self._stop_event.set()
        self._cycle_abort.set()

        thread = self._thread
        if thread is not None and thread.is_alive():
            try:
                thread.join(timeout=timeout)
            except Exception as e:
                self._log.warning("[AutonomousBot] join failed while stopping: %s", e)

        if thread is not None and thread.is_alive() and force:
            self._log.warning("[AutonomousBot] cooperative stop timed out, forcing the thread to exit")
            force_abort_thread(thread, self._log)

        still_alive = thread is not None and thread.is_alive()
        if still_alive:
            self._log.warning(
                "[AutonomousBot] Controller thread is still running (blocked in a socket/HTTP call); "
                "it exits as soon as that call returns"
            )
        else:
            self._log.info("[AutonomousBot] Controller stopped")
        return not still_alive

    def send_user_message(self, username: str, content: str):
        self._queue.put({"username": username, "content": content, "timestamp": time.time()})

    def pause(self):
        self._paused.clear()
        self._log.info("[AutonomousBot] Paused")

    def resume(self):
        self._paused.set()
        self._log.info("[AutonomousBot] Resumed")

    @property
    def is_paused(self) -> bool:
        return not self._paused.is_set()

    @property
    def is_running(self) -> bool:
        return self._running

    def reload_config(
        self,
        model: str,
        base_url: str,
        api_key: str,
        system_prompt: str = "",
        chat_prompt: str = "",
        extra_body: dict | None = None,
        cycle_interval: float = 15.0,
        bot_username: str = "Bot",
    ) -> None:
        """
        Update controller config in-place. Used on plugin hot-reload so that
        the running controller picks up AI/bot config changes without a full
        Mineflayer restart. Safe to call while the loop is running: the next
        cycle reads the new attributes.
        """
        self._model = model
        self._base_url = base_url
        self._api_key = api_key
        self._openai_client = OpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
        )
        self._system_prompt = system_prompt
        self._chat_prompt = chat_prompt
        self._extra_body = extra_body or {}
        self._cycle_interval = cycle_interval
        self._bot_username = bot_username
        self._log.info("[AutonomousBot] Controller config reloaded")

    # ── internal loop ───────────────────────────────────────

    def _run_loop(self):
        """
        Controller loop. Wrapped as a whole so an injected forced abort (see
        :func:`force_abort_thread`) is reported as a log line instead of an ugly traceback
        printed by ``threading``.
        """
        try:
            while self._running:
                self._paused.wait()
                if self._stop_event.is_set():
                    break

                try:
                    self._one_cycle()
                except _ControllerAbort:
                    raise
                except Exception:
                    self._error_count += 1
                    self._log.exception("[AutonomousBot] Cycle error")

                # interruptible wait: stop() ends a quiet controller immediately instead of
                # after one full cycle_interval
                if self._stop_event.wait(self._cycle_interval):
                    break
        except _ControllerAbort:
            self._log.warning("[AutonomousBot] controller thread aborted")
        finally:
            self._log.info("[AutonomousBot] loop left, controller thread is finishing")

    def _one_cycle(self):
        user_msgs = self._drain_queue()

        with self._cycle_lock:
            self._cycle_users = {um.get("username", "") for um in user_msgs}
            self._cycle_abort.clear()

        try:
            state = self._get_bot_state()

            messages = self._build_messages(state, user_msgs)
            before_count = len(messages)

            reply = self._call_ai_with_tools(messages)

            new_msgs = messages[before_count:]
            if new_msgs and not self._cycle_stopped():
                self._conversation.extend(new_msgs)
            elif new_msgs:
                # interrupted by `!!ask stop`: the half-finished step is dropped
                self._log.info("[AutonomousBot] cycle aborted by stop, %d message(s) discarded", len(new_msgs))

            self._trim_conversation()
        finally:
            with self._cycle_lock:
                self._cycle_users = set()
                self._cycle_abort.clear()

    # ── helpers ─────────────────────────────────────────────

    def _drain_queue(self) -> list[dict]:
        msgs: list[dict] = []
        while True:
            try:
                msgs.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return msgs

    def _get_bot_state(self) -> dict | None:
        if self._ws is None or not self._ws.is_connected:
            return None
        try:
            result = self._ws.send_command("get_state", timeout=5)
            return result.get("data", result)
        except Exception:
            return None

    def _build_messages(self, state: dict | None, user_msgs: list[dict]) -> list[dict]:
        T = self._tr
        msgs: list[dict] = []

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msgs.append({"role": "system", "content": T(f"{_LK}.time", time=now)})

        msgs.append({"role": "system", "content": self._system_prompt})

        msgs.append({"role": "system", "content": T(f"{_LK}.bot_identity", username=self._bot_username)})

        if self._chat_prompt:
            msgs.append({"role": "system", "content": "\n" + T(f"{_LK}.chat_style_prompt", style=self._chat_prompt)})

        if state is not None:
            msgs.append({"role": "system", "content": T(f"{_LK}.bot_state", state=json.dumps(state, ensure_ascii=False, indent=2))})
        else:
            msgs.append({"role": "system", "content": T(f"{_LK}.bot_state_unavailable")})

        for um in user_msgs:
            msgs.append({"role": "user", "content": T(f"{_LK}.user_msg", username=um['username'], content=um['content'])})

        msgs.extend(self._conversation)

        chat_msgs = self._get_chat_messages()
        if chat_msgs:
            msgs.append({"role": "user", "content": T(f"{_LK}.chat_log", messages=chat_msgs)})

        if user_msgs:
            msgs.append({"role": "user", "content": T(f"{_LK}.execute_prompt")})
        elif chat_msgs:
            msgs.append({"role": "user", "content": T(f"{_LK}.chat_execute_prompt")})
        elif not self._conversation:
            msgs.append({"role": "user", "content": T(f"{_LK}.initial_prompt")})
        else:
            msgs.append({"role": "user", "content": T(f"{_LK}.continue_prompt")})

        return msgs

    def _get_chat_messages(self) -> str:
        if self._ws is None or not self._ws.is_connected:
            return ""
        try:
            result = self._ws.send_command("get_chat_messages", timeout=3)
            raw_msgs = result.get("data", {}).get("messages", [])
        except Exception:
            return ""
        if not raw_msgs:
            return ""
        lines = []
        for m in raw_msgs:
            t = m.get("type", "")
            u = m.get("username", "")
            c = m.get("content", "")
            if t == "chat":
                lines.append(f"[公屏] <{u}>: {c}")
            elif t == "whisper":
                lines.append(f"[私聊] {u} 悄悄对你说: {c}")
            elif t == "server":
                lines.append(f"[Server] {c}")
        return "\n".join(lines) if lines else ""

    def _call_ai_with_tools(self, messages: list[dict]) -> dict | None:
        max_loops = 10
        assistant_reply = None

        for _ in range(max_loops):
            if self._cycle_stopped() or self._stop_event.is_set():
                self._log.info("[AutonomousBot] aborted before the next AI call")
                break
            try:
                ai_msg, _usage = response_chat(
                    self._openai_client,
                    model=self._model,
                    response_list=messages,
                    tools=get_bot_tool_schemas(),
                    extra_body=self._extra_body,
                    timeout=self._ai_timeout,
                )
            except Exception:
                self._log.exception("[AutonomousBot] AI call failed")
                return assistant_reply

            if ai_msg.tool_calls is None:
                messages.append(ai_msg)
                assistant_reply = ai_msg
                break

            messages.append(ai_msg)

            for tc in ai_msg.tool_calls:
                if self._cycle_stopped():
                    self._log.info("[AutonomousBot] aborted, remaining tool call(s) skipped")
                    break
                result = self._execute_tool(tc.function.name, tc.function.arguments)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

            assistant_reply = ai_msg

        return assistant_reply

    def _execute_tool(self, func_name: str, arguments: str) -> str:
        if self._ws is None or not self._ws.is_connected:
            return "The bot is not connected to the server (WebSocket not connected), so this action cannot run; try again later."

        handler = get_tool_handler(func_name)
        if handler is None:
            return f"Unknown function: {func_name}"

        try:
            func_args = json.loads(arguments) if arguments else {}
            result = handler.func(_DUMMY_SOURCE, "[AutonomousBot]", **func_args)
            return str(result) if result is not None else "OK"
        except Exception as e:
            return f"Error while executing function {func_name}: {e}"

    def _trim_conversation(self):
        if len(self._conversation) <= _MAX_CONVERSATION_MESSAGES:
            return
        trimmed = self._conversation[-_MAX_CONVERSATION_MESSAGES:]
        for i, msg in enumerate(trimmed):
            role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
            if role == "user":
                self._conversation = trimmed[i:]
                return
        for i, msg in enumerate(trimmed):
            role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
            if role != "tool":
                self._conversation = trimmed[i:]
                return
        self._conversation = trimmed
