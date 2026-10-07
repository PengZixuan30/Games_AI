"""The self-updater: release parsing, the two download sources, verification, the swap.

Everything runs against fake HTTP sessions and a fake MCDR interface in a throwaway folder;
the real plugin, the real data folder and the network are never touched. What the suite is
really pinning down:

* the artifact is only accepted when size, sha256 and the archive's own metadata all agree;
* the mirror is the *second* source, never the first, and a truncated attempt is never
  mistaken for a slow one;
* everything that can fail happens before the plugin is unloaded;
* after the unload every failure path ends with a `load_plugin` call, so the server is never
  left without GamesAI;
* `!!MCDR plugin install` is not used anywhere -- not as a fallback, not as a comment.
"""
import hashlib
import json
import os
import re
import shutil
import types
import zipfile
from pathlib import Path

import pytest

from _helpers.paths import PKG
from games_ai import updater


def make_archive(path, *, plugin_id="games_ai", version="9.9.9", extra=b"", truncate_member=False):
    """A minimal packed plugin: mcdreforged.plugin.json at the root of a zip."""
    meta = json.dumps({"id": plugin_id, "version": version, "name": "GamesAI"}).encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("mcdreforged.plugin.json", meta)
        archive.writestr(f"{plugin_id}/__init__.py", b"VERSION = %r\n" % version.encode())
        if extra:
            archive.writestr("payload.bin", extra)
    if truncate_member:
        # corrupt the first member's data so that testzip() reports it
        path = Path(path)
        raw = bytearray(path.read_bytes())
        name = b"mcdreforged.plugin.json"
        offset = 30 + len(name)
        raw[offset] ^= 0xFF
        path.write_bytes(bytes(raw))
    return path


def release_for(path, version="9.9.9", url=None):
    body = Path(path).read_bytes()
    return updater.ReleaseInfo(
        version=version,
        url=url or (updater.ALLOWED_URL_PREFIX + version + "/GamesAI-v" + version + ".mcdr"),
        size=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        file_name="GamesAI-v%s.mcdr" % version,
    ), body


