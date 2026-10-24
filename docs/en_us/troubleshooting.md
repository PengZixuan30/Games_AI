<div align="center">

# Troubleshooting

English  |  [简体中文](../zh_cn/troubleshooting.md)  |  [繁體中文](../zh_tw/troubleshooting.md)

[Back to README](../../README.md)

</div>

## Missing Python Packages

The plugin needs `openai`, `requests` and `websockets`. It does not require them to be installed before it starts: on a start where one of them is missing it reports it (`Missing Python package(s): ...`), installs the missing ones with pip and reloads itself.

- **Two attempts**: the first one runs `pip install <packages>` with the machine's own pip configuration (no index or proxy argument is added, so `pip.ini`, `PIP_INDEX_URL` and a proxy keep working); when that fails, the second one retries against the Aliyun PyPI mirror (`https://mirrors.aliyun.com/pypi/simple/`), announced by one log line and limited to the packages that are still missing.
- **Every pip line is written to the log**, prefixed with `[deps]`, so a slow install is visible while it runs. The plugin reloads itself only once the packages really import; the instance that comes back confirms it with `Dependencies are ready; the plugin is fully loaded again (...)`.
- **When both attempts fail** the log prints `Could not install: ...` and the exact command to run by hand (`python -m pip install openai requests websockets`):

```bash
python -m pip install openai requests websockets
```

Then run `!!MCDR plugin reload games_ai`. Until then the plugin is loaded but idle: it registers no command and starts neither the bot nor the cross-server link.
- The package list lives in `games_ai/requirements.txt` inside the plugin. It is deliberately **not** at the plugin root: MCDR checks a root `requirements.txt` before the plugin is imported and refuses to load the plugin while a package is missing, which would keep the plugin from ever repairing itself.
- Installing through the plugin catalogue (`!!MCDR plugin install games_ai`) no longer installs these packages first: MCDR only reads a `requirements.txt` at the plugin root, and the list now lives inside the package, so a catalogue install goes through the same self-repair as any other start.
- If pip cannot write to the interpreter's `site-packages` (a Python under `Program Files`, a service account), the install fails with pip's own message in the log; install the packages as the user MCDR runs as, or with `--user` when that directory is on the interpreter's path.

## `!!ask` Errors

|Symptom|Likely Cause|Solution|
|---|---|---|
|HTTP 400|Malformed request body|Check `extra_body` format matches your API provider's spec.|
|HTTP 401|Invalid API key|Verify `api_key` in your AI configuration.|
|HTTP 404|Model not found|Check `ai_model` name is correct for your provider.|
|HTTP 429|Rate limit exceeded|Wait and retry, or upgrade your API plan.|
|Timeout / no response|Network issue or slow API|Use `!!gamesai speedtest` to check latency. Try a different model.|
|"Unknown function" reply|AI called a tool that doesn't exist|This is usually harmless — the AI will retry with a different approach.|

> The log line for a failed request is now a WARNING with the status, its meaning and the provider's request ID (visible without `!!gamesai debug`). In the reply, the meaning is spelled out right after the code for a provider status other than a wrong key or a rate limit (for example `HTTP 402 (Insufficient API Key balance)`); 401 and 429 have their own sentences, which already name the cause.

## Mineflayer Bot Errors

|Symptom|Relevant Log Message|Solution|
|---|---|---|
|Bot not starting (no `[Mineflayer]` logs at all)|`Mineflayer bot is enabled but Node.js was not found`|Install Node.js >= 18. Run `node --version` to verify.|
|Bot disabled on startup|`Mineflayer requires Node.js >= 18, but found v{X}`|Upgrade Node.js to version 18 or higher.|
|The bot never comes online|No `Registered on hub` line in its log|Check that the hub behind `websocket.uri` is running; the bot dials the address the plugin wrote into its own config and retries every `reconnect_interval` (10 s by default) while the hub is not up. See [cross-server](cross-server.md).|
|`[Bot] Kicked from server` with auth reason|`[Bot] Kicked from server. Reason:` followed by authentication error|Verify `username`/`password`/`auth` via `!!aibot set`. For Microsoft auth, ensure the account has migrated.|
|Bot stuck / not moving|No path error from `goto` action|The `goto` action now returns an error if no path is found. Try different coordinates.|
|`[Bot] Disconnected` then reconnects|`[Bot] Disconnected. Reason: ...` followed by `Reconnecting in 5 seconds...`|This is normal after a server restart or network hiccup. Bot auto-reconnects after 5 seconds.|
|`[Bot] Died, respawning...`|`[Bot] Died, respawning...`|Normal — the bot auto-respawns on death. No action needed.|
|Bot not responding to commands|No `[WS]` activity in logs|Restart with `!!aibot leave` then `!!aibot join`. If it persists, check that the address in the top-level `websocket.uri` (`config/games_ai/config.json`) is reachable from the bot's machine.|
|`npm install failed` in logs|`npm install failed (exit {X})` or `npm is not installed or not in PATH`|Ensure npm is installed and available in PATH. Check the error details in the log for specific package issues.|
|`Server version '{X}' is not supported`|`[Bot] Error: Server version ... is not supported. Latest supported version is ...`|The Minecraft server was upgraded beyond the installed mineflayer's support. The plugin detects this automatically, updates the npm dependencies and restarts the bot. If the error persists, check network access to the npm registry, or manually run `npm install --no-save mineflayer ws vec3 mineflayer-pathfinder mineflayer-mcefly` in `config/games_ai/mineflayer/`, then restart the bot with `!!aibot leave` / `!!aibot join`.|

