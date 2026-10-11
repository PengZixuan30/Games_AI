"""The editor stubs the plugin seeds next to the user's ``tools.py``.

``games_ai/ai/tools_stub_files.py`` writes ``<data folder>/tools/games_ai/**`` from the stub tree
the plugin ships in ``games_ai/ai/_stubs``, so an editor resolves ``games_ai.*`` inside the custom
tools file with no project configuration -- for a directory install and for a packed ``.mcdr``
alike, whose source a language server cannot read.

This suite pins the three things that can silently go wrong:

* the shipped tree drifting from the plugin source (a module added or renamed without
  regenerating would leave the editor with an outdated or incomplete picture),
* the writer misbehaving on the user's disk (clobbering ``tools.py``, rewriting unchanged stubs on
  every load, translating line endings so the comparison never settles, or raising on a folder it
  cannot write),
* a packed install finding nothing, because the files only exist inside the archive.
"""
import ast
import importlib
import inspect
import os
import zipfile

import pytest

from _helpers.paths import PKG, REPO_ROOT
from _helpers.pkg import module_names

from games_ai.ai import tools_stub_files

BUNDLED = os.path.join(PKG, "ai", "_stubs")

#: The names the documentation tells a user to import (docs/*/tools.md, docs/*/skills.md,
#: docs/*/hot-reload.md and the custom_tools_management skill). Each one is a promise the package
#: makes to somebody else's code, so the stub has to keep it exactly.
DOCUMENTED = (
    ("ai/games_ai_tool", "register_tool"),
    ("ai/games_ai_tool", "register_bot_tool"),
    ("ai/games_ai_tool", "get_plugin_config_perm"),
    ("ai/register_extra_plugin", "register_self"),
    ("ai/external_skills_loader", "register_skills"),
)


class FakeServer:
    """What ``seed_tools_folder`` asks of MCDR: a logger, ``rtr()`` and the bundled-file reader."""

    def __init__(self):
        self.infos = []
        self.warnings = []
        self.logger = self

    def info(self, message):
        self.infos.append(str(message))

    def warning(self, message):
        self.warnings.append(str(message))

    def rtr(self, key, **kwargs):
        return key

    def open_bundled_file(self, relative_file_path):
        return open(os.path.join(REPO_ROOT, relative_file_path.replace("/", os.sep)), "rb")


class PackedServer(FakeServer):
    """A packed install: MCDR's reader finds nothing, so the archive is the only source."""

    def open_bundled_file(self, relative_file_path):
        raise FileNotFoundError(relative_file_path)


@pytest.fixture
def server():
    return FakeServer()


def bundled_paths():
    """The shipped stubs, as paths relative to the ``games_ai`` package."""
    return sorted(os.path.relpath(os.path.join(folder, name), BUNDLED).replace(os.sep, "/")
                  for folder, _, names in os.walk(BUNDLED) for name in names
                  if name.endswith(".pyi"))


def written_paths(tools_dir):
    """What the writer put next to ``tools.py``, in the same shape as :func:`bundled_paths`."""
    root = os.path.join(str(tools_dir), "games_ai")
    return sorted(os.path.relpath(os.path.join(folder, name), root).replace(os.sep, "/")
                  for folder, _, names in os.walk(root) for name in names)


def seed(tools_dir, server):
    return tools_stub_files.seed_tools_folder(server, str(tools_dir))


def stub_source(module):
    """The text of one shipped stub."""
    with open(os.path.join(BUNDLED, module.replace("/", os.sep) + ".pyi"), encoding="utf-8") as h:
        return h.read()


def stub_function(module, name):
    """One function of one shipped stub, as its AST node."""
    tree = ast.parse(stub_source(module))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{module}.pyi does not declare {name}")


def stub_parameters(node):
    """(name, kind, has a default) of a stub function, the way ``inspect`` reports them."""
    args = node.args
    positional = list(args.posonlyargs) + list(args.args)
    defaults = [False] * (len(positional) - len(args.defaults)) + [True] * len(args.defaults)
    out = []
    for argument, has_default in zip(positional, defaults):
        kind = "POSITIONAL_ONLY" if argument in args.posonlyargs else "POSITIONAL_OR_KEYWORD"
        out.append((argument.arg, kind, has_default))
    if args.vararg:
        out.append((args.vararg.arg, "VAR_POSITIONAL", False))
    for argument, default in zip(args.kwonlyargs, args.kw_defaults):
        out.append((argument.arg, "KEYWORD_ONLY", default is not None))
    if args.kwarg:
        out.append((args.kwarg.arg, "VAR_KEYWORD", False))
    return out


