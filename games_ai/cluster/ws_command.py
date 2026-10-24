"""Remote command execution: the command source and the text format on the wire.

A command issued on one instance may be executed on another one. The executor wraps the
request in a :class:`WebSocketCommandSource` so the ordinary MCDR command code runs
unchanged: `source.reply()` is what streams the answer back to whoever asked.

Rich text travels as MCDR's own JSON text object (``RTextBase.to_json_object`` /
``from_json_object``), so colours, bold/italic/underline/strikethrough, hover texts,
click events and nested lists survive without a format of our own.

The source answers the whole ``CommandSource`` API an ordinary command handler may use, so a
handler written against a local player or console source behaves the same when it runs for a
remote issuer (see ``tests/test_ws_command.py`` for the contract).
"""

import logging
import threading
import time
import uuid
from collections.abc import Callable

from mcdreforged.api.all import (
    CommandSource, IllegalCallError, Info, InfoSource, PreferenceItem, RText, RTextBase,
)
from mcdreforged.plugin.si.server_interface import ServerInterface

# How a command is handled by this instance. See __init__._route for the wiring.
ROUTE_SERVER = "server"     # the instance that owns the link executes it
ROUTE_LOCAL = "local"       # whoever typed it executes it (help texts and the like)
ROUTE_CLUSTER = "cluster"   # every instance executes it (reload, debug, ...)

# Console has no player name to look up, and anyone sitting at a machine's console already
# controls that machine, so a remote console keeps its own level.
REMOTE_CONSOLE_LEVEL = 4

# A remote `!!ask` may stream for minutes; keep the mapping long enough for that.
SESSION_TTL = 30 * 60
MAX_SESSIONS = 64


def encode_text(message) -> dict | list | str:
    """MCDR text (or anything else) -> a JSON text object that can cross the wire."""
    try:
        return RTextBase.from_any(message).to_json_object()
    except Exception:
        return str(message)


