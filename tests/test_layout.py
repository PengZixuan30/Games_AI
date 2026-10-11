"""The shape of the plugin package and of this test suite: which modules exist, who may import
what, and the file-level conventions the repository holds.

This suite is deliberately independent of the source *text* of any one module: it is the check
that notices a layout change, so it must not be the thing that breaks when the layout changes.
It pins the properties the repository relies on:

* the package is a tree of the known subpackages (``core/``, ``commands/``, ``cluster/``, ``ai/``,
  ``bot/``, ``update/``, ``ui/``) with exactly the known modules in them. Each subpackage's
  ``__init__.py`` is that package's front door: it re-exports names, but it may only *import* the
  modules whose own import closure needs nothing third-party -- anything else is resolved on first
  use (PEP 562), because importing a submodule runs the package's ``__init__.py`` first, and the
  entry module touches ``ai``/``bot``/``cluster``/``commands`` before the dependency gate. What a
  name resolved that way hands out is also declared in the front door's ``if TYPE_CHECKING:``
  block -- the only thing a type checker can read, since ``__getattr__`` is invisible to it,
* the entry module stays within a line budget (pinned at its current size: it may shrink, but a
  silent growth fails here),
* the files the plugin generates for the user point at the real modules: the custom ``tools.py``
  skeleton is seeded by ``ai/tools_stub_files.py`` and imports modules that exist (and registers
  its tool through the plugin's own loader), the editor stubs that module writes next to it are
  inventoried by ``tests/test_tool_stubs.py``, and the context-table builder rewrites the module
  the plugin reads (a path left behind by the subpackage move is invisible in all of them until
  they run),
* the package has an acyclic internal import graph and no module imports the entry package,
* the modules the entry module imports *before* the dependency gate pull no third-party package
  -- that is what lets a machine without ``openai``/``websockets`` load the plugin and repair
  itself,
* the manifest does not pack the tests, and no root ``requirements.txt`` comes back,
* the line endings are the ones the repository promises,
* the verification suite keeps its pytest shape: ``pytest.ini`` at the root, one ``conftest.py``
  for the shared fixtures, helpers in ``tests/_helpers/``, every Python file under ``tests/`` a
  test module -- and no trace of the hand-written runner and ``check()`` harness this repository
  used before.
"""
import ast
import io
import json
import os
import sys

import pytest

from _helpers.paths import LANG_DIR, MANIFEST, PKG, REPO_ROOT, TESTS_DIR
from _helpers.pkg import module_file

# The size the entry module has today. It is a ceiling, not a target: splitting more out of it is
# fine, an accidental growth is not.
ENTRY_LIMIT = 3329

# Every module the package is allowed to contain, as paths relative to games_ai/. Anything else in
# the tree is a stray file (a leftover .bak, a scratch script).
KNOWN_MODULES = {
    "__init__.py",
    "core/__init__.py", "core/clock.py", "core/config.py", "core/database.py", "core/deps.py",
    "core/logger.py", "core/permission.py",
    "commands/__init__.py", "commands/aibot.py", "commands/clear.py", "commands/data.py",
    "commands/node.py", "commands/settings.py",
    "cluster/__init__.py", "cluster/cross_server.py", "cluster/websockets_client.py",
    "cluster/websockets_server.py", "cluster/ws_command.py",
    "ai/__init__.py", "ai/chat_param.py", "ai/context_table.py", "ai/context_table_data.py",
    "ai/external_skills_loader.py", "ai/games_ai_tool.py", "ai/openai_api.py",
    "ai/register_extra_plugin.py", "ai/tools_interpreter.py", "ai/tools_stub_files.py",
    "bot/__init__.py", "bot/mineflayer.py", "bot/mineflayer_ai.py", "bot/mineflayer_service_files.py",
    "update/__init__.py", "update/update_round.py", "update/updater.py",
    "ui/__init__.py", "ui/help.py",
}

# Every directory the package is allowed to contain, besides the entry module itself.
KNOWN_PACKAGES = {"core", "commands", "cluster", "ai", "bot", "update", "ui"}

# These five still carry CRLF from before the line-ending convention existed. The set is pinned, so
# a *new* CRLF file fails here instead of surviving quietly; normalising them is a separate change.
CRLF_PENDING = {"core/database.py", "ai/openai_api.py", "ai/tools_interpreter.py",
                "ai/external_skills_loader.py", "ai/register_extra_plugin.py"}

