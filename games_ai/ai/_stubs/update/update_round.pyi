# Generated from games_ai/update/update_round.py by tools/build_tool_stubs.py -- do not edit.
import threading
from . import updater as updater
from ..ai import context_table as context_table
from ..cluster.cross_server import MODE_CLIENT as MODE_CLIENT
from ..cluster.websockets_server import FEATURE_UPDATE_ORDER as FEATURE_UPDATE_ORDER
from ..core import logger as logger
from ..core.config import plugin_config as plugin_config
from _typeshed import Incomplete
from collections.abc import Callable as Callable
from mcdreforged.api.types import PluginServerInterface as PluginServerInterface
from mcdreforged.command.command_source import CommandSource as CommandSource

_server_of: Callable[[], object | None]
_manager_of: Callable[[], object | None]
_link_thread_of: Callable[[], threading.Thread | None]
_version: str
_unload_status_code: int
_timer: threading.Timer | None

def attach(*, server_of: Callable[[], object | None], manager_of: Callable[[], object | None], link_thread_of: Callable[[], threading.Thread | None], version: str) -> None:
    """Bind this module to the plugin instance that owns the live state.

    The three getters are read at use time -- never cached at attach time -- so a manager that
    ``!!gamesai node claim`` replaced, or a server that a later load set, is the one used. A run
    without :func:`attach` behaves exactly like a plugin with no cross-server link.
    """
def unload_status() -> int:
    """1 while this unload is the reload of an update, 0 for an ordinary shutdown."""
def stop_timer() -> None:
    """Cancel the armed 24 h timer, if any (called from ``on_unload``)."""

_UPDATE_ACK_TIMEOUT: float
_UPDATE_STAGE_DEADLINE: float
_UPDATE_REJOIN_DEADLINE: float
_UPDATE_CATCHUP_INTERVAL: float
_UPDATE_ROUND_HISTORY: int
_update_loop_lock: Incomplete
_update_loop_started: bool
_update_round_lock: Incomplete
_update_round: dict | None
_update_order_lock: Incomplete
_update_order_thread: threading.Thread | None
_update_rounds_seen: list[str]
_last_catchup: float
_STAGE_RANK: Incomplete

def check_update(source: CommandSource, context: dict): ...
def _settled_role(timeout: float = 20.0) -> str:
    '''The cross-server role, waiting out a decision that is still in flight.

    ``plugin_config.cross_server_mode`` reads "pending" from load until the background probe
    settles it (``!!gamesai node claim`` starts that over). "Pending" must never be read as
    "probably not a client": updating inside that window could make an instance that is on its
    way to becoming a client install a release by itself, which is the role swap the round
    exists to prevent.
    '''
def cyclic_check_updates(server: PluginServerInterface): ...
def update(server: PluginServerInterface, force_table: bool = False, notify=None, announce: bool = True):
    '''Check the catalogue for a newer release and hand it to the updater.

    ``notify`` replaces ``server.say`` for the lines this function produces. ``!!gamesai check``
    passes the command source\'s ``reply``: the command may have been forwarded from a client,
    and only a reply travels back to the instance that typed it.

    ``announce`` is False for the 24 h loop and the check it runs on load: nobody asked for that
    one, so "checking" and "no new version" are not broadcast at all -- a line per load, for a
    decision no player is waiting for -- and go to the debug log instead (``logger.verbose``,
    visible with ``!!gamesai debug``). A release that *is* found is announced either way, and so
    is a check that fails: those two need an operator\'s attention. A typed ``!!gamesai check``
    keeps every line, because somebody is waiting for the answer.
    '''
def self_update(server: PluginServerInterface, release_entry: dict, new_version: str):
    """Hand the release the checker resolved over to :mod:`games_ai.update.updater`.

    On the hub this is a whole cluster round: the artifact is fetched and verified here first
    (a hub that cannot install the release must not order its nodes to install it), then every
    online node is ordered to install it and the hub *blocks* until they are done, and only
    then does the hub replace its own file. On a standalone instance it is just the download
    and the swap.

    There is deliberately no `!!MCDR plugin install` fallback: a failure is reported and the
    round ends (see docs/<lang>/cross-server.md).
    """
def _set_node_stage(entry: dict, stage: str, error: str = '') -> None:
    """Record how far one node got.  A stage never moves backwards.

    The ack to an order and the node's own report arrive as two independent frames, so they can
    be processed in either order. Without this ranking a late ``accepted`` would overwrite the
    ``staged`` that already arrived, and the hub would wait for a report that will never come.
    """
