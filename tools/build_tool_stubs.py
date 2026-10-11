"""
Type-stub builder for the editor stubs the plugin ships.

The plugin seeds ``<data folder>/tools/games_ai/`` with a package of ``.pyi`` stubs on every load
(see ``games_ai/ai/tools_stub_files.py``), so that an editor resolves ``games_ai.*`` inside the
user's custom ``tools.py`` with no project configuration at all -- including for a packed
``.mcdr`` install, whose source a language server cannot read. This script is what produces that
tree: it converts the plugin's own source into stubs, so the types cannot drift from the code.

Modes:

  python tools/build_tool_stubs.py
      Regenerate ``games_ai/ai/_stubs/`` from the plugin source. The tree is replaced: a module
      that disappeared takes its stub with it.

  python tools/build_tool_stubs.py --check
      Regenerate into a temporary directory and compare it with the checked-in tree. Verify only;
      writes nothing, exits 1 when the two differ.

The conversion is ``stubgen``, which ships with mypy (``pip install mypy``). It is a development
tool only: neither the plugin nor the test suite imports it, and the generated tree is committed.

Everything that matters to the stubs themselves lives in the writer, not here: the copied-out
layout (``_stubs/<module>.pyi`` -> ``tools/games_ai/<module>.pyi``), the refresh rule and the
packed-install lookup are all in ``games_ai/ai/tools_stub_files.py``.
"""
import filecmp
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "games_ai")
TARGET = os.path.join(ROOT, "games_ai", "ai", "_stubs")

#: Written as the first line of every stub. ``{}`` is the module file the stub came from.
HEADER = "# Generated from games_ai/{} by tools/build_tool_stubs.py -- do not edit.\n"

#: stubgen's own defaults are what the writer's guards assume: private members are kept (the
#: module stubs import each other, and e.g. the tool interpreter reaches ``_TOOL_REGISTRY``),
#: the modules are only parsed -- importing the package here would need the third-party
#: packages and MCDR's runtime -- and the docstrings travel with the signatures, which is what
#: an editor shows when somebody hovers a name from the plugin.
STUBGEN_ARGS = ["--no-import", "--include-private", "--include-docstrings"]


def stubgen_command() -> list[str]:
    """How to run stubgen here: its console script, else the module inside this interpreter."""
    executable = shutil.which("stubgen")
    if executable:
        return [executable]
    probe = subprocess.run([sys.executable, "-m", "mypy.stubgen", "--help"],
                           capture_output=True, text=True)
    if probe.returncode == 0:
        return [sys.executable, "-m", "mypy.stubgen"]
    print("[error] stubgen was not found (install it with: python -m pip install mypy)")
    return []


def source_files() -> list[str]:
    """Every module of the package to convert, in a stable order.

    ``ai/_stubs`` is skipped: it is this script's own output, and converting a stub tree into
    stubs would double the tree on every run.
    """
    files = []
    for folder, folders, names in os.walk(SOURCE):
        folders[:] = sorted(name for name in folders if name != "__pycache__")
        if os.path.abspath(folder) == os.path.abspath(os.path.dirname(TARGET)) \
                or os.path.abspath(folder).startswith(os.path.abspath(TARGET) + os.sep):
            folders[:] = [name for name in folders if name != os.path.basename(TARGET)]
        for name in sorted(names):
            if name.endswith(".py"):
                files.append(os.path.join(folder, name))
    return files


def generate(out_dir: str) -> dict[str, str]:
    """Convert the package into ``_stubs``-relative paths -> stub text, one module per file."""
    command = stubgen_command()
    if not command:
        raise SystemExit(2)
    # stubgen keeps a mypy cache in its working directory: run it inside the scratch directory (and
    # point MYPY_CACHE_DIR there too) so regenerating never leaves a stray cache in the repository.
    environment = dict(os.environ, MYPY_CACHE_DIR=os.path.join(out_dir, "_cache"))
    result = subprocess.run(command + STUBGEN_ARGS + ["-o", out_dir] + source_files(),
                            cwd=out_dir, env=environment, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        print("[error] stubgen failed")
        raise SystemExit(2)

    generated = os.path.join(out_dir, "games_ai")
    if not os.path.isdir(generated):
        print(f"[error] stubgen wrote nothing to {generated}")
        raise SystemExit(2)

    stubs: dict[str, str] = {}
    for folder, folders, names in os.walk(generated):
        folders[:] = sorted(name for name in folders if name != "__pycache__")
        for name in sorted(names):
            if not name.endswith(".pyi"):
                continue
            full = os.path.join(folder, name)
            relative = os.path.relpath(full, generated).replace(os.sep, "/")
            with open(full, "r", encoding="utf-8", newline="") as handle:
                body = handle.read()
            # stubgen writes the platform's line endings; the repository and the writer's byte
            # comparison both want LF, and normalising here keeps --check stable across machines.
            # The normalized text goes back into the scratch tree, so --check compares like with
            # like on every platform.
            body = body.replace("\r\n", "\n").replace("\r", "\n")
            stubs[relative] = HEADER.format(relative[:-len(".pyi")] + ".py") + body
            with open(full, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(stubs[relative])
    return stubs


def write_tree(stubs: dict[str, str]) -> None:
    """Replace the checked-in tree (a module that disappeared takes its stub with it)."""
    removed = 0
    for folder, folders, names in os.walk(TARGET):
        folders[:] = [name for name in folders if name != "__pycache__"]
        for name in names:
            if not name.endswith(".pyi"):
                continue
            relative = os.path.relpath(os.path.join(folder, name), TARGET).replace(os.sep, "/")
            if relative not in stubs:
                os.remove(os.path.join(folder, name))
                removed += 1
    for relative, text in sorted(stubs.items()):
        path = os.path.join(TARGET, relative.replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    print(f"[write] {TARGET} ({len(stubs)} stubs, {removed} removed)")


def verify(stubs: dict[str, str], scratch: str) -> bool:
    """Compare the generated tree with the checked-in one, file by file.

    ``scratch`` is stubgen's output root -- the directory that *holds* ``games_ai/``.
    """
    present = set()
    for folder, folders, names in os.walk(TARGET):
        folders[:] = [name for name in folders if name != "__pycache__"]
        for name in names:
            if name.endswith(".pyi"):
                present.add(os.path.relpath(os.path.join(folder, name), TARGET)
                            .replace(os.sep, "/"))

    problems = []
    for relative in sorted(set(stubs) | present):
        if relative not in stubs:
            problems.append(f"extra: {relative}")
        elif relative not in present:
            problems.append(f"missing: {relative}")
        elif not filecmp.cmp(os.path.join(TARGET, relative.replace("/", os.sep)),
                             os.path.join(scratch, "games_ai", relative.replace("/", os.sep)),
                             shallow=False):
            problems.append(f"stale: {relative}")

    print("== verify ==")
    if problems:
        for problem in problems:
            print(f"  [FAIL] {problem}")
        print("  [info] run: python tools/build_tool_stubs.py")
        return False
    print(f"  [PASS] the tree matches the plugin source ({len(stubs)} stubs)")
    return True


def main() -> int:
    check_only = "--check" in sys.argv[1:]
    with tempfile.TemporaryDirectory() as scratch:
        stubs = generate(scratch)
        if not check_only:
            write_tree(stubs)
        return 0 if verify(stubs, scratch) else 1


if __name__ == "__main__":
    sys.exit(main())
