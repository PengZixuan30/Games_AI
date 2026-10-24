"""The foundation every other package imports: settings, logging, the dependency gate, the
permission rule and the storage.

This module is the package's front door: the entry module imports what it needs from here instead
of from the individual modules. Nothing in this package needs a third-party package, so every name
below is imported eagerly -- see ``games_ai/cluster/__init__.py`` for the lazy half of the rule.
"""
from . import clock, config, database, deps, logger, permission
from .config import SyncPluginConfig, plugin_config
from .database import (ChatHistoryStore, PublicDatabase, close_public_database,
                       open_public_database, public_database)
from .permission import (TOOL_DENIED_LEVEL, TOOL_DENIED_NOT_ALLOWED, has_permission,
                         require_permission)

__all__ = [
    # the modules
    "clock", "config", "database", "deps", "logger", "permission",
    # the names
    "SyncPluginConfig", "plugin_config", "ChatHistoryStore", "PublicDatabase",
    "open_public_database", "public_database", "close_public_database",
    "TOOL_DENIED_LEVEL", "TOOL_DENIED_NOT_ALLOWED", "has_permission", "require_permission",
]
