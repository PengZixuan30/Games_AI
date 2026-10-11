# Generated from games_ai/commands/clear.py by tools/build_tool_stubs.py -- do not edit.
from mcdreforged.api.all import *
from ..core import logger as logger
from ..core.config import plugin_config as plugin_config
from ..core.permission import require_permission as require_permission
from typing import Callable

_conversations: Callable
_history_store_of: Callable
_username_of: Callable

def attach(*, conversations, history_store, username_of) -> None:
    """Bind the three things this module needs from the entry module.

    ``conversations`` returns the live ``all_chat_param`` mapping (the entry replaces values inside
    it, so the mapping itself is what must be read at call time), ``history_store`` returns the
    ``ChatHistoryStore`` or ``None``, and ``username_of`` is the entry's ``get_username``.
    """
def _drop_stored_history(username: str) -> bool:
    """Drop one stored conversation (``!!gamesai clear``); True when a row was there."""
def _drop_all_stored_histories() -> None:
    """Drop every stored conversation (``!!gamesai clearall``).

    The command is a cluster-class one, so every instance deletes the conversations of its own
    data folder: in a cluster the hub holds them, and the other instances have none to lose.
    """
def clear_history(source: CommandSource, context: dict):
    """``!!gamesai clear`` -- drop the caller's own conversation, memory and stored row."""
def clear_history_named(source: CommandSource, context: dict):
    """``!!gamesai clear <name>`` -- drop one player's conversation (config permission).

    The named form is a management action, so it is gated by the configured permission level
    (the bare ``!!gamesai clear`` only ever touches the caller's own history and is not).

    A round of that player may still be in flight, and it would otherwise write the history
    back when it ends: it is asked to stop first, the conversation is removed from memory and
    the stored row is deleted. ``_save_history`` refuses to store a conversation that is no
    longer the registered one, so the detached round cannot resurrect it either.
    """
def clear_history_all(source: CommandSource, context: dict): ...
