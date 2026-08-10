from mcdreforged.command.command_source import CommandSource

from dataclasses import dataclass
from typing import Callable
import requests, os, json, time

from .config import plugin_config
from .external_skills_loader import EXTERNAL_SKILLS_LIST, read_external_skills

@dataclass
class ToolHandler:
    func: Callable
    schema: dict
    tr_key: str

_TOOL_REGISTRY: dict[str, ToolHandler] = {}
TOOL_SCHEMAS: list[dict] = []


def register_tool(*, description: str, tr_key: str | None = "", parameters: dict | None = None):
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


_BOT_SAFE_TOOL_NAMES: set[str] = set()


def register_bot_tool():
    def decorator(func: Callable):
        _BOT_SAFE_TOOL_NAMES.add(func.__name__)
        return func
    return decorator


def get_bot_tool_schemas() -> list[dict]:
    return [
        s for s in TOOL_SCHEMAS
        if s.get("function", {}).get("name") in _BOT_SAFE_TOOL_NAMES
    ]

@register_tool(description="获取服务器当前的在线玩家列表", tr_key="getting_online_players")
@register_bot_tool()
def get_online_players(source: CommandSource, ai_prefix: str):
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
def get_whitelist_name(source: CommandSource, ai_prefix: str):
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
    
@register_tool(description="在白名单中添加一名玩家,推荐在添加之前先查询白名单", tr_key="adding_whitelist", parameters={
    "type": "object",
    "properties": {
        "player": {
            "type": "string",
            "description": "要添加到白名单的玩家名称。只能添加一个。"
        }
    },
    "required": ["player"]
})
def add_to_whitelist(source: CommandSource, ai_prefix: str, player: str):
    source.reply(f'{ai_prefix}{source.get_server().rtr("games_ai.tools.adding_whitelist")}')
    if source.get_permission_level() < 3:
        return "向你发起这项命令的玩家没有权限使用此功能"
    __whitelist_api = source.get_server().get_plugin_instance('whitelist_api')
    if __whitelist_api is None:
        return "无法获取白名单插件实例"
    __whitelist_api.add_player(player)
    return f"玩家 {player} 已添加到白名单"

@register_tool(description="删除一名白名单中的玩家,推荐在删除之前先查询白名单", tr_key="removing_whitelist", parameters={
    "type": "object",
    "properties": {
        "player": {
            "type": "string",
            "description": "要从白名单中移除的玩家名称。只能移除一个。"
        }
    },
    "required": ["player"]
})
def remove_from_whitelist(source: CommandSource, ai_prefix: str, player: str):
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
@register_bot_tool()
def search_minecraft_wiki(source: CommandSource, ai_prefix: str, query: str):
    source.reply(f'{ai_prefix}{source.get_server().rtr("games_ai.tools.searching_minecraft_wiki", query=query)}')
    lang = source.get_server().get_mcdr_language()
    if lang == "en_us":
        search_url = f"https://minecraft.wiki/?search={query}"
    else:
        search_url = f"https://zh.minecraft.wiki/?search={query}"
    response = requests.get(search_url)
    if response.status_code == 200:
        return f"以下是搜索内容 {query} 的结果:\n{response.content.decode('utf-8')}"
    else:
        return "无法访问Minecraft Wiki进行搜索"

@register_tool(description="计算一个数学表达式, 只能使用数字和+-*/()运算符", tr_key="calculating_expression", parameters={
    "type": "object",
    "properties": {
        "expression": {
            "type": "string",
            "description": "要计算的数学表达式，例如 (2+3)*4。只能包含数字和+-*/()运算符"
        }
    },
    "required": ["expression"]
})
@register_bot_tool()
def calculator(source: CommandSource, ai_prefix: str, expression: str):
    source.reply(f'{ai_prefix}{source.get_server().rtr("games_ai.tools.calculating_expression", expression=expression)}')
    try:
        if not all(c.isdigit() or c in "+-*/(). " for c in expression):
            return "表达式包含非法字符"
        result = eval(expression)
        return f"计算结果: {result}"
    except Exception as e:
        return f"计算错误: {str(e)}"
    
