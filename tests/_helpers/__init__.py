"""What the suites share: checkout paths, package source reading, polling and the prototype peers.

Nothing in this folder is collected by pytest -- the file names do not start with ``test_``. The
modules are imported by the suites (``from _helpers.paths import PKG``) or, for the WebSocket
prototypes, imported as the reference implementation of the wire protocol the plugin speaks
(``from _helpers.ws_sync_hub import CrossServerHub``).

``tests/`` is on ``sys.path`` (see ``pythonpath`` in the repository's ``pytest.ini``), which is why
``_helpers`` is importable by that name from any test module.
"""
