"""The update path: the 24 h checker, the cluster round and the version comparison.

One update is a round. The hub orders every online node, blocks until each one is staged or
failed, waits for them to come back on the new version, and only then replaces its own file --
that order matters because a node decides its cross-server role once per plugin load, so a hub
that is down while a node loads is exactly how a client and a hub swap places. The download,
verification and replacement primitives live in :mod:`games_ai.update.updater`; this module decides
*when* they run and in which order.

The entry module owns the live state: the server interface, the cross-server manager and the
thread that decides the role. This module is told how to read that state instead of importing
it, through :func:`attach`. Every getter is called at use time and never cached, because
``!!gamesai node claim`` replaces the manager and ``on_unload`` clears the server. Before
:func:`attach` runs the getters answer ``None``, which is exactly the "no link, no server" case
the code below already handles.
"""

import json
import lzma
import re
import threading
import time
import uuid
from collections.abc import Callable

import requests

from mcdreforged.api.decorator import new_thread
from mcdreforged.api.types import PluginServerInterface
from mcdreforged.command.command_source import CommandSource

from ..ai import context_table
from ..core import logger
from . import updater
from ..core.config import plugin_config
from ..cluster.cross_server import MODE_CLIENT
from ..cluster.websockets_server import APP_ID as WS_APP_ID, FEATURE_UPDATE_ORDER

#: Where the entry module's live state is read from. See :func:`attach`.
_server_of: Callable[[], object | None] = lambda: None
_manager_of: Callable[[], object | None] = lambda: None
_link_thread_of: Callable[[], threading.Thread | None] = lambda: None
#: The version this instance is running, as ``PLUGIN_METADATA`` had it at load time.
_version: str = ""

#: Reported by the update paths and read by ``on_unload``: an unload that follows a replacement
#: is an update (the player is told the server restarts), anything else is a plain shutdown.
_unload_status_code = 0

#: The 24 h timer, armed by :func:`cyclic_check_updates` once the role is settled.
_timer: threading.Timer | None = None


def attach(*, server_of: Callable[[], object | None],
           manager_of: Callable[[], object | None],
           link_thread_of: Callable[[], threading.Thread | None],
           version: str) -> None:
    """Bind this module to the plugin instance that owns the live state.

    The three getters are read at use time -- never cached at attach time -- so a manager that
    ``!!gamesai node claim`` replaced, or a server that a later load set, is the one used. A run
    without :func:`attach` behaves exactly like a plugin with no cross-server link.
    """
    global _server_of, _manager_of, _link_thread_of, _version
    _server_of = server_of
    _manager_of = manager_of
    _link_thread_of = link_thread_of
    _version = version


def unload_status() -> int:
    """1 while this unload is the reload of an update, 0 for an ordinary shutdown."""
    return _unload_status_code


def stop_timer() -> None:
    """Cancel the armed 24 h timer, if any (called from ``on_unload``)."""
    global _timer
    if _timer is None:
        return
    try:
        _timer.cancel()
    except Exception as e:
        logger.log("exception", f"{plugin_config.prefix} Failed to cancel the 24h update timer: {e}")


