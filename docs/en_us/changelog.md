<div align="center">

# What's New

English  |  [简体中文](../zh_cn/changelog.md)  |  [繁體中文](../zh_tw/changelog.md)

[Back to README](../../README.md)

</div>

## Version 0.8.0

- **Errors are readable without debug mode**: a failed request now logs one WARNING line with the status code, its localized meaning and the provider's request ID (it used to be a DEBUG line), and the player's reply spells the meaning out for a provider status other than a wrong key or a rate limit (for example `HTTP 402 (Insufficient API Key balance)`); 401 and 429 keep their own sentences, which name the cause.
- **Conversations are stored**: every `ChatParam` is written into a `chat_history` table of `config/games_ai/database/public_database.db` after every finished round and restored on every plugin load, so a reload, an update, a restart or removing the plugin no longer loses anybody's conversation. It is the same database file as `!!data` (a separate table), and in a cluster the store belongs to the hub; deleting that file deletes both. The numbers `!!ask context` shows are stored with the conversation too -- the last request's usage, this round's counters and the last compression -- so they are back after a reload; only the held-context estimate is recomputed from the restored history at load, because the tool schemas belong to the next request.
- **A message for another user's assistant**: the new `send_message_to_player_ai` tool lets a user's assistant hand one message to anyone else's conversation. It is one-way (the recipient reads it at their next question; nothing wakes them up) and open to everyone: the only requirement is that the recipient already has a conversation -- no permission level is compared or looked up, on either side, so a delivery can never add a name to `permission.yml`. The server console's own conversation is a valid target too (its key is `Server Control Panel`).
- **`!!ask stop` keeps what the round wrote**: stopping a round no longer deletes the step it interrupted. The question, the injected notes (time, skill) and every tool call that came back keep their place in the history and in the stored conversation; only a trailing tool call whose result never arrived is dropped (an incomplete batch goes as a whole, because a provider rejects a `tool_calls` message without its results). Queued `!!ask -f` messages are no longer discarded either -- the next round merges them as usual.
- **One player's history can be cleared by name**: the new `!!gamesai clear <name>` deletes another player's conversation -- memory and stored row -- and needs the configured `permission` (the bare `!!gamesai clear`, which only ever touches your own history, still needs no level). A round that player still has in flight is stopped first, and a conversation that is no longer the registered one is never stored again, so the clear cannot be undone by the round it interrupted.
- **Tool scope**: a new `execute_in_hub` registration flag (default `false`). Every cross-server request uploads the schemas the asking instance can run locally, so the hub decides which calls run here and which are routed back, and the model is never offered a tool neither side has. Permission is re-decided by the origin from its own `permission.yml`; a routed call is never retried, and a timeout is reported honestly as an unknown outcome.
- **Role memory and grace period**: the decided role is written to `config/games_ai/cross_server/role.json`, so an instance that was a client waits for its hub (15 seconds by default) instead of racing it for the port. An address this machine cannot bind is never made a hub, a hub reloading itself still decides immediately, and an instance **without an identity** still takes over when its hub never comes back.
- **The link's runtime state lives in one folder**: the node's token (`identity.json`), the hub's node table (`nodes.json`) and the role memory (`role.json`) live in `config/games_ai/cross_server/`.
- **The plugin updates itself**: `!!MCDR plugin install` is no longer used. A new release is downloaded from the plugin's own GitHub release (`https://ghfast.top/<url>` as the second source) and accepted only when the announced size, the sha256 **and** the plugin id and version inside the archive all match; installing it means unloading the plugin, deleting the old file, moving the verified one in and loading it again -- with a `.bak` copy restored and loaded if the new file does not come up. Every failure ends the round and says why; there is deliberately no fallback to MCDR's installer.
- **Cluster updates run nodes first, hub last**: the hub orders every online node, blocks until each one is staged **and** has reconnected announcing the new version, and only then replaces its own file. A node decides its cross-server role once per plugin load, so this order is what stops a node that loaded while the hub was down from taking the hub port. An enrolled instance never takes the hub role (`!!gamesai node forget` is the way back if the hub is gone for good), a cross-server client never runs the update check at all, and `!!gamesai check` is a hub-side command that starts and coordinates the round.
- **The plugin installs its own Python packages**: a start where `openai`, `requests` or `websockets` is missing no longer leaves an idle or unloadable plugin. It reports what is missing, installs the packages with pip -- the machine's own pip configuration first, the Aliyun PyPI mirror as a second attempt, every pip line written to the log -- and reloads itself once they import. `requirements.txt` therefore moved from the plugin root into the package: MCDR refuses to load a plugin whose root `requirements.txt` is unsatisfied, which would leave the plugin no chance to repair itself.

- **A queued question gets one merged answer**: an `!!ask` typed while that conversation is already answering no longer starts a second round. The conversation has one atomic round owner (a lock plus an `active` flag, not only the `is_stopped` event); the waiting player gets the usual "thinking" line immediately, and when the round ends the queued questions are sent in arrival order as **one merged follow-up round** whose answer streams to the round owner. `!!ask stop` keeps queued questions and they are sent afterwards; the server-change note is written before a round starts (never inside a tool-call group), and an exception while setting a round up is logged and answered instead of leaving the conversation stuck as "running".
- **Skill tools stay inside the skills folder**: `write_skills`/`modify_skills`/`delete_skills`/`read_skills` reject absolute paths, `..` traversal and nested names -- the model gets an error instead of a file outside `skills/` being read, overwritten or deleted.
- **A reload cannot push an AI round onto the cluster**: the cluster fan-out only broadcasts the command the source actually typed, the reload tool invokes `!!gamesai reload` without the AI round's command source, and a node refuses a broadcast `!!ask` outright. Session ids are unique per instance, so one instance's reply can no longer be delivered to another instance's local player.
- **Unknown remote players stay unknown**: the cross-server permission lookup goes through MCDR's permission manager with `auto_add=False`, so a name this instance never saw is level 0 and a routed command no longer rewrites `permission.yml`.
- **One locked public database**: `!!data` and the AI tools share one SQLite connection with an atomic append, so two concurrent `add`s both land; the connection is closed on unload and reopened when the data path changes.
- **A bad reload input no longer keeps the plugin from loading**: a corrupt or non-list `skills.json` is logged and treated as "no skills"; a conversation whose model was removed from the config keeps its previous client and logs a warning instead of aborting the reload (conversations mid-round are skipped by it).
- **Bot start/stop follows the real process**: a bot whose config says enabled but whose process is dead is restarted (forced reload), disabling cancels a launch that is still waiting for the server, and a launch aborted during `run_node` kills the process it just created before a controller can start.
- **A failing bot action no longer kills the bot**: an exception inside the embedded `init.js` action switch is answered as an error frame (the process keeps running), and a failed `goto` always clears the pathfinder goal instead of leaving the bot walking.
- **Update round honesty**: an ack timeout is recorded as a correctable `timeout` (the node may report `staged` a moment later) instead of `failed`, a peer that did not announce a version is ordered rather than compared against an empty string, and a rollback only claims success after the restored archive is byte-verified against the backup.
- **Context compression no longer blocks command handling**: the summarizing request runs outside the context lock (a read-only `!!ask context` no longer waits up to a minute on the MCDR command thread), and a message appended while a summary is generated is never lost (the replacement is skipped and retried by the next preflight).
- **`setting_timer` refuses unbounded waits by default**: a duration over 600 seconds is refused with a retry hint unless the model explicitly passes `allow_long_wait=true`.
- **An extension unload is no longer reported as "not found" when MCDR queued it**: `on_unload` runs inside MCDR's plugin-manipulation chain, so unloading another plugin from there is queued rather than executed, and `ServerInterface.unload_plugin` answers `None` for both "queued" and "plugin not found". The log now asks whether MCDR still has a loaded instance: a queued unload says so at INFO, and only a plugin that is really gone is reported as not found and dropped from the unload list.
- **`!!ask context --all` reports per configured AI, not per upstream model**: two `all_ai` entries pointing at the same `ai_model` used to be merged into one row (named after whichever conversation was read first), so the command claimed "1 model" although players were spread over two assistants. The row is now the configured entry (named by `ai_name`), while the hover names the `all_ai` id and the upstream `ai_model` the provider actually bills. A conversation whose numbers cannot be read is logged and skipped instead of silently disappearing from the totals.
- **A colored `ai_name` no longer makes the rest of a `!!ask context --all` row white**: `ai_name` may contain `§` formatting codes (the configuration documents that), and inside the gray model row they overrode the row color while a `§r` left everything after the name at the default white. The row now resets and re-asserts gray right after the name, so the configured name keeps its own colors and the player/usage/round numbers are gray again.

