from abc import ABC, abstractmethod
from openai import OpenAI
import json, datetime, threading

from .openai_api import response_chat
from .config import plugin_config
from .games_ai_tool import get_tool_handler, get_tool_schemas_for_perm
from .external_skills_loader import EXTERNAL_SKILLS_LIST

from mcdreforged.command.command_source import CommandSource
from mcdreforged.plugin.si.server_interface import ServerInterface
from openai.types.chat.chat_completion_message_function_tool_call import ChatCompletionMessageFunctionToolCall

class BasicChatParam(ABC):
    """
    A abstract basic class about ChatParam Object.
    """

    allow_type = [
        'system',
        'user',
        'assistant',
        'tool'
    ]

    def __init__(
        self,
        server: 'ServerInterface',
        *,
        model_id: str | None = None,
    ):
        self.server = server
        self.model_id: str | None = model_id
        self.ai_info: dict = plugin_config.all_ai.get(self.model_id, {})
        self.openai_client: OpenAI | None = None
        self.response_list: list[dict] = []
        self.system_message: list[dict] = []

        self.response_queue: list[dict] = []

        self.tool_count: int = 0

        self.is_stopped = threading.Event()
        self.is_stopped.set()

    @property
    def get_response_list(self) -> list[dict]:
        return self.response_list

    @property
    def get_response_queue(self) -> list[dict]:
        return self.response_queue
    
    @property
    def get_openai_client(self) -> OpenAI | None:
        return self.openai_client

    @property
    def get_model_id(self) -> str | None:
        return self.model_id

    @property
    def get_is_stopped(self) -> bool:
        return self.is_stopped.is_set()

    @abstractmethod
    def build_openai_client(self) -> None:
        """
        Build a OpenAI client object
        """
        pass

    @abstractmethod
    def build_system_message(self) -> list[dict]:
        pass

    @abstractmethod
    def add_to_response_list(self, type: str, content: str, *, args: dict | None = None) -> None:
        """
        Add a message to response queue
        """
        pass

    @abstractmethod
    def forced_add_to_response_list(self, type: str, content: str) -> None:
        """
        Forced add a message to response queue
        """
        pass

    @abstractmethod
    def tool_call(self, source: CommandSource, tool_calls: list[ChatCompletionMessageFunctionToolCall]) -> None:
        """
        Auto run tools.
        """
        pass

    @abstractmethod
    def response_ai(self, source: CommandSource, data: list[tuple[str, str]]) -> None:
        """
        Response AI loop
        """
        pass

    @abstractmethod
    def change_model(self, source: CommandSource, model_id: str) -> None:
        """
        Change the model and re-build a OpenAI client object and re-build system message
        """
        pass

    def trim_response_list(self, max_len: int = 0) -> None:
        """
        Trim response queue safely that reduce AI context
        """
        if max_len <= 0:
            self.response_list.clear()
            return
        if len(self.response_list) <= max_len:
            return
    
        trimmed = self.response_list[-max_len:]
    
        for i, msg in enumerate(trimmed):
            role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
            if role == "user":
                self.response_list = trimmed[i:]
                return
    
        self.response_list = trimmed

    def wait_until_stop(self) -> None:
        """
        Wait this round stop
        """
        self.is_stopped.wait()

    def _log(self, msg: str) -> None:
        """Debug-mode logging: INFO level when !!gamesai debug is on, DEBUG otherwise."""
        try:
            if plugin_config.debug_mode:
                self.server.logger.info(f"[ChatParam]{msg}")
            else:
                self.server.logger.debug(f"[ChatParam]{msg}")
        except Exception:
            pass

    def reload_ai_info(self) -> None:
        self.ai_info: dict = plugin_config.all_ai.get(self.model_id, {})
        self.build_openai_client()
        self.build_system_message()


