# Generated from games_ai/cluster/websockets_client.py by tools/build_tool_stubs.py -- do not edit.
import logging
import threading
from _typeshed import Incomplete
from collections.abc import Callable, Iterable
from websockets.sync.client import ClientConnection as ClientConnection

APP_ID: str
APP_ID_BOT: str
ACCEPTED_PEER_APPS: Incomplete
PROTOCOL_VERSION: int
FEATURES: Incomplete
CLOSE_BAD_HANDSHAKE: int
CLOSE_BAD_TOKEN: int
CLOSE_NO_NAME: int
CLOSE_REPLACED: int
CLOSE_BAD_PROTOCOL: int
CLOSE_NOT_GAMES_AI: int
CLOSE_ENROLMENT_REQUIRED: int
CLOSE_TOKEN_EXPIRED: int
ENROLMENT_REQUIRED_HINT: str
TOKEN_EXPIRED_HINT: str
FATAL_CLOSE_CODES: Incomplete
PROBE_GAMES_AI: str
PROBE_FOREIGN: str
PROBE_UNREACHABLE: str
RECONNECT_DELAYS: Incomplete
MAX_MESSAGE_SIZE: Incomplete
FRAME_MARGIN: int
HANDSHAKE_TIMEOUT: float
MessageHandler = Callable[[dict], dict | None]

def token_fingerprint(token: str) -> str:
    """The public short name of a token (sha256[:6]); the token itself is never logged."""
def _dumps(obj: dict) -> str: ...
def _hello_frame(name: str, token: str, version: str, *, probe: bool = False, app: str = ..., enroll: bool = False) -> dict: ...
def probe_hub_detail(uri: str, timeout: float = 3.0, logger: logging.Logger | None = None, token: str = '', name: str = 'probe') -> tuple[str, dict]:
    '''Ask whatever listens at ``uri`` whether it is a GamesAI hub, and what it thinks of a token.

    Returns ``(result, info)`` where ``result`` is one of :data:`PROBE_GAMES_AI`,
    :data:`PROBE_FOREIGN` or :data:`PROBE_UNREACHABLE`, and ``info`` carries what the ack
    said: ``{"hub": str, "peers": [str], "token_name": str | None, "expires_in": int | None}``.
    A probe never registers, never enrols and never creates a pending entry. With a token the
    hub knows, ``token_name`` says which node it was issued for -- that is what
    ``!!gamesai node claim`` checks before it writes anything.
    '''
def probe_hub(uri: str, timeout: float = 3.0, logger: logging.Logger | None = None, token: str = '') -> tuple[str, list[str], str]:
    """Ask whatever listens at ``uri`` whether it is a GamesAI hub.

    Returns ``(result, peers, hub_name)``, with ``result`` one of :data:`PROBE_GAMES_AI`,
    :data:`PROBE_FOREIGN` or :data:`PROBE_UNREACHABLE`. Used on load to decide between
    dialling that hub as a client and starting our own. A probe needs no token, so an
    unenrolled instance still sees the hub -- it just gets an empty peer list.
    """

class CrossServerNode:
    """Client half of the cross-server link.  One per MCDR instance."""
    uri: Incomplete
    name: Incomplete
    token: Incomplete
    app: Incomplete
    version: Incomplete
    handler: Incomplete
    logger: Incomplete
    reconnect: Incomplete
    auto_enroll: Incomplete
    _reconnect_delays: Incomplete
    _ping_interval: Incomplete
    _ping_timeout: Incomplete
    _max_message_size: Incomplete
    _conn: ClientConnection | None
    _thread: threading.Thread | None
    _first_attempt: Incomplete
    _first_result: bool | None
    _connected: Incomplete
    _stopping: Incomplete
    _lock: Incomplete
    _peers: list[str]
    _rid: int
    _pending: dict[str, tuple[threading.Event, dict]]
    _fatal: str | None
    hub_name: str
    expires_in: int | None
    enrol_requested: bool
    issued_token: str | None
    def __init__(self, uri: str, server_name: str, token: str = '', *, app: str = ..., version: str = '', handler: MessageHandler | None = None, logger: logging.Logger | None = None, reconnect: bool = True, reconnect_delays: Iterable[float] = ..., ping_interval: float = 20, ping_timeout: float = 20, max_message_size: int = ..., auto_enroll: bool = True) -> None: ...
    def start(self, timeout: float = 10.0) -> bool:
        """Start the link thread.  Returns True when the handshake succeeded."""
    def stop(self, timeout: float = 5.0) -> None:
        """Close the link and join the thread."""
    @property
    def connected(self) -> bool: ...
    @property
    def peers(self) -> list[str]:
        """The other servers, as the hub last reported them."""
    @property
    def fatal_error(self) -> str | None:
        """Why the node gave up, if it did."""
    def _run(self) -> None: ...
    def _drain_until_closed(self, connection: ClientConnection) -> None:
        """Read frames until the hub closes, so a fatal close code is never missed.

        The hub may answer a refused handshake with an error frame first (``enroll_pending``)
        and then close; nothing else can arrive on a connection that never registered.
        """
    def _handshake(self, connection: ClientConnection) -> bool: ...
    def _session(self, connection: ClientConnection) -> None: ...
    def _note_close(self, connection: ClientConnection, exc: Exception | None = None) -> None:
        """Remember a fatal close code so the retry loop can give up."""
    def _on_frame(self, connection: ClientConnection, raw: object) -> None: ...
    def _call_handler(self, msg: dict) -> dict: ...
    def send(self, target: str | None, action: str, message: str = '', data: dict | None = None, *, wait: bool = False, timeout: float = 5.0, event: bool = False) -> dict | None:
        '''Talk to the hub itself (``target=None``), to one peer, or to ``"*"``.

        ``event=True`` sends a fire and forget frame.  Otherwise every ``message``
        is answered with one ``reply``, which ``wait=True`` blocks for and returns
        as ``{"ok": bool, "message": str, "data": dict, "error": str | None}``.
        ``None`` comes back when the frame could not be sent at all.
        '''
    def _send_json(self, connection: ClientConnection, msg: dict) -> bool:
        """Send one frame, never one that is over the limit the other side enforces.

        websockets closes the connection with 1009 for anything larger than
        :data:`MAX_MESSAGE_SIZE`, so an oversized frame is shrunk to a small honest one
        first (``_shrink_oversized``) rather than taking the link down with it.
        """
    @staticmethod
    def _oversized(msg: dict) -> int | None:
        """The frame's size in bytes when it is too large to send, else None."""
    def _shrink_oversized(self, msg: dict, size: int) -> dict | None:
        """Replace a frame that cannot be sent with a small, honest one (or None to drop it)."""
    def ping(self, target: str | None = None, timeout: float = 5.0) -> float:
        """Application level round trip in seconds, or -1.0 when it failed."""
    def _next_rid(self) -> str: ...
    def _abort_pending(self, reason: str) -> int:
        '''Wake every caller waiting for a reply that can no longer arrive.

        The answer says ``unknown`` on purpose: the hub may have run the call before the link
        dropped, so the honest outcome is "we do not know", not "it failed".
        '''
    def _resolve_pending(self, msg: dict) -> None: ...
    def _answer(self, connection: ClientConnection, request: dict, payload: dict | None) -> None: ...
    def _close_quietly(self, connection: ClientConnection | None, code: int, reason: str) -> None: ...
