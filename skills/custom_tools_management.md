# Custom Tools Management Guide

This skill describes how to read and modify the custom tools file (`tools.py`) to extend the AI's capabilities with new tool functions.

---

## Available Tools

| Tool | Purpose |
|------|---------|
| `read_custom_tools` | Read the current content of the custom tools file |
| `modify_custom_tools` | Replace the entire custom tools file with new code |
| `append_custom_tools` | Append new tool code to the end of the custom tools file |

---

## Custom Tools File Location

The custom tools file is located at:

```
config/games_ai/tools/tools.py
```

This file is loaded on every plugin reload. Tools defined here are registered alongside the built-in tools and become available to the AI immediately after a reload.

---

## File Structure Rules

### Import Requirements

Every custom tools file MUST include these imports at the top:

```python
from mcdreforged.command.command_source import CommandSource
from games_ai.games_ai_tool import register_tool
```

### Tool Registration Pattern

Each tool function MUST be decorated with `@register_tool(...)`. The decorator parameters are:

- **description** (required): A clear description of what the tool does. This is what the AI reads to decide when to call the tool.
- **parameters** (optional): JSON Schema for function parameters.

Every tool function MUST accept these two parameters:
- `source: CommandSource` — the command source that triggered the AI request
- `ai_prefix: str` — the AI's display name prefix for replying to the player

### Basic Template

```python
from mcdreforged.command.command_source import CommandSource
from games_ai.games_ai_tool import register_tool

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

### Important Rules

1. **Function names must be unique** — they cannot conflict with built-in tool names or other custom tools.
2. **Always reply to the player** using `source.reply(f"{ai_prefix}...")` to show progress.
3. **Return a string** — this is sent back to the AI as the tool result. Make it informative and actionable.
4. **Permission checks** — use `source.get_permission_level()` to restrict sensitive operations.
5. **Access other plugins** — use `source.get_server().get_plugin_instance('plugin_id')` to interact with other MCDR plugins.

---

## Workflow for Modifying Custom Tools

### Step 1: Always Read First

Before modifying, use `read_custom_tools` to see the current file content. Never modify blindly — you might overwrite existing tools.

### Step 2: Plan Your Changes

Understand what the user wants and design the tool function(s). Consider:
- What parameters does it need?
- What other plugins does it depend on?
- What permissions should be required?
- What should the return value tell the AI?

### Step 3A: Append New Tools (Recommended)

If you only need to **add** new tool functions, use `append_custom_tools`. Only provide the new function's code — it will be appended to the end of the file. This is safer and simpler than a full overwrite.

### Step 3B: Full File Replacement

Use `modify_custom_tools` only when you need to rewrite the entire file. You must include:
1. All existing imports
2. All existing tool functions (if you want to keep them)
3. Your new tool function(s)

### Step 4: Reload the Plugin

After modifying, call `reload_plugin` to apply the changes. This will reload the plugin and register your new tools.

---

## Best Practices

1. **Read before write** — always call `read_custom_tools` before `modify_custom_tools` or `append_custom_tools`.
2. **Prefer append over replace** — when adding new tools, use `append_custom_tools` instead of `modify_custom_tools` to avoid accidentally deleting existing code.
3. **Preserve existing code** — when using `modify_custom_tools`, keep all working tools and only add/change what's needed.
4. **Follow existing patterns** — look at how built-in tools are structured and follow the same conventions.
5. **Handle errors gracefully** — wrap risky operations in try/except and return meaningful error messages.
6. **One modification at a time** — make focused, incremental changes rather than rewriting everything at once.
7. **Test your logic** — ensure the Python code is syntactically correct and all imports are valid.
