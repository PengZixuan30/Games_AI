"""Same protocol, asyncio flavour (closest to the existing stub).

Verified counterpart of ws_sync_hub.py / ws_sync_node.py.  The extra machinery
compared with the sync flavour is the thread <-> event loop bridge:
run_coroutine_threadsafe + asyncio.run_coroutine_threadsafe for every send that
comes from an MCDR thread.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any, Callable, Optional

import websockets
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

PROTOCOL_VERSION = 1
CLOSE_BAD_HANDSHAKE, CLOSE_BAD_TOKEN, CLOSE_NO_NAME, CLOSE_REPLACED, CLOSE_BAD_PROTOCOL = 4000, 4001, 4002, 4003, 4004
FATAL_CLOSE_CODES = {4001: "bad token", 4002: "no server name", 4003: "name taken", 4004: "protocol mismatch"}
MAX_SIZE = 1 << 20


def _dumps(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _drain(loop: asyncio.AbstractEventLoop) -> None:
    """Cancel and await every leftover task before closing the loop.

    Without this asyncio prints 'Task was destroyed but it is pending!' at exit
    (websockets' keepalive() tasks and connect()'s async generator).
    """
    pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
    for task in pending:
        task.cancel()
    if pending:
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    loop.run_until_complete(loop.shutdown_asyncgens())


class AsyncHub:
    def __init__(self, host, port, *, name="hub", token="", handler=None, logger=None):
        self.host, self.port, self.name, self.token = host, port, name, token or ""
        self.handler = handler
        self.logger = logger or logging.getLogger("games_ai.hub.async")
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._peers: dict[str, Any] = {}
        self._pending: dict[str, asyncio.Future] = {}
        self._rid = 0
        self._lock = threading.RLock()
        self._started = False

    # ---- lifecycle -------------------------------------------------------
    def start(self, timeout=10.0) -> bool:
        self._thread = threading.Thread(target=self._thread_main, name="games-ai-hub", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self._started

    def _thread_main(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._main())
        except Exception:
            self.logger.exception("hub crashed")
        finally:
            _drain(loop)
            loop.close()
            self._ready.set()

    async def _main(self):
        async with serve(self._handler, self.host, self.port, ping_interval=20,
                         ping_timeout=20, max_size=MAX_SIZE, logger=self.logger) as server:
            self._server = server
            self._started = True
            self.logger.info("hub listening on ws://%s:%s", self.host, self.port)
            self._ready.set()
            await server.serve_forever()

    def stop(self, timeout=5.0):
        self._started = False
        loop = self._loop
        server = getattr(self, "_server", None)
        if loop is not None and not loop.is_closed() and server is not None:
            try:
                loop.call_soon_threadsafe(server.close)
            except RuntimeError:
                pass
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    @property
    def peers(self):
        with self._lock:
            return sorted(self._peers)

    # ---- thread-safe sending --------------------------------------------
    def _submit(self, coro, timeout):
        if self._loop is None:
            coro.close()
            raise RuntimeError("hub loop is not running")
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def send(self, target, action, message="", data=None, *, wait=False, timeout=5.0):
        msg = {"type": "message", "request_id": self._next_rid(), "source": self.name,
               "target": target, "action": action, "message": message, "data": data or {}}
        return self._submit(self._send(msg, wait, timeout), timeout + 1)

    def broadcast(self, action, message="", data=None):
        msg = {"type": "event", "source": self.name, "action": action, "message": message, "data": data or {}}
        return self._submit(self._fanout(msg), 5)

    def _next_rid(self):
        with self._lock:
            self._rid += 1
            return "{}#{}".format(self.name, self._rid)

    async def _send(self, msg: dict, wait: bool, timeout: float):
        conn = self._peers.get(msg["target"])
        if conn is None:
            return {"ok": False, "error": "unknown target {!r}".format(msg["target"])}
        fut = self._loop.create_future() if wait else None
        if fut is not None:
            self._pending[msg["request_id"]] = fut
        try:
            await conn.send(_dumps(msg))
            if fut is None:
                return None
            try:
                return await asyncio.wait_for(asyncio.shield(fut), timeout)
            except asyncio.TimeoutError:
                return {"ok": False, "error": "timeout"}
        finally:
            self._pending.pop(msg["request_id"], None)

    async def _fanout(self, msg):
        sent = 0
        for conn in list(self._peers.values()):
            try:
                await conn.send(_dumps(msg))
                sent += 1
            except ConnectionClosed:
                pass
        return sent

    # ---- connection handling --------------------------------------------
    async def _handler(self, conn):
        peer = "?"
        try:
            peer = await self._handshake(conn)
            if peer is None:
                return
            old = self._peers.get(peer)
            self._peers[peer] = conn
            if old is not None and old is not conn:
                await old.close(CLOSE_REPLACED, "replaced")
            await conn.send(_dumps({"type": "hello_ack", "protocol": PROTOCOL_VERSION, "hub": self.name,
                                    "peers": [p for p in self.peers if p != peer]}))
            await self._push_peers()
            self.logger.info("node %r registered", peer)
            async for raw in conn:
                await self._on_frame(peer, conn, raw)
        except ConnectionClosed:
            pass
        except Exception:
            self.logger.exception("handler crashed")
        finally:
            if self._peers.get(peer) is conn:
                del self._peers[peer]
                await self._push_peers()

    async def _push_peers(self):
        names = self.peers
        for name, conn in list(self._peers.items()):
            try:
                await conn.send(_dumps({"type": "event", "source": self.name, "action": "peers",
                                        "data": {"peers": [p for p in names if p != name]}}))
            except ConnectionClosed:
                pass

    async def _handshake(self, conn):
        try:
            hello = json.loads(await asyncio.wait_for(conn.recv(), 10))
        except (asyncio.TimeoutError, ValueError, TypeError):
            await conn.close(CLOSE_BAD_HANDSHAKE, "bad hello")
            return None
        if not isinstance(hello, dict) or hello.get("type") != "hello":
            await conn.close(CLOSE_BAD_HANDSHAKE, "first frame must be hello")
            return None
        if hello.get("protocol") != PROTOCOL_VERSION:
            await conn.close(CLOSE_BAD_PROTOCOL, "protocol mismatch")
            return None
        if self.token and hello.get("token") != self.token:
            await conn.close(CLOSE_BAD_TOKEN, "bad token")
            return None
        name = str(hello.get("server") or "").strip()
        if not name:
            await conn.close(CLOSE_NO_NAME, "no server name")
            return None
        return name

    async def _on_frame(self, sender, conn, raw):
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return
        msg["source"] = sender
        mtype, target = msg.get("type"), msg.get("target")
        if mtype == "reply":
            fut = self._pending.get(msg.get("request_id"))
            if fut is not None and not fut.done():
                fut.set_result(msg)
            elif target not in (None, "", self.name):
                await self._deliver(target, msg)
            return
        if mtype == "event":
            if not target or target == "*":
                await self._fanout(msg)
            else:
                await self._deliver(target, msg)
            return
        if mtype != "message":
            return
        if msg.get("action") == "ping":
            await self._answer(conn, msg, {"message": "pong"})
        elif target in (None, "", self.name):
            await self._answer(conn, msg, self._call_handler(msg))
        elif target == "*":
            await self._fanout(msg)
            await self._answer(conn, msg, {"message": "broadcast", "data": {"peers": self.peers}})
        elif not await self._deliver(target, msg):
            await self._answer(conn, msg, {"ok": False, "error": "unknown target {!r}".format(target),
                                           "data": {"peers": self.peers}})

    async def _deliver(self, name, msg):
        conn = self._peers.get(name)
        if conn is None:
            return False
        try:
            await conn.send(_dumps(msg))
            return True
        except ConnectionClosed:
            return False

    def _call_handler(self, msg):
        if self.handler is None:
            return {"ok": False, "error": "no handler"}
        try:
            payload = self.handler(msg) or {}
        except Exception as exc:
            self.logger.exception("handler failed")
            return {"ok": False, "error": str(exc)}
        reply = {"ok": True, "message": "", "data": {}}
        reply.update(payload)
        return reply

    async def _answer(self, conn, request, payload):
        reply = {"type": "reply", "request_id": request.get("request_id"), "source": self.name,
                 "target": request.get("source"), "ok": True, "message": "", "data": {}, "error": None}
        reply.update(payload or {})
        try:
            await conn.send(_dumps(reply))
        except ConnectionClosed:
            pass


class AsyncNode:
    def __init__(self, uri, server_name, token="", *, handler=None, logger=None):
        self.uri, self.name, self.token = uri, server_name, token or ""
        self.handler = handler
        self.logger = logger or logging.getLogger("games_ai.node.async")
        self._loop = None
        self._thread = None
        self._ready = threading.Event()
        self._first_result = None
        self._connected = threading.Event()
        self._conn = None
        self._peers: list[str] = []
        self._pending: dict[str, asyncio.Future] = {}
        self._rid = 0
        self._stopping = threading.Event()
        self._fatal = None

    def start(self, timeout=10.0) -> bool:
        self._thread = threading.Thread(target=self._thread_main, name="games-ai-node", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return bool(self._first_result)

    def _thread_main(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._task = loop.create_task(self._run())
        try:
            loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            pass
        except Exception:
            self.logger.exception("node crashed")
        finally:
            _drain(loop)                                         # let connect() close itself
            loop.close()
            self._ready.set()

    async def _run(self):
        attempt = 0
        while not self._stopping.is_set():
            try:
                async for conn in connect(self.uri, ping_interval=20, ping_timeout=20,
                                          max_size=MAX_SIZE, open_timeout=10, logger=self.logger):
                    try:
                        ok = await self._handshake(conn)
                        self._first_result = ok
                        self._ready.set()
                        if not ok:
                            break
                        attempt = 0
                        self._conn = conn
                        self._connected.set()
                        async for raw in conn:
                            await self._on_frame(conn, raw)
                    except ConnectionClosed:
                        pass
                    finally:
                        self._connected.clear()
                        self._conn = None
                        self._peers = []
                    if self._fatal:
                        break
            except OSError as exc:
                self.logger.info("cannot reach %s: %s", self.uri, exc)
            except Exception:
                self.logger.exception("link crashed")
            finally:
                if self._first_result is None:
                    self._first_result = False
                self._ready.set()
            if self._stopping.is_set() or self._fatal:
                break
            delay = min(0.5 * (2 ** attempt), 30.0)
            attempt += 1
            self.logger.info("reconnecting in %.1fs", delay)
            if self._stopping.wait(delay):
                break
        if self._fatal:
            self.logger.error("link disabled: %s", self._fatal)

    async def _handshake(self, conn):
        await conn.send(_dumps({"type": "hello", "protocol": PROTOCOL_VERSION,
                                "server": self.name, "token": self.token}))
        try:
            ack = json.loads(await asyncio.wait_for(conn.recv(), 10))
        except (asyncio.TimeoutError, ValueError, TypeError):
            return False
        except ConnectionClosed as exc:
            self._note_close(conn, exc)
            return False
        if ack.get("type") != "hello_ack" or ack.get("protocol") != PROTOCOL_VERSION:
            self._fatal = "bad hello_ack"
            return False
        self._peers = [str(p) for p in ack.get("peers", [])]
        return True

    def _note_close(self, conn, exc=None):
        code = getattr(getattr(exc, "rcvd", None), "code", None) or getattr(conn, "close_code", None)
        if code in FATAL_CLOSE_CODES:
            self._fatal = FATAL_CLOSE_CODES[code]

    async def _on_frame(self, conn, raw):
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return
        mtype = msg.get("type")
        if mtype == "reply":
            fut = self._pending.pop(msg.get("request_id"), None)
            if fut is not None and not fut.done():
                fut.set_result(msg)
            return
        if mtype == "event":
            if msg.get("action") == "peers":
                self._peers = [str(p) for p in msg.get("data", {}).get("peers", [])]
                return
            self._call_handler(msg)
            return
        if mtype != "message":
            return
        if msg.get("action") == "ping":
            await self._answer(conn, msg, {"message": "pong"})
            return
        await self._answer(conn, msg, self._call_handler(msg))

    def _call_handler(self, msg):
        if self.handler is None:
            return {"ok": False, "error": "no handler"}
        try:
            payload = self.handler(msg) or {}
        except Exception as exc:
            self.logger.exception("handler failed")
            return {"ok": False, "error": str(exc)}
        reply = {"ok": True, "message": "", "data": {}}
        reply.update(payload)
        return reply

    async def _answer(self, conn, request, payload):
        reply = {"type": "reply", "request_id": request.get("request_id"), "source": self.name,
                 "target": request.get("source"), "ok": True, "message": "", "data": {}, "error": None}
        reply.update(payload or {})
        try:
            await conn.send(_dumps(reply))
        except ConnectionClosed:
            pass

    @property
    def connected(self):
        return self._connected.is_set()

    @property
    def peers(self):
        return list(self._peers)

    @property
    def fatal_error(self):
        return self._fatal

    def send(self, target, action, message="", data=None, *, wait=False, timeout=5.0):
        if self._loop is None or self._conn is None:
            return {"ok": False, "error": "not connected"} if wait else None
        msg = {"type": "message", "request_id": self._next_rid(), "source": self.name,
               "target": target, "action": action, "message": message, "data": data or {}}
        return asyncio.run_coroutine_threadsafe(
            self._send(msg, wait, timeout), self._loop).result(timeout + 1)

    def ping(self, target=None, timeout=5.0):
        t0 = time.perf_counter()
        reply = self.send(target, "ping", wait=True, timeout=timeout)
        return time.perf_counter() - t0 if reply and reply.get("ok") else -1.0

    def _next_rid(self):
        self._rid += 1
        return "{}#{}".format(self.name, self._rid)

    async def _send(self, msg, wait, timeout):
        fut = self._loop.create_future() if wait else None
        if fut is not None:
            self._pending[msg["request_id"]] = fut
        try:
            await self._conn.send(_dumps(msg))
            if fut is None:
                return None
            try:
                return await asyncio.wait_for(asyncio.shield(fut), timeout)
            except asyncio.TimeoutError:
                return {"ok": False, "error": "timeout"}
        except ConnectionClosed:
            return {"ok": False, "error": "closed"} if wait else None
        finally:
            self._pending.pop(msg["request_id"], None)

    def stop(self, timeout=5.0):
        self._stopping.set()
        loop = self._loop
        task = getattr(self, "_task", None)
        if loop is not None and not loop.is_closed() and task is not None:
            try:
                # cancelling unwinds `async for conn in connect(...)` and closes it properly
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:                 # the loop already finished by itself
                pass
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