# ── the round's timings and its state ──────────────────────────────────────
_UPDATE_ACK_TIMEOUT = 10.0        # the node understood the order (it answers before downloading)
# Must stay comfortably above the node's own download budget (updater.DOWNLOAD_DEADLINE = 300s
# plus its retry backoff): if the hub gave up first it would reload while a node is still
# deciding its role, which is exactly the ordering this round exists to guarantee.
_UPDATE_STAGE_DEADLINE = 420.0    # download + verify + replace on the nodes, all together
_UPDATE_REJOIN_DEADLINE = 120.0   # the node reconnects announcing the new version
_UPDATE_CATCHUP_INTERVAL = 60.0   # at most one catch-up round per minute
_UPDATE_ROUND_HISTORY = 8         # how many round ids a node remembers (idempotency)
# The update loop starts once the role is settled; a client never runs it (see _start_update_loop).
_update_loop_lock = threading.Lock()
_update_loop_started = False
# The round in progress, hub side: {"id", "version", "nodes": {name: entry}}.
_update_round_lock = threading.RLock()
_update_round: dict | None = None
# Node side: the round currently being applied here, and the ids already handled.
_update_order_lock = threading.Lock()
_update_order_thread: threading.Thread | None = None
_update_rounds_seen: list[str] = []
# Hub side: when the last catch-up round was scheduled, so a reconnecting node cannot spam.
_last_catchup = 0.0
#: How far a node's reported stage may go without ever moving backwards (see _set_node_stage).
#: ``timeout`` and ``unsupported`` rank *below* what the node itself reports on purpose: both are
#: this side's guesses (a clock running out, a missing feature list), and a node that answers
#: late -- its link thread may have been busy with a routed tool call -- has to be able to
#: correct them. ``stale`` is the opposite: a node that said "staged" but never came back on the
#: new version is a settled verdict, and it outranks the report it corrects.
_STAGE_RANK = {"pending": 0, "timeout": 1, "unsupported": 2, "accepted": 3, "staged": 4,
               "failed": 4, "stale": 5}


@new_thread("games_ai@update")
def check_update(source: CommandSource, context: dict):
    server = source.get_server()
    try:
        # ``notify`` sends the lines to whoever typed the command instead of broadcasting them:
        # on a client this command arrives as a forwarded frame, and ``server.say`` on the hub
        # would reach the hub's console only -- the client player saw nothing at all.
        update(server, force_table=True, notify=source.reply)
    except Exception as e:
        server.say(f"{plugin_config.prefix}{server.rtr("games_ai.update.no_metadata")}")
        server.logger.warning(f"{plugin_config.prefix}{server.rtr("games_ai.update.no_metadata")}")

def _settled_role(timeout: float = 20.0) -> str:
    """The cross-server role, waiting out a decision that is still in flight.

    ``plugin_config.cross_server_mode`` reads "pending" from load until the background probe
    settles it (``!!gamesai node claim`` starts that over). "Pending" must never be read as
    "probably not a client": updating inside that window could make an instance that is on its
    way to becoming a client install a release by itself, which is the role swap the round
    exists to prevent.
    """
    link_thread = _link_thread_of()
    if plugin_config.cross_server_mode == "pending" and link_thread is not None:
        link_thread.join(timeout)
    return plugin_config.cross_server_mode


def cyclic_check_updates(server: PluginServerInterface):
    global _timer
    role = _settled_role()
    if role == MODE_CLIENT:
        # The role can change without a reload (``!!gamesai node claim`` turns a local instance
        # into a client), so this is checked every cycle as well: a client never re-arms.
        server.logger.info(f"{plugin_config.prefix} This instance became a cross-server client; the update "
                           f"check loop stops here (the hub decides about updates)")
        _timer = None
        return
    if role == "pending":
        server.logger.info(f"{plugin_config.prefix} The cross-server role is still being decided; this update "
                           f"check was skipped")
    else:
        try:
            # Nobody asked for this check, so it does not announce itself (see update()).
            update(server, announce=False)
        except Exception as e:
            server.say(f"{plugin_config.prefix}{server.rtr("games_ai.update.no_metadata")}")
            server.logger.warning(f"{plugin_config.prefix}{server.rtr("games_ai.update.no_metadata")}")
    _timer = threading.Timer(86400, cyclic_check_updates, args=(server,))
    _timer.name = "games_ai@update_timer"
    _timer.daemon = True
    _timer.start()

