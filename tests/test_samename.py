"""Two instances on one machine share a hostname: replies must still come back."""
import importlib.util
import logging
import os
import sys

import pytest

from _helpers.paths import PKG
from _helpers.wait import wait_until
from mcdreforged.api.all import RText
from mcdreforged.minecraft.rtext.style import RColor

SHARED_NAME = "one-machine"          # both instances report the same hostname


class FakeInfo:
    content = "!!data read key1"


class FakeSource:
    def __init__(self, who="Steve", permission=3, console=False):
        self.player = None if console else who
        self.permission = permission
        self.console = console
        self.received = []

    def get_info(self):
        return FakeInfo()

    def get_permission_level(self):
        return self.permission

    @property
    def is_console(self):
        return self.console

    @property
    def is_player(self):
        return not self.console

    def reply(self, message, **kwargs):
        self.received.append(message)

    def __str__(self):
        return "console" if self.console else self.player


class FakeServer:
    def __init__(self, name):
        self.name = name
        self.seen = []

    def execute_command(self, raw, source):
        self.seen.append(raw)
        source.reply(RText("answer line one", RColor.gold))
        source.reply("answer line two")

    def get_permission_level(self, player):
        return 3


def load_instance(alias):
    """Load the plugin package a second time, under its own namespace of globals."""
    spec = importlib.util.spec_from_file_location(
        alias, os.path.join(PKG, "__init__.py"), submodule_search_locations=[PKG])
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


def unload_instance(alias):
    """Forget an instance and every submodule it registered, so nothing leaks into a later test."""
    for name in [name for name in sys.modules
                 if name == alias or name.startswith(alias + ".")]:
        del sys.modules[name]


@pytest.fixture
def instances(monkeypatch):
    """Two copies of the plugin, each with its own fake server, dropped again afterwards."""
    a = load_instance("games_ai_same_a")
    b = load_instance("games_ai_same_b")
    monkeypatch.setattr(a, "_server_ref", FakeServer("A"), raising=False)
    monkeypatch.setattr(b, "_server_ref", FakeServer("B"), raising=False)
    yield a, b
    unload_instance("games_ai_same_a")
    unload_instance("games_ai_same_b")


@pytest.fixture
def live_managers():
    """The managers a test starts: stopped in reverse order however the test ends."""
    started = []
    yield started
    for manager in reversed(started):
        manager.stop()


def test_two_instances_that_share_a_hostname_still_reply(instances, live_managers, monkeypatch,
                                                         free_port):
    a, b = instances
    uri = "ws://127.0.0.1:{}".format(free_port())
    log = logging.getLogger("test")

    manager_a = a.CrossServerManager(uri, name=SHARED_NAME, handler=a._on_cross_message, logger=log)
    live_managers.append(manager_a)
    assert manager_a.start(timeout=5) == a.MODE_SERVER, f"A is the hub: {manager_a.reason}"
    # B needs a token of its own; the hub issues one per name (docs/token-enrollment.md).
    shared_token = manager_a.hub.issue(SHARED_NAME)
    manager_b = b.CrossServerManager(uri, name=SHARED_NAME, token=shared_token,
                                     handler=b._on_cross_message, logger=log)
    live_managers.append(manager_b)
    assert manager_b.start(timeout=5) == b.MODE_CLIENT, \
        f"B becomes a client under the same name: {manager_b.reason}"
    monkeypatch.setattr(a, "_cross_server", manager_a, raising=False)
    monkeypatch.setattr(b, "_cross_server", manager_b, raising=False)

    assert manager_a.peers == [SHARED_NAME], \
        f"the hub lists a peer with the same name as itself: {manager_a.peers}"

    steve = FakeSource()
    b._forward_command(b.ROUTE_SERVER, steve, "!!data read key1")

    assert wait_until(lambda: len(steve.received) >= 2, timeout=5), \
        f"waiting for both lines of the reply: {steve.received}"
    assert a._server_ref.seen == ["!!data read key1"], \
        f"the hub executed the forwarded command: {a._server_ref.seen}"
    assert len(steve.received) == 2, \
        f"the reply came back despite the identical names: {steve.received}"
    assert (any("answer line one" in str(text) for text in steve.received)
            and any("answer line two" in str(text) for text in steve.received)), \
        f"both lines survived: {[str(text) for text in steve.received]}"
