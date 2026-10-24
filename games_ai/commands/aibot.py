"""``!!aibot join`` / ``!!aibot leave`` -- turn the Mineflayer bot on and off.

The switch lives in ``config.json`` (``mineflayer_bot.enabled``) and takes effect through
``!!gamesai reload``, so this is a two-line edit plus a reload. The lock keeps two operators from
rewriting the file at the same time.

``force`` exists because the config value alone cannot describe reality: after a crash (or a
failed first launch) ``enabled`` is already ``true`` while no process runs, and after an
out-of-band start ``enabled`` may be ``false`` while one does. A plain toggle would answer
"already joined"/"already left" and do nothing about either; the commands pass ``force=True``
when the process state says the config is stale.
"""
import json, os, re
import threading

from mcdreforged.api.all import *

from ..core.config import plugin_config
from ..core.permission import require_permission

#: Serialises the read-modify-write of ``config.json`` between two `!!aibot` commands.
_aibot_lock = threading.Lock()


def _toggle_aibot(server: PluginServerInterface, enabled: bool, *, force: bool = False) -> bool:
    config_path = os.path.join(os.path.dirname(os.path.dirname(plugin_config.skills_path)), "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    current = config.get("mineflayer_bot", {}).get("enabled", False)
    if current == enabled and not force:
        return True
    config.setdefault("mineflayer_bot", {})["enabled"] = enabled
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    server.execute_command("!!gamesai reload")
    return False


def aibot_join(source: CommandSource, context: dict):
    with _aibot_lock:
        server = source.get_server()
        if not require_permission(source):
            return
        if not re.fullmatch(r'[a-zA-Z0-9_]+', plugin_config.bot_username):
            source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.aibot.invalid_bot_username', username=plugin_config.bot_username)}")
            return
        # Lazy import: the bot package pulls third-party modules, while this command module is
        # imported before the dependency gate decides whether those exist.
        from ..bot.mineflayer import is_node_running
        if is_node_running():
            server.say(f"{plugin_config.prefix}{server.rtr('games_ai.aibot.already_joined', username=plugin_config.bot_username)}")
            return
        _toggle_aibot(server, True, force=True)
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.aibot.join', username=plugin_config.bot_username)}")


def aibot_leave(source: CommandSource, context: dict):
    with _aibot_lock:
        server = source.get_server()
        if not require_permission(source):
            return
        from ..bot.mineflayer import is_node_running
        if not is_node_running():
            server.say(f"{plugin_config.prefix}{server.rtr('games_ai.aibot.already_left', username=plugin_config.bot_username)}")
            return
        _toggle_aibot(server, False, force=True)
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.aibot.leave', username=plugin_config.bot_username)}")
