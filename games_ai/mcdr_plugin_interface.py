from whitelist_api import WhitelistException
from online_player_api import get_player_list

def get_whitelist_name_api(server):
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

def get_online_players_to_init(server):
    online_players_list = get_player_list()
    return online_players_list
