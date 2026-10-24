"""``!!gamesai node ...``: per-node enrolment, in a module of its own.

The eight commands under ``!!gamesai node`` are one unit -- they all speak either to the hub's node
table or to this instance's identity file -- and they used to sit in the middle of the entry
module, between the cross-server link and the data commands. They live here now, together:

* hub side: :func:`pending` (who asked to enrol), :func:`issue_token` (the one token that name is
  waiting for), :func:`list_nodes` (every enrolled node, no usable secret), :func:`revoke` and
  :func:`rotate`;
* node side: :func:`claim` (adopt a token), :func:`status` (what this instance really is) and
  :func:`forget` (drop the identity file).

None of them travels through the cluster: ``register_commands`` registers each one plainly, never
through the entry's ``_route()``, so it runs where it was typed -- a node running ``node token``
would be nonsense and would leak the hub's table.

This module never imports the entry package (``tests/test_layout.py`` pins that for every module),
so the live state and the few actions that stay behind arrive through :func:`attach`, the same way
``games_ai/update/update_round.py`` receives them. It is imported inside the dependency gate, because the
handshake probe and the token fingerprint come from ``websockets_client``.
"""
import time
from typing import Callable

from mcdreforged.api.command import CommandContext
from mcdreforged.command.command_source import CommandSource

from ..core import logger
from ..core.config import plugin_config
from ..core.permission import require_permission
from ..cluster.websockets_client import (
    PROBE_GAMES_AI,
    PROBE_UNREACHABLE,
    probe_hub_detail,
    token_fingerprint,
)

#: What the entry module owns and this one only uses. See :func:`attach`.
_server_of: Callable = lambda source=None: None
_manager_of: Callable = lambda: None
_restart_link: Callable = lambda server: None
_stop_link: Callable = lambda server: None
_store_bot_token: Callable = lambda server, name, token: None
_identity_path: Callable = lambda server=None: None
_load_identity: Callable = lambda server=None: None
_save_identity: Callable = lambda server, name, token, hub: None
_delete_identity: Callable = lambda server=None: None
_identity_fingerprint: Callable = lambda server=None: None


def attach(*, server_of, manager_of, restart_link, stop_link, store_bot_token,
           identity_path, load_identity, save_identity, delete_identity,
           identity_fingerprint) -> None:
    """Bind this module to the plugin instance that owns the live state.

    Every callable is read at *use* time -- never cached at attach time -- so a manager that
    :func:`claim` replaced, or a server a later load set, is the one the next command sees. The
    identity-file helpers and the bot-token writer stay in the entry module because the
    cross-server link uses them too; they are handed in rather than imported, because no module
    may import the entry package.
    """
    global _server_of, _manager_of, _restart_link, _stop_link, _store_bot_token
    global _identity_path, _load_identity, _save_identity, _delete_identity, _identity_fingerprint
    _server_of = server_of
    _manager_of = manager_of
    _restart_link = restart_link
    _stop_link = stop_link
    _store_bot_token = store_bot_token
    _identity_path = identity_path
    _load_identity = load_identity
    _save_identity = save_identity
    _delete_identity = delete_identity
    _identity_fingerprint = identity_fingerprint


def _source_name(source: CommandSource) -> str:
    """How a command source is recorded in the node table's ``issued_by``."""
    try:
        if source.is_console:
            return "console"
        return str(source.player or "?")
    except Exception:
        return "?"


def _hub(source: CommandSource):
    """The hub of this cluster, when this instance really is one.

    A local-mode instance also hosts a loopback hub for the bot, but it has no cluster node
    table to speak of, so the hub-side commands refuse to run there.
    """
    manager = _manager_of()
    if manager is None or not manager.is_server or manager.hub is None:
        role = plugin_config.cross_server_mode
        if manager is not None:
            role = manager.mode
        source.reply(f"{plugin_config.prefix}{source.get_server().rtr('games_ai.cross_server.node.not_hub', role=role)}")
        return None
    return manager.hub


