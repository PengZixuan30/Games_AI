"""Stage-3 wiring test: two plugin instances, real sockets, fake MCDR command executor."""
import importlib.util
import inspect
import logging
import os
import sys
import types
from types import SimpleNamespace

import pytest

from _helpers.paths import PKG
from _helpers.wait import wait_until
from mcdreforged.api.all import RText
from mcdreforged.command.builder.callback import DirectCallbackInvoker, ScheduledCallback
from mcdreforged.minecraft.rtext.style import RColor


class FakeInfo:
    def __init__(self, content):
        self.content = content


class FakeSource:
    """Stands in for a PlayerCommandSource / ConsoleCommandSource on that instance."""

    def __init__(self, who, permission=3, console=False):
        self.who = who
        self.permission = permission
        self.console = console
        self.player = None if console else who
        self.received = []

    def get_info(self):
        return FakeInfo("!!place holder")

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
        return "console" if self.console else self.who


class FakeServer:
    """Stands in for PluginServerInterface: records and answers the remote commands."""

    def __init__(self, name, levels=None, answer="the answer"):
        self.name = name
        self.levels = levels or {}
        self.answer = answer
        self.seen = []

    def execute_command(self, raw, source):
        self.seen.append((raw, source, source.get_permission_level()))
        source.reply(RText(f"{self.answer} from {self.name}", RColor.gold))   # rich text reply
        source.reply("second line")

    def get_permission_level(self, player):
        return self.levels.get(str(player), 0)


class PluginSource:
    """Our own ``server.execute_command`` calls: a source with no Info to rebuild a line from."""

    def get_permission_level(self):
        return 4

    @property
    def is_console(self):
        return True

    @property
    def is_player(self):
        return False

    def reply(self, message, **kwargs):
        pass


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


def mcdr_invoke(callback, source, context):
    """Run a command callback exactly the way MCDR does."""
    return ScheduledCallback(callback, (source, context), lambda e: e).invoke(DirectCallbackInvoker())


@pytest.fixture(scope="module")
def instances():
    """Two copies of the plugin, each with its own namespace of globals.

    Loading a whole package twice is the expensive part of this module and the copies are never
    mutated by the fixtures themselves, so one pair serves every test; the links between them are
    built per test by :func:`cluster`.
    """
    a = load_instance("games_ai_a")          # becomes the hub
    b = load_instance("games_ai_b")          # becomes a client
    yield a, b
    unload_instance("games_ai_a")
    unload_instance("games_ai_b")


@pytest.fixture
def cluster(instances, monkeypatch, free_port):
    """A hub and a client over a real socket, with a fake MCDR server on each end.

    The fixture *is* the boot step the old script ran once at module level, so its two boot
    checks -- "A is the hub" and "B is a client" -- are asserted here, with the same wording:
    every test below needs a live cluster, and a hub that cannot start has to say so.
    """
    a, b = instances
    managers = []
    try:
        monkeypatch.setattr(a, "_server_ref", FakeServer("host-a", levels={"Steve": 3, "Bob": 1}),
                            raising=False)
        monkeypatch.setattr(b, "_server_ref", FakeServer("host-b"), raising=False)
        uri = "ws://127.0.0.1:{}".format(free_port())

        manager_a = a.CrossServerManager(uri, name="host-a", handler=a._on_cross_message)
        managers.append(manager_a)
        assert manager_a.start(timeout=5) == a.MODE_SERVER, f"A is the hub: {manager_a.reason}"

        # The hub issues one token per node; B has to carry its own (docs/token-enrollment.md).
        host_b_token = manager_a.hub.issue("host-b")
        manager_b = b.CrossServerManager(uri, name="host-b", token=host_b_token,
                                         handler=b._on_cross_message)
        managers.append(manager_b)
        assert manager_b.start(timeout=5) == b.MODE_CLIENT, f"B is a client: {manager_b.reason}"

        monkeypatch.setattr(a, "_cross_server", manager_a, raising=False)
        monkeypatch.setattr(b, "_cross_server", manager_b, raising=False)
        yield SimpleNamespace(a=a, b=b, hub=manager_a, client=manager_b)
    finally:
        for manager in reversed(managers):
            manager.stop()


