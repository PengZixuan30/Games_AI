<div align="center">

# GamesAI

English  |  [简体中文](/README.zh-CN.md)  |  [繁體中文](/README.zh-TW.md)

[Report an Issue](https://github.com/PengZixuan30/Games_AI/issues/new)  |  [Share an Idea](https://github.com/PengZixuan30/Games_AI/discussions/new/choose)

</div>

> [!NOTE]
> Welcome to version 0.5.3! This release fixes a **critical history corruption bug** (HTTP 400 error) and implements **per-user tool call tracking**. See [What's New](#whats-new)

> [!IMPORTANT]
> Version 0.5.0 introduced custom tool support and created a `tools.py` file in the config folder. Version 0.5.1 introduced the prompt file feature and created a `prompt` folder. Version 0.5.2 introduced the Skills system and created a `skills` folder. **Version 0.5.3** fixes a critical message history bug and improves tool call tracking. See [Skills](#skills).

<details>
<summary>Table of Contents (click to expand)</summary>

- [GamesAI](#gamesai)
  - [Installation](#installation)
  - [Usage](#usage)
  - [Configuration](#configuration)
    - [1.prefix](#1prefix)
    - [2.permission](#2permission)
    - [3.max\_history](#3max_history)
    - [4.all\_ai](#4all_ai)
    - [5.default\_ai](#5default_ai)
  - [Tools, Skills \& Custom Tools](#tools-skills--custom-tools)
    - [Tools](#tools)
    - [Skills](#skills)
    - [Custom Tools](#custom-tools)
  - [What's New](#whats-new)
    - [Version 0.5.3](#version-053)
      - [1. History Corruption Fix (Critical)](#1-history-corruption-fix-critical)
      - [2. Per-User Tool Call Tracking](#2-per-user-tool-call-tracking)
      - [3. Debug Mode Display Fix](#3-debug-mode-display-fix)
    - [Version 0.5.2](#version-052)
      - [1. Skills System](#1-skills-system)
  - [Acknowledgements \& Disclaimer](#acknowledgements--disclaimer)
  - [License](#license)

</details>

## Installation

Run the following command in the MCDR console to install the plugin:

`!!MCDR plugin install games_ai`

---

Alternatively, get it from the [MCDR Plugin Repository](https://mcdreforged.com/plugin/games_ai) and place it in your plugin directory.

If you choose to install manually, install the Python packages `openai` and `requests` first:

```bash
pip install openai requests
```

## Usage

Type `!!gamesai` anywhere to display all available features of this plugin.

<details>
<summary>

All `!!gamesai` Commands (click to expand)</summary>

|Command|Description|
|---|---|
|`!!gamesai clear`|Clear your own chat history. Chat history is unrelated to the public database.|
|`!!gamesai clearall`|Clear all players' chat history. Chat history is unrelated to the public database.|
|`!!gamesai reload`|Reload the plugin configuration file.|
|`!!gamesai check`|Check for plugin updates.|

</details>

---

You can also use `!!ask` directly to ask the AI questions, chat, or ask it to do things for you.

<details>
<summary>

All `!!ask` Commands (click to expand)</summary>

|Command|Description|
|---|---|
|`!!ask <content>`|Ask the AI a question, chat, or ask it to do something. `<content>` is what you want the AI to do or the question you want to ask.|
|`!!ask -m <model> <content>`|Use a specific model to ask the AI a question, chat, or ask it to do something. `<model>` is the AI_ID or nickname of the model you want to use. `<content>` is what you want the AI to do or the question you want to ask.|

</details>

---

Type `!!data` for information about database commands.

> [!TIP]
> The database is automatically created when upgrading to version 0.3.0 or above.

<details>
<summary>

All `!!data` Commands (click to expand)</summary>

|Command|Description|
|---|---|
|`!!data write <key> <value>`|Add a data entry to the public database. `<key>` must not contain spaces; `<value>` can be any string.|
|`!!data add <key> <value>`|Append `<value>` to an existing key in the public database. Creates a new key if it does not exist.|
|`!!data del <key>`|Delete a data entry from the public database, regardless of whether the key exists.|
|`!!data read <key>`|Read the value associated with a key from the public database.|
|`!!data list`|Read all entries in the public database.|
|`!!data list keys`|Read all keys in the public database.|

</details>

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
          "thinking": false
      }
    },
  "default_ai": "<Your AI ID>"
  }
```

---

Below is a brief introduction to each parameter:

<details>

<summary>Click to expand</summary>

### 1.prefix
Type: `str`

Default: `[GamesAI]`

The plugin name used as a prefix in replies. May include Minecraft formatting codes.

### 2.permission
Type: `int`

Default: `3`

The minimum permission level required to execute commands like `!!data`. See the [MCDR Permission Documentation](https://docs.mcdreforged.com/en/latest/permission.html).

### 3.max_history
Type: `int`

Default: `10`

The maximum number of conversation turns retained per player. Unrelated to the public database.

### 4.all_ai
Type: `dict`

Default: see file

All AI configuration entries, consisting of multiple sub-dictionaries. Each sub-dictionary represents one AI model, and its key serves as the plugin's internal AI_ID.

**prompt**: Use this option to write a system prompt for each AI. Use `> xxx.md` to point the prompt to the `config/games_ai/prompt/xxx.md` file (any file type is supported).

**ai_name**: Similar to `prefix`, but set per model. May include Minecraft formatting codes.

**base_url**, **ai_model**, **api_key**: Same as previous related configuration, but now set per model.

**thinking**: Enable or disable the model's thinking/reasoning mode. Defaults to `false` when omitted. Do not enable this for models that do not support a thinking mode — it may cause errors.

### 5.default_ai
Type: `str`

Default: `<Your AI ID>`

The model used when a player simply uses `!!ask`. Should be one of the keys in the `all_ai` dictionary (i.e. the plugin's internal AI_ID). An incorrect value will prevent `!!ask` from working properly.

</details>

## Tools, Skills & Custom Tools

### Tools
The GamesAI plugin provides many built-in tools, listed in the table below. If you want more tools, you can [submit a suggestion](https://github.com/PengZixuan30/Games_AI/issues/new) or use [Custom Tools](#custom-tools).

<details>
<summary>Click to view all built-in tools</summary>

|Tool ID|Parameters|Description|
|:---:|:---:|:---|
|get_online_players|None|Get the list of currently online players. Depends on the `online_player_api` plugin; automatically disabled if unavailable.|
|get_whitelist_name|None|Get the complete server whitelist. Depends on the `whitelist_api` plugin; automatically disabled if unavailable.|
|add_to_whitelist|`name`|Add a player to the whitelist. Depends on the `whitelist_api` plugin; automatically disabled if unavailable.|
|remove_from_whitelist|`name`|Remove a player from the whitelist. Depends on the `whitelist_api` plugin; automatically disabled if unavailable.|
|search_minecraft_wiki|`query`|Let the AI search the Minecraft Wiki for more accurate answers.|
|calculator|`expression`|A simple mathematical expression calculator.|
|item_caculator|`expression`, `single_limit`|A mathematical expression calculator that converts results into Minecraft item notation (shulker boxes, stacks, items). Automatically adapts to stack size; defaults to 64 if not specified.|
|add_pos_pos|`name`, `pos`, `dimension`|Add a waypoint at a specified location. Depends on the `where2go` or `location_marker` plugin; prioritizes `where2go` when both are present; automatically disabled when neither is available.|
|add_pos_here|`name`|Add a waypoint at the player's current location. Automatically disabled when executed from the console. Depends on the `where2go` or `location_marker` plugin; prioritizes `where2go` when both are present; automatically disabled when neither is available.|
|remove_pos|`name`|Delete a waypoint. The `where2go` version automatically converts names to IDs. Depends on the `where2go` or `location_marker` plugin; prioritizes `where2go` when both are present; automatically disabled when neither is available.|
|search_pos|`name`|Search for a waypoint. Depends on the `where2go` or `location_marker` plugin; prioritizes `where2go` when both are present; automatically disabled when neither is available.|
|get_all_pos|None|Get a list of all waypoints. Depends on the `where2go` or `location_marker` plugin; prioritizes `where2go` when both are present; automatically disabled when neither is available.|
|ai_read_data|`key`|Read a single entry from the database.|
|ai_read_all_keys|None|Get all keys from the database.|
|ai_write_data|`key`, `value`|Write a data entry to the database (overwrite mode).|
|ai_add_data|`key`, `value`|Write a data entry to the database (append mode).|
|read_skills|`skills`|Read a registered skill instruction file to guide AI behavior for specific tasks.|
|ai_del_data|`key`|Delete a data entry from the database.|

</details>

### Skills

The Skills system lets you write instruction files to guide how the AI handles specific tasks — such as whitelist management, fake player control, and more.

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

> [!TIP]
> Skills are like SOPs (Standard Operating Procedures) for the AI — they ensure the AI follows the correct workflow every time.

### Custom Tools
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

As you can see, the structure is very simple.

Now I'll show you how to build a real tool. Let's use searching `baidu.com` as an example.

<details>

<summary>Click to expand</summary>

The best way to understand how to implement a Baidu search is to look at the built-in `search_minecraft_wiki` tool in the GamesAI source code:

```python
@register_tool(description="Search Minecraft Wiki for relevant information. Do not use this method to search for non-Minecraft content. If the search results page is returned, you can browse that page first and then perform a more precise query.", tr_key="searching_minecraft_wiki", parameters={
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "The search term, e.g. the name of an item, mob, or game mechanic."
        }
    },
    "required": ["query"]
})
def search_minecraft_wiki(source: CommandSource, ai_prefix: str, query: str):
    source.reply(f'{ai_prefix}{source.get_server().rtr("games_ai.tools.searching_minecraft_wiki", query=query)}')
    lang = source.get_server().get_mcdr_language()
    if lang == "en_us":
        search_url = f"https://minecraft.wiki/?search={query}"
    else:
        search_url = f"https://zh.minecraft.wiki/?search={query}"
    response = requests.get(search_url)
    if response.status_code == 200:
        return f"Search results for {query}:\n{response.content.decode('utf-8')}"
    else:
        return "Unable to access Minecraft Wiki for searching."
```

Let's start by looking at the tool registration. `description` is like a system prompt — it's mandatory and is provided to the AI. `tr_key` is an internal identifier; you do **not** need to include it when writing external `tools.py`. `parameters` defines the arguments the AI should pass in. You can decide whether to include it based on your actual needs. `properties` lists all the input parameters, and `required` specifies which are mandatory. Make sure `properties` and the function's parameter list correspond one-to-one.

For example:

```python
@register_tool(description="Search Baidu")
```

However, searching Baidu obviously requires a search term, so:

```python
@register_tool(description="Search Baidu", parameters={
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "The search term"
        }
    },
    "required": ["query"]
})
```

Great — you now know how to register a tool! Next, write the function definition:

```python
def search_baidu(source: CommandSource, ai_prefix: str, query: str):
```

In the code above, the `source` and `ai_prefix` parameters **must** be included because they are always passed in.

Then write the function body:

```python
def search_baidu(source: CommandSource, ai_prefix: str, query: str):
    ...
    return ...
```

The function body can contain any operations you need. Just remember to always `return` a result — otherwise the AI won't be able to process the output properly.

Complete `tools.py` example:

```python
import requests
from games_ai.games_ai_tool import register_tool

@register_tool(
    description="Use Baidu to search for information on the internet. Use this tool when you need real-time info, news, encyclopedia knowledge, etc.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The keyword or question to search for on Baidu"
            }
        },
        "required": ["query"]
    }
)
def search_baidu(source, ai_prefix: str, query: str):
    source.reply(f'{ai_prefix}Searching Baidu: {query}...')

    try:
        url = "https://www.baidu.com/s"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        response = requests.get(url, params={"wd": query}, headers=headers, timeout=10)

        if response.status_code != 200:
            return f"Baidu search failed, HTTP status code: {response.status_code}"

        # Extract plain text from page (strip HTML tags)
        import re
        text = response.text
        # Remove script and style tag contents
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        # Collapse extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        # Truncate long content (keep first 3000 characters, suitable for AI context)
        max_len = 3000
        if len(text) > max_len:
            text = text[:max_len] + "\n...(content truncated)"

        return f"Baidu search results for 「{query}」:\n{text}"

    except requests.Timeout:
        return "Baidu search request timed out. Please try again later."
    except Exception as e:
        return f"Baidu search error: {str(e)}"
```

</details>

## What's New

### Version 0.5.3

#### 1. History Corruption Fix (Critical)
Fixed a critical bug where `history.append(response_message)` was appending an entire message **list** as a single element into the conversation history. This caused malformed API requests (HTTP 400: `"invalid type: map, expected variant identifier"`) on the second conversation after a tool call. Now correctly appends individual messages via `history.append(user_message)`.

#### 2. Per-User Tool Call Tracking
The global `tool_count` variable has been replaced with a per-user, per-AI dictionary (`user_tool_counts`). Previously, `tool_count` accumulated across all users and conversations without ever resetting, causing the history retention limit (`max_history * 2 + tool_count * 2`) to grow without bound. Now each user's tool count is tracked independently and automatically cleared when their conversation history is cleared via `!!gamesai clear` or `!!gamesai clearall`.

#### 3. Debug Mode Display Fix
Fixed a typo where `debug` (an undefined variable) was used instead of `debug_mode` in the history limit display line. This would have caused a `NameError` at runtime when debug mode was enabled.

### Version 0.5.2

#### 1. Skills System
The Skills system is a new way to teach the AI standardized workflows. By writing Markdown instruction files and registering them in `skills.json`, you can control exactly how the AI behaves for specific tasks (e.g. whitelist management, fake player control). The AI will automatically read the relevant skill file before executing related operations.

- `config/games_ai/skills/skills.json` — skill registration.
- `config/games_ai/skills/*.md` — skill instruction files.
- Built-in `read_skills` tool for the AI to read skills.

Additionally, this release fixes several issues and improves Python 3.14 compatibility.

## Acknowledgements & Disclaimer

Special thanks to the Wanghai Commune server for providing the foundation for testing this plugin.

All content generated by AI (LLM) models is unrelated to this plugin.

All consequences arising from custom tools are unrelated to this plugin.

## License

MIT License, Copyright (c) 2026 yello

<div align = "center">

---

[Back to Top](#gamesai)

</div>
