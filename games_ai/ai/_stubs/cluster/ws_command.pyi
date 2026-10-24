# Generated from games_ai/cluster/ws_command.py by tools/build_tool_stubs.py -- do not edit.
import logging
from _typeshed import Incomplete
from collections.abc import Callable as Callable
from mcdreforged.api.all import CommandSource, Info, PreferenceItem as PreferenceItem, RTextBase
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

    What it does provide is the rest of the API those sources expose, with the meaning the wire
    allows: :meth:`get_info` returns an ``Info`` rebuilt from the forwarded command (finalized
    against this instance's MCDR, so ``Info.get_server()`` and ``Info.get_command_source()``
    work like they do locally), :meth:`get_preference` looks a remote player up by name in this
    instance's preference file, and :meth:`reply` honours a console source's ``console_text``.
    """
    _server: Incomplete
    origin: Incomplete
    player: Incomplete
    _is_console: Incomplete
    _permission_level: Incomplete
    _sink: Incomplete
    tools: list[dict]
    session: Incomplete
    _command: Incomplete
    _info: Info | None
    _str: Incomplete
    def __init__(self, server: ServerInterface, *, origin: str, player: str | None, is_console: bool, permission_level: int, sink: Callable[[RTextBase], None], tools: list[dict] | None = None, session: str = '', command: str | None = None) -> None: ...
    def get_server(self) -> ServerInterface: ...
    def get_permission_level(self) -> int: ...
    @property
    def is_console(self) -> bool: ...
    @property
    def is_player(self) -> bool: ...
    def get_info(self) -> Info:
        """The command this source stands for, as an MCDR ``Info``.

        The origin sends the command line, not its ``Info`` object, so this is rebuilt: the
        player name, the parsed content and the server/console origin are the origin's; the raw
        line is the command as it was typed. It is then finalized against this instance's MCDR,
        which is what makes :meth:`Info.get_server` and :meth:`Info.get_command_source` work --
        the latter returns this source, the way it returns the local source of a typed command.
        Both hooks are non-public MCDR internals, so a rename downgrades the ``Info`` to an
        unfinalized one (its data fields still work) instead of breaking the command.

        A routed *tool* call has no command behind it; asking for its ``Info`` is a programming
        error (:class:`IllegalCallError`), because any object returned for it would be invented.
        """
    def get_preference(self) -> PreferenceItem:
        """The remote issuer's preference as this instance knows it.

        A remote player is looked up by name in this instance's preference file -- the players
        of a cluster usually play on every instance -- and falls back to this instance's default
        when the name is not configured here. A console has no name of its own, so it gets the
        default as well. That is what :meth:`preferred_language_context` then resolves, so a
        reply is translated in the same language a local command would use.
        """
    def reply(self, message, *, encoding: str | None = None, console_text=None, **kwargs) -> None:
        """Send one line back to the requester (rich text included).

        ``encoding`` is accepted for parity with ``PlayerCommandSource`` and ignored: a reply
        crosses the link as MCDR's JSON text, not as encoded server output. ``console_text`` is
        what a ``ConsoleCommandSource`` shows instead of the message, so it is honoured when the
        issuer is a remote console. Never raises: a reply that cannot be converted or sent must
        not break the command that is running on behalf of the remote side.
        """
    def __str__(self) -> str: ...
    def __repr__(self) -> str: ...
    def __eq__(self, other) -> bool:
        """Two remote sources are the same issuer when the instance and the identity match.

        MCDR's builtin sources all compare by what they stand for (``PlayerCommandSource`` by
        player name, ``ConsoleCommandSource`` as one console), so a handler that compares sources
        gets the same kind of answer here. Like those classes, defining this makes the source
        unhashable; nothing in the plugin puts a command source in a set or uses one as a key.
        """

class SessionRegistry:
    '''Remembers which local command source a remote session answers to.

    A remote ``!!ask`` streams long after the command call returned (its handler runs on a
    thread of its own), so entries are expired by age instead of being dropped when the
    command returns.

    Each session also remembers the *class* of the command it belongs to, because that decides
    how the streamed answers are rendered: a ``ROUTE_SERVER`` command was handed to the hub,
    which then answers **this** player -- those lines are the answer to the command they typed
    and carry no instance label. A ``ROUTE_CLUSTER`` command runs on every instance, so the
    lines that come back from the others are labelled with the instance that produced them.

    A session id must be unique across the whole cluster, not just inside this process: the id
    travels on the wire, and the executing instance\'s ``_local_sink`` treats a locally known id
    as "this reply belongs to a local command source". With a bare per-instance counter two
    instances both mint ``s1``, so one instance\'s answer could be delivered to the other
    instance\'s local player (or silently lost). Therefore every registry carries a random tag.
    '''
    _log: Incomplete
    _lock: Incomplete
    _sessions: dict[str, tuple[float, CommandSource, str]]
    _counter: int
    _tag: Incomplete
    def __init__(self, logger: logging.Logger | None = None) -> None: ...
    def new(self, source: CommandSource, kind: str = ...) -> str: ...
    def get(self, session: str) -> CommandSource | None: ...
    def kind_of(self, session: str) -> str:
        """The class of the command that owns this session (ROUTE_SERVER when unknown)."""
    def drop(self, session: str) -> None: ...
    def clear(self) -> None: ...
    def _sweep_locked(self) -> None: ...
