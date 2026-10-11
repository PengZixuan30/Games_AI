# Generated from games_ai/ai/register_extra_plugin.py by tools/build_tool_stubs.py -- do not edit.
from mcdreforged.command.command_source import CommandSource as CommandSource
from typing import Callable

REGISTER_PLUGIN_LIST: dict[str, Callable[[CommandSource], None] | None]

def register_self(plugin_id: str, reloader: Callable[[CommandSource], None] | None = None):
    """Add another MCDR plugin to the list GamesAI reloads on ``!!gamesai reload``.

    Without ``reloader`` the plugin is reloaded with MCDR's own ``reload_plugin``; with one, that
    callable runs instead and receives the command source that triggered the reload. A plugin that
    registers tools is tracked by the tool registry already and does not need this.
    """