## Logging & Debugging

- **`!!gamesai debug`** — toggles debug mode. While it is on, the full AI request flow is raised to INFO level in the MCDR console (full prompts, request start/finish, `!!ask -f` queueing and merging, the round lifecycle, tool calls and their results, context window/usage/calibration and every compaction); with it off the same messages stay at DEBUG level.
- **`!!gamesai debug thread`** — lists the threads GamesAI currently owns together with their ids, which is how you check for leftovers after an unload or a hot reload:
  - each line is `#<Python thread id>  <name>  [daemon|non-daemon]  native=<OS thread id>`; the thread running the command is marked `(current)`;
  - `#id` is Python's internal thread id (the one a forced abort targets) and `native=` is the operating system's thread id;
  - only GamesAI's own threads are listed (`games_ai@...`, plus the legacy `AutonomousBotAI` / `MineflayerBotLog` names): anything still listed after an unload or `!!MCDR plugin reload games_ai` belongs to the previous instance. The next plugin load aborts a leftover **bot controller** thread automatically (`games_ai@autonomous_bot`, or the legacy `AutonomousBotAI`), and if it sits inside a blocking call it exits once that call returns; any other leftover is only reported -- restart MCDR if one never goes away;
  - at most 12 entries are printed, the rest are summarised as `... +N`.
- Mineflayer bot logs are prefixed with `[Mineflayer]` in the MCDR console.
- **Context-related checks** (no `!!gamesai debug` needed; `!!ask context` and `!!ask context --all` are read-only and always safe to run, while `!!ask compact` only schedules a compression that is applied before your next question):
  - **`!!ask context [player]`** — start here. It shows the window size, which layer it comes from (config override / model table / default), how much context is in use, how many tokens are left before compression, and whether one round in the per-round sizes has ballooned. The hover also shows the last request's cache hits and reasoning usage;
  - **`!!ask context --all`** — the whole server summed up per configured AI entry (the row is its `ai_name`; the hover names the `all_ai` id and upstream `ai_model`), which answers "is everybody piling context onto the same assistant/model". The **totals since those conversations were created** on hover never shrink when a history is compressed, so that is where you check real consumption; "context in use" *does* drop after a compression or `!!gamesai clear`, so do not read it as a total;
  - **`!!ask compact`** — compress on demand, for when you are far from the 80% line but want the history slimmed now. It is **deferred** (the summarizing request is sent by the preflight of your next question), so seeing "scheduled" rather than "done" is expected. A history of 10 rounds or fewer has nothing to compact and answers "There is no history to compact." A reply saying a round is in progress means exactly that: wait for it, or run `!!ask stop` first.
- A `bot_teardown` thread that is still finishing in the background after `!!gamesai reload` or an unload is expected -- give it a few seconds. If the bot stays away, check that the hub behind `websocket.uri` is reachable: the bot no longer owns a port of its own.
- **OpenAI logging bridge**: at load the plugin routes the `openai` logger and every HTTP logger the installed SDK depends on (`httpx`/`httpx2`, `httpcore`/`httpcore2`, plus the names derived from the SDK metadata) into the MCDR logger (fixed INFO level, independent of `!!gamesai debug`), so the SDK's HTTP requests, responses and warnings all appear in the MCDR console with an `[OpenAI] ` prefix; a `[OpenAI] Logging bridge enabled (level=INFO, loggers=…)` line confirms it at startup.

## Plugin Updates

|Symptom|Cause and fix|
|---|---|
|`Update aborted, the download failed on both sources`|Neither the GitHub release nor the `ghfast.top` mirror produced the announced file (four attempts). Check the machine's access to GitHub, then run `!!gamesai check` again.|
|`Update aborted, the downloaded file did not pass verification`|The size, the sha256 or the metadata inside the archive did not match the release. Nothing was replaced. This is usually a proxy or an antivirus rewriting the download -- retry, and if it persists install by hand.|
|`Update aborted, the plugin file could not be replaced`|Windows still had the file locked after the plugin unloaded (antivirus, the search indexer). The previous file was loaded again, so the server keeps working; the log line names the file. Retry later.|
|`Update aborted: ... the previous version was restored`|The new archive was in place but MCDR did not load it (or loaded a different version), so the previous file was restored and loaded. Report it with the log excerpt -- this is the one case worth investigating.|
|`Update aborted: this instance is not a packed .mcdr install`|The plugin was installed as a source directory. Automatic self-replacement is impossible there; install the `.mcdr` release by hand (`!!MCDR plugin install -U -y games_ai`).|
|An update failed and no other route was tried|On purpose: there is no `!!MCDR plugin install` fallback (see [cross-server](cross-server.md#cluster-updates)). Read the reason, then run `!!gamesai check` again or install by hand.|
|A node never updates itself|A cross-server client does not run the update check; the hub decides. Run `!!gamesai check` (it is executed on the hub) or wait for the hub's round.|
|The log says this instance "is enrolled as a node, so it stays a client"|The hub did not answer while this instance loaded, and an enrolled instance never takes the hub role. It keeps retrying; if the hub is gone for good, run `!!gamesai node forget` and reload.|
- If all else fails, check `config/games_ai/config.json` for misconfiguration.
