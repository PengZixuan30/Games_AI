"""Cross-server hub -- the WebSocket server half of the cross-server link.

One MCDR instance runs the hub, and every instance (including that one) may run
a node from websockets_client.py and dial into it.  The hub keeps a
``server name -> connection`` table and routes frames between the nodes, so the
topology is a star: only the hub listens, only the hub needs an open port.

Wire protocol -- one JSON object per text frame:

    node -> hub   hello       {"type": "hello", "protocol": 1, "server": "alpha",
                               "token": "<this node's token>", "version": "0.7.3",
                               "features": ["update_order"]}
    node -> hub   hello       {"type": "hello", "protocol": 1, "server": "alpha",
                               "enroll": true, "version": "0.7.3"}   -- no token yet
    hub -> node   enroll_pending  {"type": "enroll_pending", "name": "alpha", ...}
    hub -> node   hello_ack   {"type": "hello_ack", "protocol": 1, "hub": "hub",
                               "peers": ["beta"], "expires_in": 86400}
    both          message     {"type": "message", "request_id": "alpha#7",
                               "source": "alpha", "target": "beta" | "*" | None,
                               "action": "chat", "message": "hi", "data": {}}
    both          reply       {"type": "reply", "request_id": "alpha#7",
                               "source": "beta", "target": "alpha", "ok": True,
                               "message": "hi back", "data": {}, "error": None}
    both          event       same shape as message, never answered

Routing rules:

* the hub always overwrites ``source`` with the registered name of the sender,
  so a node cannot impersonate another one;
* ``target`` = a peer name -> that peer only;
* ``target`` = ``"*"`` -> every peer except the sender;
* ``target`` missing, empty or equal to the hub's own name -> the hub handles
  the message locally through ``handler``;
* every ``message`` is answered with exactly one ``reply``, an ``event`` is not;
* ``action`` = ``"ping"`` is answered by the hub itself with ``"pong"``.

Enrolment -- the hub issues one token per node and keeps only its hash:

* a node that has no token sends ``enroll: true`` and no token; the hub records the
  request in its ``pending`` table, answers ``enroll_pending`` and closes with ``4007``.
  That close code is not retryable: the node cannot succeed until an operator issues a
  token (``!!gamesai node token <name>``) and claims it on that node;
* a token the hub knows and that has not expired registers the node normally. The
  ``hello_ack`` carries ``expires_in`` (seconds, omitted when the token never expires);
* the Mineflayer bot is provisioned without a human step: an ``app: mineflayer_bot``
  handshake without a token is answered with a freshly issued one, but only when it comes
  over the loopback interface (the bot runs on the hub's machine) or from the address of
  an already enrolled node (the bot runs on a client's machine);
* probes (``probe: true``) never enrol and never touch ``pending``: they are answered
  without any token, and only learn the online list when they carry a token the hub knows.

Close codes -- keep in sync with websockets_client.py:

    4000 bad handshake, 4001 unknown or revoked token, 4002 no server name,
    4003 the name was taken over by a newer connection,
    4004 protocol version mismatch,
    4005 the peer is not a GamesAI instance (its hello did not identify itself as one),
    4007 enrolment required (the request was recorded, or refused), not retryable,
    4008 the enrolment token expired, not retryable.

Threading: every connection is served in its own thread by the library, and
``Connection.send()`` takes the protocol lock internally, so :meth:`send` and
:meth:`broadcast` may be called from any MCDR thread. The node table is guarded
by its own lock and written to disk on every change.
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import socket
import threading
import time
from collections.abc import Callable, Iterable
from typing import NamedTuple

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import ServerConnection, serve

# The identity a peer announces in its hello frame. The hub adapts to it: a GamesAI-MCDR
# instance takes part in command routing and cluster-wide commands, a Mineflayer bot only
# answers `bot_action` requests. GamesAI-Java will announce `games_ai_java`; until it is a
# built-in, admit it through ``websocket.allow_app_id``.
APP_ID = "games_ai_mcdr"            # this hub's own identity (a GamesAI-MCDR instance)
APP_ID_BOT = "mineflayer_bot"       # a Mineflayer bot client
ACCEPTED_PEER_APPS = (APP_ID, APP_ID_BOT)

# Extra identities the user admits through ``websocket.allow_app_id``. They are accepted and
# routed like any other peer -- the hub applies no bespoke handling for them, it only stops
# refusing them with 4005.

PROTOCOL_VERSION = 1

# Optional capabilities a peer announces in its hello frame. They are additive on purpose:
# an instance running an older build sends no ``features`` at all, and the hub must then treat
# it as "cannot be ordered around" rather than as a protocol error (the wire version stays 1,
# so a half-updated cluster keeps talking -- see docs/<lang>/cross-server.md).
FEATURE_UPDATE_ORDER = "update_order"

CLOSE_BAD_HANDSHAKE = 4000
CLOSE_BAD_TOKEN = 4001
CLOSE_NO_NAME = 4002
CLOSE_REPLACED = 4003
CLOSE_BAD_PROTOCOL = 4004
CLOSE_NOT_GAMES_AI = 4005
CLOSE_ENROLMENT_REQUIRED = 4007
CLOSE_TOKEN_EXPIRED = 4008

MAX_MESSAGE_SIZE = 1 << 20
# A frame has to fit the receiver's limit, so the checks below leave a margin for the JSON
# envelope itself (the fields are added before the length is measured, but a reply built on top
# of an already large frame must not push it over).
FRAME_MARGIN = 1024
HANDSHAKE_TIMEOUT = 10.0

# Enrolment requests arrive from instances that are not authenticated yet, so the table needs
# its own limits: a full or stale `pending` list must not grow without bound, and an address
# that floods it must not be able to fill it (or the disk) at will.
MAX_ENROL_PENDING = 32
ENROL_PENDING_TTL = 7 * 24 * 3600
ENROL_RATE_LIMIT = 10
ENROL_RATE_WINDOW = 60.0
# `record_seen` runs on every handshake; the timestamps it stores are informational, so a
# stable cluster must not rewrite the table once per reconnect.
NODE_TABLE_SEEN_INTERVAL = 600.0

# A token that is about to run out is worth a warning while the operator can still rotate it,
# but the check runs on every handshake, so it is rate limited.
EXPIRY_WARNING_SECONDS = 24 * 3600
EXPIRY_WARNING_INTERVAL = 3600.0

# handler(msg) -> None (nothing to say) or a dict merged into the reply:
#   {"message": str, "data": dict, "ok": bool, "error": str}
# msg carries {"type", "source", "action", "message", "data", "request_id"}.
MessageHandler = Callable[[dict], dict | None]


def hash_token(token: str) -> str:
    """The stored form of a token: plain sha256, hex. A 32-byte random token cannot be
    brute forced, so no salt or KDF is needed (the enrolment flow is documented in
    ``docs/<lang>/cross-server.md``)."""
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def token_fingerprint(token: str) -> str:
    """The public short name of a token, safe to log and to show in commands."""
    return hash_token(token)[:6]


def remote_ip(connection) -> str:
    """The address a connection comes from, without its port ("" when unknown)."""
    address = getattr(connection, "remote_address", None)
    if isinstance(address, (tuple, list)) and address:
        return str(address[0] or "")
    return ""


def format_duration(seconds: float) -> str:
    """A compact duration for logs and command output: ``3d 4h`` / ``5h`` / ``12m`` / ``30s``."""
    seconds = max(0, int(seconds))
    if seconds >= 86400:
        return f"{seconds // 86400}d {seconds % 86400 // 3600}h"
    if seconds >= 3600:
        return f"{seconds // 3600}h {seconds % 3600 // 60}m"
    if seconds >= 60:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds}s"


class Handshake(NamedTuple):
    """Outcome of one ``hello`` frame (see :meth:`CrossServerHub._handshake`).

    ``name`` is None when the client was refused; it is closed here with the close code
    that says why. ``token_name`` is set for a probe that presented a token the hub knows,
    so ``!!gamesai node claim`` can tell whose token it holds without enrolling anything.
    """

    name: str | None = None
    probe: bool = False
    app: str = ""
    token_ok: bool = False
    expires_in: int | None = None
    token_name: str | None = None
    issued_token: str | None = None
    #: The plugin version the peer announced, and the optional features it understands.
    #: Both are informational: the hub uses them to decide whether a peer can be ordered to
    #: update itself (see ``FEATURE_UPDATE_ORDER``), and records them in the node table.
    version: str = ""
    features: tuple = ()


def _dumps(obj: dict) -> str:
    # ensure_ascii=False keeps Chinese readable in the frame and on the wire.
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def is_port_available(host: str, port: int) -> bool:
    """True when this process could bind ``host:port`` right now.

    Plain ``bind`` without ``SO_REUSEADDR`` on purpose: on Windows that option lets a
    second socket bind an address another process is already listening on, which would
    make an occupied port look free and turn the bind failure into a runtime surprise.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((host, port))
    except OSError:
        return False
    return True


