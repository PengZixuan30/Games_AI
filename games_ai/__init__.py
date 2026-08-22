from mcdreforged.api.all import *

from .openai_api import response_chat, setup_openai_logging
from .games_ai_tool import get_tool_handler, register_tool, get_tool_schemas_for_perm, get_plugin_config_perm, reset_all_tools, TOOL_PLUGIN_IDS
from .database import PublicDatabase
from .config import plugin_config
from .tools_interpreter import load_external_tools
from .mineflayer import write_default_init, write_package_json, run_node, start_mineflayer_client, stop_mineflayer_client, stop_mineflayer_process, get_default_init_hash, is_node_running, MineflayerWSClient
from .mineflayer_ai import AutonomousBotController, set_bot_controller
from .external_skills_loader import EXTERNAL_SKILLS_LIST
from .register_extra_plugin import REGISTER_PLUGIN_LIST

import time,os,requests,lzma,json,threading,datetime,logging

import shutil
import subprocess
import hashlib
import re

PLUGIN_METADATA = {
    "id": "games_ai",
    "version": "0.6.4",
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
user_tool_counts = {}
_history_locks: dict[tuple, threading.Lock] = {}
websocket_connections: dict[str, MineflayerWSClient] = {}
_autonomous_controller: AutonomousBotController | None = None
_aibot_lock = threading.Lock()
# Set when the plugin is unloaded, so a pending "wait for server start" bot
# launch aborts cleanly (see _wait_server_then_launch)
_mineflayer_pending_abort = threading.Event()
_mineflayer_wait_thread: threading.Thread | None = None

def _get_history_lock(username: str, ai_prefix: str) -> threading.Lock:
    key = (username, ai_prefix)
    lock = _history_locks.get(key)
    if lock is None:
        lock = threading.Lock()
        _history_locks[key] = lock
    return lock

def on_load(server: PluginServerInterface, old):
    global prefix,allow_permission,max_history,mcdr_lang,_timer,ai_dict,default_ai,name_to_id,data_path,skills
    _timer = None
    
    DEFAULT_CONFIG = {
        "prefix": "[GamesAI]",
        "permission": 3,
        "max_history": 10,
        "all_ai": {
            "<Your AI ID>":{
                "prompt": str(server.rtr("games_ai.system_message.default")),
                "ai_name": "[GamesAI]",
                "base_url": "<Your API Base URL>",
                "ai_model": "<Your AI Model>",
                "api_key": "<Your API Key>",
                "extra_body": {},
            }
        },
        "default_ai": "<Your AI ID>",
        "mineflayer_bot": {
            "enabled": False,
            "cycle_interval": 15.0,
            "websocket": {
                "url": "ws://127.0.0.1:8080",
                "reconnect_interval": 10,
                "timeout": 60
            },
            "bot": {
                "username": "<Your Minecraft Bot Username>",
                "password": "<Your Minecraft Bot Password>",
                "auth": "microsoft"
            }
        }
    }
    
    server.register_help_message(prefix="!!gamesai",message=server.rtr("games_ai.mcdr_help_message.gamesai_help"))
    server.register_help_message(prefix="!!ask <content>",message=server.rtr("games_ai.mcdr_help_message.gamesai_ask"))

    config = server.load_config_simple(
        file_name='config.json',
        default_config=DEFAULT_CONFIG,
        in_data_folder=True
    )

    _apply_config(server, config)
    setup_openai_logging(server.logger, level=logging.INFO)

    server.register_help_message(prefix="!!data",message=server.rtr("games_ai.mcdr_help_message.data"),permission=allow_permission)

    server.logger.info(f'{prefix}{server.rtr("games_ai.load_message.server_info")}')
    server.say(f'{prefix}{server.rtr("games_ai.load_message.client_info",v=PLUGIN_METADATA.get("version"))}')

    builder = SimpleCommandBuilder()

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

    skills_path = os.path.join(server.get_data_folder(), "skills", "skills.json")
    skills_dir = os.path.dirname(skills_path)
    if not os.path.exists(skills_dir):
        os.makedirs(skills_dir, exist_ok=True)
    if not os.path.exists(skills_path):
        with open(skills_path, mode='w', encoding='utf-8') as f:
            f.write("[{}]")
        server.logger.info(f"{server.rtr("games_ai.load_message.server_create_data_dir")}{skills_path}")

    with open(skills_path, mode="r", encoding="utf-8") as f:
        content = f.read()
        skills = json.loads(content)

    mineflayer_path = os.path.join(server.get_data_folder(), "mineflayer", "init.js")
    mineflayer_dir = os.path.dirname(mineflayer_path)
    mineflayer_package_json_path = os.path.join(server.get_data_folder(), "mineflayer", "package.json")
    if not os.path.exists(mineflayer_dir):
        os.makedirs(mineflayer_dir, exist_ok=True)
    _write_mineflayer_config(server, config)
    if not os.path.exists(mineflayer_path) or hashlib.md5(open(mineflayer_path, "rb").read()).hexdigest() != get_default_init_hash():
        write_default_init(mineflayer_path)
    if not os.path.exists(mineflayer_package_json_path):
        write_package_json(mineflayer_package_json_path)

    plugin_config.data_path = data_path
    plugin_config.tools_path = tools_path
    plugin_config.skills_path = skills_path
    plugin_config.builtin_skills_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")
    plugin_config.mineflayer_init_js_path = mineflayer_path

    load_external_tools(log=server.logger.info)

    mineflayer_cfg = config.get("mineflayer_bot", {})
    if mineflayer_cfg.get("enabled", False):
        _run_mineflayer_bot(server, mineflayer_cfg, mineflayer_path)

    data_manager = DataManager(data_path)
    config_manager = ConfigManager(config)
    helper = gamesai_help()

    builder.command('!!gamesai', helper.all_help)
    builder.command('!!gamesai help', helper.all_help)

    builder.command('!!gamesai clear',clear_history)
    builder.command('!!gamesai clearall',clear_history_all)
    
    builder.command('!!gamesai check', check_update)

    builder.command('!!gamesai debug', debug)

    builder.command('!!gamesai reload', reloader)

    builder.command('!!gamesai speedtest', speed_test)
    builder.command('!!gamesai speedtest <model>', speed_test)

    builder.command('!!gamesai config', helper.config_help)
    builder.command('!!gamesai config get', helper.config_help)
    builder.command('!!gamesai config get <key>', config_manager.get_config)
    builder.command('!!gamesai config set', helper.config_help)
    builder.command('!!gamesai config set <key>', helper.config_help)
    builder.command('!!gamesai config set <key> <value>', config_manager.set_config)

    builder.command('!!ask', helper.ask_help)
    builder.command('!!ask <content>', ask_ai)
    builder.command('!!ask -m <model> <content>', ask_ai)
    builder.command('!!ask --model <model> <content>', ask_ai)
    builder.command('!!ask --no-history <content>', lambda source, context: ask_ai(source, context, no_history=True))
    builder.command('!!ask --no-history -m <model> <content>', lambda source, context: ask_ai(source, context, no_history=True))
    builder.command('!!ask --no-history --model <model> <content>', lambda source, context: ask_ai(source, context, no_history=True))
    builder.command('!!ask -n <content>', lambda source, context: ask_ai(source, context, no_history=True))
    builder.command('!!ask -n -m <model> <content>', lambda source, context: ask_ai(source, context, no_history=True))
    builder.command('!!ask -n --model <model> <content>', lambda source, context: ask_ai(source, context, no_history=True))

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

    builder.command('!!aibot', helper.aibot_help)
    builder.command('!!aibot join', aibot_join)
    builder.command('!!aibot leave', aibot_leave)
    builder.command('!!aibot set', helper.aibot_help)
    builder.command('!!aibot set <key>', helper.aibot_help)
    builder.command('!!aibot set <key> <value>', config_manager.aibot_config)

    builder.arg('model', Text)
    builder.arg('content',GreedyText)

    builder.arg('key', Text)
    builder.arg('value', GreedyText)

    builder.register(server)

    threading.Thread(target=cyclic_check_updates, daemon=True, args=(server,)).start()

def on_server_startup(server: PluginServerInterface):
    server.say(f'{prefix}{server.rtr("games_ai.load_message.client_info", v=PLUGIN_METADATA.get('version'))}')


def _disable_mineflayer_and_reload(server: PluginServerInterface):
    config_path = os.path.join(os.path.dirname(os.path.dirname(plugin_config.skills_path)), "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    config.setdefault("mineflayer_bot", {})["enabled"] = False
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    server.execute_command("!!gamesai reload")


def _get_minecraft_server_address() -> tuple[str, int]:
    host = "127.0.0.1"
    port = 25565
    for candidate in ("server.properties", "server/server.properties"):
        if os.path.isfile(candidate):
            with open(candidate, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("server-ip="):
                        v = line.split("=", 1)[1].strip()
                        if v:
                            host = v
                    elif line.startswith("server-port="):
                        try:
                            port = int(line.split("=", 1)[1].strip())
                        except ValueError:
                            pass
            break
    return host, port


def _write_mineflayer_config(server: PluginServerInterface, config: dict):
    mineflayer_dir = os.path.dirname(plugin_config.mineflayer_init_js_path)
    mineflayer_config_path = os.path.join(mineflayer_dir, "config.json")
    cfg = dict(config.get("mineflayer_bot", {}))
    host, port = _get_minecraft_server_address()
    cfg.setdefault("bot", {})
    cfg["bot"]["server_host"] = host
    cfg["bot"]["server_port"] = port
    with open(mineflayer_config_path, mode='w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


@register_tool(
    description="启动 Mineflayer 机器人，使其加入 Minecraft 服务器。如果机器人已在运行则不做任何操作。",
    perm=get_plugin_config_perm,
)
def run_mineflayer_bot(source: CommandSource, ai_prefix: str):
    server = source.get_server()
    if source.get_permission_level() < plugin_config.allow_permission:
        return server.rtr("games_ai.tools.permission_denied")
    if is_node_running():
        return f"Mineflayer 机器人已在运行（{plugin_config.bot_username}）"
    source.reply(f"{ai_prefix}{server.rtr('games_ai.tools.bot_start')}")
    _toggle_aibot(server, True)
    return "正在启动 Mineflayer 机器人..."


@register_tool(
    description="停止 Mineflayer 机器人，使其离开 Minecraft 服务器。",
    perm=get_plugin_config_perm,
)
def stop_mineflayer_bot(source: CommandSource, ai_prefix: str):
    server = source.get_server()
    if source.get_permission_level() < plugin_config.allow_permission:
        return server.rtr("games_ai.tools.permission_denied")
    if not is_node_running():
        return "Mineflayer 机器人未在运行"
    source.reply(f"{ai_prefix}{server.rtr('games_ai.tools.bot_stop')}")
    _toggle_aibot(server, False)
    return "正在停止 Mineflayer 机器人..."

def _run_mineflayer_bot(server: ServerInterface, bot_config: dict, mineflayer_init_js_path: str):
    if not server.is_server_running():
        global _mineflayer_wait_thread
        if _mineflayer_wait_thread is not None and _mineflayer_wait_thread.is_alive():
            server.logger.info(f"{prefix} Minecraft server is not running, already waiting for it to start...")
            return
        server.logger.info(f"{prefix} Minecraft server is not running, Mineflayer bot will launch automatically after the server starts")
        _mineflayer_wait_thread = _wait_server_then_launch(server, bot_config, mineflayer_init_js_path)
        return
    _launch_mineflayer_bot(server, bot_config, mineflayer_init_js_path)


@new_thread("games_ai@mineflayer_wait_server")
def _wait_server_then_launch(server: ServerInterface, bot_config: dict, mineflayer_init_js_path: str):
    while not server.is_server_running():
        if _mineflayer_pending_abort.is_set():
            server.logger.info(f"{prefix} Plugin unloaded, Mineflayer bot launch cancelled")
            return
        time.sleep(2)
    if _mineflayer_pending_abort.is_set():
        server.logger.info(f"{prefix} Plugin unloaded, Mineflayer bot launch cancelled")
        return
    server.logger.info(f"{prefix} Minecraft server started, launching Mineflayer bot...")
    _launch_mineflayer_bot(server, bot_config, mineflayer_init_js_path)


def _launch_mineflayer_bot(server: ServerInterface, bot_config: dict, mineflayer_init_js_path: str):
    node_path = shutil.which("node")
    if not node_path:
        server.logger.warning(f"{prefix} Mineflayer bot is enabled but Node.js was not found. Disabling and reloading...")
        _disable_mineflayer_and_reload(server)
    else:
        ws_cfg = bot_config.get("websocket", {})
        ws_url = ws_cfg.get("url", "ws://127.0.0.1:8080")
        try:
            import socket as _socket
            m = re.match(r'^ws://([^/:]+)(?::(\d+))?', ws_url)
            host = m.group(1) if m else "127.0.0.1"
            port = int(m.group(2)) if m and m.group(2) else 8080
            with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.bind((host, port))
        except OSError:
            server.logger.warning(
                f"{prefix} WebSocket port {port} is already in use! "
                f"Please change mineflayer_bot.websocket.url to a different port and reload."
            )
            _disable_mineflayer_and_reload(server)
            return
        try:
            version_output = subprocess.check_output([node_path, "--version"], text=True, timeout=5).strip()
            if version_output.startswith("v"):
                version_output = version_output[1:]
            major = int(version_output.split(".")[0])
            if major < 18:
                server.logger.warning(
                    f"{prefix} Mineflayer requires Node.js >= 18, but found v{version_output}. "
                    f"Disabling and reloading..."
                )
                _disable_mineflayer_and_reload(server)
            else:
                try:
                    run_node(mineflayer_init_js_path, logger=server.logger)
                except (RuntimeError, FileNotFoundError) as e:
                    server.logger.error(f"{prefix} Failed to launch Mineflayer bot: {e}")
                    return
                server.logger.info(f"{prefix} Mineflayer JS bot launched (Node.js v{version_output})")
                ws_reconnect = ws_cfg.get("reconnect_interval", 10)
                ws_timeout = ws_cfg.get("timeout", 60)
                try:
                    client = start_mineflayer_client(ws_url, server.logger, ws_reconnect, ws_timeout)
                    websocket_connections["mineflayer"] = client
                    server.logger.info(f"{prefix} Mineflayer WS client started (Node.js v{version_output}), connecting to {ws_url}")

                    default_ai_info = ai_dict.get(default_ai, None)
                    if default_ai_info is not None:
                        global _autonomous_controller
                        _autonomous_controller = AutonomousBotController(
                            ws_client=client,
                            model=default_ai_info.get("ai_model", ""),
                            base_url=default_ai_info.get("base_url", ""),
                            api_key=default_ai_info.get("api_key", ""),
                            system_prompt=str(server.rtr("games_ai.autonomous_bot.default_system_prompt")),
                            chat_prompt=default_ai_info.get("prompt", ""),
                            extra_body=default_ai_info.get("extra_body", {}),
                            cycle_interval=bot_config.get("cycle_interval", 15.0),
                            bot_username=plugin_config.bot_username,
                            server=server,
                            logger=server.logger,
                            tr=lambda key, **kw: str(server.rtr(key, **kw)),
                        )
                        _autonomous_controller.start()
                        set_bot_controller(_autonomous_controller)
                        server.logger.info(f"{prefix} AutonomousBot controller started")
                    else:
                        server.logger.warning(f"{prefix} No default AI configured, AutonomousBot controller skipped")
                except Exception as e:
                    server.logger.warning(f"{prefix} Failed to start Mineflayer WS client: {e}")
        except (subprocess.TimeoutExpired, ValueError, OSError) as e:
            server.logger.warning(f"{prefix} Failed to detect Node.js version: {e}. Skipping WS client startup.")


def _apply_config(server: PluginServerInterface, config: dict):
    global prefix, allow_permission, max_history, mcdr_lang, ai_dict, default_ai, name_to_id

    prefix = config.get('prefix', '[GamesAI]')
    max_history = config.get('max_history', 10)
    allow_permission = config.get('permission', 3)

    plugin_config.prefix = prefix
    plugin_config.allow_permission = allow_permission
    plugin_config.max_history = max_history
    
    prompt_dir = os.path.join(os.path.dirname(os.path.dirname(plugin_config.skills_path)), "prompt")
    if not os.path.exists(prompt_dir):
        os.makedirs(prompt_dir, exist_ok=True)

    ai_dict = {}
    all_ai: dict = config.get('all_ai', {})
    for ai_id, ai_config in all_ai.items():
        if not isinstance(ai_config, dict):
            continue
        raw_prompt: str = ai_config.get("prompt", str(server.rtr("games_ai.system_message.default")))
        if raw_prompt.startswith("> "):
            prompt_file_path = raw_prompt[2:].strip()
            prompt_full_path = os.path.join(prompt_dir, prompt_file_path)
            try:
                with open(prompt_full_path, 'r', encoding='utf-8') as f:
                    raw_prompt = f.read()
                server.logger.info(f"{prefix} Loaded prompt from file: {prompt_full_path}")
            except FileNotFoundError:
                server.logger.warning(f"{prefix} Prompt file not found: {prompt_full_path}, using default prompt")
                raw_prompt = str(server.rtr("games_ai.system_message.default"))
        ai_dict[ai_id] = {
            "prompt": raw_prompt,
            "ai_name": ai_config.get("ai_name", "[GamesAI]"),
            "base_url": ai_config.get("base_url", ""),
            "ai_model": ai_config.get("ai_model", ""),
            "api_key": ai_config.get("api_key", ""),
            "extra_body": ai_config.get("extra_body", {}),
        }

    default_ai = config.get("default_ai", list(ai_dict.keys())[0] if ai_dict else "")

    name_to_id = {}
    for aid, info in ai_dict.items():
        name = info.get("ai_name")
        name_to_id[name] = aid

    mcdr_lang = str(server.rtr("games_ai.system_message.lang", lang=server.get_mcdr_language()))

    bot_cfg = config.get("mineflayer_bot", {}).get("bot", {})
    plugin_config.bot_username = bot_cfg.get("username", "Bot")

def on_unload(server: PluginServerInterface):
    global _autonomous_controller, _mineflayer_wait_thread
    _mineflayer_pending_abort.set()
    _mineflayer_wait_thread = None
    if _timer is not None:
        _timer.cancel()
    try:
        if _autonomous_controller is not None:
            _autonomous_controller.stop()
            _autonomous_controller = None
        set_bot_controller(None)
        stop_mineflayer_client()
        websocket_connections.clear()
        stop_mineflayer_process()
    except Exception as e:
        server.logger.exception(f"{prefix} Unload failed: {e}")
    else:
        server.logger.info(f"{prefix} Mineflayer bot stopped successfully!")
    finally:
        server.logger.info(f"{prefix} Mineflayer bot process has been terminated successfully!")
    server.logger.info(f"{prefix}{server.rtr("games_ai.unload_message.server_info")}")
    for plugin_id in list(REGISTER_PLUGIN_LIST.keys()):
        try:
            server.logger.info(f"{prefix} Unloading registered extension plugin '{plugin_id}'")
            result = server.unload_plugin(plugin_id)
            if result is None:
                server.logger.warning(f"{prefix} Registered plugin '{plugin_id}' not found, removed from unload list")
                REGISTER_PLUGIN_LIST.pop(plugin_id, None)
            elif not result:
                server.logger.warning(f"{prefix} Failed to unload registered plugin '{plugin_id}'")
        except Exception as e:
            server.logger.exception(f"{prefix} Error while unloading registered plugin '{plugin_id}': {e}")
    REGISTER_PLUGIN_LIST.clear()
    if unload_status_code == 0:
        server.say(f'{prefix}Bye!')
    elif unload_status_code == 1:
        server.say(f'{prefix}{server.rtr("games_ai.unload_message.after_update_restart_msg")}')

class gamesai_help:
    @staticmethod
    def ask_help(source: CommandSource):
        server = source.get_server()
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.greeting", v=PLUGIN_METADATA.get("version")))
        send_help(source, prefix, command="!!ask <content>", command_help_key="games_ai.gamesai_help_message.ask_help")
        send_help(source, prefix, command="!!ask -m <model> <content>", command_help_key="games_ai.gamesai_help_message.ask_help")
        send_help(source, prefix, command="!!ask -n <content>", command_help_key="games_ai.gamesai_help_message.ask_no_history_help")
        send_help(source, prefix, command="!!ask -n -m <model> <content>", command_help_key="games_ai.gamesai_help_message.ask_no_history_help")
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.all_ai_model") + str(list(ai_dict.keys())))

    @staticmethod
    def data_help(source: CommandSource):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission=allow_permission))
            return
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.greeting", v=PLUGIN_METADATA.get("version")))
        send_help(source, prefix, command="!!data write <key> <value>", command_help_key="games_ai.gamesai_help_message.data_write_help")
        send_help(source, prefix, command="!!data add <key> <value>", command_help_key="games_ai.gamesai_help_message.data_add_help")
        send_help(source, prefix, command="!!data del <key>", command_help_key="games_ai.gamesai_help_message.data_del_help")
        send_help(source, prefix, command="!!data read <key>", command_help_key="games_ai.gamesai_help_message.data_read_help")
        send_help(source, prefix, command="!!data list", command_help_key="games_ai.gamesai_help_message.data_list_help")
        send_help(source, prefix, command="!!data list keys", command_help_key="games_ai.gamesai_help_message.data_keys_help")

    @staticmethod
    def data_write_help(source: CommandSource):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission=allow_permission))
            return
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.greeting", v=PLUGIN_METADATA.get("version")))
        send_help(source, prefix, command="!!data write <key> <value>", command_help_key="games_ai.gamesai_help_message.data_write_help")

    @staticmethod
    def data_del_help(source: CommandSource):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission=allow_permission))
            return
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.greeting", v=PLUGIN_METADATA.get("version")))
        send_help(source, prefix, command="!!data del <key>", command_help_key="games_ai.gamesai_help_message.data_del_help")

    @staticmethod
    def data_read_help(source: CommandSource):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission=allow_permission))
            return
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.greeting", v=PLUGIN_METADATA.get("version")))
        send_help(source, prefix, command="!!data read <key>", command_help_key="games_ai.gamesai_help_message.data_read_help")

    @staticmethod
    def data_add_help(source: CommandSource):
        server = source.get_server()
        if source.get_permission_level() < allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission=allow_permission))
            return
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.greeting", v=PLUGIN_METADATA.get("version")))
        send_help(source, prefix, command="!!data add <key> <value>", command_help_key="games_ai.gamesai_help_message.data_add_help")


    @staticmethod
    def config_help(source: CommandSource):
        server = source.get_server()
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.greeting", v=PLUGIN_METADATA.get("version")))
        if source.get_permission_level() < allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission=allow_permission))
            return
        send_help(source, prefix, command='!!gamesai config get <key>', command_help_key="games_ai.gamesai_help_message.config_help_get")
        send_help(source, prefix, command='!!gamesai config set <key> <value>', command_help_key="games_ai.gamesai_help_message.config_help_set")


    @staticmethod
    def aibot_help(source: CommandSource):
        server = source.get_server()
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.greeting", v=PLUGIN_METADATA.get("version")))
        if source.get_permission_level() < allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission=allow_permission))
            return
        send_help(source, prefix, command="!!aibot join", command_help_key="games_ai.gamesai_help_message.aibot_join_help")
        send_help(source, prefix, command="!!aibot leave", command_help_key="games_ai.gamesai_help_message.aibot_leave_help")
        send_help(source, prefix, command="!!aibot set <key> <value>", command_help_key="games_ai.gamesai_help_message.aibot_set_help")


    @staticmethod
    def all_help(source: CommandSource):
        server = source.get_server()
        send_help(source, prefix, message=server.rtr("games_ai.gamesai_help_message.greeting", v=PLUGIN_METADATA.get("version")))
        send_help(source, prefix, command="!!ask <content>", command_help_key="games_ai.gamesai_help_message.ask_help")
        send_help(source, prefix, command="!!gamesai clear", command_help_key="games_ai.gamesai_help_message.clear_help")
        if source.get_permission_level() >= allow_permission:
            send_help(source, prefix, command="!!gamesai clearall", command_help_key="games_ai.gamesai_help_message.clearall_help")
            send_help(source, prefix, command="!!gamesai check", command_help_key="games_ai.gamesai_help_message.check_update_help")
            send_help(source, prefix, command='!!gamesai config',command_help_key="games_ai.gamesai_help_message.config_help")
            send_help(source, prefix, command="!!data", command_help_key="games_ai.gamesai_help_message.data_help")
            send_help(source, prefix, command="!!aibot <join | leave>", command_help_key="games_ai.gamesai_help_message.aibot_help")


