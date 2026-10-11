# Generated from games_ai/ui/help.py by tools/build_tool_stubs.py -- do not edit.
from mcdreforged.api.all import *
from ..core.config import plugin_config as plugin_config
from ..core.permission import has_permission as has_permission, require_permission as require_permission

_PLUGIN_ID: str

def plugin_version(server: ServerInterface) -> str:
    """The version MCDR loaded for this plugin, or ``?`` when it cannot be read.

    ``get_plugin_metadata()`` is on the plain ``ServerInterface`` that every command source hands
    out (player, console and plugin sources alike), which is why the help text does not need the
    ``PLUGIN_METADATA`` literal of the entry module.
    """

class gamesai_help:
    """One static method per command group; each prints its lines through :func:`send_help`."""
    @staticmethod
    def ask_help(source: CommandSource): ...
    @staticmethod
    def switch_help(source: CommandSource): ...
    @staticmethod
    def data_help(source: CommandSource): ...
    @staticmethod
    def data_write_help(source: CommandSource): ...
    @staticmethod
    def data_del_help(source: CommandSource): ...
    @staticmethod
    def data_read_help(source: CommandSource): ...
    @staticmethod
    def data_add_help(source: CommandSource): ...
    @staticmethod
    def config_help(source: CommandSource): ...
    @staticmethod
    def aibot_help(source: CommandSource): ...
    @staticmethod
    def node_help(source: CommandSource):
        """The `!!gamesai node` group: hub side first, then the node's own commands."""
    @staticmethod
    def all_help(source: CommandSource): ...

def send_help(source: CommandSource, message: str | None = None, command: str | None = None, command_help_key: str | None = None):
    """One help line: the command itself (clickable to fill it in) or a free-form message."""
