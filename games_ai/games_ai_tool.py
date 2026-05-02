from dataclasses import dataclass
from typing import Callable
import requests

from .config import plugin_config

@dataclass
class ToolHandler:
    func: Callable
    schema: dict
    tr_key: str

_TOOL_REGISTRY: dict[str, ToolHandler] = {}
TOOL_SCHEMAS: list[dict] = []


def register_tool(*, description: str, tr_key: str, parameters: dict | None = None):
    def decorator(func: Callable):
        func_name = func.__name__

        schema: dict = {
            "type": "function",
            "function": {
                "name": func_name,
                "description": description,
            },
        }
        if parameters is not None:
            schema["function"]["parameters"] = parameters

        handler = ToolHandler(func=func, schema=schema, tr_key=tr_key)
        _TOOL_REGISTRY[func_name] = handler
        TOOL_SCHEMAS.append(schema)
        return func
    return decorator


def get_tool_handler(name: str) -> ToolHandler | None:
    return _TOOL_REGISTRY.get(name)

@register_tool(description="获取服务器当前的在线玩家列表", tr_key="getting_online_players")
def get_online_players(source, ai_prefix):
    server = source.get_server()
    source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.getting_online_players")}')
    __online_players_api = server.get_plugin_instance('online_player_api')
    if __online_players_api is None:
        return "无法获取在线玩家插件实例"
    online_players = __online_players_api.get_player_list()
    if online_players:
        return ", ".join(online_players)
    else:
        return "无在线玩家"


@register_tool(description="获取服务器的白名单列表", tr_key="getting_whitelist")
def get_whitelist_name(source, ai_prefix):
    server = source.get_server()
    source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.getting_whitelist")}')
    __whitelist_api = server.get_plugin_instance('whitelist_api')
    if __whitelist_api is None:
        return "无法获取白名单插件实例"
    whitelist = __whitelist_api.get_whitelist()
    names = [player.name for player in whitelist]
    names.sort()
    if names:
        return ", ".join(names)
    else:
        return "无白名单玩家"
    
@register_tool(description="在白名单中添加一名玩家", tr_key="adding_whitelist", parameters={
    "type": "object",
    "properties": {
        "player": {
            "type": "string",
            "description": "要添加到白名单的玩家名称。只能添加一个。"
        }
    },
    "required": ["player"]
})
def add_to_whitelist(source, ai_prefix, player):
    source.reply(f'{ai_prefix}{source.get_server().rtr("games_ai.tools.adding_whitelist")}')
    if source.get_permission_level() < 3:
        return "向你发起这项命令的玩家没有权限使用此功能"
    __whitelist_api = source.get_server().get_plugin_instance('whitelist_api')
    if __whitelist_api is None:
        return "无法获取白名单插件实例"
    __whitelist_api.add_player(player)
    return f"玩家 {player} 已添加到白名单"

@register_tool(description="删除一名白名单中的玩家", tr_key="removing_whitelist", parameters={
    "type": "object",
    "properties": {
        "player": {
            "type": "string",
            "description": "要从白名单中移除的玩家名称。只能移除一个。"
        }
    },
    "required": ["player"]
})
def remove_from_whitelist(source, ai_prefix, player):
    source.reply(f'{ai_prefix}{source.get_server().rtr("games_ai.tools.removing_whitelist")}')
    if source.get_permission_level() < 3:
        return "向你发起这项命令的玩家没有权限使用此功能"
    __whitelist_api = source.get_server().get_plugin_instance('whitelist_api')
    if __whitelist_api is None:
        return "无法获取白名单插件实例"
    __whitelist_api.remove_player(player)
    return f"玩家 {player} 已从白名单中移除"

@register_tool(description="搜索Minecraft Wiki以获取相关信息, 请不要使用此方法搜索与Minecraft无关的东西。如果返回了Search results页面, 你可以通过先浏览此页面, 再进行一次精确查询", tr_key="searching_minecraft_wiki", parameters={
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "要搜索的内容，例如某个物品、怪物、机制等的名称。"
        }
    },
    "required": ["query"]
})
def search_minecraft_wiki(source, ai_prefix, query):
    source.reply(f'{ai_prefix}{source.get_server().rtr("games_ai.tools.searching_minecraft_wiki", query=query)}')
    lang = source.get_server().get_mcdr_language()
    if lang == "en_us":
        search_url = f"https://minecraft.wiki/?search={query}"
    else:
        search_url = f"https://zh.minecraft.wiki/?search={query}"
    response = requests.get(search_url)
    if response.status_code == 200:
        return f"一下是搜索内容 {query} 的结果:\n{response.content.decode('utf-8')}"
    else:
        return "无法访问Minecraft Wiki进行搜索"
