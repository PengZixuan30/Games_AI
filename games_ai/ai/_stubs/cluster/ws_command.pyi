# Generated from games_ai/cluster/ws_command.py by tools/build_tool_stubs.py -- do not edit.
import logging
from _typeshed import Incomplete
from collections.abc import Callable as Callable
from mcdreforged.api.all import CommandSource, RTextBase
from mcdreforged.plugin.si.server_interface import ServerInterface as ServerInterface

ROUTE_SERVER: str
ROUTE_LOCAL: str
ROUTE_CLUSTER: str
REMOTE_CONSOLE_LEVEL: int
SESSION_TTL: Incomplete
MAX_SESSIONS: int

def encode_text(message) -> dict | list | str:
    """MCDR text (or anything else) -> a JSON text object that can cross the wire."""
def decode_text(data) -> RTextBase:
    """The inverse of :func:`encode_text`; never raises."""

class WebSocketCommandSource(CommandSource):
    """Stands for a player *or* the console of another instance.

    It inherits the ``CommandSource`` base and nothing else on purpose: the caller may be a
    player or a console, so claiming to be a ``PlayerCommandSource`` or a
    ``ConsoleCommandSource`` would make the remote side lie about what it is, while
    ``is_player`` / ``is_console`` still answer correctly.
    """
    _server: Incomplete
    origin: Incomplete
    player: Incomplete
    _is_console: Incomplete
    _permission_level: Incomplete
    _sink: Incomplete
    tools: list[dict]
    session: Incomplete
    _str: Incomplete
    def __init__(self, server: ServerInterface, *, origin: str, player: str | None, is_console: bool, permission_level: int, sink: Callable[[RTextBase], None], tools: list[dict] | None = None, session: str = '') -> None: ...
    def get_server(self) -> ServerInterface: ...
    def get_permission_level(self) -> int: ...
    @property
    def is_console(self) -> bool: ...
    @property
    def is_player(self) -> bool: ...
    def reply(self, message, **kwargs) -> None:
        """Send one line back to the requester (rich text included).

        Never raises: a reply that cannot be converted or sent must not break the command
        that is running on behalf of the remote side.
        """
    def __str__(self) -> str: ...
    def __repr__(self) -> str: ...

class SessionRegistry:
    """Remembers which local command source a remote session answers to.

    A remote ``!!ask`` streams long after the command call returned (its handler runs on a
    thread of its own), so entries are expired by age instead of being dropped when the
    command returns.

    Each session also remembers the *class* of the command it belongs to, because that decides
    how the streamed answers are rendered: a ``ROUTE_SERVER`` command was handed to the hub,
    which then answers **this** player -- those lines are the answer to the command they typed
    and carry no instance label. A ``ROUTE_CLUSTER`` command runs on every instance, so the
    lines that come back from the others are labelled with the instance that produced them.
    """
    _log: Incomplete
    _lock: Incomplete
    _sessions: dict[str, tuple[float, CommandSource, str]]
    _counter: int
    def __init__(self, logger: logging.Logger | None = None) -> None: ...
    def new(self, source: CommandSource, kind: str = ...) -> str: ...
    def get(self, session: str) -> CommandSource | None: ...
    def kind_of(self, session: str) -> str:
        """The class of the command that owns this session (ROUTE_SERVER when unknown)."""
    def drop(self, session: str) -> None: ...
    def clear(self) -> None: ...
    def _sweep_locked(self) -> None: ...
