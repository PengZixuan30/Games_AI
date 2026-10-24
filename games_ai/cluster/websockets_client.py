"""Cross-server node -- the WebSocket client half of the cross-server link.

Every MCDR instance that wants to talk across servers runs one node and points
it at the hub's URI (``ws://host:port``).  The hub itself and the full wire
protocol live in websockets_server.py; this module speaks exactly the same
frames from the other side.

The node owns one daemon thread that

1. connects, sends ``hello`` and waits for ``hello_ack`` (which carries the list
   of the other servers that are online),
2. then loops over incoming frames, answering every ``message`` with exactly one
   ``reply`` and handing ``event`` / ``message`` frames to ``handler``,
3. reconnects with exponential backoff whenever the link drops.

Frames the node sends:

    {"type": "hello",   "protocol": 1, "server": "alpha", "token": "...",
     "version": "0.7.3", "features": ["update_order"]}
    {"type": "hello",   "protocol": 1, "server": "alpha", "enroll": true,
     "version": "0.7.3"}                       -- no token yet: please record me
    {"type": "message", "request_id": "alpha#7", "source": "alpha",
     "target": "beta" | "*" | None, "action": "chat", "message": "hi",
     "data": {}", "ok": ...}
    {"type": "reply",   ...}   -- the answer to a routed message
    {"type": "event",   ...}   -- fire and forget, never answered

``target=None`` means "the hub handles it", a peer name routes it to that peer
and ``"*"`` broadcasts it to every peer except us.

Fatal close codes -- keep in sync with websockets_server.py:

    4001 the hub does not know our token (revoked, or issued for another name),
    4002 we sent no server name, 4003 another instance took our name over,
    4004 protocol version mismatch, 4005 the address is not a GamesAI instance,
    4007 this instance is not enrolled (the hub recorded the request, or refused it),
    4008 our enrolment token expired.

4007 and 4008 are not retryable either: the node cannot succeed until a token is claimed,
so it stops and logs what to do instead of reconnecting in a loop. Every other failure
(hub down, network gone, hub restarted) is retried with backoff.

Threading: :meth:`send` may be called from any MCDR thread -- the underlying
``Connection.send()`` takes the protocol lock internally.
"""

import hashlib
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterable

from websockets.exceptions import (
    ConnectionClosed,
    InvalidHandshake,
    InvalidMessage,
    InvalidStatus,
    InvalidURI,
)
from websockets.sync.client import ClientConnection, connect

# What this client announces; the hub adapts to it (see websockets_server.py).
APP_ID = "games_ai_mcdr"            # a GamesAI-MCDR instance
APP_ID_BOT = "mineflayer_bot"       # a Mineflayer bot
ACCEPTED_PEER_APPS = (APP_ID, APP_ID_BOT)

PROTOCOL_VERSION = 1

# What this build understands, announced in the hello frame so a hub can tell whether it may
# hand this instance an update order. Purely additive: an older hub ignores the field, and an
# older node does not send it -- which is exactly how the hub recognizes "cannot be ordered".
FEATURES = ("update_order",)

CLOSE_BAD_HANDSHAKE = 4000
CLOSE_BAD_TOKEN = 4001
CLOSE_NO_NAME = 4002
CLOSE_REPLACED = 4003
CLOSE_BAD_PROTOCOL = 4004
CLOSE_NOT_GAMES_AI = 4005

CLOSE_ENROLMENT_REQUIRED = 4007
CLOSE_TOKEN_EXPIRED = 4008

# The one line the operator needs, used both for a close code and for an `enroll_pending`
# answer (the hub sends that frame, then closes with 4007).
ENROLMENT_REQUIRED_HINT = ("this instance is not enrolled: ask the hub for a token, "
                           "then run !!gamesai node claim <token>")
TOKEN_EXPIRED_HINT = ("the enrolment token expired: ask the hub for a new one "
                      "(!!gamesai node rotate <name>), then run !!gamesai node claim <token>")