This release is about **cross-server linking**: several MCDR instances can form one cluster that shares a single AI, one conversation history and one public database.

### 🌐 Cross-server linking

- **The role is decided automatically**: on load the plugin probes `websocket.uri`. If it answers and confirms it is GamesAI, this instance joins as a **client**; if nothing answers and the port is free, this instance **listens** and becomes the hub; `force_server` insists on the hub role (and falls back to local mode with an error when the port is taken).
- **Something else on that address means hands off**: when the uri is owned by a non-GamesAI service, cross-server stays disabled entirely (no client, no server) and every local feature keeps working.
- **Mutual identification**: both `hello` and `hello_ack` carry `"app": "games_ai"` and a protocol version, and a mismatch is refused with a dedicated close code. The startup probe marks itself `"probe": true` and is answered **without being registered**, so it neither pollutes the online list nor risks a name takeover.
- **One token per node**: a new instance is listed by `!!gamesai node pending` on the hub, issued with `node token <name>` (waiting names only), and joins by running `node claim <token>` on its own machine; the hub stores a `sha256` hash only and the plaintext appears once, in the reply. The close codes `683` (enrolment required) and `683` (token expired) are not retryable; validity comes from the hub's `websocket.token_ttl_hours` (default `-1` = unlimited) and is checked only during the handshake. The bot is issued automatically, with no human step.
- **`websocket.name`**: overrides this instance's name inside the cluster. Empty derives it from the instance directory (`<directory>-<first 6 digits of a path hash>`, e.g. `survival-9f31ab`), so two instances on one machine do not collide and a machine rename does not break the enrolment.
- **The handshake id tells peers apart**: `games_ai_mcdr` (an instance) and `mineflayer_bot` (the bot), with the hub adapting to it -- cluster-wide commands reach trusted instances only and never the bot, while a `hello_ack` always carries the hub's own `games_ai_mcdr` plus a `you` field saying which identity this hub accepted the peer as.
- **`websocket.allow_app_id`**: a list setting that admits your own service to this hub instead of refusing it with `683`. The hub applies no bespoke handling for those ids (they are ordinary peers) but trusts them **completely** -- they may trigger command execution like a GamesAI instance -- so list only services you control.
- **Identity comes from the instance directory**: a client's name is derived from it by default, or from `websocket.name`. A newer connection still takes a name over (the old one is closed with `683` and a reason), and the hub **refuses** to issue a token for a name that is already enrolled -- that would knock the online node offline (`683`, not retryable). Use `!!gamesai node rotate <name>` to replace a node on purpose.
- **The role is remembered**: the decided role is written to `config/games_ai/cross_server/role.json`, so an instance that was a client waits for its hub (15 seconds by default) instead of racing it for the port; a hub reloading itself still decides immediately. An address this machine cannot bind is never made a hub, and an instance **without an identity** still takes over when its hub never comes back.
- **The link's runtime state lives in one folder**: `config/games_ai/cross_server/` holds the node's token (`identity.json`), the hub's node table (`nodes.json`) and the role memory (`role.json`).
- **Local mode still has a local link**: a loopback hub (random port on `127.0.0.1`) serves local peers only, so the bot has somewhere to register in every mode.
- **A bot may not order the hub around**: `mineflayer_bot` is provisioned automatically over loopback (and a tunnel or reverse proxy makes every peer look like loopback), so the hub refuses `command`, `command_cluster`, `exec_cluster`, `tool_call` and `event` frames from a bot identity before routing them (`reply` and `ping` are accepted) and logs a warning.
- **Enrolment is rate limited**: one address may ask for 10 new names per minute, the waiting list holds at most 32 entries and expires after 7 days, and a handshake whose `last_seen` did not change never rewrites the node table.
- **A frame is size-checked before it is sent**: past 1 MiB a tool result becomes an honest error and streamed output becomes one note, so the receiver never closes the link with `683` and takes every running conversation with it.
- **A waiting call wakes when its peer disconnects**: a dropped peer (or a hub/node stop) releases every waiting call at once with "the outcome is unknown, do not retry", instead of letting each one run into the 120 second timeout.

### 🧩 Commands are routed by class

- **Class A (the hub executes it)**: `!!ask` (including `-n/-f/switch/stop/compact/context`), `!!data`, `!!gamesai clear [name]`, `!!gamesai speedtest`, `!!gamesai config get/set`, `!!aibot join/leave/set`.
- **Class B (runs where it was typed)**: the help texts.
- **Class C (cluster-wide)**: `!!gamesai clearall`, `reload`, `debug`, `debug thread` -- the hub and every client run it; the originating instance's own output is unlabelled and every other instance is prefixed with `[its instance name]`. (`!!gamesai check` is class A: checking for an update is the hub's decision, and it then coordinates the cluster.)
- **Internal calls never travel**: anything invoked without an `Info` (such as our own `server.execute_command()`) stays local, or a `reload` would bounce around the cluster.
- **Permissions**: a remote player gets `min(the level the client reported, this instance's own permission.yml)`, and 0 when this instance does not know the name; a remote console always keeps level 4.

### 🎨 Rich text over the wire