def fresh_plugin_dir(folder, artifact_path):
    """A live 8.8.8 archive, with the staged 9.9.9 replacement waiting next to it."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    live = folder / "GamesAI-v8.8.8.mcdr"
    make_archive(live, version="8.8.8")
    staged = folder / "GamesAI-v9.9.9.mcdr.part"
    shutil.copy2(artifact_path, staged)
    return live, staged


class FakeResponse:
    def __init__(self, body=b"", status=200):
        self.body = body
        self.status_code = status
        self.closed = False

    def iter_content(self, size):
        for start in range(0, len(self.body), size):
            yield self.body[start:start + size]

    def close(self):
        self.closed = True


class FakeSession:
    """Returns the planned responses in order; records every URL it was asked for."""

    def __init__(self, plan):
        self.plan = list(plan)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        item = self.plan.pop(0) if self.plan else FakeResponse(b"")
        if isinstance(item, Exception):
            raise item
        return item


class FakeMetadata:
    def __init__(self, version):
        self.version = version


class FakeServer:
    """Just enough PluginServerInterface for the swap: records the call order."""

    def __init__(self, *, load_results=(True,), version_after_load=None, unload_result=True):
        self.calls = []
        self.load_results = list(load_results)
        self.version_after_load = version_after_load
        self.unload_result = unload_result
        self.said = []

    def unload_plugin(self, plugin_id):
        self.calls.append(("unload", plugin_id))
        return self.unload_result

    def load_plugin(self, path):
        self.calls.append(("load", os.path.basename(str(path))))
        result = self.load_results.pop(0) if self.load_results else False
        return result

    def get_plugin_metadata(self, plugin_id):
        self.calls.append(("metadata", plugin_id))
        if not self.load_results and self.version_after_load is None:
            return FakeMetadata("old")
        return FakeMetadata(self.version_after_load or "9.9.9")

    def say(self, text):
        self.said.append(text)


def entry(version="9.9.9", url=None, size=None, sha256=None, name=None):
    return {
        "asset": {
            "name": name if name is not None else "GamesAI-v%s.mcdr" % version,
            "size": 12345 if size is None else size,
            "hash_sha256": sha256 if sha256 is not None else "a" * 64,
            "browser_download_url": url or (
                updater.ALLOWED_URL_PREFIX + version + "/GamesAI-v%s.mcdr" % version),
        },
        "meta": {"version": version},
    }


@pytest.fixture(autouse=True)
def fast_backoff(monkeypatch):
    """A download retry in a test must not sit on the production backoff (2s, then 5s)."""
    monkeypatch.setattr(updater, "RETRY_BACKOFF", (0.0, 0.0))


@pytest.fixture
def artifact(tmp_path):
    """A valid 9.9.9 archive on disk, plus the plan and the bytes that describe it."""
    path = tmp_path / "artifact.mcdr"
    make_archive(path, version="9.9.9")
    release, body = release_for(path)
    return types.SimpleNamespace(path=path, release=release, body=body)


@pytest.fixture
def work(tmp_path):
    """An empty folder for one download attempt: the .part file lands here."""
    folder = tmp_path / "work"
    folder.mkdir()
    return folder


def test_the_release_entry_the_checker_hands_over():
    """Section 1: the release entry the checker hands over."""
    good = updater.release_from_entry(entry(), "9.9.9")
    assert (good.version, good.size, good.file_name) == ("9.9.9", 12345, "GamesAI-v9.9.9.mcdr"), \
        f"a good entry becomes a plan: {good}"
    assert good.proxy_url == updater.PROXY_PREFIX + good.url, \
        f"the mirror is derived from the direct url: {good.proxy_url}"

    for name, bad_entry, expected in [
        ("version mismatch", entry("9.9.9"), "9.9.8"),
        ("missing asset", {"meta": {"version": "9.9.9"}}, "9.9.9"),
        ("foreign host", entry(url="https://example.com/x.mcdr"), "9.9.9"),
        ("zero size", entry(size=0), "9.9.9"),
        ("oversized", entry(size=updater.MAX_ARCHIVE_BYTES + 1), "9.9.9"),
        ("bad sha", entry(sha256="zz"), "9.9.9"),
    ]:
        detail = ""
        try:
            updater.release_from_entry(bad_entry, expected)
        except updater.ReleaseError as error:
            detail = error.detail
        assert detail, f"rejected: {name}: no error raised"


def test_finding_the_entry_for_one_exact_version():
    """Section 2: finding the entry for one exact version (the catch-up case)."""
    catalogue = {"plugins": {"games_ai": {"release": {"releases": [
        entry("9.9.9"), entry("9.9.8", size=999), {"meta": {"version": "9.9.7"}}]}}}}

    found = updater.entry_for_version(catalogue, "9.9.8")
    assert found is not None and found["asset"]["size"] == 999, \
        f"the entry of an older version is found: {found}"
    assert updater.entry_for_version(catalogue, "1.0.0") is None, \
        "an unpublished version yields None"
    assert updater.entry_for_version(catalogue, "9.9.7") == {"meta": {"version": "9.9.7"}}, \
        "a release without an asset is still returned (release_from_entry rejects it later)"
    assert updater.entry_for_version({"plugins": {}}, "9.9.8") is None \
        and updater.entry_for_version({}, "9.9.8") is None \
        and updater.entry_for_version({"plugins": {"games_ai": {"release": {"releases": None}}}},
                                      "9.9.8") is None, "a malformed catalogue yields None"


def test_where_is_our_own_mcdr(tmp_path, monkeypatch):
    """Section 3: where is our own .mcdr?"""
    fake_archive = tmp_path / "plugins" / "GamesAI-v8.8.8.mcdr"
    fake_archive.parent.mkdir(parents=True, exist_ok=True)
    make_archive(fake_archive, version="8.8.8")

    monkeypatch.setattr(updater, "__file__", str(fake_archive / "games_ai" / "updater.py"))
    assert updater.self_archive_path() == fake_archive, \
        f"a packed install finds its archive: {updater.self_archive_path()}"

    monkeypatch.setattr(updater, "__file__", str(tmp_path / "plugins" / "games_ai" / "updater.py"))
    assert updater.self_archive_path() is None, \
        f"an unpacked install reports None (cannot self-replace): {updater.self_archive_path()}"

    monkeypatch.setattr(updater, "__file__",
                        str(tmp_path / "plugins" / "gone.mcdr" / "games_ai" / "updater.py"))
    assert updater.self_archive_path() is None, \
        f"a .mcdr that is not a file is not used: {updater.self_archive_path()}"


def test_the_direct_source_is_used_first(work, artifact):
    """Section 3b: download -- direct first, mirror second."""
    session = FakeSession([FakeResponse(artifact.body)])

    part = updater.download_release(artifact.release, work, session=session)

    assert session.calls == [artifact.release.url], \
        f"the direct source is used first: {session.calls}"
    assert Path(part).read_bytes() == artifact.body, \
        f"the .part file carries every byte: {len(artifact.body)}"


def test_a_reset_connection_is_retried_on_the_same_source(work, artifact):
    session = FakeSession([ConnectionResetError("reset"), FakeResponse(artifact.body)])

    updater.download_release(artifact.release, work, session=session)

    assert session.calls == [artifact.release.url, artifact.release.url], \
        f"a reset connection is retried on the same source: {session.calls}"


def test_the_mirror_is_only_tried_after_the_direct_source_failed_twice(work, artifact):
    session = FakeSession([ConnectionResetError("reset"), ConnectionResetError("reset"),
                           FakeResponse(artifact.body)])

    updater.download_release(artifact.release, work, session=session)

    assert session.calls == [artifact.release.url, artifact.release.url,
                             artifact.release.proxy_url], \
        f"the mirror is only tried after the direct source failed twice: {session.calls}"


def test_a_truncated_file_is_rejected_and_retried(work, artifact):
    session = FakeSession([FakeResponse(artifact.body[:-10])])          # truncated

    detail = ""
    try:
        updater.download_release(artifact.release, work, session=session)
    except updater.DownloadError as error:
        detail = error.detail
    assert "size mismatch" in detail, f"a truncated file is rejected and retried: {detail}"
    assert not any(name.endswith(".part") for name in os.listdir(work)), \
        f"no .part file survives a failed attempt: {os.listdir(work)}"


def test_a_wrong_sha256_is_rejected(work, artifact):
    session = FakeSession([FakeResponse(b"x" * artifact.release.size)])

    detail = ""
    try:
        updater.download_release(artifact.release, work, session=session)
    except updater.DownloadError as error:
        detail = error.detail
    assert "sha256 mismatch" in detail, f"a wrong sha256 is rejected: {detail}"


def test_both_sources_failing_ends_the_update(work, artifact):
    session = FakeSession([ConnectionResetError("a"), ConnectionResetError("b"),
                           ConnectionResetError("c"), ConnectionResetError("d")])

    detail = ""
    try:
        updater.download_release(artifact.release, work, session=session)
    except updater.DownloadError as error:
        detail = error.detail
    assert "mirror" in detail, f"both sources failing ends the update: {detail}"
    assert len(session.calls) == 4, f"all four attempts were made: {session.calls}"


def test_an_http_error_is_reported_not_accepted(work, artifact):
    session = FakeSession([FakeResponse(artifact.body, status=404)])

    detail = ""
    try:
        updater.download_release(artifact.release, work, session=session)
    except updater.DownloadError as error:
        detail = error.detail
    assert "404" in detail, f"an HTTP error is reported, not accepted: {detail}"


def test_the_archive_itself_is_checked(tmp_path, artifact):
    """Section 4: the archive itself is checked."""
    assert updater.verify_archive(artifact.path, artifact.release) is None, \
        "a good archive passes verification"

    for name, kwargs, needle in [
        ("wrong plugin id", {"plugin_id": "other_plugin"}, "not 'games_ai'"),
        ("wrong version", {"version": "1.2.3"}, "expected '9.9.9'"),
    ]:
        broken = tmp_path / (name.replace(" ", "_") + ".mcdr")
        make_archive(broken, version=kwargs.pop("version", "9.9.9"), **kwargs)
        detail = ""
        try:
            updater.verify_archive(broken, artifact.release)
        except updater.VerifyError as error:
            detail = error.detail
        assert needle in detail, f"rejected: {name}: {detail}"

    no_meta = tmp_path / "no_meta.mcdr"
    with zipfile.ZipFile(no_meta, "w") as archive:
        archive.writestr("games_ai/__init__.py", b"x = 1\n")
    detail = ""
    try:
        updater.verify_archive(no_meta, artifact.release)
    except updater.VerifyError as error:
        detail = error.detail
    assert "mcdreforged.plugin.json" in detail, f"rejected: no metadata file: {detail}"

    not_zip = tmp_path / "not_a_zip.mcdr"
    not_zip.write_bytes(b"this is not a zip file")
    detail = ""
    try:
        updater.verify_archive(not_zip, artifact.release)
    except updater.VerifyError as error:
        detail = error.detail
    assert "not a zip" in detail, f"rejected: not a zip: {detail}"

    corrupt = tmp_path / "corrupt.mcdr"
    make_archive(corrupt, version="9.9.9", truncate_member=True)
    detail = ""
    try:
        updater.verify_archive(corrupt, artifact.release)
    except updater.VerifyError as error:
        detail = error.detail
    assert "corrupt" in detail, f"rejected: corrupt member: {detail}"


def test_preflight_happens_before_anything_is_destroyed(artifact):
    """Section 5: preflight happens before anything is destroyed."""
    key = ""
    try:
        updater.preflight(artifact.release, None)
    except updater.PreflightError as error:
        key = error.key
    assert key == "games_ai.update.not_packed", \
        f"an unpacked install refuses to update itself: {key}"

    assert updater.preflight(artifact.release, artifact.path) is None, \
        "preflight accepts a writable folder with room"


def test_the_swap_unloads_deletes_replaces_and_loads(tmp_path, artifact):
    """Section 6: the swap -- unload -> delete -> replace -> load."""
    live, staged = fresh_plugin_dir(tmp_path / "swap_ok", artifact.path)
    server = FakeServer(version_after_load="9.9.9")

    updater.apply_archive(server, staged, live, artifact.release)

    assert [call[0] for call in server.calls] == ["unload", "load", "metadata"], \
        f"the swap unloads, deletes, replaces and loads, in that order: {server.calls}"
    assert updater.verify_archive(live, artifact.release) is None, \
        "the archive is now the new version"
    assert not staged.exists(), "the staged file was consumed"
    assert not (live.parent / (live.name + ".bak")).exists(), \
        f"the backup is cleaned up after a good load: {sorted(os.listdir(live.parent))}"


def test_a_failed_unload_stops_before_touching_the_file(tmp_path, artifact):
    live, staged = fresh_plugin_dir(tmp_path / "swap_unload_fails", artifact.path)
    server = FakeServer(unload_result=False)

    detail = ""
    try:
        updater.apply_archive(server, staged, live, artifact.release)
    except updater.ReplaceError as error:
        detail = error.detail

    assert "could not be unloaded" in detail, \
        f"a failed unload stops before touching the file: {detail}"
    assert [call[0] for call in server.calls] == ["unload"], \
        f"nothing was loaded after the failed unload: {server.calls}"
    assert live.exists(), "the old archive is untouched"
    assert not staged.exists(), "the staged file was cleaned up"


def test_a_file_windows_still_locks_ends_the_update(tmp_path, artifact, monkeypatch):
    live, staged = fresh_plugin_dir(tmp_path / "swap_delete_locked", artifact.path)
    server = FakeServer(version_after_load="9.9.9")

    def locked_delete(path):
        raise updater.ReplaceError("cannot delete {}: [WinError 32]".format(path))

    monkeypatch.setattr(updater, "_remove_with_retries", locked_delete)

    detail = ""
    try:
        updater.apply_archive(server, staged, live, artifact.release)
    except updater.ReplaceError as error:
        detail = error.detail

    assert "previous file was loaded again" in detail, \
        f"a file Windows still locks ends the update: {detail}"
    assert [call[0] for call in server.calls] == ["unload", "load"], \
        f"the old file is loaded again, so the server keeps GamesAI: {server.calls}"
    assert (live.parent / (live.name + ".bak")).exists(), \
        f"the backup copy is kept for the operator: {sorted(os.listdir(live.parent))}"


def test_a_failed_move_restores_the_previous_file(tmp_path, artifact, monkeypatch):
    live, staged = fresh_plugin_dir(tmp_path / "swap_move_fails", artifact.path)
    server = FakeServer(version_after_load="9.9.9")

    def failing_move(source, target):
        raise updater.ReplaceError("cannot move: [WinError 5]")

    monkeypatch.setattr(updater, "_replace_with_retries", failing_move)

    detail = ""
    try:
        updater.apply_archive(server, staged, live, artifact.release)
    except updater.ReplaceError as error:
        detail = error.detail

    assert "previous file was restored" in detail, \
        f"a failed move restores the previous file: {detail}"
    assert live.exists() and [call[0] for call in server.calls] == ["unload", "load"], \
        f"the old archive is back on disk and loaded: {server.calls}"


def test_a_refused_load_rolls_back(tmp_path, artifact):
    live, staged = fresh_plugin_dir(tmp_path / "swap_load_fails", artifact.path)
    server = FakeServer(load_results=[False], version_after_load="8.8.8")

    detail = ""
    try:
        updater.apply_archive(server, staged, live, artifact.release)
    except updater.LoadError as error:
        detail = error.detail

    assert "previous version was restored" in detail, f"a refused load rolls back: {detail}"
    assert [call[0] for call in server.calls] == ["unload", "load", "load"], \
        f"the rollback loaded the old file again: {server.calls}"
    assert zipfile.ZipFile(live).read("mcdreforged.plugin.json").find(b"8.8.8") > 0, \
        f"the file on disk is the old version again: {zipfile.ZipFile(live).read('mcdreforged.plugin.json')}"


def test_a_loaded_version_that_is_not_the_target_rolls_back(tmp_path, artifact):
    live, staged = fresh_plugin_dir(tmp_path / "swap_wrong_version", artifact.path)
    server = FakeServer(version_after_load="0.0.1")

    detail = ""
    try:
        updater.apply_archive(server, staged, live, artifact.release)
    except updater.LoadError as error:
        detail = error.detail

    assert "expected '9.9.9'" in detail, \
        f"a loaded version that is not the target rolls back: {detail}"
    assert [call[0] for call in server.calls] == ["unload", "load", "metadata", "unload", "load"], \
        f"the rollback unloads the wrong build before restoring and loading the old one: {server.calls}"
    assert zipfile.ZipFile(live).read("mcdreforged.plugin.json").find(b"8.8.8") > 0, \
        ("the file on disk is the old version after that rollback: "
         f"{zipfile.ZipFile(live).read('mcdreforged.plugin.json')}")


def test_a_rollback_that_cannot_prepare_its_copy_says_so(tmp_path, artifact, monkeypatch):
    live, staged = fresh_plugin_dir(tmp_path / "swap_restore_copy_fails", artifact.path)
    server = FakeServer(load_results=[False], version_after_load="8.8.8")
    # The real copy2 is kept aside: the rollback still has to back up the file, only the
    # `.restore` copy is made to fail. monkeypatch puts shutil.copy2 back by itself.
    real_copy = shutil.copy2

    def failing_copy(source, destination, *args, **kwargs):
        if str(destination).endswith(".restore"):
            raise OSError("[Errno 28] No space left on device")
        return real_copy(source, destination, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2", failing_copy)

    detail = ""
    try:
        updater.apply_archive(server, staged, live, artifact.release)
    except updater.LoadError as error:
        detail = error.detail

    assert "could not be restored" in detail, \
        f"a rollback that cannot even prepare its copy says so instead of claiming success: {detail}"
    assert live.exists(), \
        f"the live archive is still there when the rollback copy cannot be made: {sorted(os.listdir(live.parent))}"
    assert server.calls[-1][0] == "load", \
        f"and the plugin was loaded from it (never left with nothing to load): {server.calls}"


def test_the_whole_update_runs(tmp_path, artifact, monkeypatch):
    """Section 7: the whole update."""
    folder = tmp_path / "end_to_end"
    folder.mkdir()
    live = folder / "GamesAI-v8.8.8.mcdr"
    make_archive(live, version="8.8.8")
    monkeypatch.setattr(updater, "__file__", str(live / "games_ai" / "updater.py"))
    server = FakeServer(version_after_load="9.9.9")
    session = FakeSession([FakeResponse(artifact.body)])

    failure = ""
    try:
        updater.run_self_update(server, artifact.release, session=session)
    except Exception as error:                       # noqa: BLE001 - the probe wants the reason
        failure = repr(error)

    assert not failure, f"the end-to-end update runs: {failure}"
    assert updater.verify_archive(live, artifact.release) is None, \
        "the live file is the new release"
    assert sorted(os.listdir(folder)) == ["GamesAI-v8.8.8.mcdr"], \
        f"nothing extra is left in the plugin folder: {sorted(os.listdir(folder))}"


def test_an_unpacked_install_never_even_downloads(artifact):
    session = FakeSession([])

    key = ""
    try:
        updater.run_self_update(FakeServer(), artifact.release, session=session)
    except updater.PreflightError as error:
        key = error.key

    assert key == "games_ai.update.not_packed", \
        f"an unpacked install never even downloads: {key}"


def test_the_updater_never_hands_the_work_back_to_pim():
    """The prose may mention MCDR's installer; a *call* that hands the work back must not exist."""
    offenders = []
    targets = []
    for path in sorted(Path(PKG).rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for literal in re.findall(r"execute_command\(\s*[\"']([^\"']*)[\"']", text):
            targets.append((path.name, literal))
            if literal.startswith("!!MCDR"):
                offenders.append((path.name, literal))

    assert offenders == [], f"no source calls a !!MCDR command (no PIM fallback): {offenders}"
    assert all(literal.startswith("!!gamesai") for _, literal in targets), \
        f"every execute_command target is a GamesAI command: {targets}"
    assert "os.replace" in (Path(PKG) / "updater.py").read_text(encoding="utf-8"), \
        "updater.py is the only file that replaces the archive"
