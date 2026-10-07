"""Fixtures the whole pytest suite shares.

The suites in this folder used to be stand-alone scripts: each one carried its own ``check()``
counter, its own path arithmetic, its own ``free_port()`` and its own summary line, and
``_run_suites.py`` started them one by one and parsed ``N / N checks passed`` out of their output.
pytest is the runner now, so what every one of them needed lives here once:

* the checkout paths -- imported from :mod:`_helpers.paths` rather than requested as a fixture,
  because helper modules need them too,
* a free TCP port for the suites that bring a hub, a node or one of the prototype peers up,
* quiet logging, because these suites talk to themselves on purpose and log every frame,
* one session-wide guard that keeps the checkout out of reach (see
  :func:`keep_the_checkout_clean`) -- the only place here that touches the plugin, and it does so
  through a local import so that importing this file stays free of the plugin's dependency gate.

A fixture that reaches into ``games_ai`` for a *suite's* needs would make every suite depend on
that reach; suites decide for themselves what they load.
"""
import logging
import socket

import pytest

# Suites that exercise the wire protocol log every frame at DEBUG level; keep that out of the
# report. A suite that wants its own logging sets it up itself.
logging.basicConfig(level=logging.CRITICAL)


@pytest.fixture
def free_port():
    """A factory for ports nothing is listening on: ``port = free_port()``.

    Binding port 0 and reading the port back is the portable way to get one; the socket is closed
    immediately, so a suite still has to tolerate the microscopic race against another process.
    """
    def _free_port():
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        return port

    return _free_port


@pytest.fixture(scope="session", autouse=True)
def keep_the_checkout_clean(tmp_path_factory):
    """Point the plugin's repository-relative paths at a scratch folder for the whole session.

    ``plugin_config.skills_path`` defaults to ``config/games_ai/skills/skills.json`` and
    ``data_path`` to ``config/games_ai/database/public_database.db`` -- relative paths, so they
    resolve inside the checkout whenever pytest runs from the repository root. Anything that
    derives a folder from them writes into the developer's real ``config/``: the context-window
    cache (``config/games_ai/cache/context_windows.json``), the plugin's ``config.json``, the
    public database, the prompt folder.

    Patch-per-test is not enough. ``_start_cross_server`` starts a 24 h update loop on a daemon
    thread; that thread can outlive the test that started it and refresh the window table *after*
    ``monkeypatch`` was undone, which lands the write back in the checkout. Rebinding the two
    paths for the whole session takes the checkout out of reach for every suite, however it is
    torn down.

    A suite that wants its own paths still patches them itself; this is only the default.
    """
    from games_ai.config import plugin_config  # local: this file stays importable on its own

    scratch = tmp_path_factory.mktemp("checkout") / "config" / "games_ai"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(plugin_config, "skills_path",
                      str(scratch / "skills" / "skills.json"), raising=False)
        patch.setattr(plugin_config, "data_path",
                      str(scratch / "database" / "public_database.db"), raising=False)
        yield
