# Custom Tools Management Guide

This skill describes how to read and modify the custom tools file (`tools.py`) to extend the AI's capabilities with new tool functions.

> [!IMPORTANT]
> **Confirm the requirements with the user before writing any tool code.** Behaviour, parameters, permission level and the expected return value must be clear — ask first, then implement (see [Step 0](#step-0-ask-the-user-first-mandatory)).

---

## Available Tools

| Tool | Purpose |
|------|---------|
| `read_custom_tools` | Read the current content of the custom tools file |
| `modify_custom_tools` | Edit the custom tools file by regular-expression replacement (`old_string` → `new_string`) |
| `append_custom_tools` | Append new tool code to the end of the custom tools file |

---

## Custom Tools File Location

The custom tools file is located at:

```
config/games_ai/tools/tools.py
```

This file is loaded on every plugin reload. Tools defined here are registered alongside the built-in tools and become available to the AI immediately after a reload.

Beside it the plugin keeps a generated `games_ai/` folder of type stubs (`.pyi`) — that is what an editor resolves `games_ai.*` from while this file is edited. It is not a tool module: never edit or delete it (the plugin rewrites it on load), and never import anything from it.

---

## File Structure Rules

### Import Requirements

Every custom tools file MUST include these imports at the top:

```python
from mcdreforged.command.command_source import CommandSource
from games_ai.ai.games_ai_tool import register_tool
```

An existing file may import the older flat path instead (`from games_ai.games_ai_tool import ...`) — that module is kept as a compatibility re-export, so such a file works unchanged and must not be "fixed". Write new imports as above.

### Tool Registration Pattern

Each tool function MUST be decorated with `@register_tool(...)`. The decorator parameters are:

- **description** (required): A clear description of what the tool does. This is what the AI reads to decide when to call the tool.
- **parameters** (optional): JSON Schema for function parameters.
- **execute_in_hub** (optional, default `false`): which machine runs the tool when several instances share one AI — see [Cluster Scope](#cluster-scope-execute_in_hub).
- **perm** (optional): The minimum MCDR permission level required for the tool to be offered to the player's AI. Can be an `int` or a zero-argument callable returning an `int`. Defaults to `0` (available to everyone). Use `get_plugin_config_perm` (imported from `games_ai.ai.games_ai_tool`) to make the tool follow the plugin's `permission` config value dynamically:

```python
from mcdreforged.command.command_source import CommandSource
from games_ai.ai.games_ai_tool import register_tool, get_plugin_config_perm

@register_tool(description="Admin-only tool", perm=get_plugin_config_perm)
def my_admin_tool(source: CommandSource, ai_prefix: str):
    return "Only visible to players with the configured permission level"
```

Note: tools with a `perm` above the requesting player's level are not passed to the AI at all, so the model cannot even see or call them. You should still keep the runtime permission check inside the function for safety.

Every tool function MUST accept these two parameters:
- `source: CommandSource` — the command source that triggered the AI request
- `ai_prefix: str` — the AI's display name prefix for replying to the player

### Basic Template

```python
from mcdreforged.command.command_source import CommandSource
from games_ai.ai.games_ai_tool import register_tool

@register_tool(description="Description of what this tool does")
def my_tool(source: CommandSource, ai_prefix: str):
    source.reply(f"{ai_prefix}Doing something...")
    # Tool logic here
    return "Result string returned to the AI"
```

### Tool with Parameters

```python
@register_tool(description="Description of the tool", parameters={
    "type": "object",
    "properties": {
        "param_name": {
            "type": "string",
            "description": "What this parameter is for"
        }
    },
    "required": ["param_name"]
})
def my_tool(source: CommandSource, ai_prefix: str, param_name: str):
    # Use param_name
    return f"Result: {param_name}"
```

### Cluster Scope (`execute_in_hub`)

When several MCDR instances share one AI (a cross-server cluster), every tool runs on exactly one machine, and this flag picks which:

- **`false` (default)** — the tool describes **the server the player is on**. The instance that asked uploads its tool list with the request, and a call is routed back and executed **there**, with that machine's `source.get_server()`, its plugins, its commands and its permission table.
- **`true`** — the tool belongs to **the instance that runs the AI** (the hub): its skill files, its public database, its bot, its own `tools.py`. It is offered for every request no matter which instance the player is on, and always runs on the hub.

Which one to write:

- touches files under `config/games_ai/` of the AI instance, the public database, the bot, or is pure computation → `execute_in_hub=True`;
- reads or changes the player's world, players, other plugins or server commands → keep the default;
- **never promise a tool that needs the asking player's server.** If the tool has to read the world, the player list, another plugin or run commands on the machine the player is on, do not write it here: this file belongs to the AI instance, and a tool written here either runs on the hub (`execute_in_hub=True`) or is only visible to players asking on the hub. Tell the user instead that the tool has to be added to that instance's own `config/games_ai/tools/tools.py` by hand — GamesAI cannot write another instance's file;
- **the file you are editing lives on the hub**, so a tool appended here with the default flag is usable **only by players asking on the hub**. If everyone should have it, either pass `execute_in_hub=True`, or tell the user the same code has to be added on the other instances;
- **nothing syncs this file.** Every instance keeps its own `config/games_ai/tools/tools.py`; if the user wants the same tool everywhere, they have to copy the file to the other instances themselves and reload them there.

### Important Rules

1. **Function names must be unique** — they cannot conflict with built-in tool names or other custom tools.
2. **Always reply to the player** using `source.reply(f"{ai_prefix}...")` to show progress.
3. **Return a string** — this is sent back to the AI as the tool result. Make it informative and actionable.
4. **Permission checks** — use `source.get_permission_level()` to restrict sensitive operations.
5. **Access other plugins** — use `source.get_server().get_plugin_instance('plugin_id')` to interact with other MCDR plugins.
6. **Pick the cluster scope on purpose** — the default runs the tool where the asking player is; pass `execute_in_hub=True` for a tool that belongs to the AI instance (its files, database or bot). A tool appended here without the flag only works for players asking on the hub, because this file lives there (see [Cluster Scope](#cluster-scope-execute_in_hub)).

---

## Workflow for Modifying Custom Tools

### Step 0: Ask the User First (MANDATORY)

**Never write a line of tool code before the requirements are confirmed.** A tool is written once and then runs unattended on the server, so guessing here creates broken or unsafe tools. Ask the user first — in their own language, in one short message — and wait for the answer.

Required questions (ask only the ones the user has not already answered):

| # | Question | Why it matters |
|---|----------|----------------|
| 1 | **What exactly should the tool do?** Ask for the concrete behaviour, with an example input and the expected output | The `description` and the whole implementation depend on it |
| 2 | **Which parameters does it take, and are they required or optional?** Confirm names, types and defaults | Becomes the JSON `parameters` schema and the function signature |
| 3 | **Who may use it?** Should only admins/players with the configured `permission` level be able to call it, or everyone? | Decides `perm=get_plugin_config_perm` plus the runtime check |
| 4 | **Does it need other MCDR plugins or external services?** (e.g. `minecraft_data_api`, `online_player_api`, RCON, the internet) | Decides the imports, the availability check and the error message when the dependency is missing |
| 5 | **What should it return to you?** What information must the tool result contain so you can answer the player afterwards? | Decides the return string — remember only a string comes back, and it must be in English |
| 6 | **What is the tool called?** Propose a `snake_case` function name and confirm it does not collide with an existing tool | The function name *is* the tool name the model will call |
| 7 | **Is there an existing tool that should be extended instead of a new one being added?** | Avoids duplicated tools |
| 8 | **Should it work for players on every instance, or only where the player is?** Ask this only when more than one instance shares this AI | Decides `execute_in_hub`; the `tools.py` you edit lives on the hub, so a tool meant for another instance's players has to be marked `true` or installed there |

Rules:

- If the user's request is already complete, do not re-ask everything — briefly restate what you understood (behaviour, parameters, permission level) and ask for a yes/no confirmation instead;
- Ask about **risky or irreversible** behaviour explicitly (deleting files/blocks, kicking players, running commands, spending money, writing to the database) and make sure the user really wants it and at which permission level;
- Do not silently invent parameters, defaults or permission levels the user did not mention — ask instead;
- Only after the user confirmed: continue with Step 1.

### Step 1: Always Read First

Before modifying, use `read_custom_tools` to see the current file content. Never modify blindly — you might overwrite existing tools.

### Step 2: Plan Your Changes

Now design the tool function(s) against the confirmed requirements:

- Which parameters did the user confirm, and which are optional with which defaults?
- Which other plugins does it depend on, and what should happen when they are missing?
- Which permission level did the user choose?
- What should the return value tell the AI (in English)?

### Step 3A: Append New Tools (Recommended)

If you only need to **add** new tool functions, use `append_custom_tools`. Only provide the new function's code — it will be appended to the end of the file. This is safer and simpler than editing existing code.

### Step 3B: Edit the File with a Regex Replacement

Use `modify_custom_tools` to change part of the file. It takes:

| Parameter | Meaning |
|-----------|---------|
| **old_string** | A Python regular expression matched against the whole file |
| **new_string** | The replacement text; backreferences like `\1` or `\g<name>` are supported |

Rules:

- every match is replaced, so include enough context in `old_string` to hit only the code you mean;
- if the pattern is not a valid regular expression, or matches nothing, the same text is retried as a **literal** string;
- if nothing matches, the tool reports an error and the file is left untouched — always copy `old_string` from what `read_custom_tools` returned;
- to add lines around existing code, match an anchor and keep it with a backreference, e.g. `old_string`: `(@register_tool\(description="My Custom Tool"\))`, `new_string`: `\1  # edited`;
- only replace whole tool functions or their bodies; never leave the file with unbalanced brackets or broken decorators.

### Step 4: Reload the Plugin

After modifying, call `reload_plugin` to apply the changes. This will reload the plugin and register your new tools.

---

## Best Practices

1. **Ask before you build** — confirm behaviour, parameters, permission level and return value with the user *before* writing any code (see Step 0). Never guess on the user's behalf.
2. **Read before write** — always call `read_custom_tools` before `modify_custom_tools` or `append_custom_tools`.
3. **Prefer append over replace** — when adding new tools, use `append_custom_tools` instead of `modify_custom_tools` to avoid accidentally deleting existing code.
4. **Make surgical edits** — with `modify_custom_tools`, replace exactly the lines you mean (a precise `old_string` regex, or a literal snippet copied from the file); an edit that does not match anything changes nothing and tells you so.
4. **Follow existing patterns** — look at how built-in tools are structured and follow the same conventions.
5. **Handle errors gracefully** — wrap risky operations in try/except and return meaningful error messages.
6. **One modification at a time** — make focused, incremental changes rather than rewriting everything at once.
7. **Test your logic** — ensure the Python code is syntactically correct and all imports are valid.
