# Generated from games_ai/cluster/websockets_server.py by tools/build_tool_stubs.py -- do not edit.
import logging
import threading
from _typeshed import Incomplete
from collections.abc import Callable, Iterable
from typing import NamedTuple
from websockets.sync.server import ServerConnection as ServerConnection

APP_ID: str
APP_ID_BOT: str
ACCEPTED_PEER_APPS: Incomplete
PROTOCOL_VERSION: int
FEATURE_UPDATE_ORDER: str
CLOSE_BAD_HANDSHAKE: int
CLOSE_BAD_TOKEN: int
CLOSE_NO_NAME: int
CLOSE_REPLACED: int
CLOSE_BAD_PROTOCOL: int
CLOSE_NOT_GAMES_AI: int
CLOSE_ENROLMENT_REQUIRED: int
CLOSE_TOKEN_EXPIRED: int
MAX_MESSAGE_SIZE: Incomplete
FRAME_MARGIN: int
HANDSHAKE_TIMEOUT: float
MAX_ENROL_PENDING: int
ENROL_PENDING_TTL: Incomplete
ENROL_RATE_LIMIT: int
ENROL_RATE_WINDOW: float
NODE_TABLE_SEEN_INTERVAL: float
EXPIRY_WARNING_SECONDS: Incomplete
EXPIRY_WARNING_INTERVAL: float
MessageHandler = Callable[[dict], dict | None]

def hash_token(token: str) -> str:
    """The stored form of a token: plain sha256, hex. A 32-byte random token cannot be
    brute forced, so no salt or KDF is needed (the enrolment flow is documented in
    ``docs/<lang>/cross-server.md``)."""
def token_fingerprint(token: str) -> str:
    """The public short name of a token, safe to log and to show in commands."""
def remote_ip(connection) -> str:
    '''The address a connection comes from, without its port ("" when unknown).'''
def format_duration(seconds: float) -> str:
    """A compact duration for logs and command output: ``3d 4h`` / ``5h`` / ``12m`` / ``30s``."""

class Handshake(NamedTuple):
    """Outcome of one ``hello`` frame (see :meth:`CrossServerHub._handshake`).

    ``name`` is None when the client was refused; it is closed here with the close code
    that says why. ``token_name`` is set for a probe that presented a token the hub knows,
    so ``!!gamesai node claim`` can tell whose token it holds without enrolling anything.
    """
    name: str | None = ...
    probe: bool = ...
    app: str = ...
    token_ok: bool = ...
    expires_in: int | None = ...
    token_name: str | None = ...
    issued_token: str | None = ...
    version: str = ...
    features: tuple = ...

def _dumps(obj: dict) -> str: ...
def is_port_available(host: str, port: int) -> bool:
    """True when this process could bind ``host:port`` right now.

    Plain ``bind`` without ``SO_REUSEADDR`` on purpose: on Windows that option lets a
    second socket bind an address another process is already listening on, which would
    make an occupied port look free and turn the bind failure into a runtime surprise.
    """

