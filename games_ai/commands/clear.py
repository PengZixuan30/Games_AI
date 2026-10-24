"""``!!gamesai clear`` / ``clear <name>`` / ``clearall`` -- drop conversations.

Dropping a conversation means three things: the live object in the entry module's
``all_chat_param``, the stored row, and -- for the named form -- a round that is still in flight,
which is asked to stop first so it cannot write the history back. The live map and the store stay
in the entry module, so they arrive through :func:`attach`.
"""
from typing import Callable

from mcdreforged.api.all import *

from ..core import logger
from ..core.config import plugin_config
from ..core.permission import require_permission

#: The entry module's live conversations, its history store and its "who typed this" helper.
#: See :func:`attach`; every callable is read at use time, never cached.
_conversations: Callable = lambda: {}
_history_store_of: Callable = lambda: None
_username_of: Callable = lambda source: ""


def attach(*, conversations, history_store, username_of) -> None:
    """Bind the three things this module needs from the entry module.

    ``conversations`` returns the live ``all_chat_param`` mapping (the entry replaces values inside
    it, so the mapping itself is what must be read at call time), ``history_store`` returns the
    ``ChatHistoryStore`` or ``None``, and ``username_of`` is the entry's ``get_username``.
    """
    global _conversations, _history_store_of, _username_of
    _conversations = conversations
    _history_store_of = history_store
    _username_of = username_of


def _drop_stored_history(username: str) -> bool:
    """Drop one stored conversation (``!!gamesai clear``); True when a row was there."""
    store = _history_store_of()
    if store is None:
        return False
    try:
        return bool(store.delete(username))
    except Exception as e:
        logger.log("exception", f"{plugin_config.prefix}Failed to delete the stored conversation of {username!r}: {e}")
        return False


def _drop_all_stored_histories() -> None:
    """Drop every stored conversation (``!!gamesai clearall``).

    The command is a cluster-class one, so every instance deletes the conversations of its own
    data folder: in a cluster the hub holds them, and the other instances have none to lose.
    """
    store = _history_store_of()
    if store is None:
        return
    try:
        store.delete_all()
    except Exception as e:
        logger.log("exception", f"{plugin_config.prefix}Failed to delete the stored conversations: {e}")


def clear_history(source: CommandSource,context: dict):
    """``!!gamesai clear`` -- drop the caller's own conversation, memory and stored row."""
    server = source.get_server()
    username = _username_of(source)
    had_object = _conversations().pop(username, None) is not None
    # Also drops a row that could not be restored at load (a removed model, for instance):
    # whoever owns the conversation must be able to wipe it even when it is not in memory.
    removed = _drop_stored_history(username)
    key = "success" if (had_object or removed) else "no_history"
    source.reply(f'{plugin_config.prefix}{server.rtr("games_ai.clear_history_message." + key, username=username)}')

def clear_history_named(source: CommandSource, context: dict):
    """``!!gamesai clear <name>`` -- drop one player's conversation (config permission).

    The named form is a management action, so it is gated by the configured permission level
    (the bare ``!!gamesai clear`` only ever touches the caller's own history and is not).

    A round of that player may still be in flight, and it would otherwise write the history
    back when it ends: it is asked to stop first, the conversation is removed from memory and
    the stored row is deleted. ``_save_history`` refuses to store a conversation that is no
    longer the registered one, so the detached round cannot resurrect it either.
    """
    server = source.get_server()
    if not require_permission(source):
        return
    target = str(context.get("name") or "").strip()
    if not target:
        source.reply(f'{plugin_config.prefix}{server.rtr("games_ai.clear_history_message.name_required")}')
        return

    existing = _conversations().get(target)
    stopped = existing is not None and existing.request_stop()
    _conversations().pop(target, None)
    removed = _drop_stored_history(target)

    if existing is None and not removed:
        source.reply(f'{plugin_config.prefix}{server.rtr("games_ai.clear_history_message.no_history_other",username=target)}')
        return
    key = "success_other_stopped" if stopped else "success_other"
    source.reply(f'{plugin_config.prefix}{server.rtr("games_ai.clear_history_message." + key, username=target)}')

def clear_history_all(source: CommandSource,context: dict):
    server = source.get_server()
    if not require_permission(source):
        return
    count = len(_conversations())
    _conversations().clear()
    _drop_all_stored_histories()
    source.reply(f'{plugin_config.prefix}{server.rtr("games_ai.clear_history_message.clearall_success",count=count)}')
