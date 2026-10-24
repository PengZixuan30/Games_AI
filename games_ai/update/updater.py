"""Download a GamesAI release from GitHub and replace this plugin's own file with it.

Why this exists: MCDR's own installer (``!!MCDR plugin install``) does exactly this work and
does it well, but it is fire-and-forget -- the plugin that issued it cannot tell whether it
worked, and it knows nothing about the other instances of a cluster. A coordinated update
needs the artifact *in hand and verified* before anything is replaced, and needs to know the
outcome. So the download and the file swap live here. ``!!MCDR plugin install`` is never used
as a fallback: when a step fails the round is over and the failure is reported (see
``docs/<lang>/cross-server.md``).

The sequence, with the reason for each step:

1. everything that can fail -- release metadata, download, zip/metadata verification, free
   disk space, writability of the folder -- happens *before* the plugin is unloaded;
2. ``server.unload_plugin``: MCDR then holds no handle on the archive (``PackedPlugin`` reads
   the zip into memory and closes the file, and unloading clears the zipimport cache and the
   ``importlib.metadata`` path cache through ``release_file_occupation()``);
3. delete the old file, with retries: Windows can still answer "used by another process"
   (antivirus, the search indexer) even after MCDR let go;
4. ``os.replace`` the verified file onto the *same path*, so MCDR keeps exactly one file for
   this plugin id -- a second file with the same id would be dropped with an error and stay
   on disk;
5. ``server.load_plugin`` and check the version MCDR reports, restoring the previous file if
   that fails.

Every failure path after step 2 ends with a ``load_plugin`` call: a plugin that unloaded
itself and then gave up would leave the server running without GamesAI.

Two download sources, tried in order: the GitHub release asset itself, then the same URL
behind the ``ghfast.top`` mirror (some networks reset the connection to GitHub -- that has
been observed on the development machine, so retrying is not optional).
"""
import gc
import hashlib
import json
import os
import shutil
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests

PLUGIN_ID = "games_ai"
#: Only release assets of the plugin's own repository may be installed.
ALLOWED_URL_PREFIX = "https://github.com/PengZixuan30/Games_AI/releases/download/"
#: Second source: the same GitHub URL behind a mirror (``https://ghfast.top/<url>``).
PROXY_PREFIX = "https://ghfast.top/"
META_FILE = "mcdreforged.plugin.json"
ARCHIVE_SUFFIXES = (".mcdr", ".pyz")

DOWNLOAD_TIMEOUT = 15.0
#: Total wall-clock budget for all download attempts together.
DOWNLOAD_DEADLINE = 300.0
DIRECT_ATTEMPTS = 2
PROXY_ATTEMPTS = 2
RETRY_BACKOFF = (2.0, 5.0)
CHUNK_SIZE = 64 * 1024
#: MCDR refuses plugin files above 100 MiB; refuse them before downloading.
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
#: Deleting a file Windows still considers open: try, wait, try again.
DELETE_ATTEMPTS = 6
DELETE_BACKOFF = 1.0
MOVE_ATTEMPTS = 3

#: Held by the caller for a whole update (the 24 h check and the cluster round share it).
#: ``run_self_update`` does not take it itself, so a caller must never call it twice.
update_lock = threading.Lock()


class UpdaterError(Exception):
    """A failure the caller reports to players and the log.

    ``key`` is the localization key of the line to show; ``detail`` is the technical part
    that goes into that line and into the log.
    """

    key = "games_ai.update.failed"

    def __init__(self, detail: str, *, key: str | None = None):
        super().__init__(detail)
        self.detail = str(detail)
        if key:
            self.key = key


class ReleaseError(UpdaterError):
    """The release metadata is missing, inconsistent or points somewhere unexpected."""

    key = "games_ai.update.bad_release"


class DownloadError(UpdaterError):
    """Neither the direct download nor the mirror produced the announced file."""

    key = "games_ai.update.download_failed"


class VerifyError(UpdaterError):
    """The bytes are there but they are not the announced archive."""

    key = "games_ai.update.verify_failed"


