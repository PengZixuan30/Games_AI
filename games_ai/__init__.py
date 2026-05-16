from mcdreforged.api.all import *

from .openai_api import response_chat
from .games_ai_tool import TOOL_SCHEMAS, get_tool_handler, register_tool
from .database import PublicDatabase
from .config import plugin_config
from .tools_interpreter import load_external_tools

import time,os,requests,lzma,json,threading,datetime

PLUGIN_METADATA = {
    "id": "games_ai",
    "version": "0.5.1",
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

history_conversation = {}
unload_status_code = 0
debug_mode = False

def on_load(server: PluginServerInterface, old):
    global prefix,allow_permission,max_history,allow_permission,mcdr_lang,_timer,ai_dict,default_ai,name_to_id,data_path
    _timer = None
    
    DEFAULT_CONFIG = {
        "prefix": "[GamesAI]",
        "permission": 3,
        "max_history": 10,
        "all_ai": {
            "<Your AI ID>":{
                "prompt": server.rtr("games_ai.system_message.default"),
                "ai_name": "[GamesAI]",
                "base_url": "<Your API Base URL>",
                "ai_model": "<Your AI Model>",
                "api_key": "<Your API Key>",
                "thinking": False,
            }
        },
        "default_ai": "<Your AI ID>"
    }
    
    server.register_help_message(prefix="!!gamesai",message=server.rtr("games_ai.mcdr_help_message.gamesai_help"))
    server.register_help_message(prefix="!!ask <content>",message=server.rtr("games_ai.mcdr_help_message.gamesai_ask"))

    config = server.load_config_simple(
        file_name='config.json',
        default_config=DEFAULT_CONFIG,
        in_data_folder=True
    )

    prefix = config.get('prefix','[GamesAI]')
    max_history = config.get('max_history',10)
    allow_permission = config.get('permission',3)

    plugin_config.prefix = prefix
    plugin_config.allow_permission = allow_permission
    plugin_config.max_history = max_history

    prompt_path = os.path.join(server.get_data_folder(), "prompt")
    if not os.path.exists(prompt_path):
        os.makedirs(prompt_path, exist_ok=True)

    ai_dict = {}

    all_ai: dict = config.get('all_ai', {})
    for ai_id,ai_config in all_ai.items():
        if not isinstance(ai_config, dict):
            continue
        raw_prompt: str = ai_config.get("prompt", server.rtr("games_ai.system_message.default"))
        if raw_prompt.startswith("> "):
            prompt_file_path = raw_prompt[2:].strip()
            prompt_full_path = os.path.join(server.get_data_folder(), "prompt", prompt_file_path)
            try:
                with open(prompt_full_path, 'r', encoding='utf-8') as f:
                    raw_prompt = f.read()
                server.logger.info(f"{prefix} Loaded prompt from file: {prompt_full_path}")
            except FileNotFoundError:
                server.logger.warning(f"{prefix} Prompt file not found: {prompt_full_path}, using default prompt")
                raw_prompt = server.rtr("games_ai.system_message.default")
        ai_info = {
            "prompt": raw_prompt,
            "ai_name": ai_config.get("ai_name", "[GamesAI]"),
            "base_url": ai_config.get("base_url", ""),
            "ai_model": ai_config.get("ai_model", ""),
            "api_key": ai_config.get("api_key", ""),
            "thinking": ai_config.get("thinking", False),
        }
        ai_dict[ai_id] = ai_info

    default_ai = config.get("default_ai", list(ai_dict.keys())[0])

    name_to_id = {}

    for id, info in ai_dict.items():
        name = info.get("ai_name")
        name_to_id[name] = id

    mcdr_lang = str(server.rtr("games_ai.system_message.lang", lang=server.get_mcdr_language()))

    
    server.register_help_message(prefix="!!data",message=server.rtr("games_ai.mcdr_help_message.data"),permission=allow_permission)

    server.logger.info(f'{prefix}{server.rtr("games_ai.load_message.server_info")}')
    server.say(f'{prefix}{server.rtr("games_ai.load_message.client_info",v=PLUGIN_METADATA.get("version"))}')

    builder = SimpleCommandBuilder()
    helper = gamesai_help()

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

    plugin_config.data_path = data_path
    plugin_config.tools_path = tools_path

    load_external_tools(log=server.logger.info)

    data_manager = DataManager(data_path)

    builder.command('!!gamesai', helper.all_help)
    builder.command('!!gamesai help', helper.all_help)

    builder.command('!!gamesai clear',clear_history)
    builder.command('!!gamesai clearall',clear_history_all)
    
    builder.command('!!gamesai check', check_update)

    builder.command('!!gamesai debug', debug)

    builder.command('!!gamesai reload', reloader)

    builder.command('!!ask', helper.ask_help)
    builder.command('!!ask <content>', ask_ai)
    builder.command('!!ask -m <model> <content>', ask_ai)
    builder.command('!!ask --model <model> <content>', ask_ai)

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

    builder.arg('model', Text)
    builder.arg('content',GreedyText)

    builder.arg('key', Text)
    builder.arg('value', GreedyText)

    builder.register(server)

    threading.Thread(target=cyclic_check_updates, daemon=True, args=(server,)).start()

def on_server_startup(server: PluginServerInterface):
    server.say(f'{prefix}{server.rtr("games_ai.load_message.client_info", v=PLUGIN_METADATA.get('version'))}')

def on_unload(server: PluginServerInterface):
    if _timer is not None:
        _timer.cancel()
    server.logger.info(f"{prefix}{server.rtr("games_ai.unload_message.server_info")}")
    if unload_status_code == 0:
        server.say(f'{prefix}Bye!')
    elif unload_status_code == 1:
        server.say(f'{prefix}{server.rtr("games_ai.unload_message.after_update_restart_msg")}')
    else:
        server.say(f'{prefix}{server.rtr("games_ai.unload_message.reloader_msg")}')

class gamesai_help:
    @staticmethod
    def ask_help(source: CommandSource):
        server = source.get_server()
        ask_help_part = RTextList(
            prefix,
            server.rtr("games_ai.gamesai_help_message.greeting",v=PLUGIN_METADATA.get("version")),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.help_prefix"),
            RText("!!ask <content>", RColor.gray).c(RAction.suggest_command,'!!ask '),
            server.rtr("games_ai.gamesai_help_message.ask_help"),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.help_prefix"),
            RText("!!ask -m <model> <content>", RColor.gray).c(RAction.suggest_command,'!!ask -m '),
            server.rtr("games_ai.gamesai_help_message.ask_help"),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.all_ai_model"),
            list(ai_dict.keys()),
        )
        source.reply(ask_help_part)

    @staticmethod
    def data_help(source: CommandSource):
        server = source.get_server()
        data_help_part = RTextList(
            prefix,
            server.rtr("games_ai.gamesai_help_message.greeting",v=PLUGIN_METADATA.get("version")),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.help_prefix"),
            RText("!!data write <key> <value>", RColor.gray).c(RAction.suggest_command,'!!data write '),
            server.rtr("games_ai.gamesai_help_message.data_write_help"),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.help_prefix"),
            RText("!!data add <key> <value>", RColor.gray).c(RAction.suggest_command,'!!data add '),
            server.rtr("games_ai.gamesai_help_message.data_add_help"),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.help_prefix"),
            RText("!!data del <key>", RColor.gray).c(RAction.suggest_command,'!!data del '),
            server.rtr("games_ai.gamesai_help_message.data_del_help"),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.help_prefix"),
            RText("!!data read <key>", RColor.gray).c(RAction.suggest_command,'!!data read '),
            server.rtr("games_ai.gamesai_help_message.data_read_help"),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.help_prefix"),
            RText("!!data list", RColor.gray).c(RAction.suggest_command,"!!data list"),
            server.rtr("games_ai.gamesai_help_message.data_list_help"),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.help_prefix"),
            RText("!!data list keys", RColor.gray).c(RAction.suggest_command, '!!data list keys'),
            server.rtr("games_ai.gamesai_help_message.data_keys_help"),
        )
        if source.get_permission_level() < allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission = allow_permission))
        else:
            source.reply(data_help_part)

    @staticmethod
    def data_write_help(source: CommandSource):
        server = source.get_server()
        data_add_help_part = RTextList(
            prefix,
            server.rtr("games_ai.gamesai_help_message.greeting",v=PLUGIN_METADATA.get("version")),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.help_prefix"),
            RText("!!data write <key> <value>", RColor.gray).c(RAction.suggest_command,'!!data write '),
            server.rtr("games_ai.gamesai_help_message.data_write_help"),
        )
        if source.get_permission_level() < allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission = allow_permission))
        else:
            source.reply(data_add_help_part)

    @staticmethod
    def data_del_help(source: CommandSource):
        server = source.get_server()
        data_del_help_part = RTextList(
            prefix,
            server.rtr("games_ai.gamesai_help_message.greeting",v=PLUGIN_METADATA.get("version")),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.help_prefix"),
            RText("!!data del <key>", RColor.gray).c(RAction.suggest_command,'!!data del '),
            server.rtr("games_ai.gamesai_help_message.data_del_help"),
        )
        if source.get_permission_level() < allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission = allow_permission))
        else:
            source.reply(data_del_help_part)

    @staticmethod
    def data_read_help(source: CommandSource):
        server = source.get_server()
        data_read_help_part = RTextList(
            prefix,
            server.rtr("games_ai.gamesai_help_message.greeting",v=PLUGIN_METADATA.get("version")),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.help_prefix"),
            RText("!!data read <key>", RColor.gray).c(RAction.suggest_command,'!!data read '),
            server.rtr("games_ai.gamesai_help_message.data_read_help"),
        )
        if source.get_permission_level() < allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission = allow_permission))
        else:
            source.reply(data_read_help_part)

    @staticmethod
    def data_add_help(source: CommandSource):
        server = source.get_server()
        data_add_help_part = RTextList(
            prefix,
            server.rtr("games_ai.gamesai_help_message.greeting", v=PLUGIN_METADATA.get("version")),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.help_prefix"),
            RText("!!data add <key> <value>", RColor.gray).c(RAction.suggest_command,'!!data add '),
            server.rtr("games_ai.gamesai_help_message.data_add_help"),
        )
        if source.get_permission_level() < allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission = allow_permission))
        else:
            source.reply(data_add_help_part)

    @staticmethod
    def all_help(source: CommandSource):
        server = source.get_server()
        basic_help_part = RTextList(
            prefix,
            server.rtr("games_ai.gamesai_help_message.greeting",v=PLUGIN_METADATA.get("version")),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.help_prefix"),
            RText("!!ask <content>", RColor.gray).c(RAction.suggest_command,'!!ask '),
            server.rtr("games_ai.gamesai_help_message.ask_help"),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.help_prefix"),
            RText("!!gamesai clear", RColor.gray).c(RAction.suggest_command,'!!gamesai clear'),
            server.rtr("games_ai.gamesai_help_message.clear_help"),
            )
        per_help_part = RTextList(
            prefix,
            server.rtr("games_ai.gamesai_help_message.help_prefix"),
            RText("!!gamesai clearall", RColor.gray).c(RAction.suggest_command,'!!gamesai clearall'),
            server.rtr("games_ai.gamesai_help_message.clearall_help"),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.help_prefix"),
            RText("!!gamesai check", RColor.gray).c(RAction.suggest_command, '!!gamesai check'),
            server.rtr("games_ai.gamesai_help_message.check_update_help"),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.help_prefix"),
            RText("!!data", RColor.gray).c(RAction.suggest_command, '!!data'),
            server.rtr("games_ai.gamesai_help_message.data_help"),
        )
        if source.get_permission_level() < allow_permission:
            source.reply(basic_help_part)
        else:
            all_help_part = RTextList(basic_help_part, "\n", per_help_part)
            source.reply(all_help_part)

