"""Test the stage-3 foundation: the command source, the session registry and the codec."""
import pytest

from mcdreforged.api.all import RText, RTextList
from mcdreforged.command.command_source import (
    CommandSource, ConsoleCommandSource, InfoCommandSource, PlayerCommandSource,
)
from mcdreforged.minecraft.rtext.click_event import RAction
from mcdreforged.minecraft.rtext.style import RColor, RStyle

from games_ai.ws_command import (
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