# What a module imported before the gate may reach: the standard library, MCDR itself and this
# package. ``requests``/``openai``/``websockets`` may only be imported behind the gate.
ALLOWED_EXTERNAL = {"mcdreforged"}

# The helper modules and the protocol prototypes the suites share. They are not test modules, so
# they live under tests/_helpers/ and are imported by name (``from _helpers.paths import PKG``).
EXPECTED_HELPERS = {"__init__.py", "paths.py", "pkg.py", "wait.py",
                    "ws_async.py", "ws_sync_hub.py", "ws_sync_node.py"}

# The hand-written harness this suite used before it became a pytest suite. Its return would mean
# the conversion was undone, so one test looks for it.
HARNESS_MARKERS = ("RESULTS = []", "def check(name, cond")


def read(path, newline=""):
    with io.open(path, "r", encoding="utf-8", newline=newline) as handle:
        return handle.read()


def raw(path):
    with open(path, "rb") as handle:
        return handle.read()


def package_of(name):
    """The subpackage of one module as path parts: ``"cluster/cross_server.py" -> ["cluster"]``."""
    return [part for part in os.path.dirname(name).split("/") if part]


def resolve_relative(name, node):
    """What one relative ``ImportFrom`` reaches: dotted modules inside the package, and whether it
    reaches the entry package itself.

    Levels walk up from the importing module's package: inside ``cluster/cross_server.py``,
    ``from ..core.config import x`` is ``core.config`` and ``from .. import x`` is the entry
    package (``games_ai``), which no module may import.
    """
    parts = package_of(name)
    up = node.level - 1
    if up > len(parts):
        return [], True                                    # climbs past the package
    base = parts[:len(parts) - up]
    if node.module:
        return [".".join(base + node.module.split("."))], False
    if not base:
        return [], True                                    # `from .. import x` from a subpackage
    return [".".join(base + [alias.name.split(".")[0]]) for alias in node.names], False


def imports_of(tree, name, body_only=True):
    """(external roots, dotted internal modules, entry-package hits) of one module's imports.

    ``body_only`` asks for the imports that run when the module is imported; the default matters
    because an import inside ``if not _deps_pending:`` (or any other block) does not run then,
    which is the whole point of the dependency gate.
    """
    nodes = tree.body if body_only else list(ast.walk(tree))
    external, internal, entry = set(), set(), []
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if alias.name == "games_ai":
                    entry.append(getattr(node, "lineno", "?"))
                elif root == "games_ai":
                    internal.add(alias.name[len("games_ai."):])
                else:
                    external.add(root)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                dotted, reaches_entry = resolve_relative(name, node)
                if reaches_entry:
                    entry.append(getattr(node, "lineno", "?"))
                else:
                    internal |= {d for d in dotted if d}
            else:
                parts = (node.module or "").split(".")
                if parts[0] == "games_ai":
                    if len(parts) == 1:
                        entry.append(getattr(node, "lineno", "?"))
                    else:
                        internal.add(".".join(parts[1:]))
                elif parts[0]:
                    external.add(parts[0])
    return external, internal, entry


def dotted_to_file(dotted, present):
    """The module file a dotted package path names, or None when it is not a module of the package."""
    candidate = dotted.replace(".", "/") + ".py"
    if candidate in present:
        return candidate
    package = dotted.replace(".", "/") + "/__init__.py"
    return package if package in present else None


def python_files(root):
    """Every .py file under ``root`` as an absolute path, sorted, ``__pycache__`` skipped."""
    out = []
    for folder, folders, names in os.walk(root):
        folders[:] = sorted(name for name in folders if name != "__pycache__")
        out.extend(os.path.join(folder, name) for name in sorted(names) if name.endswith(".py"))
    return sorted(out)


def relative(path):
    """A path under tests/ the way a report should read it, with forward slashes."""
    return os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")


def package_path(name):
    """The absolute path of one package module, from its ``a/b.py`` relative path."""
    return os.path.join(PKG, name.replace("/", os.sep))


def is_type_checking(test):
    """Whether an ``if`` tests the ``TYPE_CHECKING`` flag (however it was imported)."""
    return isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"


def literal_strings(node):
    """The string literals of a set literal, or of a dict's keys."""
    items = node.keys if isinstance(node, ast.Dict) else node.elts
    return {item.value for item in items if isinstance(item, ast.Constant)}


