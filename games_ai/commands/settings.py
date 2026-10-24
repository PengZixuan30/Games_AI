"""``!!gamesai config get/set`` and ``!!aibot set`` -- edit ``config.json`` from the game.

Both commands touch the same file (``config.json`` next to the plugin data folder) and both end
with ``!!gamesai reload``, so they share one manager. The runtime settings singleton lives in
``games_ai/core/config.py``; this module only edits the file that feeds it.
"""
import json, os, re

from mcdreforged.api.all import *

from ..core.config import plugin_config
from ..core.permission import require_permission


class ConfigManager:
    #: Keys whose value is a secret: `config get` shows a placeholder instead of the value.
    #: `websocket.token` no longer exists in the schema, but a stale key in the file must not
    #: be echoed either, so the mask is applied to whatever the file happens to contain.
    SECRET_KEYS = ("token", "password", "api_key")

    def __init__(self, config: dict):
        self.config = config
        self.config_path = os.path.join(os.path.dirname(os.path.dirname(plugin_config.skills_path)), "config.json")

    @classmethod
    def _mask_secrets(cls, value):
        """Recursively replace anything under a secret key with a placeholder."""
        if isinstance(value, dict):
            return {key: ("<masked>" if str(key).lower() in cls.SECRET_KEYS
                          else cls._mask_secrets(item))
                    for key, item in value.items()}
        if isinstance(value, list):
            return [cls._mask_secrets(item) for item in value]
        return value

    def get_config(self, source: CommandSource, context: CommandContext):
        server = source.get_server()
        if not require_permission(source):
            return

        config_key = context.get("key")
        if config_key is None:
            source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.config_manager.no_key')}")
            return
        with open(self.config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        content = config.get(config_key)
        if content is None:
            source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.config_manager.key_not_found', key=config_key)}")
            return
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.config_manager.get_success', key=config_key, value=json.dumps(self._mask_secrets(content), ensure_ascii=False, indent=2))}")
        return


    def set_config(self, source: CommandSource, context: CommandContext):
        server = source.get_server()
        if not require_permission(source):
            return

        config_key = context.get("key")
        new_value = context.get("value")
        if config_key is None or new_value is None:
            source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.config_manager.missing_args')}")
            return
        if config_key in ("all_ai", "mineflayer_bot"):
            source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.config_manager.complex_key_denied', key=config_key)}")
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
                source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.config_manager.type_mismatch', key=config_key, old_type=type(old_value).__name__, new_type=type(parsed_value).__name__)}")
                return

        config[config_key] = parsed_value
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.config_manager.set_success', key=config_key, value=new_value)}")
        server.execute_command("!!gamesai reload")
        return


    def aibot_config(self, source: CommandSource, context: CommandContext):
        server = source.get_server()
        if not require_permission(source):
            return

        config_key = context.get("key")
        config_value = context.get("value")
        if config_key is None or config_value is None:
            source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.config_manager.missing_args')}")
            return
        if config_key not in ("username", "password", "auth"):
            source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.aibot.invalid_key', key=config_key)}")
            return

        if config_key in ("username", "password"):
            if not re.fullmatch(r'[a-zA-Z0-9_]+', config_value):
                source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.aibot.invalid_format', key=config_key)}")
                return
        if config_key == "auth" and config_value not in ("microsoft", "mojang", "offline"):
            source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.aibot.invalid_auth')}")
            return

        with open(self.config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        bot_section = config.setdefault("mineflayer_bot", {}).setdefault("bot", {})
        bot_section[config_key] = config_value

        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.aibot.set_success', key=config_key, value=config_value)}")
        server.execute_command("!!gamesai reload")
        return
