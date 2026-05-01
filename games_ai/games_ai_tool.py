from dataclasses import dataclass
from typing import Callable

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

@register_tool(description="Get the list of online players on the server", tr_key="getting_online_players")
def get_online_players(source):
    server = source.get_server()
    __online_players_api = server.get_plugin_instance('online_player_api')
    if __online_players_api is None:
        return "无法获取在线玩家插件实例"
    online_players = __online_players_api.get_player_list()
    if online_players:
        return ", ".join(online_players)
    else:
        return "无在线玩家"


@register_tool(description="Get the list of whitelisted players on the server", tr_key="getting_whitelist")
def get_whitelist_name(source):
    server = source.get_server()
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
    
@register_tool(description="Add a player to the whitelist", tr_key="adding_whitelist", parameters={
    "type": "object",
    "properties": {
        "player": {
            "type": "string",
            "description": "The names of players to be added to the whitelist.There can only be one."
        }
    },
    "required": ["player"]
})
def add_to_whitelist(source, player):
    if source.get_permission_level() < 3:
        return "向你发起这项命令的玩家没有权限使用此功能"
    __whitelist_api = source.get_server().get_plugin_instance('whitelist_api')
    if __whitelist_api is None:
        return "无法获取白名单插件实例"
    __whitelist_api.add_player(player)
    return f"玩家 {player} 已添加到白名单"

@register_tool(description="Remove a player from the whitelist", tr_key="removing_whitelist", parameters={
    "type": "object",
    "properties": {
        "player": {
            "type": "string",
            "description": "The names of players to be removed from the whitelist.There can only be one."
        }
    },
    "required": ["player"]
})
def remove_from_whitelist(source, player):
    if source.get_permission_level() < 3:
        return "向你发起这项命令的玩家没有权限使用此功能"
    __whitelist_api = source.get_server().get_plugin_instance('whitelist_api')
    if __whitelist_api is None:
        return "无法获取白名单插件实例"
    __whitelist_api.remove_player(player)
    return f"玩家 {player} 已从白名单中移除"
