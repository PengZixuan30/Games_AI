"""The plugin's source as text: one module at a time, or the whole package concatenated.

A layout check has to ask the right question. *"The entry module owns PLUGIN_METADATA"* is about
one file, so it reads :func:`module_text` for ``__init__.py``. *"The plugin defines X somewhere"*
is about the package, so it reads :func:`package_text` -- that stays true when a symbol moves to
another module, while a symbol that disappears entirely still fails the check.
"""
import os

from _helpers.paths import PKG

_BANNER = "# ==== games_ai/{} ====\n"


def module_names() -> list:
    """Every Python module of the package, sorted, as plain file names."""
    return sorted(name for name in os.listdir(PKG) if name.endswith(".py"))


def module_text(name: str) -> str:
    """The source of one module, by file name (``"__init__.py"``) or module name (``"help"``)."""
    if not name.endswith(".py"):
        name += ".py"
    with open(os.path.join(PKG, name), encoding="utf-8") as handle:
        return handle.read()


def package_text() -> str:
    """Every module's source, each one introduced by a ``# ==== games_ai/<file> ====`` banner.

    The banner keeps a match attributable to a file while a plain substring search still means
    "this exists in the plugin".
    """
    return "\n".join(_BANNER.format(name) + module_text(name) for name in module_names())
