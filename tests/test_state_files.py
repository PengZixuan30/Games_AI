"""The cross-server runtime state lives in `<data folder>/cross_server/`, and old files move there.

Three files belong to the link and none of them may be lost by the move:

* ``identity.json`` -- this node's own token (a node that loses it gets 4001 and needs a new one);
* ``nodes.json``    -- the hub's node table (losing it invalidates every enrolled node's token);
* ``role.json``     -- the role this instance held on its last load (used against role swaps).

So the migration is part of the contract, not a convenience: an installation that is already
enrolled must keep working without re-claiming anything, and when the move cannot happen at all
the previous location is used for that load instead of pretending there is no identity.
"""
import json
import logging
import os

import pytest

import games_ai
from games_ai.config import plugin_config
from games_ai.websockets_server import APP_ID, CrossServerHub


class RecordingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


class FakeServer:
    """What the state-path helpers ask of a server: its data folder and a logger."""

    def __init__(self, folder):
        self._folder = folder
        self.logger = logging.getLogger("gamesai_state_{}".format(id(self)))
        self.logger.propagate = False
        self.logger.setLevel(logging.DEBUG)
        self.handler = RecordingHandler()
        self.logger.addHandler(self.handler)

    def get_data_folder(self):
        return self._folder

    def logged(self, needle):
        return [line for line in self.handler.lines if needle in line]


@pytest.fixture
def make_server(tmp_path, monkeypatch):
    """One load's worth of state: a fake server, its own data folder, a fresh migration cache.

    ``games_ai.logger.attach`` wires the fake logger into the plugin's stdlib logger for the
    duration of the test only -- the plugin logger must not keep a handler of a server that no
    longer exists, or a later suite's records would be written into this test's recorder.
    """
    original_log_server = games_ai.logger._server
    plugin_logger = logging.getLogger(games_ai.logger.PLUGIN_LOGGER_NAME)
    original_propagate, original_level = plugin_logger.propagate, plugin_logger.level
    attached = []

    def _make(tag):
        folder = tmp_path / tag
        folder.mkdir(parents=True, exist_ok=True)
        server = FakeServer(str(folder))
        monkeypatch.setattr(games_ai, "_server_ref", server)          # what on_load stores
        games_ai.logger.attach(server)
        monkeypatch.setattr(games_ai, "_state_files_seen", set(), raising=False)
        attached.append(server)
        return server

    yield _make

    for server in attached:
        plugin_logger.removeHandler(server.handler)
    plugin_logger.propagate, plugin_logger.level = original_propagate, original_level
    games_ai.logger._server = original_log_server


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def test_the_three_paths_point_into_cross_server(make_server):
    server = make_server("paths")
    data = server.get_data_folder()

    assert games_ai._identity_path(server) == os.path.join(data, "cross_server", "identity.json"), \
        f"identity path: {games_ai._identity_path(server)}"
    assert games_ai._node_table_path(server) == os.path.join(data, "cross_server", "nodes.json"), \
        f"node table path: {games_ai._node_table_path(server)}"
    assert games_ai._cross_server_role_path(server) == \
        os.path.join(data, "cross_server", "role.json"), \
        f"role path: {games_ai._cross_server_role_path(server)}"
    assert os.path.isdir(os.path.join(data, "cross_server")), \
        f"the folder is created by the lookup: {os.listdir(data)}"


def test_the_writers_work_in_the_new_folder(make_server):
    server = make_server("writers")
    data = server.get_data_folder()

    saved = games_ai._save_identity(server, "me", "tok-123", "ws://hub:1")
    assert saved == os.path.join(data, "cross_server", "identity.json") and os.path.isfile(saved), \
        f"_save_identity writes into cross_server/: {saved}"

    games_ai._save_cross_server_role(server, "client")
    assert read_json(os.path.join(data, "cross_server", "role.json")) == {"role": "client"}, \
        f"_save_cross_server_role writes there too: {os.listdir(os.path.join(data, 'cross_server'))}"

    hub = CrossServerHub("127.0.0.1", 0, name="hub",
                         node_file=games_ai._node_table_path(server))
    token = hub.issue("node-b", app=APP_ID)
    assert bool(token) and os.path.isfile(os.path.join(data, "cross_server", "nodes.json")), \
        f"the hub's node table lands there as well: {os.listdir(os.path.join(data, 'cross_server'))}"
    assert read_json(os.path.join(data, "cross_server", "nodes.json"))["nodes"] \
        .get("node-b", {}).get("hash") == hub.nodes["node-b"]["hash"], \
        "and it is readable again"


