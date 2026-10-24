# Generated from games_ai/commands/aibot.py by tools/build_tool_stubs.py -- do not edit.
from mcdreforged.api.all import *
from ..core.config import plugin_config as plugin_config
from ..core.permission import require_permission as require_permission
from _typeshed import Incomplete

_aibot_lock: Incomplete

def _toggle_aibot(server: PluginServerInterface, enabled: bool, *, force: bool = False) -> bool: ...
def aibot_join(source: CommandSource, context: dict): ...
def aibot_leave(source: CommandSource, context: dict): ...
