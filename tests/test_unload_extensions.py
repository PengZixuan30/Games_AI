"""A queued plugin unload is not a missing plugin.

``on_unload`` runs inside MCDR's own plugin-operation chain, so a nested ``unload_plugin`` cannot
run synchronously: ``PluginManager.__run_manipulation`` queues it and returns an unfinished future,
and ``ServerInterface.__existed_regular_plugin_manipulate`` turns that future into ``None`` -- the
same value its docstring uses for "plugin not found". Interpreting it as "not found" printed a
misleading WARNING for every registered extension on every unload/reload and dropped the entry
early. The unload attempt is still made (and MCDR's dependency collection also unloads dependents);
only the verdict is now decided by whether MCDR still has a loaded instance of that plugin.
"""
import logging
import threading

import pytest

import games_ai


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def messages(self, level=None):
        return [str(record.getMessage()) for record in self.records
                if level is None or record.levelno == level]

    def warnings(self):
        return self.messages(logging.WARNING)

    def infos(self):
        return self.messages(logging.INFO)

    def exceptions(self):
        return [record for record in self.records if record.exc_info]


class RecordingDict(dict):
    """A registry that remembers the individual entries removed by ``pop``."""

    def __init__(self, values):
        super().__init__(values)
        self.popped = []

    def pop(self, key, *default):
        self.popped.append(key)
        return super().pop(key, *default)


class FakeServer:
    """What the unload path asks of MCDR: a logger, rtr/say, and the plugin operations."""

    def __init__(self, results=None, loaded=None):
        self.logger = logging.getLogger("unload-extension-server")
        self.results = dict(results or {})
        self.loaded = set(loaded or ())
        self.unload_calls = []
        self.said = []

    def rtr(self, key, **kwargs):
        return key

    def say(self, message, **kwargs):
        self.said.append(str(message))

    def unload_plugin(self, plugin_id):
        self.unload_calls.append(plugin_id)
        return self.results.get(plugin_id)

    def get_plugin_instance(self, plugin_id):
        return object() if plugin_id in self.loaded else None


class RaisingServer(FakeServer):
    def unload_plugin(self, plugin_id):
        if plugin_id == "raising_ext":
            self.unload_calls.append(plugin_id)
            raise RuntimeError("the plugin host refused the operation")
        return super().unload_plugin(plugin_id)


class HostWithoutInstanceGetter(FakeServer):
    def get_plugin_instance(self, plugin_id):
        raise TypeError("this host does not implement the instance getter")


class FakeThread:
    def is_alive(self):
        return False


@pytest.fixture
def run_unload(monkeypatch):
    """Run ``on_unload`` with everything outside the log path neutralised."""
    monkeypatch.setattr(games_ai, "_deps_pending", False, raising=False)
    monkeypatch.setattr(games_ai, "_history_frozen", False, raising=False)
    monkeypatch.setattr(games_ai, "_restore_thread_excepthook", lambda: None, raising=False)
    monkeypatch.setattr(games_ai, "_stop_cross_server", lambda server: None, raising=False)
    monkeypatch.setattr(games_ai.update_round, "stop_timer", lambda: None, raising=False)
    monkeypatch.setattr(games_ai.update_round, "unload_status", lambda: 0, raising=False)
    monkeypatch.setattr(games_ai.database, "close_public_database", lambda: None, raising=False)
    monkeypatch.setattr(games_ai, "_teardown_bot_async", lambda server: FakeThread(), raising=False)
    teardown_event = threading.Event()
    teardown_event.set()
    monkeypatch.setattr(games_ai, "_bot_teardown_event", teardown_event, raising=False)
    previous_abort = games_ai._mineflayer_pending_abort.is_set()
    previous_wait = games_ai._mineflayer_wait_thread

    def run(server, entries):
        capture = LogCapture()
        server.logger.addHandler(capture)
        server.logger.setLevel(logging.DEBUG)
        server.logger.propagate = False
        monkeypatch.setattr(games_ai, "REGISTER_PLUGIN_LIST", entries, raising=False)
        try:
            games_ai.on_unload(server)
        finally:
            server.logger.removeHandler(capture)
            server.logger.setLevel(logging.NOTSET)
            server.logger.propagate = True
        return capture

    try:
        yield run
    finally:
        if previous_abort:
            games_ai._mineflayer_pending_abort.set()
        else:
            games_ai._mineflayer_pending_abort.clear()
        games_ai._mineflayer_wait_thread = previous_wait


def test_a_queued_unload_is_logged_as_queued_not_as_not_found(run_unload):
    server = FakeServer({"loaded_ext": None}, {"loaded_ext"})
    entries = RecordingDict({"loaded_ext": None})

    capture = run_unload(server, entries)

    assert server.unload_calls == ["loaded_ext"], "the unload attempt is still made"
    assert any("queued by MCDR" in line for line in capture.infos()), \
        f"a queued unload says it was queued: {capture.infos()}"
    assert not any("not found" in line for line in capture.warnings()), \
        f"a queued unload is not reported as a missing plugin: {capture.warnings()}"
    assert entries.popped == [], "a queued unload does not drop its entry"


def test_a_plugin_that_really_is_gone_is_still_reported(run_unload):
    server = FakeServer({"gone_ext": None}, set())
    entries = RecordingDict({"gone_ext": None})

    capture = run_unload(server, entries)

    assert any("not found" in line for line in capture.warnings()), \
        f"a plugin MCDR no longer has is still reported: {capture.warnings()}"
    assert entries.popped == ["gone_ext"], "and only the stale entry is removed"


def test_a_failed_unload_is_still_reported(run_unload):
    server = FakeServer({"failed_ext": False}, {"failed_ext"})
    entries = RecordingDict({"failed_ext": None})

    capture = run_unload(server, entries)

    assert any("Failed to unload" in line for line in capture.warnings()), \
        f"a failure is reported: {capture.warnings()}"
    assert entries.popped == [], "a failed unload keeps its entry"


def test_one_raising_plugin_does_not_stop_the_others(run_unload):
    server = RaisingServer({"ok_ext": True}, set())
    entries = RecordingDict({"raising_ext": None, "ok_ext": None})

    capture = run_unload(server, entries)

    assert server.unload_calls == ["raising_ext", "ok_ext"], "the next entry is still attempted"
    assert len(capture.exceptions()) == 1, "the failure is logged with its traceback"
    assert entries.popped == [], "neither entry was dropped"


def test_a_host_without_the_instance_getter_falls_back_to_not_found(run_unload):
    server = HostWithoutInstanceGetter({"gone_ext": None}, set())
    entries = RecordingDict({"gone_ext": None})

    capture = run_unload(server, entries)

    assert any("not found" in line for line in capture.warnings()), \
        f"a host that cannot answer the instance question keeps the old reading: {capture.warnings()}"
    assert entries.popped == ["gone_ext"]