def test_boot_two_instances(cluster):
    assert cluster.a is not cluster.b and cluster.a.cross_server is not cluster.b.cross_server, \
        f"two isolated namespaces: {(cluster.a.cross_server, cluster.b.cross_server)}"


def test_an_a_class_command_is_executed_on_the_hub(cluster):
    a, b = cluster.a, cluster.b
    steve = FakeSource("Steve", permission=3)
    b._forward_command(b.ROUTE_SERVER, steve, "!!data read key1")

    assert wait_until(lambda: len(steve.received) >= 2, timeout=5), \
        f"waiting for both lines to stream back: {steve.received}"
    assert a._server_ref.seen and a._server_ref.seen[-1][0] == "!!data read key1", \
        f"the hub ran the command: {a._server_ref.seen}"
    raw, remote_source, perm = a._server_ref.seen[-1]
    assert type(remote_source).__name__ == "WebSocketCommandSource", \
        "the source is a WebSocketCommandSource"
    assert remote_source.is_player and remote_source.player == "Steve", \
        "it reports the player identity"
    assert perm == 3, f"permission is min(reported, hub table) = 3: {perm}"
    assert str(remote_source) == "host-b/Steve", f"str shows origin and player: {str(remote_source)}"
    assert len(steve.received) == 2, f"both lines streamed back: {steve.received}"
    assert "gold" in str(steve.received[0].to_json_object()), \
        f"rich text survived: {steve.received[0].to_json_object()}"
    assert "host-a" in steve.received[0].to_plain_text(), \
        f"the answer was prefixed with the executing instance: {steve.received[0].to_plain_text()}"
    assert steve.received[1].to_plain_text().endswith("second line"), \
        f"the second line kept its text: {steve.received[1].to_plain_text()}"


def test_the_hubs_own_table_caps_the_reported_level(cluster):
    a, b = cluster.a, cluster.b
    bob = FakeSource("Bob", permission=4)
    b._forward_command(b.ROUTE_SERVER, bob, "!!data read key2")

    assert wait_until(lambda: len(a._server_ref.seen) >= 1, timeout=5), \
        f"waiting for the hub to run Bob's command: {a._server_ref.seen}"
    assert a._server_ref.seen[-1][2] == 1, f"Bob is capped to level 1: {a._server_ref.seen[-1][2]}"

    stranger = FakeSource("Nobody", permission=4)
    b._forward_command(b.ROUTE_SERVER, stranger, "!!data read key3")

    assert wait_until(lambda: len(a._server_ref.seen) >= 2, timeout=5), \
        f"waiting for the hub to run the stranger's command: {a._server_ref.seen}"
    assert a._server_ref.seen[-1][2] == 0, \
        f"an unknown player gets level 0: {a._server_ref.seen[-1][2]}"


def test_a_remote_console_keeps_level_4(cluster):
    a, b = cluster.a, cluster.b
    console = FakeSource("console", permission=4, console=True)
    b._forward_command(b.ROUTE_SERVER, console, "!!gamesai config get permission")

    assert wait_until(lambda: len(a._server_ref.seen) >= 1, timeout=5), \
        f"waiting for the hub to run the console command: {a._server_ref.seen}"
    raw, remote_console, perm = a._server_ref.seen[-1]
    assert perm == 4, f"console keeps level 4: {perm}"
    assert remote_console.is_console and not remote_console.is_player, \
        "the source reports itself as console"
    assert str(remote_console) == "host-b/console", \
        f"str shows origin/console: {str(remote_console)}"


def test_a_local_command_is_answered_in_place(cluster):
    b = cluster.b
    before = len(cluster.a._server_ref.seen)
    help_source = FakeSource("Steve")
    handler_ran = []
    wrapped = b._route(b.ROUTE_LOCAL, lambda src: handler_ran.append(src))
    wrapped(help_source)

    assert handler_ran == [help_source], "a local command runs in place"
    assert len(cluster.a._server_ref.seen) == before, "nothing was sent to the hub"