class ChatParam(BasicChatParam):

    def __init__(
        self,
        server: 'ServerInterface',
        *,
        model_id: str | None = None,
    ):
        super().__init__(server, model_id=model_id)
        self.build_openai_client()

    def build_openai_client(self) -> None:
        if self.model_id is None:
            raise TypeError("model_id must be string")
        api_key = self.ai_info.get("api_key")
        base_url = self.ai_info.get("base_url")
        if api_key is None or base_url is None:
            raise AttributeError("api_key and base_url missing")
        self.openai_client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )

    def build_system_message(self) -> list[dict]:
        prompt = str(self.ai_info.get("prompt", ""))
        now_time = str(self.server.rtr("games_ai.user_message.time", time=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

        skills = plugin_config.skills_description
        default_skills = [
            {"file": "skills_management.md", "description": str(self.server.rtr("games_ai.builtin_skills.skills_management"))},
            {"file": "custom_tools_management.md", "description": str(self.server.rtr("games_ai.builtin_skills.custom_tools_management"))},
            {"file": "mineflayer_bot_guide.md", "description": str(self.server.rtr("games_ai.builtin_skills.mineflayer_bot_guide", username=plugin_config.bot_username))},
        ]
        external_skills: list[dict[str, str]] = []
        if EXTERNAL_SKILLS_LIST:
            for i in EXTERNAL_SKILLS_LIST:
                file = i.get("file")
                description = i.get("description")
                if file is None or description is None:
                    continue
                external_skills.append({"file": file, "description": description})
        if external_skills:
            skills_file_list = str(self.server.rtr("games_ai.user_message.skills", skills=[*skills, *default_skills, *external_skills]))
        else:
            skills_file_list = str(self.server.rtr("games_ai.user_message.skills", skills=[*skills, *default_skills]))

        self.system_message.clear()
        self.system_message.append({
            "role": "system",
            "content": now_time,
        })
        self.system_message.append({
            "role": "system",
            "content": prompt,
        })
        self.system_message.append({
            "role": "system",
            "content": skills_file_list
        })

        return self.system_message

    def add_to_response_list(self, type: str, content: str, *, args: dict | None = None) -> None:
        if type not in self.allow_type:
            raise TypeError("Response type must be 'system', 'user', 'assistant', 'tool'")
        if not isinstance(type, str) or not isinstance(content, str):
            raise TypeError("type or content must be string")
        new = {}
        if args:
            new = args
        new["role"] = type
        new["content"] = content
        self.response_list.append(new)

    def forced_add_to_response_list(self, type: str, content: str) -> None:
        if type not in ['system', 'user']:
            raise TypeError("Forced add to response queue by type must be 'system' or 'user'")
        if not isinstance(type, str) or not isinstance(content, str):
            raise TypeError("type or content must be string")
        new = {}
        new["role"] = type
        new["content"] = content
        self.response_queue.append(new)

    def tool_call(self, source: CommandSource, tool_calls: list[ChatCompletionMessageFunctionToolCall]) -> None:
        ai_prefix = self.ai_info.get("ai_name", "")
        for tool_call in tool_calls:
            func_name = tool_call.function.name
            handler = get_tool_handler(func_name)
            self.tool_count += 1

            if handler is None:
                result = f"未知函数: {func_name}"
                source.reply(f'{ai_prefix}{self.server.rtr("games_ai.tools.unknown_function",func_name=func_name)}')
            else:
                try:
                    func_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                    result = str(handler.func(source, ai_prefix, **func_args))
                    source.reply(f'{ai_prefix}{self.server.rtr("games_ai.tools.tool_success")}')
                except Exception as e:
                    result = f"函数 {func_name} 执行出错: {e}"
                    source.reply(f'{ai_prefix}{self.server.rtr("games_ai.tools.execution_error",func_name=func_name,ex=e)}')

            self.add_to_response_list("tool", result, args={"tool_call_id": tool_call.id})
            self._log(f"tool_call: {func_name} (tool_count={self.tool_count})")

    def response_ai(self, source: CommandSource, data: list[tuple[str, str]]) -> None:
        self.is_stopped.clear()

        merged_leftover = len(self.response_queue)
        self.response_list.extend(self.response_queue)
        self.response_queue.clear()
        if merged_leftover:
            self._log(f"response_ai start: merged {merged_leftover} leftover queued message(s) into history")

        system = self.build_system_message()
        system.append({"role": "system","content": f'{str(self.server.rtr("games_ai.user_message.data_list"))}{data}'})

        ai_model = self.ai_info.get("ai_model", "")
        ai_prefix = self.ai_info.get("ai_name", "")
        ai_tools = get_tool_schemas_for_perm(source.get_permission_level())
        extra_body = self.ai_info.get("extra_body", {})
        self._log(f"response_ai start: model={ai_model}, history={len(self.response_list)}, queue={len(self.response_queue)}")
        while True:
            try:
                ai_reply = response_chat(
                    self.openai_client,
                    model=ai_model,
                    response_list=system + self.response_list,
                    tools=ai_tools,
                    extra_body= extra_body
                )
                self.response_list.append(ai_reply)
                if ai_reply.content:
                    source.reply(f"{ai_prefix}{ai_reply.content}")

                if ai_reply.tool_calls:
                    self.tool_call(source, ai_reply.tool_calls)

                has_queue = bool(self.response_queue)

                if has_queue:
                    n = len(self.response_queue)
                    self.response_list.extend(self.response_queue)
                    self.response_queue.clear()
                    self._log(f"merged {n} queued message(s) into running round (continue)")

                if ai_reply.tool_calls or has_queue:
                    continue
                self.trim_response_list(max_len=plugin_config.max_history * 2 + self.tool_count * 2)
                self._log(f"response_ai finished: history={len(self.response_list)}")
                break
            except Exception as e:
                error_code_map = {
                    400: self.server.rtr("games_ai.error_code_map.error400"),
                    401: self.server.rtr("games_ai.error_code_map.error401"),
                    402: self.server.rtr("games_ai.error_code_map.error402"),
                    403: self.server.rtr("games_ai.error_code_map.error403"),
                    404: self.server.rtr("games_ai.error_code_map.error404"),
                    408: self.server.rtr("games_ai.error_code_map.error408"),
                    422: self.server.rtr("games_ai.error_code_map.error422"),
                    429: self.server.rtr("games_ai.error_code_map.error429"),
                    500: self.server.rtr("games_ai.error_code_map.error500"),
                    502: self.server.rtr("games_ai.error_code_map.error502"),
                    503: self.server.rtr("games_ai.error_code_map.error503"),
                }
    
                error_code = getattr(e, 'status_code', None)
                request_id = None
    
                resp = getattr(e, 'response', None)
                if resp is not None:
                    request_id = getattr(resp, '_request_id', None)
    
                if request_id is None:
                    try:
                        request_id = ai_reply._request_id
                    except (NameError, AttributeError):
                        request_id = None
    
                if error_code is not None:
                    error_desc = error_code_map.get(error_code, f"未知错误 (HTTP {error_code})")
                    rid_str = f" [Request ID: {request_id}]" if request_id else ""
                    source.reply(f'{ai_prefix}ERROR! [Code: {error_code}] {error_desc}{rid_str}\n{ai_prefix}{e}')
                else:
                    source.reply(f'{ai_prefix}ERROR!\n{ai_prefix}{e}')
                self._log(f"response_ai error: {e}")
                self.is_stopped.set()
                raise e
        self.is_stopped.set()

    def change_model(self, source: CommandSource, model_id: str) -> None:
        self.model_id = model_id
        self.ai_info: dict = plugin_config.all_ai.get(self.model_id, {})
        self.build_openai_client()
        self.build_system_message()