class PreflightError(UpdaterError):
    """This instance cannot replace its own file at all (checked before unloading)."""

    key = "games_ai.update.not_packed"


class ReplaceError(UpdaterError):
    """The plugin unloaded, but its file could not be deleted or replaced."""

    key = "games_ai.update.replace_failed"


class LoadError(UpdaterError):
    """The new file is in place but MCDR did not load it (the previous file was restored)."""

    key = "games_ai.update.load_failed"


@dataclass(frozen=True)
class ReleaseInfo:
    """Everything needed to fetch and verify one release."""

    version: str
    url: str
    size: int
    sha256: str
    file_name: str

    @property
    def proxy_url(self) -> str:
        return PROXY_PREFIX + self.url


def release_from_entry(entry: dict, expected_version: str) -> ReleaseInfo:
    """Turn the catalogue release entry the update checker already parsed into a plan.

    The checker keeps doing the version comparison; this only re-reads the fields of the
    release it decided on, so the updater never has to fetch or interpret the catalogue
    itself. Every field is validated here, before a single byte is downloaded.
    """
    if not isinstance(entry, dict):
        raise ReleaseError("the catalogue entry is not an object")
    meta = entry.get("meta") or {}
    asset = entry.get("asset") or {}
    version = str(meta.get("version") or "")
    if version != str(expected_version):
        raise ReleaseError(f"the catalogue entry is for version {version!r}, "
                           f"expected {expected_version!r}")
    url = str(asset.get("browser_download_url") or "")
    if not url.startswith(ALLOWED_URL_PREFIX):
        raise ReleaseError(f"unexpected download address {url!r}")
    try:
        size = int(asset.get("size") or 0)
    except (TypeError, ValueError):
        raise ReleaseError("the catalogue entry carries no usable size") from None
    if size <= 0 or size > MAX_ARCHIVE_BYTES:
        raise ReleaseError(f"implausible artifact size {size}")
    sha256 = str(asset.get("hash_sha256") or "").strip().lower()
    if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
        raise ReleaseError("the catalogue entry carries no usable sha256")
    name = str(asset.get("name") or "").strip() or f"{PLUGIN_ID}-{version}.mcdr"
    return ReleaseInfo(version=version, url=url, size=size, sha256=sha256, file_name=name)


def entry_for_version(catalogue: dict, version: str) -> dict | None:
    """The catalogue release entry for one exact version, or None when it is not published.

    Used to catch a node up to the version this instance already runs: that release is not
    "new" for the checker (which only acts on something newer), but the node still has to
    install it.
    """
    try:
        releases = catalogue.get("plugins").get("games_ai").get("release").get("releases") or []
    except AttributeError:
        return None
    for entry in releases:
        if not isinstance(entry, dict):
            continue
        meta = entry.get("meta") or {}
        if str(meta.get("version") or "") == str(version):
            return entry
    return None


def self_archive_path() -> Path | None:
    """This plugin's own packed file, or ``None`` for an unpacked (directory) install.

    ``__file__`` of a module inside a packed plugin is
    ``<plugins>/Something.mcdr/games_ai/__init__.py``, so the first parent with an archive
    suffix is the file MCDR loaded. MCDR itself relies on the same shape when it compares the
    entrypoint module path with the plugin path; a directory install has no such parent and
    cannot be replaced this way.
    """
    here = Path(os.path.abspath(__file__))
    for parent in here.parents:
        if parent.suffix.lower() in ARCHIVE_SUFFIXES:
            return parent if parent.is_file() else None
    return None


def preflight(release: ReleaseInfo, target: Path | None) -> None:
    """Refuse early, while the plugin is still loaded and nothing has been destroyed.

    A failure here costs nothing; the same failure after the unload would leave the server
    without GamesAI until somebody notices.
    """
    if target is None or not Path(target).is_file():
        raise PreflightError(
            "this instance is not a packed .mcdr install, so it cannot replace itself",
            key="games_ai.update.not_packed",
        )
    folder = Path(target).parent
    if not os.access(str(folder), os.W_OK):
        raise PreflightError(f"the plugin folder {folder} is not writable",
                             key="games_ai.update.folder_not_writable")
    free = None
    try:
        free = shutil.disk_usage(str(folder)).free
    except OSError:
        pass
    needed = release.size * 3 + (1 << 20)
    if free is not None and free < needed:
        raise PreflightError(f"{free} bytes free next to {folder}, need about {needed}",
                             key="games_ai.update.no_disk_space")


