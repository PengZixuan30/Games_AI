"""The plugin's source as text: one module at a time, or the whole package concatenated.

A layout check has to ask the right question. *"The entry module owns PLUGIN_METADATA"* is about
one file, so it reads :func:`module_text` for ``"__init__.py"``. *"The plugin defines X somewhere"*
is about the package, so it reads :func:`package_text` -- that stays true when a symbol moves to
another module, while a symbol that disappears entirely still fails the check.

The package is a tree of subpackages (``core/``, ``commands/``, ``cluster/``, ``ai/``, ``bot/``,
``update/``, ``ui/``), so every path here is relative to ``games_ai/`` and written with forward
slashes: ``"cluster/cross_server.py"``.
"""
import os

from _helpers.paths import PKG

_BANNER = "# ==== games_ai/{} ====\n"


def module_names() -> list:
    """Every Python module of the package, sorted, as paths relative to the package root."""
    out = []
    for folder, folders, names in os.walk(PKG):
        folders[:] = sorted(name for name in folders if name != "__pycache__")
        for name in sorted(names):
            if name.endswith(".py"):
                out.append(os.path.relpath(os.path.join(folder, name), PKG).replace(os.sep, "/"))
    return sorted(out)


def resolve(name: str) -> str:
    """The relative path of one module, however a test names it.

    ``"__init__.py"`` and ``"cluster/cross_server.py"`` are paths; ``"cross_server"`` and
    ``"cluster.cross_server"`` are module names. A bare file name is looked up across the tree and
    has to be unique -- two modules of the same name would make a check ambiguous, which is an
    error here rather than a coin flip.
    """
    wanted = name.replace("\\", "/")
    if wanted.endswith(".py") and wanted in module_names():
        return wanted
    dotted = wanted[:-3] if wanted.endswith(".py") else wanted
    if dotted.startswith("games_ai."):
        dotted = dotted[len("games_ai."):]
    candidate = dotted.replace(".", "/") + ".py"
    if candidate in module_names():
        return candidate
    matches = [path for path in module_names()
               if os.path.basename(path) in (wanted, dotted + ".py")]
    if len(matches) == 1:
        return matches[0]
    raise KeyError("{} is not one module of games_ai/: {}".format(name, matches or module_names()))


def module_file(dotted: str) -> str | None:
    """The file a *written-down* dotted name (``games_ai.ai.games_ai_tool``) points at, or None.

    :func:`resolve` accepts a bare file name, because a layout check may ask "where is help.py".
    A path somebody wrote into a document or a generated file is a different question: it has to
    be exactly where it says. Falling back to a unique file name would quietly accept
    ``games_ai.games_ai_tool`` after the module moved into ``ai/``, which is the drift these
    checks exist for. The package itself (``games_ai``, ``games_ai.ai``) is its ``__init__.py``.
    """
    inside = dotted[len("games_ai."):] if dotted.startswith("games_ai.") else dotted
    parts = [] if dotted in ("games_ai", "") else inside.split(".")
    base = os.path.join(PKG, *parts)
    for candidate in (base + ".py", os.path.join(base, "__init__.py")):
        if os.path.isfile(candidate):
            return os.path.relpath(candidate, PKG).replace(os.sep, "/")
    return None


def module_text(name: str) -> str:
    """The source of one module, by relative path, module name or unique file name."""
    with open(os.path.join(PKG, resolve(name).replace("/", os.sep)), encoding="utf-8") as handle:
        return handle.read()


def package_text() -> str:
    """Every module's source, each one introduced by a ``# ==== games_ai/<path> ====`` banner.

    The banner keeps a match attributable to a file while a plain substring search still means
    "this exists in the plugin".
    """
    return "\n".join(_BANNER.format(name) + module_text(name) for name in module_names())