def send_help(source: CommandSource, prefix: str, message: str|None = None, command: str|None = None, command_help_key: str|None = None):
    server = source.get_server()
    if command and message is None:
        source.reply(RTextList(
            prefix,
            server.rtr("games_ai.gamesai_help_message.help_prefix"),
            RText(command, RColor.gray).c(RAction.suggest_command, command[:command.find(' <')] + ' ' if ' <' in command else command + ' '),
            server.rtr(command_help_key)
        ))
        return
    else:
        source.reply(RTextList(
            prefix,
            message,
        ))
        return

def _safe_trim_history(history: list, max_len: int) -> list:
    if len(history) <= max_len:
        return history

    trimmed = history[-max_len:]

    for i, msg in enumerate(trimmed):
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        if role == "user":
            return trimmed[i:]

    return trimmed


@new_thread("games_ai@ask_ai")
def ask_ai(source: CommandSource, context: dict, no_history: bool = False):
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
            source.reply(f"{prefix}{server.rtr("games_ai.user_message.model_error")}{list(ai_dict.keys())}")
            return

    ai_prefix = ai_info.get("ai_name")
    ai_model = ai_info.get("ai_model")
    base_url = ai_info.get("base_url")
    api_key = ai_info.get("api_key")
    prompt = ai_info.get("prompt")

    default_skills = [
        {"file": "skills_management.md", "description": str(server.rtr("games_ai.builtin_skills.skills_management"))},
        {"file": "custom_tools_management.md", "description": str(server.rtr("games_ai.builtin_skills.custom_tools_management"))},
    ]
    if is_node_running() and _autonomous_controller is not None and _autonomous_controller.is_running:
        default_skills.append({"file": "mineflayer_bot_guide.md", "description": str(server.rtr("games_ai.builtin_skills.mineflayer_bot_guide", username=plugin_config.bot_username))})

    external_skills: list[dict[str, str]] = []
    if EXTERNAL_SKILLS_LIST:
        for i in EXTERNAL_SKILLS_LIST:
            file = i.get("file")
            description = i.get("description")
            if file is None or description is None:
                continue
            external_skills.append({"file": file, "description": description})

    if external_skills:
        skills_file_list = str(server.rtr("games_ai.user_message.skills", skills=[*skills, *default_skills, *external_skills]))
    else:
        skills_file_list = str(server.rtr("games_ai.user_message.skills", skills=[*skills, *default_skills]))

    extra_body = ai_info.get("extra_body", {})

    now_time = datetime.datetime.now()
    now_time = str(server.rtr("games_ai.user_message.time", time=now_time.strftime('%Y-%m-%d %H:%M:%S')))
    username = get_username(source)
    lock = _get_history_lock(username, ai_prefix)
    with lock:
        shared = history_conversation.setdefault(username, {}).setdefault(ai_prefix, [])
        base_len = len(shared)
        history = list(shared)
        current_tool_count = user_tool_counts.setdefault(username, {}).get(ai_prefix, 0)
    content: str = context['content']
    if source.is_player:
        user_name = f'{username}'
    else:
        user_name = "Server Control Panel"

    skills_file: str | None = None
    if content.strip().startswith("/"):
        skill_name = content.strip().split(" ")[0][1:]
        if not skill_name.endswith(".md"):
            skill_name += ".md"

        all_skill_files: list[str] = [
            f.get("file", "") for f in [*skills, *default_skills]
            if f.get("file")
        ]
        for es in external_skills:
            f = es.get("file")
            if f:
                all_skill_files.append(f)

        if skill_name in all_skill_files:
            skills_file = skill_name
            source.reply(f"{ai_prefix}{server.rtr('games_ai.user_message.skill_selected', skill=skill_name)}")
        else:
            source.reply(f"{ai_prefix}{server.rtr('games_ai.user_message.skill_not_found', skill=skill_name)}")

    user_message = {"role": "user","content": f'{str(server.rtr("games_ai.user_message.username"))}{user_name}\n{str(server.rtr("games_ai.user_message.message"))}{content}'}
    response_message = [
        {"role": "system","content": now_time + mcdr_lang},
        {"role": "system", "content": prompt},
    ]
    if skills_file:
        response_message.append({
            "role": "system",
            "content": str(server.rtr('games_ai.user_message.skill_injected', skill=skills_file))
        })
    else:
        response_message.append({"role": "system", "content": skills_file_list})
    data = DataManager(data_path).ask_ai_read_data()
    data_message = {"role": "system","content": f'{str(server.rtr("games_ai.user_message.data_list"))}{data}'}
    response_message.append(data_message)
    if not no_history:
        response_message.extend(history)
    response_message.append(user_message)

    ai_tools: list[dict] = get_tool_schemas_for_perm(source.get_permission_level())

    if debug_mode:
        source.reply(f"[DEBUG]{response_message}")
    
    history.append(user_message)

    source.reply(f"{ai_prefix}{server.rtr("games_ai.user_message.thinking")}")

    while True:
        try:
            ai_reply = response_chat(model=ai_model,url=base_url,message=response_message,api_key=api_key,tools=ai_tools,extra_body=extra_body)
            if ai_reply.tool_calls is not None:
                response_message.append(ai_reply)
                history.append(ai_reply)
                if ai_reply.content:
                    source.reply(f"{ai_prefix}{ai_reply.content}")

                if debug_mode:
                    source.reply(f"[DEBUG]{ai_reply.tool_calls}")

                for tool_call in ai_reply.tool_calls:
                    func_name = tool_call.function.name
                    handler = get_tool_handler(func_name)
                    current_tool_count += 1

                    if handler is None:
                        result = f"未知函数: {func_name}"
                        source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.unknown_function",func_name=func_name)}')
                    else:
                        try:
                            func_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                            result = str(handler.func(source, ai_prefix, **func_args))
                            source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.tool_success")}')
                        except Exception as e:
                            result = f"函数 {func_name} 执行出错: {e}"
                            source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.execution_error",func_name=func_name,ex=e)}')
                        
                    if debug_mode:
                        source.reply(f"[DEBUG] Tool call result: \n{result}")

                    response_message.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })
                    history.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })
                continue
            else:
                message = f'{ai_prefix}{ai_reply.content}'

                if max_history > 0:
                    history.append(ai_reply)
                    with lock:
                        shared = history_conversation.setdefault(username, {}).setdefault(ai_prefix, [])
                        new_msgs = history[base_len:]
                        shared.extend(new_msgs)
                        max_len = max_history * 2 + current_tool_count * 2
                        if debug_mode:
                            source.reply(f"{ai_prefix}当前最大历史记录数: {max_len}")
                        if len(shared) > max_len:
                            trimmed = _safe_trim_history(list(shared), max_len)
                            shared.clear()
                            shared.extend(trimmed)
                        user_tool_counts.setdefault(username, {})[ai_prefix] = current_tool_count
                
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

