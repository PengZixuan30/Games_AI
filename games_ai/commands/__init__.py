"""What a player or the console types: the handlers behind ``!!data``, ``!!gamesai config``,
``!!aibot``, ``!!gamesai clear`` and ``!!gamesai node``.

This module is the package's front door. The data, settings, aibot and clear handlers need only the
standard library and MCDR, so they are eager; ``node`` talks to the hub's client and is resolved on
first use (PEP 562) -- importing ``games_ai.commands`` must stay possible while the plugin repairs
its Python packages.

``clear`` and ``node`` each expose an ``attach()``, so the facade renames them: ``clear_attach``
and ``node_attach``.
"""
import importlib
from typing import TYPE_CHECKING, Any

from . import aibot, clear, data, settings
from .aibot import aibot_join, aibot_leave
from .clear import attach as clear_attach
from .clear import clear_history, clear_history_all, clear_history_named
from .data import DataManager
from .settings import ConfigManager

if TYPE_CHECKING:
    # What a type checker reads instead of the runtime ``__getattr__`` below; it never runs, so
    # the dependency gate is untouched (see the package docstring). ``node``'s ``attach`` arrives
    # under the name this package gives it.
    from . import node
    from .node import (attach as node_attach, claim, forget, issue_token, list_nodes, pending,
                       revoke, rotate, status)

#: Name -> the module that defines it. This module needs a third-party package.
_LAZY_NAMES = {
    "claim": "node",
    "forget": "node",
    "issue_token": "node",
    "list_nodes": "node",
    "pending": "node",
    "revoke": "node",
    "rotate": "node",
    "status": "node",
}
#: The same module by name: ``from .commands import node``.
_LAZY_MODULES = {"node"}
#: Names this package gives to an attribute of a lazy module: ``name -> (module, attribute)``.
_LAZY_ALIASES = {"node_attach": ("node", "attach")}

__all__ = [
    # the modules
    "aibot", "clear", "data", "node", "settings",
    # the names that need nothing third-party
    "ConfigManager", "DataManager", "aibot_join", "aibot_leave", "clear_attach", "clear_history",
    "clear_history_all", "clear_history_named",
    # the names that do (resolved on first use), with the node module's own names prefixed
    "claim", "forget", "issue_token", "list_nodes", "node_attach", "pending", "revoke", "rotate",
    "status",
]


def __getattr__(name: str) -> Any:
    """Resolve one of the third-party names on first use; anything else is a real AttributeError."""
    if name in _LAZY_MODULES:
        return importlib.import_module("." + name, __name__)
    alias = _LAZY_ALIASES.get(name)
    if alias is not None:
        alias_module, attribute = alias
        return getattr(importlib.import_module("." + alias_module, __name__), attribute)
    module_name = _LAZY_NAMES.get(name)
    if module_name is None:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    return getattr(importlib.import_module("." + module_name, __name__), name)


def __dir__() -> list:
    return sorted(set(globals()) | set(_LAZY_ALIASES) | set(_LAZY_NAMES) | _LAZY_MODULES)
