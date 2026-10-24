"""The in-game help texts: ``!!gamesai``, the bare ``!!ask`` and every per-command hint.

Each method is a table of "which localized line for which command": :func:`send_help` builds one
chat line from a ``games_ai.gamesai_help_message.*`` key, and the class groups them per command
group. The entry module only registers these handlers, so this module deliberately imports
nothing from :mod:`games_ai` -- the version the greeting prints is read back from MCDR through
:func:`plugin_version`, not from a literal kept in the entry module.
"""
from mcdreforged.api.all import *

from ..core.config import plugin_config
from ..core.permission import has_permission, require_permission

#: This plugin's id, used to read its own metadata back from MCDR.
_PLUGIN_ID = "games_ai"


def plugin_version(server: ServerInterface) -> str:
    """The version MCDR loaded for this plugin, or ``?`` when it cannot be read.

    ``get_plugin_metadata()`` is on the plain ``ServerInterface`` that every command source hands
    out (player, console and plugin sources alike), which is why the help text does not need the
    ``PLUGIN_METADATA`` literal of the entry module.
    """
    try:
        metadata = server.get_plugin_metadata(_PLUGIN_ID)
    except Exception:
        return "?"
    return str(metadata.version) if metadata is not None else "?"


class gamesai_help:
    """One static method per command group; each prints its lines through :func:`send_help`."""

    @staticmethod
    def ask_help(source: CommandSource):
        server = source.get_server()
        send_help(source, message=server.rtr("games_ai.gamesai_help_message.greeting", v=plugin_version(server)))
        send_help(source, command="!!ask <content>", command_help_key="games_ai.gamesai_help_message.ask_help")
        send_help(source, command="!!ask -n <content>", command_help_key="games_ai.gamesai_help_message.ask_no_history_help")
        send_help(source, command="!!ask -f <content>", command_help_key="games_ai.gamesai_help_message.ask_force_help")
        send_help(source, command="!!ask switch <model>", command_help_key="games_ai.gamesai_help_message.switch_help")
        send_help(source, command="!!ask compact", command_help_key="games_ai.gamesai_help_message.ask_compact_help")
        send_help(source, command="!!ask context <player>", command_help_key="games_ai.gamesai_help_message.ask_context_help")
        send_help(source, command="!!ask context --all", command_help_key="games_ai.gamesai_help_message.ask_context_all_help")
        send_help(source, command="!!ask stop", command_help_key="games_ai.gamesai_help_message.ask_stop_help")
        send_help(source, message=server.rtr("games_ai.gamesai_help_message.all_ai_model") + str(list(plugin_config.all_ai.keys())))

    @staticmethod
    def switch_help(source: CommandSource):
        server = source.get_server()
        send_help(source, message=server.rtr("games_ai.gamesai_help_message.greeting", v=plugin_version(server)))
        send_help(source, command="!!ask switch <model>", command_help_key="games_ai.gamesai_help_message.switch_help")

    @staticmethod
    def data_help(source: CommandSource):
        server = source.get_server()
        if not require_permission(source):
            return
        send_help(source, message=server.rtr("games_ai.gamesai_help_message.greeting", v=plugin_version(server)))
        send_help(source, command="!!data write <key> <value>", command_help_key="games_ai.gamesai_help_message.data_write_help")
        send_help(source, command="!!data add <key> <value>", command_help_key="games_ai.gamesai_help_message.data_add_help")
        send_help(source, command="!!data del <key>", command_help_key="games_ai.gamesai_help_message.data_del_help")
        send_help(source, command="!!data read <key>", command_help_key="games_ai.gamesai_help_message.data_read_help")
        send_help(source, command="!!data list", command_help_key="games_ai.gamesai_help_message.data_list_help")
        send_help(source, command="!!data list keys", command_help_key="games_ai.gamesai_help_message.data_keys_help")

    @staticmethod
    def data_write_help(source: CommandSource):
        server = source.get_server()
        if not require_permission(source):
            return
        send_help(source, message=server.rtr("games_ai.gamesai_help_message.greeting", v=plugin_version(server)))
        send_help(source, command="!!data write <key> <value>", command_help_key="games_ai.gamesai_help_message.data_write_help")

    @staticmethod
    def data_del_help(source: CommandSource):
        server = source.get_server()
        if not require_permission(source):
            return
        send_help(source, message=server.rtr("games_ai.gamesai_help_message.greeting", v=plugin_version(server)))
        send_help(source, command="!!data del <key>", command_help_key="games_ai.gamesai_help_message.data_del_help")

    @staticmethod
    def data_read_help(source: CommandSource):
        server = source.get_server()
        if not require_permission(source):
            return
        send_help(source, message=server.rtr("games_ai.gamesai_help_message.greeting", v=plugin_version(server)))
        send_help(source, command="!!data read <key>", command_help_key="games_ai.gamesai_help_message.data_read_help")

    @staticmethod
    def data_add_help(source: CommandSource):
        server = source.get_server()
        if not require_permission(source):
            return
        send_help(source, message=server.rtr("games_ai.gamesai_help_message.greeting", v=plugin_version(server)))
        send_help(source, command="!!data add <key> <value>", command_help_key="games_ai.gamesai_help_message.data_add_help")


    @staticmethod
    def config_help(source: CommandSource):
        server = source.get_server()
        send_help(source, message=server.rtr("games_ai.gamesai_help_message.greeting", v=plugin_version(server)))
        if not require_permission(source):
            return
        send_help(source, command='!!gamesai config get <key>', command_help_key="games_ai.gamesai_help_message.config_help_get")
        send_help(source, command='!!gamesai config set <key> <value>', command_help_key="games_ai.gamesai_help_message.config_help_set")


    @staticmethod
    def aibot_help(source: CommandSource):
        server = source.get_server()
        send_help(source, message=server.rtr("games_ai.gamesai_help_message.greeting", v=plugin_version(server)))
        if not require_permission(source):
            return
        send_help(source, command="!!aibot join", command_help_key="games_ai.gamesai_help_message.aibot_join_help")
        send_help(source, command="!!aibot leave", command_help_key="games_ai.gamesai_help_message.aibot_leave_help")
        send_help(source, command="!!aibot set <key> <value>", command_help_key="games_ai.gamesai_help_message.aibot_set_help")

    @staticmethod
    def node_help(source: CommandSource):
        """The `!!gamesai node` group: hub side first, then the node's own commands."""
        server = source.get_server()
        send_help(source, message=server.rtr("games_ai.gamesai_help_message.greeting", v=plugin_version(server)))
        if not require_permission(source):
            return
        send_help(source, message=server.rtr("games_ai.gamesai_help_message.node_help_hub"))
        send_help(source, command="!!gamesai node pending", command_help_key="games_ai.gamesai_help_message.node_pending_help")
        send_help(source, command="!!gamesai node token <name>", command_help_key="games_ai.gamesai_help_message.node_token_help")
        send_help(source, command="!!gamesai node list", command_help_key="games_ai.gamesai_help_message.node_list_help")
        send_help(source, command="!!gamesai node revoke <name>", command_help_key="games_ai.gamesai_help_message.node_revoke_help")
        send_help(source, command="!!gamesai node rotate <name>", command_help_key="games_ai.gamesai_help_message.node_rotate_help")
        send_help(source, message=server.rtr("games_ai.gamesai_help_message.node_help_node"))
        send_help(source, command="!!gamesai node claim <token>", command_help_key="games_ai.gamesai_help_message.node_claim_help")
        send_help(source, command="!!gamesai node status", command_help_key="games_ai.gamesai_help_message.node_status_help")
        send_help(source, command="!!gamesai node forget", command_help_key="games_ai.gamesai_help_message.node_forget_help")


    @staticmethod
    def all_help(source: CommandSource):
        server = source.get_server()
        send_help(source, message=server.rtr("games_ai.gamesai_help_message.greeting", v=plugin_version(server)))
        send_help(source, command="!!ask <content>", command_help_key="games_ai.gamesai_help_message.ask_help")
        send_help(source, command="!!gamesai clear", command_help_key="games_ai.gamesai_help_message.clear_help")
        if has_permission(source):
            send_help(source, command="!!gamesai clear <name>", command_help_key="games_ai.gamesai_help_message.clear_other_help")
            send_help(source, command="!!gamesai clearall", command_help_key="games_ai.gamesai_help_message.clearall_help")
            send_help(source, command="!!gamesai check", command_help_key="games_ai.gamesai_help_message.check_update_help")
            send_help(source, command='!!gamesai config',command_help_key="games_ai.gamesai_help_message.config_help")
            send_help(source, command="!!gamesai node", command_help_key="games_ai.gamesai_help_message.node_group_help")
            send_help(source, command="!!data", command_help_key="games_ai.gamesai_help_message.data_help")
            send_help(source, command="!!aibot <join | leave>", command_help_key="games_ai.gamesai_help_message.aibot_help")


def send_help(source: CommandSource, message: str|None = None, command: str|None = None, command_help_key: str|None = None):
    """One help line: the command itself (clickable to fill it in) or a free-form message."""
    server = source.get_server()
    if command and message is None:
        source.reply(RTextList(
            plugin_config.prefix,
            server.rtr("games_ai.gamesai_help_message.help_prefix"),
            RText(command, RColor.gray).c(RAction.suggest_command, command[:command.find(' <')] + ' ' if ' <' in command else command + ' '),
            server.rtr(command_help_key)
        ))
        return
    else:
        source.reply(RTextList(
            plugin_config.prefix,
            message,
        ))
        return
