"""What an update check says, and to whom.

The check the plugin runs by itself -- on load and every 24 h -- must not broadcast that it is
checking or that there is nothing new: that is a line per load, for a decision nobody on the
server is waiting for, and it used to reach every player. It announces a release when it actually
finds one (and then the round that installs it), and a check that *fails* stays visible, because
that one does need an operator. ``!!gamesai check`` keeps every line: somebody typed it and is
waiting for the answer, and only that caller is answered.
"""
import json
import logging
import lzma

import pytest

from games_ai.cluster.cross_server import MODE_LOCAL
from games_ai.core.config import plugin_config
from games_ai.update import update_round


class FakeServer:
    """The three calls ``update()`` makes: a logger, ``say()`` and ``rtr()``."""

    def __init__(self):
        self.logger = logging.getLogger("gamesai_notice")
        self.said = []

    def say(self, text):
        self.said.append(str(text))

    def rtr(self, key, **kwargs):
        return key + ("|{}".format(kwargs["version"]) if "version" in kwargs else "")


class FakeSource:
    """A command source: the server it belongs to, and the channel it is answered on."""

    def __init__(self):
        self.server = FakeServer()
        self.replies = []

    def get_server(self):
        return self.server

    def reply(self, text):
        self.replies.append(str(text))


def catalogue(version: str = "1.0.0", status: int = 200):
    """A catalogue reply shaped the way the checker reads it, really lzma-compressed."""
    payload = {"plugins": {"games_ai": {"release": {"releases": [{"meta": {"version": version}}]}}}}

    class Reply:
        status_code = status
        content = lzma.compress(json.dumps(payload).encode("utf-8"))

    return Reply()


@pytest.fixture
def checker(monkeypatch):
    """``update()`` without a network: the catalogue is faked per test, the context table is left
    alone, and this instance runs a version the fake releases compare against. Returns the debug
    lines the run produced."""
    debug_lines: list = []
    monkeypatch.setattr(update_round.context_table, "refresh_table", lambda *args, **kwargs: None)
    monkeypatch.setattr(update_round, "_version", "1.0.0")
    monkeypatch.setattr(update_round.logger, "verbose",
                        lambda server, message, **kwargs: debug_lines.append(str(message)))
    return debug_lines


def answers(monkeypatch, reply):
    """Make the catalogue request return ``reply``."""
    monkeypatch.setattr(update_round.requests, "get", lambda *args, **kwargs: reply)


def test_the_loop_is_silent_when_there_is_nothing_to_report(monkeypatch, checker):
    server = FakeServer()
    answers(monkeypatch, catalogue("1.0.0"))

    update_round.update(server, announce=False)

    assert server.said == [], f"the loop broadcasts nothing at all: {server.said}"
    assert any("no release newer" in line for line in checker), \
        f"it says so in the debug log instead: {checker}"


def test_the_loop_announces_the_release_it_finds(monkeypatch, checker):
    server = FakeServer()
    answers(monkeypatch, catalogue("2.0.0"))
    installed: list = []
    monkeypatch.setattr(update_round, "self_update",
                        lambda server, entry, version: installed.append(version))

    update_round.update(server, announce=False)

    assert installed == ["2.0.0"], "the release is handed to the updater"
    assert len(server.said) == 1, f"one line, and only that one: {server.said}"
    assert "games_ai.update.new_update" in server.said[0] and "2.0.0" in server.said[0], \
        f"it is the announcement of the new version: {server.said}"
    assert not any("checking_update" in line for line in server.said), \
        f"never the check itself: {server.said}"


def test_a_failed_check_is_still_reported(monkeypatch, checker):
    server = FakeServer()
    answers(monkeypatch, catalogue(status=503))

    update_round.update(server, announce=False)

    assert len(server.said) == 1 and "games_ai.update.no_metadata" in server.said[0], \
        f"a check that could not run is not silenced: {server.said}"


def test_a_typed_check_reports_the_check_and_the_result(monkeypatch, checker):
    server = FakeServer()
    answers(monkeypatch, catalogue("1.0.0"))
    replies: list = []

    update_round.update(server, force_table=True, notify=replies.append)

    assert any("games_ai.update.checking_update" in line for line in replies), \
        f"whoever typed it is told that a check is running: {replies}"
    assert any("games_ai.update.no_update" in line for line in replies), \
        f"and what it found: {replies}"
    assert server.said == [], f"the answer goes to that caller, not to the server: {server.said}"


def test_the_command_runs_the_same_check_without_silencing_it(monkeypatch, checker):
    source = FakeSource()
    calls: list = []
    monkeypatch.setattr(update_round, "update", lambda server, **kwargs: calls.append(kwargs))

    update_round.check_update.__wrapped__(source, {})

    assert len(calls) == 1, f"one check per command: {calls}"
    assert calls[0].get("force_table") is True, "the command bypasses the 24 h TTL"
    assert calls[0].get("notify") == source.reply, "and answers whoever typed it"
    assert calls[0].get("announce", True) is True, f"it keeps its lines: {calls[0]}"


def test_the_loop_check_is_the_quiet_one(monkeypatch, checker):
    """The load-time check and the 24 h ones are the same call, and both ask for silence."""
    monkeypatch.setattr(plugin_config, "cross_server_mode", MODE_LOCAL)
    monkeypatch.setattr(update_round, "_timer", None)
    calls: list = []
    monkeypatch.setattr(update_round, "update", lambda server, **kwargs: calls.append(kwargs))

    try:
        update_round.cyclic_check_updates(FakeServer())
    finally:
        update_round.stop_timer()

    assert calls == [{"announce": False}], f"the loop asks for the quiet check: {calls}"