FATAL_CLOSE_CODES = {
    CLOSE_BAD_TOKEN: "the hub rejected our token (revoked, or issued for another name)",
    CLOSE_NO_NAME: "we did not send a server name",
    CLOSE_REPLACED: "another instance registered the same server name",
    CLOSE_BAD_PROTOCOL: "protocol version mismatch (hub and node versions differ)",
    CLOSE_NOT_GAMES_AI: "the address is not a GamesAI instance",
    CLOSE_ENROLMENT_REQUIRED: ENROLMENT_REQUIRED_HINT,
    CLOSE_TOKEN_EXPIRED: TOKEN_EXPIRED_HINT,
}

# What a probe of the configured uri found there.
PROBE_GAMES_AI = "games_ai"       # a GamesAI hub answered our hello
PROBE_FOREIGN = "foreign"         # something is listening, but it is not a GamesAI hub
PROBE_UNREACHABLE = "unreachable" # nothing answered at all

RECONNECT_DELAYS = (0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 30.0, 60.0)

MAX_MESSAGE_SIZE = 1 << 20
# A frame has to fit the receiver's limit; the margin covers the JSON envelope.
FRAME_MARGIN = 1024
HANDSHAKE_TIMEOUT = 10.0

# handler(msg) -> None (nothing to say) or a dict merged into the reply:
#   {"message": str, "data": dict, "ok": bool, "error": str}
# msg carries {"type", "source", "action", "message", "data", "request_id"}.
MessageHandler = Callable[[dict], dict | None]


def token_fingerprint(token: str) -> str:
    """The public short name of a token (sha256[:6]); the token itself is never logged."""
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()[:6]


def _dumps(obj: dict) -> str:
    # ensure_ascii=False keeps Chinese readable in the frame and on the wire.
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _hello_frame(name: str, token: str, version: str, *, probe: bool = False,
                 app: str = APP_ID, enroll: bool = False) -> dict:
    frame = {
        "type": "hello",
        "app": app,
        "protocol": PROTOCOL_VERSION,
        "server": name,
        "version": version,
        "features": list(FEATURES),
    }
    if enroll:
        # "I have no token; please record an enrolment request for this name." Sent with no
        # token at all, so the hub cannot mistake an empty secret for a real one.
        frame["enroll"] = True
    else:
        frame["token"] = token
    if probe:
        # A probe must not take a name over or show up in the online list: the hub answers
        # it and closes instead of registering it.
        frame["probe"] = True
    return frame


def probe_hub_detail(uri: str, timeout: float = 3.0, logger: logging.Logger | None = None,
                     token: str = "", name: str = "probe") -> tuple[str, dict]:
    """Ask whatever listens at ``uri`` whether it is a GamesAI hub, and what it thinks of a token.

    Returns ``(result, info)`` where ``result`` is one of :data:`PROBE_GAMES_AI`,
    :data:`PROBE_FOREIGN` or :data:`PROBE_UNREACHABLE`, and ``info`` carries what the ack
    said: ``{"hub": str, "peers": [str], "token_name": str | None, "expires_in": int | None}``.
    A probe never registers, never enrols and never creates a pending entry. With a token the
    hub knows, ``token_name`` says which node it was issued for -- that is what
    ``!!gamesai node claim`` checks before it writes anything.
    """
    probe_log = logger or logging.getLogger(__name__)
    empty: dict = {"hub": "", "peers": [], "token_name": None, "expires_in": None}
    try:
        connection = connect(
            uri,
            open_timeout=timeout,
            close_timeout=2,
            ping_interval=None,
            max_size=MAX_MESSAGE_SIZE,
            logger=probe_log,
        )
    except (OSError, TimeoutError):
        return PROBE_UNREACHABLE, empty
    except (InvalidHandshake, InvalidStatus, InvalidURI, ValueError) as exc:
        # Something is listening but it did not complete a WebSocket handshake.
        return PROBE_FOREIGN, {**empty, "hub": str(exc)}

    try:
        with connection:
            connection.send(_dumps(_hello_frame(name, token, "", probe=True)))
            try:
                raw = connection.recv(timeout=timeout)
            except (ConnectionClosed, TimeoutError) as exc:
                # The handshake worked, so the port is taken -- just not by a GamesAI hub
                # that accepts our protocol version.
                return PROBE_FOREIGN, {**empty, "hub": str(exc)}
    except (OSError, TimeoutError):
        return PROBE_UNREACHABLE, empty
    except (ConnectionClosed, InvalidHandshake, InvalidMessage) as exc:
        return PROBE_FOREIGN, {**empty, "hub": str(exc)}

    try:
        ack = json.loads(raw)
    except (TypeError, ValueError):
        return PROBE_FOREIGN, {**empty, "hub": "the answer is not JSON"}
    if (
        isinstance(ack, dict)
        and ack.get("type") == "hello_ack"
        and ack.get("app") == APP_ID
        and ack.get("protocol") == PROTOCOL_VERSION
    ):
        expires_in = ack.get("expires_in")
        info = {
            "hub": str(ack.get("hub", "")),
            "peers": [str(peer) for peer in ack.get("peers", [])],
            "token_name": str(ack["token_name"]) if ack.get("token_name") else None,
            "expires_in": int(expires_in) if isinstance(expires_in, (int, float)) else None,
        }
        return PROBE_GAMES_AI, info
    return PROBE_FOREIGN, empty