@new_thread("games_ai@ask_ai")
def ask_ai(source: CommandSource,context: dict):
    server = source.get_server()

    user_input = context.get("model", default_ai)
    user_input_id = name_to_id.get(user_input, user_input)
    ai_info = ai_dict.get(user_input_id)
    may_user_ai = []
    if ai_info is None:
        for ai_id,ai_config in ai_dict.items():
            name = ai_config.get("ai_name", "")
            if user_input.lower() in name.lower() or user_input.lower() in ai_id.lower():
                may_user_ai.append(ai_id)
        if len(may_user_ai) == 1:
            ai_info = ai_dict.get(may_user_ai[0])
        elif len(may_user_ai) > 1:
            source.reply(f"{prefix}{server.rtr("games_ai.user_message.model_more")}{may_user_ai}")
            return
        else:
            source.reply(f"{prefix}{server.rtr("games_ai.user_message.model_error")}{ai_dict.keys()}")
            return

    ai_prefix = ai_info.get("ai_name")
    ai_model = ai_info.get("ai_model")
    base_url = ai_info.get("base_url")
    api_key = ai_info.get("api_key")
    prompt = ai_info.get("prompt")
    config_thinking = ai_info.get("thinking", False)
    if config_thinking:
        thinking = "enabled"
    else:
        thinking = "disabled"

    os.environ["OPENAI_API_KEY"] = api_key

    time = datetime.datetime.now()
    now_time = str(server.rtr("games_ai.user_message.time", time=time.strftime('%Y-%m-%d %H:%M:%S')))
    username = get_username(source)
    history = history_conversation.get(username, {}).get(ai_prefix, [])
    content = context['content']
    if source.is_player:
        user_name = f'{username}'
    else:
        user_name = "Server Control Panel"
    user_message = {"role": "user","content": f'{server.rtr("games_ai.user_message.username")}{user_name}\n{server.rtr("games_ai.user_message.message")}{content}'}
    response_message = [
        {"role": "system","content": now_time + mcdr_lang + prompt},
    ]
    data = DataManager(data_path).ask_ai_read_data()
    source.reply(f'{ai_prefix}{server.rtr("games_ai.user_message.get_data")}')
    data_message = {"role": "assistant","content": f'{server.rtr("games_ai.user_message.data_list")}{data}'}
    response_message.append(data_message)
    response_message.extend(history)
    response_message.append(user_message)

    if debug_mode:
        source.reply(f"[DEBUG]{response_message}")

    while True:
        try:
            ai_reply = response_chat(model=ai_model,url=base_url,message=response_message,tools=TOOL_SCHEMAS,thinking=thinking)
            if ai_reply.tool_calls is not None:
                response_message.append(ai_reply)
                if ai_reply.content:
                    source.reply(f"{ai_prefix}{ai_reply.content}")

                if debug_mode:
                    source.reply(f"[DEBUG]{ai_reply.tool_calls}")

                for tool_call in ai_reply.tool_calls:
                    func_name = tool_call.function.name
                    handler = get_tool_handler(func_name)

                    if handler is None:
                        result = f"未知函数: {func_name}"
                        source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.unknown_function",func_name=func_name)}')
                    else:
                        try:
                            func_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                            result = handler.func(source, ai_prefix, **func_args)
                            source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.tool_success")}')
                        except Exception as e:
                            result = f"函数 {func_name} 执行出错: {e}"
                            source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.execution_error",func_name=func_name,ex=e)}')
                            raise e
                        
                    if debug_mode:
                        source.reply(f"[DEBUG] Tool call result: \n{result}")

                    response_message.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })
                continue
            else:
                message = f'{ai_prefix}{ai_reply.content}'
                history.append(user_message)
                history.append(ai_reply)
                max_len = max_history * 2
                if len(history) > max_len:
                    history = history[-max_len:]
                history_conversation.setdefault(username, {})[ai_prefix] = history
                source.reply(message)
                break
        except Exception as e:
            error_code_map = {
                400: server.rtr("games_ai.error_code_map.error400"),
                401: server.rtr("games_ai.error_code_map.error401"),
                402: server.rtr("games_ai.error_code_map.error402"),
                403: server.rtr("games_ai.error_code_map.error403"),
                404: server.rtr("games_ai.error_code_map.error404"),
                408: server.rtr("games_ai.error_code_map.error408"),
                422: server.rtr("games_ai.error_code_map.error422"),
                429: server.rtr("games_ai.error_code_map.error429"),
                500: server.rtr("games_ai.error_code_map.error500"),
                502: server.rtr("games_ai.error_code_map.error502"),
                503: server.rtr("games_ai.error_code_map.error503"),
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
            raise e

def get_username(source: CommandSource):
    if source.is_player:
        return source.player
    else:
        return "Server Control Panel"

def clear_history(source: CommandSource,context: dict):
    server = source.get_server()
    username = get_username(source)
    if username in history_conversation:
        del history_conversation[username]
        source.reply(f'{prefix}{server.rtr("games_ai.clear_history_message.success",username=username)}')
    else:
        source.reply(f'{prefix}{server.rtr("games_ai.clear_history_message.no_history",username=username)}')

def clear_history_all(source: CommandSource,context: dict):
    server = source.get_server()
    if source.get_permission_level() < allow_permission:
        source.reply(f'{prefix}{server.rtr("games_ai.no_permission",permission=allow_permission)}')
    else:
        count = len(history_conversation)
        history_conversation.clear()
        source.reply(f'{prefix}{server.rtr("games_ai.clear_history_message.clearall_success",count=count)}')

class DataManager:
    def __init__(self,db_path: str):
        if db_path.endswith(".db"):
            self.db = PublicDatabase(db_path)
        else:
            self.db = PublicDatabase(db_path + "/public_database.db")

    @new_thread("data_manager@write")
    def write_data(self, source: CommandSource, context: dict):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            return source.reply(f'{prefix}{server.rtr("games_ai.no_permission",permission = allow_permission)}')
        else:
            key = context.get("key")
            value = context.get("value")
            self.db.write_data(key, value)
            return source.reply(f'{prefix}{server.rtr("games_ai.data.write_message.success",key=key,value=value)}')
        
    @new_thread("data_manager@add")
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

    @new_thread("data_manager@del")
    def del_data(self, source: CommandSource, context: dict):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            return source.reply(f'{prefix}{server.rtr("games_ai.no_permission",permission = allow_permission)}')
        else:
            key = context.get("key")
            self.db.delete_data(key)
            return source.reply(f'{prefix}{server.rtr("games_ai.data.del_message.success",key=key)}')

    @new_thread("data_manager@read")
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

    @new_thread("data_manager@list")
    def read_data_list(self, source: CommandSource, context: dict):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            return source.reply(f'{prefix}{server.rtr("games_ai.no_permission",permission = allow_permission)}')
        else:
            value = self.db.data_list()
            return source.reply(f'{prefix}{server.rtr("games_ai.data.read_list_message")}\n{value}')

    @new_thread("data_manager@keys")
    def read_all_keys(self, source: CommandSource):
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
    @register_tool(description="读取公共数据中的键值对, 输入key以获取对应的value, 推荐在读取之前先查看现有的key都有哪些", tr_key="reading_data", parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "要读取的数据的键"
            }
        },
        "required": ["key"]
    })
    def ai_read_data(source: CommandSource, ai_prefix: str, key: str):
        server = source.get_server()
        source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.reading_data",key=key)}')
        result = PublicDatabase(data_path).read_data(key)
        if result is None:
            return f"键 {key} 不存在"
        else:
            return f"键 {key} 的值为 {result}"

    @staticmethod
    @register_tool(description="读取公共数据中的所有键", tr_key="reading_all_keys")
    def ai_read_all_keys(source: CommandSource, ai_prefix: str):
        server = source.get_server()
        source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.reading_all_keys")}')
        keys = PublicDatabase(data_path).get_all_key()
        return f"当前所有的键有: {keys}"

    @staticmethod
    @register_tool(description="向公共数据中写入键值对(新增/覆写模式), 输入key和value以写入数据, 注意写入方式为覆写, 需避免覆盖重要数据, 数据不存在时将自动创建", tr_key="writing_data", parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "要写入的数据的键"
            },
            "value": {
                "type": "string",
                "description": "要写入的数据的值"
            }
        },
        "required": ["key", "value"]
    })
    def ai_write_data(source: CommandSource, ai_prefix: str, key: str, value: str):
        server = source.get_server()
        source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.writing_data",key=key,value=value)}')
        if source.get_permission_level() < allow_permission:
            return f'向你发起这项命令的玩家没有权限使用此功能'
        PublicDatabase(data_path).write_data(key, value)
        return f"已将键 {key} 的值写入 {value}"

    @staticmethod
    @register_tool(description="向公共数据中追加数据(新增/追加模式), 输入key和value以追加数据, 数据将被追加到原数据的末尾, 不存在时自动创建", tr_key="adding_data", parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "要追加数据的键"
            },
            "value": {
                "type": "string",
                "description": "要追加的数据的值"
            }
        },
        "required": ["key", "value"]
    })
    def ai_add_data(source: CommandSource, ai_prefix: str, key: str, value: str):
        server = source.get_server()
        source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.adding_data",key=key,value=value)}')
        if source.get_permission_level() < allow_permission:
            return f'向你发起这项命令的玩家没有权限使用此功能'
        old_value = PublicDatabase(data_path).read_data(key)
        if old_value == None:
            new_value = value
        else:
            new_value = old_value + value
        PublicDatabase(data_path).write_data(key, new_value)
        return f"已将键 {key} 的值增加 {value}, 当前值为 {new_value}"

    @staticmethod
    @register_tool(description="从公共数据中删除数据, 输入key以删除对应的数据, 注意删除后无法恢复, 即使key不存在, 也仍然会进行删除", tr_key="deleting_data", parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "要删除的数据的键"
            }
        },
        "required": ["key"]
    })
    def ai_del_data(source: CommandSource, ai_prefix: str, key: str):
        server = source.get_server()
        source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.deleting_data",key=key)}')
        if source.get_permission_level() < allow_permission:
            return f'向你发起这项命令的玩家没有权限使用此功能'
        PublicDatabase(data_path).delete_data(key)
        return f"已删除键 {key} 的数据"

@new_thread("games_ai@update")
def check_update(source: CommandSource, context: dict):
    server = source.get_server()
    try:
        update(server)
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
        _timer.daemon = True
        _timer.start()

def update(server: PluginServerInterface):
    global unload_status_code
    unload_status_code = 0
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
        server.say(f"{prefix}{server.rtr("games_ai.debug.disable")}")
        server.logger.info(f"{prefix}{server.rtr("games_ai.debug.disable")}")
        return
    else:
        debug_mode = True
        server.say(f"{prefix}{server.rtr("games_ai.debug.enable")}")
        server.logger.info(f"{prefix}{server.rtr("games_ai.debug.enable")}")
        return

@new_thread("games_ai@reloader")
def reloader(source: CommandSource, context: dict):
    global unload_status_code
    unload_status_code = 2
    server = source.get_server()
    server.execute_command("!!MCDR plugin unload games_ai")
    while True:
        if server.get_plugin_metadata("games_ai") is None:
            break
    server.execute_command(f"!!MCDR plugin load GamesAI-v{PLUGIN_METADATA.get('version')}.mcdr")
    return