def body_external_closure(name, trees):
    """Every external root the *body* imports of ``name`` reach, following package-internal imports.

    This is what a module drags in the moment it is imported: an import inside a function or a
    block is not part of it, which is exactly why the dependency gate works.
    """
    present = set(trees)
    seen, stack, external = set(), [name], set()
    while stack:
        current = stack.pop()
        if current in seen or current not in trees:
            continue
        seen.add(current)
        roots, internal, _ = imports_of(trees[current], current, body_only=True)
        external |= roots
        stack.extend(path for dotted in sorted(internal)
                     if (path := dotted_to_file(dotted, present)))
    return external


def is_pre_gate_safe(name, trees):
    """Whether importing ``name`` needs nothing but the standard library, MCDR and this package."""
    return all(root in ALLOWED_EXTERNAL or root in sys.stdlib_module_names or root == "games_ai"
               for root in body_external_closure(name, trees))


@pytest.fixture(scope="module")
def trees():
    """Every package module, parsed once: the whole suite asks questions about the same trees."""
    names = sorted(relative(path)[len("games_ai/"):] for path in python_files(PKG))
    return {name: ast.parse(read(package_path(name)), filename=name) for name in names}


def test_only_the_known_subpackages_exist():
    present = {name for name in os.listdir(PKG)
               if os.path.isdir(os.path.join(PKG, name)) and name != "__pycache__"}
    stray = sorted(present - KNOWN_PACKAGES)

    assert not stray, f"no stray directory in games_ai/: {stray}"


def test_every_subpackage_has_an_init_module():
    missing = sorted(name for name in KNOWN_PACKAGES
                     if not os.path.isfile(os.path.join(PKG, name, "__init__.py")))

    assert not missing, f"every subpackage has an __init__.py: {missing}"


def test_subpackage_init_modules_only_import_pre_gate_safe_modules(trees):
    """A front door may re-export anything, but it may only *import* what is safe before the gate.

    Importing ``games_ai.<pkg>.<module>`` executes ``<pkg>/__init__.py`` first, so an eager import
    of a module that needs ``openai``/``websockets``/``requests`` would break the entry module's
    own import on a machine where the plugin is still repairing its packages. Those names belong
    in the package's ``__getattr__`` instead.
    """
    present = set(trees)
    offenders = []
    for package in sorted(KNOWN_PACKAGES):
        init = "{}/__init__.py".format(package)
        if init not in trees:
            continue
        _, internal, _ = imports_of(trees[init], init, body_only=True)
        for dotted in sorted(internal):
            path = dotted_to_file(dotted, present)
            if path is None:
                offenders.append("{}: eager import of unknown module {}".format(init, dotted))
            elif not is_pre_gate_safe(path, trees):
                offenders.append("{}: {} needs a third-party package".format(init, path))

    assert not offenders, f"the subpackage front doors import only pre-gate safe modules: {offenders}"


def test_every_subpackage_declares_a_resolvable_facade():
    """Each front door lists its public names in ``__all__``, and every one of them resolves."""
    import importlib

    problems = []
    for package in sorted(KNOWN_PACKAGES):
        module = importlib.import_module("games_ai." + package)
        exported = getattr(module, "__all__", None)
        if not isinstance(exported, list) or not exported:
            problems.append("{}: no __all__".format(package))
            continue
        if len(set(exported)) != len(exported):
            problems.append("{}: __all__ repeats a name".format(package))
        missing = [name for name in exported if not hasattr(module, name)]
        if missing:
            problems.append("{}: __all__ lists names that do not resolve: {}".format(package, missing))

    assert not problems, f"every package front door resolves: {problems}"


def test_the_static_reexports_mirror_the_lazy_ones(trees):
    """A front door's ``if TYPE_CHECKING:`` block declares exactly what the runtime resolves.

    The third-party names leave the package through ``__getattr__``, which no type checker can
    see; the block is what it reads instead, so an editor knows the real type of every exported
    name instead of ``Any``. If the two drift, the checker promises a name the runtime cannot
    resolve -- or misses one it can, and the name silently goes back to ``Any``.
    """
    problems = []
    for package in sorted(KNOWN_PACKAGES):
        tree = trees["{}/__init__.py".format(package)]
        declared, lazy = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and is_type_checking(node.test):
                for inner in ast.walk(node):
                    if isinstance(inner, ast.ImportFrom):
                        declared |= {(alias.asname or alias.name) for alias in inner.names}
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.targets[0], ast.Name):
                continue
            kind = node.targets[0].id
            if kind == "_LAZY_NAMES" and isinstance(node.value, ast.Dict):
                lazy |= literal_strings(node.value)
            elif kind in ("_LAZY_MODULES", "_LAZY_ALIASES") \
                    and isinstance(node.value, (ast.Set, ast.Dict)):
                lazy |= literal_strings(node.value)
        if declared != lazy:
            problems.append("{}: block only {} / runtime only {}".format(
                package, sorted(declared - lazy), sorted(lazy - declared)))

    assert not problems, f"the checker sees what the runtime resolves: {problems}"


