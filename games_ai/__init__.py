from mcdreforged.api.all import *
from .openai_api import response_chat
from .mcdr_plugin_interface import get_whitelist_name_api,get_online_players_to_init
import os

version = "0.2.0"

history_conversation = {}

def on_load(server: PluginServerInterface,info: Info):
    global ai_model,base_url,system_message,max_history,prefix
    
    server.register_help_message(prefix="!!openai",message="显示OpenAI插件的帮助信息以及使用OpenAI")
    server.register_help_message(prefix="!!openai clear",message="清除当前玩家的所有对话历史")
    server.register_help_message(prefix="!!openai clearall",message="清除所有历史消息",permission=3)
    server.register_help_message(prefix="!!ask",message="向AI询问问题")

    config = server.load_config_simple(
        file_name='config.json',
        default_config={
            'system_message': '使用简洁的语言回答,但请带有一定的情感,始终使用语言为zh_cn,如果你想获取在线玩家列表,请回复get_players;如果你想获取服务器白名单(既全体成员名单),请回复get_whitelist。你是Minecraft服务器的一名机器人',
            'prefix': '[OpenAI]',
            'base_url':'https://api.deepseek.com',
            'ai_model':'deepseek-chat',
            'api_key':'<Your API Key>',
            'max_history': 10
        },
        in_data_folder=True
    )
    server.logger.info("配置文件已加载")

    prefix = config.get('prefix','[OpenAI]')
    system_message = config.get('system_message',"使用简洁的语言回答,但请带有一定的情感,始终使用语言为zh_cn,如果你想获取在线玩家列表,请回复get_players;如果你想获取服务器白名单(既全体成员名单),请回复get_whitelist。你是Minecraft服务器的一名机器人")
    base_url = config['base_url']
    ai_model = config['ai_model']
    api_key = config['api_key']
    max_history = config.get('max_history',10)
    os.environ["OPENAI_API_KEY"] = api_key

    builder = SimpleCommandBuilder()

    builder.command('!!openai',openai_help)
    builder.command('!!openai help',openai_help)
    builder.command('!!openai clear',clear_history)
    builder.command('!!openai clearall',clear_history_all)
    builder.command('!!ask <content>',ask_ai)

    builder.arg('content',GreedyText)

    builder.register(server)

def openai_help(source: CommandSource,context: dict):
    source.reply(f'{prefix}欢迎使用MCDR插件OpenAI API')
    if source.is_player:
        text_ask = RText('!!ask', RColor.gray).c(RAction.suggest_command,'!!ask')
        source.reply(f'{prefix}输入' + text_ask + '以向AI提问')
        text_clear = RText('!!openai clear', RColor.gray).c(RAction.suggest_command,'!!openai clear')
        source.reply(f'{prefix}输入' + text_clear + '以清除你的历史聊天记录')
        text_clearall = RText('!!openai clearall', RColor.gray).c(RAction.suggest_command,'!!openai clearall')
        source.reply(f'{prefix}输入' + text_clearall + '以清除所有历史聊天记录(需要3级及以上权限)')
    else:
        source.reply(f'{prefix}输入!!ask以向AI提问')
        source.reply(f'{prefix}输入!!openai clear以清除你的历史聊天记录')
        source.reply(f'{prefix}输入!!openai clearall以清除所有历史聊天记录')

@new_thread("request_ai")
def ask_ai(source: CommandSource,context: dict):
    username = get_username(source)
    history = history_conversation.get(username,[])
    content = context['content']
    if source.is_player:
        user_name = f'{username}(玩家)'
    else:
        user_name = "Server Control Panel"
    user_message = {"role": "user","content": f'用户名:{user_name}\n玩家消息:{content}'}
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
                source.reply(f'{prefix}正在获取在线玩家列表')
                online_players_list = {"role": "user","content": f'在线玩家列表:{get_online_players_to_init(source.get_server())}'}
                response_message.append(online_players_list)
                return response_try()
            elif ai_reply.find("get_whitelist") >= 0:
                source.reply(f'{prefix}正在获取全体玩家列表')
                all_players_list = {"role": "user","content": f'全体玩家列表:{get_whitelist_name_api(source.get_server())}'}
                response_message.append(all_players_list)
                return response_try()
            else:
                message = f'{prefix}{ai_reply}'
                history.append({"role": "assistant","content": f'历史记录:玩家消息:{user_message["content"]};AI回复:{ai_reply}'})
                max_len = max_history
                if len(history) > max_len:
                    history = history[-max_len:]
                history_conversation[username] = history
                source.reply(message)
        except Exception as e:
            source.reply(f'{prefix}ERROR!Info:{e}')
    response_try()

def get_username(source: CommandSource):
    if source.is_player:
        return source.player
    else:
        return "Server Control Panel"

def clear_history(source: CommandSource,context: dict):
    username = get_username(source)
    if username in history_conversation:
        del history_conversation[username]
        source.reply(f'{prefix}已清除玩家{username}的历史消息')
    else:
        source.reply(f'{prefix}当前玩家{username}没有可清除的消息')

def clear_history_all(source: CommandSource,context: dict):
    if source.get_permission_level() < 3:
        source.reply(f'{prefix}你没有权限使用此指令,需要权限等级达到admin')
    else:
        count = len(history_conversation)
        history_conversation.clear()
        source.reply(f'{prefix}已清除所有历史消息,总计{count}个玩家的消息')
