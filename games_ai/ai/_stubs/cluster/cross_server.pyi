# Generated from games_ai/cluster/cross_server.py by tools/build_tool_stubs.py -- do not edit.
import logging
from .websockets_client import CrossServerNode as CrossServerNode, PROBE_FOREIGN as PROBE_FOREIGN, PROBE_GAMES_AI as PROBE_GAMES_AI, PROBE_UNREACHABLE as PROBE_UNREACHABLE, probe_hub as probe_hub
from .websockets_server import CrossServerHub as CrossServerHub, is_port_available as is_port_available
from _typeshed import Incomplete
from collections.abc import Iterable

MODE_SERVER: str
MODE_CLIENT: str
MODE_LOCAL: str

def _free_loopback_port() -> int | None:
    """Pick a free port on 127.0.0.1 for the loopback hub."""
def parse_uri(uri: str) -> tuple[str, int] | None:
    """``ws://host:port`` -> ``(host, port)``; None when the address is not usable."""

SILENT_URI_GRACE_SECONDS: float
SILENT_URI_RETRY_INTERVAL: float

def local_addresses() -> set[str]:
    """Every address this machine can bind: the loopback names, the wildcards, and its own IPs."""
def is_servable(host: str) -> bool:
    '''True when ``host`` is an address this instance could actually listen on.

    A uri pointing anywhere else can only ever be dialled: deciding "server" for it ends in a
    failed bind, and during a reload that means a stray local mode instead of a plain client.
    '''
def _probe_with_grace(uri: str, *, logger: logging.Logger, token: str, grace: float):
    """Probe ``uri`` until it answers or the grace period runs out."""
def decide_mode(uri: str, *, force_server: bool, logger: logging.Logger, token: str = '', previous_role: str | None = None, grace: float | None = None) -> tuple[str, str]:
    """Pick the role for this load.  Returns ``(mode, reason)``; never raises.

    ``previous_role`` is what this instance was on the last load, when the caller knows it: an
    instance that was a client waits for its hub instead of racing it for the port, which is
    what used to swap the two roles on a machine where both can bind the same address.
    """

class CrossServerManager:
    role_hint: str | None
    uri: Incomplete
    name: Incomplete
    version: Incomplete
    force_server: Incomplete
    handler: Incomplete
    allow_app_id: Incomplete
    token: Incomplete
    auto_enroll: Incomplete
    node_file: Incomplete
    ttl_hours: Incomplete
    on_bot_token: Incomplete
    on_peer_registered: Incomplete
    logger: Incomplete
    mode: Incomplete
    reason: str
    hub: CrossServerHub | None
    node: CrossServerNode | None
    hub_uri: str | None
    enrol_requested: bool
    _stopping: Incomplete
    _lock: Incomplete
    def __init__(self, uri: str, *, name: str, version: str = '', force_server: bool = False, handler=None, allow_app_id: Iterable[str] = (), token: str = '', auto_enroll: bool = True, node_file: str | None = None, ttl_hours: int = -1, on_bot_token=None, on_peer_registered=None, logger: logging.Logger | None = None) -> None: ...
    def start(self, timeout: float = 10.0) -> str:
        """Decide and build the link.  Returns the final mode."""
    def _stop_requested(self, when: str) -> bool:
        """True once stop() was called; also settles the role so callers can just return."""
    def _abandon(self, link) -> bool:
        """Stop a link that was built after stop() had already been requested."""
    def _start_local_hub(self, timeout: float) -> None:
        '''Host a loopback-only hub so local peers (the bot) still have somewhere to register.

        Local mode means "do not touch the configured uri", not "have no peers at all": the
        JS bot is a client of ours in every mode, so it needs a socket. A random port on
        127.0.0.1 cannot collide with the address we deliberately stayed away from.
        '''
    def stop(self, timeout: float = 5.0) -> None: ...
    def _settle(self, mode: str, reason: str) -> None: ...
    @property
    def is_server(self) -> bool: ...
    @property
    def is_client(self) -> bool: ...
    @property
    def connected(self) -> bool:
        """True while the link can actually carry frames right now."""
    @property
    def peers(self) -> list[str]:
        """The other servers (and bots) currently online, as seen by this instance."""
    @property
    def peer_versions(self) -> dict[str, str]:
        """The plugin version each online peer announced, hub side only (name -> version).

        An empty dict on a client is correct rather than a gap: a node is not the one that
        decides who needs updating, and the hub's ``hello_ack`` carries no version.
        """
    def peer_supports(self, name: str, feature: str) -> bool:
        """True when that online peer announced ``feature`` in its hello (see the hub)."""
    @property
    def enrolled(self) -> bool:
        """True when this instance holds a token (it may still be refused for other reasons)."""
    @property
    def hub_name(self) -> str:
        """The name the hub gave us, when we are a client of one."""
    @property
    def token_expires_in(self) -> int | None:
        """Seconds until this node's token expires, as the hub reported it; None = unlimited."""
    @property
    def peer_uri(self) -> str:
        """The address a *local* peer (the JS bot) must dial in this mode.

        A hub that we host answers on :attr:`hub_uri`; in client mode there is no local hub,
        so local peers join the same hub we dialled.
        """
    def send_to_hub(self, action: str, message: str = '', data: dict | None = None, *, wait: bool = False, timeout: float = 5.0) -> dict | None:
        """Send to whichever instance owns the link, or handle it here when we own it."""
    def send_to(self, target: str, action: str, message: str = '', data: dict | None = None, *, wait: bool = False, timeout: float = 5.0) -> dict | None:
        """Send one request to a named peer, through whichever side owns the link."""