def live_parameters(func):
    return [(parameter.name, parameter.kind.name, parameter.default is not inspect.Parameter.empty)
            for parameter in inspect.signature(func).parameters.values()]


# ------------------------------------------------------------------- the shipped tree (the guard)

def test_the_bundled_tree_mirrors_the_package_modules():
    """One stub per module: a module added or renamed without regenerating fails here.

    The tree is produced by ``tools/build_tool_stubs.py`` from the plugin source. Nothing
    regenerates it at runtime (the plugin has no stub generator and may not grow one), so this is
    what keeps an out-of-date tree from shipping.
    """
    modules = {name[:-len(".py")] for name in module_names()}
    stubs = {path[:-len(".pyi")] for path in bundled_paths()}

    assert stubs == modules, (f"the stub tree mirrors the package: missing "
                              f"{sorted(modules - stubs)}, extra {sorted(stubs - modules)}")


@pytest.mark.parametrize("module,name", DOCUMENTED)
def test_the_documented_names_keep_their_signatures(module, name):
    """A documented import must keep working, and keep its shape, for the editor's reader."""
    live = getattr(importlib.import_module("games_ai." + module.replace("/", ".")), name)

    assert stub_parameters(stub_function(module, name)) == live_parameters(live), \
        f"{module}.{name} has the same parameters in the stub as at runtime"


@pytest.mark.parametrize("name", ["register_tool", "register_bot_tool"])
def test_the_decorators_keep_the_decorated_signature(name):
    """The stub's decorator returns the function it was given, ``ParamSpec`` and all.

    Without a return annotation a decorated tool loses its own signature in the editor; this is
    what ``typing.ParamSpec`` in the real implementation buys, and the stub inherits it.
    """
    returns = stub_function("ai/games_ai_tool", name).returns

    assert returns is not None, f"{name} declares its return type in the stub"
    assert "ParamSpec" in ast.dump(returns) or "_P" in ast.dump(returns), \
        f"{name} returns a signature-preserving decorator: {ast.dump(returns)}"


@pytest.mark.parametrize("module,name", DOCUMENTED)
def test_the_documented_names_publish_their_documentation(module, name):
    """Hovering a documented name has to say something: the stub carries its docstring.

    ``stubgen`` leaves docstrings out unless it is asked for them, which is how the first version
    of this tree shipped signatures with nothing behind them -- an editor showed the call shape
    and no explanation. A name the guides tell people to import must have something to show, and
    that means both a docstring in the source and ``--include-docstrings`` in the generator.
    """
    live = getattr(importlib.import_module("games_ai." + module.replace("/", ".")), name)
    documentation = inspect.getdoc(live)

    assert documentation, f"{module}.{name} has a docstring for the editor to show"
    assert documentation.splitlines()[0].strip() in stub_source(module), \
        f"{module}.{name}: the stub carries the docstring an editor hovers"


# ------------------------------------------------------------------------- the writer on disk

def test_the_stub_tree_is_written_next_to_the_tools_file(tmp_path, server):
    tools_dir = tmp_path / "tools"

    tools_path = seed(tools_dir, server)

    assert tools_path == str(tools_dir / "tools.py")
    assert written_paths(tools_dir) == bundled_paths(), "every shipped stub is written out"
    for relative in bundled_paths():
        with open(os.path.join(BUNDLED, relative.replace("/", os.sep)), "rb") as handle:
            shipped = handle.read()
        with open(os.path.join(str(tools_dir), "games_ai", relative.replace("/", os.sep)),
                  "rb") as handle:
            assert handle.read() == shipped, f"{relative} is copied byte for byte"
    assert (tools_dir / "tools.py").read_text(encoding="utf-8") == tools_stub_files.TOOLS_SKELETON
    assert any(f"Type stubs written: {len(bundled_paths())} file(s)" in line
               for line in server.infos), f"the write is logged once: {server.infos}"


