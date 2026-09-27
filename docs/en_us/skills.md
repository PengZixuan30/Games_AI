<div align="center">

# Skills

English  |  [简体中文](../zh_cn/skills.md)  |  [繁體中文](../zh_tw/skills.md)

[Back to README](../../README.md)

</div>

A skill is a **standard operating procedure** written for the AI: a Markdown file describing how a class of tasks must be done and which constraints apply. The division of labour with tools is simple — **tools give the AI abilities, skills give it procedures**.

## 1. What problem it solves

The model already knows how to call `modify_custom_tools`, but it does not know that on *your* server "confirm the exact player name before touching the whitelist" or "verify a project is unclaimed before deleting it". Those rules live in skill files; the AI reads the relevant one before doing the task, and then follows your process instead of guessing.

The important part is **lazy loading**: a skill's body does not occupy context permanently, it enters the conversation only when read. So:

- the **skills index** (`skills.json`) holds only the one line saying *when* to read it — that part is **always** in the system prompt and is a fixed cost;
- the **body** is loaded when you or the AI decide it is needed, and stays in that round's context.

Which means the `description` decides whether the AI remembers the skill at the right moment.

## 2. Built-in skills

The plugin ships three skill files that the AI reads automatically before the matching operations. You do not register them yourself:

| Skill file | Content |
|---|---|
| `skills_management.md` | How to read, write, modify and delete skill files |
| `custom_tools_management.md` | How to safely read, edit and append custom tool code. It contains a mandatory step: confirm the requirement, parameters, permission level and expected return value with the user **before** writing any code |
| `mineflayer_bot_guide.md` | How to drive the Mineflayer bot (it only appears in the index while the bot is running) |

These three are read-only references you normally never need to change.

## 3. Adding your own skills

Skill files live in:

```
config/games_ai/skills/
```

The format is Markdown (`.md`). Registering one means adding an entry to `skills.json` in the same directory:

```json
[
    {
        "file": "whitelist.md",
        "description": "Read this skill file whenever the whitelist is added to, removed from or queried"
    }
]
```

- **`file`** — the skill file name, relative to the `skills` directory;
- **`description`** — the one line shown to the AI saying **when** to read it. This is the most important line in the whole file: it sits permanently in the system prompt and is the only basis the AI has for deciding whether to read.

Once registered, the skill name appears in the AI's system prompt and the AI can read the full text with the `read_skills` tool before doing the task.

### How to write a `description`

| Writing | Effect |
|---|---|
| `"whitelist stuff"` | Too vague; the AI cannot tell when to trigger it |
| `"Read this skill file whenever the whitelist is added to, removed from or queried"` | Lists the **triggering actions**, so the AI recalls it at the right moment |
| `"Read this skill file whenever a bot is created, controlled or deleted"` | "Must" marks it as mandatory procedure, which constrains the model better than "consider" |
| `"Full item bulk-category reference list"` | Not "when to read" but "what this is" — right for **reference** skills the AI reads when it needs the data |

In one sentence: **action skills state when they must be read; reference skills state what they contain**.

### How to write the body

The body is an operating procedure for the model, not documentation for humans. Rules of thumb:

- open with one sentence stating the **scope** ("This skill applies when ...");
- use an ordered list for the steps, one action per step;
- call out **irreversible operations** separately and require confirmation ("before deleting, repeat the project name and ask the player to confirm");
- say **what to do on failure** ("if the tool returns a permission error, tell the player the required level and do not retry");
- name **actual tools** (`modify_custom_tools`) so the model can map the procedure onto its callable list.

> [!TIP]
> A skill does not need to be long. A clear 20-line procedure constrains the model better than a vague 200-line document.

## 4. Letting the AI maintain skills

Three tools let the AI work on skill files:

| Tool | Purpose | Permission |
|---|---|---|
| `write_skills` | Creates or **overwrites** a skill file and registers it in the index (`skills`, `summary`, `content`) | config permission |
| `modify_skills` | **Precisely edits** an existing skill by regular-expression replacement (`old_string`, `new_string`, optional `summary`) | config permission |
| `delete_skills` | Deletes a skill file and removes its index entry | config permission |

Together with the built-in `skills_management.md`, the AI reads before writing. `write_skills` is overwrite semantics, so editing an existing skill should go through `modify_skills` — that way one bad write cannot throw away the whole file.

**In practice** you simply tell the AI what you want, for example:

```
!!ask Write me a skill: from now on, whenever a player asks for a teleport, you must first
      confirm the target player is online and repeat the coordinates back, and only execute
      after confirmation. Use the file name tp_safety.md
```

The AI first reads `skills_management.md` to learn the procedure, then writes the file with `write_skills` and registers its `description` in the index. You will see it in `skills.json` afterwards.

## 5. Registering skills from your own MCDR plugin

A plugin can inject skills programmatically at load time, without touching disk:

```python
from games_ai.external_skills_loader import register_skills

def on_load(server, old):
    register_skills(
        file_name="my_skill.md",
        description="Read this skill file before performing operation XYZ",
        content="""## My skill

This skill tells the AI how to ...
- Step 1: ...
- Step 2: ...
"""
    )
```

- **`file_name`** — the skill name the AI uses when calling `read_skills`;
- **`description`** — same role as the field of the same name in `skills.json`;
- **`content`** — the full text.

Skills registered this way are **exactly equivalent** to those in `skills.json`: they appear in the available-skills list of the system prompt and can be read with `read_skills`. The only difference is that they live **in memory**, so they must be registered again after a plugin reload.

> [!IMPORTANT]
> If your plugin registers skills but no tools, it will not follow GamesAI's hot reload automatically; use `register_self()` for that — see [Hot Reload](hot-reload.md#hot-reload).

## 6. How skills and tools relate

| | Tools | Skills |
|---|---|---|
| Nature | Functions that can be called | Documents that get read |
| When it enters context | The **declaration** (with parameters and description) is always present; the return value enters after a call | The index is always present; the **body** enters only after `read_skills` |
| What it decides | What the AI **can** do | How the AI **should** do it |
| Cost of getting it wrong | The call fails or does nothing | The AI follows its own judgement, with unpredictable results |
| Typical content | `modify_custom_tools` | "Read the file and confirm with the user before editing" |

In practice the two always come in pairs: **a tool for the ability, a skill for the procedure**. Tools without skills mean the AI has abilities but no process; skills without tools mean it knows the process but cannot act.

## 7. Troubleshooting

| Symptom | What to check |
|---|---|
| The AI never reads a skill | Does the `description` in `skills.json` state the trigger? Does the file name match the `.md` on disk exactly, including case? |
| Selecting a skill with `/skillname` says "skill file not found" | The comparison uses the `file` value from the index; check the `.md` extension and the spelling |
| The skill body was edited but behaviour did not change | Bodies are loaded **at read time**, so edits apply immediately; if you changed the `skills.json` index instead, run `!!gamesai reload` |
| Suspecting the skill never entered context | Turn on `!!gamesai debug`: the `read_skills` call and its result are logged; `!!ask context` also shows the context growing |