class CrossServerHub:
    """Star-topology hub.  Run one per server network, in its own thread.

    The hub owns the node table (``config/games_ai/cross_server/nodes.json``): one hash per
    enrolled node plus the enrolment requests that are still waiting for an operator. It
    never holds a usable secret, so a leaked copy of that file does not allow impersonation.
    """
    host: Incomplete
    port: Incomplete
    name: Incomplete
    handler: Incomplete
    logger: Incomplete
    _ping_interval: Incomplete
    _ping_timeout: Incomplete
    _max_message_size: Incomplete
    accepted_apps: set[str]
    node_file: Incomplete
    ttl_hours: Incomplete
    on_bot_token: Incomplete
    on_peer_registered: Incomplete
    _nodes: dict[str, dict]
    _enrol_pending: dict[str, dict]
    _nodes_lock: Incomplete
    _last_expiry_warning: float
    _server: Incomplete
    _thread: threading.Thread | None
    _started: Incomplete
    _bind_ok: bool
    _stopping: Incomplete
    _lock: Incomplete
    _peers: dict[str, ServerConnection]
    _peer_apps: dict[str, str]
    _peer_info: dict[str, dict]
    _rid: int
    _pending: dict[str, tuple[threading.Event, dict, str]]
    _enrol_rate: dict[str, tuple[float, int]]
    def __init__(self, host: str, port: int, *, name: str = 'hub', handler: MessageHandler | None = None, logger: logging.Logger | None = None, ping_interval: float = 20, ping_timeout: float = 20, max_message_size: int = ..., extra_app_ids: Iterable[str] = (), node_file: str | None = None, ttl_hours: int = -1, on_bot_token: Callable[[str, str], None] | None = None, on_peer_registered: Callable[[str, str, tuple], None] | None = None) -> None: ...
    def _load_node_table(self) -> None:
        '''Read the node table; a missing file simply means "nobody is enrolled yet".'''
    def _save_node_table(self) -> None:
        """Write the node table. Call with :attr:`_nodes_lock` held."""
    @property
    def nodes(self) -> dict[str, dict]:
        """A copy of the node table: name -> {app, hash, issued_at, ttl_hours, ...}."""
    @property
    def pending_requests(self) -> dict[str, dict]:
        """A copy of the enrolment requests waiting for ``!!gamesai node token <name>``.

        Entries nobody acted on within :data:`ENROL_PENDING_TTL` are dropped here, so the list
        an operator sees is the list that can still be issued to.
        """
    def is_enrolled(self, name: str) -> bool: ...
    def is_pending(self, name: str) -> bool: ...
    def fingerprint(self, name: str) -> str | None:
        """The public fingerprint (hash[:6]) of a node's token, or None when not enrolled."""
    def expires_in(self, name: str) -> int | None:
        """Seconds until this node's token expires; None when unknown or unlimited."""
    def name_for_token(self, token: str) -> str | None:
        """Which node a token belongs to, or None when the hub does not know it.

        Used for a probe that carries a token, which is how ``!!gamesai node claim`` checks
        the name a token was issued for before writing anything.
        """
    def _prune_pending_locked(self, now: float) -> int:
        """Drop enrolment requests nobody acted on. Call with :attr:`_nodes_lock` held."""
    def _enrol_rate_ok_locked(self, ip: str, now: float) -> bool:
        """One address may ask for a limited number of *new* names per window."""
    def enrol(self, name: str, app: str = '', ip: str = '') -> dict:
        """Record (or refresh) an enrolment request. Never authorises anything by itself.

        This runs for peers that are not authenticated yet, so it is the one table an outsider
        can write to: new names are capped (:data:`MAX_ENROL_PENDING`), limited per address
        (:data:`ENROL_RATE_LIMIT` per :data:`ENROL_RATE_WINDOW`) and dropped once they are older
        than :data:`ENROL_PENDING_TTL`. A refused request changes nothing and writes nothing;
        the returned dict says why (``refused``) so the handshake can be honest about it.
        """
    def issue(self, name: str, *, app: str = '', issued_by: str = '', ip: str = '', require_pending: bool = False, replace: bool = False) -> str | None:
        """Mint a token for one node and store its hash. Returns the plaintext, once.

        ``require_pending`` is what makes ``!!gamesai node token <name>`` strict: a name that
        never asked to enrol gets no token.

        A name that is already enrolled is never taken over unless the caller says so with
        ``replace``: the table holds one entry per name, so minting a second token would drop
        the first node's hash and that node's next connect would fail with 4001 -- which is not
        retryable, so it stays offline until somebody reloads it. Two instances that share a
        name is the usual cause (see the default name derivation in the plugin). ``replace``
        is for the two callers that mean it: ``!!gamesai node rotate`` and the Mineflayer bot's
        automatic provisioning.
        """
    def rotate(self, name: str, *, issued_by: str = '') -> str | None:
        '''Issue a new token for a node that is already enrolled; the old one dies now.

        Replacing is the whole point here, so it passes ``replace=True``: this is the operator
        saying "the token of *this* node is lost or suspected leaked".
        '''
    def revoke(self, name: str) -> bool:
        """Drop a node entry (and any outstanding request); its next connect fails with 4001."""
    def verify(self, name: str, app: str, token: str) -> str:
        '''Check one node\'s token. Returns ``"ok"``, ``"expired"`` or ``"unknown"``.

        The comparison is constant time and works on the hash, so the hub never needs the
        plaintext. A name or app that does not match is "unknown": a token is bound to the
        one name (and identity) it was issued for.
        '''
    def record_seen(self, name: str, ip: str = '', *, version: str = '', features: tuple = ()) -> None:
        """Remember when (and from where) an enrolled node last registered, and its build.

        This runs on every handshake, so it only rewrites the table when the answer really
        changed: a new source address, a new version or feature set, or a timestamp older than
        :data:`NODE_TABLE_SEEN_INTERVAL`. A stable cluster therefore stops writing the file once
        per reconnect.

        The build fields matter across a hub restart: an offline node that was last seen on an
        older version has to be updated once it comes back, and the round that decides that runs
        right after the hub itself has restarted.
        """
    def ttl_text(self) -> str:
        """The configured TTL as a word for logs and command output."""
    def _warn_expiring(self) -> None:
        """Warn about tokens that expire within 24h -- at most one line per hour."""
    def start(self, timeout: float = 10.0) -> bool:
        """Bind the port and start serving in a daemon thread.

        Returns False when the port could not be bound (it is occupied, or the host is
        not local) -- the caller then falls back to local mode instead of pretending to
        be a hub.
        """
    def _serve(self) -> None: ...
    def stop(self, timeout: float = 5.0) -> None:
        """Stop listening, drop every node and join the thread."""
    @property
    def is_running(self) -> bool: ...
    @property
    def peers(self) -> list[str]:
        """Names of the nodes registered right now."""
    def send(self, target: str | None, action: str, message: str = '', data: dict | None = None, *, wait: bool = False, timeout: float = 5.0) -> dict | None:
        '''Send to one node (``target`` = its name) or handle it locally (``None``).

        With ``wait=True`` this blocks until the peer\'s reply arrives and returns
        it as ``{"ok": bool, "message": str, "data": dict, "error": str | None}``.
        With ``wait=False`` it returns ``None`` right away (``None`` also means the
        frame could not be sent at all, e.g. the target is offline).
        '''
    def deliver(self, target: str, action: str, message: str = '', data: dict | None = None) -> bool:
        '''Send straight to a registered peer, even when its name equals the hub\'s own.

        :meth:`send` treats ``target == self.name`` as "the hub handles it", which is right for
        commands a local player typed but wrong for a *peer* that happens to share the hub\'s
        name (possible whenever two instances are given the same ``websocket.name``).
        '''
    def broadcast(self, action: str, message: str = '', data: dict | None = None, apps: str | Iterable[str] | None = None) -> int:
        """Fire and forget to every registered peer.  Returns how many got it.

        ``apps`` restricts the fan-out to some identities: cluster-wide commands go to the
        trusted instances (see :attr:`command_apps`), never to the bot.
        """
    @staticmethod
    def _normalise_apps(apps: str | Iterable[str] | None) -> set[str] | None: ...
    @property
    def command_apps(self) -> set[str]:
        """Identities that may take part in cluster-wide commands: everything trusted
        except the bot, which only answers ``bot_action``."""
    @property
    def peer_apps(self) -> dict[str, str]:
        """The identity each online peer announced (name -> app)."""
    @property
    def peer_versions(self) -> dict[str, str]:
        '''The plugin version each online peer announced at its handshake (name -> version).

        Empty string means "it did not say" -- an instance running a build from before the
        field existed. The cluster update round reads this to find out which nodes still have
        to be updated, and after an update it is the authoritative "the node came back on the
        new version" signal.
        '''
    def peer_supports(self, name: str, feature: str) -> bool:
        '''True when that online peer announced ``feature`` in its hello frame.

        A peer that never announces it (older build, or a non-GamesAI service admitted through
        ``allow_app_id``) can only be *reported*, never ordered: it would answer the order with
        the automatic ``{"ok": true}`` that every unknown action gets.
        '''
    def _is_bot_peer(self, name: str) -> bool:
        """True when that online peer registered with the bot identity (see :meth:`_on_frame`)."""
    def peers_of(self, app: str) -> list[str]:
        """The online peers of one kind, e.g. only the Mineflayer bots."""
    def ping(self, target: str | None = None, timeout: float = 5.0) -> dict:
        '''Round trip in seconds.  ``target=None`` measures every node at once.

        Returns ``{"alpha": 0.0031, "beta": -1.0}`` -- ``-1.0`` means no reply.
        '''
    def _next_rid(self) -> str: ...
    def _send_and_maybe_wait(self, msg: dict, wait: bool, timeout: float) -> dict | None: ...
    def _call_handler(self, msg: dict) -> dict: ...
    def _handler(self, connection: ServerConnection) -> None:
        """Serve one node; websockets gives every connection its own thread."""
    def _handshake(self, connection: ServerConnection) -> Handshake:
        """Read the hello frame and decide what this connection is (see the frame table in
        ``docs/<lang>/cross-server.md`` and the module docstring above).

        A rejected client is closed here with the close code that says why; the returned
        :class:`Handshake` then carries ``name = None``.
        """
    def _bot_auto_issue_allowed(self, ip: str) -> bool:
        """May a token-less Mineflayer bot be provisioned from this address right now?

        Yes only over the loopback interface (the bot runs on the hub's own machine) or from
        the address of an already enrolled node (the bot runs on a client's machine, next to
        that node). Anywhere else the request is treated like any other unenrolled one, so a
        stranger who can reach the port cannot have a token minted for a name.
        """
    def _hello_ack(self, peers: list[str], you: str = ..., *, expires_in: int | None = None, token: str | None = None, token_name: str | None = None) -> dict: ...
    def _push_peers(self) -> None:
        """Tell every node who is online, so the list never goes stale."""
    def _on_frame(self, sender: str, connection: ServerConnection, raw: object) -> None: ...
    def _refuse_bot_frame(self, connection: ServerConnection, sender: str, msg: dict, frame_type: object) -> bool:
        """Stop a bot peer's ``message`` / ``event`` frames before anything looks at them.

        A bot only ever *answers* ``bot_action``: it is never a source of commands. The check
        runs before the ``event`` branch and before the ``message`` routing, so such a frame can
        be neither handled locally (``command`` frames carry ``console: true`` and are executed
        at level 4) nor relayed to another instance. The addresses that may obtain the bot
        identity -- loopback, which a tunnel or reverse proxy makes *every* peer look like, or an
        enrolled node's address -- are deliberately not a trust boundary for command execution.

        ``hello`` (handshake), ``ping`` (answered by the caller of this method's sibling) and
        ``reply`` (the bot's whole purpose) are unaffected.
        """
    def _fanout(self, msg: dict, *, exclude: str | None = None, apps: str | Iterable[str] | None = None) -> int: ...
    def _deliver(self, name: str, msg: dict) -> bool: ...
    def _resolve_pending(self, msg: dict) -> None: ...
    def _abort_pending(self, target: str | None, reason: str) -> int:
        '''Wake every caller waiting for ``target`` (or for anyone, when it is None).

        Without this a caller only learns about a dropped connection when its own timeout runs
        out -- the AI round of a routed tool call would sit there for the full 120 seconds. The
        answer says ``unknown`` on purpose: the peer may have run the call before it dropped, so
        the honest outcome is "we do not know", not "it failed".
        '''
    def _answer(self, connection: ServerConnection, request: dict, payload: dict | None) -> None: ...
    def _oversized(self, msg: dict) -> int | None:
        """The frame's size in bytes when it is too large to send, else None.

        The receiving side closes the connection with 1009 for anything over
        :data:`MAX_MESSAGE_SIZE`, so an oversized reply must never be handed to websockets: it
        would take the whole link down (and every other conversation with it).
        """
    def _send(self, connection: ServerConnection, msg: dict) -> bool: ...
    def _shrink_oversized(self, msg: dict, size: int) -> dict | None:
        """Replace a frame that cannot be sent with a small, honest one (or None to drop it).

        A ``reply`` keeps the request_id, so whoever waits for it fails immediately with a real
        reason instead of a 120 second timeout. A streamed ``command_reply`` becomes one short
        line. Anything else is dropped with a warning.
        """
    def _close_quietly(self, connection: ServerConnection, code: int, reason: str) -> None: ...