- Replies travel as **MCDR's own JSON text object** (`to_json_object()` / `from_json_object()`): colours, bold/italic/underline/strikethrough, hover texts, all four click actions (`run_command` / `suggest_command` / `copy_to_clipboard` / `open_url`) and nested lists survive intact, so the `!!data read` buttons keep working on a client.
- A remote command is executed through a `WebSocketCommandSource` that inherits the `CommandSource` **base** only (the issuer may be a player or a console, so it must not claim to be either), and `source.reply()` is the streaming channel back.

### 🤖 The bot joins the cluster

- The Mineflayer bot no longer **runs a WebSocket server of its own**: it **joins the cluster as a client** under its Minecraft username and still answers the same action switch, so every bot tool and the autonomous controller behave exactly as before.
- It no longer owns a port, so nothing has to be reconfigured when the old bot address is taken, and the bot's link can never fight with the cross-server link over one.
- Startup order changed to **decide the role first, then write the bot's config and launch it**, since the address it dials depends on this instance's role.

### 🔧 Fixes

- **The OpenAI request log was not bridged into the MCDR logger**: the `openai` 2.x/3.x SDK had its HTTP dependency renamed from `httpx` to `httpx2` while the bridge only covered `httpx`, so `INFO:httpx2:HTTP Request: ...` escaped to the root logger and printed in a bare format next to MCDR's own lines. The bridged names are now **derived from the installed SDK's metadata**, so the next rename cannot repeat this.
- **Config migration**: the old `mineflayer_bot.websocket.url` is moved to the top-level `websocket.uri` and the dead block is dropped; the new block is written through MCDR's `data_processor` hook, which runs *before* the defaults are filled in, so an address the user already set is never overwritten.
- **The time reading is driven by the clock now, and it names a zone**: a conversation used to answer with the time of its last reading however long it had been idle -- twenty rounds are twenty seconds in one session and twenty hours in the next -- and that reading was a bare local time with no offset at all. It is refreshed on the first round, every 20 rounds, **and whenever the previous reading is older than 10 minutes**, and it is four lines: an ISO timestamp carrying the server's UTC offset, the zone it was written in, the time since the previous reading, and the time since the previous message. Both baselines are stored with the conversation, so a restart or a compression cannot make them lie; a reading with nothing to measure from says `unavailable`. The zone is detected from the machine (`TZ`, the system's own record, the C library's name) and the numeric offset always comes from the clock itself, so daylight saving and a clock that was just changed are right -- and there is deliberately nothing to configure, because a server runs in exactly one zone, the operator's. The four lines are English written in the code rather than translated strings (the keys are gone from `lang/*.yml`): they are addressed to the model, so their meaning must not depend on the language the server happens to run in. The autonomous controller's own request line got the same timestamp and zone, English for the same reason; being rebuilt every cycle, it needs neither the round number nor the elapsed lines.

- **The generated `tools.py` skeleton imported a module that no longer exists**: `on_load` wrote `from games_ai.games_ai_tool import register_tool` into `config/games_ai/tools/tools.py` on the first start, and the [Tools](tools.md) page and the built-in `custom_tools_management` skill showed the same line -- all of them written before the modules moved into the subpackages. That import raises `ModuleNotFoundError`, and because `tools.py` is loaded as one module, **every** custom tool in it fails with it: the log holds a single `Failed to load external tools: No module named 'games_ai.games_ai_tool'` line and nothing is registered. The skeleton and both guides now say `games_ai.ai.games_ai_tool`; the `register_self` example in [Hot reload](hot-reload.md) (`games_ai.ai.register_extra_plugin`) and the `register_skills` example in [Skills](skills.md) (`games_ai.ai.external_skills_loader`) got the same correction, and `tools/build_context_table.py` regenerates the file the plugin actually reads (`games_ai/ai/context_table_data.py`) instead of the pre-subpackage path, where a table update wrote an unused module and left the shipped fallback stale. A new documentation check imports every `games_ai` line those pages show, module **and** name, so a moved module cannot leave a copy-pasteable example behind again.

- **The update loop no longer announces a check nobody asked for**: the check that runs on load and every 24 hours used to broadcast `Checking for plugin updates!` and then `No new version available at this time!` to the whole server -- one line per load, for a decision no player is waiting for. It is quiet now unless it finds something: `checking` and `no new version` go to the debug log (visible with `!!gamesai debug`) and only a release that is actually found is announced, followed by the round that installs it. `!!gamesai check` is unchanged -- somebody typed it, so it still answers `Checking for plugin updates!` and then the result, and only to that caller -- and a check that *fails* (no catalogue or no metadata) stays visible on both paths, because that one needs an operator. (`tests/test_update_notice.py` pins all four cases.)

- **A remote command source now answers the whole command API**: a command forwarded from another instance runs against a `WebSocketCommandSource`, and a handler written for a local player or console source must not notice a difference. `get_info()` now exists and rebuilds the command's `Info` from the forwarded line, finalized against this instance's MCDR when MCDR's hooks allow it, so `Info.get_server()` and `Info.get_command_source()` (which returns the source itself) behave as they do locally -- while a routed *tool* call, which has no command behind it, refuses with `IllegalCallError` instead of inventing one. `get_preference()` looks a remote player up by name in this instance's preference file (a console and an unknown name get the default), so `preferred_language_context()` resolves like a local command. `reply()` honours a console source's `console_text` and accepts a player source's `encoding`, and two sources compare equal when they stand for the same issuer on the same instance -- the way MCDR's builtin sources compare -- which, like them, makes a source unhashable. `_raw_command` refuses a forwarded source explicitly now that it has an `Info`: without that guard a command from the link could be forwarded again, or a cluster command fanned out again, forever. `tests/test_ws_command.py` covers the API member by member.

- **The `!!ask` round runs on its own thread again**: the split into subpackages dropped the `@new_thread("games_ai@ask_ai")` decorator from `ask_ai`, so the whole AI round -- provider round-trips, streaming, tool calls, minutes of it -- ran on MCDR's synchronous TaskExecutor. MCDR's watchdog reports the executor as unresponsive after `advanced.watchdog_threshold` (10 seconds by default) and rebuilds it, printing this plugin's thread stack each time, which is why the executor appeared to be rebuilt over and over while a question was being answered -- and every other command sat behind that round. The decorator is back, under the thread name `games_ai@ask_ai` that `on_unload` already reports, so the command returns at once and the round streams from its own thread exactly as before the split. `tests/test_migration.py` pins the wrapper; the failure cases in `tests/test_ask_errors.py` call the undecorated body through `ask_ai.original`, because the failure has to happen on the test's thread.

### 📚 Documentation

