"""The server-change note: once per change, only inside a real cluster."""
import os
import threading
import types

import pytest

import games_ai


class FakeServer:
    def rtr(self, key, **kw):
        return "[" + key.split(".")[-1] + " " + ",".join("{}={}".format(k, v) for k, v in sorted(kw.items())) + "]"


class FakeSource:
    def __init__(self, player="Steve", origin=None, console=False):
        self.player = None if console else player
        self.origin = origin
        self.console = console

    def get_server(self):
        return FakeServer()

    @property
    def is_console(self):
        return self.console


class FakeParam:
    def __init__(self):
        self.notes = []
        self.threads = []

    def add_to_response_list(self, type_, content, **kw):
        self.notes.append(content)
        self.threads.append(threading.current_thread().name)


class FakeHub:
    def __init__(self, peers=(), is_client=False, name="hub"):
        self.peers = list(peers)
        self.is_client = is_client
        self.name = name
        self.hub = None


@pytest.fixture
def param():
    return FakeParam()


@pytest.fixture
def cluster(monkeypatch):
    """The plugin's cross-server globals: a real cluster (one peer), no player recorded yet.

    ``monkeypatch`` rebinds both globals and restores them however the test ends, so no test can
    leak a fake hub into the next one.
    """
    monkeypatch.setattr(games_ai, "_cross_server", FakeHub(peers=["other"]), raising=False)
    monkeypatch.setattr(games_ai, "_player_servers", {}, raising=False)
    return games_ai


def test_a_standalone_instance_announces_nothing(monkeypatch, param):
    monkeypatch.setattr(games_ai, "_cross_server", None, raising=False)

    games_ai._note_player_server(FakeSource(origin="survival"), param)

    assert param.notes == [], f"a standalone instance announces nothing: {param.notes}"


def test_local_mode_with_no_peers_announces_nothing(monkeypatch, param):
    monkeypatch.setattr(games_ai, "_cross_server", FakeHub(peers=[]), raising=False)

    games_ai._note_player_server(FakeSource(origin="survival"), param)

    assert param.notes == [], f"local mode with no peers announces nothing: {param.notes}"


def test_the_first_message_names_the_server(cluster, param):
    games_ai._note_player_server(FakeSource(origin="survival"), param)

    assert len(param.notes) == 1 and "server_here" in param.notes[0], \
        f"the first message names the server: {param.notes}"


def test_the_same_server_again_is_silent(cluster, param):
    games_ai._note_player_server(FakeSource(origin="survival"), param)
    games_ai._note_player_server(FakeSource(origin="survival"), param)

    assert len(param.notes) == 1, f"the same server again is silent: {param.notes}"


def test_a_move_is_announced_with_both_names(cluster, param):
    games_ai._note_player_server(FakeSource(origin="survival"), param)
    games_ai._note_player_server(FakeSource(origin="creative"), param)

    assert (len(param.notes) == 2 and "server_moved" in param.notes[1]
            and "previous=survival" in param.notes[1] and "server=creative" in param.notes[1]), \
        f"a move is announced with both names: {param.notes}"


def test_and_then_silent_again(cluster, param):
    games_ai._note_player_server(FakeSource(origin="survival"), param)
    games_ai._note_player_server(FakeSource(origin="creative"), param)
    games_ai._note_player_server(FakeSource(origin="creative"), param)

    assert len(param.notes) == 2, f"and then silent again: {param.notes}"


def test_a_console_is_not_tracked(cluster, param):
    games_ai._note_player_server(FakeSource(origin="survival"), param)
    games_ai._note_player_server(FakeSource(origin="creative"), param)
    games_ai._note_player_server(FakeSource(player=None, origin="creative", console=True), param)

    assert len(param.notes) == 2, f"a console is not tracked: {param.notes}"


def test_a_client_that_sends_locally_uses_its_own_name(cluster, monkeypatch, param):
    games_ai._note_player_server(FakeSource(origin="survival"), param)
    games_ai._note_player_server(FakeSource(origin="creative"), param)
    monkeypatch.setattr(games_ai, "_cross_server",
                        FakeHub(peers=[], is_client=True, name="this-client"), raising=False)

    games_ai._note_player_server(FakeSource(player="Alex"), param)

    assert len(param.notes) == 3 and "server=this-client" in param.notes[2], \
        f"a client that sends locally uses its own name: {param.notes}"


def test_hopping_without_an_ai_request_records_one_move(cluster, param):
    """The case the operator asked about: hopping with no AI request in between.

    survival -> creative -> survival -> creative -> survival, without one AI request between the
    steps: the tracking only samples at request time, so none of that is written down and the next
    ask finds the recorded server unchanged.
    """
    games_ai._note_player_server(FakeSource(origin="survival"), param)
    assert len(param.notes) == 1, f"the first ask records where the player is: {param.notes}"

    games_ai._note_player_server(FakeSource(origin="survival"), param)
    assert len(param.notes) == 1, f"returning to the recorded server adds nothing: {param.notes}"

    games_ai._note_player_server(FakeSource(origin="creative"), param)
    assert len(param.notes) == 2 and "previous=survival" in param.notes[1], \
        f"the next ask adds one move, not one per hop: {param.notes}"

    games_ai._note_player_server(FakeSource(origin="creative"), param)
    assert len(param.notes) == 2, f"asking twice on the new server stays at one move: {param.notes}"


def test_the_note_is_written_on_the_callers_thread(cluster, param):
    games_ai._note_player_server(FakeSource(origin="survival"), param)
    games_ai._note_player_server(FakeSource(origin="creative"), param)

    assert param.threads == [threading.current_thread().name] * len(param.threads), \
        f"the note is written on the caller's thread, never @new_thread: {param.threads}"


def test_eight_racing_asks_produce_one_note(cluster, param):
    gate = threading.Barrier(8)

    def racer():
        gate.wait()
        games_ai._note_player_server(FakeSource(origin="survival"), param)

    racers = [threading.Thread(target=racer) for _ in range(8)]
    for thread in racers:
        thread.start()
    for thread in racers:
        thread.join()

    assert len(param.notes) == 1, f"eight racing asks produce one note: {param.notes}"


def test_the_map_can_be_cleared_on_unload(cluster):
    games_ai._player_servers["survival"] = "Steve"

    games_ai._player_servers.clear()

    assert games_ai._player_servers == {}, "the map can be cleared on unload"


def test_the_remembered_role_round_trips_through_the_data_folder(tmp_path):
    """Section 10: the remembered cross-server role round-trips through the data folder."""
    data_folder = str(tmp_path)
    fake_server = types.SimpleNamespace(get_data_folder=lambda: data_folder)
    role_path = os.path.join(data_folder, "cross_server", "role.json")

    assert games_ai._read_cross_server_role(fake_server) is None, "no file yet -> no hint"

    games_ai._save_cross_server_role(fake_server, "client")
    assert games_ai._read_cross_server_role(fake_server) == "client", \
        "a saved client role is remembered"
    assert os.path.isfile(role_path), "and it lives in the plugin data folder"

    games_ai._save_cross_server_role(fake_server, "server")
    assert games_ai._read_cross_server_role(fake_server) == "server", "a later save replaces it"

    with open(role_path, "w", encoding="utf-8") as handle:
        handle.write("{ not json")
    assert games_ai._read_cross_server_role(fake_server) is None, \
        "a corrupt file reads as no hint instead of raising"

    games_ai._save_cross_server_role(fake_server, "nonsense")
    assert games_ai._read_cross_server_role(fake_server) is None, "an unknown role is not stored"
