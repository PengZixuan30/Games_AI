"""A cross-server client never runs the 24 h update check loop.

The hub decides about updates for the cluster, so a client must not check (and must never
update itself): that would break the ordering the round depends on. This pins both places
where the decision is made -- the start of the loop after the role settles, and the guard at
the top of every cycle (the role can change without a reload, via !!gamesai node claim).
"""
import logging
import re
import threading
import time
from pathlib import Path

import pytest

from _helpers.paths import PKG
import games_ai
from games_ai import update_round
from games_ai.config import plugin_config
from games_ai.cross_server import MODE_CLIENT, MODE_LOCAL, MODE_SERVER

# The real per-cycle guard, captured before any test replaces the module attribute.
REAL_CYCLIC_CHECK_UPDATES = update_round.cyclic_check_updates


class FakeServer:
    """What the loop asks of a PluginServerInterface: a logger, say(), rtr()."""

    def __init__(self):
        self.logger = logging.getLogger("gamesai_loop")
        self.said = []

    def say(self, text):
        self.said.append(text)

    def rtr(self, key, **kwargs):
        return key


@pytest.fixture
def server():
    return FakeServer()


@pytest.fixture
def stubbed(monkeypatch):
    """The two calls a started loop is allowed to make, recorded instead of performed."""
    started = []

    def fake_loop(server):
        started.append(server)

    def fake_update(server, force_table=False):
        started.append(("update", server))

    monkeypatch.setattr(update_round, "cyclic_check_updates", fake_loop)
    monkeypatch.setattr(update_round, "update", fake_update)
    return started


@pytest.fixture(autouse=True)
def loop_state(monkeypatch):
    """Each test decides the role and the armed timer for itself; both are put back after."""
    monkeypatch.setattr(update_round, "_update_loop_started", False)
    monkeypatch.setattr(update_round, "_timer", None)
    yield
    timer = update_round._timer
    if isinstance(timer, threading.Timer):
        timer.cancel()


def test_a_client_never_starts_the_loop(server, stubbed, monkeypatch):
    """Section 1: a client never starts the loop."""
    monkeypatch.setattr(plugin_config, "cross_server_mode", MODE_CLIENT)

    update_round._start_update_loop(server)
    time.sleep(0.3)

    assert stubbed == [] and not update_round._update_loop_started, \
        f"nothing was started: {(stubbed, update_round._update_loop_started)}"
    assert not any(t.name == "games_ai@update_loop" for t in threading.enumerate()), \
        f"no games_ai@update_loop thread exists: {[t.name for t in threading.enumerate()]}"


def test_a_pending_role_does_not_start_it_either(server, stubbed, monkeypatch):
    """Section 2: a pending role does not start it either (the role is not in yet)."""
    monkeypatch.setattr(plugin_config, "cross_server_mode", "pending")

    update_round._start_update_loop(server)
    time.sleep(0.2)

    assert stubbed == [] and not update_round._update_loop_started, \
        f"nothing was started while the role is pending: {(stubbed, update_round._update_loop_started)}"


def test_the_hub_and_a_standalone_instance_do_start_it(server, stubbed, monkeypatch):
    """Section 3: the hub and a standalone instance do start it."""
    for role in (MODE_SERVER, MODE_LOCAL):
        monkeypatch.setattr(update_round, "_update_loop_started", False)
        stubbed.clear()
        monkeypatch.setattr(plugin_config, "cross_server_mode", role)

        update_round._start_update_loop(server)
        time.sleep(0.3)
        assert stubbed == [server], f"the loop starts for role {role!r}: {(role, stubbed)}"

        update_round._start_update_loop(server)
        time.sleep(0.2)
        assert len(stubbed) == 1, \
            f"starting it twice does not add a second loop for {role!r}: {stubbed}"


def test_the_per_cycle_guard_stops_a_loop_that_is_already_running(server, stubbed, monkeypatch):
    """Section 4: the per-cycle guard stops a loop that is already running."""
    monkeypatch.setattr(plugin_config, "cross_server_mode", MODE_CLIENT)

    REAL_CYCLIC_CHECK_UPDATES(server)

    assert stubbed == [], f"update() is not called on a client: {stubbed}"
    assert update_round._timer is None, f"the timer is not re-armed: {update_round._timer}"


def test_a_non_client_cycle_still_runs_and_re_arms(server, stubbed, monkeypatch):
    """Section 5: a non-client cycle still runs and re-arms."""
    monkeypatch.setattr(plugin_config, "cross_server_mode", MODE_LOCAL)

    REAL_CYCLIC_CHECK_UPDATES(server)
    timer = update_round._timer

    assert stubbed == [("update", server)], f"update() runs where this instance decides: {stubbed}"
    assert isinstance(timer, threading.Timer), f"the 24 h timer is re-armed: {timer}"
    assert getattr(timer, "name", "") == "games_ai@update_timer", \
        f"the timer carries the loop name: {getattr(timer, 'name', '')}"


def test_the_update_threads_keep_the_names_on_unload_reports():
    """Section 6: the update threads keep the names on_unload reports."""
    source = (Path(PKG) / "update_round.py").read_text(encoding="utf-8")

    assert re.search(r"(?m)^\s*(import games_ai\b|from games_ai\b)", source) is None, \
        "the update path does not import the entry package"
    for thread_name in ("games_ai@update_loop", "games_ai@update_timer", "games_ai@update",
                        "games_ai@update_order"):
        assert thread_name in source, f"{thread_name} is still created by the module"
        assert thread_name in games_ai._PLUGIN_THREAD_NAMES, \
            f"...and on_unload still knows it: {sorted(games_ai._PLUGIN_THREAD_NAMES)}"