def test_an_old_installation_is_migrated(make_server):
    server = make_server("migrate_identity")
    data = server.get_data_folder()
    write_json(os.path.join(data, "cross_server_identity.json"),
               {"name": "me", "token": "tok-old", "hub": "ws://hub:1", "issued_at": 1})

    identity = games_ai._load_identity(server)
    assert identity is not None and identity["token"] == "tok-old", \
        f"the old identity is found: {identity}"
    assert os.path.isfile(os.path.join(data, "cross_server", "identity.json")), \
        "it now lives in cross_server/identity.json"
    assert not os.path.exists(os.path.join(data, "cross_server_identity.json")), \
        "the old file is gone"
    assert bool(server.logged("Cross-server state moved")), \
        f"the move is logged for the operator: {server.handler.lines}"

    server = make_server("migrate_table")
    data = server.get_data_folder()
    write_json(os.path.join(data, "cross_server_nodes.json"),
               {"nodes": {"node-b": {"hash": "abc"}}, "pending": {}})
    written = CrossServerHub("127.0.0.1", 0, name="hub",
                             node_file=games_ai._node_table_path(server))
    assert "node-b" in written.nodes and written.nodes["node-b"]["hash"] == "abc", \
        f"an old node table is migrated and read back: {written.nodes}"
    assert not os.path.exists(os.path.join(data, "cross_server_nodes.json")), \
        "...and the old file is gone"

    server = make_server("migrate_role")
    data = server.get_data_folder()
    write_json(os.path.join(data, "cross_server_role.json"), {"role": "client"})
    assert games_ai._read_cross_server_role(server) == "client", \
        f"an old role memory is migrated and still wins: {games_ai._read_cross_server_role(server)}"
    assert not os.path.exists(os.path.join(data, "cross_server_role.json")), \
        "...and the old file is gone"


def test_both_locations_present_the_new_one_wins(make_server):
    server = make_server("both")
    data = server.get_data_folder()
    write_json(os.path.join(data, "cross_server", "identity.json"),
               {"name": "me", "token": "tok-new", "hub": "ws://hub:1", "issued_at": 2})
    write_json(os.path.join(data, "cross_server_identity.json"),
               {"name": "me", "token": "tok-old", "hub": "ws://hub:1", "issued_at": 1})

    identity = games_ai._load_identity(server)
    assert identity and identity["token"] == "tok-new", f"the new file is what is read: {identity}"
    assert os.path.isfile(os.path.join(data, "cross_server_identity.json")), \
        "the old file is not deleted"
    assert len(server.logged("leaving the old file alone")) == 1, \
        f"and the operator is warned once: {server.handler.lines}"


def test_a_migration_that_cannot_happen_keeps_the_old_file_in_use(make_server):
    server = make_server("blocked")
    data = server.get_data_folder()
    write_json(os.path.join(data, "cross_server_identity.json"),
               {"name": "me", "token": "tok-blocked", "hub": "ws://hub:1", "issued_at": 1})
    # `cross_server` as a *file*: the folder cannot be created, so the move must not happen.
    with open(os.path.join(data, "cross_server"), "w", encoding="utf-8") as handle:
        handle.write("not a folder")

    path = games_ai._identity_path(server)
    assert path == os.path.join(data, "cross_server_identity.json"), \
        f"the previous location is used for this load: {path}"
    identity = games_ai._load_identity(server)
    assert identity and identity["token"] == "tok-blocked", f"...so the token is not lost: {identity}"
    assert bool(server.logged("Could not move")), f"the failure is logged: {server.handler.lines}"


def test_websocket_identity_file_still_overrides_everything(make_server, tmp_path, monkeypatch):
    server = make_server("override")
    data = server.get_data_folder()
    custom = str(tmp_path / "custom" / "my_identity.json")
    monkeypatch.setattr(plugin_config, "websocket_identity_file", custom)
    write_json(os.path.join(data, "cross_server_identity.json"),
               {"name": "me", "token": "tok-old", "hub": "ws://hub:1", "issued_at": 1})

    assert games_ai._identity_path(server) == custom, \
        f"the override is used verbatim: {games_ai._identity_path(server)}"
    assert os.path.isfile(os.path.join(data, "cross_server_identity.json")), \
        "an overridden path is not migrated"
    assert games_ai._load_identity(server) is None, "and no identity is invented there"

    saved = games_ai._save_identity(server, "me", "tok-custom", "ws://hub:1")
    assert saved == custom and os.path.isfile(custom), f"claiming writes the overridden file: {saved}"


def test_no_data_folder_means_no_path_and_nothing_raises(monkeypatch):
    monkeypatch.setattr(games_ai, "_server_ref", None)     # no fallback to the load's server either

    class NoFolder:
        def get_data_folder(self):
            return None

    class BrokenFolder:
        def get_data_folder(self):
            raise RuntimeError("MCDR is not ready")

    for label, target in (("an empty answer", NoFolder()), ("an asking failure", BrokenFolder())):
        assert games_ai._identity_path(target) is None, f"identity path is None for {label}"
        assert games_ai._node_table_path(target) is None, f"node table path is None for {label}"
        assert games_ai._cross_server_role_path(target) is None, f"role path is None for {label}"
