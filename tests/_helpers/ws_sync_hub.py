"""Cross-server hub (WebSocket server side), threading flavour.

Layout: ONE instance runs the hub, every instance (including the hub) may run a
node client (see ws_sync_node.py) and connect to it.  The hub keeps a
``server name -> connection`` table and routes frames between nodes.

Wire protocol -- one JSON object per text frame:

    node -> hub   hello       {"type": "hello", "protocol": 1, "server": "alpha",
                               "token": "<secret>", "version": "0.7.3"}
    hub -> node   hello_ack   {"type": "hello_ack", "protocol": 1, "hub": "hub",
                               "request_id": "...", "peers": ["beta"]}
    both          message     {"type": "message", "request_id": "alpha#7",
                               "source": "alpha", "target": "beta" | "*" | null,
                               "action": "chat", "message": "hi", "data": {}}
    both          reply       {"type": "reply", "request_id": "alpha#7",
                               "source": "beta", "target": "alpha",
                               "ok": true, "message": "hi back", "data": {},
                               "error": null}
    both          event       same shape as message, never answered

Routing rules:
  * the hub always overwrites ``source`` with the registered name of the sender,
  * ``target`` = a peer name  -> deliver to that peer only,
  * ``target`` = ``"*"``      -> deliver to every peer except the sender,
  * ``target`` missing/None/the hub's own name -> the hub handles it itself,
  * every ``message`` is answered with exactly one ``reply`` sent back to
    ``source``; ``event`` is fire and forget.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Optional

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import serve

PROTOCOL_VERSION = 1

CLOSE_BAD_HANDSHAKE = 4000
CLOSE_BAD_TOKEN = 4001
CLOSE_NO_NAME = 4002
CLOSE_REPLACED = 4003
CLOSE_BAD_PROTOCOL = 4004

MAX_MESSAGE_SIZE = 1 << 20
HANDSHAKE_TIMEOUT = 10.0

# handler(msg: dict) -> dict | None
#   msg carries {"type", "source", "action", "message", "data", "request_id"}
#   return None            -> reply {"ok": True, "message": ""}  (nothing to say)
#   return {"message": ...} / {"data": ...} / {"ok": False, "error": ...}
MessageHandler = Callable[[dict], Optional[dict]]


def _dumps(obj: dict) -> str:
    # ensure_ascii=False keeps Chinese readable in the frame and on the wire.
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


class CrossServerHub:
    """Star-topology hub.  Start it once per network, in its own thread."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        name: str = "hub",
        token: str = "",
        handler: Optional[MessageHandler] = None,
        logger: Optional[logging.Logger] = None,
        ping_interval: float = 20,
        ping_timeout: float = 20,
        max_message_size: int = MAX_MESSAGE_SIZE,
    ):
        self.host = host
        self.port = port
        self.name = name
        self.token = token or ""
        self.handler = handler
        self.logger = logger or logging.getLogger("games_ai.cross_server.hub")

        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout
        self._max_message_size = max_message_size

        self._server = None                      # websockets.sync.server.Server
        self._thread: Optional[threading.Thread] = None
        self._started = threading.Event()
        self._stopping = threading.Event()

        self._lock = threading.RLock()
        self._peers: dict[str, Any] = {}         # server name -> ServerConnection
        self._rid = 0
        self._pending: dict[str, tuple[threading.Event, dict]] = {}

    # ------------------------------------------------------------------ life
    def start(self, timeout: float = 10.0) -> bool:
        """Spawn the daemon thread that owns the listening socket."""
        if self._thread is not None:
            raise RuntimeError("hub already started")
        self._thread = threading.Thread(target=self._serve, name="games-ai-hub", daemon=True)
        self._thread.start()
        return self._started.wait(timeout)

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
                self.logger.info("cross-server hub listening on ws://%s:%s", self.host, self.port)
                self._started.set()
                server.serve_forever()          # blocks until shutdown()
        except Exception:
            self.logger.exception("cross-server hub failed")
            self._started.set()                 # unblock start() so the caller sees is_running == False
        finally:
            self._server = None

    def stop(self, timeout: float = 5.0) -> None:
        self._stopping.set()
        server, self._server = self._server, None
        if server is not None:
            try:
                server.shutdown()               # thread-safe, stops serve_forever()
            except Exception:
                self.logger.exception("failed to shut the hub down")
        with self._lock:
            conns = list(self._peers.values())
            self._peers.clear()
        for conn in conns:
            self._close_quietly(conn, 1001, "hub is going away")
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._server is not None

    @property
    def peers(self) -> list[str]:
        """Names of the nodes currently registered."""
        with self._lock:
            return sorted(self._peers)

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
    ) -> Optional[dict]:
        """Send to one node (``target`` = its name) or handle locally (``None``).

        With ``wait=True`` blocks until the peer's reply arrives and returns it
        as ``{"ok": bool, "message": str, "data": dict, "error": str|None}``.
        Returns ``None`` when the frame could not be sent at all (``wait=False``).
        """
        if target is None or target == self.name:
            return self._handle_local_payload(action, message, data, wait, timeout)

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

    def broadcast(self, action: str, message: str = "", data: Optional[dict] = None) -> int:
        """Fire and forget to every registered node.  Returns how many got it."""
        msg = {
            "type": "event",
            "source": self.name,
            "action": action,
            "message": message,
            "data": data or {},
        }
        sent = 0
        with self._lock:
            conns = list(self._peers.items())
        for name, conn in conns:
            if self._send(conn, msg):
                sent += 1
        return sent

    def ping(self, target: Optional[str] = None, timeout: float = 5.0) -> dict:
        """Round trip in seconds.  ``target=None`` measures every node at once.

        Returns ``{"alpha": 0.0031, "beta": -1.0}`` -- ``-1.0`` means no reply.
        """
        if target is not None:
            t0 = time.perf_counter()
            reply = self.send(target, "ping", wait=True, timeout=timeout)
            if not reply or not reply.get("ok"):
                return {target: -1.0}
            return {target: time.perf_counter() - t0}
        return {name: self.ping(name, timeout)[name] for name in self.peers}

    # ------------------------------------------------------------- internals
    def _next_rid(self) -> str:
        with self._lock:
            self._rid += 1
            return "{}#{}".format(self.name, self._rid)

    def _send_and_maybe_wait(self, msg: dict, wait: bool, timeout: float) -> Optional[dict]:
        target = msg["target"]
        with self._lock:
            conn = self._peers.get(target)
        if conn is None:
            if wait:
                return {
                    "ok": False,
                    "error": "unknown target {!r}".format(target),
                    "data": {"peers": self.peers},
                }
            return None

        wake = None
        box: dict = {}
        if wait:
            wake = threading.Event()
            with self._lock:
                self._pending[msg["request_id"]] = (wake, box)

        try:
            if not self._send(conn, msg):
                return {"ok": False, "error": "send failed"} if wait else None
            if not wait:
                return None
            if not wake.wait(timeout):
                return {"ok": False, "error": "timeout after {}s".format(timeout)}
            return box["reply"]
        finally:
            if wait:
                with self._lock:
                    self._pending.pop(msg["request_id"], None)

    def _handle_local_payload(
        self, action: str, message: str, data: Optional[dict], wait: bool, timeout: float
    ) -> Optional[dict]:
        """The hub is the addressee -- answer with the plugin handler in line."""
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

    def _call_handler(self, msg: dict) -> dict:
        if self.handler is None:
            return {"ok": False, "error": "hub has no handler"}
        try:
            payload = self.handler(msg)
        except Exception as exc:
            self.logger.exception("hub handler failed for action %r", msg.get("action"))
            return {"ok": False, "error": "handler failed: {}".format(exc)}
        if payload is None:
            return {"ok": True, "message": "", "data": {}}
        reply = {"ok": True, "message": "", "data": {}}
        reply.update(payload)
        return reply

    # ---------------------------------------------------------- connections
    def _handler(self, conn) -> None:
        """One thread per connection (websockets.sync.server does that for us)."""
        peer = "?"
        try:
            peer = self._handshake(conn)
            if peer is None:
                return

            with self._lock:
                old = self._peers.get(peer)
                self._peers[peer] = conn
            if old is not None and old is not conn:
                self.logger.warning("node %r reconnected, dropping the old connection", peer)
                self._close_quietly(old, CLOSE_REPLACED, "replaced by a new connection")

            self.logger.info("node %r registered (%d online)", peer, len(self.peers))
            self._send(conn, {
                "type": "hello_ack",
                "protocol": PROTOCOL_VERSION,
                "hub": self.name,
                "request_id": "{}#hello".format(self.name),
                "peers": [p for p in self.peers if p != peer],
            })
            self._push_peers()

            for raw in conn:                    # blocking receive loop
                self._on_frame(peer, conn, raw)
        except ConnectionClosed:
            pass
        except Exception:
            self.logger.exception("connection handler crashed")
        finally:
            with self._lock:
                if self._peers.get(peer) is conn:
                    del self._peers[peer]
                    gone = True
                else:
                    gone = False
            if gone:
                self.logger.info("node %r left (%d online)", peer, len(self.peers))
                self._push_peers()

    def _push_peers(self) -> None:
        """Tell every node who is online, so the list never goes stale."""
        with self._lock:
            names = sorted(self._peers)
        for name, conn in list(self._peers.items()):
            self._send(conn, {
                "type": "event",
                "source": self.name,
                "action": "peers",
                "message": "",
                "data": {"peers": [p for p in names if p != name]},
            })

    def _handshake(self, conn) -> Optional[str]:
        try:
            raw = conn.recv(timeout=HANDSHAKE_TIMEOUT)
        except (ConnectionClosed, TimeoutError):
            self.logger.warning("client never sent a hello frame")
            return None
        try:
            hello = json.loads(raw)
        except (TypeError, ValueError):
            self._close_quietly(conn, CLOSE_BAD_HANDSHAKE, "hello must be JSON")
            return None
        if not isinstance(hello, dict) or hello.get("type") != "hello":
            self._close_quietly(conn, CLOSE_BAD_HANDSHAKE, "the first frame must be hello")
            return None
        if hello.get("protocol") != PROTOCOL_VERSION:
            self._close_quietly(conn, CLOSE_BAD_PROTOCOL, "protocol version mismatch")
            return None
        if self.token and hello.get("token") != self.token:
            self.logger.warning("rejected a node with a bad token")
            self._close_quietly(conn, CLOSE_BAD_TOKEN, "bad token")
            return None
        name = str(hello.get("server") or "").strip()
        if not name:
            self._close_quietly(conn, CLOSE_NO_NAME, "hello must carry a server name")
            return None
        return name

    def _on_frame(self, sender: str, conn, raw: Any) -> None:
        try:
            msg = json.loads(raw)
        except (TypeError, ValueError):
            self.logger.warning("dropping a non-JSON frame from %r", sender)
            return
        if not isinstance(msg, dict):
            return

        msg["source"] = sender                   # authoritative, blocks spoofing
        mtype = msg.get("type")
        target = msg.get("target")

        if mtype == "reply":
            if target in (None, "", self.name):
                self._resolve_pending(msg)
            elif not self._deliver(target, msg):
                self.logger.debug("reply for %r could not be delivered", target)
            return

        if mtype == "event":
            if target == "*" or not target:
                self._fanout(msg, exclude=sender)
                self._call_handler(msg)          # let the hub observe it too
            else:
                self._deliver(target, msg)
            return

        if mtype != "message":
            self.logger.warning("unknown frame type %r from %r", mtype, sender)
            return

        if msg.get("action") == "ping":          # answered locally, never routed
            self._answer(conn, msg, {"message": "pong"})
            return

        if target in (None, "", self.name):
            self._answer(conn, msg, self._call_handler(msg))
        elif target == "*":
            self._fanout(msg, exclude=sender)
            self._answer(conn, msg, {"message": "broadcast", "data": {"peers": self.peers}})
        elif not self._deliver(target, msg):
            self._answer(conn, msg, {
                "ok": False,
                "error": "unknown target {!r}".format(target),
                "data": {"peers": self.peers},
            })

    def _fanout(self, msg: dict, *, exclude: Optional[str] = None) -> int:
        sent = 0
        with self._lock:
            conns = list(self._peers.items())
        for name, conn in conns:
            if name == exclude:
                continue
            if self._send(conn, msg):
                sent += 1
        return sent

    def _deliver(self, name: str, msg: dict) -> bool:
        with self._lock:
            conn = self._peers.get(name)
        return conn is not None and self._send(conn, msg)

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
        self._send(conn, reply)

    def _send(self, conn, msg: dict) -> bool:
        try:
            conn.send(_dumps(msg))              # send() takes the protocol lock: any thread is fine
            return True
        except ConnectionClosed:
            return False
        except Exception:
            self.logger.exception("send failed")
            return False

    def _close_quietly(self, conn, code: int, reason: str) -> None:
        try:
            conn.close(code, reason)
        except Exception:
            pass
