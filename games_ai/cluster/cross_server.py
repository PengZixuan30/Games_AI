"""Cross-server coordinator: decide what this instance is, then own the link.

Called once per plugin load (from ``on_load``) and always on a background thread: the
probe dials the configured uri, which can take a couple of seconds and must never block
MCDR's plugin loading.

The role this instance ends up with:

* ``server`` -- the uri was free, so this instance listens and becomes the hub of the
  cluster; its own AI, ChatParam and tools are the authoritative ones;
* ``client`` -- the uri answered as a GamesAI hub, so this instance dials it and hands
  its commands over instead of running them itself;
* ``local``  -- no cross-server at all: the uri is owned by something else (or is not
  usable), so this instance keeps every feature to itself, exactly like a standalone
  install does today.

``force_server`` skips the probe and insists on the server role; when the port is taken
anyway the instance falls back to ``local`` with an error instead of failing the load.

Enrolment: a node needs its own token, which only the hub can issue. The probe needs no
token, so an unenrolled instance still *detects* the hub -- it then stays in local mode and
says what to do instead of dialling with a token it does not have. With ``auto_enroll`` it
sends exactly one enrolment request, so the hub can list it under ``!!gamesai node pending``.
"""

import logging
import time
import socket
import threading
from collections.abc import Iterable
from urllib.parse import urlsplit

from .websockets_client import (
    PROBE_FOREIGN,
    PROBE_GAMES_AI,
    PROBE_UNREACHABLE,
    CrossServerNode,
    probe_hub,
)
from .websockets_server import CrossServerHub, is_port_available

MODE_SERVER = "server"
MODE_CLIENT = "client"
MODE_LOCAL = "local"


def _free_loopback_port() -> int | None:
    """Pick a free port on 127.0.0.1 for the loopback hub."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            return probe.getsockname()[1]
    except OSError:
        return None


def parse_uri(uri: str) -> tuple[str, int] | None:
    """``ws://host:port`` -> ``(host, port)``; None when the address is not usable."""
    try:
        parts = urlsplit(uri)
    except ValueError:
        return None
    if parts.scheme not in ("ws", "wss") or not parts.hostname:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    if port is None:
        port = 443 if parts.scheme == "wss" else 80
    return parts.hostname, port


# A uri whose instance is restarting answers nothing for a while, and a cluster reload
# restarts every instance at once, so a client can easily look at the hub's address during that
# window. Without a grace period it would settle on local mode and never rejoin (the role is
# decided once per load).
SILENT_URI_GRACE_SECONDS = 15.0
SILENT_URI_RETRY_INTERVAL = 1.5


def local_addresses() -> set[str]:
    """Every address this machine can bind: the loopback names, the wildcards, and its own IPs."""
    addresses = {"127.0.0.1", "::1", "localhost", "0.0.0.0", "::"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, proto=socket.IPPROTO_TCP):
            addresses.add(info[4][0])
    except OSError:
        pass
    try:
        # the address the OS itself would use to leave this machine (nothing is sent)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            addresses.add(probe.getsockname()[0])
    except OSError:
        pass
    return addresses


def is_servable(host: str) -> bool:
    """True when ``host`` is an address this instance could actually listen on.

    A uri pointing anywhere else can only ever be dialled: deciding "server" for it ends in a
    failed bind, and during a reload that means a stray local mode instead of a plain client.
    """
    return host in local_addresses()


def _probe_with_grace(uri: str, *, logger: logging.Logger, token: str, grace: float):
    """Probe ``uri`` until it answers or the grace period runs out."""
    deadline = time.monotonic() + grace
    announced = False
    while True:
        result, peers, hub_name = probe_hub(uri, logger=logger, token=token)
        if result != PROBE_UNREACHABLE or time.monotonic() >= deadline:
            return result, peers, hub_name
        if not announced:
            announced = True
            logger.info(f"waiting up to {grace:.0f}s for the instance at {uri} to answer "
                        f"(a cluster reload restarts every instance at once)")
        time.sleep(min(SILENT_URI_RETRY_INTERVAL, max(0.0, deadline - time.monotonic())))


