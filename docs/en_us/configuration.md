<div align="center">

# Configuration

English  |  [简体中文](../zh_cn/configuration.md)  |  [繁體中文](../zh_tw/configuration.md)

[Back to README](../../README.md)

</div>

The default configuration file structure is as follows:

```json
{
    "prefix": "[GamesAI]",
    "permission": 3,
    "all_ai": {
        "<Your AI ID>":{
            "prompt": "You are a mature, reliable Minecraft bot tool named \"GamesAI\".",
            "ai_name": "[GamesAI]",
            "base_url": "<Your API Base URL>",
            "ai_model": "<Your AI Model>",
            "api_key": "<Your API Key>",
            "extra_body": {},
            "context_window": null
        }
    },
    "default_ai": "<Your AI ID>",
    "mineflayer_bot": {
            "enabled": false,
            "cycle_interval": 15.0,
            "websocket": {
            "url": "ws://127.0.0.1:8080",
            "reconnect_interval": 10,
            "timeout": 60,
            "first_connect_interval": 0.5
        },
        "bot": {
            "username": "<Your Minecraft Bot Username>",
            "password": "<Your Minecraft Bot Password>",
            "auth": "microsoft"
        }
    }
}
```

---

Below is a brief introduction to each parameter:

## 1.prefix
Type: `str`

Default: `[GamesAI]`

The plugin name used as a prefix in replies. May include Minecraft formatting codes.

## 2.permission
Type: `int`

Default: `3`

The minimum permission level required to execute commands like `!!data`. See the [MCDR Permission Documentation](https://docs.mcdreforged.com/en/latest/permission.html).

Since 0.6.4, this value also controls which **AI tools** are offered to a player: tools whose `perm` is above the player's level are not passed to the AI model at all, so the model cannot see or call them. Built-in tools that manage data, skills, custom tools, or the bot use this value (via `get_plugin_config_perm`), and it is re-read on every request, so changes take effect immediately after a reload.

## 3.all_ai
Type: `dict`

Default: see file

All AI configuration entries, consisting of multiple sub-dictionaries. Each sub-dictionary represents one AI model, and its key serves as the plugin's internal AI_ID.

**prompt**: Use this option to write a system prompt for each AI. Use `> xxx.md` to point the prompt to the `config/games_ai/prompt/xxx.md` file (any file type is supported).

**ai_name**: Similar to `prefix`, but set per model. May include Minecraft formatting codes.

**base_url**, **ai_model**, **api_key**: Same as previous related configuration, but now set per model.

**extra_body**: Please refer to your API provider's documentation for the `extra_body` parameter. For DeepSeek users migrating from the previous `thinking` option, use `{"thinking": {"type": "enabled"}}`. Defaults to `{}` (empty).

**context_window** (optional): Overrides the context window (in tokens) used by [automatic context management](ai-request-pipeline.md#automatic-context-management) for this model. Leave it as `null` to use the value from the context-window table. Useful as a cost-control knob for models with a very large window, e.g. `"context_window": 65536`.

> [!TIP]
> `!!ask context --all` shows how much context each model **actually** carries and how many tokens it has spent since the plugin was loaded (cache hit rate included). If a 1M-window model never grows past a few tens of thousands of tokens, that is the signal that the override above can safely be lowered — a smaller window makes compression step in earlier, which makes every request of a long conversation cheaper. See [Context Inspection](ai-request-pipeline.md#context-inspection).

## 4.default_ai
Type: `str`

Default: `<Your AI ID>`

The model used when a player simply uses `!!ask`. Should be one of the keys in the `all_ai` dictionary (i.e. the plugin's internal AI_ID). An incorrect value will prevent `!!ask` from working properly.

## 5.mineflayer_bot
Type: `dict`

Default: see above

Configuration for the Mineflayer autonomous bot agent.

**enabled**: Whether to launch the bot on startup. Requires Node.js >= 18.

**cycle_interval**: Seconds between autonomous AI decision cycles (default: 15.0).

**websocket**: Internal WebSocket connection settings. `url`, `reconnect_interval`, `timeout`, and `first_connect_interval`.

**first_connect_interval**: The retry gap (in seconds) used **until the first successful connection** (default: 0.5). The Node service needs a moment to start and open its port; backing off by `reconnect_interval` (10 s by default) after a failed first attempt would delay the bot's login by that much for no reason. Once a connection has succeeded, `reconnect_interval` applies again.

> [!WARNING]
> The WebSocket `url` host **must** be `127.0.0.1`. Ensure the chosen port is not already in use — the plugin will automatically check for port conflicts on startup and disable the bot if the port is occupied.
> Do not modify the `websocket` settings unless you fully understand what you are doing.

**bot**: Minecraft account credentials — `username`, `password`, `auth` (microsoft/mojang/offline). The server address is auto-detected from `server.properties`.

> [!WARNING]
> The `username` must match the regular expression `[a-zA-Z0-9_]+` (only English letters, numbers, and underscores; no spaces). `!!aibot join` will be rejected if the username contains invalid characters.

> [!TIP]
> After modifying the configuration, use `!!gamesai reload` or `!!gamesai config set` to apply changes. See [Hot Reload](hot-reload.md#hot-reload) for details.