@register_tool(description="计算一个数学表达式, 只能使用数字和+-*/()运算符, 结果会被转换成 盒、组、个 的格式返回", tr_key="calculating_expression", parameters={
    "type": "object",
    "properties": {
        "expression": {
            "type": "string",
            "description": "要计算的数学表达式，例如 (2+3)*4。只能包含数字和+-*/()运算符"
        },
        "single_limit": {
            "type": "integer",
            "description": "每组的数量上限,默认为64"
        }
    },
    "required": ["expression"]
})
@register_bot_tool()
def item_caculator(source: CommandSource, ai_prefix: str, expression: str, single_limit: int = 64):
    source.reply(f'{ai_prefix}{source.get_server().rtr("games_ai.tools.calculating_expression", expression=expression)}')
    try:
        if not all(c.isdigit() or c in "+-*/(). " for c in expression):
            return "表达式包含非法字符"
        result = eval(expression)
        single = result % single_limit
        box = result // (single_limit*27)
        stack = (result - box*single_limit*27 - single) // single_limit
        return f"计算结果: {result}, 共有 {box} 箱, {stack} 组, {single} 个"
    except Exception as e:
        return f"计算错误: {str(e)}"


@register_tool(description="阅读技能, 调用多个工具前必备, 每次只能读取一个skills", tr_key="games_ai.tools.reading_skills", parameters={
    "type": "object",
    "properties": {
        "skills": {
            "type": "string",
            "description": "你要阅读的技能文件的文件名"
        }
    },
    "required": ["skills"]
})
def read_skills(source: CommandSource, ai_prefix: str, skills: str):
    server = source.get_server()
    source.reply(f"{ai_prefix}{server.rtr("games_ai.tools.reading_skills", skills=skills)}")
    errors = []
    if not skills.endswith(".md"):
        skills += ".md"

    external_content = read_external_skills(skills)
    if external_content is not None:
        return f"skills的内容: \n{external_content}"

    custom_path = os.path.join(os.path.dirname(plugin_config.skills_path), skills)

    if os.path.isfile(custom_path):
        try:
            with open(custom_path, mode='r', encoding='utf-8') as f:
                return f"skills的内容: \n{f.read()}"
        except Exception as e:
            errors.append(f"自定义路径读取失败: {e}")

    _plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.isfile(_plugin_root):
        import zipfile
        try:
            with zipfile.ZipFile(_plugin_root, 'r') as zf:
                zip_path = f"skills/{skills}"
                if zip_path in zf.namelist():
                    content = zf.read(zip_path).decode('utf-8')
                    return f"skills的内容: \n{content}"
                else:
                    errors.append(f"内置skills中未找到: {zip_path}")
        except (zipfile.BadZipFile, KeyError, OSError) as e:
            errors.append(f"内置skills读取失败: {e}")

    if plugin_config.builtin_skills_dir:
        builtin_path = os.path.join(plugin_config.builtin_skills_dir, skills)
        try:
            with open(builtin_path, mode='r', encoding='utf-8') as f:
                return f"skills的内容: \n{f.read()}"
        except Exception as e:
            errors.append(f"内置目录读取失败: {e}")

    error_detail = "; ".join(errors) if errors else "文件不存在于任何路径"
    return f"skills读取失败, 原因: {error_detail}"

@register_tool(description="写入技能, 调用多个工具前必备, 每次只能写入一个skills", tr_key="games_ai.tools.writing_skills", parameters={
    "type": "object",
    "properties": {
        "skills": {
            "type": "string",
            "description": "你要写入的技能文件的文件名"
        },
        "summary": {
            "type": "string",
            "description": "你要写入的技能的简介"
        },
        "content": {
            "type": "string",
            "description": "你要写入的技能内容"
        }
    },
    "required": ["skills", "summary", "content"]
})
def write_skills(source: CommandSource, ai_prefix: str, skills: str, summary: str, content: str):
    server = source.get_server()
    source.reply(f"{ai_prefix}{server.rtr("games_ai.tools.writing_skills", skills=skills)}")
    if source.get_permission_level() < plugin_config.allow_permission:
        return server.rtr("games_ai.tools.permission_denied")
    skills_path = os.path.join(os.path.dirname(plugin_config.skills_path), skills)
    try:
        with open(skills_path, mode='w', encoding='utf-8') as f:
            f.write(content)

        try:
            with open(plugin_config.skills_path, mode='r', encoding='utf-8') as f:
                index_data = json.load(f)
                if not isinstance(index_data, list):
                    index_data = []
        except (FileNotFoundError, json.JSONDecodeError):
            index_data = []

        found = False
        for item in index_data:
            if item.get("file") == skills:
                item["description"] = summary
                found = True
                break
        if not found:
            index_data.append({"file": skills, "description": summary})

        with open(plugin_config.skills_path, mode='w', encoding='utf-8') as f:
            json.dump(index_data, f, ensure_ascii=False, indent=4)

        return f"skills写入成功"
    except Exception as e:
        return f"skills写入失败, 原因: {e}"

