# Generated from games_ai/core/deps.py by tools/build_tool_stubs.py -- do not edit.
from _typeshed import Incomplete

__all__ = ['REQUIREMENTS', 'ALIYUN_INDEX_URL', 'PER_ATTEMPT_TIMEOUT_SECONDS', 'STALE_INSTALL_SECONDS', 'CACHE_DIR_NAME', 'missing', 'unimportable', 'unsatisfied', 'manual_command', 'pip_argv', 'install_once', 'install', 'state_path', 'read_state', 'write_state', 'begin_install', 'finish_install', 'note_recovered']

REQUIREMENTS: Incomplete
ALIYUN_INDEX_URL: str
PER_ATTEMPT_TIMEOUT_SECONDS: int
STALE_INSTALL_SECONDS: int
CACHE_DIR_NAME: str

def missing() -> list[str]:
    """The distributions of :data:`REQUIREMENTS` that have no metadata at all."""
def unimportable() -> list[str]:
    """The distributions that are installed but cannot be imported (a broken install)."""
def unsatisfied() -> list[str]:
    """Every requirement that is missing or not importable, in :data:`REQUIREMENTS` order."""
def manual_command(names) -> str:
    """The command a user can run himself when both pip attempts failed."""
def pip_argv(names, index_url: str | None = None) -> list[str]:
    """The pip command line of one attempt.

    ``index_url`` is only set for the mirror attempt: the first attempt must let pip use whatever
    this machine is configured with (pip.ini, ``PIP_INDEX_URL``, a proxy), so no index or proxy
    argument is passed at all.
    """
def install_once(names, log, abort, index_url: str | None = None) -> tuple[bool, str]:
    '''Run one ``pip install`` and stream its output.

    A reader thread pumps pip\'s stdout/stderr line by line into ``log`` while this thread only
    waits: that way an abort (MCDR shutting down) or the per-attempt timeout is noticed within
    half a second instead of after the next line arrives. Returns ``(returncode == 0, tail)``;
    ``tail`` is the last few output lines, or ``"aborted"`` / ``"timeout"``.
    '''
def install(names, log, abort, retry_log=None) -> tuple[bool, str, str]:
    '''Install the missing packages, machine pip configuration first, Aliyun mirror second.

    :return: ``(ok, phase, detail)`` where ``phase`` is ``"local"`` or ``"mirror"``. Nothing is
        retried when the mirror attempt failed too; the caller reports it.
    '''
def state_path(server) -> str:
    """The record of the last repair attempt, in the plugin's cache folder."""
def read_state(server) -> dict: ...
def write_state(server, **fields) -> None:
    """Merge ``fields`` into the state file. Never raises: a read-only data folder must not stop
    the install itself."""
def begin_install(server, names) -> tuple[bool, str]:
    '''Claim the repair.

    :return: ``(False, "running")`` when another instance is visibly installing right now,
        otherwise ``(True, "")`` after writing the ``installing`` record.
    '''
def finish_install(server, ok, detail: str = '', phase: str = '') -> None: ...
def note_recovered(server) -> list[str]:
    """Called by the normal ``on_load``: the packages are there, so report the repaired names once.

    A ``failed`` record counts as well -- the user may have installed the packages by hand and
    reloaded the plugin. The record turns ``ready`` so the next instance stays quiet.
    """