def probe_hub(uri: str, timeout: float = 3.0, logger: logging.Logger | None = None,
              token: str = "") -> tuple[str, list[str], str]:
    """Ask whatever listens at ``uri`` whether it is a GamesAI hub.

    Returns ``(result, peers, hub_name)``, with ``result`` one of :data:`PROBE_GAMES_AI`,
    :data:`PROBE_FOREIGN` or :data:`PROBE_UNREACHABLE`. Used on load to decide between
    dialling that hub as a client and starting our own. A probe needs no token, so an
    unenrolled instance still sees the hub -- it just gets an empty peer list.
    """
    result, info = probe_hub_detail(uri, timeout=timeout, logger=logger, token=token)
    return result, list(info["peers"]), str(info["hub"])


class CrossServerNode:
    """Client half of the cross-server link.  One per MCDR instance."""

    def __init__(
        self,
        uri: str,
        server_name: str,
        token: str = "",
        *,
        app: str = APP_ID,
        version: str = "",
        handler: MessageHandler | None = None,
        logger: logging.Logger | None = None,
        reconnect: bool = True,
        reconnect_delays: Iterable[float] = RECONNECT_DELAYS,
        ping_interval: float = 20,
        ping_timeout: float = 20,
        max_message_size: int = MAX_MESSAGE_SIZE,
        auto_enroll: bool = True,
    ):
        self.uri = uri
        self.name = server_name
        self.token = token or ""
        self.app = app
        self.version = version
        self.handler = handler
        self.logger = logger or logging.getLogger(__name__)
        self.reconnect = reconnect
        # With no token and auto_enroll on, the first handshake asks the hub to record an
        # enrolment request instead of guessing. One attempt only: 4007 is fatal.
        self.auto_enroll = auto_enroll

        self._reconnect_delays = tuple(reconnect_delays)
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout
        self._max_message_size = max_message_size

        self._conn: ClientConnection | None = None
        self._thread: threading.Thread | None = None
        self._first_attempt = threading.Event()
        self._first_result: bool | None = None
        self._connected = threading.Event()
        self._stopping = threading.Event()

        self._lock = threading.RLock()
        self._peers: list[str] = []
        self._rid = 0
        self._pending: dict[str, tuple[threading.Event, dict]] = {}
        self._fatal: str | None = None
        # What the hub said about this node's token, for `!!gamesai node status`.
        self.hub_name = ""
        self.expires_in: int | None = None
        self.enrol_requested = False
        self.issued_token: str | None = None

    # ------------------------------------------------------------- lifecycle
    def start(self, timeout: float = 10.0) -> bool:
        """Start the link thread.  Returns True when the handshake succeeded."""
        if self._thread is not None:
            raise RuntimeError("the node is already started")
        self._thread = threading.Thread(target=self._run, name="games_ai@ws_node", daemon=True)
        self._thread.start()
        self._first_attempt.wait(timeout)
        return bool(self._first_result)

    def stop(self, timeout: float = 5.0) -> None:
        """Close the link and join the thread."""
        self._stopping.set()
        connection, self._conn = self._conn, None
        self._abort_pending("the node is stopping")
        self._close_quietly(connection, 1000, "the node is going away")
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def peers(self) -> list[str]:
        """The other servers, as the hub last reported them."""
        with self._lock:
            return list(self._peers)

    @property
    def fatal_error(self) -> str | None:
        """Why the node gave up, if it did."""
        return self._fatal

    # --------------------------------------------------------------- threads
    def _run(self) -> None:
        attempt = 0
        while not self._stopping.is_set():
            try:
                with connect(
                    self.uri,
                    ping_interval=self._ping_interval,
                    ping_timeout=self._ping_timeout,
                    max_size=self._max_message_size,
                    open_timeout=HANDSHAKE_TIMEOUT,
                    logger=self.logger,
                ) as connection:
                    try:
                        ok = self._handshake(connection)
                        if not ok and self._fatal is None:
                            # The hub refused the handshake: read until it closes so the close
                            # code (4001 / 4007 / 4008 ...) becomes the reported reason.
                            self._drain_until_closed(connection)
                        self._first_result = ok
                        self._first_attempt.set()
                        if ok:
                            attempt = 0
                            self._session(connection)        # blocks until the link drops
                    except ConnectionClosed as exc:
                        self.logger.info(f"the link to {self.uri} closed: {exc}")
                        self._note_close(connection, exc)
            except ConnectionClosed as exc:
                self.logger.info(f"the connection to {self.uri} closed: {exc}")
            except OSError as exc:                           # hub down, refused, DNS, no route
                self.logger.info(f"cannot reach {self.uri}: {exc}")
            except Exception:
                self.logger.exception("the cross-server link crashed")
            finally:
                if self._first_result is None:
                    self._first_result = False
                self._first_attempt.set()
                self._connected.clear()
                with self._lock:
                    self._conn = None
                    self._peers = []
                # Nobody can answer us any more: wake the callers that wait for the hub instead
                # of leaving them on their own timeout.
                self._abort_pending("the link to the hub dropped")

            if self._stopping.is_set():
                break
            if self._fatal is not None:
                self.logger.error(f"cross-server link disabled: {self._fatal}")
                break
            if not self.reconnect:
                break

            delay = self._reconnect_delays[min(attempt, len(self._reconnect_delays) - 1)]
            attempt += 1
            self.logger.info(f"reconnecting to {self.uri} in {delay:.1f}s")
            if self._stopping.wait(delay):                   # an interruptible sleep
                break

    def _drain_until_closed(self, connection: ClientConnection) -> None:
        """Read frames until the hub closes, so a fatal close code is never missed.

        The hub may answer a refused handshake with an error frame first (``enroll_pending``)
        and then close; nothing else can arrive on a connection that never registered.
        """
        try:
            while True:
                connection.recv(timeout=HANDSHAKE_TIMEOUT)
        except ConnectionClosed as exc:
            self._note_close(connection, exc)
        except (TimeoutError, OSError):
            pass
        except Exception:
            pass

    def _handshake(self, connection: ClientConnection) -> bool:
        connection.send(_dumps(_hello_frame(
            self.name, self.token, self.version, app=self.app,
            enroll=not self.token and self.auto_enroll)))
        try:
            raw = connection.recv(timeout=HANDSHAKE_TIMEOUT)
        except (ConnectionClosed, TimeoutError) as exc:
            self._note_close(connection, exc if isinstance(exc, ConnectionClosed) else None)
            return False
        try:
            ack = json.loads(raw)
        except (TypeError, ValueError):
            self._fatal = "the hub sent a non-JSON hello_ack"
            return False
        if isinstance(ack, dict) and ack.get("type") == "enroll_pending":
            # The hub recorded the request; an operator has to issue a token now. Retrying
            # cannot help, so this is fatal and says exactly what to do.
            self.enrol_requested = True
            self._fatal = ENROLMENT_REQUIRED_HINT
            self.logger.warning(
                f"the hub found this instance but it is not enrolled; {ENROLMENT_REQUIRED_HINT}"
            )
            return False
        if not isinstance(ack, dict) or ack.get("type") != "hello_ack":
            self._fatal = f"unexpected first frame from the hub: {ack!r}"
            return False
        if ack.get("app") != APP_ID:
            # The address answers the GameAI wire protocol but says it is something else:
            # refuse to talk to it rather than hand it our commands.
            self._fatal = "the address is not a GamesAI instance"
            return False
        if ack.get("protocol") != PROTOCOL_VERSION:
            self._fatal = f"protocol version mismatch (the hub speaks {ack.get('protocol')!r})"
            return False

        self.hub_name = str(ack.get("hub") or "")
        expires_in = ack.get("expires_in")
        self.expires_in = int(expires_in) if isinstance(expires_in, (int, float)) else None
        issued = ack.get("token")
        if issued:
            # Only the Mineflayer bot is provisioned this way; an MCDR instance always claims
            # its token out of band and writes it into its identity file.
            self.issued_token = str(issued)
            self.logger.info(
                f"the hub issued this node a token "
                f"(fingerprint {token_fingerprint(self.issued_token)})"
            )
        with self._lock:
            self._conn = connection
            self._peers = [str(peer) for peer in ack.get("peers", [])]
        self._connected.set()
        self.logger.info(
            f"connected to the hub {self.hub_name!r} as {self.name!r}, "
            f"peers: {', '.join(self.peers) if self.peers else '(none)'}"
        )
        return True

    def _session(self, connection: ClientConnection) -> None:
        try:
            for raw in connection:
                self._on_frame(connection, raw)
        finally:
            self._connected.clear()

    def _note_close(self, connection: ClientConnection, exc: Exception | None = None) -> None:
        """Remember a fatal close code so the retry loop can give up."""
        code = getattr(getattr(exc, "rcvd", None), "code", None)
        if code is None:
            code = getattr(connection, "close_code", None)
        if code in FATAL_CLOSE_CODES:
            self._fatal = FATAL_CLOSE_CODES[code]

    # ------------------------------------------------------------- receiving
    def _on_frame(self, connection: ClientConnection, raw: object) -> None:
        try:
            msg = json.loads(raw)
        except (TypeError, ValueError):
            self.logger.warning("dropping a non-JSON frame from the hub")
            return
        if not isinstance(msg, dict):
            return

        frame_type = msg.get("type")
        if frame_type == "reply":
            self._resolve_pending(msg)
            return
        if frame_type == "event":
            if msg.get("action") == "peers":                 # the hub pushed the online list
                with self._lock:
                    self._peers = [str(peer) for peer in msg.get("data", {}).get("peers", [])]
                return
            self._call_handler(msg)
            return
        if frame_type != "message":
            self.logger.warning(f"unknown frame type {frame_type!r} from the hub")
            return
        if msg.get("action") == "ping":                      # answered here, never routed on
            self._answer(connection, msg, {"message": "pong"})
            return
        self._answer(connection, msg, self._call_handler(msg))

    def _call_handler(self, msg: dict) -> dict:
        if self.handler is None:
            return {"ok": False, "error": "the node has no handler"}
        try:
            payload = self.handler(msg)
        except Exception as exc:
            self.logger.exception(f"the node handler failed for action {msg.get('action')!r}")
            return {"ok": False, "error": f"handler failed: {exc}"}
        reply = {"ok": True, "message": "", "data": {}}
        if payload:
            reply.update(payload)
        return reply

    # --------------------------------------------------------------- sending
    def send(
        self,
        target: str | None,
        action: str,
        message: str = "",
        data: dict | None = None,
        *,
        wait: bool = False,
        timeout: float = 5.0,
        event: bool = False,
    ) -> dict | None:
        """Talk to the hub itself (``target=None``), to one peer, or to ``"*"``.

        ``event=True`` sends a fire and forget frame.  Otherwise every ``message``
        is answered with one ``reply``, which ``wait=True`` blocks for and returns
        as ``{"ok": bool, "message": str, "data": dict, "error": str | None}``.
        ``None`` comes back when the frame could not be sent at all.
        """
        connection = self._conn
        if connection is None:
            return {"ok": False, "error": "not connected"} if wait else None

        msg = {
            "type": "event" if event else "message",
            "request_id": self._next_rid(),
            "source": self.name,
            "target": target,
            "action": action,
            "message": message,
            "data": data or {},
        }

        wake = None
        box: dict = {}
        if wait and not event:
            wake = threading.Event()
            with self._lock:
                self._pending[msg["request_id"]] = (wake, box)
        try:
            if not self._send_json(connection, msg):
                return {"ok": False, "error": "the frame could not be sent"} if wait else None
        except ConnectionClosed:
            return {"ok": False, "error": "the connection is closed"} if wait else None

        if not wait or event:
            return None
        try:
            if not wake.wait(timeout):
                return {"ok": False, "error": f"timeout after {timeout}s"}
            return box["reply"]
        finally:
            with self._lock:
                self._pending.pop(msg["request_id"], None)

    def _send_json(self, connection: ClientConnection, msg: dict) -> bool:
        """Send one frame, never one that is over the limit the other side enforces.

        websockets closes the connection with 1009 for anything larger than
        :data:`MAX_MESSAGE_SIZE`, so an oversized frame is shrunk to a small honest one
        first (``_shrink_oversized``) rather than taking the link down with it.
        """
        size = self._oversized(msg)
        if size is not None:
            msg = self._shrink_oversized(msg, size)
            if msg is None:
                return False
        try:
            connection.send(_dumps(msg))                 # takes the protocol lock: any thread
            return True
        except ConnectionClosed:
            return False
        except Exception:
            self.logger.exception("failed to send a frame")
            return False

    @staticmethod
    def _oversized(msg: dict) -> int | None:
        """The frame's size in bytes when it is too large to send, else None."""
        try:
            size = len(_dumps(msg).encode("utf-8"))
        except Exception:
            return None
        return size if size > MAX_MESSAGE_SIZE - FRAME_MARGIN else None

    def _shrink_oversized(self, msg: dict, size: int) -> dict | None:
        """Replace a frame that cannot be sent with a small, honest one (or None to drop it)."""
        action = str(msg.get("action") or "")
        self.logger.warning(
            f"a {msg.get('type')!r} frame (action {action!r}) is {size} bytes, over the "
            f"{MAX_MESSAGE_SIZE} byte limit"
        )
        if msg.get("type") == "reply":
            # The hub is waiting for this one: answer with the reason instead of letting it run
            # into its timeout.
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

    def ping(self, target: str | None = None, timeout: float = 5.0) -> float:
        """Application level round trip in seconds, or -1.0 when it failed."""
        started = time.perf_counter()
        reply = self.send(target, "ping", wait=True, timeout=timeout)
        if reply is None or not reply.get("ok"):
            return -1.0
        return time.perf_counter() - started

    # ------------------------------------------------------------- internals
    def _next_rid(self) -> str:
        with self._lock:
            self._rid += 1
            return f"{self.name}#{os.getpid():x}#{self._rid}"

    def _abort_pending(self, reason: str) -> int:
        """Wake every caller waiting for a reply that can no longer arrive.

        The answer says ``unknown`` on purpose: the hub may have run the call before the link
        dropped, so the honest outcome is "we do not know", not "it failed".
        """
        with self._lock:
            doomed = list(self._pending.items())
            self._pending.clear()
        for _rid, (wake, box) in doomed:
            box["reply"] = {"ok": False, "unknown": True, "error": reason}
            wake.set()
        if doomed:
            self.logger.info(f"woke {len(doomed)} call(s) waiting for the hub ({reason})")
        return len(doomed)

    def _resolve_pending(self, msg: dict) -> None:
        request_id = msg.get("request_id")
        with self._lock:
            entry = self._pending.get(request_id)
        if entry is None:
            self.logger.debug(f"a late reply for {request_id!r} arrived, nobody is waiting")
            return
        wake, box = entry
        box["reply"] = msg
        wake.set()

    def _answer(self, connection: ClientConnection, request: dict, payload: dict | None) -> None:
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
        self._send_json(connection, reply)

    def _close_quietly(self, connection: ClientConnection | None, code: int, reason: str) -> None:
        if connection is None:
            return
        try:
            connection.close(code, reason)
        except Exception:
            pass