def test_the_entry_imports_only_from_packages(trees):
    """The entry module goes through the front doors, never into the packages' modules.

    A submodule reached directly would bypass the facade -- and with it the eager/lazy split that
    keeps the pre-gate path free of third-party imports.
    """
    offenders = []
    for node in ast.walk(trees["__init__.py"]):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            parts = node.module.split(".")
            if len(parts) > 1 and parts[0] in KNOWN_PACKAGES:
                offenders.append("{}: from .{} import".format(node.lineno, node.module))

    assert not offenders, f"the entry module imports from the packages, not their modules: {offenders}"


def test_the_entry_module_stays_within_its_line_budget():
    entry_lines = len(read(os.path.join(PKG, "__init__.py")).splitlines())

    assert entry_lines <= ENTRY_LIMIT, \
        f"entry module within {ENTRY_LIMIT} lines: {entry_lines} lines"


def test_the_packed_archive_lookup_does_not_depend_on_module_depth(tmp_path, monkeypatch):
    """``ai/games_ai_tool.py`` reads the bundled skills out of its own ``.mcdr``.

    The lookup walks up to the first parent with an archive suffix, so a module that moves deeper
    into the package -- as this one did when the subpackages appeared -- keeps finding the file
    MCDR loaded. Counting ``dirname`` calls instead would silently stop reading the bundled skills.
    """
    from games_ai.ai import games_ai_tool

    archive = tmp_path / "plugins" / "GamesAI.mcdr"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"")
    monkeypatch.setattr(games_ai_tool, "__file__",
                        str(archive / "games_ai" / "ai" / "games_ai_tool.py"))

    assert games_ai_tool.packed_plugin_file() == str(archive), \
        "the archive is found from any depth inside the package"

    monkeypatch.setattr(games_ai_tool, "__file__",
                        str(tmp_path / "plugins" / "games_ai" / "ai" / "games_ai_tool.py"))

    assert games_ai_tool.packed_plugin_file() is None, \
        "an unpacked (directory) install has no archive to read"


def generated_skeleton():
    """The custom-tools skeleton the plugin seeds on its first start, as text.

    It lives in ``ai/tools_stub_files.py`` (the module that owns everything written into the
    user's tools folder), not in the entry module -- the entry calls one function.
    """
    from games_ai.ai import tools_stub_files

    assert "@register_tool(" in tools_stub_files.TOOLS_SKELETON, \
        "the seeding module still carries the custom-tools skeleton"
    return tools_stub_files.TOOLS_SKELETON


def test_the_generated_custom_tools_skeleton_imports_the_real_modules():
    """The skeleton the plugin writes into the data folder has to name modules that exist.

    It is the plugin's own file, and the user's first custom tool starts from it. A module path
    that no longer exists makes the whole external tools file fail -- every tool in it registers
    nothing, with one ``Failed to load external tools`` line to say why -- which is exactly what
    the flat path did once the modules moved into the subpackages.
    """
    imports = [node for node in ast.walk(ast.parse(generated_skeleton()))
               if isinstance(node, ast.ImportFrom)]
    bad = ["{}: {}".format(node.module, module_file(node.module)) for node in imports
           if (node.module or "").startswith("games_ai") and module_file(node.module) is None]
    names = {alias.name for node in imports for alias in node.names}

    assert not bad, f"the skeleton imports modules of the package that exist: {bad}"
    assert "register_tool" in names, f"the skeleton imports the decorator it uses: {sorted(names)}"