def get_username(source: CommandSource) -> str:
    if source.is_player:
        return source.player
    else:
        return "Server Control Panel"

def clear_history(source: CommandSource,context: dict):
    server = source.get_server()
    username = get_username(source)
    if username in history_conversation:
        del history_conversation[username]
        if username in user_tool_counts:
            del user_tool_counts[username]
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
        user_tool_counts.clear()
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

class AiDataManager:
    @staticmethod
    @register_tool(description="读取公共数据中的键值对, 输入key以获取对应的value, 推荐在读取之前先查看现有的key都有哪些", parameters={
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
    @register_tool(description="读取公共数据中的所有键")
    def ai_read_all_keys(source: CommandSource, ai_prefix: str):
        server = source.get_server()
        source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.reading_all_keys")}')
        keys = PublicDatabase(data_path).get_all_key()
        return f"当前所有的键有: {keys}"

    @staticmethod
    @register_tool(description="向公共数据中写入键值对(新增/覆写模式), 输入key和value以写入数据, 注意写入方式为覆写, 需避免覆盖重要数据, 数据不存在时将自动创建", perm=get_plugin_config_perm, parameters={
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
    @register_tool(description="向公共数据中追加数据(新增/追加模式), 输入key和value以追加数据, 数据将被追加到原数据的末尾, 不存在时自动创建", perm=get_plugin_config_perm, parameters={
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
    @register_tool(description="从公共数据中删除数据, 输入key以删除对应的数据, 注意删除后无法恢复, 即使key不存在, 也仍然会进行删除", perm=get_plugin_config_perm, parameters={
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
    
    @staticmethod
    @register_tool(description="读取公共数据中的所有键值对")
    def ai_read_all_data(source: CommandSource, ai_prefix: str):
        server = source.get_server()
        source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.reading_all_data")}')
        value = PublicDatabase(data_path).data_list()
        return f'当前数据库中的所有数据: {value}'

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
    global skills, _autonomous_controller
    server = source.get_server()

    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(plugin_config.skills_path)), 'config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        _apply_config(server, config)

        tool_plugin_ids = set(TOOL_PLUGIN_IDS)

        reset_all_tools()

        try:
            with open(plugin_config.skills_path, mode="r", encoding="utf-8") as f:
                skills = json.loads(f.read())
        except Exception as e:
            server.logger.warning(f"{prefix} Failed to reload skills: {e}")

        load_external_tools(log=server.logger.info)

        _write_mineflayer_config(server, config)
        mineflayer_dir = os.path.dirname(plugin_config.mineflayer_init_js_path)
        mineflayer_package_json_path = os.path.join(mineflayer_dir, "package.json")
        if not os.path.exists(mineflayer_package_json_path):
            write_package_json(mineflayer_package_json_path)

        init_js_changed = False
        if not os.path.exists(plugin_config.mineflayer_init_js_path) or hashlib.md5(open(plugin_config.mineflayer_init_js_path, "rb").read()).hexdigest() != get_default_init_hash():
            write_default_init(plugin_config.mineflayer_init_js_path)
            init_js_changed = True

        mineflayer_cfg = config.get("mineflayer_bot", {})
        new_enabled = mineflayer_cfg.get("enabled", False)
        was_running = is_node_running()

        if new_enabled and was_running and not init_js_changed:
            server.logger.info(f"{prefix} Config hot-reloaded, JS bot will pick up changes automatically")
        else:
            try:
                if _autonomous_controller is not None:
                    _autonomous_controller.stop()
                    _autonomous_controller = None
                set_bot_controller(None)
                stop_mineflayer_client()
                websocket_connections.clear()
                stop_mineflayer_process()
            except Exception as e:
                server.logger.warning(f"{prefix} Failed to stop existing Mineflayer bot!")
                server.logger.exception(e)
            else:
                server.logger.info(f"{prefix} Mineflayer bot stopped successfully!")
            finally:
                server.logger.info(f"{prefix} Mineflayer bot process has been terminated successfully!")

            if new_enabled:
                try:
                    _run_mineflayer_bot(server, mineflayer_cfg, plugin_config.mineflayer_init_js_path)
                except Exception as e:
                    server.logger.exception(f"{prefix} Failed to start Mineflayer bot: {e}")

        plugin_reload_map = dict(REGISTER_PLUGIN_LIST)
        for plugin_id in tool_plugin_ids:
            if plugin_id != PLUGIN_METADATA["id"] and plugin_id not in plugin_reload_map:
                plugin_reload_map[plugin_id] = None

        for plugin_id, reloader in plugin_reload_map.items():
            if reloader is None:
                _reload_plugin = server.reload_plugin(plugin_id)
                if _reload_plugin is None:
                    server.logger.warning(f"{prefix} Plugin '{plugin_id}' (registered tools) not found")
                    REGISTER_PLUGIN_LIST.pop(plugin_id, None)
                    TOOL_PLUGIN_IDS.discard(plugin_id)
                elif not _reload_plugin:
                    server.unload_plugin(plugin_id)
                    server.logger.warning(f"{prefix} Failed to reload plugin '{plugin_id}', unloaded and removed from reload list")
                    REGISTER_PLUGIN_LIST.pop(plugin_id, None)
                    TOOL_PLUGIN_IDS.discard(plugin_id)
                else:
                    server.logger.info(f"{prefix} Successfully reloaded plugin '{plugin_id}'")
            else:
                try:
                    reloader(source)
                    server.logger.info(f"{prefix} Successfully reloaded registered plugin '{plugin_id}'")
                except Exception as e:
                    server.unload_plugin(plugin_id)
                    server.logger.warning(f"{prefix} Failed to reload registered plugin '{plugin_id}', unloaded and removed from reload list, reason: {e}")
                    REGISTER_PLUGIN_LIST.pop(plugin_id, None)
                    TOOL_PLUGIN_IDS.discard(plugin_id)
    except Exception as e:
        server.logger.exception(f"{prefix} Reload failed: {e}")
        source.reply(f"{prefix}Reload failed: {e}")

    server.dispatch_event(LiteralEvent("games_ai.reload"), (source,))

    server.say(f'{prefix}{server.rtr("games_ai.unload_message.reloader_msg")}')
    server.logger.info(f'{prefix}{server.rtr("games_ai.unload_message.reloader_msg")}')
    return

@new_thread("games_ai@speed_test")
def speed_test(source: CommandSource, context: dict):
    server = source.get_server()
    test_url = []

    user_input = context.get("model")
    if user_input is not None:
        user_input_id = name_to_id.get(user_input, user_input)
        ai_info = ai_dict.get(user_input_id)

        if ai_info is None:
            may_user_ai = []
            for ai_id, ai_config in ai_dict.items():
                name = ai_config.get("ai_name", "")
                if user_input.lower() in name.lower() or user_input.lower() in ai_id.lower():
                    may_user_ai.append(ai_id)
            if len(may_user_ai) == 1:
                ai_info = ai_dict.get(may_user_ai[0])
            elif len(may_user_ai) > 1:
                source.reply(f"{prefix}{server.rtr('games_ai.user_message.model_more')}{may_user_ai}")
                return
            else:
                source.reply(f"{prefix}{server.rtr('games_ai.user_message.model_error')}{list(ai_dict.keys())}")
                return

        ai_prefix = ai_info.get("ai_name")
        base_url = ai_info.get("base_url")
        api_key = ai_info.get("api_key")
        test_url.append((ai_prefix, base_url, api_key))
    else:
        test_url = [(ai_info.get("ai_name"), ai_info.get("base_url"), ai_info.get("api_key")) for ai_info in ai_dict.values()]

    for ai_prefix, base_url, api_key in test_url:
        source.reply(f'{ai_prefix}{server.rtr("games_ai.speed_test.testing", url=base_url)}')

        try:
            start_time = time.time()
            response = requests.get(
                base_url.rstrip("/") + "/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10
            )
            elapsed = (time.time() - start_time) * 1000

            if response.status_code in (200, 401):
                source.reply(
                    f'{ai_prefix}✅ {server.rtr("games_ai.speed_test.success")}\n{ai_prefix}{server.rtr("games_ai.speed_test.latency", latency=f"{elapsed:.0f}")}\n{ai_prefix}{server.rtr("games_ai.speed_test.status_code", code=response.status_code)}'
                )
            else:
                source.reply(
                    f'{ai_prefix}⚠️ {server.rtr("games_ai.speed_test.partial", latency=f"{elapsed:.0f}", code=response.status_code)}'
                )
        except requests.exceptions.Timeout:
            source.reply(f'{ai_prefix}❌ {server.rtr("games_ai.speed_test.timeout")}')
        except requests.exceptions.ConnectionError as e:
            source.reply(f'{ai_prefix}❌ {server.rtr("games_ai.speed_test.connection_error", error=str(e))}')
        except Exception as e:
            source.reply(f'{ai_prefix}❌ {server.rtr("games_ai.speed_test.error", error=str(e))}')
    return


def _toggle_aibot(server: PluginServerInterface, enabled: bool) -> bool:
    config_path = os.path.join(os.path.dirname(os.path.dirname(plugin_config.skills_path)), "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    current = config.get("mineflayer_bot", {}).get("enabled", False)
    if current == enabled:
        return True
    config.setdefault("mineflayer_bot", {})["enabled"] = enabled
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    server.execute_command("!!gamesai reload")
    return False


def aibot_join(source: CommandSource, context: dict):
    with _aibot_lock:
        server = source.get_server()
        if source.get_permission_level() < plugin_config.allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission=plugin_config.allow_permission))
            return
        if not re.fullmatch(r'[a-zA-Z0-9_]+', plugin_config.bot_username):
            source.reply(f"{prefix}{server.rtr('games_ai.aibot.invalid_bot_username', username=plugin_config.bot_username)}")
            return
        if _toggle_aibot(server, True):
            server.say(f"{prefix}{server.rtr('games_ai.aibot.already_joined', username=plugin_config.bot_username)}")
        else:
            source.reply(f"{prefix}{server.rtr('games_ai.aibot.join', username=plugin_config.bot_username)}")


def aibot_leave(source: CommandSource, context: dict):
    with _aibot_lock:
        server = source.get_server()
        if source.get_permission_level() < plugin_config.allow_permission:
            source.reply(server.rtr("games_ai.no_permission", permission=plugin_config.allow_permission))
            return
        if _toggle_aibot(server, False):
            server.say(f"{prefix}{server.rtr('games_ai.aibot.already_left', username=plugin_config.bot_username)}")
        else:
            source.reply(f"{prefix}{server.rtr('games_ai.aibot.leave', username=plugin_config.bot_username)}")


class ConfigManager:
    def __init__(self, config: dict):
        self.config = config
        self.config_path = os.path.join(os.path.dirname(os.path.dirname(plugin_config.skills_path)), "config.json")


    def get_config(self, source: CommandSource, context: CommandContext):
        server = source.get_server()
        if source.get_permission_level() < plugin_config.allow_permission:
            source.reply(f"{prefix}{server.rtr("games_ai.no_permission", permission=plugin_config.allow_permission)}")
            return

        config_key = context.get("key")
        if config_key is None:
            source.reply(f"{prefix}{server.rtr('games_ai.config_manager.no_key')}")
            return
        with open(self.config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        content = config.get(config_key)
        if content is None:
            source.reply(f"{prefix}{server.rtr('games_ai.config_manager.key_not_found', key=config_key)}")
            return
        source.reply(f"{prefix}{server.rtr('games_ai.config_manager.get_success', key=config_key, value=json.dumps(content, ensure_ascii=False, indent=2))}")
        return


    def set_config(self, source: CommandSource, context: CommandContext):
        server = source.get_server()
        if source.get_permission_level() < plugin_config.allow_permission:
            source.reply(f"{prefix}{server.rtr("games_ai.no_permission", permission=plugin_config.allow_permission)}")
            return

        config_key = context.get("key")
        new_value = context.get("value")
        if config_key is None or new_value is None:
            source.reply(f"{prefix}{server.rtr('games_ai.config_manager.missing_args')}")
            return
        if config_key in ("all_ai", "mineflayer_bot"):
            source.reply(f"{prefix}{server.rtr('games_ai.config_manager.complex_key_denied', key=config_key)}")
            return

        with open(self.config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        old_value = config.get(config_key)

        try:
            parsed_value = json.loads(new_value)
        except (json.JSONDecodeError, ValueError):
            parsed_value = new_value

        if old_value is not None and not isinstance(parsed_value, type(old_value)):
            try:
                if isinstance(old_value, bool):
                    parsed_value = parsed_value not in (False, 0, '', 'false', 'False', '0')
                else:
                    parsed_value = type(old_value)(parsed_value)
            except (ValueError, TypeError):
                source.reply(f"{prefix}{server.rtr('games_ai.config_manager.type_mismatch', key=config_key, old_type=type(old_value).__name__, new_type=type(parsed_value).__name__)}")
                return

        config[config_key] = parsed_value
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

        source.reply(f"{prefix}{server.rtr('games_ai.config_manager.set_success', key=config_key, value=new_value)}")
        server.execute_command("!!gamesai reload")
        return


    def aibot_config(self, source: CommandSource, context: CommandContext):
        server = source.get_server()
        if source.get_permission_level() < plugin_config.allow_permission:
            source.reply(f"{prefix}{server.rtr("games_ai.no_permission", permission=plugin_config.allow_permission)}")
            return

        config_key = context.get("key")
        config_value = context.get("value")
        if config_key is None or config_value is None:
            source.reply(f"{prefix}{server.rtr('games_ai.config_manager.missing_args')}")
            return
        if config_key not in ("username", "password", "auth"):
            source.reply(f"{prefix}{server.rtr('games_ai.aibot.invalid_key', key=config_key)}")
            return

        if config_key in ("username", "password"):
            if not re.fullmatch(r'[a-zA-Z0-9_]+', config_value):
                source.reply(f"{prefix}{server.rtr('games_ai.aibot.invalid_format', key=config_key)}")
                return
        if config_key == "auth" and config_value not in ("microsoft", "mojang", "offline"):
            source.reply(f"{prefix}{server.rtr('games_ai.aibot.invalid_auth')}")
            return

        with open(self.config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        bot_section = config.setdefault("mineflayer_bot", {}).setdefault("bot", {})
        bot_section[config_key] = config_value

        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

        source.reply(f"{prefix}{server.rtr('games_ai.aibot.set_success', key=config_key, value=config_value)}")
        server.execute_command("!!gamesai reload")
        return

