"""Test the remote command source, the session registry and the codec.

The source has to answer the whole ``CommandSource`` API a local command handler may use, so a
command that crossed the link behaves like one typed here: ``tests`` below cover the members,
their remote meaning, and the two places the wire cannot be as faithful as a local source.
"""
import pytest

from mcdreforged.api.all import (
    IllegalCallError, IllegalStateError, InfoSource, RText, RTextList,
)
from mcdreforged.command.command_source import (
    CommandSource, ConsoleCommandSource, InfoCommandSource, PlayerCommandSource,
)
from mcdreforged.minecraft.rtext.click_event import RAction
from mcdreforged.minecraft.rtext.style import RColor, RStyle

from games_ai.cluster.ws_command import (
    REMOTE_CONSOLE_LEVEL,
    MAX_SESSIONS,
    SessionRegistry,
    WebSocketCommandSource,
    decode_text,
    encode_text,
)


class Boom:
    """A hostile reply object: ``str()`` raises, and ``reply`` must survive that."""

    def __str__(self):
        raise RuntimeError("nope")


@pytest.fixture
def sources():
    """The two remote command sources this suite drives, sharing one captured-output sink."""
    captured = []
    player = WebSocketCommandSource(
        None, origin="host-b", player="Steve", is_console=False,
        permission_level=2, sink=captured.append,
    )
    console = WebSocketCommandSource(
        None, origin="host-b", player=None, is_console=True,
        permission_level=REMOTE_CONSOLE_LEVEL, sink=captured.append,
    )
    return player, console, captured


def test_the_command_source_is_a_base_command_source_not_a_subtype(sources):
    player, console, _captured = sources

    assert issubclass(WebSocketCommandSource, CommandSource), "inherits CommandSource"
    assert not WebSocketCommandSource.__abstractmethods__, \
        f"no abstract methods left: {WebSocketCommandSource.__abstractmethods__}"
    assert player.is_player and not player.is_console, "player source reports is_player"
    assert console.is_console and not console.is_player, "console source reports is_console"
    assert (player.get_permission_level(), console.get_permission_level()) == (2, 4), \
        "permission is carried through"
    assert str(player) == "host-b/Steve" and str(console) == "host-b/console", \
        f"str is descriptive: {(str(player), str(console))}"


@pytest.mark.parametrize("cls", [PlayerCommandSource, ConsoleCommandSource, InfoCommandSource],
                         ids=["PlayerCommandSource", "ConsoleCommandSource", "InfoCommandSource"])
def test_it_does_not_inherit_one_of_the_concrete_sources(cls):
    assert not issubclass(WebSocketCommandSource, cls), f"does not inherit {cls.__name__}"


def test_reply_streams_rich_text_to_the_sink(sources):
    player, _console, captured = sources

    player.reply("plain line")
    assert isinstance(captured[-1], RText) and captured[-1].to_plain_text() == "plain line", \
        f"a str arrives as RTextBase: {captured[-1]}"

    player.reply(RText("coloured", RColor.gold).h("a hover"))
    assert captured[-1].to_json_object().get("color") == "gold", \
        f"an RText keeps its colour: {captured[-1].to_json_object()}"

    player.reply(Boom())          # from_any on a hostile object must not raise
    assert len(captured) == 3, f"a hostile object still produces something: {len(captured)}"


def test_rich_text_survives_the_wire():
    rich = RTextList(
        RText("GamesAI", RColor.gold).set_styles([RStyle.bold]),
        RText(" | ", RColor.dark_gray),
        RText("write", RColor.gray)
            .h("Click to write the value")
            .c(RAction.suggest_command, "!!data write k "),
        RText("copy", RColor.blue)
            .h(RTextList("copy the value", RText("\nsecond hover line", RColor.gray)))
            .c(RAction.copy_to_clipboard, "value"),
        RText("run", RColor.red).c(RAction.run_command, "!!ask hi"),
        RText("site", RColor.aqua).c(RAction.open_url, "https://example.invalid/"),
    )
    wire = encode_text(rich)

    assert isinstance(wire, list), f"encoded as a list of segments: {type(wire)}"

    back = decode_text(wire)
    assert back.to_plain_text() == rich.to_plain_text(), \
        f"plain text round trip: {back.to_plain_text()}"
    assert back.to_json_object() == wire, "json round trip is identical"

    flat = str(back.to_json_object())
    for feature in ("bold", "hoverEvent", "suggest_command", "copy_to_clipboard",
                    "run_command", "open_url", "gold", "aqua"):
        assert feature in flat, f"kept {feature}: {flat}"

    assert decode_text(encode_text("hello")).to_plain_text() == "hello", "a plain string is stable"
    assert decode_text({"nonsense": True}) is not None, \
        "garbage decodes to text instead of raising"
    assert decode_text(None).to_plain_text() == "None", "None decodes safely"


