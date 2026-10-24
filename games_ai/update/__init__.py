"""Self-update: the download/verify/replace logic and the 24 h check that drives it.

This module is the package's front door. Both of its modules need a third-party package
(``requests``), so nothing is eager here: the names and the modules resolve on first use
(PEP 562), which keeps the rule uniform -- no package ``__init__.py`` imports a third-party
package, whenever it happens to be imported.

The ``attach`` name belongs to ``update_round``; ``updater`` has no such function.
"""
import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # What a type checker reads instead of the runtime ``__getattr__`` below; it never runs, so
    # the dependency gate is untouched (see the package docstring).
    from . import update_round, updater
    from .update_round import (attach, check_update, cyclic_check_updates, get_main_version,
                               self_update, stop_timer, unload_status, update)
    from .updater import (ReleaseInfo, prepare, release_from_entry, run_self_update,
                          self_archive_path)

#: Name -> the module that defines it. Both modules need a third-party package.
_LAZY_NAMES = {
    "ReleaseInfo": "updater",
    "prepare": "updater",
    "release_from_entry": "updater",
    "run_self_update": "updater",
    "self_archive_path": "updater",
    "attach": "update_round",
    "check_update": "update_round",
    "cyclic_check_updates": "update_round",
    "get_main_version": "update_round",
    "self_update": "update_round",
    "stop_timer": "update_round",
    "unload_status": "update_round",
    "update": "update_round",
}
#: The modules by name: ``from .update import update_round``.
_LAZY_MODULES = {"updater", "update_round"}

__all__ = [
    # the modules
    "update_round", "updater",
    # the names, all resolved on first use
    "ReleaseInfo", "attach", "check_update", "cyclic_check_updates", "get_main_version",
    "prepare", "release_from_entry", "run_self_update", "self_archive_path", "self_update",
    "stop_timer", "unload_status", "update",
]


def __getattr__(name: str) -> Any:
    """Resolve one of the lazy names on first use; anything else is a real AttributeError."""
    if name in _LAZY_MODULES:
        return importlib.import_module("." + name, __name__)
    module_name = _LAZY_NAMES.get(name)
    if module_name is None:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    return getattr(importlib.import_module("." + module_name, __name__), name)


def __dir__() -> list:
    return sorted(set(globals()) | set(_LAZY_NAMES) | _LAZY_MODULES)