def test_the_generated_custom_tools_skeleton_loads_through_the_tool_loader(tmp_path, monkeypatch):
    """The skeleton has to *load*, not merely parse: the loader is what registers its tool.

    Reading it as text cannot see a failing import, and that is the whole of this failure -- the
    file parses, the loader writes one ``Failed to load external tools`` line, and no tool of the
    user's file is registered. Registering through the real loader is the check that notices.
    """
    from games_ai.ai import tools_interpreter
    from games_ai.core.config import plugin_config

    path = tmp_path / "tools.py"
    path.write_text(generated_skeleton(), encoding="utf-8", newline="\n")
    monkeypatch.setattr(plugin_config, "tools_path", str(path))
    lines: list = []
    try:
        loaded, _ = tools_interpreter.load_external_tools(log=lines.append)
    finally:
        # The registry is process-wide: leave it exactly as it was found.
        tools_interpreter._clear_external_tools()
        sys.modules.pop("external_tools", None)

    assert "my_custom_tool" in loaded, f"the generated skeleton registers its tool: {lines}"


def test_the_context_table_builder_regenerates_the_module_the_plugin_reads():
    """``tools/build_context_table.py`` has to rewrite the file ``context_table.py`` imports.

    The bundled fallback is ``games_ai/ai/context_table_data.py`` now. A builder still pointing at
    the pre-subpackage path writes a second, unused module and leaves the shipped table stale, so
    editing the repository JSON and running the tool would change nothing the plugin reads.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_context_table", os.path.join(REPO_ROOT, "tools", "build_context_table.py"))
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    bundled = importlib.import_module("games_ai.ai.context_table_data")

    assert os.path.abspath(builder.DATA_MODULE) == os.path.abspath(bundled.__file__), \
        f"the builder regenerates the module context_table.py imports: {builder.DATA_MODULE}"


def test_no_stray_module_in_the_package(trees):
    assert set(trees) <= KNOWN_MODULES, \
        f"no stray module in games_ai/: {sorted(set(trees) - KNOWN_MODULES)}"


def test_every_known_module_is_present(trees):
    assert KNOWN_MODULES <= set(trees), \
        f"every known module is present: missing {sorted(KNOWN_MODULES - set(trees))}"


def test_no_module_imports_the_entry_package(trees):
    offenders = ["{}:{}".format(name, line)
                 for name, tree in trees.items() if name != "__init__.py"
                 for line in imports_of(tree, name, body_only=False)[2]]

    assert not offenders, f"no module imports the entry package: {offenders}"


def test_no_import_cycle_inside_the_package(trees):
    present = set(trees)
    graph = {name: {path for dotted in imports_of(tree, name, body_only=False)[1]
                    if (path := dotted_to_file(dotted, present))}
             for name, tree in trees.items()}
    state = {}

    def walk(node, trail):
        if state.get(node) == 1:
            return trail + [node]
        if state.get(node) == 2:
            return None
        state[node] = 1
        for nxt in sorted(graph.get(node, ())):
            cycle = walk(nxt, trail + [node])
            if cycle:
                return cycle
        state[node] = 2
        return None

    cycles = [cycle for name in sorted(graph) if (cycle := walk(name, []))]

    assert not cycles, f"no import cycle inside the package: {cycles[:1]}"


def test_modules_imported_before_the_gate_need_nothing_but_stdlib_and_mcdr(trees):
    present = set(trees)
    seen, stack, reached = set(), ["__init__.py"], set()
    while stack:
        current = stack.pop()
        if current in seen or current not in trees:
            continue
        seen.add(current)
        external, internal, _ = imports_of(trees[current], current, body_only=True)
        reached |= external
        for dotted in sorted(internal):
            path = dotted_to_file(dotted, present)
            if not path:
                continue
            stack.append(path)
            # Importing that module runs its package's front door first.
            package_init = "{}/__init__.py".format(os.path.dirname(path))
            if package_init in present:
                stack.append(package_init)
    bad = sorted(root for root in reached
                 if root not in ALLOWED_EXTERNAL and root not in sys.stdlib_module_names
                 and root != "games_ai")

    assert not bad, \
        f"modules imported before the gate need nothing but stdlib and MCDR: {sorted(seen)} pulled {bad}"


def test_the_manifest_does_not_pack_the_tests():
    manifest = json.loads(read(MANIFEST))
    resources = [str(item) for item in manifest.get("resources") or []]

    assert not any(r.strip("/") == "tests" for r in resources), \
        f"the manifest does not pack tests/: {resources}"


def test_no_root_requirements_txt():
    assert not os.path.exists(os.path.join(REPO_ROOT, "requirements.txt")), \
        "no root requirements.txt (MCDR would refuse to load the plugin)"


def test_the_package_carries_its_own_requirements_txt():
    assert os.path.isfile(os.path.join(PKG, "requirements.txt")), \
        "the package carries its own requirements.txt"


def test_only_the_pinned_files_are_still_crlf(trees):
    crlf = sorted(name for name in trees if b"\r\n" in raw(package_path(name)))

    assert crlf == sorted(CRLF_PENDING), f"only the pinned files are still CRLF: {crlf}"


def test_no_file_mixes_crlf_and_lf():
    mixed = []
    folders = [(PKG, ".py", True), (os.path.join(REPO_ROOT, "docs"), ".md", False),
               (REPO_ROOT, ".md", False)]
    for folder, suffix, recursive in folders:
        for path in (python_files(folder) if recursive else
                     [os.path.join(folder, name) for name in sorted(os.listdir(folder))]):
            if not path.endswith(suffix) or not os.path.isfile(path):
                continue
            body = raw(path)
            if b"\r\n" in body and body.replace(b"\r\n", b"").count(b"\n"):
                mixed.append(os.path.relpath(path, REPO_ROOT))

    assert not mixed, f"no file mixes CRLF and LF: {mixed}"


def test_lang_yml_are_still_crlf():
    assert all(b"\r\n" in raw(os.path.join(LANG_DIR, name))
               for name in sorted(os.listdir(LANG_DIR)) if name.endswith(".yml")), \
        "lang/*.yml are still CRLF"


def test_no_bom_in_the_package():
    boms = [relative(path) for path in python_files(PKG)
            if raw(path).startswith(b"\xef\xbb\xbf")]

    assert not boms, f"no BOM in the package: {boms}"


# --------------------------------------------------------------------------- the test suite itself

def test_the_suite_is_configured_for_pytest():
    config_path = os.path.join(REPO_ROOT, "pytest.ini")
    assert os.path.isfile(config_path), "pytest.ini sits at the repository root"
    config = read(config_path)
    assert "testpaths = tests" in config, f"pytest.ini points at tests/: {config!r}"
    assert os.path.isfile(os.path.join(TESTS_DIR, "conftest.py")), \
        "tests/conftest.py holds the shared fixtures"


def test_every_python_file_under_tests_is_a_test_module_or_a_conftest():
    stray = []
    for path in python_files(TESTS_DIR):
        inside = os.path.relpath(path, TESTS_DIR)
        if inside.startswith("_helpers" + os.sep):
            continue
        base = os.path.basename(path)
        if base == "conftest.py" or base.startswith("test_"):
            continue
        stray.append(relative(path))

    assert not stray, \
        f"every Python file under tests/ is a test module or a conftest: {stray}"


def test_the_documentation_checkers_are_test_modules():
    stray = [relative(path) for path in python_files(os.path.join(TESTS_DIR, "docs"))
             if not os.path.basename(path).startswith("test_")]

    assert not stray, f"the documentation checkers are test modules: {stray}"


def test_the_helpers_are_where_the_suites_expect_them():
    helpers_dir = os.path.join(TESTS_DIR, "_helpers")
    present = {name for name in os.listdir(helpers_dir) if name.endswith(".py")}

    assert present == EXPECTED_HELPERS, \
        f"tests/_helpers/ holds exactly the shared helpers: {sorted(present ^ EXPECTED_HELPERS)}"


def test_no_leftover_helper_module_at_the_tests_root():
    stray = sorted(name for name in os.listdir(TESTS_DIR)
                   if name.endswith(".py") and (name.startswith("_") or name.startswith("ws_")))

    assert not stray, f"no leftover helper module at the tests root: {stray}"


def scanned_files():
    """Every test-side Python file the two scans below look at: everything but the helpers and
    this module itself, whose own marker strings would otherwise match."""
    here = os.path.abspath(__file__)
    return [path for path in python_files(TESTS_DIR)
            if os.path.abspath(path) != here
            and not os.path.relpath(path, TESTS_DIR).startswith("_helpers" + os.sep)]


def test_the_hand_written_harness_is_gone():
    offenders = [relative(path) for path in scanned_files()
                 if any(marker in read(path) for marker in HARNESS_MARKERS)]

    assert not offenders, f"no check()/RESULTS harness left: {offenders}"


def test_the_old_runner_is_gone():
    assert not os.path.exists(os.path.join(TESTS_DIR, "_run_suites.py")), \
        "the hand-written runner is gone: pytest is the runner"


def test_no_test_module_does_path_arithmetic():
    needle = "sys.path." + "insert"
    offenders = [relative(path) for path in scanned_files() if needle in read(path)]

    assert not offenders, \
        f"no test module inserts into sys.path (pythonpath in pytest.ini does that): {offenders}"
