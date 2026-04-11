from mcdreforged.api.all import *
from .openai_api import response_chat
from .mcdr_plugin_interface import get_whitelist_name_api,get_online_players_to_init
import os
from .database import PublicDatabase

PLUGIN_METADATA = {
    "id": "games_ai",
    "version": "0.3.0",
    "name": "Games AI",
    "description": {
        "zh_cn": "此插件可以将MCDR与支持OpenAI的AI进行结合，使得在游戏内也能使用AI",
        "en_us": "This plugin can combine MCDR with AI that supports OpenAI, allowing you to use AI in the game"},
    "author": "yello",
    "link": "https://github.com/PengZixuan30/Games_AI",
    "dependencies": {
        "mcdreforged": ">=2.14.0",
        "online_player_api": ">=1.0.0",
        "whitelist_api": ">=1.0.0"
    }
}

history_conversation = {}

def on_load(server: PluginServerInterface, old):
    global ai_model,base_url,system_message,max_history,prefix,data_path,allow_permission
    
    server.register_help_message(prefix="!!gamesai",message=server.rtr("games_ai.mcdr_help_message.gamesai_help"))
    server.register_help_message(prefix="!!gamesai clear",message=server.rtr("games_ai.mcdr_help_message.gamesai_clear"))
    server.register_help_message(prefix="!!gamesai clearall",message=server.rtr("games_ai.mcdr_help_message.gamesai_clearall"),permission=3)
    server.register_help_message(prefix="!!ask <content>",message=server.rtr("games_ai.mcdr_help_message.gamesai_ask"))
    server.register_help_message(prefix="!!data add <key> <value>",message=server.rtr("games_ai.mcdr_help_message.data_add"),permission=3)
    server.register_help_message(prefix="!!data del <key>",message=server.rtr("games_ai.mcdr_help_message.data_del"),permission=3)
    server.register_help_message(prefix="!!data read <key>",message=server.rtr("games_ai.mcdr_help_message.data_read"),permission=3)

    config = server.load_config_simple(
        file_name='config.json',
        default_config={
            'system_message': server.rtr("games_ai.system_message.default"),
            'prefix': '[GamesAI]',
            'permission': 3,
            'base_url':'<Your API Base URL>',
            'ai_model':'<Your AI Model>',
            'api_key':'<Your API Key>',
            'max_history': 10
        },
        in_data_folder=True
    )

    prefix = config.get('prefix','[GamesAI]')
    system_message = config.get('system_message', server.rtr("games_ai.system_message.default"))
    base_url = config['base_url']
    ai_model = config['ai_model']
    api_key = config['api_key']
    max_history = config.get('max_history',10)
    allow_permission = config.get('permission',3)
    if base_url == "<Your API Base URL>" or ai_model == "<Your AI Model>" or api_key == "<Your API Key>":
        server.logger.error(f"{prefix}ERROR!Please modify the base_url, ai_model, and api_key items in the configuration file before using the plugin!")
    os.environ["OPENAI_API_KEY"] = api_key

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

    builder.command('!!ask', helper.ask_help)
    builder.command('!!ask <content>',ask_ai)

    builder.command('!!data', helper.data_help)

    builder.command('!!data add', helper.data_add_help)
    builder.command('!!data add <key>', helper.data_add_help)
    builder.command('!!data add <key> <value>', data_manager.add_data)

    builder.command('!!data del', helper.data_del_help)
    builder.command('!!data del <key>', data_manager.del_data)

    builder.command('!!data read', helper.data_read_help)
    builder.command('!!data read <key>', data_manager.read_data)

    builder.arg('content',GreedyText)
    builder.arg('key', Text)
    builder.arg('value', GreedyText)

    builder.register(server)

def on_server_startup(server: PluginServerInterface):
    server.say(f'{prefix}{server.rtr("games_ai.load_message.client_info", v=PLUGIN_METADATA.get('version'))}')

