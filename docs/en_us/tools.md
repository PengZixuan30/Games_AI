<div align="center">

# Tools

English  |  [简体中文](../zh_cn/tools.md)  |  [繁體中文](../zh_tw/tools.md)

[Back to README](../../README.md)

</div>

Tools are the **functions** offered to the model: it can call them to get things done — read data, touch files, run commands, drive the bot. This page covers three things: which tools ship with the plugin, how to add your own, and how a tool's permission and visibility are decided.

## 1. Built-in tools

The table below is exported from the plugin's own tool registry. `Permission` is the minimum MCDR permission level required for the tool to be **offered to the AI**, and `Bot` marks the tools that are also given to the autonomous bot controller (the rest are chat-AI only).

<details>
<summary>Click to see all 26 built-in tools</summary>

| Tool | Parameters | Permission | Bot | Description |
|---|---|:---:|:---:|---|
| `get_online_players` | none | 0 | ✅ | List the players currently online. Uses the `online_player_api` plugin, falling back to an RCON `list` query |
| `get_player_position` | `player` | 0 | ✅ | Position and dimension of one player. Needs the `minecraft_data_api` plugin; without it the tool is not registered at all |
| `calculator` | `expression` | 0 | ✅ | Arithmetic expression evaluator |
| `item_caculator` | `expression`, `single_limit` (optional) | 0 | ✅ | Evaluates an expression and converts the result into boxes / stacks / items; `single_limit` is the stack size (default 64) |
| `setting_timer` | `duration` | 0 | ✅ | Waits the given number of seconds before continuing |
| `read_skills` | `skills` | 0 | — | Reads one registered skill file. **Not** offered to the bot |
| `reload_plugin` | none | 0 | — | Hot-reloads the plugin so config, skill and custom-tool changes take effect |
| `ai_read_data` | `key` | 0 | — | Reads one key of the public database |
| `ai_read_all_keys` | none | 0 | — | Lists every key of the public database |
| `ai_read_all_data` | none | 0 | — | Reads every key/value pair of the public database at once |
| `ai_write_data` | `key`, `value` | config permission | — | Overwrites one public database entry |
| `ai_add_data` | `key`, `value` | config permission | — | Appends one public database entry |
| `ai_del_data` | `key` | config permission | — | Deletes one public database entry |
| `write_skills` | `skills`, `summary`, `content` | config permission | — | Creates or overwrites a skill file and registers it in the skills index |
| `modify_skills` | `skills`, `old_string`, `new_string`, `summary` (optional) | config permission | — | Edits a skill file by regular-expression replacement; a non-empty `summary` updates the index too |
| `delete_skills` | `skills` | config permission | — | Deletes a skill file and its index entry |
| `read_custom_tools` | none | config permission | — | Reads the custom `tools.py` |
| `modify_custom_tools` | `old_string`, `new_string` | config permission | — | Edits the custom `tools.py` by regular-expression replacement |
| `append_custom_tools` | `tools` | config permission | — | Appends tool code to the end of the custom `tools.py` |
| `run_mineflayer_bot` | none | config permission | — | Starts the Mineflayer bot |
| `stop_mineflayer_bot` | none | config permission | ✅ | Stops the Mineflayer bot |
| `bot_chat` | `message` | 0 | ✅ | Makes the bot speak in public chat |
| `bot_whisper` | `username`, `message` | 0 | ✅ | Makes the bot whisper a player |
| `bot_get_state` | none | 0 | ✅ | Full bot state (30+ fields) |
| `bot_call_action` | `action`, `params` (optional) | 0 | ✅ | Sends any action to the bot (`goto`, `dig`, `place`, `attack`, …) |
| `delegate_to_bot` | `task`, `username` (optional) | 0 | ✅ | Hands a complex task to the autonomous bot controller, which plans and performs the steps itself |

</details>

Three notes about that table:

