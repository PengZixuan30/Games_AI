from typing import Callable
from mcdreforged.command.command_source import CommandSource

REGISTER_PLUGIN_LIST: dict[str, Callable[[CommandSource], None] | None] = {}

def register_self(plugin_id: str, reloader: Callable[[CommandSource], None] | None = None):
    """Add another MCDR plugin to the list GamesAI reloads on ``!!gamesai reload``.

    Without ``reloader`` the plugin is reloaded with MCDR's own ``reload_plugin``; with one, that
    callable runs instead and receives the command source that triggered the reload. A plugin that
    registers tools is tracked by the tool registry already and does not need this.
    """
    if plugin_id:
        if plugin_id not in REGISTER_PLUGIN_LIST.keys():
            REGISTER_PLUGIN_LIST[plugin_id] = reloader
