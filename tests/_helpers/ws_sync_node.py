"""Cross-server node (WebSocket client side), threading flavour.

Every MCDR instance that wants to talk across servers runs one node and points
it at the hub's URI (``ws://host:port``).  The node owns a daemon thread that

    1. connects, sends ``hello``, waits for ``hello_ack`` (with the peer list),
    2. then loops over incoming frames, answering every ``message`` with one
       ``reply`` and feeding ``event``/``message`` to the plugin handler,
    3. reconnects with exponential backoff whenever the link drops.

Threading contract: :meth:`send` may be called from any MCDR thread -- the
underlying ``Connection.send`` takes the protocol lock internally.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Optional

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

PROTOCOL_VERSION = 1

RECONNECT_DELAYS = (0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 30.0, 60.0)

# Fatal close codes: retrying cannot help, so the node stops and says why.
FATAL_CLOSE_CODES = {
    4001: "the hub rejected our token",
    4002: "we did not send a server name",
    4003: "another instance registered the same server name",
    4004: "protocol version mismatch (hub and node versions differ)",
}

MAX_MESSAGE_SIZE = 1 << 20
HANDSHAKE_TIMEOUT = 10.0

# handler(msg: dict) -> dict | None
#   msg carries {"type", "source", "action", "message", "data", "request_id"}
#   return {"message": ..., "data": ...} to answer; None means "handled, empty reply".
MessageHandler = Callable[[dict], Optional[dict]]


def _dumps(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


class CrossServerNode:
    """Client half of the cross-server link."""

    def __init__(
        self,
        uri: str,
        server_name: str,
        token: str = "",
        *,
        version: str = "",
        handler: Optional[MessageHandler] = None,
        logger: Optional[logging.Logger] = None,
        reconnect: bool = True,
        reconnect_delays: tuple = RECONNECT_DELAYS,
        ping_interval: float = 20,
        ping_timeout: float = 20,
        max_message_size: int = MAX_MESSAGE_SIZE,
    ):
        self.uri = uri
        self.name = server_name
        self.token = token or ""
        self.version = version
        self.handler = handler
        self.logger = logger or logging.getLogger("games_ai.cross_server.node")
        self.reconnect = reconnect
        self._reconnect_delays = reconnect_delays

        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout
        self._max_message_size = max_message_size

        self._conn = None                        # websockets.sync.client.ClientConnection
        self._thread: Optional[threading.Thread] = None
        self._first_attempt = threading.Event()
        self._first_result: Optional[bool] = None
        self._connected = threading.Event()
        self._stopping = threading.Event()

        self._lock = threading.RLock()
        self._peers: list[str] = []
        self._rid = 0
        self._pending: dict[str, tuple[threading.Event, dict]] = {}
        self._fatal: Optional[str] = None

    # ------------------------------------------------------------------ life
    def start(self, timeout: float = 10.0) -> bool:
        """Start the link thread.  Returns True once the handshake succeeded."""
        if self._thread is not None:
            raise RuntimeError("node already started")
        self._thread = threading.Thread(target=self._run, name="games-ai-node", daemon=True)
        self._thread.start()
        self._first_attempt.wait(timeout)
        return bool(self._first_result)

    def stop(self, timeout: float = 5.0) -> None:
        self._stopping.set()
        conn, self._conn = self._conn, None
        self._close_quietly(conn, 1000, "node is going away")
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def peers(self) -> list[str]:
        """Other servers, as reported by the hub."""
        with self._lock:
            return list(self._peers)

    @property
    def fatal_error(self) -> Optional[str]:
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
                ) as conn:
                    try:
                        ok = self._handshake(conn)
                        self._first_result = ok
                        self._first_attempt.set()
                        if ok:
                            attempt = 0
                            self._session(conn)      # blocks until the link drops
                    except ConnectionClosed as exc:
                        self.logger.info("link to %s closed: %s", self.uri, exc)
                        self._note_close(conn, exc)
            except ConnectionClosed as exc:
                self.logger.info("connection to %s closed: %s", self.uri, exc)
            except OSError as exc:               # hub down, DNS failure, refused...
                self.logger.info("cannot reach %s: %s", self.uri, exc)
            except Exception:
                self.logger.exception("node link crashed")
            finally:
                self._first_result = self._first_result if self._first_result is not None else False
                self._first_attempt.set()
                self._connected.clear()
                with self._lock:
                    self._conn = None
                    self._peers = []

            if self._stopping.is_set():
                break
            if self._fatal is not None:
                self.logger.error("cross-server link disabled: %s", self._fatal)
                break
            if not self.reconnect:
                break

            delay = self._reconnect_delays[min(attempt, len(self._reconnect_delays) - 1)]
            attempt += 1
            self.logger.info("reconnecting to %s in %.1fs", self.uri, delay)
            if self._stopping.wait(delay):
                break

    def _handshake(self, conn) -> bool:
        conn.send(_dumps({
            "type": "hello",
            "protocol": PROTOCOL_VERSION,
            "server": self.name,
            "token": self.token,
            "version": self.version,
        }))
        try:
            raw = conn.recv(timeout=HANDSHAKE_TIMEOUT)
        except (ConnectionClosed, TimeoutError):
            self._note_close(conn)
            return False
        try:
            ack = json.loads(raw)
        except (TypeError, ValueError):
            self._fatal = "the hub sent a non-JSON hello_ack"
            return False
        if not isinstance(ack, dict) or ack.get("type") != "hello_ack":
            self._fatal = "unexpected first frame from the hub: {!r}".format(ack.get("type"))
            return False
        if ack.get("protocol") != PROTOCOL_VERSION:
            self._fatal = "protocol version mismatch (hub speaks {!r})".format(ack.get("protocol"))
            return False

        with self._lock:
            self._conn = conn
            self._peers = [str(p) for p in ack.get("peers", [])]
        self._connected.set()
        self.logger.info("connected to hub %r, peers: %s", ack.get("hub"), self.peers or "(none)")
        return True

    def _session(self, conn) -> None:
        try:
            for raw in conn:
                self._on_frame(conn, raw)
        finally:
            self._connected.clear()

    def _note_close(self, conn, exc: Optional[Exception] = None) -> None:
        """Remember a fatal close code so the retry loop can give up."""
        code = getattr(getattr(exc, "rcvd", None), "code", None)
        if code is None:
            code = getattr(conn, "close_code", None)
        if code in FATAL_CLOSE_CODES:
            self._fatal = FATAL_CLOSE_CODES[code]

    # ------------------------------------------------------------- receiving
    def _on_frame(self, conn, raw: Any) -> None:
        try:
            msg = json.loads(raw)
        except (TypeError, ValueError):
            self.logger.warning("dropping a non-JSON frame from the hub")
            return
        if not isinstance(msg, dict):
            return

        mtype = msg.get("type")
        if mtype == "reply":
            self._resolve_pending(msg)
            return
        if mtype == "event":
            if msg.get("action") == "peers":       # hub pushed the online list
                with self._lock:
                    self._peers = [str(p) for p in msg.get("data", {}).get("peers", [])]
                return
            self._call_handler(msg)
            return
        if mtype != "message":
            self.logger.warning("unknown frame type %r from the hub", mtype)
            return
        if msg.get("action") == "ping":
            self._answer(conn, msg, {"message": "pong"})
            return
        self._answer(conn, msg, self._call_handler(msg))

    def _call_handler(self, msg: dict) -> dict:
        if self.handler is None:
            return {"ok": False, "error": "node has no handler"}
        try:
            payload = self.handler(msg)
        except Exception as exc:
            self.logger.exception("handler failed for action %r", msg.get("action"))
            return {"ok": False, "error": "handler failed: {}".format(exc)}
        if payload is None:
            return {"ok": True, "message": "", "data": {}}
        reply = {"ok": True, "message": "", "data": {}}
        reply.update(payload)
        return reply

    # ------------------------------------------------------------- sending
    def send(
        self,
        target: Optional[str],
        action: str,
        message: str = "",
        data: Optional[dict] = None,
        *,
        wait: bool = False,
        timeout: float = 5.0,
        event: bool = False,
    ) -> Optional[dict]:
        """Talk to the hub itself (``target=None``), one peer, or ``"*"``.

        ``event=True`` sends a fire-and-forget frame; otherwise every ``message``
        gets one ``reply``, which ``wait=True`` blocks for.
        """
        conn = self._conn
        if conn is None:
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
            conn.send(_dumps(msg))
        except ConnectionClosed:
            return {"ok": False, "error": "connection closed"} if wait else None
        except Exception as exc:
            self.logger.exception("send failed")
            return {"ok": False, "error": str(exc)} if wait else None

        if not wait or event:
            return None
        try:
            if not wake.wait(timeout):
                return {"ok": False, "error": "timeout after {}s".format(timeout)}
            return box["reply"]
        finally:
            with self._lock:
                self._pending.pop(msg["request_id"], None)

    def ping(self, target: Optional[str] = None, timeout: float = 5.0) -> float:
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
            return "{}#{}".format(self.name, self._rid)

    def _resolve_pending(self, msg: dict) -> None:
        rid = msg.get("request_id")
        with self._lock:
            entry = self._pending.get(rid)
        if entry is None:
            self.logger.debug("late reply for %r, nobody is waiting", rid)
            return
        wake, box = entry
        box["reply"] = msg
        wake.set()

    def _answer(self, conn, request: dict, payload: Optional[dict]) -> None:
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
        try:
            conn.send(_dumps(reply))
        except ConnectionClosed:
            pass
        except Exception:
            self.logger.exception("failed to answer %r", request.get("action"))

    def _close_quietly(self, conn, code: int, reason: str) -> None:
        if conn is None:
            return
        try:
            conn.close(code, reason)
        except Exception:
            pass