class gamesai_help:
    @staticmethod
    def ask_help(source: CommandSource):
        server = source.get_server()
        ask_help_part = RTextList(
            prefix,
            server.rtr("games_ai.gamesai_help_message.greeting",v=PLUGIN_METADATA.get("version")),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.ask_help_prefix"),
            RText("!!ask <content>", RColor.gray).c(RAction.suggest_command,'!!ask '),
            server.rtr("games_ai.gamesai_help_message.ask_help_suffix"),
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
            server.rtr("games_ai.gamesai_help_message.data_add_help_prefix"),
            RText("!!data add <key> <value>", RColor.gray).c(RAction.suggest_command,'!!data add '),
            server.rtr("games_ai.gamesai_help_message.data_add_help_suffix"),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.data_del_help_prefix"),
            RText("!!data del <key>", RColor.gray).c(RAction.suggest_command,'!!data del '),
            server.rtr("games_ai.gamesai_help_message.data_del_help_suffix"),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.data_read_help_prefix"),
            RText("!!data read <key>", RColor.gray).c(RAction.suggest_command,'!!data read '),
            server.rtr("games_ai.gamesai_help_message.data_read_help_suffix"),
        )
        source.reply(data_help_part)

    @staticmethod
    def data_add_help(source: CommandSource):
        server = source.get_server()
        data_add_help_part = RTextList(
            prefix,
            server.rtr("games_ai.gamesai_help_message.greeting",v=PLUGIN_METADATA.get("version")),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.data_add_help_prefix"),
            RText("!!data add <key> <value>", RColor.gray).c(RAction.suggest_command,'!!data add '),
            server.rtr("games_ai.gamesai_help_message.data_add_help_suffix"),
        )
        source.reply(data_add_help_part)

    @staticmethod
    def data_del_help(source: CommandSource):
        server = source.get_server()
        data_del_help_part = RTextList(
            prefix,
            server.rtr("games_ai.gamesai_help_message.greeting",v=PLUGIN_METADATA.get("version")),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.data_del_help_prefix"),
            RText("!!data del <key>", RColor.gray).c(RAction.suggest_command,'!!data del '),
            server.rtr("games_ai.gamesai_help_message.data_del_help_suffix"),
        )
        source.reply(data_del_help_part)

    @staticmethod
    def data_read_help(source: CommandSource):
        server = source.get_server()
        data_read_help_part = RTextList(
            prefix,
            server.rtr("games_ai.gamesai_help_message.greeting",v=PLUGIN_METADATA.get("version")),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.data_read_help_prefix"),
            RText("!!data read <key>", RColor.gray).c(RAction.suggest_command,'!!data read '),
            server.rtr("games_ai.gamesai_help_message.data_read_help_suffix"),
        )
        source.reply(data_read_help_part)

    @staticmethod
    def all_help(source: CommandSource):
        server = source.get_server()
        all_help_part = RTextList(
            prefix,
            server.rtr("games_ai.gamesai_help_message.greeting",v=PLUGIN_METADATA.get("version")),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.ask_help_prefix"),
            RText("!!ask <content>", RColor.gray).c(RAction.suggest_command,'!!ask '),
            server.rtr("games_ai.gamesai_help_message.ask_help_suffix"),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.clear_help_prefix"),
            RText("!!gamesai clear", RColor.gray).c(RAction.suggest_command,'!!gamesai clear'),
            server.rtr("games_ai.gamesai_help_message.clear_help_suffix"),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.clearall_help_prefix"),
            RText("!!gamesai clearall", RColor.gray).c(RAction.suggest_command,'!!gamesai clearall'),
            server.rtr("games_ai.gamesai_help_message.clearall_help_suffix"),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.data_add_help_prefix"),
            RText("!!data add <key> <value>", RColor.gray).c(RAction.suggest_command,'!!data add '),
            server.rtr("games_ai.gamesai_help_message.data_add_help_suffix"),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.data_del_help_prefix"),
            RText("!!data del <key>", RColor.gray).c(RAction.suggest_command,'!!data del '),
            server.rtr("games_ai.gamesai_help_message.data_del_help_suffix"),
            "\n",
            prefix,
            server.rtr("games_ai.gamesai_help_message.data_read_help_prefix"),
            RText("!!data read <key>", RColor.gray).c(RAction.suggest_command,'!!data read '),
            server.rtr("games_ai.gamesai_help_message.data_read_help_suffix"),
        )
        source.reply(all_help_part)

