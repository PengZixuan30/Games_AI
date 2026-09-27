<div align="center">

# What's New

English  |  [简体中文](../zh_cn/changelog.md)  |  [繁體中文](../zh_tw/changelog.md)

[Back to README](../../README.md)

</div>

## Version 0.7.2

### 🎯 Highlights

- **🔍 Context Inspection** — Three read-only commands turn context management from invisible into visible: `!!ask context` shows one conversation's window usage, how many tokens are left before compression, the per-round sizes and the cache hits; `!!ask context --all` sums every player's usage per model; `!!ask compact` compresses the older history on demand. All three read the same consistent snapshot, so looking while a round is running is safe.
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
- The hover shows the totals of that model **since the plugin was loaded**: prompt, completion, total, cache hits (0.1% resolution, truncated rather than rounded) and reasoning tokens;
- **Zero usage is not listed**: a model nobody is holding context on and that has spent nothing does not appear;
- No player names, and no permission restriction.

For "the pre-compression usage stays visible" to hold, `ChatParam` gained four **never-reset** accumulators (`_total_prompt/completion/cached/reasoning_tokens`): previously only a per-round counter (cleared every round) and a last-request counter (overwritten by every request) existed, so one compression erased the record. **Note: these accumulators start at the plugin load of this run; earlier calls cannot be reconstructed.**

### 3. On-demand Compression: `!!ask compact`

- Ignores the window triggers and the "skip when there are no more than 10 rounds" early return, compressing the older conversation immediately;
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
- **First-connect backoff**: the WebSocket client retries with a short interval until its first successful connection (new option `mineflayer_bot.websocket.first_connect_interval`, default `0.5` s) instead of sleeping a whole `reconnect_interval` (10 s by default) merely because Node is still booting; after the first connection the configured interval applies again.

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
- **🛑 `!!ask stop`** — Stop everything you have in flight at once: the running round (tool calls included), a running `!!ask -n` request and a task delegated to the bot. The interrupted step is deleted from the history instead of being left half-written.
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
- **New remote table** — `data/context_windows.json` is maintained in this repository (**249 entries** covering 19 providers plus hosted platforms, verified 2026-09-11; sources and caveats in [`data/context_windows.sources.md`](https://github.com/PengZixuan30/Games_AI/blob/main/data/context_windows.sources.md)). The plugin fetches it on startup and together with the 24 h update check, and caches it at `config/games_ai/cache/context_windows.json`; `!!gamesai check` forces a refresh regardless of the 24 h TTL. Maintainers can edit the JSON and run `python tools/build_context_table.py` to re-sync the bundled table and verify it.
- **One refresh chain** — the table refresh shares the startup / 24 h update-check thread instead of running on a second thread of its own, and concurrent refreshes can no longer download the table twice.

### 5. Other Improvements

- `response_chat` also accepts a per-request `timeout` and returns `(message, usage)`;
- New `context_table` module with table matching, validation, caching and silent offline fallback; the version-bundled table now lives in the generated `games_ai/context_table_data.py` (one entry per line) instead of being inlined into the logic module;
- **All built-in tool text is English** — the `description` and parameter descriptions of all 26 built-in tools, **and** every tool return value the model reads back (results, error and permission messages) are now English, so the function-calling prompt no longer mixes languages. Only the notices printed to players stay localized;
- **`modify_skills` and `modify_custom_tools` now edit instead of rewriting** — both take `old_string` (a Python regular expression) and `new_string` (with backreferences such as `\1`), replacing every match instead of overwriting the whole file. A pattern that does not compile or matches nothing is retried as literal text; no match means nothing is written and the model is told so. `modify_skills` keeps an optional `summary` that still updates the skills index;
- `!!gamesai debug` reports the window, usage, calibration factor and every compression step;
- **new `!!ask stop` command** — aborts the player's running round at its next checkpoint (a request in flight cannot be cancelled), drops the interrupted step from the history, discards queued `!!ask -f` messages, and also stops a running `!!ask -n` request and a task delegated to the autonomous bot. See [Stopping a Running Round](ai-request-pipeline.md#stopping-a-running-round);
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

`games_ai/chat_param.py` introduces `BasicChatParam` / `ChatParam`:

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