def test_unchanged_stubs_are_not_rewritten(tmp_path, server):
    """A load that changes nothing touches nothing: no write, no log line."""
    tools_dir = tmp_path / "tools"
    seed(tools_dir, server)
    before = {path: os.stat(path).st_mtime_ns
              for path in (tools_dir / "games_ai").rglob("*.pyi")}
    server.infos.clear()

    seed(tools_dir, server)

    after = {path: os.stat(path).st_mtime_ns for path in (tools_dir / "games_ai").rglob("*.pyi")}
    assert after == before, "the second load rewrites nothing"
    assert not any("Type stubs written" in line for line in server.infos), \
        f"and says nothing about it: {server.infos}"


def test_a_stale_or_deleted_stub_is_restored(tmp_path, server):
    """The tree is self-healing after an upgrade, a partial write or a stray deletion."""
    tools_dir = tmp_path / "tools"
    seed(tools_dir, server)
    stale = tools_dir / "games_ai" / "ai" / "games_ai_tool.pyi"
    deleted = tools_dir / "games_ai" / "core" / "clock.pyi"
    stale.write_bytes(b"# an older version of this stub\n")
    deleted.unlink()
    server.infos.clear()

    seed(tools_dir, server)

    with open(os.path.join(BUNDLED, "ai", "games_ai_tool.pyi"), "rb") as handle:
        expected = handle.read()
    assert stale.read_bytes() == expected, "a stub that differs from the shipped one is replaced"
    assert deleted.is_file(), "a deleted stub comes back"
    assert any("Type stubs written: 2 file(s)" in line for line in server.infos), \
        f"exactly the two files are rewritten: {server.infos}"


def test_an_existing_tools_py_is_never_touched(tmp_path, server):
    """The skeleton is for a fresh install; a file the user wrote stays theirs."""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    mine = tools_dir / "tools.py"
    mine.write_bytes(b"# my own tools\n")

    seed(tools_dir, server)

    assert mine.read_bytes() == b"# my own tools\n", "the user's tools.py is left alone"
    assert not any(line.endswith("tools.py") for line in server.infos), \
        f"and is not reported as created: {server.infos}"


def test_the_written_files_use_lf(tmp_path, server):
    """Byte comparison plus LF writes: no translated copy can ever look permanently stale.

    The Mineflayer ``init.js`` seeding compares a text-mode file (CRLF on Windows) against a hash
    of the LF template, so it never matches and rewrites on every load. The stubs must not repeat
    that.
    """
    tools_dir = tmp_path / "tools"

    seed(tools_dir, server)

    for path in [tools_dir / "tools.py"] + sorted((tools_dir / "games_ai").rglob("*.pyi")):
        raw = path.read_bytes()
        assert b"\r\n" not in raw and b"\r" not in raw, f"{path} is written with LF endings"


def test_a_folder_that_cannot_be_written_is_logged_not_raised(tmp_path, server):
    """Seeding the data folder must never keep the plugin from loading."""
    blocker = tmp_path / "tools"
    blocker.write_text("this is a file, not a folder", encoding="utf-8")

    tools_path = seed(blocker, server)

    assert tools_path == str(blocker / "tools.py"), "the path is still handed back"
    assert server.warnings, f"the failure is reported: {server.warnings}"
    assert not (blocker / "games_ai").exists(), "and nothing is half-written"


def test_a_packed_install_reads_the_tree_from_the_archive(tmp_path, monkeypatch):
    """A ``.mcdr`` has no ``_stubs`` directory on disk; the archive is where the stubs live."""
    archive = tmp_path / "GamesAI.mcdr"
    members = ("__init__.pyi", "ai/games_ai_tool.pyi")
    with zipfile.ZipFile(archive, "w") as handle:
        for relative in members:
            handle.write(os.path.join(BUNDLED, relative.replace("/", os.sep)),
                         "games_ai/ai/_stubs/" + relative)
    monkeypatch.setattr(tools_stub_files, "_STUB_DIR", str(tmp_path / "gone"))
    monkeypatch.setattr(tools_stub_files, "packed_plugin_file", lambda: str(archive))

    assert tools_stub_files._bundled_paths() == sorted(members), \
        "the archive lists the stubs when the directory is not there"

    tools_dir = tmp_path / "tools"
    seed(tools_dir, PackedServer())

    assert written_paths(tools_dir) == sorted(members), "and they are written out from the archive"