def _sync_local_bot_token(server, name: str, token: str) -> None:
    """Keep the local bot's config in step when its token is (re)issued on this machine.

    The bot cannot type ``!!gamesai node claim``; without this, rotating its token would
    strand it until somebody edited the JS config by hand, which is exactly the human step
    the bot provisioning is supposed to avoid.
    """
    if name == plugin_config.bot_username:
        _store_bot_token(server, name, token)


def _format_duration(seconds: float) -> str:
    """A compact duration: 3d 4h / 5h 12m / 12m 30s / 30s (used for ages and for TTLs)."""
    seconds = max(0, int(seconds))
    if seconds >= 86400:
        return f"{seconds // 86400}d {seconds % 86400 // 3600}h"
    if seconds >= 3600:
        return f"{seconds // 3600}h {seconds % 3600 // 60}m"
    if seconds >= 60:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds}s"


def _format_timestamp(epoch) -> str | None:
    """An epoch second as local time, or None when it was never recorded."""
    try:
        stamp = int(epoch)
    except (TypeError, ValueError):
        return None
    if stamp <= 0:
        return None
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp))


def pending(source: CommandSource):
    """`!!gamesai node pending` -- who asked to enrol and is still waiting."""
    server = _server_of(source)
    if not require_permission(source):
        return
    hub = _hub(source)
    if hub is None:
        return
    waiting = hub.pending_requests
    if not waiting:
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.pending_empty')}")
        return
    source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.pending_header', count=len(waiting))}")
    now = time.time()
    for name in sorted(waiting):
        entry = waiting[name]
        try:
            age = _format_duration(now - float(entry.get("requested_at") or now))
        except (TypeError, ValueError):
            age = "?"
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.pending_line',
                                           name=name, app=entry.get('app') or '?',
                                           ip=entry.get('ip') or '?', age=age,
                                           requests=entry.get('requests') or 0)}")


def issue_token(source: CommandSource, context: CommandContext):
    """`!!gamesai node token <name>` -- issue the one token that name is waiting for.

    Strict on purpose: a node that never asked to enrol does not get a token (use
    `node rotate` for one that is already enrolled, `node pending` to see who is waiting), and
    a name that is *already* enrolled is refused instead of being taken over: the hub keys its
    node table by name, so issuing a second token for it would silently drop the first node's
    hash and that node would fail every connect with 4001. Two instances with the same name is
    the usual reason (see the entry's ``_default_instance_name``), and the refusal says so.
    """
    server = _server_of(source)
    if not require_permission(source):
        return
    hub = _hub(source)
    if hub is None:
        return
    name = str(context.get("name") or "").strip()
    if hub.is_enrolled(name):
        entry = hub.nodes.get(name) or {}
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.token_name_taken',
                                           name=name, ip=entry.get('last_ip') or '?')}")
        return
    if not hub.is_pending(name):
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.token_not_pending', name=name)}")
        return
    entry = hub.pending_requests.get(name) or {}
    token = hub.issue(name, app=str(entry.get("app") or ""), issued_by=_source_name(source),
                      ip=str(entry.get("ip") or ""), require_pending=True)
    if not token:
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.token_not_pending', name=name)}")
        return
    _sync_local_bot_token(server, name, token)
    # The one and only place a token is ever printed; the log line above carries the
    # fingerprint only (MCDR still writes this reply to its own log, as the docs say).
    source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.token_issued',
                                       name=name, token=token,
                                       fingerprint=token_fingerprint(token))}")


