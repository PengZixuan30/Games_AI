"""The files the plugin seeds into the user's tools folder: ``tools.py`` and the editor stubs.

``<data folder>/tools/`` holds the custom tools file the user writes, and next to it a generated
``games_ai/`` package of ``.pyi`` stubs. The stubs exist for one reason: the custom tools file
lives in MCDR's config directory, outside any project that can see the plugin, so without them an
editor answers ``Import "games_ai" could not be resolved`` and every name from the plugin is
``Any``. A stub package *in the same directory as the edited file* is what a language server
resolves with no project configuration at all -- including for a packed ``.mcdr`` install, whose
source is inside an archive that a language server cannot read.

The tree is generated from the plugin's own source by ``tools/build_tool_stubs.py`` and shipped
inside the package (``ai/_stubs``), so it cannot drift from the code by hand: regenerate it after
a source change instead of editing a stub. The lookups below handle both install shapes -- the
files next to this module for a directory install, MCDR's bundled-file reader or the archive
itself for a packed one.

Nothing imports a stub at runtime: they are read here, written next to ``tools.py``, and left for
the editor. Deleting the folder is harmless -- the next load puts it back.
"""

import os
import zipfile

from ..core.config import plugin_config
from .games_ai_tool import packed_plugin_file
from mcdreforged.plugin.si.plugin_server_interface import PluginServerInterface

#: The first-start skeleton written to ``tools.py`` when the user has none. The import path is the
#: module the registry really lives in (see docs/*/tools.md); the file is plain Python the plugin
#: executes on every load.
TOOLS_SKELETON = '''from mcdreforged.command.command_source import CommandSource
from games_ai.ai.games_ai_tool import register_tool

@register_tool(description="My Custom Tool")
def my_custom_tool(source: CommandSource, ai_prefix: str):
    return "Tool execution completed"
'''

#: Where the generated stubs are shipped (see tools/build_tool_stubs.py), and the path prefix
#: MCDR's bundled-file reader and the packed archive use for them.
_STUB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_stubs")
_BUNDLED_PREFIX = "games_ai/ai/_stubs/"
_STUB_PACKAGE = "games_ai"


def _bundled_paths() -> list:
    """The stubs the plugin ships, as paths relative to the ``games_ai`` package.

    A directory install reads them straight from ``ai/_stubs``; a packed ``.mcdr`` only carries
    them inside the archive, which :func:`packed_plugin_file` locates.
    """
    if os.path.isdir(_STUB_DIR):
        found = []
        for folder, folders, names in os.walk(_STUB_DIR):
            folders[:] = sorted(name for name in folders if name != "__pycache__")
            for name in sorted(names):
                if name.endswith(".pyi"):
                    found.append(os.path.relpath(os.path.join(folder, name), _STUB_DIR)
                                 .replace(os.sep, "/"))
        return found

    archive = packed_plugin_file()
    if archive is None:
        return []
    try:
        with zipfile.ZipFile(archive) as handle:
            return sorted(name[len(_BUNDLED_PREFIX):] for name in handle.namelist()
                          if name.startswith(_BUNDLED_PREFIX) and name.endswith(".pyi"))
    except (OSError, zipfile.BadZipFile):
        return []


def _read_bundled(server: PluginServerInterface, relative: str) -> bytes:
    """One stub's bytes: the shipped file, else MCDR's reader, else the archive."""
    local = os.path.join(_STUB_DIR, relative.replace("/", os.sep))
    if os.path.isfile(local):
        with open(local, "rb") as handle:
            return handle.read()

    opener = getattr(server, "open_bundled_file", None)
    if opener is not None:
        try:
            with opener(_BUNDLED_PREFIX + relative) as handle:
                return handle.read()
        except (OSError, KeyError):
            pass

    archive = packed_plugin_file()
    if archive is not None:
        with zipfile.ZipFile(archive) as handle:
            return handle.read(_BUNDLED_PREFIX + relative)
    raise FileNotFoundError(relative)


def _write_stubs(server: PluginServerInterface, tools_dir: str) -> tuple:
    """Refresh the stub tree under ``tools_dir``; returns (written, failed, first error).

    A file is written when it is missing or its bytes differ from the shipped stub, which makes
    the tree self-healing after an upgrade and cheap on every other load. The comparison and the
    write are byte-level on purpose: a text-mode write would translate the line endings on
    Windows, so the file on disk would never compare equal to the stub it came from.
    """
    root = os.path.join(tools_dir, _STUB_PACKAGE)
    written = 0
    failed = 0
    first_error = None
    for relative in _bundled_paths():
        target = os.path.join(root, relative.replace("/", os.sep))
        try:
            text = _read_bundled(server, relative)
            if os.path.isfile(target):
                with open(target, "rb") as handle:
                    if handle.read() == text:
                        continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as handle:
                handle.write(text)
            written += 1
        except (OSError, KeyError) as error:
            failed += 1
            first_error = first_error or error
    return written, failed, first_error


def seed_tools_folder(server: PluginServerInterface, tools_dir: str) -> str:
    """Create ``tools_dir``, write ``tools.py`` on first start, refresh the editor stubs.

    Returns the ``tools.py`` path, which ``on_load`` stores in ``plugin_config.tools_path``. A
    folder this cannot write to is logged and skipped -- seeding the user's data folder must never
    keep the plugin from loading.
    """
    tools_path = os.path.join(tools_dir, "tools.py")
    try:
        if not os.path.isdir(tools_dir):
            os.makedirs(tools_dir, exist_ok=True)
            server.logger.info(f"{server.rtr('games_ai.load_message.server_create_data_dir')}{tools_dir}")
        if not os.path.exists(tools_path):
            with open(tools_path, "wb") as handle:
                handle.write(TOOLS_SKELETON.encode("utf-8"))
            server.logger.info(f"{server.rtr('games_ai.load_message.server_create_data_dir')}{tools_path}")
    except OSError as error:
        server.logger.warning(f"{plugin_config.prefix} Cannot prepare the tools folder: {error}")
        return tools_path

    if not _bundled_paths():
        server.logger.warning(f"{plugin_config.prefix} The bundled editor stubs are missing, "
                              "so an editor cannot resolve games_ai.* in tools.py")
        return tools_path

    written, failed, first_error = _write_stubs(server, tools_dir)
    if written:
        server.logger.info(f"{plugin_config.prefix} Type stubs written: {written} file(s) in "
                           f"{os.path.join(tools_dir, _STUB_PACKAGE)}")
    if failed:
        server.logger.warning(f"{plugin_config.prefix} {failed} type stub file(s) could not be "
                              f"written: {first_error}")
    return tools_path
