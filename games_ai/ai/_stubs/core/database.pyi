# Generated from games_ai/core/database.py by tools/build_tool_stubs.py -- do not edit.
import sqlite3
from _typeshed import Incomplete

class PublicDatabase:
    """The ``!!data`` key/value table, through one long-lived SQLite connection.

    The connection is opened once (see :func:`open_public_database`) and reused for the whole
    plugin lifetime; every method runs under one re-entrant lock, so a multi-threaded caller
    (`!!data add` commands and AI tool calls run on separate threads) can never interleave a
    read-modify-write. :meth:`append` is the atomic operation for that pattern: two concurrent
    appends both land instead of the second overwriting the first.
    """
    db_path: Incomplete
    _lock: Incomplete
    _connection: sqlite3.Connection | None
    _cursor: sqlite3.Cursor | None
    def __init__(self, db_path: str) -> None: ...
    def _connect(self):
        """The one connection and its cursor (called under the lock; created on first use)."""
    def close(self) -> None:
        """Close the connection (plugin unload, or a data-path change on reload)."""
    def write_data(self, key: str, value: str): ...
    def delete_data(self, key: str): ...
    def read_data(self, key: str) -> str | None: ...
    def append(self, key: str, value: str) -> str:
        """Read, concatenate and write one key atomically; returns the new value."""
    def data_list(self) -> list[tuple[str, str]]: ...
    def get_all_key(self) -> list[str]: ...

_public_lock: Incomplete
_public_db: PublicDatabase | None
_public_db_path: str | None

def open_public_database(path: str) -> PublicDatabase:
    """Open (or re-open, when the path changed) the one public database of this plugin load."""
def public_database() -> PublicDatabase:
    """The open public database (``open_public_database`` must have run)."""
def close_public_database() -> None:
    """Close and drop the singleton (plugin unload)."""

class ChatHistoryStore:
    """Every stored conversation, one row per user, in its own table of the public database file.

    Kept in the same SQLite file as ``public_data`` rather than in a file of its own: it is
    ``config/games_ai/database/public_database.db`` either way, but a **different table**, so
    ``!!data`` and the conversations never touch each other's rows. One row holds the whole
    conversation -- the message list, the pending queue and the lifetime token counters -- as
    JSON, which makes every write a single UPSERT and every read a single SELECT.

    MCDR never deletes a plugin's data folder (not on unload, reload, update or plugin removal),
    so a conversation stored here survives all of them. Deleting that database file is the one
    way to lose both ``!!data`` and every conversation.
    """
    db_path: Incomplete
    def __init__(self, db_path: str) -> None: ...
    def _connect(self): ...
    def save(self, user: str, format_version: int, model_id: str | None, saved_at: int, rounds_since_time: int, payload: str) -> None:
        """Create or overwrite the row of one user (one statement, so a row is never half written)."""
    def load_all(self) -> list[dict]:
        """Every stored conversation, newest first is not needed: the payload decides everything."""
    def delete(self, user: str) -> int:
        """Delete one conversation; returns how many rows were removed (0 or 1)."""
    def delete_all(self) -> None: ...