def update(server: PluginServerInterface, force_table: bool = False, notify=None, announce: bool = True):
    """Check the catalogue for a newer release and hand it to the updater.

    ``notify`` replaces ``server.say`` for the lines this function produces. ``!!gamesai check``
    passes the command source's ``reply``: the command may have been forwarded from a client,
    and only a reply travels back to the instance that typed it.

    ``announce`` is False for the 24 h loop and the check it runs on load: nobody asked for that
    one, so "checking" and "no new version" are not broadcast at all -- a line per load, for a
    decision no player is waiting for -- and go to the debug log instead (``logger.verbose``,
    visible with ``!!gamesai debug``). A release that *is* found is announced either way, and so
    is a check that fails: those two need an operator's attention. A typed ``!!gamesai check``
    keeps every line, because somebody is waiting for the answer.
    """
    global _unload_status_code
    _unload_status_code = 0
    say = notify if notify is not None else server.say

    # Refresh the context-window table as part of the same startup/24h run.
    # Keep this the very first statement: the branches below return early.
    # Manual `!!gamesai check` passes force_table=True to bypass the 24h TTL.
    try:
        context_table.refresh_table(server, force=force_table)
    except Exception as e:
        server.logger.debug(f"{plugin_config.prefix} Context window table refresh failed: {e}")

    if announce:
        say(f"{plugin_config.prefix}{server.rtr("games_ai.update.checking_update")}")
        server.logger.info(f"{plugin_config.prefix}{server.rtr("games_ai.update.checking_update")}")
    else:
        logger.verbose(server, "[update] checking the catalogue for a release")
    response = requests.get("https://api.mcdreforged.com/catalogue/everything_slim.json.xz")
    if response.status_code == 200:
        compress_data = response.content
        decompress_data = lzma.decompress(compress_data)
        json_data = json.loads(decompress_data.decode('utf-8'))
        try:
            # The whole release entry, not just the version: the updater re-reads the asset
            # fields (url, size, sha256) from it, so it never has to fetch the catalogue
            # itself. The comparison below is unchanged.
            release_entry = json_data.get("plugins").get("games_ai").get("release").get("releases")[0]
            new_version = release_entry.get("meta").get("version")
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            say(f"{plugin_config.prefix}{server.rtr("games_ai.update.no_metadata")}")
            server.logger.warning(f"{plugin_config.prefix}{server.rtr("games_ai.update.no_metadata")}")
            return e
        if get_main_version(new_version) <= get_main_version(_version):
            if announce:
                server.logger.info(f"{plugin_config.prefix}{server.rtr("games_ai.update.no_update")}")
                say(f"{plugin_config.prefix}{server.rtr("games_ai.update.no_update")}")
            else:
                logger.verbose(server, f"[update] no release newer than {_version}")
            return
        else:
            say(f"{plugin_config.prefix}{server.rtr("games_ai.update.new_update",version = new_version)}")
            server.logger.info(f"{plugin_config.prefix}{server.rtr("games_ai.update.new_update",version = new_version)}")
            self_update(server, release_entry, new_version)
            return
    else:
        say(f"{plugin_config.prefix}{server.rtr("games_ai.update.no_metadata")}")
        server.logger.warning(f"{plugin_config.prefix}{server.rtr("games_ai.update.no_metadata")}")
        return

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
    global _unload_status_code
    if _settled_role() == MODE_CLIENT:
        # Not reachable through any normal path (the loop is not started for a client and
        # !!gamesai check is executed on the hub), but this is the one place that must never
        # run on a client: a client that updated itself would load while the hub is deciding,
        # which is exactly the role swap the round exists to prevent.
        server.logger.warning(f"{plugin_config.prefix} This instance is a cross-server client; the hub decides "
                              f"about updates, so nothing was installed here")
        return
    if not updater.update_lock.acquire(blocking=False):
        server.say(f"{plugin_config.prefix}{server.rtr("games_ai.update.busy")}")
        server.logger.info(f"{plugin_config.prefix} An update is already running")
        return
    try:
        release = updater.release_from_entry(release_entry, new_version)
        server.logger.info(f"{plugin_config.prefix} Downloading GamesAI {release.version} ({release.size} bytes) "
                           f"from GitHub")
        target, staged = updater.prepare(server, release, log=logger.step(server, plugin_config.prefix))
        try:
            manager = _manager_of()
            if manager is not None and manager.is_server and manager.connected:
                state = _order_cluster_update(server, release)
                if state:
                    _wait_for_cluster_update(server, state, release)
                    _report_cluster_update(server, state, release)
                    server.say(f"{plugin_config.prefix}{server.rtr('games_ai.update.hub_reloading')}")
            # Read by on_unload: the unload inside apply_archive is the update, not a shutdown.
            _unload_status_code = 1
            updater.apply_archive(server, staged, target, release, log=logger.step(server, plugin_config.prefix))
        finally:
            updater.discard(staged)
        server.say(f"{plugin_config.prefix}{server.rtr("games_ai.update.update_ok",version = release.version)}")
        server.logger.info(f"{plugin_config.prefix} GamesAI {release.version} is loaded")
    except updater.UpdaterError as e:
        _unload_status_code = 0
        server.say(f"{plugin_config.prefix}{server.rtr(e.key,detail = e.detail)}")
        server.logger.error(f"{plugin_config.prefix} Update aborted: {e.detail}")
    except Exception as e:
        _unload_status_code = 0
        server.say(f"{plugin_config.prefix}{server.rtr("games_ai.update.failed",detail = str(e))}")
        server.logger.exception(f"{plugin_config.prefix} Update failed: {e}")
    finally:
        updater.update_lock.release()


