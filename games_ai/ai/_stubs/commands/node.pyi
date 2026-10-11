# Generated from games_ai/commands/node.py by tools/build_tool_stubs.py -- do not edit.
from ..cluster.websockets_client import PROBE_GAMES_AI as PROBE_GAMES_AI, PROBE_UNREACHABLE as PROBE_UNREACHABLE, probe_hub_detail as probe_hub_detail, token_fingerprint as token_fingerprint
from ..core import logger as logger
from ..core.config import plugin_config as plugin_config
from ..core.permission import require_permission as require_permission
from mcdreforged.api.command import CommandContext as CommandContext
from mcdreforged.command.command_source import CommandSource as CommandSource
from typing import Callable

_server_of: Callable
_manager_of: Callable
_restart_link: Callable
_stop_link: Callable
_store_bot_token: Callable
_identity_path: Callable
_load_identity: Callable
_save_identity: Callable
_delete_identity: Callable
_identity_fingerprint: Callable

def attach(*, server_of, manager_of, restart_link, stop_link, store_bot_token, identity_path, load_identity, save_identity, delete_identity, identity_fingerprint) -> None:
    """Bind this module to the plugin instance that owns the live state.

    Every callable is read at *use* time -- never cached at attach time -- so a manager that
    :func:`claim` replaced, or a server a later load set, is the one the next command sees. The
    identity-file helpers and the bot-token writer stay in the entry module because the
    cross-server link uses them too; they are handed in rather than imported, because no module
    may import the entry package.
    """
def _source_name(source: CommandSource) -> str:
    """How a command source is recorded in the node table's ``issued_by``."""
def _hub(source: CommandSource):
    """The hub of this cluster, when this instance really is one.

    A local-mode instance also hosts a loopback hub for the bot, but it has no cluster node
    table to speak of, so the hub-side commands refuse to run there.
    """
def _sync_local_bot_token(server, name: str, token: str) -> None:
    """Keep the local bot's config in step when its token is (re)issued on this machine.

    The bot cannot type ``!!gamesai node claim``; without this, rotating its token would
    strand it until somebody edited the JS config by hand, which is exactly the human step
    the bot provisioning is supposed to avoid.
    """
def _format_duration(seconds: float) -> str:
    """A compact duration: 3d 4h / 5h 12m / 12m 30s / 30s (used for ages and for TTLs)."""
def _format_timestamp(epoch) -> str | None:
    """An epoch second as local time, or None when it was never recorded."""
def pending(source: CommandSource):
    """`!!gamesai node pending` -- who asked to enrol and is still waiting."""
def issue_token(source: CommandSource, context: CommandContext):
    """`!!gamesai node token <name>` -- issue the one token that name is waiting for.

    Strict on purpose: a node that never asked to enrol does not get a token (use
    `node rotate` for one that is already enrolled, `node pending` to see who is waiting), and
    a name that is *already* enrolled is refused instead of being taken over: the hub keys its
    node table by name, so issuing a second token for it would silently drop the first node's
    hash and that node would fail every connect with 4001. Two instances with the same name is
    the usual reason (see the entry's ``_default_instance_name``), and the refusal says so.
    """
def list_nodes(source: CommandSource):
    """`!!gamesai node list` -- every enrolled node, without any usable secret."""
def revoke(source: CommandSource, context: CommandContext):
    """`!!gamesai node revoke <name>` -- drop the entry; the node's next connect is 4001."""
def rotate(source: CommandSource, context: CommandContext):
    """`!!gamesai node rotate <name>` -- a fresh token for an enrolled node, printed once."""
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
def status(source: CommandSource):
    '''`!!gamesai node status` -- the role, the enrolment and, on a hub, the cluster size.

    The answer follows what this instance really is, because no single sentence is true for all
    three roles. A hub that is told "not enrolled, go claim a token" is sent to do something it
    never does -- it is the one that *issues* those tokens -- and printing its own name in the
    ``hub:`` field reads as if it had dialled itself.
    '''
def forget(source: CommandSource):
    """`!!gamesai node forget` -- delete the identity file (change of hub, suspected leak)."""
