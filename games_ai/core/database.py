import sqlite3
import threading


class PublicDatabase:
    """The ``!!data`` key/value table, through one long-lived SQLite connection.

    The connection is opened once (see :func:`open_public_database`) and reused for the whole
    plugin lifetime; every method runs under one re-entrant lock, so a multi-threaded caller
    (`!!data add` commands and AI tool calls run on separate threads) can never interleave a
    read-modify-write. :meth:`append` is the atomic operation for that pattern: two concurrent
    appends both land instead of the second overwriting the first.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None
        self._cursor: sqlite3.Cursor | None = None

    def _connect(self):
        """The one connection and its cursor (called under the lock; created on first use)."""
        if self._connection is None:
            # check_same_thread=False: the calls are serialised by `_lock`, not by one thread.
            self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self._cursor = self._connection.cursor()
            self._cursor.execute('''
                CREATE TABLE IF NOT EXISTS public_data(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL UNIQUE,
                    value TEXT NOT NULL
                )
            ''')
            self._connection.commit()
        return self._connection, self._cursor

    def close(self) -> None:
        """Close the connection (plugin unload, or a data-path change on reload)."""
        with self._lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                except sqlite3.Error:
                    pass
            self._connection = None
            self._cursor = None

    def write_data(self, key: str, value: str):
        with self._lock:
            conn, cursor = self._connect()
            cursor.execute("INSERT OR REPLACE INTO public_data (key, value) VALUES (?, ?)", (key, value))
            conn.commit()

    def delete_data(self, key: str):
        with self._lock:
            conn, cursor = self._connect()
            cursor.execute("DELETE FROM public_data WHERE key = ?", (key,))
            conn.commit()

    def read_data(self, key: str) -> str | None:
        with self._lock:
            _conn, cursor = self._connect()
            cursor.execute("SELECT value FROM public_data WHERE key = ?", (key,))
            result = cursor.fetchone()
        return result[0] if result else None

    def append(self, key: str, value: str) -> str:
        """Read, concatenate and write one key atomically; returns the new value."""
        with self._lock:
            conn, cursor = self._connect()
            cursor.execute("SELECT value FROM public_data WHERE key = ?", (key,))
            row = cursor.fetchone()
            new_value = str(value) if row is None else str(row[0]) + str(value)
            cursor.execute("INSERT OR REPLACE INTO public_data (key, value) VALUES (?, ?)",
                           (key, new_value))
            conn.commit()
            return new_value

    def data_list(self) -> list[tuple[str, str]]:
        with self._lock:
            _conn, cursor = self._connect()
            cursor.execute("SELECT key, value FROM public_data")
            return cursor.fetchall()

    def get_all_key(self) -> list[str]:
        with self._lock:
            _conn, cursor = self._connect()
            cursor.execute("SELECT key FROM public_data")
            return [row[0] for row in cursor.fetchall()]


# ── the plugin-lifetime singleton ─────────────────────────────────────────────
_public_lock = threading.RLock()
_public_db: PublicDatabase | None = None
_public_db_path: str | None = None


def open_public_database(path: str) -> PublicDatabase:
    """Open (or re-open, when the path changed) the one public database of this plugin load."""
    global _public_db, _public_db_path
    with _public_lock:
        if _public_db is not None and _public_db_path == path:
            return _public_db
        if _public_db is not None:
            _public_db.close()
        _public_db = PublicDatabase(path)
        _public_db_path = path
        _public_db._connect()          # fail at load, not on the first command
        return _public_db


def public_database() -> PublicDatabase:
    """The open public database (``open_public_database`` must have run)."""
    with _public_lock:
        if _public_db is None:
            raise RuntimeError("the public database is not open (open_public_database first)")
        return _public_db


def close_public_database() -> None:
    """Close and drop the singleton (plugin unload)."""
    global _public_db, _public_db_path
    with _public_lock:
        if _public_db is not None:
            _public_db.close()
        _public_db = None
        _public_db_path = None


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

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_history(
                user TEXT PRIMARY KEY,
                format INTEGER NOT NULL,
                model_id TEXT,
                saved_at INTEGER NOT NULL,
                rounds_since_time INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL
            )
        ''')
        conn.commit()
        return conn, cursor

    def save(self, user: str, format_version: int, model_id: str | None, saved_at: int,
             rounds_since_time: int, payload: str) -> None:
        """Create or overwrite the row of one user (one statement, so a row is never half written)."""
        conn, cursor = self._connect()
        cursor.execute(
            "INSERT OR REPLACE INTO chat_history "
            "(user, format, model_id, saved_at, rounds_since_time, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (str(user), int(format_version), model_id, int(saved_at), int(rounds_since_time),
             str(payload)),
        )
        conn.commit()
        conn.close()

    def load_all(self) -> list[dict]:
        """Every stored conversation, newest first is not needed: the payload decides everything."""
        conn, cursor = self._connect()
        cursor.execute(
            "SELECT user, format, model_id, saved_at, rounds_since_time, payload FROM chat_history"
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "user": row[0],
                "format": row[1],
                "model_id": row[2],
                "saved_at": row[3],
                "rounds_since_time": row[4],
                "payload": row[5],
            }
            for row in rows
        ]

    def delete(self, user: str) -> int:
        """Delete one conversation; returns how many rows were removed (0 or 1)."""
        conn, cursor = self._connect()
        cursor.execute("DELETE FROM chat_history WHERE user = ?", (str(user),))
        removed = cursor.rowcount
        conn.commit()
        conn.close()
        return max(0, int(removed))

    def delete_all(self) -> None:
        conn, cursor = self._connect()
        cursor.execute("DELETE FROM chat_history")
        conn.commit()
        conn.close()
