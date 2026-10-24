"""The public database: one locked connection per plugin load, atomic ``append``.

Every call used to open a fresh SQLite connection; ``ai_add_data``/``!!data add`` read a value and
wrote it back in two separate calls, so two concurrent appends could silently lose one. The plugin
now keeps one connection guarded by a re-entrant lock and an atomic ``append``.
"""
import threading

import pytest

from games_ai.core import database
from games_ai.core.database import PublicDatabase


@pytest.fixture(autouse=True)
def clean_singleton():
    database.close_public_database()
    yield
    database.close_public_database()


def test_the_plugin_uses_one_connection_for_the_whole_load(tmp_path):
    path = str(tmp_path / "public.db")
    first = database.open_public_database(path)
    second = database.open_public_database(path)
    assert first is second and database.public_database() is first
    first.write_data("k", "v")
    assert first.read_data("k") == "v"
    assert second._connection is not None and second._connection is first._connection


def test_two_concurrent_appends_both_land(tmp_path):
    path = str(tmp_path / "public.db")
    db = database.open_public_database(path)
    db.write_data("key", "")
    barrier = threading.Barrier(8)

    def append(letter):
        barrier.wait()
        for _ in range(50):
            db.append("key", letter)

    threads = [threading.Thread(target=append, args=(chr(65 + index),)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    value = db.read_data("key") or ""
    assert len(value) == 8 * 50, "no append was lost"
    assert sorted(value) == sorted("".join(chr(65 + index) * 50 for index in range(8)))


def test_closing_and_reopening_another_path_replaces_the_connection(tmp_path):
    first = database.open_public_database(str(tmp_path / "one.db"))
    second = database.open_public_database(str(tmp_path / "two.db"))
    assert second is not first and first._connection is None, "the previous connection is closed"
    assert database.public_database() is second


def test_a_closed_singleton_is_a_clear_runtime_error(tmp_path):
    database.open_public_database(str(tmp_path / "public.db"))
    database.close_public_database()
    with pytest.raises(RuntimeError):
        database.public_database()


def test_direct_instances_still_work_for_isolated_files(tmp_path):
    path = str(tmp_path / "direct.db")
    standalone = PublicDatabase(path)
    standalone.write_data("k", "v1")
    standalone.append("k", "+v2")
    assert standalone.read_data("k") == "v1+v2"
    assert standalone.data_list() == [("k", "v1+v2")]
    assert standalone.get_all_key() == ["k"]
    standalone.close()