@register_tool(description="修改技能, 调用多个工具前必备, 每次只能修改一个skills", tr_key="games_ai.tools.modifying_skills", parameters={
    "type": "object",
    "properties": {
        "skills": {
            "type": "string",
            "description": "你要修改的技能文件的文件名"
        },
        "summary": {
            "type": "string",
            "description": "你要修改的技能的简介"
        },
        "content": {
            "type": "string",
            "description": "你要修改的技能内容"
        }
    },
    "required": ["skills", "summary", "content"]
})
def modify_skills(source: CommandSource, ai_prefix: str, skills: str, summary: str, content: str):
    server = source.get_server()
    source.reply(f"{ai_prefix}{server.rtr("games_ai.tools.modifying_skills", skills=skills)}")
    if source.get_permission_level() < plugin_config.allow_permission:
        return server.rtr("games_ai.tools.permission_denied")
    skills_path = os.path.join(os.path.dirname(plugin_config.skills_path), skills)
    try:
        with open(skills_path, mode='w', encoding='utf-8') as f:
            f.write(content)

        try:
            with open(plugin_config.skills_path, mode='r', encoding='utf-8') as f:
                index_data = json.load(f)
                if not isinstance(index_data, list):
                    index_data = []
        except (FileNotFoundError, json.JSONDecodeError):
            index_data = []

        found = False
        for item in index_data:
            if item.get("file") == skills:
                item["description"] = summary
                found = True
                break
        if not found:
            index_data.append({"file": skills, "description": summary})

        with open(plugin_config.skills_path, mode='w', encoding='utf-8') as f:
            json.dump(index_data, f, ensure_ascii=False, indent=4)

        return f"skills修改成功"
    except Exception as e:
        return f"skills修改失败, 原因: {e}"

@register_tool(description="删除技能, 调用多个工具前必备, 每次只能删除一个skills", tr_key="games_ai.tools.deleting_skills", parameters={
    "type": "object",
    "properties": {
        "skills": {
            "type": "string",
            "description": "你要删除的技能文件的文件名"
        }
    },
    "required": ["skills"]
})
def delete_skills(source: CommandSource, ai_prefix: str, skills: str):
    server = source.get_server()
    source.reply(f"{ai_prefix}{server.rtr("games_ai.tools.deleting_skills", skills=skills)}")
    if source.get_permission_level() < plugin_config.allow_permission:
        return server.rtr("games_ai.tools.permission_denied")
    skills_path = os.path.join(os.path.dirname(plugin_config.skills_path), skills)
    try:
        os.remove(skills_path)

        try:
            with open(plugin_config.skills_path, mode='r', encoding='utf-8') as f:
                index_data = json.load(f)
                if not isinstance(index_data, list):
                    index_data = []
        except (FileNotFoundError, json.JSONDecodeError):
            index_data = []

        index_data = [item for item in index_data if item.get("file") != skills]

        with open(plugin_config.skills_path, mode='w', encoding='utf-8') as f:
            json.dump(index_data, f, ensure_ascii=False, indent=4)

        return f"skills删除成功"
    except Exception as e:
        return f"skills删除失败, 原因: {e}"
    
@register_tool(description="设置一个计时器, 等待这段时间之后再执行下一步操作", tr_key="setting_timer", parameters={
    "type": "object",
    "properties": {
        "duration": {
            "type": "number",
            "description": "等待的时长（秒）"
        }
    },
    "required": ["duration"]
})
@register_bot_tool()
def setting_timer(source: CommandSource, ai_prefix: str, duration: int):
    server = source.get_server()
    source.reply(f"{ai_prefix}{server.rtr("games_ai.tools.setting_timer", duration=duration)}")
    time.sleep(duration)
    return f"计时器结束，已等待 {duration} 秒"