def _ack_failure_stage(reply: dict | None) -> tuple[str, str]:
    """The stage and detail to record for an order that did not come back ok.

    An ack timeout is not a failure: the node may simply be busy (its link thread can be
    serving a routed tool call) and report ``staged`` a moment later. Recording ``failed`` would
    outrank that late report (see :data:`_STAGE_RANK`) and make the hub skip a node that is
    actually updating, so a timeout is recorded as ``timeout`` -- it ranks below the node's own
    word and the round waits for it up to the stage deadline.
    """
def _order_cluster_update(server: PluginServerInterface, release) -> dict:
    '''Order every online node to install ``release``; returns ``{name: state}``.

    Only instances that announced the ``update_order`` feature are ordered: an older build
    answers every unknown action with an automatic ``{"ok": true}``, and reading that as
    success would mean "the hub believes in a cluster update that never happened". Those nodes
    are reported instead (they have to be updated by hand once, see the migration note in
    docs/<lang>/cross-server.md).
    '''
def _wait_for_cluster_update(server: PluginServerInterface, state: dict, release) -> None:
    '''Block until every ordered node is staged or failed, then until it came back updated.

    This is the "nodes first" half of the rule. A node decides its cross-server role once per
    plugin load, so it must never load while the hub is down: that is what would let it take
    over the hub port (and hand the roles to each other for good). Waiting for the node\'s
    *reconnect* rather than for its word is deliberate -- "staged" only means the bytes are
    verified on disk, not that the new version came up.
    '''
def _report_cluster_update(server: PluginServerInterface, state: dict, release) -> None:
    """One honest summary of the round, for the console and the log."""
def _on_update_result(sender: str, data: dict) -> None:
    """A node reporting how far it got with an order (runs on the link thread: record + wake)."""
def _on_update_order(sender: str, data: dict) -> dict:
    """Handle one update order from the hub (runs on the link thread: validate, then delegate).

    The reply is deliberately sent before any work happens, because this thread is also the
    reader of this connection: a download here would freeze every frame of this node -- while
    the hub sits waiting for the ack. The download itself runs on its own thread and reports
    back with ``plugin_update_result``.
    """
def _node_update_worker(round_id: str, version: str, url: str, sha256: str, size: int) -> None:
    """Install one ordered release on this node, reporting every outcome to the hub.

    ``staged`` is reported *before* the swap: applying unloads this plugin, which drops the
    link, so anything said afterwards would never arrive. The hub knows that and waits for this
    node to come back announcing the new version instead.
    """
def _start_update_loop(server: PluginServerInterface) -> None:
    """Start the 24 h check loop -- on everything except a client.

    A client never checks for updates: the hub decides, and a client that updated itself would
    break the ordering the round depends on (it has to load while the hub is up). Called once
    the cross-server role is settled, from ``_start_cross_server``.
    """
def _on_peer_registered(name: str, version: str, features) -> None:
    """Hub side: a node just registered. If it is behind us, schedule a catch-up round.

    Runs on that node's connection thread, so it only decides and hands the work to a thread of
    its own. Three things are checked before anything is spent: only a GamesAI peer (the
    Mineflayer bot announces a version too, and must never consume the catch-up budget), only a
    peer that is genuinely *older* (never push a node backwards), and at most one catch-up per
    minute (a flapping node must not start a round per reconnect).
    """
def _catch_up_round(server: PluginServerInterface) -> None:
    """Order the nodes that are behind up to the version this hub already runs.

    The checker cannot drive this case: it only ever acts on a release *newer* than the one we
    run, so a node that missed the round (it was offline, or its download failed) would stay
    behind forever once the hub is current. The hub does not reinstall itself here -- it is
    already on that version -- it only orders, waits and reports.
    """
def _own_release(server: PluginServerInterface):
    """The catalogue entry for the version this instance runs, or None when unpublished."""
def _fetch_catalogue(timeout: float = 30.0) -> dict:
    """Read the plugin catalogue.  The checker does its own (untimed) fetch; this one is for
    one-off lookups and always carries a timeout, so a hung request cannot outlive the round."""
def get_main_version(ver: str): ...

_SNAPSHOT_PATTERN: Incomplete

def _snapshot_number(version: str) -> int:
    """The ``-SNAPSHOT-n`` counter of a version, or 0 when it is not a snapshot."""
def _version_is_older(candidate: str, reference: str) -> bool:
    '''True when ``candidate`` is an older build than ``reference``.

    :func:`get_main_version` deliberately ignores the snapshot suffix (``0.8.0-SNAPSHOT-7`` and
    ``-8`` compare equal there), so it cannot answer "is this node behind us" on its own -- and
    that question decides whether the hub may order a node to install a release. Without the
    suffix comparison a node that is *newer* than the hub would be handed the hub\'s older
    release, i.e. pushed backwards.
    '''