@new_thread("request_ai")
def ask_ai(source: CommandSource,context: dict):
    server = source.get_server()
    username = get_username(source)
    history = history_conversation.get(username,[])
    content = context['content']
    if source.is_player:
        user_name = f'{username}({server.rtr("games_ai.user_message.player")})'
    else:
        user_name = "Server Control Panel"
    user_message = {"role": "user","content": f'{server.rtr("games_ai.user_message.username")}{user_name}\n{server.rtr("games_ai.user_message.message")}{content}'}
    response_message = [
        {"role": "system","content": system_message},
    ]
    data = DataManager(data_path).ask_ai_read_data()
    source.reply(f'{prefix}{server.rtr("games_ai.user_message.get_data")}')
    data_message = {"role": "assistant","content": f'{server.rtr("games_ai.user_message.data_list")}{data}'}
    response_message.extend(history)
    response_message.append(data_message)
    response_message.append(user_message)
    while True:
        try:
            ai_reply = response_chat(model=ai_model,url=base_url,message=response_message)
            if ai_reply.find("get_players") >= 0:
                source.reply(f'{prefix}{server.rtr("games_ai.user_message.getting_online_players")}')
                online_players_list = {"role": "assistant","content": f'{server.rtr("games_ai.user_message.online_players")}{get_online_players_to_init(source.get_server())}'}
                response_message.append(online_players_list)
                continue
            elif ai_reply.find("get_whitelist") >= 0:
                source.reply(f'{prefix}{server.rtr("games_ai.user_message.getting_whitelist")}')
                all_players_list = {"role": "assistant","content": f'{server.rtr("games_ai.user_message.whitelist_players")}{get_whitelist_name_api(source.get_server())}'}
                response_message.append(all_players_list)
                continue
            else:
                message = f'{prefix}{ai_reply}'
                history.append({"role": "assistant","content": f'{server.rtr("games_ai.user_message.history.prefix")}{server.rtr("games_ai.user_message.history.user_message")}{user_message["content"]}\n{server.rtr("games_ai.user_message.history.ai_reply")}{ai_reply}'})
                max_len = max_history
                if len(history) > max_len:
                    history = history[-max_len:]
                history_conversation[username] = history
                source.reply(message)
                break
        except Exception as e:
            source.reply(f'{prefix}ERROR!\n{e}')
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
        source.reply(f'{prefix}{server.rtr("games_ai.no_permission")}')
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

    @new_thread("data_manager@add")
    def add_data(self, source: CommandSource, context: dict):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            return source.reply(f'{prefix}{server.rtr("games_ai.no_permission")}')
        else:
            key = context.get("key")
            value = context.get("value")
            self.db.write_data(key, value)
            return source.reply(f'{prefix}{server.rtr("games_ai.data.add_message.success",key=key,value=value)}')

    @new_thread("data_manager@del")
    def del_data(self, source: CommandSource, context: dict):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            return source.reply(f'{prefix}{server.rtr("games_ai.no_permission")}')
        else:
            key = context.get("key")
            self.db.delete_data(key)
            return source.reply(f'{prefix}{server.rtr("games_ai.data.del_message.success",key=key)}')

    @new_thread("data_manager@read")
    def read_data(self, source: CommandSource, context: dict):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            return source.reply(f'{prefix}{server.rtr("games_ai.no_permission")}')
        else:
            key = context.get("key")
            value = self.db.read_data(key)
            if value is None:
                return source.reply(f'{prefix}{server.rtr("games_ai.data.read_message.no_key",key=key)}')
            return source.reply(f'{prefix}{server.rtr("games_ai.data.read_message.success",key=key,value=value)}')

    def ask_ai_read_data(self):
        value = self.db.data_list()
        return value
