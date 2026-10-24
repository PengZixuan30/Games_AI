<div align="center">

# Architecture

English  |  [简体中文](../zh_cn/architecture.md)  |  [繁體中文](../zh_tw/architecture.md)

[Back to README](../../README.md)

</div>

The plugin is one Python package, `games_ai/`, whose modules are grouped by what they do. This page is the map: which package owns what, how the parts are allowed to depend on each other, and where a new module belongs.

## The shape of the package

```text
games_ai/
  __init__.py     entry: metadata, the MCDR lifecycle, the wiring, the !!ask pipeline
  requirements.txt
  core/           settings, logging, the dependency gate, permissions, storage
  commands/       the handlers behind !!data, !!gamesai config, !!aibot, !!gamesai clear, !!gamesai node
  cluster/        the cross-server link: role decision, hub, node client, remote command source
  ai/             the request path: conversations, provider client, context table, tools, skills
  bot/            the Mineflayer bot: process, controller, the embedded init.js
  update/         self-update and the 24 h round that drives it
  ui/             the in-game help texts
```

Every one of those directories also holds an `__init__.py`, the package's front door: it re-exports the modules and names that the rest of the plugin imports from that package, so the entry module never has to know which file a name lives in. A name whose module needs a third-party package is resolved on first use with `__getattr__` (so importing a package early stays free of third-party imports) and is declared a second time in an `if TYPE_CHECKING:` block — the part that never runs but is what an editor or a type checker reads, which is why `from .ai import ChatParam` still shows the real signature instead of `Any`.

The package root keeps one compatibility module beside the entry: `games_ai_tool.py` re-exports the tool registry under the path it had before the subpackages existed, because an existing `config/games_ai/tools/tools.py` and other plugins import it. It exists for code outside the plugin — no module here imports it — and new code uses `ai/games_ai_tool.py` (see [Tools](tools.md), and `tests/test_tool_compat.py` for the contract).

## What each package holds

|Path|What it holds|
|---|---|
|`core/`|`clock.py` (the clock the AI is told about: zone detection, timestamps, durations), `config.py` (the `plugin_config` singleton), `logger.py` (the logging bridge), `deps.py` (the dependency gate and the pip repair), `permission.py` (the one permission rule) and `database.py` (the public database and the chat-history store).|
|`commands/`|One module per command group: `data.py`, `settings.py`, `aibot.py`, `clear.py` and `node.py`. Each answers the caller; the entry state they need arrives through an `attach()` call.|
|`cluster/`|`cross_server.py` (the role decision and the manager), `websockets_server.py` (the hub), `websockets_client.py` (the node client and the handshake probe) and `ws_command.py` (the remote command source and the session registry).|
|`ai/`|`chat_param.py` (the conversation and the request pipeline), `openai_api.py` (the provider client), `context_table.py` with its generated `context_table_data.py`, `games_ai_tool.py` (the tool registry), `tools_interpreter.py`, `external_skills_loader.py` and `register_extra_plugin.py`; `tools_stub_files.py` seeds the user's tools folder (their `tools.py` skeleton and the generated `_stubs/` tree copied out beside it, see [Tools](tools.md)).|
|`bot/`|`mineflayer.py` (the Node process), `mineflayer_ai.py` (the autonomous controller) and `mineflayer_service_files.py` (the embedded `init.js`, `package.json` and their writers).|
|`update/`|`updater.py` (download, verify and replace this plugin's own file) and `update_round.py` (the 24 h check and the cluster-coordinated round).|
|`ui/`|`help.py`: the in-game help texts and their `send_help` builder.|

## How the parts depend on each other

- The entry module may import any package; **no package may import the entry module** -- `tests/test_layout.py` fails when one does.
- `core/` is the floor: every other package may import it, and it imports nothing but the standard library and MCDR.
- The dependency gate comes first: importing `games_ai` has to work with no third-party package installed. The entry module takes every name from the packages' front doors (`__init__.py`): a front door imports the names that need nothing but the standard library and MCDR eagerly and resolves the rest on first use (PEP 562), so importing a package early never drags a third-party package onto the pre-gate path.

## Where a new module goes

- Pick the package by the question the module answers, not by who calls it: cluster transport in `cluster/`, model-facing code in `ai/`, bot code in `bot/`, a handler a player can type in `commands/`, text a player reads in `ui/`, and anything every other part uses in `core/`.
- A module that imports a third-party package has to be imported behind the gate, so it may live anywhere except `core/`: `core/` stays importable on a machine where nothing is installed.
- Add the new file to `KNOWN_MODULES` in `tests/test_layout.py`, and if another part needs its names, add them to the package's `__init__.py` -- eagerly when the module needs nothing third-party, in `_LAZY_NAMES` when it does. That suite also checks that the import graph stays acyclic, that every front door's `__all__` resolves, that a front door's eager imports are pre-gate safe, that the entry module never reaches past the front doors, and that the pre-gate closure pulls nothing third-party.
- A module added, renamed or deleted also makes the shipped editor stubs stale: regenerate them with `python tools/build_tool_stubs.py` (it needs `stubgen` from `mypy`; the generated tree is committed, and `--check` verifies it without writing). `tests/test_tool_stubs.py` fails until the tree matches the source again.

## What the entry module keeps

- The MCDR metadata and lifecycle: `PLUGIN_METADATA`, `on_load`, `on_unload`, `on_server_startup` and the `_deps_*` repair path.
- The wiring: the configuration applied to `plugin_config`, the command tree, the start and stop of the cross-server link, the identity file, the bot stack, and the `attach()` calls that hand the entry's live state to the modules that need it.
- The `!!ask` pipeline itself (`ask_ai` and its dispatcher), which is the one command group still living in the entry module.
