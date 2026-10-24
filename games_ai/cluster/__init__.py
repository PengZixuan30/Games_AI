"""Talking to the other instances: the role decision, the hub, the node client, the remote
command source and the update round that runs across them.

This module is the package's front door. The remote command source (``ws_command``) speaks the
protocol with the standard library and MCDR only, so it is eager; ``cross_server``,
``websockets_client`` and ``websockets_server`` need ``websockets`` and are resolved on first use
(PEP 562) -- importing ``games_ai.cluster`` must stay possible while the plugin repairs its Python
packages.

Two names exist in both websocket modules: ``APP_ID``, ``APP_ID_BOT`` and ``token_fingerprint``
resolve to the **client** copy here (the one the entry module uses); the server's same-named
constants stay reachable as ``games_ai.cluster.websockets_server.<name>``.
"""
import importlib
from typing import TYPE_CHECKING, Any

from . import ws_command
from .ws_command import (REMOTE_CONSOLE_LEVEL, ROUTE_CLUSTER, ROUTE_LOCAL, ROUTE_SERVER,
                         SessionRegistry, WebSocketCommandSource, decode_text, encode_text)

if TYPE_CHECKING:
    # What a type checker reads instead of the runtime ``__getattr__`` below; it never runs, so
    # the dependency gate is untouched (see the package docstring). The duplicated names are
    # declared once, from the same module the runtime resolves them from.
    from . import cross_server, websockets_client, websockets_server
    from .cross_server import MODE_CLIENT, MODE_LOCAL, MODE_SERVER, CrossServerManager
    from .websockets_client import (APP_ID, APP_ID_BOT, PROBE_GAMES_AI, PROBE_UNREACHABLE,
                                    CrossServerNode, probe_hub_detail, token_fingerprint)
    from .websockets_server import CrossServerHub, is_port_available

#: Name -> the module that defines it. These modules need a third-party package.
_LAZY_NAMES = {
    "MODE_CLIENT": "cross_server",
    "MODE_LOCAL": "cross_server",
    "MODE_SERVER": "cross_server",
    "CrossServerManager": "cross_server",
    "APP_ID": "websockets_client",
    "APP_ID_BOT": "websockets_client",
    "PROBE_GAMES_AI": "websockets_client",
    "PROBE_UNREACHABLE": "websockets_client",
    "CrossServerNode": "websockets_client",
    "probe_hub_detail": "websockets_client",
    "token_fingerprint": "websockets_client",
    "CrossServerHub": "websockets_server",
    "is_port_available": "websockets_server",
}
#: The same modules by name: ``from .cluster import cross_server``.
_LAZY_MODULES = {"cross_server", "websockets_client", "websockets_server"}

__all__ = [
    # the modules
    "cross_server", "websockets_client", "websockets_server", "ws_command",
    # the names that need nothing third-party
    "REMOTE_CONSOLE_LEVEL", "ROUTE_CLUSTER", "ROUTE_LOCAL", "ROUTE_SERVER", "SessionRegistry",
    "WebSocketCommandSource", "decode_text", "encode_text",
    # the names that do (resolved on first use)
    "APP_ID", "APP_ID_BOT", "CrossServerHub", "CrossServerManager", "CrossServerNode",
    "MODE_CLIENT", "MODE_LOCAL", "MODE_SERVER", "PROBE_GAMES_AI", "PROBE_UNREACHABLE",
    "is_port_available", "probe_hub_detail", "token_fingerprint",
]


def __getattr__(name: str) -> Any:
    """Resolve one of the third-party names on first use; anything else is a real AttributeError."""
    if name in _LAZY_MODULES:
        return importlib.import_module("." + name, __name__)
    module_name = _LAZY_NAMES.get(name)
    if module_name is None:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    return getattr(importlib.import_module("." + module_name, __name__), name)


def __dir__() -> list:
    return sorted(set(globals()) | set(_LAZY_NAMES) | _LAZY_MODULES)
