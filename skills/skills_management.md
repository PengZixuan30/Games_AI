# Skills Management Guide

This skill describes how to use the skills-related tools (`read_skills`, `write_skills`, `modify_skills`, `delete_skills`) to manage skill files on the Minecraft server.

---

## Available Tools

| Tool | Purpose |
|------|---------|
| `read_skills` | Read the content of a skill file |
| `write_skills` | Create a new skill file (or overwrite an existing one) |
| `modify_skills` | Edit an existing skill file by regular-expression replacement |
| `delete_skills` | Delete a skill file |

---

## When to Use Skills Tools

### MUST read skills BEFORE:
- Performing **any multi-step task** that involves chaining multiple tool calls together
- Executing workflows that have a corresponding skill file (check the skills index to discover available skills)

### How to discover and read skills:
Skills are managed dynamically — the list of available skills is NOT fixed. To find out what skills exist:
1. Check the skills index (`skills.json`) to see all registered skills and their descriptions
2. Use `read_skills` with the **exact filename** to load a skill's full content

Each skill file contains detailed instructions, command formats, and step-by-step procedures for a specific workflow.

---

## Writing a New Skill

Use `write_skills` with these parameters:
- **skills**: The filename (e.g., `my_skill.md`)
- **summary**: A one-line description of when to read this skill (e.g., "When doing X, you must read this skill file")
- **content**: The full Markdown content of the skill, including instructions, command formats, and examples

The summary will be stored in the skills index (`skills.json`) so the AI can discover available skills.

---

## Modifying an Existing Skill

Use `modify_skills` with a **regular-expression replacement** instead of rewriting the whole file:

| Parameter | Meaning |
|-----------|---------|
| **skills** | The exact file name (e.g., `my_skill.md`) |
| **old_string** | A Python regular expression matched against the whole file |
| **new_string** | The replacement text; backreferences like `\1` or `\g<name>` are supported |
| **summary** | Optional: a new one-line description for the skills index. Omit it to keep the current summary |

Rules:

- Every match of `old_string` is replaced, so anchor your pattern (`^`/`$` with care) when it must hit one place only;
- If the pattern is not a valid regular expression, or matches nothing, the same text is retried as a **literal** string — so plain text containing `(`, `.` or `*` still works;
- If nothing matches at all, the tool reports an error and the file is left untouched — `old_string` must be copied from the current file content (read it with `read_skills` first);
- To insert something, match a small unique anchor and use a backreference to keep it, e.g. `old_string`: `(## Notes)`, `new_string`: `\1\n\nExtra paragraph`;
- The result message tells you how many occurrences were replaced and whether regex or literal matching was used.

---

## Deleting a Skill

Use `delete_skills` with only the **skills** parameter (the filename). This removes both the skill file and its index entry.

---

## After Modifying Skills

After completing any `write_skills`, `modify_skills`, or `delete_skills` operations, you MUST call `reload_plugin` to apply the changes. When batching multiple skill changes, do all operations first, then call `reload_plugin` once at the end.

---

## Best Practices

1. **Always read before acting**: If a task involves a known skill area, read the corresponding skill file FIRST.
2. **Batch and reload**: When creating/modifying/deleting multiple skills, do all operations first, then call `reload_plugin` once.
3. **One skill at a time**: Each tool call works on exactly one skill file.
4. **Use descriptive summaries**: When writing/modifying skills, the summary should clearly state the trigger condition (e.g., "When doing X, you must read this skill file").
5. **Edit, don't rewrite**: Prefer `modify_skills` with a precise `old_string` pattern over `write_skills` when changing an existing skill — a full overwrite is how working content gets lost.
6. **Write in Markdown**: Skill content should be well-structured Markdown with clear headings, code blocks for commands, and step-by-step instructions.
7. **Filename convention**: Use lowercase with underscores, ending in `.md` (e.g., `my_feature.md`).
