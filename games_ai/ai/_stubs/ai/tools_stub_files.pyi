# Generated from games_ai/ai/tools_stub_files.py by tools/build_tool_stubs.py -- do not edit.
from ..core.config import plugin_config as plugin_config
from .games_ai_tool import packed_plugin_file as packed_plugin_file
from _typeshed import Incomplete
from mcdreforged.plugin.si.plugin_server_interface import PluginServerInterface as PluginServerInterface

TOOLS_SKELETON: str
_STUB_DIR: Incomplete
_BUNDLED_PREFIX: str
_STUB_PACKAGE: str

def _bundled_paths() -> list:
    """The stubs the plugin ships, as paths relative to the ``games_ai`` package.

    A directory install reads them straight from ``ai/_stubs``; a packed ``.mcdr`` only carries
    them inside the archive, which :func:`packed_plugin_file` locates.
    """
def _read_bundled(server: PluginServerInterface, relative: str) -> bytes:
    """One stub's bytes: the shipped file, else MCDR's reader, else the archive."""
def _write_stubs(server: PluginServerInterface, tools_dir: str) -> tuple:
    """Refresh the stub tree under ``tools_dir``; returns (written, failed, first error).

    A file is written when it is missing or its bytes differ from the shipped stub, which makes
    the tree self-healing after an upgrade and cheap on every other load. The comparison and the
    write are byte-level on purpose: a text-mode write would translate the line endings on
    Windows, so the file on disk would never compare equal to the stub it came from.
    """
def seed_tools_folder(server: PluginServerInterface, tools_dir: str) -> str:
    """Create ``tools_dir``, write ``tools.py`` on first start, refresh the editor stubs.

    Returns the ``tools.py`` path, which ``on_load`` stores in ``plugin_config.tools_path``. A
    folder this cannot write to is logged and skipped -- seeding the user's data folder must never
    keep the plugin from loading.
    """