- **`config permission`** means the `permission` value of `config.json`. It decides which level these tools are opened to; for a player below that level the tools never appear in the request at all, so the model cannot call them.
- **The `Bot` column is narrow on purpose**: the tool set handed to the bot controller is deliberately smaller (no `read_skills`, no database access, no skill/tool management), so an unsupervised autonomous loop cannot rewrite skills or data.
- **`perm` is only the first gate.** Sensitive built-in and custom tools usually check the caller's real level again inside the function (`source.get_permission_level()`). Both gates have to pass before anything happens.

> [!TIP]
> Need more tools? There are three routes: install [GamesAI-Extra](https://github.com/PengZixuan30/Games_AI-Extra) (waypoints, whitelist management, Minecraft Wiki search), write them in `tools.py`, or register them from your own MCDR plugin.

## 2. Custom tools in `tools.py`

Custom tools live in this file:

```
config/games_ai/tools/tools.py
```

The plugin writes a skeleton with one example tool on first start. Its minimal shape is:

```python
from mcdreforged.command.command_source import CommandSource
from games_ai.games_ai_tool import register_tool

@register_tool(description="My custom tool")
def my_custom_tool(source: CommandSource, ai_prefix: str):
    return "Tool finished"
```

Three hard requirements:

1. `from games_ai.games_ai_tool import register_tool` must be there;
2. the function must carry the `@register_tool(...)` decorator. **A public function without it is not registered** — at load the plugin scans the file and logs them as `Functions in external tools.py WITHOUT @register_tool() decorator (REJECTED)`. Private helpers should start with `_`, which makes them skipped rather than reported;
3. the first two parameters must be `source: CommandSource` and `ai_prefix: str`, followed by the parameters declared in `parameters`, in the same order.

### Declaring parameters

`description` and `parameters` become the model's tool description **verbatim**, so they are prompts written for the model, not comments for humans:

```python
@register_tool(
    description="Read one registered skill file. Read it before performing the matching task.",
    parameters={
        "type": "object",
        "properties": {
            "skills": {"type": "string", "description": "Skill file name, e.g. skills_management.md"}
        },
        "required": ["skills"]
    }
)
def read_skills(source: CommandSource, ai_prefix: str, skills: str):
    ...
```

- The structure follows the OpenAI function-calling JSON Schema; **omitting `parameters` makes it a no-argument tool**;
- parameters with default values (such as `max_length: int = 3000`) must not be listed in `required` — the model may leave them out;
- a good `description` answers three questions: **when to use it**, **what it needs first**, and **what it returns on failure**. The model only ever sees that text and whatever you `return`.

### Return values

The string you `return` is the entire result the model sees. Therefore:

- **read-only tools** return the content itself;
- **write operations** return what was done (e.g. `Executed Minecraft command: /say hello`) so the model can confirm the outcome;
- **failures** return a readable reason (`Permission denied: level 3 or above required`) instead of raising or returning `None`.

Messages for the player go through `source.reply(f"{ai_prefix}...")`; those appear in chat only and the model never sees them. Keep the two separate.

### Permissions

```python
from games_ai.games_ai_tool import register_tool, get_plugin_config_perm

@register_tool(description="Admin-only tool", perm=get_plugin_config_perm)
def my_admin_tool(source: CommandSource, ai_prefix: str):
    if source.get_permission_level() < get_plugin_config_perm():
        return f"Permission denied: level {get_plugin_config_perm()} or above required"
    ...
```

- `perm` may be a fixed integer or a zero-argument callable returning one; `get_plugin_config_perm` follows `config.json`'s `permission` dynamically, so changing the config needs no code change;
- **`perm` only controls whether the tool is handed to the model.** Once it is, the function should still re-check the caller's level as above — the tool runs **on behalf of the asking player**, and the model can be talked into calling it.
- To vary **one tool's behaviour** by level, put the check in the function body (for example: unrestricted commands at level 4, a whitelist at levels 1/3).

### Making a tool available to the bot

Custom tools are chat-AI only by default. To let the bot controller call one, stack the second decorator:

```python
from games_ai.games_ai_tool import register_tool, register_bot_tool

@register_tool(description="Makes the bot hand an item to a player")
@register_bot_tool()
def give_item(source: CommandSource, ai_prefix: str, player: str):
    ...
```

The bot controller calls these from an unsupervised loop, so **only mark tools that are idempotent or safe to retry**.

### Letting the AI write them

`read_custom_tools`, `modify_custom_tools` and `append_custom_tools` together let the AI read, precisely edit and append to this file; afterwards it should call `reload_plugin` for the change to take effect. The built-in skill `custom_tools_management.md` forces it to confirm the requirement, parameters, permission level and expected return value with you **before** writing any code.

The edits are **regular-expression replacements**: `old_string` is a Python regex matched against the whole file, `new_string` may use backreferences such as `\1` or `\g<name>`, and **every** match is replaced. A regex that does not compile, or matches nothing, falls back to a literal text replacement; if that also finds nothing, nothing is written and the model is told so.

### Dependencies and loading

`tools.py` is an ordinary Python module that the plugin executes on every load and hot reload:

- third-party `import`s at the top must actually be installed. One failing `import requests` makes the **entire** file fail to load, and **none** of your custom tools register (the log says why);
- so put a heavy `import` inside the function and return a readable error when it is missing, or install the dependency first;
- every `!!gamesai reload` re-executes the file, so tool changes never need a server restart.

> [!WARNING]
> Custom tools can make **real and possibly irreversible** changes to the server: editing files, running commands, installing dependencies or reloading the plugin is one function call away. If you offer such tools, spell out the "confirm first" rules in the matching skill file and tighten them by permission level inside the function — a skill constrains the model, the check inside the function is the last line of defence at runtime.

## 3. Registering tools from your own MCDR plugin

Instead of editing `tools.py`, register directly from plugin code:

```python
from games_ai.games_ai_tool import register_tool, register_bot_tool

@register_tool(
    description="Description of your tool",
    parameters={...}          # optional
)
@register_bot_tool()          # optional: also let the bot controller call it
def my_plugin_tool(source: CommandSource, ai_prefix: str, ...):
    source.reply(f"{ai_prefix}Running...")
    return "Tool result"
```

Key points:

- your plugin must declare the dependency in `mcdreforged.plugin.json` so that GamesAI loads first:

```json
{
    "id": "my_plugin",
    "dependencies": {
        "mcdreforged": ">=2.15.0",
        "games_ai": ">=0.6.1"
    }
}
```

- when you use `@register_bot_tool()`, require `>= 0.6.0` or above;
- tools registered this way are **exactly equivalent** to built-in ones or those in `tools.py`: same permission rules, same presence in the model's callable list;
- **any plugin that registers tools is reloaded automatically when GamesAI hot-reloads**, so its tool code always tracks the newest version — nothing extra to do. Only if your plugin registers skills but no tools, or needs its own reload logic, use `register_self()` — see [Hot Reload](hot-reload.md#hot-reload).

## 4. Troubleshooting

| Symptom | What to check |
|---|---|
| The AI says a tool is unavailable | Is `config.json`'s `permission` above that player's level? A tool with a higher `perm` is never sent to the model |
| Every custom tool stopped working | Search the MCDR log for `[tools_interpreter]`: a failed load prints the exception, and rejected functions are listed after `REJECTED` |
| The tool is called but nothing happens | The level check inside the function returned the "permission denied" string — the model sees that text, but no action is performed |
| A `tools.py` edit had no effect | Run `!!gamesai reload`, or have the AI call `reload_plugin` |
| Want to see what a tool actually sent to the model | Turn on `!!gamesai debug`; tool calls and their results are logged. The tool's own definition can be read back with `read_custom_tools` |
