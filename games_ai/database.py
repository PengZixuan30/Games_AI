import sqlite3

class PublicDatabase:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS public_data(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL UNIQUE,
                value TEXT NOT NULL
            )
        ''')
        conn.commit()
        return conn, cursor

    def write_data(self, key: str, value: str):
        conn, cursor = self._connect()
        cursor.execute("INSERT OR REPLACE INTO public_data (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()

    def delete_data(self, key: str):
        conn, cursor = self._connect()
        cursor.execute("DELETE FROM public_data WHERE key = ?", (key,))
        conn.commit()
        conn.close()

    def read_data(self, key: str) -> str | None:
        conn, cursor = self._connect()
        cursor.execute("SELECT value FROM public_data WHERE key = ?", (key,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    
    def data_list(self) -> list[tuple[str, str]]:
        conn, cursor = self._connect()
        cursor.execute("SELECT key, value FROM public_data")
        result = cursor.fetchall()
        conn.close()
        return result
    