def list_nodes(source: CommandSource):
    """`!!gamesai node list` -- every enrolled node, without any usable secret."""
    server = _server_of(source)
    if not require_permission(source):
        return
    hub = _hub(source)
    if hub is None:
        return
    nodes = hub.nodes
    if not nodes:
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.list_empty')}")
        return
    source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.list_header', count=len(nodes))}")
    for name in sorted(nodes):
        remaining = hub.expires_in(name)
        if remaining is None:
            expires = server.rtr("games_ai.cross_server.node.unlimited")
        elif remaining <= 0:
            expires = server.rtr("games_ai.cross_server.node.expired")
        else:
            expires = _format_duration(remaining)
        entry = nodes[name]
        ttl = entry.get("ttl_hours")
        try:
            ttl_text = (server.rtr("games_ai.cross_server.node.unlimited") if int(ttl) < 0
                        else f"{int(ttl)}h")
        except (TypeError, ValueError):
            ttl_text = server.rtr("games_ai.cross_server.node.unknown")
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.list_line',
                                           name=name, app=entry.get('app') or '?',
                                           version=entry.get('version')
                                                   or server.rtr("games_ai.cross_server.node.unknown"),
                                           issued=_format_timestamp(entry.get('issued_at'))
                                                  or server.rtr("games_ai.cross_server.node.unknown"),
                                           ttl=ttl_text, expires=expires,
                                           ip=entry.get('last_ip') or '?',
                                           seen=_format_timestamp(entry.get('last_seen'))
                                                or server.rtr("games_ai.cross_server.node.never"),
                                           fingerprint=hub.fingerprint(name) or '?')}")


def revoke(source: CommandSource, context: CommandContext):
    """`!!gamesai node revoke <name>` -- drop the entry; the node's next connect is 4001."""
    server = _server_of(source)
    if not require_permission(source):
        return
    hub = _hub(source)
    if hub is None:
        return
    name = str(context.get("name") or "").strip()
    if not hub.revoke(name):
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.not_enrolled', name=name)}")
        return
    source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.revoked', name=name)}")


def rotate(source: CommandSource, context: CommandContext):
    """`!!gamesai node rotate <name>` -- a fresh token for an enrolled node, printed once."""
    server = _server_of(source)
    if not require_permission(source):
        return
    hub = _hub(source)
    if hub is None:
        return
    name = str(context.get("name") or "").strip()
    if not hub.is_enrolled(name):
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.not_enrolled', name=name)}")
        return
    token = hub.rotate(name, issued_by=_source_name(source))
    if not token:
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.not_enrolled', name=name)}")
        return
    _sync_local_bot_token(server, name, token)
    source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.rotated',
                                       name=name, token=token,
                                       fingerprint=token_fingerprint(token))}")


def claim(source: CommandSource, context: CommandContext):
    """`!!gamesai node claim <token>` -- adopt the token the hub issued for this name.

    The token is verified against the hub *before* anything is written, because a token is
    bound to one name: pasting another node's token has to fail here, with the name it was
    issued for, instead of silently breaking this instance's link.

    ``server`` comes from the entry's ``_plugin_server``, never from the command source: only the
    plugin interface knows where this instance's identity file lives, and a claim that writes
    nothing must never look like a success (that is how an enrolled instance used to stay in
    local mode and run every command itself).
    """
    server = _server_of(source)
    if not require_permission(source):
        return
    token = str(context.get("token") or "").strip()
    if not token:
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.claim_usage')}")
        return
    uri = plugin_config.websocket_uri
    if not uri:
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.not_configured')}")
        return
    name = plugin_config.cross_server_name
    # Short timeout on purpose: this runs inside the command, and the hub is normally the
    # machine next door (or the one this instance is already talking to).
    result, info = probe_hub_detail(uri, timeout=2.0, logger=server.logger, token=token)
    if result == PROBE_UNREACHABLE:
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.claim_unreachable', uri=uri)}")
        return
    if result != PROBE_GAMES_AI:
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.claim_not_hub', uri=uri)}")
        return
    token_name = info.get("token_name")
    if not token_name:
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.claim_unknown_token', uri=uri)}")
        return
    if str(token_name) != name:
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.claim_wrong_name',
                                           token_name=token_name, name=name)}")
        return
    path = _save_identity(server, name, token, uri)
    if path is None:
        # No identity file means no token for the link, so the instance would silently stay in
        # local mode and run every command itself. Refuse the claim instead of faking success.
        logger.log("error", f"{plugin_config.prefix} Cannot write the identity file of {name!r}: this plugin "
                            f"has no data folder to write it to")
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.claim_write_failed',
                                           name=name)}")
        return
    source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.claim_ok',
                                       name=name, path=path)}")
    server.logger.info(
        f"{plugin_config.prefix} Enrolled as {name!r} on {uri} (token fingerprint "
        f"{token_fingerprint(token)}); reconnecting"
    )
    _restart_link(server)


