# Generated from games_ai/core/database.py by tools/build_tool_stubs.py -- do not edit.
from _typeshed import Incomplete

class PublicDatabase:
    db_path: Incomplete
    def __init__(self, db_path: str) -> None: ...
    def _connect(self): ...
    def write_data(self, key: str, value: str): ...
    def delete_data(self, key: str): ...
    def read_data(self, key: str) -> str | None: ...
    def data_list(self) -> list[tuple[str, str]]: ...
    def get_all_key(self) -> list[str]: ...

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
