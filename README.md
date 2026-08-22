<div align="center">

# GamesAI for MCDReforged

English  |  [简体中文](/README.zh-CN.md)  |  [繁體中文](/README.zh-TW.md)

[Report an Issue](https://github.com/PengZixuan30/Games_AI/issues/new)  |  [Share an Idea](https://github.com/PengZixuan30/Games_AI/discussions/new/choose)  |  [Join QQ Group](https://qm.qq.com/q/jDQQaUPNmw)

[Go to Fabric Version](https://github.com/PengZixuan30/GamesAI)

</div>

> [!NOTE]
> **GamesAI Plugin/Mod QQ Group: 849544707** — Join us to discuss issues, share feedback, and exchange prompt, skills, tools configurations!

> [!NOTE]
> Welcome to version 0.6.4! This release brings a **permission-based AI tool system** (`perm` for `@register_tool`), **full tool re-registration on hot reload** (built-in tools replayed, custom `tools.py` re-imported, third-party plugin tools reloaded together with their plugins), and **several reload & permission fixes**. Whitelist and Minecraft Wiki tools have been moved to [GamesAI-Extra](https://github.com/PengZixuan30/Games_AI-Extra). See [What's New](#whats-new) for details.

<details>
<summary>Table of Contents (click to expand)</summary>

- [GamesAI for MCDReforged](#gamesai-for-mcdreforged)
  - [Installation](#installation)
  - [Usage](#usage)
  - [Using the Mineflayer Bot](#using-the-mineflayer-bot)
    - [Prerequisites](#prerequisites)
    - [Commands](#commands)
    - [How It Works](#how-it-works)
    - [Supported Actions](#supported-actions)
    - [AI Tools for Bot Control](#ai-tools-for-bot-control)
    - [Configuration](#configuration)
  - [Configuration](#configuration-1)
    - [1.prefix](#1prefix)
    - [2.permission](#2permission)
    - [3.max\_history](#3max_history)
    - [4.all\_ai](#4all_ai)
    - [5.default\_ai](#5default_ai)
    - [6.mineflayer\_bot](#6mineflayer_bot)
  - [Tools \& Skills](#tools--skills)
    - [Built-in Tools](#built-in-tools)
    - [Custom Tools via Config File](#custom-tools-via-config-file)
    - [Custom Tools in Your MCDR Plugin](#custom-tools-in-your-mcdr-plugin)
    - [Built-in Skills](#built-in-skills)
    - [Add Skills via Config File](#add-skills-via-config-file)
    - [Register Skills in Your MCDR Plugin](#register-skills-in-your-mcdr-plugin)
  - [Hot Reload](#hot-reload)
    - [Triggering a Hot Reload](#triggering-a-hot-reload)
    - [What Happens During a Hot Reload](#what-happens-during-a-hot-reload)
    - [Making Your MCDR Plugin Follow GamesAI Hot Reload](#making-your-mcdr-plugin-follow-gamesai-hot-reload)
      - [Approach 1: Auto-Reload with `register_self()` (Recommended)](#approach-1-auto-reload-with-register_self-recommended)
      - [Approach 2: Responding to Hot Reload via Event Listening](#approach-2-responding-to-hot-reload-via-event-listening)
    - [Comparison of the Two Approaches](#comparison-of-the-two-approaches)
  - [Troubleshooting](#troubleshooting)
    - [`!!ask` Errors](#ask-errors)
    - [Mineflayer Bot Errors](#mineflayer-bot-errors)
    - [Logging \& Debugging](#logging--debugging)
  - [What's New](#whats-new)
    - [Version 0.6.4](#version-064)
      - [🎯 Highlights](#-highlights)
      - [1. Permission-Based AI Tool System](#1-permission-based-ai-tool-system)
      - [2. Full Tool Re-Registration on Hot Reload](#2-full-tool-re-registration-on-hot-reload)
      - [3. Tool Set Adjustments](#3-tool-set-adjustments)
      - [4. Fixes](#4-fixes)
    - [Version 0.6.3](#version-063)
      - [🎯 Highlights](#-highlights-1)
      - [1. Mineflayer Version Compatibility Auto-Repair](#1-mineflayer-version-compatibility-auto-repair)
      - [2. Permission Checks for Bot Start/Stop Tools](#2-permission-checks-for-bot-startstop-tools)
      - [3. Wait for Server Start before Launching the Bot](#3-wait-for-server-start-before-launching-the-bot)
      - [4. Unload Registered Extension Plugins on Plugin Unload](#4-unload-registered-extension-plugins-on-plugin-unload)
    - [Version 0.6.2](#version-062)
      - [🎯 Highlights](#-highlights-2)
      - [1. New Tool: `get_player_position`](#1-new-tool-get_player_position)
      - [2. Forced Skill Reading: `!!ask /<skill>`](#2-forced-skill-reading-ask-skill)
      - [3. `games_ai.reload` Event](#3-games_aireload-event)
    - [Version 0.6.1](#version-061)
      - [🎯 Highlights](#-highlights-3)
      - [1. Extension Plugin System](#1-extension-plugin-system)
      - [2. Validation \& Stability](#2-validation--stability)
    - [Version 0.6.0](#version-060)
      - [🎯 Highlights](#-highlights-4)
      - [1. Mineflayer Bot Integration](#1-mineflayer-bot-integration)
      - [2. Configuration System Overhaul](#2-configuration-system-overhaul)
      - [3. OpenAI Logging Bridge](#3-openai-logging-bridge)
  - [Acknowledgements \& Disclaimer](#acknowledgements--disclaimer)
  - [Sponsorship \& Contributors](#sponsorship--contributors)
  - [License](#license)

</details>

## Installation

Run the following command in the MCDR console to install the plugin:

`!!MCDR plugin install games_ai`

---

Alternatively, get it from the [MCDR Plugin Repository](https://mcdreforged.com/plugin/games_ai) and place it in your plugin directory.

If you choose to install manually, install the Python packages `openai`, `requests`, and `websockets` first:

```bash
pip install openai requests websockets
```

## Usage

Type `!!gamesai` anywhere to display all available features of this plugin.

|Command|Description|
|---|---|
|`!!gamesai clear`|Clear your own chat history. Chat history is unrelated to the public database.|
|`!!gamesai clearall`|Clear all players' chat history. Chat history is unrelated to the public database.|
|`!!gamesai reload`|Reload the plugin configuration file. See [Hot Reload](#hot-reload) for details.|
|`!!gamesai check`|Check for plugin updates.|
|`!!gamesai speedtest [model]`|Test API server connection latency. If no model is specified, all models are tested.|
|`!!gamesai config get <key>`|Read a configuration value.|
|`!!gamesai config set <key> <value>`|Update a configuration value (auto type-adapts; automatically triggers [Hot Reload](#hot-reload)).|

---

You can also use `!!ask` directly to ask the AI questions, chat, or ask it to do things for you.

|Command|Description|
|---|---|
|`!!ask <content>`|Ask the AI a question, chat, or ask it to do something. `<content>` is what you want the AI to do or the question you want to ask.|
|`!!ask -m <model> <content>`|Use a specific model to ask the AI a question, chat, or ask it to do something. `<model>` is the AI_ID or nickname of the model you want to use. `<content>` is what you want the AI to do or the question you want to ask.|
|`!!ask -n <content>`|Ask the AI without using conversation history (current conversation is still saved).|
|`!!ask -n -m <model> <content>`|Use a specific model without conversation history.|

---

Type `!!data` for information about database commands.

> [!TIP]
> The database is automatically created when upgrading to version 0.3.0 or above.

|Command|Description|
|---|---|
|`!!data write <key> <value>`|Add a data entry to the public database. `<key>` must not contain spaces; `<value>` can be any string.|
|`!!data add <key> <value>`|Append `<value>` to an existing key in the public database. Creates a new key if it does not exist.|
|`!!data del <key>`|Delete a data entry from the public database, regardless of whether the key exists.|
|`!!data read <key>`|Read the value associated with a key from the public database.|
|`!!data list`|Read all entries in the public database.|
|`!!data list keys`|Read all keys in the public database.|

---

## Using the Mineflayer Bot

GamesAI 0.6.0 introduces a fully autonomous Minecraft bot powered by [Mineflayer](https://github.com/PrismarineJS/mineflayer). The AI can directly control the bot to navigate, mine, build, craft, fight, and interact with the world.

### Prerequisites

- **Node.js >= 18** and **npm** must be installed on the server
- The plugin automatically installs npm dependencies (`mineflayer`, `ws`, `vec3`, `mineflayer-pathfinder`, `mineflayer-mcefly`) on first launch, and refreshes them automatically when the installed mineflayer does not support the server version (e.g. after a Minecraft server upgrade)
- A Minecraft account for the bot (Microsoft/Mojang/offline)

### Commands

|Command|Description|
|---|---|
|`!!aibot join`|Enable the bot and make it join the server.|
|`!!aibot leave`|Make the bot leave the server and disable it.|
|`!!aibot set <key> <value>`|Configure bot identity (`username`/`password`/`auth`).|

### How It Works

```
Player !!ask → GamesAI Plugin → WS Client (Python) → WS Server (Node.js) → Mineflayer Bot
                                                                            ↓
                                                                     Minecraft Server

AI (Autonomous Controller):
  get_state → analyze → bot_call_action(goto/dig/attack/...) → cycle
```

The plugin launches a Node.js process running a WebSocket server. A Python WebSocket client (built into the plugin) connects to it locally, forming a bridge between MCDR and the Mineflayer bot. When the bot is enabled, an **autonomous AI controller** periodically reads the bot's state, checks chat messages, and decides what actions to take.

### Supported Actions

The bot supports 20+ actions callable via the `bot_call_action` AI tool:

|Action|Description|
|---|---|
|`goto`|A\* pathfinding to coordinates `{x, y, z, range?}`|
|`efly`|Elytra flight to coordinates (requires elytra)|
|`dig`|Break a block at coordinates|
|`place`|Place a block at coordinates|
|`attack`|Attack a nearby entity by name or nearest hostile|
|`useOn`|Right-click an entity (e.g. villager trading)|
|`equip` / `unequip`|Equip/unequip armor or items to hand|
|`mount` / `dismount`|Ride or dismount vehicles and animals|
|`craft`|Craft items (inventory or crafting table)|
|`lookAt`|Look at coordinates or set yaw/pitch directly|
|`sleep` / `wake`|Sleep in a bed or wake up|
|`activateBlock`|Right-click a block (open chest, press button)|
|`setControlState`|Control vehicle movement (forward/back/jump)|
|`viewContainer` / `takeFromContainer` / `putToContainer`|Container management|
|`openFurnace` / `furnacePutInput` / `furnacePutFuel` / `furnaceTakeOutput`|Furnace operations|
|`nearbyEntities` / `findBlocks` / `getBlock`|World query|
|`stop` / `stopEfly`|Stop all movement or elytra flight|

### AI Tools for Bot Control

In addition to `bot_call_action`, these dedicated AI tools are available:

|Tool|Description|
|---|---|
|`bot_chat`|Make the bot send a message in public chat.|
|`bot_whisper`|Make the bot send a private message to a player.|
|`bot_get_state`|Get the bot's full state (30+ fields).|
|`run_mineflayer_bot` / `stop_mineflayer_bot`|Start or stop the bot. Require the configured `permission` level (0.6.4+).|
|`delegate_to_bot`|Delegate a complex Minecraft task to the autonomous controller.|

### Configuration

See [6.mineflayer_bot](#6mineflayer_bot) for the full configuration reference. Key points:

- Set `mineflayer_bot.enabled` to `true` (or use `!!aibot join`) to launch the bot
- `mineflayer_bot.bot.username` / `password` / `auth` — the bot's Minecraft credentials. **Username must match `[a-zA-Z0-9_]+`** (letters, numbers, underscores only).
- `mineflayer_bot.cycle_interval` — how often (in seconds) the autonomous AI makes decisions
- `mineflayer_bot.websocket` — internal settings; do not modify unless you know what you are doing

> [!NOTE]
> After modifying Bot configuration, run `!!gamesai reload` (or use `!!aibot set` / `!!gamesai config set`) to automatically restart the Bot with the new settings. See [Hot Reload](#hot-reload) for details.

## Configuration

The default configuration file structure is as follows:

```json
{
  "prefix": "[GamesAI]",
  "permission": 3,
  "max_history": 10,
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
      "websocket": {
          "url": "ws://127.0.0.1:8080",
          "reconnect_interval": 10,
          "timeout": 60
      },
      "bot": {
          "username": "<Your Minecraft Bot Username>",
          "password": "<Your Minecraft Bot Password>",
          "auth": "microsoft"
      }
  }
```

---

Below is a brief introduction to each parameter:

### 1.prefix
Type: `str`

Default: `[GamesAI]`

The plugin name used as a prefix in replies. May include Minecraft formatting codes.

### 2.permission
Type: `int`

Default: `3`

The minimum permission level required to execute commands like `!!data`. See the [MCDR Permission Documentation](https://docs.mcdreforged.com/en/latest/permission.html).

Since 0.6.4, this value also controls which **AI tools** are offered to a player: tools whose `perm` is above the player's level are not passed to the AI model at all, so the model cannot see or call them. Built-in tools that manage data, skills, custom tools, or the bot use this value (via `get_plugin_config_perm`), and it is re-read on every request, so changes take effect immediately after a reload.

### 3.max_history
Type: `int`

Default: `10`

The maximum number of conversation turns retained per player. Unrelated to the public database. Set to `0` to completely disable history.

### 4.all_ai
Type: `dict`

Default: see file

All AI configuration entries, consisting of multiple sub-dictionaries. Each sub-dictionary represents one AI model, and its key serves as the plugin's internal AI_ID.

**prompt**: Use this option to write a system prompt for each AI. Use `> xxx.md` to point the prompt to the `config/games_ai/prompt/xxx.md` file (any file type is supported).

**ai_name**: Similar to `prefix`, but set per model. May include Minecraft formatting codes.

**base_url**, **ai_model**, **api_key**: Same as previous related configuration, but now set per model.

**extra_body**: Please refer to your API provider's documentation for the `extra_body` parameter. For DeepSeek users migrating from the previous `thinking` option, use `{"thinking": {"type": "enabled"}}`. Defaults to `{}` (empty).

### 5.default_ai
Type: `str`

Default: `<Your AI ID>`

The model used when a player simply uses `!!ask`. Should be one of the keys in the `all_ai` dictionary (i.e. the plugin's internal AI_ID). An incorrect value will prevent `!!ask` from working properly.

### 6.mineflayer_bot
Type: `dict`

Default: see above

Configuration for the Mineflayer autonomous bot agent.

**enabled**: Whether to launch the bot on startup. Requires Node.js >= 18.

**cycle_interval**: Seconds between autonomous AI decision cycles (default: 15.0).

**websocket**: Internal WebSocket connection settings. `url`, `reconnect_interval`, and `timeout`.

> [!WARNING]
> The WebSocket `url` host **must** be `127.0.0.1`. Ensure the chosen port is not already in use — the plugin will automatically check for port conflicts on startup and disable the bot if the port is occupied.
> Do not modify the `websocket` settings unless you fully understand what you are doing.

**bot**: Minecraft account credentials — `username`, `password`, `auth` (microsoft/mojang/offline). The server address is auto-detected from `server.properties`.

> [!WARNING]
> The `username` must match the regular expression `[a-zA-Z0-9_]+` (only English letters, numbers, and underscores; no spaces). `!!aibot join` will be rejected if the username contains invalid characters.

> [!TIP]
> After modifying the configuration, use `!!gamesai reload` or `!!gamesai config set` to apply changes. See [Hot Reload](#hot-reload) for details.

## Tools & Skills

> [!TIP]
> Some tools are available via the [GamesAI-Extra](https://github.com/PengZixuan30/Games_AI-Extra) plugin — waypoint management and position tracking, and (since 0.6.4) whitelist management (`get_whitelist_name`, `add_to_whitelist`, `remove_from_whitelist`) and `search_minecraft_wiki`. Install it to get these tools.

### Built-in Tools

The GamesAI plugin provides many built-in tools, listed in the table below. If you want more tools, you can [submit a suggestion](https://github.com/PengZixuan30/Games_AI/issues/new), use [Custom Tools via Config File](#custom-tools-via-config-file), or [register tools from your own MCDR plugin](#custom-tools-in-your-mcdr-plugin).

<details>
<summary>Click to view all built-in tools</summary>

|Tool ID|Parameters|Description|
|:---:|:---:|:---|
|get_online_players|None|Get the list of currently online players. Depends on the `online_player_api` plugin; falls back to an RCON `list` query when RCON is running.|
|get_player_position|`player`|Get a player's position and dimension. Depends on the `minecraft_data_api` plugin; automatically disabled if unavailable.|
|calculator|`expression`|A simple mathematical expression calculator.|
|item_caculator|`expression`, `single_limit`|A mathematical expression calculator that converts results into Minecraft item notation (shulker boxes, stacks, items). Automatically adapts to stack size; defaults to 64 if not specified.|
|ai_read_data|`key`|Read a single entry from the database.|
|ai_read_all_keys|None|Get all keys from the database.|
|ai_read_all_data|None|Read all key-value pairs from the database at once.|
|ai_write_data|`key`, `value`|Write a data entry to the database (overwrite mode).|
|ai_add_data|`key`, `value`|Write a data entry to the database (append mode).|
|read_skills|`skills`|Read a registered skill instruction file to guide AI behavior for specific tasks.|
|write_skills|`skills`, `summary`, `content`|Create or overwrite a skill file and register it in the skills index.|
|modify_skills|`skills`, `summary`, `content`|Modify an existing skill file and update its summary in the index.|
|delete_skills|`skills`|Delete a skill file and remove it from the skills index.|
|read_custom_tools|None|Read the current content of the custom `tools.py` file.|
|modify_custom_tools|`tools`|Replace the entire custom `tools.py` file with new code.|
|append_custom_tools|`tools`|Append new tool code to the end of the custom `tools.py` file.|
|setting_timer|`duration`|Pause execution for the specified number of seconds before continuing.|
|reload_plugin|None|Hot-reload the plugin to apply configuration, skills, and custom tools changes without losing chat history. See [Hot Reload](#hot-reload).|
|ai_del_data|`key`|Delete a data entry from the database.|
|bot_chat|`message`|Make the Mineflayer bot send a message in Minecraft chat.|
|bot_whisper|`username`, `message`|Make the bot send a private message to a player.|
|bot_get_state|None|Get the bot's full state (30+ fields).|
|bot_call_action|`action`, `params`|Send arbitrary action to the bot (goto, dig, place, attack, etc.).|
|run_mineflayer_bot|None|Start the Mineflayer bot if not running. Requires the configured `permission` level.|
|stop_mineflayer_bot|None|Stop the Mineflayer bot. Requires the configured `permission` level.|
|delegate_to_bot|`task`|Delegate a complex Minecraft task to the autonomous bot controller.|

> [!NOTE]
> Since 0.6.4, tools with a `perm` above the requesting player's permission level are not offered to the AI at all. Tools that write/delete data, manage skills, manage custom tools, or start/stop the bot require the configured `permission` level.

</details>

### Custom Tools via Config File

Customize tools by editing the `config/games_ai/tools/tools.py` file.

Let's start by looking at the default content:

```python
from mcdreforged.command.command_source import CommandSource
from games_ai.games_ai_tool import register_tool

@register_tool(description="My Custom Tool")
def my_custom_tool(source: CommandSource, ai_prefix: str):
    return "Tool execution completed"
```

> [!IMPORTANT]
> The `from games_ai.games_ai_tool import register_tool` import and the `@register_tool` decorator above the function definition **must** be present.

> [!TIP]
> In version 0.5.7+, the AI can autonomously **read, modify, and append** the custom tools file using the `read_custom_tools`, `modify_custom_tools`, and `append_custom_tools` tools. Just ask the AI to add a new tool for you — it will read the current file, write the new code, and apply changes via [Hot Reload](#hot-reload).

The `description` parameter is mandatory and tells the AI what the tool does. The `parameters` dictionary (optional) defines the arguments the AI should pass in, following the [OpenAI function calling schema](https://platform.openai.com/docs/guides/function-calling). The function signature must include `source: CommandSource` and `ai_prefix: str` as the first two parameters, followed by any custom parameters defined in `parameters`.

Since 0.6.4, the optional `perm` parameter sets the minimum permission level required for the tool to be offered to the player's AI — an `int`, or a zero-argument callable returning an `int` (e.g. `get_plugin_config_perm`, which follows the plugin's `permission` config dynamically). It defaults to `0` (available to everyone):

```python
from games_ai.games_ai_tool import register_tool, get_plugin_config_perm

@register_tool(description="Admin-only tool", perm=get_plugin_config_perm)
def my_admin_tool(source: CommandSource, ai_prefix: str):
    return "Only visible to players with the configured permission level"
```

Tools above the player's level are not passed to the AI at all; still keep a runtime `source.get_permission_level()` check inside the function for safety.

> [!TIP]
> Add the `@register_bot_tool()` decorator (from `games_ai.games_ai_tool`) alongside `@register_tool` to make the tool available to the autonomous Mineflayer Bot controller. Without it, the tool can only be used through `!!ask` by the chat AI.

### Custom Tools in Your MCDR Plugin

If you are developing a separate MCDR plugin, you can register tools directly from your plugin code without touching `tools.py`:

```python
from games_ai.games_ai_tool import register_tool, register_bot_tool

@register_tool(
    description="Description of your custom tool",
    parameters={...}  # optional
)
@register_bot_tool()  # optional — makes the tool available to the Mineflayer Bot controller
def my_plugin_tool(source: CommandSource, ai_prefix: str, ...):
    source.reply(f'{ai_prefix}Running my tool...')
    return "Result of the tool"
```

> [!IMPORTANT]
> Your plugin **must** require `games_ai >= 0.4.1` in its `mcdreforged.plugin.json` dependencies, otherwise the import will fail. If you use `@register_bot_tool()`, the minimum version should be `>= 0.6.0`.

Your plugin should list `games_ai` in its `dependencies` in `mcdreforged.plugin.json` to ensure GamesAI is loaded first:

```json
{
    "id": "my_plugin",
    "dependencies": {
        "mcdreforged": ">=2.15.0",
        "games_ai": ">=0.4.1"
    }
}
```

Tools registered this way are identical to built-in tools — the AI can call them directly, and you can mark them as bot-accessible with `@register_bot_tool()` if needed. Since 0.6.4, the optional `perm` parameter (an `int` or a zero-argument callable such as `get_plugin_config_perm`) controls which permission level the tool is offered at.

> [!NOTE]
> Since 0.6.4, any plugin that registers tools via `@register_tool` is **automatically reloaded** during `!!gamesai reload` so its tool code stays fresh — no `register_self()` call required. Use `register_self()` only if your plugin needs custom reload logic or wants to be reloaded without registering tools. See [Making Your MCDR Plugin Follow GamesAI Hot Reload](#making-your-mcdr-plugin-follow-gamesai-hot-reload).

If you want your plugin to be **automatically reloaded** when GamesAI runs `!!gamesai reload` even without registering tools (e.g. a skills-only plugin), or you need custom reload logic, call `register_self()` in your plugin's `on_load`:

```python
from games_ai.register_extra_plugin import register_self

def on_load(server, old):
    register_self(server.get_self_metadata().id)
```

This ensures your plugin is reloaded alongside GamesAI's configuration and tools, so any tool code changes take effect immediately. See [Hot Reload](#hot-reload) for more details.

### Built-in Skills

GamesAI ships with two **built-in skills** that the AI automatically reads before performing related operations:

| Skill File | Description |
|---|---|
| `skills_management.md` | Guides the AI on how to read, write, modify, and delete skill files correctly. |
| `custom_tools_management.md` | Guides the AI on how to read, modify, and append custom tool code safely. |
| `mineflayer_bot_guide.md` | Guides the AI on how to control the Mineflayer bot (available only when the bot is running). |

> [!TIP]
> Skills are like SOPs (Standard Operating Procedures) for the AI — they ensure the AI follows the correct workflow every time.

### Add Skills via Config File

You can create custom skill files to guide how the AI handles specific tasks — such as whitelist management, fake player control, and more.

Skills files are stored in `config/games_ai/skills/` as Markdown (`.md`) files. To register a skill, edit `config/games_ai/skills/skills.json`. The following is an example configuration (`whitelist.md` and `player.md` are example filenames only — they are not built-in files):

```json
[
    {
        "file": "whitelist.md",
        "description": "Read this skill before managing the whitelist"
    },
    {
        "file": "player.md",
        "description": "Read this skill before controlling fake players"
    }
]
```

- **`file`** — the skill filename (relative to the `skills` folder).
- **`description`** — a short hint shown to the AI, explaining when to read this skill.

When a skill is registered, it appears in the AI's system prompt. The AI can then use the **`read_skills`** tool to read the full contents of any skill file before performing related tasks.

### Register Skills in Your MCDR Plugin

You can register skill files programmatically from your own MCDR plugin so they appear in the AI's system prompt automatically:

```python
from games_ai.external_skills_loader import register_skills

def on_load(server, old):
    register_skills(
        file_name="my_skill.md",
        description="Read this skill before performing XYZ operations",
        content="""## My Skill

This skill guides the AI to...
- Step 1: ...
- Step 2: ...
"""
    )
```

> [!IMPORTANT]
> Your plugin **must** require `games_ai >= 0.6.1` in its `mcdreforged.plugin.json` dependencies.

- **`file_name`** — the skill's filename (used by the AI's `read_skills` tool to locate it).
- **`description`** — a short hint shown to the AI, explaining when to read this skill.
- **`content`** — the full Markdown content of the skill file.

Skills registered this way are identical to those defined in `skills.json` — they appear in the AI's system prompt under "Available skills" and are readable via the `read_skills` tool. If you also want your plugin to auto-refresh during GamesAI hot reload, see [Making Your MCDR Plugin Follow GamesAI Hot Reload](#making-your-mcdr-plugin-follow-gamesai-hot-reload).

## Hot Reload

GamesAI provides a comprehensive hot-reload mechanism that lets you apply configuration, tool, and skill changes without restarting the server.

### Triggering a Hot Reload

Hot reload can be triggered in the following ways:

|Method|Description|
|---|---|
|`!!gamesai reload`|Run by an admin to reload all configuration, tools, and skills.|
|`!!gamesai config set <key> <value>`|Automatically triggers a reload after modifying a config value.|
|AI tool `reload_plugin`|Called by the AI after modifying tool code or skill files to ensure changes take effect immediately.|
|`!!aibot set <key> <value>`|Automatically triggers a reload after modifying Bot configuration.|

### What Happens During a Hot Reload

When a hot reload is performed, the plugin executes the following steps in order:

1. **Re-read the configuration file** (`config/games_ai/config.json`) — Applies all changes to `prefix`, `permission`, `max_history`, `all_ai`, `default_ai`, etc.
2. **Re-register all tools (0.6.4+)** — Completely clears the tool registry and rebuilds it from every source: built-in tools are replayed from recorded registrations, custom `tools.py` tools are re-imported, and plugins that registered tools are reloaded so their registration code runs again (see steps 4 and 6).
3. **Reload Skills** (`config/games_ai/skills/skills.json`) — Refreshes the skill index; the available skills list in the AI's system prompt is updated synchronously.
4. **Reload Custom Tools** (`config/games_ai/tools/tools.py`) — Hot-loads custom tool code without restarting MCDR.
5. **Restart the Mineflayer Bot** (if enabled) — Stops the existing Bot process and WebSocket connection, then restarts with the new configuration.
6. **Reload Plugins that Registered Tools & Registered Extension Plugins** — Reloads every third-party plugin that registered tools via `@register_tool` (tracked automatically since 0.6.4) plus every plugin in `REGISTER_PLUGIN_LIST` ([see below](#making-your-mcdr-plugin-follow-gamesai-hot-reload)). Failed or missing plugins are removed from the reload list.
7. **Dispatch the `games_ai.reload` Event** — Notifies all other MCDR plugins that are listening for this event ([see below](#responding-to-hot-reload-via-event-listening)).

> [!NOTE]
> Hot reload **does not** clear players' chat history.

### Making Your MCDR Plugin Follow GamesAI Hot Reload

If you are developing an MCDR plugin that depends on GamesAI (e.g., registering custom tools or skills), you may want your plugin to refresh alongside GamesAI during a hot reload. GamesAI offers two approaches:

#### Approach 1: Auto-Reload with `register_self()` (Recommended)

This is the simplest approach. Call `register_self()` in your plugin's `on_load` to add your plugin to GamesAI's reload list:

> [!NOTE]
> Since 0.6.4, plugins that register tools via `@register_tool` are reloaded automatically during hot reload (they are tracked by the tool registry), so `register_self()` is only needed for plugins that don't register tools (e.g. skills-only plugins) or need custom reload logic.

```python
from games_ai.register_extra_plugin import register_self

def on_load(server, old):
    register_self(server.get_self_metadata().id)
```

Each time `!!gamesai reload` is executed, your plugin will be automatically reloaded by MCDR (via `server.reload_plugin()`). If the reload fails, the plugin is unloaded and removed from the reload list.

If your plugin needs **custom reload logic** (beyond the default `reload_plugin`), you can pass a custom reloader function as the second argument. Besides regular functions, you can also pass a method (`self.xxx`) or a lambda expression:

```python
from mcdreforged.command.command_source import CommandSource
from games_ai.register_extra_plugin import register_self

def my_reloader(source: CommandSource):
    # Custom reload logic
    server = source.get_server()
    server.logger.info("Executing my custom reload logic...")
    # e.g., re-read your own config, rebuild database connections, etc.

def on_load(server, old):
    register_self(server.get_self_metadata().id, my_reloader)
```

> [!IMPORTANT]
> The custom reloader function's **first parameter must be `CommandSource`** (as shown by `source` in the example above). GamesAI passes the command source that triggered the hot reload to your function.

When the custom reloader raises an exception, the plugin is automatically unloaded and removed from the reload list, with the failure reason recorded in the log.

#### Approach 2: Responding to Hot Reload via Event Listening

If you don't want your plugin to be unloaded/reloaded, but only want to be notified when GamesAI finishes a hot reload and perform some logic, you can listen for the `games_ai.reload` event:

```python
from mcdreforged.api.all import *

def on_load(server: PluginServerInterface, old):
    server.register_event_listener("games_ai.reload", on_gamesai_reload)

def on_gamesai_reload(server: PluginServerInterface):
    server.logger.info("GamesAI hot reload completed, syncing my state...")
    # e.g., re-read GamesAI's latest configuration
    # e.g., refresh my cached tool list
```

> [!NOTE]
> The first argument to the event callback is always `PluginServerInterface`, automatically prepended by MCDR.

> [!TIP]
> The `games_ai.reload` event is dispatched **after** the reload is complete, so listeners always see the latest reloaded state.

### Comparison of the Two Approaches

`register_self()` behaves differently depending on whether a second argument (custom reloader) is passed:

|Feature|`register_self()` without reloader|`register_self()` with custom reloader|Listening to `games_ai.reload` Event|
|---|---|---|---|
|When it fires|During reload (Step 6)|During reload (Step 6)|After reload completes (Step 7)|
|Plugin behavior|MCDR unloads then reloads (`on_load` re-runs)|Plugin stays loaded; only custom function runs|Plugin unaffected|
|Failure handling|Plugin unloaded, removed from reload list|Plugin unloaded, removed from reload list|Exception does not unload plugin|
|Tools/Skills|Auto re-registered by `on_load`|No re-registration needed (plugin not unloaded, registrations persist)|Not needed|
|Best for|Plugins that need a full code refresh|Lightweight operations like re-reading config or refreshing caches|Plugins that only need a notification or state sync|

> [!NOTE]
> Tools (`@register_tool`) and Skills (`register_skills()`) registered with GamesAI are tied to the lifecycle of the plugin that registered them. As long as the plugin is not unloaded by MCDR, the registered tools and skills remain valid. Therefore, **no re-registration is needed** when using a custom reloader.

## Troubleshooting

### `!!ask` Errors

|Symptom|Likely Cause|Solution|
|---|---|---|
|HTTP 400|Malformed request body|Check `extra_body` format matches your API provider's spec.|
|HTTP 401|Invalid API key|Verify `api_key` in your AI configuration.|
|HTTP 404|Model not found|Check `ai_model` name is correct for your provider.|
|HTTP 429|Rate limit exceeded|Wait and retry, or upgrade your API plan.|
|Timeout / no response|Network issue or slow API|Use `!!gamesai speedtest` to check latency. Try a different model.|
|"Unknown function" reply|AI called a tool that doesn't exist|This is usually harmless — the AI will retry with a different approach.|

### Mineflayer Bot Errors

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

### Logging & Debugging

- Enable debug mode: `!!gamesai debug` — shows full AI prompts and tool call results.
- Mineflayer bot logs are prefixed with `[Mineflayer]` in the MCDR console.
- OpenAI SDK HTTP logs are routed to the MCDR console automatically (see [OpenAI Logging Bridge](#3-openai-logging-bridge)).
- If all else fails, check `config/games_ai/config.json` for misconfiguration.

## What's New

### Version 0.6.4

#### 🎯 Highlights

- **🔐 Permission-Based AI Tool System** — `@register_tool` now accepts a `perm` parameter; tools above the requesting player's permission level are not even offered to the AI. `perm` supports a callable (e.g. `get_plugin_config_perm`) so it follows the `permission` config dynamically.
- **♻️ Full Tool Re-Registration on Hot Reload** — `!!gamesai reload` now completely clears and rebuilds the tool registry: built-in tools are replayed, custom `tools.py` is re-imported, and third-party plugins that registered tools are actually reloaded so their tool code refreshes.
- **🧰 Tool Set Adjustments** — Whitelist tools (`get_whitelist_name`, `add_to_whitelist`, `remove_from_whitelist`) and `search_minecraft_wiki` moved to [GamesAI-Extra](https://github.com/PengZixuan30/Games_AI-Extra); `get_online_players` falls back to an RCON `list` query when `online_player_api` is unavailable.

#### 1. Permission-Based AI Tool System

`register_tool(description=..., perm=..., parameters=...)` — `perm` can be an `int` or a zero-argument callable returning an `int` (default `0` = everyone). Before each `!!ask`, the plugin builds the tool list from the registry and only passes tools whose `perm` is at or below the player's permission level; the runtime permission check inside each tool function still applies. Built-in tools that manage data, skills, custom tools, or the bot now use `get_plugin_config_perm` (the configured `permission` value, read at request time). This fixes the old behavior where every tool was offered to every player.

#### 2. Full Tool Re-Registration on Hot Reload

`!!gamesai reload` now performs a complete tool reset:

- **Built-in tools** — re-registered from recorded registration closures (no module re-execution, so the bot process and WebSocket handles are unaffected);
- **Custom `tools.py`** — old external tools are removed and the file is re-imported, so deleted tools actually disappear;
- **Third-party plugins** — plugins that registered tools via `@register_tool` are tracked by top-level module name and reloaded by MCDR, re-running their import/`on_load` registration code.

This replaces the previous approach, which used `importlib.import_module` on already-loaded modules (a no-op that silently dropped all built-in tools). See [What Happens During a Hot Reload](#what-happens-during-a-hot-reload).

#### 3. Tool Set Adjustments

- Whitelist tools (`get_whitelist_name`, `add_to_whitelist`, `remove_from_whitelist`) and `search_minecraft_wiki` moved to the [GamesAI-Extra](https://github.com/PengZixuan30/Games_AI-Extra) plugin.
- `get_online_players` now falls back to an RCON `list` query when the `online_player_api` plugin is not installed but RCON is running.

#### 4. Fixes

- Fixed `perm=plugin_config.allow_permission` being captured at import time — permission is now resolved lazily at request time.
- Fixed the broken reload logic that cleared `TOOL_SCHEMAS` and called `importlib.import_module` on already-imported modules (built-in tools disappeared after a reload).
- Removed leftover `tr_key` parameters that crashed tool registration with a `TypeError`.
- Merged the extension-plugin reload list with the tool-registering plugin list, with failure isolation (`REGISTER_PLUGIN_LIST.pop` / `TOOL_PLUGIN_IDS.discard`).

### Version 0.6.3

#### 🎯 Highlights

- **🔧 Mineflayer Version Compatibility Auto-Repair** — When the Minecraft server is upgraded beyond the installed mineflayer's support (`Server version 'X' is not supported`), the plugin now automatically refreshes the npm dependencies and restarts the bot. Stale installations created by older plugin versions are refreshed once on the next launch.
- **🔒 Permission Checks for Bot Start/Stop Tools** — The AI tools `run_mineflayer_bot` (`bot_start`) and `stop_mineflayer_bot` (`bot_stop`) now require the configured permission level, matching the `!!aibot join` / `!!aibot leave` commands.
- **🕐 Wait for Server Start** — The bot now waits for the Minecraft server to start before launching, so it no longer fails to connect when MCDR boots before the server.
- **📦 Clean Extension Unload** — Unloading the plugin also unloads every external plugin that called `register_self()`, with per-plugin failure isolation.

#### 1. Mineflayer Version Compatibility Auto-Repair

Fixes the `Server version 'X' is not supported. Latest supported version is ...` error (e.g. after upgrading the Minecraft server to a newer version). The plugin detects the error, runs `npm install` to refresh `mineflayer`/`minecraft-data` and friends to the latest versions, then restarts the bot automatically. Refreshes are guarded by a 10-minute cooldown and at most 3 attempts per session. See [Mineflayer Bot Errors](#mineflayer-bot-errors).

#### 2. Permission Checks for Bot Start/Stop Tools

The AI tools that start/stop the Mineflayer bot (`bot_start` / `bot_stop`) now verify the requesting player's permission level against the configured `permission` value, so players without permission can no longer start or stop the bot through the AI. The `!!aibot join` / `!!aibot leave` commands already had this check since 0.6.0.

#### 3. Wait for Server Start before Launching the Bot

`_run_mineflayer_bot` now checks whether the Minecraft server is running first. If the server is not running (e.g. MCDR boots before the server starts), the plugin waits in the background and launches the Mineflayer bot automatically once the server is up — no more "bot fails to connect because the server wasn't ready" at startup. The wait is cancelled cleanly if the plugin is unloaded, and repeated launch requests while waiting are ignored.

#### 4. Unload Registered Extension Plugins on Plugin Unload

When the plugin itself is unloaded, all external plugins that called `register_self()` are unloaded as well, each wrapped in its own error handling so one failing plugin never blocks the others. (The unload loop itself has existed since 0.6.1; 0.6.3 hardens it with failure isolation and result checking.)

### Version 0.6.2

#### 🎯 Highlights

- **📍 Player Position Query** — New `get_player_position` tool to query online players' coordinates and dimension (requires `minecraft_data_api`)
- **📖 Forced Skill Reading** — `!!ask /<skill> <content>` syntax to force the AI to read a specific skill file first
- **📡 Reload Event** — `games_ai.reload` event dispatched after `!!gamesai reload`, other plugins can listen for state sync
- **📚 Hot Reload Docs** — Comprehensive [Hot Reload](#hot-reload) chapter added to README

#### 1. New Tool: `get_player_position`

Query an online player's coordinates (x, y, z) and dimension (Overworld/Nether/End). Requires the `minecraft_data_api` plugin. Bot-accessible (`@register_bot_tool`).

#### 2. Forced Skill Reading: `!!ask /<skill>`

Players can use `!!ask /skill_name <content>` to force the AI to read a specific skill file via the `read_skills` tool before responding. The plugin validates the skill file exists and provides feedback. Ideal for scenarios requiring strict SOP adherence.

#### 3. `games_ai.reload` Event

After each `!!gamesai reload`, the plugin dispatches a `games_ai.reload` event carrying the `CommandSource` that triggered the reload. Other MCDR plugins can register event listeners to sync state when GamesAI hot-reloads. See [Hot Reload](#hot-reload).

### Version 0.6.1

#### 🎯 Highlights

- **🔌 Extension Plugin System** — `register_self()` and `register_skills()` APIs for MCDR plugin developers
- **🛡️ Input Validation** — Bot username validated on `!!aibot join`
- **📋 Logging Improvements** — Detailed logs for registered plugin reload/unload lifecycle

#### 1. Extension Plugin System

Third-party MCDR plugins can now integrate more deeply with GamesAI:

- **`register_self(plugin_id)`** — Call in your plugin's `on_load` to have it automatically reloaded when `!!gamesai reload` runs. This is essential for plugins that register custom tools and need to pick up config/Skills changes after AI modifications. See [Hot Reload](#hot-reload).
- **`register_skills(file_name, description, content)`** — Register skill files programmatically from your plugin code, without manually editing `skills.json`. Skills appear in the AI's system prompt and are readable via the `read_skills` tool.

#### 2. Validation & Stability

- Bot username is now validated on `!!aibot join` — rejects usernames with invalid characters (non `[a-zA-Z0-9_]`).
- Fixed a bug where iterating `REGISTER_PLUGIN_LIST` while removing items could skip entries.
- Added comprehensive logging for extension plugin lifecycle (reload/unload status).

### Version 0.6.0

#### 🎯 Highlights

- **🤖 Mineflayer Bot** — Fully autonomous Minecraft bot with AI-driven control via WebSocket
- **⚙️ Configuration Overhaul** — Type-adaptive config, `!!aibot` management, input validation
- **📋 Logging Bridge** — OpenAI/httpx SDK logs seamlessly routed to the MCDR logger

#### 1. Mineflayer Bot Integration

The biggest feature in 0.6.0: a fully autonomous Minecraft bot powered by Mineflayer, controlled by AI through a WebSocket command interface.

**Supported actions** (20+): `goto` (A\* pathfinding), `efly` (elytra flight), `dig`, `place`, `attack`, `useOn`, `equip`/`unequip`, `mount`/`dismount`, `craft`, container & furnace management, `lookAt`, `setControlState`, and more.

**Extended `get_state`**: 30+ fields — position, yaw/pitch, velocity, armor (head/chest/legs/feet), oxygen, experience, world time, weather, dimension, sleeping status, and more.

**Custom physics engine**: Knockback response (via `entity_velocity` packets) and entity collision/cramming. Physics automatically pauses during pathfinding to avoid interference.

**Bot management**:
- `!!aibot join` / `!!aibot leave` — lifecycle control
- `!!aibot set username/password/auth` — configure bot identity with validation
- `bot_start` / `bot_stop` AI tools for autonomous control
- `delegate_to_bot` — hand off complex tasks to the autonomous controller

**Other improvements**: Death auto-respawn, physics enabled by default, `path_update` noPath detection for unreachable destinations, `§` character stripping from chat messages.

#### 2. Configuration System Overhaul

- **Type-adaptive `set_config`**: `!!gamesai config set` now reads the existing value's type and auto-converts the new value to match. Setting a float to `"20"` stays float, bool stays bool, etc. Type mismatch errors are caught and reported.
- **`!!aibot set` command**: Manage bot username, password, and auth without editing JSON manually. Username/password validated to `[a-zA-Z0-9_]`, auth restricted to `microsoft`/`mojang`/`offline`.

#### 3. OpenAI Logging Bridge

> [!NOTE]
> This completely resolves the long-standing issue where raw OpenAI SDK logs would interfere with the MCDR console input and cause display glitches.

The `openai` and `httpx` Python loggers are now fully redirected to the MCDR logger:
- All HTTP request/response logs appear in the MCDR console
- Original handlers cleared and propagation disabled — no duplicate stderr output

## Acknowledgements & Disclaimer

Special thanks to [WangHai Server](https://github.com/Wanghai-Server) for providing the foundation for testing this plugin.

Special thanks to [william-song-shy (William Song)](https://github.com/william-song-shy) for suggesting the `!!ask` no-history mode.

Special thanks to [ZhangZuoqian (张作乾)](https://github.com/ZhangZuoqian) for suggesting the `!!gamesai speedtest` command.

All content generated by AI (LLM) models is unrelated to this plugin.

All consequences arising from custom tools are unrelated to this plugin.

## Sponsorship & Contributors

Sponsorship address: [Afdian](https://ifdian.net/a/yello)

Those who sponsor GamesAI will appear in the following sponsor list (currently no sponsors):

| # | Sponsor | Amount | Date |
|---|---------|--------|------|
| - | - | - | - |

## License

MIT License, Copyright (c) 2026 yello

<div align = "center">

---

[Back to Top](#gamesai-for-mcdreforged)

</div>