def test_the_session_registry(sources):
    player, console, _captured = sources
    registry = SessionRegistry()
    session_a = registry.new(player)
    session_b = registry.new(console)

    assert session_a != session_b, f"sessions are unique: {(session_a, session_b)}"
    assert registry.get(session_a) is player, "the source comes back"

    registry.drop(session_b)
    assert registry.get(session_b) is None and registry.get(session_a) is player, "drop forgets one"

    for _ in range(MAX_SESSIONS + 10):
        registry.new(player)
    assert len(registry._sessions) <= MAX_SESSIONS, \
        f"the registry stays bounded: {len(registry._sessions)}"
    assert registry.get(session_a) is None, "the newest sessions survive"

    registry.clear()
    assert len(registry._sessions) == 0, "clear empties it"


# --------------------------------------------------------------- the CommandSource API, aligned

class FakePreference:
    def __init__(self, language):
        self.language = language


class FakeMCDRServer:
    """The one attribute ``Info`` finalization reads from the MCDR server object."""

    def __init__(self, server):
        self.basic_server_interface = server


class FakeServer:
    """A plugin server interface as far as a remote command source is concerned."""

    def __init__(self, preferences=None, default="en_us", with_mcdr=True):
        self.preferences = dict(preferences or {})
        self.default = default
        if with_mcdr:
            self._mcdr_server = FakeMCDRServer(self)

    def get_preference(self, player_name):
        return FakePreference(self.preferences[player_name])      # unknown name: KeyError

    def get_default_preference(self):
        return FakePreference(self.default)


def remote(server, *, origin="host-b", player="Steve", is_console=False, permission=2,
           command="!!ask where am i"):
    captured = []
    source = WebSocketCommandSource(
        server, origin=origin, player=None if is_console else player, is_console=is_console,
        permission_level=REMOTE_CONSOLE_LEVEL if is_console else permission,
        sink=captured.append, command=command,
    )
    return source, captured


#: What MCDR's own command sources answer; a handler may call any of it on whatever source it gets.
COMMAND_SOURCE_API = (
    "get_server", "get_permission_level", "get_info", "get_preference",
    "preferred_language_context", "has_permission", "has_permission_higher_than", "reply",
    "is_player", "is_console",
)


@pytest.mark.parametrize("name", COMMAND_SOURCE_API)
def test_the_remote_source_answers_a_command_sources_api(name):
    """Every member of the local sources exists here too (no AttributeError for a handler)."""
    player, _captured = remote(FakeServer())
    console, _ = remote(FakeServer(), is_console=True)

    assert hasattr(player, name), f"the player-side remote source has {name}"
    assert hasattr(console, name), f"the console-side remote source has {name}"


def test_the_permission_helpers_work_off_the_carried_level():
    player, _captured = remote(FakeServer(), permission=2)

    assert player.has_permission(2) and not player.has_permission(3), \
        "has_permission compares the level the origin reported"
    assert player.has_permission_higher_than(1) and not player.has_permission_higher_than(2), \
        "has_permission_higher_than is strict"


def test_get_info_rebuilds_the_forwarded_command():
    server = FakeServer()
    source, _captured = remote(server, command="!!ask where am i")

    info = source.get_info()

    assert info.content == "!!ask where am i" and info.raw_content == "!!ask where am i", \
        f"the command travels as the content: {info}"
    assert info.player == "Steve" and info.is_from_server and info.is_player and info.is_user, \
        f"the remote player is the issuer: {(info.source, info.player)}"
    assert info.source == InfoSource.SERVER, "a player command is server info"
    assert source.get_info() is info, "the Info is built once, so its id is stable"
    assert info.get_server() is server, \
        "finalized against this MCDR: Info.get_server() answers like a local command's"
    assert info.get_command_source() is source, \
        "and Info.get_command_source() is this source, the way MCDR returns the local one"


def test_get_info_of_a_console_source():
    source, _captured = remote(FakeServer(), is_console=True, command="!!gamesai reload")

    info = source.get_info()

    assert info.content == "!!gamesai reload"
    assert info.player is None and info.is_from_console and not info.is_player, \
        f"a console command is console info: {(info.source, info.player)}"
    assert info.source == InfoSource.CONSOLE and info.is_user, "a console is a user"