def _set_node_stage(entry: dict, stage: str, error: str = "") -> None:
    """Record how far one node got.  A stage never moves backwards.

    The ack to an order and the node's own report arrive as two independent frames, so they can
    be processed in either order. Without this ranking a late ``accepted`` would overwrite the
    ``staged`` that already arrived, and the hub would wait for a report that will never come.
    """
    if not stage:
        return
    with _update_round_lock:
        current = str(entry.get("stage") or "pending")
        if _STAGE_RANK.get(stage, 0) <= _STAGE_RANK.get(current, 0):
            return
        entry["stage"] = stage
        if error:
            entry["error"] = error
        event = entry.get("event")
    if event is not None and stage not in ("accepted", "timeout"):
        # "timeout" is only this side's guess that an ack is late: the node's own report can
        # still arrive, so it must not wake the waiter as if the node were settled.
        event.set()


def _ack_failure_stage(reply: dict | None) -> tuple[str, str]:
    """The stage and detail to record for an order that did not come back ok.

    An ack timeout is not a failure: the node may simply be busy (its link thread can be
    serving a routed tool call) and report ``staged`` a moment later. Recording ``failed`` would
    outrank that late report (see :data:`_STAGE_RANK`) and make the hub skip a node that is
    actually updating, so a timeout is recorded as ``timeout`` -- it ranks below the node's own
    word and the round waits for it up to the stage deadline.
    """
    error = str((reply or {}).get("error") or "")
    if reply is None or not error:
        return "failed", "the node did not answer"
    if "timeout" in error.lower():
        return "timeout", error
    return "failed", error