def decide_mode(uri: str, *, force_server: bool, logger: logging.Logger,
                token: str = "", previous_role: str | None = None,
                grace: float | None = None) -> tuple[str, str]:
    """Pick the role for this load.  Returns ``(mode, reason)``; never raises.

    ``previous_role`` is what this instance was on the last load, when the caller knows it: an
    instance that was a client waits for its hub instead of racing it for the port, which is
    what used to swap the two roles on a machine where both can bind the same address.
    """
    if grace is None:
        grace = SILENT_URI_GRACE_SECONDS
    target = parse_uri(uri)
    if target is None:
        return MODE_LOCAL, f"{uri!r} is not a usable ws:// address"
    host, port = target
    scheme = urlsplit(uri).scheme

    if force_server:
        if scheme != "ws":
            return MODE_LOCAL, f"force_server needs a ws:// uri, {uri!r} cannot be served here"
        if is_port_available(host, port):
            return MODE_SERVER, f"force_server is enabled and ws://{host}:{port} is free"
        return MODE_LOCAL, f"force_server is enabled but ws://{host}:{port} is already occupied"

    # Only a client (or an address we could never serve) waits: a hub restarting itself must
    # still claim a free port immediately.
    # Only a dial-only ws:// address, or an instance that was a client, waits for an answer:
    # a hub restarting itself must still claim a free port immediately, and a wss:// uri can
    # never be served from here at all (a reverse proxy terminates the TLS in front of the hub).
    waiting = previous_role == MODE_CLIENT or (scheme == "ws" and not is_servable(host))
    if waiting:
        result, peers, hub_name = _probe_with_grace(uri, logger=logger, token=token, grace=grace)
    else:
        result, peers, hub_name = probe_hub(uri, logger=logger, token=token)

    if result == PROBE_GAMES_AI:
        return MODE_CLIENT, f"a GamesAI hub {hub_name!r} answered at {uri} ({len(peers)} peer(s) online)"
    if result == PROBE_FOREIGN:
        return MODE_LOCAL, f"{uri} is occupied by something that is not a GamesAI hub"

    # Nothing answered, not even during the grace period.
    if scheme == "ws" and not is_servable(host):
        return MODE_LOCAL, f"the hub at {uri} did not answer within {grace:.0f}s"
    if scheme != "ws":
        return MODE_LOCAL, f"nothing answered at {uri} and only a ws:// address can be served"
    # An enrolled instance never takes the hub role. A node that grabbed the port while its hub
    # was reloading would swap the two roles for good: the real hub comes back, finds a GamesAI
    # hub answering and becomes *its* client (with ``force_server`` it gives up and goes local).
    # A client whose link is down refuses hub-class commands and keeps retrying the address,
    # which is the honest answer; an operator who really wants to rebuild the hub here runs
    # ``!!gamesai node forget`` first, and that drops the token this check needs.
    if token and previous_role != MODE_SERVER and is_port_available(host, port):
        return MODE_CLIENT, (f"nothing answered at {uri}; this instance is enrolled as a node, "
                             f"so it stays a client and keeps retrying "
                             f"(!!gamesai node forget to build a hub here instead)")
    if is_port_available(host, port):
        return MODE_SERVER, f"nothing answered at {uri} and ws://{host}:{port} is free"
    return MODE_LOCAL, f"nothing answered at {uri} but ws://{host}:{port} is occupied"