def download_release(release: ReleaseInfo, target_dir: Path, *, session=None, log=None) -> Path:
    """Fetch the artifact into ``target_dir`` and return the verified ``.part`` file.

    Direct GitHub first, the mirror second; each attempt has to produce the announced size
    and sha256 on its own, so a truncated attempt can never be mistaken for a slow one.
    """
    target_dir = Path(target_dir)
    part = target_dir / (release.file_name + ".part")
    client = session if session is not None else requests
    deadline = time.monotonic() + DOWNLOAD_DEADLINE
    attempts = [("direct", release.url)] * DIRECT_ATTEMPTS
    attempts += [("mirror", release.proxy_url)] * PROXY_ATTEMPTS
    failures: list[str] = []
    for index, (source, url) in enumerate(attempts):
        if time.monotonic() >= deadline:
            failures.append("the download deadline ran out")
            break
        try:
            _download_once(client, url, part, release, deadline)
        except UpdaterError as error:
            failures.append(f"{source}: {error.detail}")
            _remove_quietly(part)
            if index + 1 < len(attempts):
                time.sleep(RETRY_BACKOFF[min(index, len(RETRY_BACKOFF) - 1)])
            continue
        if log is not None:
            log(f"downloaded {release.file_name} ({release.size} bytes) from the {source} source")
        return part
    raise DownloadError("; ".join(failures) or "no download was attempted")