def _order_cluster_update(server: PluginServerInterface, release) -> dict:
    """Order every online node to install ``release``; returns ``{name: state}``.

    Only instances that announced the ``update_order`` feature are ordered: an older build
    answers every unknown action with an automatic ``{"ok": true}``, and reading that as
    success would mean "the hub believes in a cluster update that never happened". Those nodes
    are reported instead (they have to be updated by hand once, see the migration note in
    docs/<lang>/cross-server.md).
    """
    global _update_round
    manager = _manager_of()
    hub = manager.hub if manager is not None else None
    state: dict[str, dict] = {}
    if hub is None:
        return state
    round_id = uuid.uuid4().hex
    versions = hub.peer_versions
    apps = hub.peer_apps
    round_state = {"id": round_id, "version": release.version, "nodes": {}}
    with _update_round_lock:
        _update_round = round_state

    candidates: list[str] = []
    for name in hub.peers:
        if apps.get(name) != WS_APP_ID:
            continue                                # never the bot, never a foreign service
        if name == hub.name:
            server.logger.warning(
                f"{plugin_config.prefix} Node {name!r} shares the hub's own name, so an update order cannot "
                f"be addressed to it; rename one of the two instances")
            continue
        current = str(versions.get(name) or "")
        if current and current == release.version:
            continue                                # it says it is already there
        if current and _version_is_older(release.version, current):
            # Never push a node backwards: it runs something newer than this release (a hand
            # installed build, or it got ahead of us while our own apply failed). A node that
            # did not announce a version (older build) has `current == ""` and is ordered like
            # any candidate; the feature check below then reports it as "unsupported".
            server.logger.warning(
                f"{plugin_config.prefix} Node {name!r} runs {current}, which is newer than "
                f"{release.version}; leaving it alone")
            continue
        candidates.append(name)
    if not candidates:
        server.logger.info(f"{plugin_config.prefix} No node needs updating to {release.version}")
        return state

    server.say(f"{plugin_config.prefix}{server.rtr('games_ai.update.round_started', version=release.version,
                                     count=len(candidates))}")
    server.logger.info(f"{plugin_config.prefix} Update round {round_id}: ordering {candidates} to install "
                       f"{release.version}")
    for name in candidates:
        entry: dict = {"stage": "pending", "error": "", "event": threading.Event()}
        state[name] = entry
        round_state["nodes"][name] = entry
        if not hub.peer_supports(name, FEATURE_UPDATE_ORDER):
            _set_node_stage(entry, "unsupported")
            server.logger.warning(
                f"{plugin_config.prefix} Node {name!r} does not support update orders (older build); it has "
                f"to be updated by hand once")
            continue
        reply = None
        try:
            reply = hub.send(name, "plugin_update", data={
                "round": round_id, "version": release.version, "url": release.url,
                "sha256": release.sha256, "size": release.size,
            }, wait=True, timeout=_UPDATE_ACK_TIMEOUT)
        except Exception as e:                        # a broken connection must not abort the round
            server.logger.warning(f"{plugin_config.prefix} Could not order node {name!r}: {e}")
            _set_node_stage(entry, "failed", str(e))
            continue
        data = (reply or {}).get("data") or {}
        if not (reply or {}).get("ok"):
            stage, detail = _ack_failure_stage(reply)
            _set_node_stage(entry, stage, detail)
            if stage == "timeout":
                server.logger.warning(
                    f"{plugin_config.prefix} Node {name!r} did not acknowledge the update order in "
                    f"time; waiting for its own report")
            else:
                server.logger.warning(f"{plugin_config.prefix} Could not order node {name!r}: {detail}")
        elif str(data.get("round") or "") != round_id or not data.get("stage"):
            _set_node_stage(entry, "unsupported")
            server.logger.warning(
                f"{plugin_config.prefix} Node {name!r} answered the update order without acknowledging it "
                f"(older build); it has to be updated by hand once")
        else:
            entry["already"] = bool(data.get("already"))
            _set_node_stage(entry, str(data["stage"]))
    return state


def _wait_for_cluster_update(server: PluginServerInterface, state: dict, release) -> None:
    """Block until every ordered node is staged or failed, then until it came back updated.

    This is the "nodes first" half of the rule. A node decides its cross-server role once per
    plugin load, so it must never load while the hub is down: that is what would let it take
    over the hub port (and hand the roles to each other for good). Waiting for the node's
    *reconnect* rather than for its word is deliberate -- "staged" only means the bytes are
    verified on disk, not that the new version came up.
    """
    deadline = time.monotonic() + _UPDATE_STAGE_DEADLINE
    server.logger.info(f"{plugin_config.prefix} Waiting for {len(state)} node(s) to install {release.version} "
                       f"(at most {int(_UPDATE_STAGE_DEADLINE)}s for the download, then "
                       f"{int(_UPDATE_REJOIN_DEADLINE)}s for them to come back)")
    for name, entry in state.items():
        stage = str(entry.get("stage") or "pending")
        if stage in ("staged", "failed", "unsupported"):
            continue                                 # nothing else will arrive for this node
        event = entry.get("event")
        remaining = max(0.0, deadline - time.monotonic())
        if event is not None and not event.wait(remaining):
            _set_node_stage(entry, "timeout",
                            f"no report within {int(_UPDATE_STAGE_DEADLINE)}s")
    rejoin_deadline = time.monotonic() + _UPDATE_REJOIN_DEADLINE
    pending: list[str] = []
    while time.monotonic() < rejoin_deadline:
        manager = _manager_of()
        versions = manager.peer_versions if manager is not None else {}
        # A node whose report timed out is watched too: the ack may simply have been late (its
        # link thread can be busy with a routed tool call) and it may well be updating right
        # now. Only "failed" and "unsupported" are settled.
        pending = [name for name, entry in state.items()
                   if entry.get("stage") in ("staged", "timeout") and not entry.get("already")
                   and versions.get(name, "") != release.version]
        if not pending:
            return
        time.sleep(0.5)
    for name in pending:
        _set_node_stage(state[name], "stale",
                        f"did not come back on {release.version} within "
                        f"{int(_UPDATE_REJOIN_DEADLINE)}s")


