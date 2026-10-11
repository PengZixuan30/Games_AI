# Generated from games_ai/update/updater.py by tools/build_tool_stubs.py -- do not edit.
import requests
from _typeshed import Incomplete
from dataclasses import dataclass
from pathlib import Path

PLUGIN_ID: str
ALLOWED_URL_PREFIX: str
PROXY_PREFIX: str
META_FILE: str
ARCHIVE_SUFFIXES: Incomplete
DOWNLOAD_TIMEOUT: float
DOWNLOAD_DEADLINE: float
DIRECT_ATTEMPTS: int
PROXY_ATTEMPTS: int
RETRY_BACKOFF: Incomplete
CHUNK_SIZE: Incomplete
MAX_ARCHIVE_BYTES: Incomplete
DELETE_ATTEMPTS: int
DELETE_BACKOFF: float
MOVE_ATTEMPTS: int
update_lock: Incomplete

class UpdaterError(Exception):
    """A failure the caller reports to players and the log.

    ``key`` is the localization key of the line to show; ``detail`` is the technical part
    that goes into that line and into the log.
    """
    key: str
    detail: Incomplete
    def __init__(self, detail: str, *, key: str | None = None) -> None: ...

class ReleaseError(UpdaterError):
    """The release metadata is missing, inconsistent or points somewhere unexpected."""
    key: str

class DownloadError(UpdaterError):
    """Neither the direct download nor the mirror produced the announced file."""
    key: str

class VerifyError(UpdaterError):
    """The bytes are there but they are not the announced archive."""
    key: str

class PreflightError(UpdaterError):
    """This instance cannot replace its own file at all (checked before unloading)."""
    key: str

class ReplaceError(UpdaterError):
    """The plugin unloaded, but its file could not be deleted or replaced."""
    key: str

class LoadError(UpdaterError):
    """The new file is in place but MCDR did not load it (the previous file was restored)."""
    key: str

@dataclass(frozen=True)
class ReleaseInfo:
    """Everything needed to fetch and verify one release."""
    version: str
    url: str
    size: int
    sha256: str
    file_name: str
    @property
    def proxy_url(self) -> str: ...

def release_from_entry(entry: dict, expected_version: str) -> ReleaseInfo:
    """Turn the catalogue release entry the update checker already parsed into a plan.

    The checker keeps doing the version comparison; this only re-reads the fields of the
    release it decided on, so the updater never has to fetch or interpret the catalogue
    itself. Every field is validated here, before a single byte is downloaded.
    """
def entry_for_version(catalogue: dict, version: str) -> dict | None:
    '''The catalogue release entry for one exact version, or None when it is not published.

    Used to catch a node up to the version this instance already runs: that release is not
    "new" for the checker (which only acts on something newer), but the node still has to
    install it.
    '''
def self_archive_path() -> Path | None:
    """This plugin's own packed file, or ``None`` for an unpacked (directory) install.

    ``__file__`` of a module inside a packed plugin is
    ``<plugins>/Something.mcdr/games_ai/__init__.py``, so the first parent with an archive
    suffix is the file MCDR loaded. MCDR itself relies on the same shape when it compares the
    entrypoint module path with the plugin path; a directory install has no such parent and
    cannot be replaced this way.
    """
def preflight(release: ReleaseInfo, target: Path | None) -> None:
    """Refuse early, while the plugin is still loaded and nothing has been destroyed.

    A failure here costs nothing; the same failure after the unload would leave the server
    without GamesAI until somebody notices.
    """
def download_release(release: ReleaseInfo, target_dir: Path, *, session=None, log=None) -> Path:
    """Fetch the artifact into ``target_dir`` and return the verified ``.part`` file.

    Direct GitHub first, the mirror second; each attempt has to produce the announced size
    and sha256 on its own, so a truncated attempt can never be mistaken for a slow one.
    """
def _download_once(client: requests, url: str, part: Path, release: ReleaseInfo, deadline: float) -> None:
    """One complete attempt: stream to ``part``, checking size and hash as it goes."""
def verify_archive(path: Path, release: ReleaseInfo) -> None:
    """Make sure the file is the announced plugin archive before it replaces anything."""
def apply_archive(server, staged: Path, target: Path, release: ReleaseInfo, *, log=None) -> None:
    """Replace the live archive with ``staged``: unload, delete, move, load.

    ``server`` is the ``PluginServerInterface`` of the *old* instance; MCDR's plugin
    operations stay usable after the unload, which is what lets this thread finish the swap.
    Every failure after the unload ends with a load attempt of whichever file is on disk.
    """
def prepare(server, release: ReleaseInfo, *, session=None, log=None) -> tuple[Path, Path]:
    """Everything that can fail while the plugin is still running: preflight, fetch, verify.

    Returns ``(target, staged)`` -- the live archive and the verified replacement next to it.
    A caller that coordinates a cluster update calls this *before* it orders the nodes around:
    a hub that cannot install the release itself must not tell its nodes to install it.
    """
def run_self_update(server, release: ReleaseInfo, *, session=None, log=None) -> None:
    """Download, verify and apply one release.  The caller holds :data:`update_lock`."""
def discard(staged: Path) -> None:
    """Drop a staged file that will not be applied (already consumed on a good apply)."""
def _remove_with_retries(path: Path) -> None:
    """Delete a file Windows may still consider open (antivirus, the indexer, a stale cache).

    ``gc.collect()`` between attempts is deliberate: the objects that keep an archive handle
    alive (``zipfile.Path`` instances cached by ``importlib.metadata``) are only released when
    the garbage collector runs.
    """
def _replace_with_retries(source: Path, target: Path) -> None: ...
def _load_quietly(server, target: Path, log) -> None:
    """Load what is on disk (used when the old file was never touched)."""
def _restore_backup(server, backup: Path, target: Path, log, *, unload_first: bool = False) -> bool:
    """Put the previous archive back and load it: never leave the server without GamesAI.

    The copy happens **before** the live file is touched, and into a sibling of the target: a
    failure while copying (no space left, an antivirus holding the new file) then leaves the
    target exactly as it was and the plugin is loaded from there. Deleting first would mean that
    the same failure leaves nothing to load at all.

    ``unload_first`` is for the one case where the wrong build *is* loaded: MCDR skips a plugin
    file whose path is already registered, so without the unload the rollback would silently do
    nothing while reporting success.

    Returns True when the previous archive really is back on disk (the caller's message must not
    claim a recovery that did not happen).
    """
def _remove_quietly(path: Path) -> None: ...
