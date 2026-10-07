"""The shape of the plugin package and of this test suite: which modules exist, who may import
what, and the file-level conventions the repository holds.

This suite is deliberately independent of the source *text* of any one module: it is the check
that notices a layout change, so it must not be the thing that breaks when the layout changes.
It pins the properties the repository relies on:

* the entry module stays within a line budget (pinned at its current size: it may shrink, but a
  silent growth fails here),
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

# The size the entry module has today. It is a ceiling, not a target: splitting more out of it is
# fine, an accidental growth is not.
ENTRY_LIMIT = 3958

# Every module the package is allowed to contain. Anything else in games_ai/ is a stray file
# (a leftover .bak, a scratch script).
KNOWN_MODULES = {
    "__init__.py", "chat_param.py", "config.py", "context_table.py", "context_table_data.py",
    "cross_server.py", "database.py", "deps.py",
    "external_skills_loader.py", "games_ai_tool.py", "help.py",
    "logger.py", "mineflayer.py", "mineflayer_ai.py", "mineflayer_service_files.py", "openai_api.py",
    "register_extra_plugin.py", "tools_interpreter.py", "update_round.py",
    "updater.py", "websockets_client.py", "websockets_server.py", "ws_command.py",
}

# These five still carry CRLF from before the line-ending convention existed. The set is pinned, so
# a *new* CRLF file fails here instead of surviving quietly; normalising them is a separate change.
CRLF_PENDING = {"database.py", "openai_api.py", "tools_interpreter.py",
                "external_skills_loader.py", "register_extra_plugin.py"}

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


def module_imports(tree):
    """(external roots, internal module names) of the imports in the module body.

    Only the body: an import inside ``if not _deps_pending:`` (or any other block) does not run
    when the module is imported, which is the whole point of the dependency gate.
    """
    external, internal = set(), set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                external.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.module:
                    internal.add(node.module.split(".")[0])
                else:
                    for alias in node.names:
                        internal.add(alias.name.split(".")[0])
            else:
                parts = (node.module or "").split(".")
                if parts[0] == "games_ai" and len(parts) > 1:
                    internal.add(parts[1])
                elif parts[0]:
                    external.add(parts[0])
    return external, internal


def all_imports(tree):
    """Every internal module name imported anywhere, body or nested block."""
    internal = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "games_ai":
                    internal.add(alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.module:
                    internal.add(node.module.split(".")[0])
                else:
                    for alias in node.names:
                        internal.add(alias.name.split(".")[0])
            elif (node.module or "").split(".")[0] == "games_ai":
                parts = node.module.split(".")
                if len(parts) > 1:
                    internal.add(parts[1])
    return internal


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


@pytest.fixture(scope="module")
def trees():
    """Every package module, parsed once: the whole suite asks questions about the same trees."""
    names = sorted(name for name in os.listdir(PKG) if name.endswith(".py"))
    return {name: ast.parse(read(os.path.join(PKG, name)), filename=name) for name in names}


def test_the_entry_module_stays_within_its_line_budget():
    entry_lines = len(read(os.path.join(PKG, "__init__.py")).splitlines())

    assert entry_lines <= ENTRY_LIMIT, \
        f"entry module within {ENTRY_LIMIT} lines: {entry_lines} lines"


def test_no_stray_module_in_the_package(trees):
    assert set(trees) <= KNOWN_MODULES, \
        f"no stray module in games_ai/: {sorted(set(trees) - KNOWN_MODULES)}"


def test_every_known_module_is_present(trees):
    assert KNOWN_MODULES <= set(trees), \
        f"every known module is present: missing {sorted(KNOWN_MODULES - set(trees))}"


def test_no_module_imports_the_entry_package(trees):
    offenders = []
    for name, tree in trees.items():
        if name == "__init__.py":
            continue
        for node in ast.walk(tree):
            hit = None
            if isinstance(node, ast.Import):
                hit = any(alias.name == "games_ai" for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level:
                hit = (node.module or "") == "games_ai"
            if hit:
                offenders.append("{}:{}".format(name, getattr(node, "lineno", "?")))

    assert not offenders, f"no module imports the entry package: {offenders}"


def test_no_import_cycle_inside_the_package(trees):
    present = set(trees)
    graph = {name: {other if other.endswith(".py") else other + ".py"
                    for other in all_imports(tree)} & present
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
    seen, stack, reached = set(), ["__init__.py"], set()
    while stack:
        current = stack.pop()
        if current in seen or current not in trees:
            continue
        seen.add(current)
        external, internal = module_imports(trees[current])
        reached |= external
        stack.extend(sorted(other if other.endswith(".py") else other + ".py" for other in internal))
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
    crlf = sorted(name for name, tree in trees.items() if b"\r\n" in raw(os.path.join(PKG, name)))

    assert crlf == sorted(CRLF_PENDING), f"only the pinned files are still CRLF: {crlf}"


def test_no_file_mixes_crlf_and_lf():
    mixed = []
    for folder, suffix in ((PKG, ".py"), (os.path.join(REPO_ROOT, "docs"), ".md"),
                           (REPO_ROOT, ".md")):
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if not os.path.isfile(path) or not name.endswith(suffix):
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
    boms = [name for name in sorted(os.listdir(PKG))
            if name.endswith(".py") and raw(os.path.join(PKG, name)).startswith(b"\xef\xbb\xbf")]

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
