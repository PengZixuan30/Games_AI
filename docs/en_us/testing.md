<div align="center">

# Testing

English  |  [简体中文](../zh_cn/testing.md)  |  [繁體中文](../zh_tw/testing.md)

[Back to README](../../README.md)

</div>

GamesAI keeps its whole verification suite in the repository: pytest is the runner, and every change is checked against it. The modules under `tests/` bring the peers, hubs, nodes and databases they talk to up themselves, so a run needs no Minecraft server, no MCDR instance, no API key and no internet access.

## Installing pytest

The suite runs on the interpreter that runs the plugin (Python 3.12 or newer). Install pytest into that interpreter:

```bash
python -m pip install pytest
```

The suites also import the plugin itself, so its runtime dependencies have to be importable from the same interpreter: `mcdreforged`, `websockets`, `openai` and `requests`. A machine that already runs the plugin has all four.

## Running the suite

Run pytest from the repository root. `pytest.ini` sets `testpaths = tests` and puts the repository and `tests/` on `sys.path`, so a module can `import games_ai` and `_helpers` by name and no suite carries path arithmetic of its own:

```bash
python -m pytest
```

One module is enough while working on a single area:

```bash
python -m pytest tests/test_layout.py
```

`-k` selects tests by name and matches any part of a test id:

```bash
python -m pytest -k clear
```

The documentation checkers can be run on their own:

```bash
python -m pytest tests/docs
```

> [!TIP]
> `python -m pytest --collect-only -q` lists what a run would collect without executing anything, and `-p no:cacheprovider` keeps pytest from writing its `.pytest_cache/` folder into the checkout.

## What the folders hold

|Path|What it holds|
|---|---|
|`pytest.ini`|The pytest settings: `testpaths = tests` makes a bare `python -m pytest` collect this folder, and `pythonpath = . tests` puts the repository and `tests/` on `sys.path`.|
|`tests/conftest.py`|The fixtures every suite shares: the `free_port` factory for the suites that start a hub, a node or a prototype peer, the quiet logging default, and the session-wide guard that keeps the plugin's repository-relative paths (`skills_path`, `data_path`) inside a temporary folder.|
|`tests/test_*.py`|The test modules: wire protocol and frames, enrolment and tokens, routing, the AI request pipeline, the update round, and the layout of the repository itself.|
|`tests/_helpers/`|The shared helpers -- `paths.py` (checkout paths), `pkg.py` (the plugin's source as text) and `wait.py` (polling instead of sleeping) -- plus the three protocol prototypes `ws_async.py`, `ws_sync_hub.py` and `ws_sync_node.py`.|
|`tests/docs/`|The documentation checkers: encoding and line endings, trilingual structure parity, README parity and hygiene, and the README's JSON blocks.|
|`tests/js/`|The Node.js side of the bot test: a vendored copy of the `ws` module, which `test_bot_js.py` copies next to the harness it builds in a temporary folder.|

## What a run needs

- Python 3.12 or newer on `PATH` (`python --version`), the same floor the plugin declares.
- pytest in that interpreter (`python -m pytest --version`).
- The plugin's runtime dependencies importable from it: `mcdreforged`, `websockets`, `openai` and `requests`.
- Node.js on `PATH` for the JavaScript bot test only: `tests/test_bot_js.py` starts a real `node` process, every other module runs without it.
- Free local TCP ports: the suites that start a hub or a node ask the operating system for one on `127.0.0.1`.

## What a run does not need

- No Minecraft server and no running MCDR instance: the peers are started in-process.
- No API key and no AI provider: the request chain is driven against stubs, so nothing leaves the machine.
- No Minecraft account: the bot test stubs the Minecraft side and only speaks the hub protocol from JavaScript.
- No internet access: nothing in the suite downloads anything, and its dependencies are installed or vendored (the `ws` module under `tests/js/`) before the run. The plugin's own background refresh -- the context-window table and the update check -- can still attempt a request inside the suites that start the cross-server link; offline it fails, is logged and changes nothing, and no test depends on it.

## Nothing is written into the checkout

The suites keep their state out of the repository:

- Plugin configuration, databases, node tables and cache files are created under the operating system's temporary directory (or pytest's own `tmp_path`), so a finished run leaves no test data behind.
- The vendored `ws` module under `tests/js/node_modules/` belongs to the checkout and is only read.
- Python's `__pycache__/` folders are the only trace a run leaves; `-p no:cacheprovider` also keeps pytest's `.pytest_cache/` out of the checkout.