class CrossServerHub:
    """Star-topology hub.  Run one per server network, in its own thread.

    The hub owns the node table (``config/games_ai/cross_server/nodes.json``): one hash per
    enrolled node plus the enrolment requests that are still waiting for an operator. It
    never holds a usable secret, so a leaked copy of that file does not allow impersonation.
    """

    def __init__(
        self,
        host: str,
        port: int,
        *,
        name: str = "hub",
        handler: MessageHandler | None = None,
        logger: logging.Logger | None = None,
        ping_interval: float = 20,
        ping_timeout: float = 20,
        max_message_size: int = MAX_MESSAGE_SIZE,
        extra_app_ids: Iterable[str] = (),
        node_file: str | None = None,
        ttl_hours: int = -1,
        on_bot_token: Callable[[str, str], None] | None = None,
        on_peer_registered: Callable[[str, str, tuple], None] | None = None,
    ):
        self.host = host
        self.port = port
        self.name = name
        self.handler = handler
        self.logger = logger or logging.getLogger(__name__)

        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout
        self._max_message_size = max_message_size
        self.accepted_apps: set[str] = set(ACCEPTED_PEER_APPS) | {
            str(app_id).strip() for app_id in extra_app_ids if str(app_id).strip()
        }

        # Node table. ``node_file`` = None keeps it in memory only (tests, throwaway hubs).
        self.node_file = str(node_file) if node_file else None
        self.ttl_hours = int(ttl_hours)
        # Called with (name, token) when the hub provisions the Mineflayer bot by itself, so
        # the plugin can write the token into the bot's own config file.
        self.on_bot_token = on_bot_token
        # Called with (name, version, features) after a peer registered. Runs on that peer's
        # connection thread, so the callback must return quickly; it is what lets the plugin
        # notice "a node came back on an older version" without polling.
        self.on_peer_registered = on_peer_registered
        self._nodes: dict[str, dict] = {}
        self._enrol_pending: dict[str, dict] = {}
        self._nodes_lock = threading.RLock()
        self._last_expiry_warning = 0.0
        self._load_node_table()

        self._server = None                              # websockets.sync.server.Server
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
        self._bind_ok = False
        self._stopping = threading.Event()

        self._lock = threading.RLock()
        self._peers: dict[str, ServerConnection] = {}
        self._peer_apps: dict[str, str] = {}         # peer name -> the app id it announced
        # peer name -> {"version": str, "features": frozenset}: what the hello frame said.
        # Kept in memory only; the node table carries the same two fields for offline nodes.
        self._peer_info: dict[str, dict] = {}
        self._rid = 0
        # request_id -> (wake, box, target). The target is kept so a peer that drops can wake
        # the callers waiting for it instead of leaving them on the timeout (see _abort_pending).
        self._pending: dict[str, tuple[threading.Event, dict, str]] = {}
        # address -> (window_started, new requests in that window), for the enrolment limit.
        self._enrol_rate: dict[str, tuple[float, int]] = {}

    # ------------------------------------------------------------- node table
    def _load_node_table(self) -> None:
        """Read the node table; a missing file simply means "nobody is enrolled yet"."""
        if not self.node_file or not os.path.isfile(self.node_file):
            return
        try:
            with open(self.node_file, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, ValueError):
            # Losing the table invalidates every token; say so instead of pretending the
            # nodes are still enrolled (each of them then has to claim a new token).
            self.logger.error(
                f"cannot read the node table {self.node_file!r}; every node must claim a new token"
            )
            return
        if not isinstance(raw, dict):
            self.logger.error(f"the node table {self.node_file!r} is not an object, ignoring it")
            return
        nodes = raw.get("nodes")
        pending = raw.get("pending")
        if isinstance(nodes, dict):
            self._nodes = {str(key): value for key, value in nodes.items() if isinstance(value, dict)}
        if isinstance(pending, dict):
            self._enrol_pending = {str(key): value for key, value in pending.items()
                                   if isinstance(value, dict)}
        if self._nodes:
            self.logger.info(f"node table loaded: {len(self._nodes)} enrolled node(s)")

    def _save_node_table(self) -> None:
        """Write the node table. Call with :attr:`_nodes_lock` held."""
        if not self.node_file:
            return
        try:
            folder = os.path.dirname(os.path.abspath(self.node_file))
            if folder:
                os.makedirs(folder, exist_ok=True)
            tmp = self.node_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump({"nodes": self._nodes, "pending": self._enrol_pending},
                          handle, indent=2, ensure_ascii=False)
            os.replace(tmp, self.node_file)              # never leave a half-written table
            try:
                os.chmod(self.node_file, 0o600)          # hashes only, but keep it private
            except OSError:
                pass
        except OSError:
            self.logger.exception(f"failed to write the node table {self.node_file!r}")

    @property
    def nodes(self) -> dict[str, dict]:
        """A copy of the node table: name -> {app, hash, issued_at, ttl_hours, ...}."""
        with self._nodes_lock:
            return {name: dict(entry) for name, entry in self._nodes.items()}

    @property
    def pending_requests(self) -> dict[str, dict]:
        """A copy of the enrolment requests waiting for ``!!gamesai node token <name>``.

        Entries nobody acted on within :data:`ENROL_PENDING_TTL` are dropped here, so the list
        an operator sees is the list that can still be issued to.
        """
        with self._nodes_lock:
            self._prune_pending_locked(time.time())
            return {name: dict(entry) for name, entry in self._enrol_pending.items()}

    def is_enrolled(self, name: str) -> bool:
        with self._nodes_lock:
            return str(name) in self._nodes

    def is_pending(self, name: str) -> bool:
        with self._nodes_lock:
            self._prune_pending_locked(time.time())
            return str(name) in self._enrol_pending

    def fingerprint(self, name: str) -> str | None:
        """The public fingerprint (hash[:6]) of a node's token, or None when not enrolled."""
        with self._nodes_lock:
            entry = self._nodes.get(str(name))
            if entry is None:
                return None
            stored = str(entry.get("hash") or "")
        return stored[:6] if stored else None

    def expires_in(self, name: str) -> int | None:
        """Seconds until this node's token expires; None when unknown or unlimited."""
        with self._nodes_lock:
            entry = self._nodes.get(str(name))
            if entry is None:
                return None
            ttl = entry.get("ttl_hours")
            issued_at = entry.get("issued_at")
        try:
            ttl = int(ttl)
            issued_at = int(issued_at)
        except (TypeError, ValueError):
            return None
        if ttl < 0:
            return None
        return int(issued_at + ttl * 3600 - time.time())

    def name_for_token(self, token: str) -> str | None:
        """Which node a token belongs to, or None when the hub does not know it.

        Used for a probe that carries a token, which is how ``!!gamesai node claim`` checks
        the name a token was issued for before writing anything.
        """
        if not token:
            return None
        wanted = hash_token(token)
        with self._nodes_lock:
            for name, entry in self._nodes.items():
                if hmac.compare_digest(str(entry.get("hash") or ""), wanted):
                    return name
        return None

    def _prune_pending_locked(self, now: float) -> int:
        """Drop enrolment requests nobody acted on. Call with :attr:`_nodes_lock` held."""
        stale = [name for name, entry in self._enrol_pending.items()
                 if now - float(entry.get("requested_at") or 0) > ENROL_PENDING_TTL]
        for name in stale:
            self._enrol_pending.pop(name, None)
        return len(stale)

    def _enrol_rate_ok_locked(self, ip: str, now: float) -> bool:
        """One address may ask for a limited number of *new* names per window."""
        if not ip:
            return True
        if len(self._enrol_rate) > 256:
            # The limiter must not become the next unbounded table: drop the windows that have
            # already expired once it grows past a few hundred addresses.
            self._enrol_rate = {key: value for key, value in self._enrol_rate.items()
                                if now - value[0] < ENROL_RATE_WINDOW}
        started, count = self._enrol_rate.get(ip) or (now, 0)
        if now - started >= ENROL_RATE_WINDOW:
            self._enrol_rate[ip] = (now, 1)
            return True
        if count >= ENROL_RATE_LIMIT:
            self._enrol_rate[ip] = (started, count + 1)      # keep counting, for the log line
            return False
        self._enrol_rate[ip] = (started, count + 1)
        return True

    def enrol(self, name: str, app: str = "", ip: str = "") -> dict:
        """Record (or refresh) an enrolment request. Never authorises anything by itself.

        This runs for peers that are not authenticated yet, so it is the one table an outsider
        can write to: new names are capped (:data:`MAX_ENROL_PENDING`), limited per address
        (:data:`ENROL_RATE_LIMIT` per :data:`ENROL_RATE_WINDOW`) and dropped once they are older
        than :data:`ENROL_PENDING_TTL`. A refused request changes nothing and writes nothing;
        the returned dict says why (``refused``) so the handshake can be honest about it.
        """
        name = str(name or "").strip()
        now = time.time()
        with self._nodes_lock:
            pruned = self._prune_pending_locked(now)
            previous = self._enrol_pending.get(name)
            if previous is None:
                if len(self._enrol_pending) >= MAX_ENROL_PENDING:
                    entry = {"app": str(app or ""), "requested_at": int(now),
                             "ip": str(ip or ""), "requests": 0, "refused": "full"}
                elif not self._enrol_rate_ok_locked(ip, now):
                    entry = {"app": str(app or ""), "requested_at": int(now),
                             "ip": str(ip or ""), "requests": 0, "refused": "rate"}
                else:
                    entry = {"app": str(app or ""), "requested_at": int(now),
                             "ip": str(ip or ""), "requests": 1}
                    self._enrol_pending[name] = entry
                    self._save_node_table()
            else:
                # A name that is already waiting is a retry by (presumably) the same instance:
                # it does not consume the rate limit and does not rewrite the table.
                entry = {
                    "app": str(app or previous.get("app") or ""),
                    "requested_at": int(previous.get("requested_at") or now),
                    "ip": str(ip or previous.get("ip") or ""),
                    "requests": int(previous.get("requests") or 0) + 1,
                }
                self._enrol_pending[name] = entry
                if pruned:
                    self._save_node_table()                  # only the prune changed the file
        if entry.get("refused"):
            self.logger.warning(
                f"refused the enrolment request of node {name!r} from {ip or '?'} "
                f"({entry['refused']}: {'the waiting list is full' if entry['refused'] == 'full' else 'too many new requests from that address'})"
            )
            return dict(entry)
        self.logger.info(
            f"node {name!r} asked to enrol (app {app or 'unknown'}, from {ip or '?'}, "
            f"request #{entry['requests']})"
        )
        if self.is_enrolled(name):
            # The pending request is under a name that already has an entry. It is either the
            # same node re-enrolling (after !!gamesai node forget -- fine, the operator then
            # runs node rotate) or a second instance that happens to use the same name, which
            # must not be given a token: it would take the enrolled node's place (see issue).
            self.logger.warning(
                f"node {name!r} is already enrolled and asked to enrol again: if this is a "
                f"different instance, give it its own websocket.name before issuing a token, "
                f"or use !!gamesai node rotate {name} to replace that node on purpose"
            )
        return dict(entry)

    def issue(self, name: str, *, app: str = "", issued_by: str = "", ip: str = "",
              require_pending: bool = False, replace: bool = False) -> str | None:
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
        name = str(name or "").strip()
        if not name:
            return None
        with self._nodes_lock:
            if require_pending and name not in self._enrol_pending:
                return None
            if not replace and name in self._nodes:
                return None
            token = secrets.token_urlsafe(32)
            self._nodes[name] = {
                "app": str(app or ""),
                "hash": hash_token(token),
                "issued_at": int(time.time()),
                "ttl_hours": int(self.ttl_hours),
                "last_seen": None,
                "last_ip": str(ip or ""),
                "issued_by": str(issued_by or ""),
            }
            self._enrol_pending.pop(name, None)
            self._save_node_table()
        self.logger.info(
            f"issued an enrolment token for node {name!r} to {issued_by or 'unknown'} "
            f"(fingerprint {token_fingerprint(token)}, ttl {self.ttl_text()})"
        )
        return token

    def rotate(self, name: str, *, issued_by: str = "") -> str | None:
        """Issue a new token for a node that is already enrolled; the old one dies now.

        Replacing is the whole point here, so it passes ``replace=True``: this is the operator
        saying "the token of *this* node is lost or suspected leaked".
        """
        name = str(name or "").strip()
        with self._nodes_lock:
            entry = self._nodes.get(name)
            if entry is None:
                return None
            app = str(entry.get("app") or "")
            ip = str(entry.get("last_ip") or "")
        return self.issue(name, app=app, issued_by=issued_by, ip=ip, replace=True)

    def revoke(self, name: str) -> bool:
        """Drop a node entry (and any outstanding request); its next connect fails with 4001."""
        name = str(name or "").strip()
        with self._nodes_lock:
            entry = self._nodes.pop(name, None)
            self._enrol_pending.pop(name, None)
            if entry is None:
                return False
            self._save_node_table()
        self.logger.info(f"revoked the enrolment token of node {name!r}")
        return True

    def verify(self, name: str, app: str, token: str) -> str:
        """Check one node's token. Returns ``"ok"``, ``"expired"`` or ``"unknown"``.

        The comparison is constant time and works on the hash, so the hub never needs the
        plaintext. A name or app that does not match is "unknown": a token is bound to the
        one name (and identity) it was issued for.
        """
        if not name or not token:
            return "unknown"
        with self._nodes_lock:
            entry = self._nodes.get(str(name))
            if entry is None:
                return "unknown"
            if app and entry.get("app") and str(entry["app"]) != str(app):
                return "unknown"
            stored = str(entry.get("hash") or "")
        if not stored or not hmac.compare_digest(stored, hash_token(token)):
            return "unknown"
        remaining = self.expires_in(name)
        if remaining is not None and remaining <= 0:
            return "expired"
        return "ok"

    def record_seen(self, name: str, ip: str = "", *, version: str = "",
                    features: tuple = ()) -> None:
        """Remember when (and from where) an enrolled node last registered, and its build.

        This runs on every handshake, so it only rewrites the table when the answer really
        changed: a new source address, a new version or feature set, or a timestamp older than
        :data:`NODE_TABLE_SEEN_INTERVAL`. A stable cluster therefore stops writing the file once
        per reconnect.

        The build fields matter across a hub restart: an offline node that was last seen on an
        older version has to be updated once it comes back, and the round that decides that runs
        right after the hub itself has restarted.
        """
        now = time.time()
        new_features = sorted(str(item) for item in features)
        with self._nodes_lock:
            entry = self._nodes.get(str(name))
            if entry is None:
                return
            last_seen = entry.get("last_seen") or 0
            new_ip = str(ip) if ip else str(entry.get("last_ip") or "")
            material = (new_ip != str(entry.get("last_ip") or "")
                        or str(entry.get("version") or "") != str(version)
                        or sorted(entry.get("features") or []) != new_features
                        or now - float(last_seen) >= NODE_TABLE_SEEN_INTERVAL)
            entry["last_seen"] = int(now)
            if ip:
                entry["last_ip"] = str(ip)
            entry["version"] = str(version)
            entry["features"] = new_features
            if material:
                self._save_node_table()

    def ttl_text(self) -> str:
        """The configured TTL as a word for logs and command output."""
        return "unlimited" if self.ttl_hours < 0 else f"{self.ttl_hours}h"

    def _warn_expiring(self) -> None:
        """Warn about tokens that expire within 24h -- at most one line per hour."""
        now = time.time()
        if now - self._last_expiry_warning < EXPIRY_WARNING_INTERVAL:
            return
        soon = []
        for name in self.nodes:
            remaining = self.expires_in(name)
            if remaining is not None and 0 < remaining <= EXPIRY_WARNING_SECONDS:
                soon.append((name, remaining))
        if not soon:
            return
        self._last_expiry_warning = now
        for name, remaining in soon:
            self.logger.warning(
                f"the enrolment token of node {name!r} expires in {format_duration(remaining)}; "
                f"rotate it with !!gamesai node rotate {name}"
            )

    # ------------------------------------------------------------- lifecycle
    def start(self, timeout: float = 10.0) -> bool:
        """Bind the port and start serving in a daemon thread.

        Returns False when the port could not be bound (it is occupied, or the host is
        not local) -- the caller then falls back to local mode instead of pretending to
        be a hub.
        """
        if self._thread is not None:
            raise RuntimeError("the hub is already started")
        self._thread = threading.Thread(target=self._serve, name="games_ai@ws_hub", daemon=True)
        self._thread.start()
        if not self._started.wait(timeout):
            return False
        return bool(self._bind_ok)

    def _serve(self) -> None:
        try:
            with serve(
                self._handler,
                self.host,
                self.port,
                ping_interval=self._ping_interval,
                ping_timeout=self._ping_timeout,
                max_size=self._max_message_size,
                logger=self.logger,
            ) as server:
                self._server = server
                self._bind_ok = True
                self._started.set()
                self.logger.info(f"cross-server hub listening on ws://{self.host}:{self.port}")
                server.serve_forever()                   # blocks until shutdown()
        except Exception as exc:
            self._bind_ok = False
            self._started.set()                          # unblock start() with a failure
            self.logger.error(f"the cross-server hub cannot listen on ws://{self.host}:{self.port}: {exc}")
        finally:
            self._server = None

    def stop(self, timeout: float = 5.0) -> None:
        """Stop listening, drop every node and join the thread."""
        self._stopping.set()
        server, self._server = self._server, None
        if server is not None:
            try:
                server.shutdown()                        # thread-safe, ends serve_forever()
            except Exception:
                self.logger.exception("failed to shut the hub down")
        with self._lock:
            connections = list(self._peers.values())
            self._peers.clear()
        self._abort_pending(None, "the hub is stopping")
        for connection in connections:
            self._close_quietly(connection, 1001, "the hub is going away")
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._server is not None

    @property
    def peers(self) -> list[str]:
        """Names of the nodes registered right now."""
        with self._lock:
            return sorted(self._peers)

    # ---------------------------------------------------------------- sending
    def send(
        self,
        target: str | None,
        action: str,
        message: str = "",
        data: dict | None = None,
        *,
        wait: bool = False,
        timeout: float = 5.0,
    ) -> dict | None:
        """Send to one node (``target`` = its name) or handle it locally (``None``).

        With ``wait=True`` this blocks until the peer's reply arrives and returns
        it as ``{"ok": bool, "message": str, "data": dict, "error": str | None}``.
        With ``wait=False`` it returns ``None`` right away (``None`` also means the
        frame could not be sent at all, e.g. the target is offline).
        """
        if target is None or target == self.name:
            msg = {
                "type": "message",
                "request_id": self._next_rid(),
                "source": self.name,
                "target": self.name,
                "action": action,
                "message": message,
                "data": data or {},
            }
            result = self._call_handler(msg)
            return result if wait else None

        msg = {
            "type": "message",
            "request_id": self._next_rid(),
            "source": self.name,
            "target": target,
            "action": action,
            "message": message,
            "data": data or {},
        }
        return self._send_and_maybe_wait(msg, wait, timeout)

    def deliver(self, target: str, action: str, message: str = "", data: dict | None = None) -> bool:
        """Send straight to a registered peer, even when its name equals the hub's own.

        :meth:`send` treats ``target == self.name`` as "the hub handles it", which is right for
        commands a local player typed but wrong for a *peer* that happens to share the hub's
        name (possible whenever two instances are given the same ``websocket.name``).
        """
        msg = {
            "type": "message",
            "request_id": self._next_rid(),
            "source": self.name,
            "target": target,
            "action": action,
            "message": message,
            "data": data or {},
        }
        with self._lock:
            connection = self._peers.get(target)
        return connection is not None and self._send(connection, msg)

    def broadcast(self, action: str, message: str = "", data: dict | None = None,
                  apps: str | Iterable[str] | None = None) -> int:
        """Fire and forget to every registered peer.  Returns how many got it.

        ``apps`` restricts the fan-out to some identities: cluster-wide commands go to the
        trusted instances (see :attr:`command_apps`), never to the bot.
        """
        msg = {
            "type": "event",
            "source": self.name,
            "action": action,
            "message": message,
            "data": data or {},
        }
        wanted = self._normalise_apps(apps)
        with self._lock:
            connections = [(name, conn) for name, conn in self._peers.items()
                           if wanted is None or self._peer_apps.get(name) in wanted]
        sent = 0
        for _, connection in connections:
            if self._send(connection, msg):
                sent += 1
        return sent

    @staticmethod
    def _normalise_apps(apps: str | Iterable[str] | None) -> set[str] | None:
        if apps is None:
            return None
        if isinstance(apps, str):
            return {apps}
        return set(apps)

    @property
    def command_apps(self) -> set[str]:
        """Identities that may take part in cluster-wide commands: everything trusted
        except the bot, which only answers ``bot_action``."""
        return self.accepted_apps - {APP_ID_BOT}

    @property
    def peer_apps(self) -> dict[str, str]:
        """The identity each online peer announced (name -> app)."""
        with self._lock:
            return dict(self._peer_apps)

    @property
    def peer_versions(self) -> dict[str, str]:
        """The plugin version each online peer announced at its handshake (name -> version).

        Empty string means "it did not say" -- an instance running a build from before the
        field existed. The cluster update round reads this to find out which nodes still have
        to be updated, and after an update it is the authoritative "the node came back on the
        new version" signal.
        """
        with self._lock:
            return {name: str(info.get("version") or "")
                    for name, info in self._peer_info.items()}

    def peer_supports(self, name: str, feature: str) -> bool:
        """True when that online peer announced ``feature`` in its hello frame.

        A peer that never announces it (older build, or a non-GamesAI service admitted through
        ``allow_app_id``) can only be *reported*, never ordered: it would answer the order with
        the automatic ``{"ok": true}`` that every unknown action gets.
        """
        with self._lock:
            info = self._peer_info.get(str(name)) or {}
        return feature in (info.get("features") or frozenset())

    def _is_bot_peer(self, name: str) -> bool:
        """True when that online peer registered with the bot identity (see :meth:`_on_frame`)."""
        with self._lock:
            return self._peer_apps.get(name) == APP_ID_BOT

    def peers_of(self, app: str) -> list[str]:
        """The online peers of one kind, e.g. only the Mineflayer bots."""
        with self._lock:
            return sorted(name for name, kind in self._peer_apps.items() if kind == app)

    def ping(self, target: str | None = None, timeout: float = 5.0) -> dict:
        """Round trip in seconds.  ``target=None`` measures every node at once.

        Returns ``{"alpha": 0.0031, "beta": -1.0}`` -- ``-1.0`` means no reply.
        """
        if target is not None:
            started = time.perf_counter()
            reply = self.send(target, "ping", wait=True, timeout=timeout)
            if not reply or not reply.get("ok"):
                return {target: -1.0}
            return {target: time.perf_counter() - started}
        return {name: self.ping(name, timeout)[name] for name in self.peers}

    # -------------------------------------------------------------- internals
    def _next_rid(self) -> str:
        with self._lock:
            self._rid += 1
            return f"{self.name}#{os.getpid():x}#{self._rid}"

    def _send_and_maybe_wait(self, msg: dict, wait: bool, timeout: float) -> dict | None:
        with self._lock:
            connection = self._peers.get(msg["target"])
        if connection is None:
            if not wait:
                return None
            return {
                "ok": False,
                "error": f"unknown target {msg['target']!r}",
                "data": {"peers": self.peers},
            }

        wake = None
        box: dict = {}
        if wait:
            wake = threading.Event()
            with self._lock:
                self._pending[msg["request_id"]] = (wake, box, str(msg["target"]))

        try:
            if not self._send(connection, msg):
                return {"ok": False, "error": "send failed"} if wait else None
            if not wait:
                return None
            if not wake.wait(timeout):
                return {"ok": False, "error": f"timeout after {timeout}s"}
            return box["reply"]
        finally:
            if wait:
                with self._lock:
                    self._pending.pop(msg["request_id"], None)

    def _call_handler(self, msg: dict) -> dict:
        if self.handler is None:
            return {"ok": False, "error": "the hub has no handler"}
        try:
            payload = self.handler(msg)
        except Exception as exc:
            self.logger.exception(f"the hub handler failed for action {msg.get('action')!r}")
            return {"ok": False, "error": f"handler failed: {exc}"}
        reply = {"ok": True, "message": "", "data": {}}
        if payload:
            reply.update(payload)
        return reply

    # ------------------------------------------------------------ connections
    def _handler(self, connection: ServerConnection) -> None:
        """Serve one node; websockets gives every connection its own thread."""
        peer = "?"
        try:
            hello = self._handshake(connection)
            if hello.name is None:
                return
            if hello.probe:
                # A probe only asks "are you a GamesAI hub?": answer it and let it go without
                # taking a name or showing up in the online list. Without a token it gets
                # no online list either; with one it also learns whose token it holds, which
                # is how `!!gamesai node claim` checks the name before writing anything.
                self._send(connection, self._hello_ack(
                    self.peers if hello.token_ok else [], hello.app,
                    expires_in=hello.expires_in, token_name=hello.token_name))
                self._close_quietly(connection, 1000, "probe answered")
                return

            peer = hello.name
            with self._lock:
                previous = self._peers.get(peer)
                self._peers[peer] = connection
                self._peer_apps[peer] = hello.app
                self._peer_info[peer] = {
                    "version": hello.version,
                    "features": frozenset(hello.features),
                }
            if previous is not None and previous is not connection:
                self.logger.warning(f"node {peer!r} reconnected, dropping the old connection")
                self._close_quietly(previous, CLOSE_REPLACED, "replaced by a newer connection")

            self.logger.info(f"{hello.app} peer {peer!r} registered ({len(self.peers)} online)")
            self._send(connection, self._hello_ack(
                [name for name in self.peers if name != peer], hello.app,
                expires_in=hello.expires_in, token=hello.issued_token))
            self._push_peers()
            if self.on_peer_registered is not None:
                try:
                    self.on_peer_registered(peer, hello.version, tuple(hello.features))
                except Exception:
                    self.logger.exception("the peer registration hook failed")

            for raw in connection:                       # blocking receive loop
                self._on_frame(peer, connection, raw)
        except ConnectionClosed:
            pass
        except Exception:
            self.logger.exception("a cross-server connection handler crashed")
        finally:
            with self._lock:
                registered = self._peers.get(peer) is connection
                if registered:
                    del self._peers[peer]
                    self._peer_apps.pop(peer, None)
                    self._peer_info.pop(peer, None)
            if registered:
                self.logger.info(f"node {peer!r} left ({len(self.peers)} online)")
                # Callers waiting on this peer must not sit on their timeout: wake them now.
                woken = self._abort_pending(peer, "the peer disconnected")
                if woken:
                    self.logger.info(f"woke {woken} waiting call(s) of node {peer!r}")
                self._push_peers()

    def _handshake(self, connection: ServerConnection) -> Handshake:
        """Read the hello frame and decide what this connection is (see the frame table in
        ``docs/<lang>/cross-server.md`` and the module docstring above).

        A rejected client is closed here with the close code that says why; the returned
        :class:`Handshake` then carries ``name = None``.
        """
        try:
            raw = connection.recv(timeout=HANDSHAKE_TIMEOUT)
        except (ConnectionClosed, TimeoutError):
            self.logger.warning("a client never sent its hello frame")
            return Handshake()
        try:
            hello = json.loads(raw)
        except (TypeError, ValueError):
            self._close_quietly(connection, CLOSE_BAD_HANDSHAKE, "hello must be JSON")
            return Handshake()
        if not isinstance(hello, dict) or hello.get("type") != "hello":
            self._close_quietly(connection, CLOSE_BAD_HANDSHAKE, "the first frame must be hello")
            return Handshake()
        app = str(hello.get("app") or "")
        # Informational hello fields: which build the peer runs and what it understands. They
        # are never validated -- an instance from before they existed simply sends nothing, and
        # that must keep working (see FEATURE_UPDATE_ORDER).
        version = str(hello.get("version") or "")
        raw_features = hello.get("features")
        features = (tuple(str(item) for item in raw_features if isinstance(item, str))
                    if isinstance(raw_features, list) else ())
        if app not in self.accepted_apps:
            # Something else speaks WebSocket on this port, or claims an identity we do not
            # know. Say so with a dedicated code so the other side can tell "not GamesAI"
            # apart from "wrong version".
            self.logger.warning(
                f"rejected {connection.remote_address}: unknown peer identity {app!r}"
            )
            self._close_quietly(connection, CLOSE_NOT_GAMES_AI, "unknown peer identity")
            return Handshake()
        if hello.get("protocol") != PROTOCOL_VERSION:
            self._close_quietly(connection, CLOSE_BAD_PROTOCOL, "protocol version mismatch")
            return Handshake()

        ip = remote_ip(connection)
        token = str(hello.get("token") or "")
        if hello.get("probe"):
            # A probe is still answered when it cannot authenticate -- the role decision
            # depends on it -- but it only learns the online list with a token we know, and
            # it never creates a pending entry or a token of its own.
            token_name = self.name_for_token(token) if token else None
            return Handshake("probe", probe=True, app=app, token_ok=token_name is not None,
                             expires_in=self.expires_in(token_name) if token_name else None,
                             token_name=token_name)

        name = str(hello.get("server") or "").strip()
        if not name:
            self._close_quietly(connection, CLOSE_NO_NAME, "hello must carry a server name")
            return Handshake(app=app)

        if not token:
            if app == APP_ID_BOT and self._bot_auto_issue_allowed(ip):
                # The bot is a helper process on a machine we already trust; provision it
                # without a human step and hand it the token in the ack. This replaces an
                # existing entry on purpose (the bot came back without its token, e.g. after
                # its config was recreated), so it says so when there was one.
                replaced = self.is_enrolled(name)
                issued = self.issue(name, app=app, issued_by="auto-enrolment", ip=ip, replace=True)
                self.logger.info(
                    f"provisioned the Mineflayer bot {name!r} automatically (request from "
                    f"{ip or '?'}, the hub's own machine or an enrolled node's)"
                )
                if replaced:
                    self.logger.warning(
                        f"the bot {name!r} was already enrolled: its previous token is now "
                        f"invalid (the bot was provisioned again without one)"
                    )
                if issued and self.on_bot_token is not None:
                    try:
                        self.on_bot_token(name, issued)
                    except Exception:
                        self.logger.exception("the bot token hook failed")
                return Handshake(name, app=app, token_ok=True,
                                 expires_in=self.expires_in(name), issued_token=issued,
                                 version=version, features=features)
            if hello.get("enroll"):
                entry = self.enrol(name, app=app, ip=ip)
                refused = str(entry.get("refused") or "")
                if refused == "full":
                    message = ("the hub's waiting list is full, so this request was not "
                               "recorded; an operator has to clear it with !!gamesai node "
                               "pending / node revoke before a token can be issued")
                elif refused == "rate":
                    message = ("too many new enrolment requests came from this address, so this "
                               "one was not recorded; wait a minute and try again")
                else:
                    message = ("the hub recorded this enrolment request; an operator must "
                               "issue a token with !!gamesai node token " + name)
                self._send(connection, {
                    "type": "enroll_pending",
                    "protocol": PROTOCOL_VERSION,
                    "hub": self.name,
                    "name": name,
                    "requests": entry["requests"],
                    "refused": refused or None,
                    "message": message,
                })
                self._close_quietly(connection, CLOSE_ENROLMENT_REQUIRED,
                                    "enrolment request recorded" if not refused
                                    else f"enrolment request refused ({refused})")
                return Handshake(app=app)
            # No token and no request to enrol: there is nothing to verify against.
            self.logger.warning(
                f"refused node {name!r} from {ip or '?'}: no token and no enrolment request"
            )
            self._close_quietly(connection, CLOSE_ENROLMENT_REQUIRED, "enrolment required")
            return Handshake(app=app)

        verdict = self.verify(name, app, token)
        if verdict == "expired":
            self.logger.warning(f"refused node {name!r}: its enrolment token has expired")
            self._close_quietly(connection, CLOSE_TOKEN_EXPIRED, "enrolment token expired")
            return Handshake(app=app)
        if verdict != "ok":
            self.logger.warning(f"rejected node {name!r} from {ip or '?'} with an unknown token")
            self._close_quietly(connection, CLOSE_BAD_TOKEN, "unknown or revoked token")
            return Handshake(app=app)

        self.record_seen(name, ip, version=version, features=features)
        self._warn_expiring()
        return Handshake(name, app=app, token_ok=True, expires_in=self.expires_in(name),
                         version=version, features=features)

    def _bot_auto_issue_allowed(self, ip: str) -> bool:
        """May a token-less Mineflayer bot be provisioned from this address right now?

        Yes only over the loopback interface (the bot runs on the hub's own machine) or from
        the address of an already enrolled node (the bot runs on a client's machine, next to
        that node). Anywhere else the request is treated like any other unenrolled one, so a
        stranger who can reach the port cannot have a token minted for a name.
        """
        if not ip:
            return False
        try:
            if ipaddress.ip_address(ip).is_loopback:
                return True
        except ValueError:
            if ip == "localhost":
                return True
        with self._nodes_lock:
            return ip in {str(entry.get("last_ip") or "") for entry in self._nodes.values()}

    def _hello_ack(self, peers: list[str], you: str = APP_ID, *, expires_in: int | None = None,
                   token: str | None = None, token_name: str | None = None) -> dict:
        ack = {
            "type": "hello_ack",
            # The hub always identifies itself as GamesAI; `you` tells the peer which
            # identity this hub accepted it as.
            "app": APP_ID,
            "you": you,
            "protocol": PROTOCOL_VERSION,
            "hub": self.name,
            "request_id": f"{self.name}#hello",
            "peers": peers,
        }
        if expires_in is not None:
            # Omitted when the token never expires, so the node can tell "unlimited" from
            # "the hub did not say".
            ack["expires_in"] = int(expires_in)
        if token:
            # Only ever sent to the bot the hub just provisioned by itself; no other reply
            # carries a usable secret.
            ack["token"] = token
        if token_name:
            ack["token_name"] = token_name
        return ack

    def _push_peers(self) -> None:
        """Tell every node who is online, so the list never goes stale."""
        with self._lock:
            names = sorted(self._peers)
            connections = list(self._peers.items())
        for name, connection in connections:
            self._send(connection, {
                "type": "event",
                "source": self.name,
                "action": "peers",
                "message": "",
                "data": {"peers": [peer for peer in names if peer != name]},
            })

    def _on_frame(self, sender: str, connection: ServerConnection, raw: object) -> None:
        try:
            msg = json.loads(raw)
        except (TypeError, ValueError):
            self.logger.warning(f"dropping a non-JSON frame from {sender!r}")
            return
        if not isinstance(msg, dict):
            return

        msg["source"] = sender                           # authoritative, blocks spoofing
        frame_type = msg.get("type")
        target = msg.get("target")

        if frame_type == "reply":
            if target in (None, "", self.name):
                self._resolve_pending(msg)
            elif not self._deliver(target, msg):
                self.logger.debug(f"a reply for {target!r} could not be delivered")
            return

        if frame_type == "message" and msg.get("action") == "ping":
            self._answer(connection, msg, {"message": "pong"})   # answered here, never routed
            return

        if self._refuse_bot_frame(connection, sender, msg, frame_type):
            return

        if frame_type == "event":
            if target == "*" or not target:
                self._fanout(msg, exclude=sender)
                self._call_handler(msg)                  # let the hub observe it too
            else:
                self._deliver(target, msg)
            return

        if frame_type != "message":
            self.logger.warning(f"unknown frame type {frame_type!r} from {sender!r}")
            return

        if target in (None, "", self.name):
            self._answer(connection, msg, self._call_handler(msg))
        elif target == "*":
            self._fanout(msg, exclude=sender)
            self._answer(connection, msg, {"message": "broadcast", "data": {"peers": self.peers}})
        elif not self._deliver(target, msg):
            self._answer(connection, msg, {
                "ok": False,
                "error": f"unknown target {target!r}",
                "data": {"peers": self.peers},
            })

    def _refuse_bot_frame(self, connection: ServerConnection, sender: str, msg: dict,
                          frame_type: object) -> bool:
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
        if frame_type not in ("message", "event") or not self._is_bot_peer(sender):
            return False
        self.logger.warning(
            f"refused a {frame_type} frame from bot peer {sender!r} "
            f"(action {msg.get('action')!r})"
        )
        if frame_type == "message":
            self._answer(connection, msg, {
                "ok": False,
                "error": "the bot identity may only answer bot_action",
            })
        return True

    def _fanout(self, msg: dict, *, exclude: str | None = None,
                apps: str | Iterable[str] | None = None) -> int:
        wanted = self._normalise_apps(apps)
        with self._lock:
            connections = [(name, conn) for name, conn in self._peers.items()
                           if wanted is None or self._peer_apps.get(name) in wanted]
        sent = 0
        for name, connection in connections:
            if name == exclude:
                continue
            if self._send(connection, msg):
                sent += 1
        return sent

    def _deliver(self, name: str, msg: dict) -> bool:
        with self._lock:
            connection = self._peers.get(name)
        return connection is not None and self._send(connection, msg)

    def _resolve_pending(self, msg: dict) -> None:
        request_id = msg.get("request_id")
        with self._lock:
            entry = self._pending.get(request_id)
        if entry is None:
            self.logger.debug(f"a late reply for {request_id!r} arrived, nobody is waiting")
            return
        wake, box, _target = entry
        box["reply"] = msg
        wake.set()

    def _abort_pending(self, target: str | None, reason: str) -> int:
        """Wake every caller waiting for ``target`` (or for anyone, when it is None).

        Without this a caller only learns about a dropped connection when its own timeout runs
        out -- the AI round of a routed tool call would sit there for the full 120 seconds. The
        answer says ``unknown`` on purpose: the peer may have run the call before it dropped, so
        the honest outcome is "we do not know", not "it failed".
        """
        with self._lock:
            doomed = [(rid, entry) for rid, entry in self._pending.items()
                      if target is None or entry[2] == target]
            for rid, _entry in doomed:
                self._pending.pop(rid, None)
        for _rid, (wake, box, name) in doomed:
            box["reply"] = {
                "ok": False,
                "unknown": True,
                "error": f"the link to {name!r} dropped before it answered ({reason})",
            }
            wake.set()
        return len(doomed)

    def _answer(self, connection: ServerConnection, request: dict, payload: dict | None) -> None:
        reply = {
            "type": "reply",
            "request_id": request.get("request_id"),
            "source": self.name,
            "target": request.get("source"),
            "ok": True,
            "message": "",
            "data": {},
            "error": None,
        }
        if payload:
            reply.update(payload)
        self._send(connection, reply)

    def _oversized(self, msg: dict) -> int | None:
        """The frame's size in bytes when it is too large to send, else None.

        The receiving side closes the connection with 1009 for anything over
        :data:`MAX_MESSAGE_SIZE`, so an oversized reply must never be handed to websockets: it
        would take the whole link down (and every other conversation with it).
        """
        try:
            size = len(_dumps(msg).encode("utf-8"))
        except Exception:
            return None
        return size if size > MAX_MESSAGE_SIZE - FRAME_MARGIN else None

    def _send(self, connection: ServerConnection, msg: dict) -> bool:
        size = self._oversized(msg)
        if size is not None:
            msg = self._shrink_oversized(msg, size)
            if msg is None:
                return False
        try:
            connection.send(_dumps(msg))                 # takes the protocol lock: any thread is fine
            return True
        except ConnectionClosed:
            return False
        except Exception:
            self.logger.exception("failed to send a frame")
            return False

    def _shrink_oversized(self, msg: dict, size: int) -> dict | None:
        """Replace a frame that cannot be sent with a small, honest one (or None to drop it).

        A ``reply`` keeps the request_id, so whoever waits for it fails immediately with a real
        reason instead of a 120 second timeout. A streamed ``command_reply`` becomes one short
        line. Anything else is dropped with a warning.
        """
        action = str(msg.get("action") or "")
        self.logger.warning(
            f"a {msg.get('type')!r} frame for {msg.get('target')!r} (action {action!r}) is "
            f"{size} bytes, over the {MAX_MESSAGE_SIZE} byte limit"
        )
        if msg.get("type") == "reply":
            return {
                "type": "reply",
                "request_id": msg.get("request_id"),
                "source": msg.get("source"),
                "target": msg.get("target"),
                "ok": False,
                "message": "",
                "data": {},
                "error": f"the reply was too large to send ({size} bytes)",
            }
        if action == "command_reply":
            data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
            return {
                "type": msg.get("type") or "message",
                "request_id": msg.get("request_id"),
                "source": msg.get("source"),
                "target": msg.get("target"),
                "action": "command_reply",
                "message": "",
                "data": {
                    "session": data.get("session"),
                    "text": (f"[GamesAI] this output was too large to stream "
                             f"({size} bytes); see the log on the instance that produced it"),
                },
            }
        return None

    def _close_quietly(self, connection: ServerConnection, code: int, reason: str) -> None:
        try:
            connection.close(code, reason)
        except Exception:
            pass