- A dedicated guide in all three languages: [cross-server](https://github.com/PengZixuan30/Games_AI/blob/main/docs/en_us/cross-server.md) -- role decision, configuration, protocol frames, command classes, permissions, rich text, the bot link and troubleshooting.
- `configuration.md` (new `6.websocket` section), `mineflayer-bot.md` and `troubleshooting.md` were updated for the 0.8.0 cross-server behaviour.

### 🧱 Internal structure

- **One source for the instance's settings**: the eight shadow globals `__init__.py` kept beside `plugin_config` -- the message prefix, the permission level, the model table, the default model, the database path, the skills index, the AI-name lookup and the debug flag -- are gone. Every reader uses `plugin_config.<field>` now, which is what the other modules already did, and `_apply_config` writes each value exactly once. The name→id map became `_ai_id_for()`, so it can no longer go stale after a config change, and `send_help()` lost the prefix parameter it was handed at 54 call sites.
- **The bot's JavaScript has its own module**: `games_ai/bot/mineflayer_service_files.py` holds the embedded 683-line `init.js`, the `package.json`, and the two writers and the hash that go with them -- 70% of `mineflayer.py`, which is down from 683 to 581 lines. The writers and the hash check moved into the new module unchanged (`get_default_init_hash()` still compares the same digest), so the split itself rewrites no deployed `init.js`; the file is replaced once by the 0.8.0 bot-link change, exactly as the hash comparison is meant to do.
- **The update path has its own module**: `games_ai/update/update_round.py` holds the 24 h checker, the cluster round and the version comparison (695 lines that used to sit in `__init__.py`, which now stands at 3579 lines). It reads the instance's live state through `attach()` getters that are called at use time, so it never imports the entry module and still sees the current cross-server manager. When and how an update runs is unchanged.
- **The help texts have their own module**: the `gamesai_help` class and its `send_help` helper moved out of `games_ai/__init__.py` into `games_ai/ui/help.py` (172 lines), which is what brought the entry module down to those 3579 lines. The new module imports nothing from the entry module -- the version its greeting prints comes from MCDR's own plugin metadata -- and the entry module still re-exports both names, so nothing that imported them breaks. `!!gamesai` and every per-command help line answer exactly as before.
- **Permission checks have one home**: `games_ai/core/permission.py` (58 lines) replaces the node-only `_node_require_permission` helper and the forty copies of the same comparison that had grown beside it. `require_permission(source)` is the gate every command and help handler calls -- it answers the localized refusal and returns `False`; `has_permission(source)` is the predicate behind it, used by the tool wrappers and by the help listing; and the two sentences a tool hands back to the AI are constants (`TOOL_DENIED_LEVEL`, `TOOL_DENIED_NOT_ALLOWED`) instead of eight and three inline copies. It is a module of its own because `help.py` may not import the entry package. The one visible difference: the refusals of the help pages and of `!!aibot` now carry the message prefix, like every other line those handlers print.
- **The node commands have their own module**: the eight handlers behind `!!gamesai node` -- pending, token, list, revoke, rotate, claim, status, forget -- moved out of `games_ai/__init__.py` into `games_ai/commands/node.py` (409 lines), together with the helpers only they used. The module never imports the entry package: the live link, the plugin server interface, the identity file and the link's restart/stop arrive through one `attach()` call, the way `update/update_round.py` already receives them. Nothing else changed -- the same replies, the same permission gate, and the same registration that keeps these commands local instead of routing them through the cluster.
- **The plugin's source is a tree of subpackages**: the modules that used to sit side by side in `games_ai/` are grouped by what they do now -- `core/` (settings, logging, the dependency gate, the permission rule, the database), `commands/` (what a player types: `!!data`, `!!gamesai config`, `!!aibot`, `!!gamesai clear`, `!!gamesai node`), `cluster/` (the role decision, the hub, the node client, the remote command source), `ai/` (the request pipeline, the provider client, the context-window table, the tool registry, the skills index), `bot/` (the Mineflayer process, its controller, the embedded `init.js`), `update/` (self-update and the round that drives it) and `ui/` (the help texts). Four command groups left the entry module for `games_ai/commands/` -- the `!!data` manager, `!!gamesai config` together with `!!aibot set`, `!!aibot join` / `leave`, and `!!gamesai clear` / `clearall` -- which brought the entry down from 3642 to 3579 lines. Every subpackage's `__init__.py` is a front door as well: it re-exports the package's public names -- eagerly the ones that need nothing but the standard library and MCDR, and on first use (PEP 562) the ones that need a third-party package -- so importing a package early still cannot drag a third-party import onto the pre-gate path the plugin repairs itself from, and the entry module now takes everything it needs from those doors. Each of those doors declares its lazily resolved names a second time in an `if TYPE_CHECKING:` block: the block never runs, but it is what an editor and a type checker read, so `from .ai import ChatParam` carries the real signature instead of `Any`. `tests/test_layout.py` guards the tree now -- the known subpackages and modules, the front doors (their `__all__` resolves, their eager imports stay pre-gate safe, their static block mirrors the runtime mapping, the entry never reaches past them), the acyclic import graph and the pre-gate closure -- and the new [Architecture](architecture.md) page in all three languages maps it.
- **The verification suite lives in the repository**: pytest is the runner now -- a bare `python -m pytest` from the repository root collects the whole suite as 593 cases (the 42 test modules at the top level of `tests/` plus the 5 documentation checkers in `tests/docs/`), configured by the `pytest.ini` at that root -- and the hand-written runner that started the suites one by one (`tests/_run_suites.py`) is gone. What each suite used to carry of its own lives once: the shared fixtures (`free_port`, the quiet logging default and the session guard that keeps the plugin's repository-relative paths inside a temporary folder) in `tests/conftest.py`, and the helper modules and the three protocol prototypes in `tests/_helpers/`. The suites derive the checkout path from their own location instead of carrying one developer's absolute path, and the new [Testing](testing.md) page in all three languages explains how to install pytest, run the whole suite, one module or one test by name, and what a run needs. A new `tests/test_layout.py` guards the layout itself -- the module inventory, the entry module's line budget, an acyclic internal import graph, the promise that everything imported before the dependency gate needs nothing but the standard library and MCDR, and the file-level conventions. Packing is unaffected: MCDR packs what the manifest's `resources` list, so `tests/` never enters the `.mcdr` (checked against a packed build).

- **The editor gets real types for `games_ai.*`**: the plugin now seeds a `games_ai/` package of `.pyi` stubs into `config/games_ai/tools/`, next to the user's `tools.py`, so VS Code resolves `from games_ai.ai.games_ai_tool import register_tool` and every other documented import **with no project configuration** -- before this, that import was reported as unresolved and every name from the plugin was `Any`. A stub package in the same folder as the file being edited is found on its own, which is also the only route for an install packed as a `.mcdr`: its source sits inside the archive, where a language server cannot read it (a directory install can point `python.analysis.extraPaths` at the plugin instead). The tree is generated from the plugin's own source by a new `tools/build_tool_stubs.py` (one stub per module, 41 today; `--check` reports drift) with the docstrings `stubgen` otherwise leaves out, so hovering a name shows what it does and not only its call shape -- the four documented helpers that had none (`register_bot_tool`, `get_plugin_config_perm`, `register_self`, `register_skills`) got short docstrings in the source, because a stub can only publish what is there -- and shipped inside the package in `games_ai/ai/_stubs/`; `games_ai/ai/tools_stub_files.py` -- the module that also took over the `tools.py` skeleton, which is why the entry module is 3579 lines today (3320 after that move, 11 more for the Python-version guard and the restored `ask_ai` decorator) -- copies it out on load and rewrites a file only when it is missing or differs from the shipped stub, byte for byte (a text-mode write would translate the line endings on Windows and never compare equal again). `register_tool` and `register_bot_tool` got the `ParamSpec` annotations their decorators always implied, without which a decorated tool loses its own signature in the editor. `tests/test_tool_stubs.py` guards both halves: the shipped tree against the source (one stub per module, and the documented signatures compared with `inspect`), and the writer against the user's disk (an existing `tools.py` is never touched, unchanged stubs are not rewritten, LF endings, a packed install reads from the archive, and a folder that cannot be written is logged while the load continues).

- **The pre-0.8.0 import path of the tool registry keeps working**: the registry moved into `ai/`, so `games_ai/games_ai_tool.py` is now a compatibility module that re-exports its public names -- the very same objects, which is what makes a tool registered through either path land in the one registry the plugin reads. An existing `config/games_ai/tools/tools.py` and any plugin written against `from games_ai.games_ai_tool import register_tool` (`register_bot_tool`, `get_plugin_config_perm`, `get_tool_handler`, `TOOL_SCHEMAS`, `ToolHandler`, the built-in tool functions, ...) therefore need no edit; new code belongs on `games_ai.ai.games_ai_tool`. The module exists for code outside the plugin -- nothing in the package imports it, so it stays off the pre-gate path -- and the legacy paths are pinned by tests: `tests/test_compat_modules.py` holds the shared contract for all of them (exactly the real module's public surface, the same objects, nothing in the package importing an old path), while `tests/test_tool_compat.py` adds the registry half -- a legacy `tools.py` really loads and registers into the same registry. Private names are deliberately not re-exported; `get_tool_handler` is the public way to a handler.
- **The other two pre-0.8.0 import paths work again as well**: the Hot reload guide's `register_self()` example imported `games_ai.register_extra_plugin` and the Skills guide's `register_skills()` example imported `games_ai.external_skills_loader` before the modules moved into `ai/`, so a plugin written against those pages raised `ModuleNotFoundError` in its own `on_load`. Both flat paths are now compatibility modules re-exporting the real modules' public names -- the same objects, so a plugin that registers itself or injects a skill through the old path reaches the one reload list / skills list the plugin reads -- while the guides keep the new paths for new code and say the old ones still work. Like `games_ai/games_ai_tool.py`, nothing inside the package imports them (they stay off the pre-gate path), and `tests/test_compat_modules.py` pins the contract: the exact public surface, the same objects, a legacy hot-reload registration and a legacy skill injection landing in the shared state, and no internal import of an old path.

### 📦 Automatic dependency installation

- **The entry module imports without the packages**: the check and the repair live in a module that uses the standard library only (`games_ai/core/deps.py`), and the third-party imports happen only when nothing is missing. A machine that has none of them still loads the plugin, and `on_load` then does one thing: report the missing packages, install them and ask MCDR to load the plugin again.
- **Two attempts, then honesty**: `pip install <packages>` runs first with whatever this machine is configured with (no index or proxy argument is added), and on failure against the Aliyun PyPI mirror (`https://mirrors.aliyun.com/pypi/simple/`) for the packages that are still missing. Every pip line reaches the MCDR log with a `[deps]` prefix, so a slow install is visible while it runs.
- **It reloads only what works**: `reload_plugin` is called only after the packages really import; a failure prints the exact `python -m pip install ...` command and stops there -- no retry loop, and the plugin stays loaded but idle (no command, no bot, no cross-server link). The instance that comes back confirms the recovery itself with `Dependencies are ready; the plugin is fully loaded again (...)`.
- **`requirements.txt` moved into the package**: at the plugin root it would make MCDR refuse to load the plugin before any of this code runs. The list is still shipped inside the plugin (`games_ai/requirements.txt`, which `pip install -r` can consume from a source checkout), and an install through the plugin catalogue now relies on that self-repair too, because MCDR only checks a `requirements.txt` at the plugin root.
- **The last attempt is recorded** in `config/games_ai/cache/dependency_install.json` (next to the context window table): it keeps a second instance from starting another pip while one is running and lets the reloaded instance confirm the recovery. It is not a setting and nothing reads it as one.

### ⚠️ Known issues

- `!!gamesai reload` is a class C command: reloading the plugin tears the cross-server link down (it reconnects by itself), so output that was being streamed at that moment can be lost.
- Cluster output is not awaited: each instance's lines appear as they arrive.

### Upgrade notes

- No manual config change is needed: the old `mineflayer_bot.websocket` keys migrate themselves and MCDR fills in the new top-level `websocket` block. A node's token is issued per node rather than shared, so read [cross-server](cross-server.md) before wiring two instances together.
- **Instance name**: an empty `websocket.name` is derived from the instance directory (`<directory>-<first 6 digits of a path hash>`); set it explicitly to pin the name inside the cluster.
- Only the hub has to expose a port. Tokens travel in plaintext (the hub stores only their `sha256` hash); **the plugin itself only ever listens in plain `ws://`**, so behind the internet the tunnel or reverse proxy has to terminate TLS (point the client's `uri` at the proxy's `wss://`; a `wss://` uri can only be a client).
- **Python 3.12 or newer**: the code uses PEP 701 f-strings (a string of the same quote type nested inside an f-string expression, e.g. `f"{server.rtr("games_ai...")}"`), which only the 3.12+ parser accepts. That was already true of the code; the READMEs, the Testing pages and the check at the top of the entry module now say 3.12 instead of 3.11. No friendlier message is possible from inside the module: an interpreter that cannot parse the file never runs a line of it.

## Version 0.7.3

### 🎯 Highlights

- **🧱 A single system message** — the model's prompt and the skills list are merged into one system message, and the current time moved out of it. Some upstreams (the Qwen3.5/3.6/3.8 chat template, for one) accept a system message at index 0 only and answered `System message must be at the beginning`, which made those models unusable.
- **⏱️ The current time travels as a `user` message** — written right in front of the question: injected on the first round and then once every 20 rounds. It is stored in the history, so two consecutive rounds share exactly the same prefix and the provider's prefix cache keeps hitting (before, the time sat in the first line of the system block and changed every round, which re-billed the whole history every round).
- **🗄️ The public data travels as an `assistant` message** — it is reference material rather than an instruction, and the message is not sent at all when the database is empty.
- **🧩 Adjacent `user` messages are merged into one before sending** — time + question, the skill note + question, several `!!ask -f` messages, a question retried after a failed round.

### 1. The message layout of a request

| Order | Role | Content |
|---|---|---|
| 1 | `system` | the model's prompt + the skills list (**exactly one**) |
| 2 | `assistant` | the public data list (not sent when the database is empty) |
| 3… | any | the conversation history (with a `user` time message right in front of the question) |
| last | `user` | this round's question |

- **The skill note changed role** — the "read this skill first" note injected by `!!ask /skill.md` is a `user` message now, not a `system` one;
- **The stateless path matches** — `!!ask -n` sends a single system message, the data as `assistant` when there is any, and one merged `user` message;
- **`response_ai(data=None)` is supported** — an empty public database no longer produces an empty "public data" message.

### 2. Round splitting and caching

- Consecutive `user` messages count as **one round** now: otherwise every injected time would be a round of its own, `KEEP_ROUNDS = 10` would keep only half of the real conversation, and compression boundaries would cut a turn's time away from its question;
- The time counter is reset when `!!ask switch` clears the history (`!!gamesai clear` drops the object) but **not** by compression — a compressed conversation is still the same conversation;
- Merging only shapes the **outgoing request**: the history keeps the messages apart, so the statistics and estimates behind `!!ask context` are unchanged.

### 3. Fixes

- **Both `_kill_mineflayer_process()` call sites** — the one in `run_node()` (cleanup before starting) and the one on the "unsupported server version → reinstall dependencies and restart the bot" path now pass the process argument; they used to raise `TypeError`, which the surrounding `try/except` swallowed into a single log line;
- **Debug log field renamed** — the request header printed by `!!gamesai debug` is `preamble=` now instead of `system=` (that position can also hold an `assistant` message).

### 4. Documentation

- A new "What a request contains" section in all three languages, plus matching updates to the request chain, the `!!ask -n` consistency list and the `system_message` entry under per-user state.

### ⚠️ Known issues

- Context-compression summaries and model-switch hand-off summaries are **still injected as `system` messages** (unchanged in this release), so on upstreams that accept a single system message those two paths can still be rejected.

### Upgrade notes

- **No configuration change is required**;
- The first request after the upgrade rebuilds the prompt prefix, so the old prefix cache misses once and then works normally.

## Version 0.7.2

### 🎯 Highlights

- **🔍 Context Inspection** — Two read-only commands and an on-demand compaction turn context management from invisible into visible: `!!ask context` shows one conversation's window usage, how many tokens are left before compression, the per-round sizes and the cache hits; `!!ask context --all` sums every player's usage per model; `!!ask compact` schedules a compaction of the older history that your next question applies. The two read-only commands read the same consistent snapshot, so looking while a round is running is safe.
- **🔧 `!!ask` Is Now a Command Dispatcher** — The eight separate command nodes were merged into `!!ask` + `!!ask <content>`, with the subcommands parsed by a dispatcher. This fixes a real defect: a sentence like `!!ask stop it.` was answered with **Unknown Argument and silently dropped**, because `stop` was its own command node (`!!ask switch it.` instead took `it.` as a model name). Any sentence now reaches the model, unless it is exactly one of the subcommands.
- **🧹 Unload and Reload Are No Longer Held Hostage by the Bot** — Stopping the Node process went from an escalating ladder that could wait up to 21 seconds in series to one terminate plus a bounded wait (measured: **5 ms**); the unload hands the slow half to a detached thread and waits only 1.5 s; `!!gamesai reload` got a single-flight lock, so two reloads can no longer mistake each other's dying process for a foreign program and **switch the bot off entirely**.
- **🧵 Threads Are Observable** — `!!gamesai debug thread` lists every thread the plugin holds with its ids, the unload reports honestly which threads survived, and a leftover controller thread is aborted on the next load instead of running next to the new instance.

### 1. Context Inspection: `!!ask context`

`!!ask context [player]` (without a player name it shows your own; any player may inspect any player):

- **The summary lines** show the model and where its window comes from (config override / model table / default), the context in use and its share of the window, the window and output limits, how many tokens are left before compression triggers, and the round/message counts;
- **The hover** carries what does not fit: the three compression lines (history 80% / burst 20% / emergency 95%), the per-round token sizes and their share of the window, the last request's prompt/completion/cache/reasoning usage plus this round's totals, and the time and message counts of the last compression.

The numbers come from `ChatParam.context_snapshot()`, read **under one lock**: the round thread appends messages and a compression replaces the whole history list, so without it a reader could observe a half-rewritten history. For that, `_split_rounds` / `_drop_oldest_round` / `_truncate_long_messages` / `_compress_old_rounds` became public-locked wrappers around the original logic (re-entrant, because compressing splits the rounds again internally).

### 2. Server-wide Totals: `!!ask context --all`

- One line per **model**: player count, total context in use and its share of the window, total round prompt, total round peak;
- The hover shows the totals of that model **since those conversations were created**: prompt, completion, total, cache hits (0.1% resolution, truncated rather than rounded) and reasoning tokens; they are stored with the conversation, so a reload or a restart does not zero them;
- **Zero usage is not listed**: a model nobody is holding context on and that has spent nothing does not appear;
- No player names, and no permission restriction.

For "the pre-compression usage stays visible" to hold, `ChatParam` gained four **never-reset** accumulators (`_total_prompt/completion/cached/reasoning_tokens`): previously only a per-round counter (cleared every round) and a last-request counter (overwritten by every request) existed, so one compression erased the record. **Note: since 0.8.0 these accumulators are stored with the conversation and come back on load, so a reload or a restart keeps them; only calls made before 0.7.2 -- when the counters did not exist -- cannot be reconstructed.**

### 3. On-demand Compression: `!!ask compact`

- Ignores the window triggers and compacts the older conversation right away: the newest 10 rounds are kept verbatim, and a history that holds no more than those 10 rounds answers "nothing to compact";
- Like the model-switch hand-off it is **deferred**: the command itself never waits for the summarizing request (up to 60 s); the preflight of your next question performs it, so the command returns at once without blocking the server thread;
- Three honest outcomes: scheduled / nothing to compact / a round is in progress (wait for it or `!!ask stop` first).

### 4. The `!!ask` Command Dispatcher

- The registered nodes dropped from eight to two (`!!ask`, `!!ask <content>`); subcommands are matched by **word** in `ask_ai_dispatcher`, and every longer piece of logic lives in its own function;
- Real defects fixed: `!!ask stop it.` used to report `Unknown Argument` and **execute nothing**; `!!ask switch it.` replied "invalid model";
- Keyword rules: `switch` / `stop` must be **exactly that word** to act as a subcommand, and any extra text makes the whole line a question for the model; `-n` / `--no-history` / `-f` / `--forced` work as leading flags followed by content;
- Fixed along the way: a bare `!!ask -n` used to answer `Unknown Command` and is now an ordinary question; words like `!!ask contextual` are no longer swallowed by the `context` prefix.

### 5. Unload, Reload and Stopping the Bot

- **Node shutdown**: the old "`terminate` → wait 3 s → `kill` → wait 3 s → Windows `taskkill /T /F` → wait 10 s → wait 5 s" ladder became one `terminate` plus a 2 s wait, followed by one platform-specific forced step if needed — measured at **5 ms**. The process handle is **detached** from the module state before it is killed, so the next instance starts from a clean slate;
- **Asynchronous unload**: `on_unload` waits at most 1.5 s synchronously and leaves the rest to the `games_ai@bot_teardown` background thread, which only uses `threading`/`subprocess`/`socket` and a logger **bound as an argument** — it reads no module global and touches no MCDR object, because the plugin is already unloaded by then;
- **Single-flight reload**: `!!gamesai reload` takes a non-blocking lock and answers "a reload is already running" when it is re-entered. With two reloads running, the second one's port probe saw the first one's dying Node process as a foreign program and wrote `mineflayer_bot.enabled = false`, triggering yet another reload — that path is sealed;
- **The port probe** now waits for a running teardown first (up to 5 s) instead of misjudging it;
- **First-connect backoff**: the WebSocket client retries with a short interval until its first successful connection (new option `mineflayer_bot.websocket.first_connect_interval`, default `0.5` s) instead of sleeping a whole `reconnect_interval` (10 s by default) merely because Node is still booting; after the first connection the configured interval applies again (the option was dropped in 0.8.0 together with the rest of the `mineflayer_bot.websocket` block).

### 6. The Autonomous Bot Controller

- **Cooperative stop first**: a new `_stop_event` interrupts the wait between cycles, so an idle controller ends immediately instead of after a full `cycle_interval`;
- **Forced abort**: once the cooperative stop times out, `force_abort_thread` injects `_ControllerAbort` into the controller thread via `PyThreadState_SetAsyncExc` (derived from `BaseException`, so the loop's own `except Exception` cannot swallow it). It **cannot interrupt a blocking C call** (socket read / HTTP request) but takes effect the moment that call returns; a hit on more than one thread is rolled back;
- **AI request timeout**: the controller gained `ai_timeout` (default 120 s), so one stuck request can no longer hold the thread for the SDK's ten-minute default;
- **Leftover threads**: a controller thread that survived an unload is aborted on the **next load** (including the old `AutonomousBotAI` name), and a thread exception hook logs the injected abort as a single line instead of a full traceback.

### 7. Other Improvements and Fixes

- New `!!gamesai debug thread` and the `games_ai.debug.threads_header` string: lists the threads the plugin holds (`#id`, name, daemon flag, `native=`, `(current)`), at most 12 per listing;
- Every thread is now named `games_ai@...` (`games_ai@autonomous_bot`, `games_ai@ws_client`, `games_ai@update_loop`, `games_ai@update_timer`, `games_ai@data_*`, `games_ai@bot_teardown`, …), while the old `AutonomousBotAI` / `MineflayerBotLog` names are still recognised;
- **Fixed `mineflayer_bot.enabled` being switched off by mistake**: the directory is created before `config.json` is written, so the write no longer depends on the caller's working directory;
- `stop_mineflayer_bot` got its missing `@register_bot_tool()` marker, so the autonomous bot can actually call it;
- Unload and hot reload share `_stop_bot_stack()`, where every step is isolated: one failing step can no longer leave the WebSocket client and the Node process behind;
- Added the missing type annotation of `response_list` in `response_chat`;
- Documentation restructure: the trilingual READMEs keep only the entry points (intro / install / usage / command overview / doc links), while the technical detail moved into **nine** files under `docs/<language>/` (AI request pipeline, Mineflayer bot, configuration, tools, skills, example, hot reload, troubleshooting, changelog) and now ships inside the plugin archive. The former "Tools & Skills" page was split into separate tools and skills pages and rewritten against the current implementation (permission and bot-visibility columns added, parameter descriptions corrected), plus a new page with a real server example.

## Version 0.7.1

### 🎯 Highlights

- **🧮 Automatic Context Management** — The fixed `max_history` option is gone. Each model's context window is resolved automatically, real usage is read from the provider's `usage` field, and the conversation is compressed only when it actually grows too large.
- **🔀 Summary Hand-off on `!!ask switch`** — The community vote in [#20](https://github.com/PengZixuan30/Games_AI/issues/20) chose option **B1**: the raw history is cleared at once and the **old** model compresses it into one neutral factual summary right before your next request (same timing as automatic context compression), so the switch never blocks and the new model gets the facts without the old model's style.
- **🛑 `!!ask stop`** — Stop everything you have in flight at once: the running round (tool calls included), a running `!!ask -n` request and a task delegated to the bot. The interrupted step is deleted from the history instead of being left half-written. (0.8.0 changed this: the round keeps what it already wrote -- see the 0.8.0 notes above)
- **🪶 A Stateless `!!ask -n`** — One-shot questions no longer build (and throw away) a full conversation object: `NonHistoryChatParam` keeps no history, no queue and no context bookkeeping, and reuses one HTTP client per endpoint.
- **📊 Usage-Aware Requests** — `response_chat` now returns the provider's `usage`, so the plugin knows the real input size of every request and calibrates its local estimate per `base_url|model`.
- **🧩 New `context_window` Option** — An optional per-AI value in `all_ai` that overrides the window used for context management (handy as a cost-control knob for very large-window models).

### 1. Automatic Context Management

Every request is measured against the model's own context window; the conversation is compressed only when needed. See [Automatic Context Management](ai-request-pipeline.md#automatic-context-management) for the full description.

- **Window resolution**: per-AI `context_window` → remote table [`data/context_windows.json`](https://github.com/PengZixuan30/Games_AI/blob/main/data/context_windows.json) (GitHub Raw with jsDelivr fallback, cached for 24 h) → version-bundled table → conservative default (`32768`).
- **Triggers** (checked before *and* after every request): the current context reaches **80 %** of the window, or a single request reaches **20 %** of the window — the latter catches sudden spikes such as reading a large log file through a tool.
- **Compression**: the newest **10 rounds** always stay verbatim; older rounds are replaced by one neutral factual summary generated by the current model (without tools). If that is still not enough, oversized messages are truncated and the oldest rounds are dropped, so the next request always fits.
- **Calibration**: local token estimates are corrected against real `usage` values per `base_url|model`, converging within a few rounds.

### 2. Summary Hand-off When Switching Models

`!!ask switch <model>` now implements option **B1** of the poll in [#20](https://github.com/PengZixuan30/Games_AI/issues/20) (the poll is closed):

- the summary request is **deferred**, exactly like automatic context compression: the command only clears the history and keeps a snapshot, and the **old** model writes the neutral factual summary (topic, settled conclusions, open items, explicit user requirements — a no-tools request with a 60 s timeout) right before your next request. The switch therefore returns instantly and no longer blocks on a summarizing request;
- the raw history is cleared at switch time, so the previous model's replies can no longer shape the new model's tone or persona;
- the summary is injected as the first system message of the new conversation, together with a note telling the new model to continue with its own instructions and style;
- if the deferred summary fails, the round still answers; the player is told that the previous conversation was dropped;
- a switch to the model you already use touches nothing, and a conversation without history needs no extra request;
- the switch waits for a running round to finish and resets the tool counter, the forced-request queue and the usage counters.

See [Summary Hand-off on Model Switch](ai-request-pipeline.md#summary-hand-off-on-model-switch).

### 3. A Stateless Path for `!!ask -n`

One-shot questions used to create a full `ChatParam` (history, queue, lifecycle event, calibration state, context management) and discard it right after the answer. They are now served by `NonHistoryChatParam`, a self-contained class that keeps nothing:

- **No retained state** — the round lives inside `response_ai` and is released when it returns; nothing is registered in `all_chat_param`, and there is no history, queue, `is_stopped` event or tool counter;
- **No context management** — no token estimation, no usage calibration, no history compression, and therefore no extra summarization request;
- **Identical answers** — the same system messages, the same permission-filtered tools, the same reply format and the same error report as the normal path; tool calls are still executed and fed back inside the round;
- **Single-round window guard** — if the whole request would exceed 80 % of the model's window, the newest message is truncated to the remaining room (the history path keeps its full context management instead);
- **Shared HTTP client** — clients are cached per `base_url` + API key, so repeated `-n` calls do not pay for a new connection pool and TLS handshake each time.

See [The stateless path](ai-request-pipeline.md#the-stateless-path-ask--n) for the details.

### 4. Configuration & Behaviour Changes

- **`max_history` removed** — existing configuration files keep working; the key is simply ignored now.
- **`context_window` added** (optional, per AI entry) — see [3.all_ai](configuration.md#3all_ai).
- **New remote table** — `data/context_windows.json` is maintained in this repository (**249 entries** covering 19 providers plus hosted platforms, verified 683-09-11; sources and caveats in [`data/context_windows.sources.md`](https://github.com/PengZixuan30/Games_AI/blob/main/data/context_windows.sources.md)). The plugin fetches it on startup and together with the 24 h update check, and caches it at `config/games_ai/cache/context_windows.json`; `!!gamesai check` forces a refresh regardless of the 24 h TTL. Maintainers can edit the JSON and run `python tools/build_context_table.py` to re-sync the bundled table and verify it.
- **One refresh chain** — the table refresh shares the startup / 24 h update-check thread instead of running on a second thread of its own, and concurrent refreshes can no longer download the table twice.

### 5. Other Improvements

- `response_chat` also accepts a per-request `timeout` and returns `(message, usage)`;
- New `context_table` module with table matching, validation, caching and silent offline fallback; the version-bundled table now lives in the generated `games_ai/ai/context_table_data.py` (one entry per line) instead of being inlined into the logic module;
- **All built-in tool text is English** — the `description` and parameter descriptions of all 26 built-in tools, **and** every tool return value the model reads back (results, error and permission messages) are now English, so the function-calling prompt no longer mixes languages. Only the notices printed to players stay localized;
- **`modify_skills` and `modify_custom_tools` now edit instead of rewriting** — both take `old_string` (a Python regular expression) and `new_string` (with backreferences such as `\1`), replacing every match instead of overwriting the whole file. A pattern that does not compile or matches nothing is retried as literal text; no match means nothing is written and the model is told so. `modify_skills` keeps an optional `summary` that still updates the skills index;
- `!!gamesai debug` reports the window, usage, calibration factor and every compression step;
- **new `!!ask stop` command** — aborts the player's running round at its next checkpoint (a request in flight cannot be cancelled), drops the interrupted step from the history, discards queued `!!ask -f` messages, and also stops a running `!!ask -n` request and a task delegated to the autonomous bot (0.8.0 changed both: the interrupted round keeps its history and the queued `!!ask -f` messages are kept and merged by the next round). See [Stopping a Running Round](ai-request-pipeline.md#stopping-a-running-round);
- the fallback shown for an unmapped HTTP error code is now a translation key (`games_ai.error_code_map.error_unknown`), so it follows the player's language like the other error codes;
- the `custom_tools_management` skill now requires the AI to **confirm the user's requirements, parameters, permission level and expected return value before writing any tool code** (new mandatory "Step 0"), and to ask again about risky or irreversible behaviour.

## Version 0.7.0

### 🎯 Highlights

- **🧠 Per-User ChatParam Architecture** — Each player's conversation is now a dedicated `ChatParam` object that owns the dialogue history, system messages, a forced-request queue and a round lifecycle event. History handling, model switching and forced requests all go through this object.
- **🔀 Model Switching: `!!ask switch <model>`** — Switch the AI model of your current conversation on the fly. v0.7.0 kept the history fully; the policy was decided by the community vote in [#20](https://github.com/PengZixuan30/Games_AI/issues/20) (option B1, summary hand-off) and is implemented in v0.7.1.
- **⚡ Forced Requests: `!!ask -f <content>`** — Fire a question into a still-running round: it is merged into the in-flight round (or answered by an automatic follow-up round) without waiting for the previous reply to finish.
- **🗑️ Removed Commands** — `!!ask -m <model> <content>`, `!!ask --model ...`, and their `-n` / `--no-history` combinations are gone; use `!!ask switch <model>` + `!!ask -n <content>` instead.
- **📋 Debug Logging** — `!!gamesai debug` now makes the full AI request flow visible in the MCDR console (model switch, forced-request queue/merge, round lifecycle, tool calls).

### 1. ChatParam: One Conversation Object per Player

`games_ai/ai/chat_param.py` introduces `BasicChatParam` / `ChatParam`:

- `response_list` — the dialogue history of this player;
- `system_message` — rebuilt every round (current time, prompt, skills list, public data);
- `response_queue` — incoming `!!ask -f` messages waiting to be merged;
- `is_stopped` — the round lifecycle event that serializes rounds per player;
- `trim_response_list()` — bounded history (`max_history × 2 + tool_count × 2`, replaced by automatic context management in 0.7.1);
- `reload_ai_info()` — refreshes the AI config and client after `!!gamesai reload`.

All player objects are held in `all_chat_param`; `!!gamesai clear` / `!!gamesai clearall` remove them.

### 2. The Full Request Chain

`!!ask <content>` → `ask_ai` builds the user message → the player's `ChatParam` → `response_ai` assembles the request (system messages + history + permission-filtered tools) → OpenAI-compatible API via the cached client (`openai_api.response_chat`) → reply streamed to the player; tool calls are executed and fed back until a final text reply. See [AI Request Pipeline & Chat Mechanism](ai-request-pipeline.md#ai-request-pipeline--chat-mechanism).

### 3. Other Improvements & Fixes

- `!!ask switch <model>` now confirms with a localized message and updates the conversation in place (history preserved in v0.7.0);
- `response_chat` now receives an injected `OpenAI` client (per-AI-config) with type checks, and the Mineflayer autonomous controller was adapted to the new signature;
- `!!gamesai reload` refreshes existing `ChatParam` objects (client rebuild) and reloads `AutonomousBotController` config in the hot-reload path;
- Forced-request flow is fully covered by debug logs (queueing, merge, follow-up round).