def test_a_cluster_command_runs_everywhere(cluster):
    b = cluster.b
    cluster_source = FakeSource("Steve")
    cluster_handler = b._route(b.ROUTE_CLUSTER, lambda src: None)
    cluster_handler(cluster_source)          # typed on the client -> forwarded

    def both_instances_answered():
        # The hub runs the forwarded command and fans it out; the origin runs it when the
        # broadcast arrives, and the answers stream back with the sender's name on them.
        return (any(c[0] == "!!place holder" for c in cluster.a._server_ref.seen)
                and any(c[0] == "!!place holder" for c in b._server_ref.seen)
                and any("host-a" in t.to_plain_text() for t in cluster_source.received)
                and any("host-b" in t.to_plain_text() for t in cluster_source.received))

    assert wait_until(both_instances_answered, timeout=5), \
        ("waiting for both instances to run the cluster command and answer: "
         f"{[t.to_plain_text() for t in cluster_source.received]}")
    assert any(c[0] == "!!place holder" for c in cluster.a._server_ref.seen), \
        f"the hub executed the cluster command: {cluster.a._server_ref.seen}"
    assert any(c[0] == "!!place holder" for c in b._server_ref.seen), \
        f"the origin ran it locally too: {b._server_ref.seen}"
    assert any("host-a" not in t.to_plain_text() and "host-b" in t.to_plain_text()
               for t in cluster_source.received), \
        ("the origin sees its own output unprefixed: "
         f"{[t.to_plain_text() for t in cluster_source.received]}")
    assert any("host-a" in t.to_plain_text() for t in cluster_source.received), \
        f"the hub's own output arrived prefixed: {[t.to_plain_text() for t in cluster_source.received]}"


def test_an_internal_command_is_never_forwarded(cluster):
    b = cluster.b
    before = len(cluster.a._server_ref.seen)
    internal = b._route(b.ROUTE_SERVER, lambda src: "ran locally")(PluginSource())

    assert internal == "ran locally", "a PluginCommandSource runs locally"
    assert len(cluster.a._server_ref.seen) == before, "and is not forwarded"


def test_an_incoming_command_is_never_bounced_back(cluster):
    b = cluster.b
    remote_ws_source = b.WebSocketCommandSource(b._server_ref, origin="host-a", player="Steve",
                                                is_console=False, permission_level=3,
                                                sink=lambda t: None)

    assert b._should_forward(remote_ws_source) is False, \
        "a WebSocketCommandSource is not forwarded"


def test_the_wrapper_keeps_the_callbacks_arity(instances, monkeypatch):
    """MCDR slices arguments by the callback's declared positional count."""
    _, b = instances
    monkeypatch.setattr(b, "_cross_server", None, raising=False)   # local mode: nothing forwarded

    seen = []

    def two_arg_handler(src, ctx):
        seen.append(("two", src, ctx))
        return "two-arg ran"

    def one_arg_handler(src):
        seen.append(("one", src))
        return "one-arg ran"

    wrapped_two = b._route(b.ROUTE_SERVER, two_arg_handler)
    wrapped_one = b._route(b.ROUTE_SERVER, one_arg_handler)
    assert b._callback_arity(two_arg_handler) == 2, \
        f"a 2-arg handler keeps arity 2: {b._callback_arity(two_arg_handler)}"
    assert b._callback_arity(one_arg_handler) == 1, \
        f"a 1-arg handler keeps arity 1: {b._callback_arity(one_arg_handler)}"
    assert len(inspect.getfullargspec(wrapped_two).args) == 2, \
        ("the wrapper of a 2-arg handler declares 2 params: "
         f"{inspect.getfullargspec(wrapped_two).args}")
    assert len(inspect.getfullargspec(wrapped_one).args) == 1, \
        ("the wrapper of a 1-arg handler declares 1 param: "
         f"{inspect.getfullargspec(wrapped_one).args}")

    sentinel_ctx = object()
    result_two = mcdr_invoke(wrapped_two, "SRC", sentinel_ctx)
    result_one = mcdr_invoke(wrapped_one, "SRC", sentinel_ctx)
    assert result_two == "two-arg ran" and seen[-2] == ("two", "SRC", sentinel_ctx), \
        f"MCDR's invocation reaches the 2-arg handler with its context: {seen[-2:]}"
    assert result_one == "one-arg ran" and seen[-1] == ("one", "SRC"), \
        f"and the 1-arg handler still gets exactly one argument: {seen[-1:]}"

    bound = types.MethodType(lambda self, src, ctx: ctx, object())
    assert b._callback_arity(bound) == 2, \
        f"a bound method's arity counts without self: {b._callback_arity(bound)}"
