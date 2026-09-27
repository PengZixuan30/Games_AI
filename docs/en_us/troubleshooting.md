<div align="center">

# Troubleshooting

English  |  [简体中文](../zh_cn/troubleshooting.md)  |  [繁體中文](../zh_tw/troubleshooting.md)

[Back to README](../../README.md)

</div>

## `!!ask` Errors

|Symptom|Likely Cause|Solution|
|---|---|---|
|HTTP 400|Malformed request body|Check `extra_body` format matches your API provider's spec.|
|HTTP 401|Invalid API key|Verify `api_key` in your AI configuration.|
|HTTP 404|Model not found|Check `ai_model` name is correct for your provider.|
|HTTP 429|Rate limit exceeded|Wait and retry, or upgrade your API plan.|
|Timeout / no response|Network issue or slow API|Use `!!gamesai speedtest` to check latency. Try a different model.|
|"Unknown function" reply|AI called a tool that doesn't exist|This is usually harmless — the AI will retry with a different approach.|

## Mineflayer Bot Errors

|Symptom|Relevant Log Message|Solution|
|---|---|---|
|Bot not starting (no `[Mineflayer]` logs at all)|`Mineflayer bot is enabled but Node.js was not found`|Install Node.js >= 18. Run `node --version` to verify.|
|Bot disabled on startup|`Mineflayer requires Node.js >= 18, but found v{X}`|Upgrade Node.js to version 18 or higher.|
|Bot disabled on startup|`WebSocket port {X} is already in use!`|Change `websocket.url` to a different port in the config file, then `!!gamesai reload`.|
|`[Bot] Kicked from server` with auth reason|`[Bot] Kicked from server. Reason:` followed by authentication error|Verify `username`/`password`/`auth` via `!!aibot set`. For Microsoft auth, ensure the account has migrated.|
|Bot stuck / not moving|No path error from `goto` action|The `goto` action now returns an error if no path is found. Try different coordinates.|
|`[Bot] Disconnected` then reconnects|`[Bot] Disconnected. Reason: ...` followed by `Reconnecting in 5 seconds...`|This is normal after a server restart or network hiccup. Bot auto-reconnects after 5 seconds.|
|`[Bot] Died, respawning...`|`[Bot] Died, respawning...`|Normal — the bot auto-respawns on death. No action needed.|
|Bot not responding to commands|No `[WS]` activity in logs|Restart with `!!aibot leave` then `!!aibot join`. If persistent, check that the `websocket.url` port is accessible.|
|`npm install failed` in logs|`npm install failed (exit {X})` or `npm is not installed or not in PATH`|Ensure npm is installed and available in PATH. Check the error details in the log for specific package issues.|
|`Server version '{X}' is not supported`|`[Bot] Error: Server version ... is not supported. Latest supported version is ...`|The Minecraft server was upgraded beyond the installed mineflayer's support. The plugin detects this automatically, updates the npm dependencies and restarts the bot. If the error persists, check network access to the npm registry, or manually run `npm install --no-save mineflayer ws vec3 mineflayer-pathfinder mineflayer-mcefly` in `config/games_ai/mineflayer/`, then restart the bot with `!!aibot leave` / `!!aibot join`.|

## Logging & Debugging

- **`!!gamesai debug`** — toggles debug mode. While it is on, the full AI request flow is raised to INFO level in the MCDR console (full prompts, request start/finish, `!!ask -f` queueing and merging, the round lifecycle, tool calls and their results, context window/usage/calibration and every compaction); with it off the same messages stay at DEBUG level.
- **`!!gamesai debug thread`** — lists the threads GamesAI currently owns together with their ids, which is how you check for leftovers after an unload or a hot reload:
  - each line is `#<Python thread id>  <name>  [daemon|non-daemon]  native=<OS thread id>`; the thread running the command is marked `(current)`;
  - `#id` is Python's internal thread id (the one a forced abort targets) and `native=` is the operating system's thread id;
  - only GamesAI's own threads are listed (`games_ai@...`, plus the legacy `AutonomousBotAI` / `MineflayerBotLog` names): anything still listed after an unload or `!!MCDR plugin reload games_ai` belongs to the previous instance, and the next plugin load aborts it automatically (if it sits inside a blocking call, it exits once that call returns);
  - at most 12 entries are printed, the rest are summarised as `... +N`.
- Mineflayer bot logs are prefixed with `[Mineflayer]` in the MCDR console.
- **Context-related checks** (no `!!gamesai debug` needed; all three are read-only and always safe to run):
  - **`!!ask context [player]`** — start here. It shows the window size, which layer it comes from (config override / model table / default), how much context is in use, how many tokens are left before compression, and whether one round in the per-round sizes has ballooned. The hover also shows the last request's cache hits and reasoning usage;
  - **`!!ask context --all`** — the whole server summed up per model, which answers "is everybody piling context onto the same model". The **totals since the plugin was loaded** on hover never shrink when a history is compressed, so that is where you check real consumption; "context in use" *does* drop after a compression or `!!gamesai clear`, so do not read it as a total;
  - **`!!ask compact`** — compress on demand, for when you are far from the 80% line but want the history slimmed now. It is **deferred** (the summarizing request is sent by the preflight of your next question), so seeing "scheduled" rather than "done" is expected. A reply saying a round is in progress means exactly that: wait for it, or run `!!ask stop` first.
- About a "slow bot join/leave": on the normal path stopping is **one terminate plus a bounded wait** (milliseconds), and the slow part of starting is Node itself plus the Minecraft login. Seeing the `bot_teardown` thread still finishing in the background right after a reload or unload is expected (a few seconds at most); if you instead see "WebSocket port is already in use" and the bot got disabled by it, check that no second plugin instance or a manually started Node process is holding that port.
- **OpenAI logging bridge**: at load the plugin routes the `openai` and `httpx` loggers into the MCDR logger (fixed INFO level, independent of `!!gamesai debug`), so the SDK's HTTP requests, responses and warnings all appear in the MCDR console with an `[OpenAI] ` prefix; a `[OpenAI] Logging bridge enabled (level=INFO)` line confirms it at startup.
- If all else fails, check `config/games_ai/config.json` for misconfiguration.
