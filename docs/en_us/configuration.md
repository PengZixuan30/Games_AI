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
          "extra_body": {}
      }
    },
  "default_ai": "<Your AI ID>",
  "mineflayer_bot": {
      "enabled": false,
      "cycle_interval": 15.0,
      "bot": {
          "username": "<Your Minecraft Bot Username>",
          "password": "<Your Minecraft Bot Password>",
          "auth": "microsoft"
      }
  },
  "websocket": {
      "uri": "ws://127.0.0.1:8080",
      "force_server": false,
      "allow_app_id": [],
      "name": "",
      "token_ttl_hours": -1,
      "auto_enroll": true,
      "identity_file": ""
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

This value also controls which **AI tools** are offered to a player: tools whose `perm` is above the player's level are not passed to the AI model at all, so the model cannot see or call them. Built-in tools that manage data, skills, custom tools, or the bot use this value (via `get_plugin_config_perm`), and it is re-read on every request, so changes take effect immediately after a reload.

It is not a gate on every command, though: `!!gamesai reload`, `!!gamesai check`, `!!gamesai debug`, `!!gamesai debug thread`, `!!gamesai speedtest` and the per-player `!!gamesai clear` run for any command source, and `!!ask` is open to every player (this level only filters which tools the model is offered). `!!gamesai clear <name>`, `!!gamesai clearall`, the `!!data` subcommands, `!!gamesai config get/set`, `!!aibot join/leave/set` and the `!!gamesai node …` commands do check it (the bare `!!gamesai clear` only ever touches your own history and needs no level).

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
> `!!ask context --all` shows how much context each configured AI **actually** carries and how many tokens it has spent since its conversations were created (cache hit rate included; the totals survive a restart). If a 1M-window model never grows past a few tens of thousands of tokens, that is the signal that the override above can safely be lowered — a smaller window makes compression step in earlier, which makes every request of a long conversation cheaper. See [Context Inspection](ai-request-pipeline.md#context-inspection).

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

**How the bot connects**: the bot does not listen on a port of its own; it joins the cluster as a client, so its address and role come from the top-level [6.websocket](#6websocket). See [cross-server](cross-server.md).



**bot**: Minecraft account credentials — `username`, `password`, `auth` (microsoft/mojang/offline). The server address is auto-detected from `server.properties`.


> [!TIP]
> After modifying the configuration, use `!!gamesai reload` to apply changes. `!!gamesai config set` also reloads, but it only handles top-level keys and refuses the complex `all_ai` and `mineflayer_bot` blocks (a dotted key is written as a new top-level key instead of being resolved) -- use `!!aibot set` for the bot credentials. See [Hot Reload](hot-reload.md#hot-reload) for details.

## 6.websocket

Cross-server settings; see [cross-server](cross-server.md) for the full picture.

- `websocket.uri` -- the cluster address (default `"ws://127.0.0.1:8080"`). If a GamesAI hub answers there this instance joins it as a client; if nothing answers and the port is free this instance listens as the hub -- except when it already holds a node identity: an enrolled instance stays a client and keeps retrying until `!!gamesai node forget` drops its token. The host is bound literally, so use `0.0.0.0` or the machine's LAN address to be reachable.
- `websocket.force_server` -- insist on being the hub (default `false`; a busy port falls back to local mode with an error).
- Upgrading from an older release: the old `mineflayer_bot.websocket.url` is migrated to `websocket.uri` and the dead block is removed.
- `websocket.allow_app_id` -- a list of strings (default `[]`). Extra handshake ids this hub admits (your own service, for instance) so they are not refused with `4005`; the hub applies no bespoke handling for them and trusts them completely. See [cross-server](cross-server.md#handshake-ids).
- `websocket.token_ttl_hours` -- validity of the tokens issued to nodes, in hours (default `-1` = unlimited). Fixed at issuance and checked only during the handshake, so it never cuts a live connection; set a value when the nodes are on other machines. See [cross-server](cross-server.md).
- `websocket.auto_enroll` -- whether an instance with no identity asks the hub to enrol it (default `true`).
- `websocket.identity_file` -- override the identity file path (default `config/games_ai/cross_server/identity.json`). An operator who names a file means that file: the value is used verbatim (resolved against the working directory when it is relative), and the automatic migration of the old default location is skipped.
- `websocket.name` -- this instance's name in the cluster. The default `""` derives it from the instance directory (`<instance directory>-<first 6 digits of a path hash>`, e.g. `survival-9f31ab`), so two instances on one machine cannot collide and a machine rename does not break the enrolment. Changing the name needs a new enrolment (`!!gamesai node forget`, then `node claim`).

## 7. Plugin updates

**There is nothing to configure.** Automatic updating is driven by the role the cross-server link decided (see [cross-server](cross-server.md#cluster-updates)):

- a **standalone** instance (local mode) checks on startup and every 24 hours, and installs a new release itself;
- the **hub** does the same, and additionally coordinates the whole cluster: the nodes install first, the hub blocks until they are back on the new version, and only then does the hub install;
- a **client** never checks and never installs on its own -- the hub decides. `!!gamesai check` typed on a client is executed on the hub.

The artifact always comes from the plugin's own GitHub release (the `ghfast.top` mirror is the second source), and it is only used when the announced size and sha256 **and** the plugin id and version inside the archive match. There is deliberately no fallback to `!!MCDR plugin install`: a failed round ends and is reported (`!!gamesai check` starts a new one, or `!!MCDR plugin install -U -y games_ai` installs by hand).
