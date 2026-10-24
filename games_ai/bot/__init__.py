"""The Mineflayer bot: its Node process, the autonomous controller and the embedded ``init.js``.

This module is the package's front door. The process management and the service files need only
the standard library and MCDR, so they are eager; the autonomous controller uses the provider
client and is therefore resolved on first use (PEP 562) -- importing ``games_ai.bot`` must stay
possible while the plugin is repairing its Python packages.
"""
import importlib
from typing import TYPE_CHECKING, Any

from . import mineflayer, mineflayer_service_files
from .mineflayer import (BotPeerClient, clear_bot_peer, detach_mineflayer_process,
                         get_mineflayer_client, is_node_running, run_node, set_bot_peer,
                         stop_mineflayer_process)
from .mineflayer_service_files import get_default_init_hash, write_default_init, write_package_json

if TYPE_CHECKING:
    # What a type checker reads instead of the runtime ``__getattr__`` below; it never runs, so
    # the dependency gate is untouched (see the package docstring).
    from . import mineflayer_ai
    from .mineflayer_ai import (AutonomousBotController, CONTROLLER_THREAD_NAMES,
                                force_abort_thread, get_bot_controller, set_bot_controller)

#: Name -> the module that defines it. This module needs a third-party package.
_LAZY_NAMES = {
    "AutonomousBotController": "mineflayer_ai",
    "CONTROLLER_THREAD_NAMES": "mineflayer_ai",
    "force_abort_thread": "mineflayer_ai",
    "get_bot_controller": "mineflayer_ai",
    "set_bot_controller": "mineflayer_ai",
}
#: The same module by name: ``from .bot import mineflayer_ai``.
_LAZY_MODULES = {"mineflayer_ai"}

__all__ = [
    # the modules
    "mineflayer", "mineflayer_ai", "mineflayer_service_files",
    # the names that need nothing third-party
    "BotPeerClient", "clear_bot_peer", "detach_mineflayer_process", "get_default_init_hash",
    "get_mineflayer_client", "is_node_running", "run_node", "set_bot_peer",
    "stop_mineflayer_process", "write_default_init", "write_package_json",
    # the names that do (resolved on first use)
    "AutonomousBotController", "CONTROLLER_THREAD_NAMES", "force_abort_thread",
    "get_bot_controller", "set_bot_controller",
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