def _download_once(client: requests, url: str, part: Path, release: ReleaseInfo, deadline: float) -> None:
    """One complete attempt: stream to ``part``, checking size and hash as it goes."""
    try:
        response: requests.Response = client.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT, allow_redirects=True)
    except Exception as error:
        raise DownloadError(f"request failed: {error}") from None
    digest = hashlib.sha256()
    written = 0
    try:
        status = getattr(response, "status_code", 200)
        if status != 200:
            raise DownloadError(f"HTTP {status}")
        with open(part, "wb") as handle:
            for chunk in response.iter_content(CHUNK_SIZE):
                if not chunk:
                    continue
                written += len(chunk)
                if written > release.size or written > MAX_ARCHIVE_BYTES:
                    raise DownloadError(f"the artifact is larger than announced ({written} bytes)")
                if time.monotonic() >= deadline:
                    raise DownloadError("the download deadline ran out")
                digest.update(chunk)
                handle.write(chunk)
    finally:
        closer = getattr(response, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass
    if written != release.size:
        raise DownloadError(f"size mismatch: got {written}, expected {release.size}")
    if digest.hexdigest() != release.sha256:
        raise DownloadError("sha256 mismatch")


def verify_archive(path: Path, release: ReleaseInfo) -> None:
    """Make sure the file is the announced plugin archive before it replaces anything."""
    path = Path(path)
    if not zipfile.is_zipfile(path):
        raise VerifyError("the downloaded file is not a zip archive")
    try:
        with zipfile.ZipFile(path) as archive:
            broken = archive.testzip()
            if broken is not None:
                raise VerifyError(f"the archive is corrupt at {broken!r}")
            try:
                raw = archive.read(META_FILE)
            except KeyError:
                raise VerifyError(f"the archive has no {META_FILE}") from None
    except zipfile.BadZipFile as error:
        raise VerifyError(f"the archive cannot be read: {error}") from None
    try:
        metadata = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise VerifyError(f"the archive metadata is not valid JSON: {error}") from None
    if str(metadata.get("id") or "") != PLUGIN_ID:
        raise VerifyError(f"the archive is for plugin {metadata.get('id')!r}, not {PLUGIN_ID!r}")
    archive_version = str(metadata.get("version") or "")
    if archive_version != release.version:
        raise VerifyError(f"the archive is version {archive_version!r}, "
                          f"expected {release.version!r}")


def apply_archive(server, staged: Path, target: Path, release: ReleaseInfo, *, log=None) -> None:
    """Replace the live archive with ``staged``: unload, delete, move, load.

    ``server`` is the ``PluginServerInterface`` of the *old* instance; MCDR's plugin
    operations stay usable after the unload, which is what lets this thread finish the swap.
    Every failure after the unload ends with a load attempt of whichever file is on disk.
    """
    staged, target = Path(staged), Path(target)
    backup = target.with_name(target.name + ".bak")
    _remove_quietly(backup)
    try:
        shutil.copy2(target, backup)
    except OSError as error:
        raise ReplaceError(f"cannot back up {target}: {error}") from None

    result = server.unload_plugin(PLUGIN_ID)
    if not result:
        _remove_quietly(staged)
        _remove_quietly(backup)
        raise ReplaceError(f"the plugin could not be unloaded (result={result!r})")

    try:
        _remove_with_retries(target)
    except ReplaceError as error:
        _load_quietly(server, target, log)
        raise ReplaceError(f"{error.detail}; the previous file was loaded again") from None

    try:
        _replace_with_retries(staged, target)
    except ReplaceError as error:
        restored = _restore_backup(server, backup, target, log)
        raise ReplaceError(f"{error.detail}; "
                           + ("the previous file was restored" if restored else
                              "the previous file could not be restored (see the log)")) from None

    try:
        loaded = bool(server.load_plugin(str(target)))
    except Exception as error:                       # MCDR itself failing to load the file
        loaded = False
        if log is not None:
            log(f"MCDR raised while loading {target.name}: {error}")
    if not loaded:
        restored = _restore_backup(server, backup, target, log)
        raise LoadError("MCDR refused to load the new file; "
                        + ("the previous version was restored" if restored else
                           "the previous archive could not be restored (see the log)"))

    metadata = server.get_plugin_metadata(PLUGIN_ID)
    version = str(getattr(metadata, "version", "") or "")
    if version != release.version:
        # The wrong build is loaded right now, so the restore has to unload it first: MCDR skips
        # a plugin file it already has registered, which would make the rollback a silent no-op
        # while claiming the previous version was restored.
        restored = _restore_backup(server, backup, target, log, unload_first=True)
        raise LoadError(f"MCDR reports version {version!r} after loading, "
                        f"expected {release.version!r}; "
                        + ("the previous version was restored" if restored else
                           "the previous archive could not be restored (see the log)"))
    _remove_quietly(backup)
    if log is not None:
        log(f"{target.name} is now version {release.version}")


def prepare(server, release: ReleaseInfo, *, session=None, log=None) -> tuple[Path, Path]:
    """Everything that can fail while the plugin is still running: preflight, fetch, verify.

    Returns ``(target, staged)`` -- the live archive and the verified replacement next to it.
    A caller that coordinates a cluster update calls this *before* it orders the nodes around:
    a hub that cannot install the release itself must not tell its nodes to install it.
    """
    target = self_archive_path()
    preflight(release, target)
    staged = download_release(release, Path(target).parent, session=session, log=log)
    try:
        verify_archive(staged, release)
    except UpdaterError:
        _remove_quietly(staged)
        raise
    return target, staged


def run_self_update(server, release: ReleaseInfo, *, session=None, log=None) -> None:
    """Download, verify and apply one release.  The caller holds :data:`update_lock`."""
    target, staged = prepare(server, release, session=session, log=log)
    try:
        apply_archive(server, staged, target, release, log=log)
    finally:
        _remove_quietly(staged)


def discard(staged: Path) -> None:
    """Drop a staged file that will not be applied (already consumed on a good apply)."""
    _remove_quietly(Path(staged))


def _remove_with_retries(path: Path) -> None:
    """Delete a file Windows may still consider open (antivirus, the indexer, a stale cache).

    ``gc.collect()`` between attempts is deliberate: the objects that keep an archive handle
    alive (``zipfile.Path`` instances cached by ``importlib.metadata``) are only released when
    the garbage collector runs.
    """
    last: OSError | None = None
    for attempt in range(DELETE_ATTEMPTS):
        try:
            os.remove(path)
            return
        except FileNotFoundError:
            return
        except OSError as error:
            last = error
            gc.collect()
            if attempt + 1 < DELETE_ATTEMPTS:
                time.sleep(DELETE_BACKOFF)
    raise ReplaceError(f"cannot delete {path}: {last}")


def _replace_with_retries(source: Path, target: Path) -> None:
    last: OSError | None = None
    for attempt in range(MOVE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except OSError as error:
            last = error
            if attempt + 1 < MOVE_ATTEMPTS:
                time.sleep(DELETE_BACKOFF)
    raise ReplaceError(f"cannot move {source.name} into place: {last}")


def _load_quietly(server, target: Path, log) -> None:
    """Load what is on disk (used when the old file was never touched)."""
    try:
        server.load_plugin(str(target))
    except Exception as error:
        if log is not None:
            log(f"failed to load {target.name} again: {error}")


def _files_identical(left: Path, right: Path) -> bool:
    """Byte-for-byte comparison of two files (size first, then SHA-256)."""
    try:
        if left.stat().st_size != right.stat().st_size:
            return False
        with open(left, "rb") as left_handle, open(right, "rb") as right_handle:
            return hashlib.sha256(left_handle.read()).digest() == hashlib.sha256(right_handle.read()).digest()
    except OSError:
        return False


def _restore_backup(server, backup: Path, target: Path, log, *,
                    unload_first: bool = False) -> bool:
    """Put the previous archive back and load it: never leave the server without GamesAI.

    The copy happens **before** the live file is touched, and into a sibling of the target: a
    failure while copying (no space left, an antivirus holding the new file) then leaves the
    target exactly as it was and the plugin is loaded from there. Deleting first would mean that
    the same failure leaves nothing to load at all.

    ``unload_first`` is for the one case where the wrong build *is* loaded: MCDR skips a plugin
    file whose path is already registered, so without the unload the rollback would silently do
    nothing while reporting success.

    Returns True only when the previous archive really is back on disk **and is the previous
    archive** (size + SHA-256 checked against the backup). A rollback that replaced the file but
    could not verify it must not be reported as a recovery (the caller's message would lie).
    """
    restore = target.with_name(target.name + ".restore")
    _remove_quietly(restore)
    try:
        shutil.copy2(backup, restore)
    except OSError as error:
        if log is not None:
            log(f"could not prepare {restore.name}: {error}")
        _load_quietly(server, target, log)           # whichever build is on disk stays loadable
        return False
    if unload_first:
        try:
            server.unload_plugin(PLUGIN_ID)
        except Exception as error:                   # noqa: BLE001 - reported, never fatal
            if log is not None:
                log(f"could not unload before the rollback: {error}")
    try:
        _remove_with_retries(target)
        _replace_with_retries(restore, target)
    except ReplaceError as error:
        if log is not None:
            log(f"could not put the previous archive back: {error.detail}")
        if Path(target).exists() and _files_identical(target, backup):
            # The failure was after the copy really landed (e.g. the restore file was already
            # the new archive): the target is the old build again, so loading it is correct.
            _load_quietly(server, target, log)
            return True
        # The old bytes are in `restore` (a copy, wrong suffix for MCDR): try once more to move
        # them into place, and if even that fails name the file instead of claiming a recovery.
        try:
            os.replace(restore, target)
        except OSError:
            pass
        if Path(target).exists() and _files_identical(target, backup):
            _load_quietly(server, target, log)
            return True
        if log is not None:
            log(f"the previous archive is at {restore}; move it onto {target} by hand")
        return False
    if not _files_identical(target, backup):
        # `_replace_with_retries` reported success but the file on disk is not the backup: do not
        # claim a rollback that did not happen.
        if log is not None:
            log(f"the file at {target} is not the previous archive after the rollback; "
                f"the old bytes are at {restore}")
        return False
    _load_quietly(server, target, log)
    return True


def _remove_quietly(path: Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
