"""``!!data ...`` -- the shared public database, one command per operation.

The commands run where the AI runs (``ROUTE_SERVER``): in a cluster they always reach the hub's
database, whichever instance was typed into. The manager is built once per load from
``plugin_config.data_path``, which the entry module passes in because a reload can move the file;
the actual connection is the plugin-lifetime singleton from :mod:`games_ai.core.database`
(``database.public_database()``), so every caller -- these commands, the AI tools and their
read-modify-write appends -- is serialised through one locked connection.
"""
from mcdreforged.api.all import *

from ..core import database
from ..core.config import plugin_config
from ..core.permission import require_permission


class DataManager:
    def __init__(self, db_path: str):
        self.db_path = db_path

    @property
    def db(self):
        """The plugin's one public-database connection (opened by ``on_load``)."""
        return database.public_database()

    @new_thread("games_ai@data_write")
    def write_data(self, source: CommandSource, context: dict):
        server = source.get_server()
        if not require_permission(source):
            return
        key = context.get("key")
        value = context.get("value")
        self.db.write_data(key, value)
        return source.reply(f'{plugin_config.prefix}{server.rtr("games_ai.data.write_message.success",key=key,value=value)}')
        
    @new_thread("games_ai@data_add")
    def add_data(self, source: CommandSource, context: dict):
        server = source.get_server()
        if not require_permission(source):
            return
        key = context.get("key")
        value = context.get("value")
        # Atomic read-append-write: two concurrent `!!data add` (or one of them racing an AI
        # `add_data` tool call) both land instead of the later write dropping the earlier append.
        new_value = self.db.append(key, value)
        return source.reply(f'{plugin_config.prefix}{server.rtr("games_ai.data.add_message.success", key=key, value=new_value)}')

    @new_thread("games_ai@data_del")
    def del_data(self, source: CommandSource, context: dict):
        server = source.get_server()
        if not require_permission(source):
            return
        key = context.get("key")
        self.db.delete_data(key)
        return source.reply(f'{plugin_config.prefix}{server.rtr("games_ai.data.del_message.success",key=key)}')

    @new_thread("games_ai@data_read")
    def read_data(self, source: CommandSource, context: dict):
        server = source.get_server()
        if not require_permission(source):
            return
        key = context.get("key")
        value = self.db.read_data(key)
        if value is None:
            return source.reply(f'{plugin_config.prefix}{server.rtr("games_ai.data.read_message.no_key",key=key)}')
        else:
            message_part = RTextList(
                plugin_config.prefix,
                server.rtr("games_ai.data.read_message.success",key=key,value=value),
                "\n",
                RText(server.rtr("games_ai.data.read_message.write_button"), RColor.gray).h(server.rtr("games_ai.data.read_message.write_hover")).c(RAction.suggest_command, f"!!data write {key} {value}"),
                "  OR  ",
                RText(server.rtr("games_ai.data.read_message.copy_button"), RColor.blue).h(server.rtr("games_ai.data.read_message.copy_hover")).c(RAction.copy_to_clipboard, value)
            )
            return source.reply(message_part)

    @new_thread("games_ai@data_list")
    def read_data_list(self, source: CommandSource, context: dict):
        server = source.get_server()
        if not require_permission(source):
            return
        value = self.db.data_list()
        return source.reply(f'{plugin_config.prefix}{server.rtr("games_ai.data.read_list_message")}\n{value}')

    @new_thread("games_ai@data_keys")
    def read_all_keys(self, source: CommandSource, context: dict):
        server = source.get_server()
        if not require_permission(source):
            return
        keys = self.db.get_all_key()
        return source.reply(f'{plugin_config.prefix}{server.rtr("games_ai.data.read_keys_message")}\n{keys}')

    def ask_ai_read_data(self) -> list[tuple[str, str]]:
        value = self.db.data_list()
        return value