def _report_cluster_update(server: PluginServerInterface, state: dict, release) -> None:
    """One honest summary of the round, for the console and the log."""
    ready, problems = [], []
    for name in sorted(state):
        entry = state[name]
        stage = str(entry.get("stage") or "pending")
        if stage == "staged":
            ready.append(name)
        else:
            detail = str(entry.get("error") or "")
            problems.append(f"{name} ({stage}{': ' + detail if detail else ''})")
    server.logger.info(f"{plugin_config.prefix} Update round for {release.version}: "
                       f"{len(ready)} node(s) ready"
                       + (f", problems: {'; '.join(problems)}" if problems else ""))
    # Always told to the players, not only on failure: an operator who typed !!gamesai check
    # wants to know what the round did, and the hub reloads right after this line.
    server.say(f"{plugin_config.prefix}{server.rtr('games_ai.update.round_summary', ok=len(ready),
                                     failed=len(problems),
                                     detail='; '.join(problems) or '-')}")


def _on_update_result(sender: str, data: dict) -> None:
    """A node reporting how far it got with an order (runs on the link thread: record + wake)."""
    round_id = str(data.get("round") or "")
    with _update_round_lock:
        current = _update_round
        entry = (current or {}).get("nodes", {}).get(sender) if current else None
        if entry is None or str(current.get("id")) != round_id:
            return
    stage = str(data.get("stage") or "")
    version = str(data.get("version") or "")
    _set_node_stage(entry, stage, str(data.get("error") or ""))
    if stage == "staged":
        logger.log("info", f"{plugin_config.prefix} Node {sender!r} staged {version}")
    elif stage == "failed":
        logger.log("warning", f"{plugin_config.prefix} Node {sender!r} could not update: "
                             f"{entry.get('error')}")


