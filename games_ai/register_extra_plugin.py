from typing import Callable
from mcdreforged.command.command_source import CommandSource

REGISTER_PLUGIN_LIST: dict[str, Callable[[CommandSource], None] | None] = {}

def register_self(plugin_id: str, reloader: Callable[[CommandSource], None] | None = None):
    if plugin_id:
        if plugin_id not in REGISTER_PLUGIN_LIST.keys():
            REGISTER_PLUGIN_LIST[plugin_id] = reloader
