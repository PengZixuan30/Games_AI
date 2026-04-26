from mcdreforged.api.all import *

from .openai_api import response_chat
from .mcdr_plugin_interface import get_whitelist_name_api,get_online_players_to_init
from .database import PublicDatabase

import time,os,requests,lzma,json,threading

PLUGIN_METADATA = {
    "id": "games_ai",
    "version": "0.4.0",
    "name": "Games AI",
    "description": {
        "zh_cn": "此插件可以将MCDR与支持OpenAI的AI进行结合，使得在游戏内也能使用AI",
        "en_us": "This plugin can combine MCDR with AI that supports OpenAI, allowing you to use AI in the game"},
    "author": "yello",
    "link": "https://github.com/PengZixuan30/Games_AI",
    "dependencies": {
        "mcdreforged": ">=2.15.0",
        "online_player_api": ">=1.0.0",
        "whitelist_api": ">=1.0.0"
    }
}

history_conversation = {}
update_status_code = 0

def on_load(server: PluginServerInterface, old):
    global max_history,prefix,data_path,allow_permission,mcdr_lang,_timer,ai_dict,default_ai,name_to_id
    _timer = None
    
    DEFAULT_CONFIG = {
        "prefix": "[GamesAI]",
        "permission": 3,
        "max_history": 10,
        "all_ai": {
            "<Your AI ID>":{
                "prompt": server.rtr("games_ai.system_message.default"),
                "ai_name": "[ServerAI]",
                "base_url": "<Your API Base URL>",
                "ai_model": "<Your AI Model>",
                "api_key": "<Your API Key>"
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

    ai_dict = {}

    all_ai: dict = config.get('all_ai', {})
    for ai_id,ai_config in all_ai.items():
        if not isinstance(ai_config, dict):
            continue
        ai_info = {
            "prompt": ai_config.get("prompt", ""),
            "ai_name": ai_config.get("ai_name", ""),
            "base_url": ai_config.get("base_url", ""),
            "ai_model": ai_config.get("ai_model", ""),
            "api_key": ai_config.get("api_key", "")
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
    
    data_manager = DataManager(data_path)

    builder.command('!!gamesai', helper.all_help)
    builder.command('!!gamesai help', helper.all_help)

    builder.command('!!gamesai clear',clear_history)
    builder.command('!!gamesai clearall',clear_history_all)
    
    builder.command('!!gamesai check', check_update)

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
    _timer.cancel()
    if update_status_code == 0:
        server.logger.info(f'{prefix}{server.rtr("games_ai.unload_message.server_info")}')
        server.say(f'{prefix}Bye!')
    else:
        server.logger.info(f'{prefix}{server.rtr("games_ai.update.after_update_restart_msg")}')
        server.say(f'{prefix}{server.rtr("games_ai.update.after_update_restart_msg")}')

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
            "\n",)
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
            all_help_part = RTextList(basic_help_part, per_help_part)
            source.reply(all_help_part)

@new_thread("games_ai@request_ai")
def ask_ai(source: CommandSource,context: dict):
    server = source.get_server()

    user_input = context.get("model", default_ai)
    user_input_id = name_to_id.get(user_input, user_input)
    ai_info = ai_dict.get(user_input_id)
    may_user_ai = []
    if ai_info is None:
        for ai_id,ai_config in ai_dict.items():
            name = ai_config.get("ai_name")
            if user_input.lower() in name.lower():
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

    os.environ["OPENAI_API_KEY"] = api_key

    username = get_username(source)
    history = history_conversation.get(username,[])
    content = context['content']
    if source.is_player:
        user_name = f'{username}({server.rtr("games_ai.user_message.player")})'
    else:
        user_name = "Server Control Panel"
    user_message = {"role": "user","content": f'{server.rtr("games_ai.user_message.username")}{user_name}\n{server.rtr("games_ai.user_message.message")}{content}'}
    response_message = [
        {"role": "system","content": mcdr_lang + prompt},
    ]
    data = DataManager(data_path).ask_ai_read_data()
    source.reply(f'{ai_prefix}{server.rtr("games_ai.user_message.get_data")}')
    data_message = {"role": "assistant","content": f'{server.rtr("games_ai.user_message.data_list")}{data}'}
    response_message.extend(history)
    response_message.append(data_message)
    response_message.append(user_message)

    while True:
        try:
            ai_reply = response_chat(model=ai_model,url=base_url,message=response_message)
            if ai_reply.find("get_players") >= 0:
                source.reply(f'{ai_prefix}{server.rtr("games_ai.user_message.getting_online_players")}')
                online_players_list = {"role": "assistant","content": f'{server.rtr("games_ai.user_message.online_players")}{get_online_players_to_init(source.get_server())}'}
                response_message.append(online_players_list)
                continue
            elif ai_reply.find("get_whitelist") >= 0:
                source.reply(f'{ai_prefix}{server.rtr("games_ai.user_message.getting_whitelist")}')
                all_players_list = {"role": "assistant","content": f'{server.rtr("games_ai.user_message.whitelist_players")}{get_whitelist_name_api(source.get_server())}'}
                response_message.append(all_players_list)
                continue
            else:
                message = f'{ai_prefix}{ai_reply}'
                history.append({"role": "assistant","content": f'{server.rtr("games_ai.user_message.history.prefix")}{server.rtr("games_ai.user_message.history.user_message")}{user_message["content"]}\n{server.rtr("games_ai.user_message.history.ai_reply")}{ai_reply}'})
                max_len = max_history
                if len(history) > max_len:
                    history = history[-max_len:]
                history_conversation[username] = history
                source.reply(message)
                break
        except Exception as e:
            source.reply(f'{ai_prefix}ERROR!\n{e}')
            break

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
            message_part = RTextList(
                prefix,
                server.rtr("games_ai.data.read_message.success",key=key,value=value),
                "\n",
                RText(server.rtr("games_ai.data.read_message.write_button"), RColor.gray).h(server.rtr("games_ai.data.read_message.write_hover")).c(RAction.suggest_command, f"!!data write {key} {value}"),
                "  OR  ",
                RText(server.rtr("games_ai.data.read_message.copy_button"), RColor.blue).h(server.rtr("games_ai.data.read_message.copy_hover")).c(RAction.copy_to_clipboard, value)
            )
            if value is None:
                return source.reply(f'{prefix}{server.rtr("games_ai.data.read_message.no_key",key=key)}')
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

@new_thread("games_ai@update")
def check_update(source: CommandSource, context: dict):
    server = source.get_server()
    try:
        update(server)
    except Exception as e:
        server.say(f"{prefix}{server.rtr("games_ai.update.no_metadata")}")

def cyclic_check_updates(server: PluginServerInterface):
    global _timer
    try:
        update(server)
    except Exception as e:
        server.say(f"{prefix}{server.rtr("games_ai.update.no_metadata")}")
    finally:
        _timer = threading.Timer(86400, cyclic_check_updates, args=(server,))
        _timer.daemon = True
        _timer.start()

def update(server: PluginServerInterface):
    global update_status_code
    update_status_code = 0
    server.say(f"{prefix}{server.rtr("games_ai.update.checking_update")}")
    response = requests.get("https://api.mcdreforged.com/catalogue/everything_slim.json.xz")
    if response.status_code == 200:
        compress_data = response.content
        decompress_data = lzma.decompress(compress_data)
        json_data = json.loads(decompress_data.decode('utf-8'))
        try:
            new_version = json_data.get("plugins").get("games_ai").get("release").get("releases")[0].get("meta").get("version")
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            server.say(f"{prefix}{server.rtr("games_ai.update.no_metadata")}")
            return e
        if get_main_version(new_version) <= get_main_version(PLUGIN_METADATA["version"]):
            return server.say(f"{prefix}{server.rtr("games_ai.update.no_update")}")
        else:
            server.say(f"{prefix}{server.rtr("games_ai.update.new_update",version = new_version)}")
            time.sleep(5)
            server.execute_command("!!MCDR plugin install -U games_ai")
            time.sleep(59)
            server.execute_command("!!MCDR confirm")
            server.say(f"{prefix}{server.rtr("games_ai.update.update_ok")}")
            update_status_code = 1
            return
    else:
        server.say(f"{prefix}{server.rtr("games_ai.update.no_metadata")}")
        return
    
def get_main_version(ver: str):
    return tuple(int(x) for x in ver.split('-')[0].split('.'))
