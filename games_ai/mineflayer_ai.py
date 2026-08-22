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


_LK = "games_ai.autonomous_bot"


@register_tool(
    description=(
        "当玩家要求执行涉及 Minecraft Bot 操作的复杂任务时，调用此工具将任务移交给自治 Bot 控制器。"
        "Bot 控制器会在独立线程中自主决定具体执行步骤（如导航、挖掘、放置等）。"
        "仅当任务确实需要 Bot 在 Minecraft 世界中执行操作时才调用，纯问答不需要。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "用自然语言描述需要 Bot 执行的任务，尽量包含位置、目标等关键信息",
            },
            "username": {
                "type": "string",
                "description": "发起请求的玩家名称",
            },
        },
        "required": ["task"],
    },
)
@register_bot_tool()
def delegate_to_bot(source: CommandSource, ai_prefix: str, task: str, username: str = ""):
    ctrl = get_bot_controller()
    if ctrl is None or not ctrl.is_running:
        return source.get_server().rtr(f"{_LK}.controller_not_running") if source.get_server() else "Autonomous Bot controller is not running."

    if not username:
        try:
            username = source.player if source.is_player else "Server"
        except Exception:
            username = "Unknown"

    ctrl.send_user_message(username, task)
    return source.get_server().rtr(f"{_LK}.task_delegated", task=task) if source.get_server() else f"Task delegated to bot: {task}"


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
    ):
        global _REAL_SERVER
        if server is not None:
            _REAL_SERVER = server
        self._ws = ws_client
        self._model = model
        self._base_url = base_url
        self._api_key = api_key
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
        self._thread: threading.Thread | None = None

        self._conversation: list[dict] = []

        self._cycle_count = 0
        self._error_count = 0
        self._last_chat_context: str = ""

    def start(self):
        if self._running:
            return
        self._running = True
        self._paused.set()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="AutonomousBotAI")
        self._thread.start()
        self._log.info("[AutonomousBot] Controller started")

    def stop(self):
        self._running = False
        self._paused.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=10)
        self._log.info("[AutonomousBot] Controller stopped")

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

    # ── internal loop ───────────────────────────────────────

    def _run_loop(self):
        while self._running:
            self._paused.wait()

            try:
                self._one_cycle()
            except Exception:
                self._error_count += 1
                self._log.exception("[AutonomousBot] Cycle error")
                time.sleep(self._cycle_interval)
            else:
                time.sleep(self._cycle_interval)

    def _one_cycle(self):
        user_msgs = self._drain_queue()

        state = self._get_bot_state()

        messages = self._build_messages(state, user_msgs)
        before_count = len(messages)

        reply = self._call_ai_with_tools(messages)

        new_msgs = messages[before_count:]
        if new_msgs:
            self._conversation.extend(new_msgs)

        self._trim_conversation()

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
            try:
                ai_msg = response_chat(
                    model=self._model,
                    url=self._base_url,
                    message=messages,
                    api_key=self._api_key,
                    tools=get_bot_tool_schemas(),
                    extra_body=self._extra_body,
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
            return "Bot 尚未连接到服务器（WebSocket 未连接），无法执行此操作。请稍后重试。"

        handler = get_tool_handler(func_name)
        if handler is None:
            return f"未知函数: {func_name}"

        try:
            func_args = json.loads(arguments) if arguments else {}
            result = handler.func(_DUMMY_SOURCE, "[AutonomousBot]", **func_args)
            return str(result) if result is not None else "OK"
        except Exception as e:
            return f"函数 {func_name} 执行出错: {e}"

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