@register_tool(description="读取自定义tools文件", tr_key="games_ai.tools.reading_custom_tools")
def read_custom_tools(source: CommandSource, ai_prefix: str):
    server = source.get_server()
    source.reply(f"{ai_prefix}{server.rtr("games_ai.tools.reading_custom_tools")}")
    if source.get_permission_level() < plugin_config.allow_permission:
        return server.rtr("games_ai.tools.permission_denied")
    try:
        with open(plugin_config.tools_path, mode='r', encoding='utf-8') as f:
            tools_content = f.read()
        return f"tools文件内容:\n{tools_content}"
    except Exception as e:
        return f"tools文件读取失败, 原因: {e}"

@register_tool(description="修改自定义tools文件, 为AI提供更灵活的功能, 修改之前务必先阅读tools文件和相关skills", tr_key="games_ai.tools.modifying_custom_tools", parameters={
    "type": "object",
    "properties": {
        "tools": {
            "type": "string",
            "description": "要修改的源代码, 请确保代码是有效的Python代码"
        },
    },
    "required": ["tools"]
})
def modify_custom_tools(source: CommandSource, ai_prefix: str, tools: str):
    server = source.get_server()
    source.reply(f"{ai_prefix}{server.rtr("games_ai.tools.modifying_custom_tools")}")
    if source.get_permission_level() < plugin_config.allow_permission:
        return server.rtr("games_ai.tools.permission_denied")
    try:
        with open(plugin_config.tools_path, mode='w', encoding='utf-8') as f:
            f.write(tools)
        return f"tools文件修改成功"
    except Exception as e:
        return f"tools文件修改失败, 原因: {e}"

@register_tool(description="新增一个自定义tools到原有tools文件的末尾, 修改之前务必先阅读tools文件和相关skills", tr_key="games_ai.tools.appending_custom_tools", parameters={
    "type": "object",
    "properties": {
        "tools": {
            "type": "string",
            "description": "要追加到tools文件末尾的Python源代码, 请确保代码是有效的Python代码"
        },
    },
    "required": ["tools"]
})
def append_custom_tools(source: CommandSource, ai_prefix: str, tools: str):
    server = source.get_server()
    source.reply(f"{ai_prefix}{server.rtr("games_ai.tools.appending_custom_tools")}")
    if source.get_permission_level() < plugin_config.allow_permission:
        return server.rtr("games_ai.tools.permission_denied")
    try:
        with open(plugin_config.tools_path, mode='r', encoding='utf-8') as f:
            existing = f.read()
        new_content = existing.rstrip("\n") + "\n\n" + tools.strip() + "\n"
        with open(plugin_config.tools_path, mode='w', encoding='utf-8') as f:
            f.write(new_content)
        return f"tools追加成功"
    except Exception as e:
        return f"tools追加失败, 原因: {e}"

@register_tool(description="重载插件", tr_key="games_ai.tools.reloading_plugin")
def reload_plugin(source: CommandSource, ai_prefix: str):
    server = source.get_server()
    source.reply(f"{ai_prefix}{server.rtr("games_ai.tools.reloading_plugin")}")
    server.execute_command("!!gamesai reload", source)
    return f"插件已重载"


@register_tool(description="获取指定玩家的位置、维度", tr_key="getting_player_position", parameters={
    "type": "object",
    "properties": {
        "player": {
            "type": "string",
            "description": "要查询的玩家名称"
        }
    },
    "required": ["player"]
})
@register_bot_tool()
def get_player_position(source: CommandSource, ai_prefix: str, player: str):
    server = source.get_server()
    source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.getting_player_position", player=player)}')
    api = server.get_plugin_instance('minecraft_data_api')
    if api is None:
        return "无法获取 minecraft_data_api 插件实例，请检查是否已安装并加载"
    try:
        data = api.get_player_info(player)
        if data is None:
            return f"查询玩家 {player} 超时，请稍后重试"
        pos = data.get('Pos', [])
        dim_raw = data.get('Dimension', '')
        if not pos or len(pos) < 3:
            return f"未能从玩家 {player} 的数据中解析出坐标"
        dim_map = {
            'minecraft:overworld': '主世界',
            'minecraft:the_nether': '下界',
            'minecraft:the_end': '末地',
        }
        dim_name = dim_map.get(dim_raw, dim_raw)
        return f"玩家 {player} 的位置: ({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f}), 维度: {dim_name}"
    except ValueError as e:
        return f"查询玩家 {player} 失败: {e}"
    except Exception as e:
        return f"获取玩家 {player} 信息失败: {e}"