def status(source: CommandSource):
    """`!!gamesai node status` -- the role, the enrolment and, on a hub, the cluster size.

    The answer follows what this instance really is, because no single sentence is true for all
    three roles. A hub that is told "not enrolled, go claim a token" is sent to do something it
    never does -- it is the one that *issues* those tokens -- and printing its own name in the
    ``hub:`` field reads as if it had dialled itself.
    """
    server = _server_of(source)
    if not require_permission(source):
        return
    unknown = server.rtr("games_ai.cross_server.node.unknown")
    manager = _manager_of()
    role = manager.mode if manager is not None else plugin_config.cross_server_mode
    identity = _load_identity(server)
    fingerprint = _identity_fingerprint(server) if identity is not None else None
    enrolled = (server.rtr('games_ai.cross_server.node.state_yes') if identity
                else server.rtr('games_ai.cross_server.node.state_no'))

    if manager is not None and manager.is_server and manager.hub is not None:
        # The hub itself never enrols: it owns the node table and hands the tokens out. What is
        # worth reporting here is the address it serves and how many nodes it knows / has online.
        hub = manager.hub
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.hub_status_line',
                                           role=role, name=manager.name,
                                           uri=manager.hub_uri or plugin_config.websocket_uri or unknown,
                                           nodes=len(hub.nodes), peers=len(hub.peers))}")
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.hub_hint')}")
        return

    if manager is not None and manager.is_client:
        # A client: who it dialled, whether it holds a token and how long the hub said it lasts.
        # Only the hub knows the remaining time, and it says so at the handshake; offline the
        # honest answer is "unknown", not a guess from a TTL we never saw.
        hub_label = manager.hub_name or plugin_config.websocket_uri or unknown
        remaining = manager.token_expires_in
        expires = (server.rtr("games_ai.cross_server.node.unlimited") if remaining is None
                   else _format_duration(remaining))
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.status_line',
                                           role=role, hub=hub_label, enrolled=enrolled,
                                           fingerprint=fingerprint or '-', expires=expires)}")
        if identity is None:
            source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.not_enrolled_hint')}")
        return

    # local mode: there is no link at all, so there is no hub to name -- the line drops that
    # field instead of filling it with "unknown", and the hint is about getting a link, not
    # about a token this instance may already hold.
    source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.local_status_line',
                                       role=role, enrolled=enrolled,
                                       fingerprint=fingerprint or '-')}")
    source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.local_enrolled_hint' if identity
                                       else 'games_ai.cross_server.node.local_hint')}")
    return


def forget(source: CommandSource):
    """`!!gamesai node forget` -- delete the identity file (change of hub, suspected leak)."""
    server = _server_of(source)
    if not require_permission(source):
        return
    path = _identity_path(server)
    removed = _delete_identity(server)
    if removed is None:
        source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.forget_none', path=path or '?')}")
        return
    source.reply(f"{plugin_config.prefix}{server.rtr('games_ai.cross_server.node.forget_ok', path=removed)}")
    server.logger.info(f"{plugin_config.prefix} Identity file {removed} deleted; the link stays down until "
                       f"!!gamesai node claim <token>")
    # The live session and the local loopback hub go with it: forgetting is deliberate, and
    # the instance must not keep talking to a hub it no longer holds a token for.
    _stop_link(server)