class CrossServerManager:
    #: The role this instance held on its last load. The caller sets it so that a
    #: reload cannot swap a hub and a client that share one address (see decide_mode).
    role_hint: str | None = None
    """Owns the hub or the node of this instance, or nothing at all in local mode."""

    def __init__(
        self,
        uri: str,
        *,
        name: str,
        version: str = "",
        force_server: bool = False,
        handler=None,
        allow_app_id: Iterable[str] = (),
        token: str = "",
        auto_enroll: bool = True,
        node_file: str | None = None,
        ttl_hours: int = -1,
        on_bot_token=None,
        on_peer_registered=None,
        logger: logging.Logger | None = None,
    ):
        self.uri = uri
        self.name = name
        self.version = version
        self.force_server = force_server
        self.handler = handler
        self.allow_app_id = tuple(allow_app_id)
        # This node's own token, from its identity file; empty means "not enrolled yet".
        self.token = token or ""
        self.auto_enroll = auto_enroll
        # Hub-side node table file, and the TTL copied into every token this hub issues.
        self.node_file = node_file
        self.ttl_hours = ttl_hours
        self.on_bot_token = on_bot_token
        # Hub side: called with (name, version, features) after a peer registers, so the plugin
        # can notice a node that came back on an older version (see _on_peer_registered).
        self.on_peer_registered = on_peer_registered
        self.logger = logger or logging.getLogger(__name__)

        self.mode = MODE_LOCAL
        self.reason = "not decided yet"
        self.hub: CrossServerHub | None = None
        self.node: CrossServerNode | None = None
        self.hub_uri: str | None = None
        # True when the hub recorded an enrolment request for this instance and nobody has
        # issued a token yet: the state `!!gamesai node status` reports.
        self.enrol_requested = False
        self._stopping = threading.Event()
        self._lock = threading.RLock()

    # ------------------------------------------------------------- lifecycle
    def start(self, timeout: float = 10.0) -> str:
        """Decide and build the link.  Returns the final mode."""
        mode, reason = decide_mode(self.uri, force_server=self.force_server,
                                   logger=self.logger, token=self.token,
                                   previous_role=self.role_hint)
        target = parse_uri(self.uri)
        if self._stop_requested("while the role was being decided"):
            return self.mode

        if mode == MODE_SERVER and target is not None:
            hub = CrossServerHub(target[0], target[1], name=self.name, handler=self.handler,
                                 extra_app_ids=self.allow_app_id, logger=self.logger,
                                 node_file=self.node_file, ttl_hours=self.ttl_hours,
                                 on_bot_token=self.on_bot_token,
                                 on_peer_registered=self.on_peer_registered)
            if hub.start(timeout):
                if self._abandon(hub):
                    return self.mode
                with self._lock:
                    self.hub = hub
                    self.hub_uri = f"ws://{target[0]}:{target[1]}"
                self._settle(MODE_SERVER, reason)
            else:
                hub.stop()
                self._settle(MODE_LOCAL, f"{reason}, but binding it failed")
                self._start_local_hub(timeout)
        elif mode == MODE_CLIENT:
            node = CrossServerNode(
                self.uri,
                self.name,
                self.token,
                version=self.version,
                handler=self.handler,
                logger=self.logger,
                auto_enroll=self.auto_enroll,
            )
            if node.start(timeout):
                if self._abandon(node):
                    return self.mode
                with self._lock:
                    self.node = node
                self._settle(MODE_CLIENT, reason)
            else:
                self.enrol_requested = bool(node.enrol_requested)
                if node.enrol_requested or not self.token:
                    # The hub is there, but this instance has no token of its own: it stays
                    # local until somebody claims one (see !!gamesai node claim).
                    node.stop()
                    self._settle(
                        MODE_LOCAL,
                        f"found the hub {node.hub_name or self.uri!r} but this instance is not "
                        f"enrolled; ask the hub for a token, then run "
                        f"!!gamesai node claim <token>",
                    )
                    self.logger.warning(
                        f"found the hub {node.hub_name or self.uri!r} but this instance is not "
                        f"enrolled; ask the hub for a token, then run "
                        f"!!gamesai node claim <token>"
                    )
                    self._start_local_hub(timeout)
                else:
                    # The probe has just proved that a GamesAI hub answers at this uri, and
                    # this instance holds a token, so one failed attempt (the hub restarting,
                    # a lost packet right after a claim) must not throw the client role away:
                    # `is_client` stays True and the node keeps its backoff retry loop, so the
                    # link comes back on its own. Degrading to local here used to strand an
                    # enrolled instance until somebody reloaded it -- with a loopback hub whose
                    # liveness then hid the fact that every command ran on the wrong machine.
                    if self._abandon(node):
                        return self.mode
                    failure = node.fatal_error or "the handshake was refused"
                    retrying = node.fatal_error is None
                    with self._lock:
                        self.node = node
                    self._settle(
                        MODE_CLIENT,
                        f"{reason}, but the link failed: {failure}"
                        + ("; retrying in the background" if retrying else ""),
                    )
                    self.logger.error(
                        f"found the hub at {self.uri}, but the link failed: {failure}; keeping "
                        f"the client role"
                        + (" and retrying in the background (!!gamesai node status)"
                           if retrying else
                           "; commands stay with the hub instead of running here with this "
                           "instance's own state (!!gamesai node status)")
                    )
        else:
            if self._stop_requested("while the role was being decided"):
                return self.mode
            self._settle(MODE_LOCAL, reason)
            self._start_local_hub(timeout)

        self.logger.info(f"cross-server role: {self.mode} ({self.reason})")
        return self.mode

    def _stop_requested(self, when: str) -> bool:
        """True once stop() was called; also settles the role so callers can just return."""
        if not self._stopping.is_set():
            return False
        self._settle(MODE_LOCAL, f"the plugin unloaded {when}")
        self.logger.info(f"cross-server role: {MODE_LOCAL} (the plugin unloaded {when})")
        return True

    def _abandon(self, link) -> bool:
        """Stop a link that was built after stop() had already been requested."""
        if not self._stopping.is_set():
            return False
        try:
            link.stop()
        except Exception:
            self.logger.exception("failed to stop a link built during shutdown")
        self._stop_requested("while the role was being decided")
        return True

    def _start_local_hub(self, timeout: float) -> None:
        """Host a loopback-only hub so local peers (the bot) still have somewhere to register.

        Local mode means "do not touch the configured uri", not "have no peers at all": the
        JS bot is a client of ours in every mode, so it needs a socket. A random port on
        127.0.0.1 cannot collide with the address we deliberately stayed away from.
        """
        if self._stopping.is_set():
            return
        port = _free_loopback_port()
        if port is None:
            self.logger.error("no free loopback port for the local bot link")
            return
        hub = CrossServerHub("127.0.0.1", port, name=self.name, handler=self.handler,
                             logger=self.logger, node_file=self.node_file,
                             ttl_hours=self.ttl_hours, on_bot_token=self.on_bot_token,
                             on_peer_registered=self.on_peer_registered)
        if hub.start(timeout):
            if self._abandon(hub):
                return
            with self._lock:
                self.hub = hub
                self.hub_uri = f"ws://127.0.0.1:{port}"
        else:
            hub.stop()
            self.logger.error("the local loopback hub could not be started")

    def stop(self, timeout: float = 5.0) -> None:
        # Raised first: a decision thread that is still probing (or that is between "port
        # bound" and "hub assigned") reads it and stops whatever it built, so an unload can
        # never leave a listener behind.
        self._stopping.set()
        with self._lock:
            hub, node = self.hub, self.node
            self.hub = self.node = None
        if node is not None:
            try:
                node.stop(timeout)
            except Exception:
                self.logger.exception("failed to stop the cross-server node")
        if hub is not None:
            try:
                hub.stop(timeout)
            except Exception:
                self.logger.exception("failed to stop the cross-server hub")

    def _settle(self, mode: str, reason: str) -> None:
        self.mode = mode
        self.reason = reason

    # --------------------------------------------------------------- queries
    @property
    def is_server(self) -> bool:
        return self.mode == MODE_SERVER

    @property
    def is_client(self) -> bool:
        return self.mode == MODE_CLIENT

    @property
    def connected(self) -> bool:
        """True while the link can actually carry frames right now."""
        if self.hub is not None:
            return self.hub.is_running
        if self.node is not None:
            return self.node.connected
        return False

    @property
    def peers(self) -> list[str]:
        """The other servers (and bots) currently online, as seen by this instance."""
        if self.hub is not None:
            return self.hub.peers
        if self.node is not None:
            return self.node.peers
        return []

    @property
    def peer_versions(self) -> dict[str, str]:
        """The plugin version each online peer announced, hub side only (name -> version).

        An empty dict on a client is correct rather than a gap: a node is not the one that
        decides who needs updating, and the hub's ``hello_ack`` carries no version.
        """
        hub = self.hub
        return hub.peer_versions if hub is not None else {}

    def peer_supports(self, name: str, feature: str) -> bool:
        """True when that online peer announced ``feature`` in its hello (see the hub)."""
        hub = self.hub
        return hub.peer_supports(name, feature) if hub is not None else False

    # ------------------------------------------------------------ enrolment
    @property
    def enrolled(self) -> bool:
        """True when this instance holds a token (it may still be refused for other reasons)."""
        return bool(self.token)

    @property
    def hub_name(self) -> str:
        """The name the hub gave us, when we are a client of one."""
        node = self.node
        return node.hub_name if node is not None else ""

    @property
    def token_expires_in(self) -> int | None:
        """Seconds until this node's token expires, as the hub reported it; None = unlimited."""
        node = self.node
        return node.expires_in if node is not None else None

    @property
    def peer_uri(self) -> str:
        """The address a *local* peer (the JS bot) must dial in this mode.

        A hub that we host answers on :attr:`hub_uri`; in client mode there is no local hub,
        so local peers join the same hub we dialled.
        """
        return self.hub_uri or self.uri

    def send_to_hub(
        self,
        action: str,
        message: str = "",
        data: dict | None = None,
        *,
        wait: bool = False,
        timeout: float = 5.0,
    ) -> dict | None:
        """Send to whichever instance owns the link, or handle it here when we own it."""
        if self.node is not None:
            return self.node.send(None, action, message, data, wait=wait, timeout=timeout)
        if self.hub is not None:
            return self.hub.send(None, action, message, data, wait=wait, timeout=timeout)
        return {"ok": False, "error": "the cross-server link is not running"} if wait else None

    def send_to(
        self,
        target: str,
        action: str,
        message: str = "",
        data: dict | None = None,
        *,
        wait: bool = False,
        timeout: float = 5.0,
    ) -> dict | None:
        """Send one request to a named peer, through whichever side owns the link."""
        hub, node = self.hub, self.node
        if hub is not None:
            return hub.send(target, action, message, data, wait=wait, timeout=timeout)
        if node is not None:
            return node.send(target, action, message, data, wait=wait, timeout=timeout)
        return {"ok": False, "error": "the cross-server link is not running"} if wait else None
