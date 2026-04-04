from mcdreforged.api.all import *
from .openai_api import response_chat
from .mcdr_plugin_interface import get_whitelist_name_api,get_online_players_to_init
import os

PLUGIN_METADATA = {
    "id": "games_ai",
    "version": "0.2.1",
    "name": "Games AI",
    "description": {
        "zh_cn": "此插件可以将MCDR与支持OpenAI的AI进行结合，使得在游戏内也能使用AI",
        "en_us": "This plugin can combine MCDR with AI that supports OpenAI, allowing you to use AI in the game"},
    "author": "yello",
    "link": "https://github.com/PengZixuan30/Games_AI",
    "dependencies": {
        "online_player_api": ">=1.0.0",
        "whitelist_api": ">=1.0.0"
    }
}

history_conversation = {}

def on_load(server: PluginServerInterface, old):
    global ai_model,base_url,system_message,max_history,prefix
    
    server.register_help_message(prefix="!!gamesai",message=server.rtr("games_ai.mcdr_help_message.openai_help"))
    server.register_help_message(prefix="!!gamesai clear",message=server.rtr("games_ai.mcdr_help_message.openai_clear"))
    server.register_help_message(prefix="!!gamesai clearall",message=server.rtr("games_ai.mcdr_help_message.openai_clearall"),permission=3)
    server.register_help_message(prefix="!!gamesai ask",message=server.rtr("games_ai.mcdr_help_message.openai_ask"))

    config = server.load_config_simple(
        file_name='config.json',
        default_config={
            'system_message': server.rtr("games_ai.system_message.default"),
            'prefix': '[GamesAI]',
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
    os.environ["OPENAI_API_KEY"] = api_key

    server.logger.info(f'{prefix}{server.rtr("games_ai.load_message.server_info")}')
    server.say(f'{prefix}{server.rtr("games_ai.load_message.client_info")}')

    builder = SimpleCommandBuilder()

    builder.command('!!gamesai',gamesai_help)
    builder.command('!!gamesai help',gamesai_help)
    builder.command('!!gamesai clear',clear_history)
    builder.command('!!gamesai clearall',clear_history_all)
    builder.command('!!ask', gamesai_help)
    builder.command('!!ask <content>',ask_ai)

    builder.arg('content',GreedyText)

    builder.register(server)

def gamesai_help(source: CommandSource,context: dict):
    server = source.get_server()
    source.reply(f'{prefix}{server.rtr("games_ai.openai_help_message.greeting")}')
    if source.is_player:
        ask_part = RTextList(
            server.rtr("games_ai.openai_help_message.ask_help_prefix"),
            RText('!!ask', RColor.gray).c(RAction.suggest_command,'!!ask'),
            server.rtr("games_ai.openai_help_message.ask_help_suffix")
        )
        source.reply(RTextList(prefix, ask_part))
        clear_part = RTextList(
            server.rtr("games_ai.openai_help_message.clear_help_prefix"),
            RText('!!gamesai clear', RColor.gray).c(RAction.suggest_command,'!!gamesai clear'),
            server.rtr("games_ai.openai_help_message.clear_help_suffix")
        )
        source.reply(RTextList(prefix, clear_part))
        clearall_part = RTextList(
            server.rtr("games_ai.openai_help_message.clearall_help_prefix"),
            RText('!!gamesai clearall', RColor.gray).c(RAction.suggest_command,'!!gamesai clearall'),
            server.rtr("games_ai.openai_help_message.clearall_help_suffix")
        )
        source.reply(RTextList(prefix, clearall_part))
    else:
        source.reply(f'{prefix}{server.rtr("games_ai.openai_help_message.ask_help_console")}')
        source.reply(f'{prefix}{server.rtr("games_ai.openai_help_message.clear_help_console")}')
        source.reply(f'{prefix}{server.rtr("games_ai.openai_help_message.clearall_help_console")}')

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
    response_message.extend(history)
    response_message.append(user_message)
    def response_try():
        nonlocal history
        try:
            ai_reply = response_chat(model=ai_model,url=base_url,message=response_message)
            if ai_reply.find("get_players") >= 0:
                source.reply(f'{prefix}{server.rtr("games_ai.user_message.getting_online_players")}')
                online_players_list = {"role": "user","content": f'{server.rtr("games_ai.user_message.online_players")}{get_online_players_to_init(source.get_server())}'}
                response_message.append(online_players_list)
                return response_try()
            elif ai_reply.find("get_whitelist") >= 0:
                source.reply(f'{prefix}{server.rtr("games_ai.user_message.getting_whitelist")}')
                all_players_list = {"role": "user","content": f'{server.rtr("games_ai.user_message.whitelist_players")}{get_whitelist_name_api(source.get_server())}'}
                response_message.append(all_players_list)
                return response_try()
            else:
                message = f'{prefix}{ai_reply}'
                history.append({"role": "assistant","content": f'{server.rtr("games_ai.user_message.history.prefix")}{server.rtr("games_ai.user_message.history.user_message")}{user_message["content"]}\n{server.rtr("games_ai.user_message.history.ai_reply")}{ai_reply}'})
                max_len = max_history
                if len(history) > max_len:
                    history = history[-max_len:]
                history_conversation[username] = history
                source.reply(message)
        except Exception as e:
            source.reply(f'{prefix}ERROR!\n{e}')
    response_try()

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
    if source.get_permission_level() < 3:
        source.reply(f'{prefix}{server.rtr("games_ai.clear_history_message.clearall_no_permission")}')
    else:
        count = len(history_conversation)
        history_conversation.clear()
        source.reply(f'{prefix}{server.rtr("games_ai.clear_history_message.clearall_success",count=count)}')