def test_an_unfinalizable_info_still_carries_the_data():
    """MCDR's finalize hook is non-public: if it is gone, only the two derived getters fail."""
    source, _captured = remote(FakeServer(with_mcdr=False), command="!!ask hi")

    info = source.get_info()

    assert info.content == "!!ask hi" and info.player == "Steve", "the data fields still work"
    with pytest.raises(IllegalStateError):
        info.get_command_source()


def test_get_info_of_a_routed_tool_call_is_refused():
    """A tool call has no command behind it; an Info for it would be invented."""
    source, _captured = remote(FakeServer(), command=None)

    with pytest.raises(IllegalCallError):
        source.get_info()


def test_get_preference_follows_the_remote_issuer():
    server = FakeServer(preferences={"Steve": "zh_cn"}, default="en_us")
    player, _ = remote(server, player="Steve", command="x")
    stranger, _ = remote(server, player="Alex", command="x")
    console, _ = remote(server, is_console=True, command="x")

    assert player.get_preference().language == "zh_cn", \
        "a remote player is looked up by name in this instance's preferences"
    assert stranger.get_preference().language == "en_us", \
        "an unknown name falls back to this instance's default"
    assert console.get_preference().language == "en_us", "a console has no name of its own"


def test_reply_honours_console_text_for_a_remote_console(sources):
    player, console, captured = sources

    console.reply("message", console_text="the console line")
    assert captured[-1].to_plain_text() == "the console line", \
        f"a ConsoleCommandSource shows console_text instead: {captured[-1]}"

    player.reply("message", console_text="never shown")
    assert captured[-1].to_plain_text() == "message", \
        f"a PlayerCommandSource ignores console_text: {captured[-1]}"

    player.reply("encoded", encoding="utf-8")       # accepted for parity, ignored
    assert captured[-1].to_plain_text() == "encoded", "encoding is accepted and ignored"


def test_two_remote_sources_are_equal_when_they_stand_for_the_same_issuer():
    server = FakeServer()
    steve_a, _ = remote(server, origin="host-b", player="Steve", permission=3,
                        command="!!ask a")
    steve_b, _ = remote(server, origin="host-b", player="Steve", permission=3,
                        command="!!ask b")
    steve_elsewhere, _ = remote(server, origin="host-c", player="Steve")
    console, _ = remote(server, origin="host-b", is_console=True)

    assert steve_a == steve_b, "same instance and same issuer: equal"
    assert steve_a != steve_elsewhere and steve_a != console, "another instance or identity is not"
    assert steve_a != object(), "and an unrelated object is not equal either"
    assert WebSocketCommandSource.__hash__ is PlayerCommandSource.__hash__ is None, \
        "like MCDR's own sources, defining __eq__ makes command sources unhashable"


def test_a_command_that_arrived_from_the_link_is_never_referred():
    """``_raw_command`` must answer None for a forwarded source.

    The source has an Info now, so without the guard a command that arrived from another
    instance would be forwarded again -- or a cluster command fanned out again -- forever.
    """
    import games_ai

    source, _captured = remote(FakeServer(), command="!!gamesai reload")

    assert games_ai._raw_command(source) is None, \
        "a forwarded command is not a line typed here, so it never travels again"


def test_the_executor_hands_the_forwarded_line_to_the_source(monkeypatch):
    """The wiring, not just the class: the frame's command is what the rebuilt Info carries."""
    import types

    import games_ai

    class ImmediateThread:
        """``_execute_remote`` runs the command on a thread; this one runs it now."""

        def __init__(self, target=None, args=(), **kwargs):
            self._target, self._args = target, args

        def start(self):
            self._target(*self._args)

    class ExecutorServer(FakeServer):
        def get_permission_level(self, player_name):
            return 3

    captured = {}
    monkeypatch.setattr(games_ai, "_server_ref", ExecutorServer())
    monkeypatch.setattr(games_ai, "threading", types.SimpleNamespace(Thread=ImmediateThread))
    monkeypatch.setattr(games_ai, "_run_remote_command",
                        lambda server, raw, source, origin, session: captured.update(source=source))

    games_ai._execute_remote("host-a", {
        "command": "!!ask hi", "player": "Steve", "console": False, "permission": 3,
        "session": "s1", "origin": "host-a",
    })

    info = captured["source"].get_info()
    assert info.content == "!!ask hi" and info.player == "Steve", \
        f"the forwarded line becomes the command's Info: {info}"
