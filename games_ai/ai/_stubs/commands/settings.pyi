# Generated from games_ai/commands/settings.py by tools/build_tool_stubs.py -- do not edit.
from mcdreforged.api.all import *
from ..core.config import plugin_config as plugin_config
from ..core.permission import require_permission as require_permission
from _typeshed import Incomplete

class ConfigManager:
    SECRET_KEYS: Incomplete
    config: Incomplete
    config_path: Incomplete
    def __init__(self, config: dict) -> None: ...
    @classmethod
    def _mask_secrets(cls, value):
        """Recursively replace anything under a secret key with a placeholder."""
    def get_config(self, source: CommandSource, context: CommandContext): ...
    def set_config(self, source: CommandSource, context: CommandContext): ...
    def aibot_config(self, source: CommandSource, context: CommandContext): ...