def _on_update_order(sender: str, data: dict) -> dict:
    """Handle one update order from the hub (runs on the link thread: validate, then delegate).

    The reply is deliberately sent before any work happens, because this thread is also the
    reader of this connection: a download here would freeze every frame of this node -- while
    the hub sits waiting for the ack. The download itself runs on its own thread and reports
    back with ``plugin_update_result``.
    """
    global _update_order_thread
    manager = _manager_of()
    hub_name = manager.hub_name if manager is not None else ""
    if not sender or sender != hub_name:
        return {"ok": False, "error": "the update order did not come from this node's hub"}
    round_id = str(data.get("round") or "")
    version = str(data.get("version") or "")
    url = str(data.get("url") or "")
    sha256 = str(data.get("sha256") or "").strip().lower()
    try:
        size = int(data.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    if not round_id or not version:
        return {"ok": False, "error": "the update order is incomplete"}
    if not url.startswith(updater.ALLOWED_URL_PREFIX):
        return {"ok": False, "error": f"refused an update order pointing at {url!r}"}
    if size <= 0 or size > updater.MAX_ARCHIVE_BYTES:
        return {"ok": False, "error": f"refused an implausible artifact size {size}"}
    if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
        return {"ok": False, "error": "refused an update order without a usable sha256"}
    if version == _version:
        # Already there: a caught-up node is a no-op, and the hub can count it as ready.
        return {"ok": True, "data": {"stage": "staged", "round": round_id, "already": True}}
    with _update_order_lock:
        if round_id in _update_rounds_seen:
            return {"ok": True, "data": {"stage": "accepted", "round": round_id,
                                         "duplicate": True}}
        if _update_order_thread is not None and _update_order_thread.is_alive():
            return {"ok": False, "error": "an update is already running on this instance"}
        _update_rounds_seen.append(round_id)
        del _update_rounds_seen[:-_UPDATE_ROUND_HISTORY]
        thread = threading.Thread(target=_node_update_worker,
                                  args=(round_id, version, url, sha256, size),
                                  name="games_ai@update_order", daemon=True)
        _update_order_thread = thread
        thread.start()
    return {"ok": True, "data": {"stage": "accepted", "round": round_id}}


def _node_update_worker(round_id: str, version: str, url: str, sha256: str, size: int) -> None:
    """Install one ordered release on this node, reporting every outcome to the hub.

    ``staged`` is reported *before* the swap: applying unloads this plugin, which drops the
    link, so anything said afterwards would never arrive. The hub knows that and waits for this
    node to come back announcing the new version instead.
    """
    global _unload_status_code
    release = updater.ReleaseInfo(version=version, url=url, size=size, sha256=sha256,
                                  file_name=f"GamesAI-v{version}.mcdr")

    def report(stage: str, error: str = "") -> None:
        current = _manager_of()
        if current is None or not current.connected:
            return
        current.send_to_hub("plugin_update_result",
                            data={"round": round_id, "version": version, "stage": stage,
                                  "error": error})

    if not updater.update_lock.acquire(blocking=False):
        report("failed", "another update is already running on this instance")
        return
    try:
        server = _server_of()
        target, staged = updater.prepare(server, release, log=lambda message:
                                         logger.log("info", f"{plugin_config.prefix} {message}"))
        try:
            report("staged")
            logger.log("info", f"{plugin_config.prefix} Update order {round_id}: installing {version} now")
            _unload_status_code = 1
            updater.apply_archive(server, staged, target, release, log=lambda message:
                                  logger.log("info", f"{plugin_config.prefix} {message}"))
        finally:
            updater.discard(staged)
    except updater.UpdaterError as e:
        _unload_status_code = 0
        report("failed", e.detail)
        logger.log("error", f"{plugin_config.prefix} Update order {round_id} failed: {e.detail}")
    except Exception as e:                            # noqa: BLE001 - reported, never hidden
        _unload_status_code = 0
        report("failed", str(e))
        logger.log("exception", f"{plugin_config.prefix} Update order {round_id} failed: {e}")
    finally:
        updater.update_lock.release()


def _start_update_loop(server: PluginServerInterface) -> None:
    """Start the 24 h check loop -- on everything except a client.

    A client never checks for updates: the hub decides, and a client that updated itself would
    break the ordering the round depends on (it has to load while the hub is up). Called once
    the cross-server role is settled, from ``_start_cross_server``.
    """
    global _update_loop_started
    with _update_loop_lock:
        if _update_loop_started:
            return
        role = plugin_config.cross_server_mode
        if role == MODE_CLIENT:
            server.logger.info(f"{plugin_config.prefix} Cross-server client: the hub decides about updates, "
                               f"so the update check loop is not started here")
            return
        if role == "pending":
            server.logger.info(f"{plugin_config.prefix} The cross-server role is still being decided; the "
                               f"update check loop was not started")
            return
        _update_loop_started = True
    threading.Thread(target=cyclic_check_updates, daemon=True, args=(server,),
                     name="games_ai@update_loop").start()


def _on_peer_registered(name: str, version: str, features) -> None:
    """Hub side: a node just registered. If it is behind us, schedule a catch-up round.

    Runs on that node's connection thread, so it only decides and hands the work to a thread of
    its own. Three things are checked before anything is spent: only a GamesAI peer (the
    Mineflayer bot announces a version too, and must never consume the catch-up budget), only a
    peer that is genuinely *older* (never push a node backwards), and at most one catch-up per
    minute (a flapping node must not start a round per reconnect).
    """
    global _last_catchup
    manager = _manager_of()
    if manager is None or not manager.is_server:
        return
    hub = manager.hub
    if hub is None or hub.peer_apps.get(name) != WS_APP_ID:
        return                                       # the bot and foreign services never update
    own = _version
    if not version or not _version_is_older(version, own):
        return
    now = time.monotonic()
    with _update_round_lock:
        if now - _last_catchup < _UPDATE_CATCHUP_INTERVAL:
            return
        _last_catchup = now
    server = _server_of()
    if server is None:
        return
    server.logger.info(f"{plugin_config.prefix} Node {name!r} is on {version} while the hub is on {own}; "
                       f"checking for a catch-up update")
    threading.Thread(target=_catch_up_round, args=(server,), name="games_ai@update",
                     daemon=True).start()


def _catch_up_round(server: PluginServerInterface) -> None:
    """Order the nodes that are behind up to the version this hub already runs.

    The checker cannot drive this case: it only ever acts on a release *newer* than the one we
    run, so a node that missed the round (it was offline, or its download failed) would stay
    behind forever once the hub is current. The hub does not reinstall itself here -- it is
    already on that version -- it only orders, waits and reports.
    """
    if not updater.update_lock.acquire(blocking=False):
        return                                  # a full round is running: it covers this node
    try:
        release = _own_release(server)
        if release is None:
            return
        state = _order_cluster_update(server, release)
        if not state:
            return
        _wait_for_cluster_update(server, state, release)
        _report_cluster_update(server, state, release)
    except updater.UpdaterError as e:
        server.logger.warning(f"{plugin_config.prefix} Catch-up round could not run: {e.detail}")
    except Exception as e:                      # noqa: BLE001 - a background round
        server.logger.warning(f"{plugin_config.prefix} Catch-up round failed: {e}")
    finally:
        updater.update_lock.release()


def _own_release(server: PluginServerInterface):
    """The catalogue entry for the version this instance runs, or None when unpublished."""
    own = _version
    try:
        catalogue = _fetch_catalogue()
    except Exception as e:                      # noqa: BLE001 - reported, never fatal
        server.logger.warning(f"{plugin_config.prefix} Cannot read the catalogue to catch a node up: {e}")
        return None
    entry = updater.entry_for_version(catalogue, own)
    if entry is None:
        server.logger.info(f"{plugin_config.prefix} This instance runs {own}, which is not published in the "
                           f"catalogue, so a node behind it can only be updated by hand")
        return None
    return updater.release_from_entry(entry, own)


def _fetch_catalogue(timeout: float = 30.0) -> dict:
    """Read the plugin catalogue.  The checker does its own (untimed) fetch; this one is for
    one-off lookups and always carries a timeout, so a hung request cannot outlive the round."""
    response = requests.get("https://api.mcdreforged.com/catalogue/everything_slim.json.xz",
                            timeout=timeout)
    response.raise_for_status()
    return json.loads(lzma.decompress(response.content).decode("utf-8"))
    
def get_main_version(ver: str):
    main_part = ver.split('-')[0]
    major, minor, patch = main_part.split('.')
    is_release = 1 if ver == main_part else 0
    return (int(major), int(minor), int(patch), is_release)


_SNAPSHOT_PATTERN = re.compile(r"-SNAPSHOT-(\d+)$", re.IGNORECASE)


def _snapshot_number(version: str) -> int:
    """The ``-SNAPSHOT-n`` counter of a version, or 0 when it is not a snapshot."""
    match = _SNAPSHOT_PATTERN.search(str(version))
    return int(match.group(1)) if match else 0


def _version_is_older(candidate: str, reference: str) -> bool:
    """True when ``candidate`` is an older build than ``reference``.

    :func:`get_main_version` deliberately ignores the snapshot suffix (``0.8.0-SNAPSHOT-7`` and
    ``-8`` compare equal there), so it cannot answer "is this node behind us" on its own -- and
    that question decides whether the hub may order a node to install a release. Without the
    suffix comparison a node that is *newer* than the hub would be handed the hub's older
    release, i.e. pushed backwards.
    """
    left = get_main_version(candidate)
    right = get_main_version(reference)
    if left != right:
        return left < right
    return _snapshot_number(candidate) < _snapshot_number(reference)