def decode_text(data) -> RTextBase:
    """The inverse of :func:`encode_text`; never raises."""
    try:
        return RTextBase.from_json_object(data)
    except Exception:
        return RText(str(data))


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

    def __init__(
        self,
        server: ServerInterface,
        *,
        origin: str,
        player: str | None,
        is_console: bool,
        permission_level: int,
        sink: Callable[[RTextBase], None],
        tools: list[dict] | None = None,
        session: str = "",
        command: str | None = None,
    ):
        self._server = server
        self.origin = origin                  # instance name of the one that asked
        self.player = player                  # player name, None for a console
        self._is_console = is_console
        self._permission_level = permission_level
        self._sink = sink
        # The tool schemas the asking instance uploaded with its request: they are what the
        # origin can run on its own side (see games_ai_tool.get_local_tool_schemas_for_perm).
        self.tools: list[dict] = list(tools or [])
        # The remote session this source answers to. It belongs to the instance that asked:
        # the origin streams a routed tool's own replies straight to the player through it.
        self.session = session
        # The command line as it was typed on the origin, when this source stands for a command.
        # A routed *tool* call has none: nothing was typed, so it carries no Info (see get_info).
        self._command = command
        self._info: Info | None = None
        self._str = (f"{origin}/console" if is_console else f"{origin}/{player}")

    # ---- CommandSource API ----
    def get_server(self) -> ServerInterface:
        return self._server

    def get_permission_level(self) -> int:
        return self._permission_level

    @property
    def is_console(self) -> bool:
        return self._is_console

    @property
    def is_player(self) -> bool:
        return not self._is_console

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
        if self._info is not None:
            return self._info
        if self._command is None:
            raise IllegalCallError(
                "a routed tool call has no command Info; use is_player / player / reply instead")
        info = Info(
            source=InfoSource.CONSOLE if self._is_console else InfoSource.SERVER,
            raw_content=self._command,
            content=self._command,
            player=None if self._is_console else self.player,
        )
        try:
            mcdr_server = getattr(self._server, "_mcdr_server", None)
            if mcdr_server is not None:
                info._attach_and_finalize(mcdr_server, command_source=self)
        except Exception:                              # noqa: BLE001 - a fallback, not a failure
            logging.getLogger(__name__).debug(
                "could not finalize the Info of remote command %r", self._command)
        self._info = info
        return info

    def get_preference(self) -> PreferenceItem:
        """The remote issuer's preference as this instance knows it.

        A remote player is looked up by name in this instance's preference file -- the players
        of a cluster usually play on every instance -- and falls back to this instance's default
        when the name is not configured here. A console has no name of its own, so it gets the
        default as well. That is what :meth:`preferred_language_context` then resolves, so a
        reply is translated in the same language a local command would use.
        """
        if self._server is None:
            # No server bound: let the base class raise its own IllegalCallError.
            return super().get_preference()
        if not self._is_console and self.player:
            try:
                return self._server.get_preference(self.player)
            except Exception:                          # noqa: BLE001 - fall back to the default
                pass
        return self._server.get_default_preference()

    def reply(self, message, *, encoding: str | None = None, console_text=None, **kwargs) -> None:
        """Send one line back to the requester (rich text included).

        ``encoding`` is accepted for parity with ``PlayerCommandSource`` and ignored: a reply
        crosses the link as MCDR's JSON text, not as encoded server output. ``console_text`` is
        what a ``ConsoleCommandSource`` shows instead of the message, so it is honoured when the
        issuer is a remote console. Never raises: a reply that cannot be converted or sent must
        not break the command that is running on behalf of the remote side.
        """
        if self._is_console and console_text is not None:
            message = console_text
        try:
            text = RTextBase.from_any(message)
        except Exception:
            try:
                text = RText(str(message))
            except Exception:
                text = RText("<unprintable reply>")
        try:
            self._sink(text)
        except Exception:
            logging.getLogger(__name__).exception("failed to stream a remote command reply")

    def __str__(self) -> str:
        return self._str

    def __repr__(self) -> str:
        return f"WebSocketCommandSource({self._str!r})"

    def __eq__(self, other) -> bool:
        """Two remote sources are the same issuer when the instance and the identity match.

        MCDR's builtin sources all compare by what they stand for (``PlayerCommandSource`` by
        player name, ``ConsoleCommandSource`` as one console), so a handler that compares sources
        gets the same kind of answer here. Like those classes, defining this makes the source
        unhashable; nothing in the plugin puts a command source in a set or uses one as a key.
        """
        return (
            isinstance(other, WebSocketCommandSource)
            and self.origin == other.origin
            and self._is_console == other._is_console
            and self.player == other.player
        )


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

    A session id must be unique across the whole cluster, not just inside this process: the id
    travels on the wire, and the executing instance's ``_local_sink`` treats a locally known id
    as "this reply belongs to a local command source". With a bare per-instance counter two
    instances both mint ``s1``, so one instance's answer could be delivered to the other
    instance's local player (or silently lost). Therefore every registry carries a random tag.
    """

    def __init__(self, logger: logging.Logger | None = None):
        self._log = logger or logging.getLogger(__name__)
        self._lock = threading.Lock()
        self._sessions: dict[str, tuple[float, CommandSource, str]] = {}
        self._counter = 0
        self._tag = uuid.uuid4().hex[:8]

    def new(self, source: CommandSource, kind: str = ROUTE_SERVER) -> str:
        with self._lock:
            self._counter += 1
            session = f"{self._tag}-{self._counter}"
            self._sessions[session] = (time.monotonic(), source, str(kind))
            self._sweep_locked()      # after the insert, so the cap really is the cap
        return session

    def get(self, session: str) -> CommandSource | None:
        with self._lock:
            entry = self._sessions.get(session)
        return entry[1] if entry is not None else None

    def kind_of(self, session: str) -> str:
        """The class of the command that owns this session (ROUTE_SERVER when unknown)."""
        with self._lock:
            entry = self._sessions.get(session)
        return entry[2] if entry is not None else ROUTE_SERVER

    def drop(self, session: str) -> None:
        with self._lock:
            self._sessions.pop(session, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def _sweep_locked(self) -> None:
        now = time.monotonic()
        for session in [s for s, entry in self._sessions.items() if now - entry[0] > SESSION_TTL]:
            self._sessions.pop(session, None)
        while len(self._sessions) > MAX_SESSIONS:
            oldest = min(self._sessions, key=lambda s: self._sessions[s][0])
            self._sessions.pop(oldest, None)
            self._log.debug("dropped the oldest remote command session (%s)", oldest)
