"""The pre-0.8.0 import paths of the plugin's documented modules.

The released docs told third-party code to import three modules from the flat package:
``games_ai.games_ai_tool`` (the tool registry), ``games_ai.register_extra_plugin`` (hot-reload
registration) and ``games_ai.external_skills_loader`` (skill injection). The subpackage split moved
all three into ``ai/``, so ``games_ai/<name>.py`` is now a compatibility module that re-exports the
real module's public names -- the very same objects, which is what makes a legacy file land in the
one registry/list the plugin reads -- and nothing inside the package imports them.

``tests/test_tool_compat.py`` keeps the registry-specific half (a legacy ``tools.py`` really loads
and registers into the one registry). This suite pins the shared contract for all three paths: the
exact public surface, as the same objects, old hot-reload and skills code reaching the shared
state, and the package itself never importing a legacy path.
"""
import ast
import importlib
import os

import pytest

from _helpers.paths import PKG

# legacy module file -> the real module it re-exports, both relative to games_ai/
LEGACY_MODULES = {
    "games_ai_tool.py": "ai/games_ai_tool.py",
    "register_extra_plugin.py": "ai/register_extra_plugin.py",
    "external_skills_loader.py": "ai/external_skills_loader.py",
}
LEGACY_PATHS = {"games_ai." + legacy[:-3].replace(os.sep, ".") for legacy in LEGACY_MODULES}


def module_name(relative):
    """``"ai/register_extra_plugin.py"`` -> ``"games_ai.ai.register_extra_plugin"``."""
    return "games_ai." + relative[:-3].replace("/", ".")


def public_surface(path):
    """The public names a module defines itself: functions, classes and assignments, minus what
    it only imported from somewhere else (``CommandSource``, ``plugin_config`` and friends are
    not part of a module's own surface)."""
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported.add(alias.asname or alias.name)

    defined = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            defined |= {target.id for target in node.targets if isinstance(target, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
    return {name for name in defined - imported if not name.startswith("_")}


@pytest.mark.parametrize("legacy_file", sorted(LEGACY_MODULES))
def test_a_legacy_path_exposes_the_whole_public_surface_of_its_real_module(legacy_file):
    """The old path shows what the real module defines, and shows the same objects.

    None of the old modules had an ``__all__``, so everything public in them was reachable; an old
    plugin may use any of those names. Requiring the two sets to be equal keeps a name added to the
    real module from silently staying missing on the legacy path, and the identity check keeps the
    two paths from becoming two registries.
    """
    legacy = importlib.import_module(module_name(legacy_file))
    real = importlib.import_module(module_name(LEGACY_MODULES[legacy_file]))
    expected = public_surface(os.path.join(PKG, LEGACY_MODULES[legacy_file].replace("/", os.sep)))
    exposed = {name for name in dir(legacy) if not name.startswith("_")}

    assert exposed == expected, (
        f"missing from {module_name(legacy_file)}: {sorted(expected - exposed)}, "
        f"extra: {sorted(exposed - expected)}")
    for name in sorted(expected):
        assert getattr(legacy, name) is getattr(real, name), \
            f"{module_name(legacy_file)}.{name} is the same object as {module_name(LEGACY_MODULES[legacy_file])}.{name}"


def test_a_plugin_written_against_the_old_hot_reload_path_registers_itself():
    """A plugin's ``on_load`` may keep importing ``register_self`` from the flat path."""
    from games_ai import register_extra_plugin as legacy
    from games_ai.ai import register_extra_plugin as real

    def custom_reloader(source):
        raise AssertionError("not invoked here")

    try:
        legacy.register_self("legacy-path-test-plugin", custom_reloader)
        assert real.REGISTER_PLUGIN_LIST["legacy-path-test-plugin"] is custom_reloader, \
            "...and the reload list of the real module is the one it was added to"
    finally:
        real.REGISTER_PLUGIN_LIST.pop("legacy-path-test-plugin", None)


def test_a_plugin_written_against_the_old_skills_path_injects_a_skill():
    """A plugin's ``on_load`` may keep importing ``register_skills`` from the flat path."""
    from games_ai import external_skills_loader as legacy
    from games_ai.ai import external_skills_loader as real

    try:
        legacy.register_skills("legacy-path.md", "injected the old way", "the skill content")
        assert real.read_external_skills("legacy-path.md") == "the skill content", \
            "...and the real lookup serves the skill the old path injected"
        assert any(item.get("file") == "legacy-path.md" for item in real.EXTERNAL_SKILLS_LIST), \
            "...from the one list the AI reads"
    finally:
        real.EXTERNAL_SKILLS_LIST[:] = [
            item for item in real.EXTERNAL_SKILLS_LIST if item.get("file") != "legacy-path.md"]


def imported_modules(relative, tree):
    """Every module one file imports, as an absolute dotted name with its line number.

    Relative imports are resolved against the file's own package, so ``from .games_ai_tool``
    inside ``ai/`` is the real module (``games_ai.ai.games_ai_tool``) and only the entry package's
    own level spells the legacy path.
    """
    parts = [part for part in os.path.dirname(relative).replace(os.sep, "/").split("/") if part]
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(alias.name, node.lineno) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if not node.level:
                found.append((node.module or "", node.lineno))
                continue
            up = node.level - 1
            if up > len(parts):
                continue
            base = parts[:len(parts) - up]
            found.append((".".join(["games_ai"] + base + ([node.module] if node.module else [])),
                          node.lineno))
    return found


def test_the_package_itself_does_not_import_a_legacy_path():
    """The compat modules are for code outside the plugin; the plugin uses the real paths.

    An internal import would turn a compatibility promise into a dependency: an old path could no
    longer be removed or rewritten without touching the plugin itself (and the pre-gate closure
    would grow a module nothing needs).
    """
    offenders = []
    for folder, folders, names in os.walk(PKG):
        folders[:] = [name for name in folders if name != "__pycache__"]
        for name in sorted(names):
            if not name.endswith(".py"):
                continue
            relative = os.path.relpath(os.path.join(folder, name), PKG).replace(os.sep, "/")
            if relative in LEGACY_MODULES:
                continue
            with open(os.path.join(folder, name), encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            offenders += ["{}:{}".format(relative, line)
                          for module, line in imported_modules(relative, tree)
                          if module in LEGACY_PATHS]

    assert not offenders, f"only outside code uses the legacy paths: {offenders}"
