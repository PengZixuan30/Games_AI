from mcdreforged.command.command_source import CommandSource

from dataclasses import dataclass
from typing import Callable, ParamSpec, TypeVar
import os, json, re, time

from ..core.config import plugin_config
from .external_skills_loader import read_external_skills
from ..core.permission import TOOL_DENIED_LEVEL, has_permission

#: The two decorators below hand the function back unchanged, and these make that visible to a
#: type checker: without them a decorated tool loses its own signature (the decorator's inferred
#: return type is a bare ``Callable``). The generated editor stubs in ``ai/_stubs`` inherit them.
_P = ParamSpec("_P")
_R = TypeVar("_R")

#: The packed archives MCDR installs a plugin as (the same set as ``updater.ARCHIVE_SUFFIXES``;
#: ``updater`` itself cannot be imported here, it is behind the dependency gate).
_ARCHIVE_SUFFIXES = (".mcdr", ".pyz")


def packed_plugin_file() -> str | None:
    """The archive this module is running from, or ``None`` for an unpacked (directory) install.

    ``__file__`` inside a packed plugin is
    ``<plugins>/Something.mcdr/games_ai/ai/games_ai_tool.py``, so the first parent with an archive
    suffix is the file MCDR loaded. Walking up (rather than counting ``dirname`` calls) keeps this
    correct wherever the module sits inside the package -- it moved once already.
    """
    parent = os.path.dirname(os.path.abspath(__file__))
    while True:
        if parent.lower().endswith(_ARCHIVE_SUFFIXES) and os.path.isfile(parent):
            return parent
        upper = os.path.dirname(parent)
        if upper == parent:
            return None
        parent = upper

@dataclass
class ToolHandler:
    func: Callable
    schema: dict
    perm: int | Callable[[], int]
    # True for a tool that must run where the AI runs (the hub): its data, its files and its
    # bot belong to that instance, so a client must hand the call over instead of running it.
    # False means "this instance's own server": a request that arrived from another instance
    # is routed back there (see chat_param's tool dispatch).
    execute_in_hub: bool = False

    def resolve_perm(self) -> int:
        return int(self.perm() if callable(self.perm) else (self.perm or 0))

_TOOL_REGISTRY: dict[str, ToolHandler] = {}
TOOL_SCHEMAS: list[dict] = []

_REREGISTER_CALLS: dict[str, Callable[[], None]] = {}
_BOT_REREGISTER_CALLS: dict[str, Callable[[], None]] = {}
TOOL_PLUGIN_IDS: set[str] = set()


def _is_builtin_module(func: Callable) -> bool:
    mod = getattr(func, "__module__", "") or ""
    return mod == "games_ai" or mod.startswith("games_ai.")


def _build_schema(func_name: str, description: str, parameters: dict | None) -> dict:
    schema: dict = {
        "type": "function",
        "function": {
            "name": func_name,
            "description": description,
        },
    }
    if parameters is not None:
        schema["function"]["parameters"] = parameters
    return schema


def register_tool(*, description: str, perm: int | Callable[[], int] | None = 0, parameters: dict | None = None,
                  execute_in_hub: bool = False) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Register one function as a tool the model may call.

    The decorated function keeps its own signature. The plugin supplies its first two parameters
    -- ``source: CommandSource`` (the source that triggered the request) and ``ai_prefix: str``
    (the name to reply with) -- and everything after them is the tool's own arguments, declared
    in ``parameters`` and passed in that order.

    :param description: what the model reads to decide whether to call the tool. It is sent
        verbatim, so write it as a prompt for the model, not as a note for a human: when to use
        it, what has to happen first, and what it returns when it fails.
    :param parameters: the tool's arguments as an OpenAI function-calling JSON Schema
        (``{"type": "object", "properties": {...}, "required": [...]}``). Omit it for a tool with
        no arguments; an argument with a default must not be listed in ``required``.
    :param perm: the minimum MCDR permission level at which the tool is *offered* -- an ``int``,
        or a zero-argument callable such as :func:`get_plugin_config_perm` to follow
        ``config.json``. Above the caller's level the tool never reaches the model; keep the check
        inside the function as well, because the call runs on behalf of the asking player.
    :param execute_in_hub: where the tool runs when several instances share one AI. ``False``
        (default) means the asking player's own server: the instance uploads its tool list and a
        call is routed back there. ``True`` means this instance, the one running the AI -- its
        files, its database, its bot -- and the tool is then offered for every request.
    :return: the decorated function, unchanged. The string it returns is the whole result the
        model sees, so return the content, what was done, or a readable reason for a failure
        rather than raising; text for the player goes through ``source.reply(f"{ai_prefix}...")``
        and is never shown to the model.

    Stack :func:`register_bot_tool` under it to let the autonomous controller call the tool too.
    """
    def decorator(func: Callable):
        def _apply():
            old = _TOOL_REGISTRY.get(func.__name__)
            if old is not None and old.schema in TOOL_SCHEMAS:
                TOOL_SCHEMAS.remove(old.schema)
            handler = ToolHandler(
                func=func,
                schema=_build_schema(func.__name__, description, parameters),
                perm=perm if callable(perm) else int(perm or 0),
                execute_in_hub=bool(execute_in_hub),
            )
            _TOOL_REGISTRY[func.__name__] = handler
            TOOL_SCHEMAS.append(handler.schema)
        _apply()
        if _is_builtin_module(func):
            _REREGISTER_CALLS[func.__name__] = _apply
        else:
            mod = getattr(func, "__module__", "") or ""
            top = mod.split(".")[0]
            if top and top != "external_tools":
                TOOL_PLUGIN_IDS.add(top)
        return func
    return decorator


def get_tool_handler(name: str) -> ToolHandler | None:
    return _TOOL_REGISTRY.get(name)


def get_tool_schemas_for_perm(perm_level: int) -> list[dict]:
    return [
        handler.schema
        for handler in _TOOL_REGISTRY.values()
        if perm_level >= handler.resolve_perm()
    ]


def get_hub_tool_schemas_for_perm(perm_level: int) -> list[dict]:
    """The tools the hub itself offers for one permission level.

    Only :attr:`ToolHandler.execute_in_hub` tools: everything else describes the server the
    player is on, and that server advertises its own copies (see
    :func:`get_local_tool_schemas_for_perm`).
    """
    return [
        handler.schema
        for handler in _TOOL_REGISTRY.values()
        if handler.execute_in_hub and perm_level >= handler.resolve_perm()
    ]


def get_local_tool_schemas_for_perm(perm_level: int) -> list[dict]:
    """The tools this instance would run on its own side, for one permission level.

    This is what a client uploads with a crossing request: the hub adds the list to its own
    hub-bound tools, so the model only ever sees tools that one of the two can really run.
    """
    return [
        handler.schema
        for handler in _TOOL_REGISTRY.values()
        if not handler.execute_in_hub and perm_level >= handler.resolve_perm()
    ]


def get_request_tool_schemas(perm_level: int, uploaded: list[dict] | None = None) -> list[dict]:
    """The tool list of one request.

    ``uploaded`` is the list a client sent with its request, or None for a request that was
    made here: a local request runs everything itself, so it is offered everything. For a
    crossing request the hub owns its hub-bound tools (permission-filtered as always) and the
    origin owns the rest, which is why an uploaded copy never replaces a name the hub already
    has and a tool neither side has is never advertised.
    """
    if uploaded is None:
        return get_tool_schemas_for_perm(perm_level)
    schemas = get_hub_tool_schemas_for_perm(perm_level)
    known = {_schema_name(schema) for schema in schemas}
    for schema in uploaded:
        name = _schema_name(schema)
        if name and name not in known:
            schemas.append(schema)
            known.add(name)
    return schemas


def _schema_name(schema) -> str:
    """The function name of one tool schema (empty for anything that is not a schema)."""
    if not isinstance(schema, dict):
        return ""
    function = schema.get("function")
    if not isinstance(function, dict):
        return ""
    return str(function.get("name") or "")


def get_plugin_config_perm() -> int:
    """The configured ``permission`` level, for a ``perm=`` that follows the config.

    ``@register_tool(perm=get_plugin_config_perm)`` reads it again on every request, so changing
    ``permission`` in ``config.json`` needs no code change.
    """
    return plugin_config.allow_permission


def _regex_replace_file(path: str, old_string: str, new_string: str) -> tuple[int, str, str]:
    r"""
    Replace text in a file, treating ``old_string`` as a Python regular expression.

    Falls back to a literal (non-regex) replacement when the pattern does not compile or
    matches nothing, so a plain-text edit containing characters such as ``(`` or ``.``
    still works. Backreferences (``\1``, ``\g<name>``) are interpreted in regex mode only.

    :return: ``(replacements, mode, error)`` — ``error`` is empty on success.
    """
    if not old_string:
        return 0, "", "old_string must not be empty"

    try:
        with open(path, mode='r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        return 0, "", f"file not found: {path}"
    except Exception as e:
        return 0, "", f"failed to read {path}: {e}"

    new_content: str | None = None
    count = 0
    mode = ""

    try:
        pattern = re.compile(old_string)
    except re.error:
        pattern = None                                  # not a valid regex: retry it literally

    if pattern is not None:
        try:
            candidate, hits = pattern.subn(new_string, content)
        except re.error as e:
            return 0, "", f"invalid replacement text in new_string: {e}"
        if hits:
            new_content, count, mode = candidate, hits, "regular expression"

    if new_content is None:                             # literal fallback
        try:
            candidate, hits = re.subn(re.escape(old_string), lambda _m: new_string, content)
        except re.error as e:
            return 0, "", f"literal replacement failed: {e}"
        if hits:
            new_content, count, mode = candidate, hits, "literal"

    if new_content is None:
        return 0, "", "old_string did not match anything in the file, nothing was changed"

    try:
        with open(path, mode='w', encoding='utf-8') as f:
            f.write(new_content)
    except Exception as e:
        return 0, "", f"failed to write {path}: {e}"

    return count, mode, ""


_BOT_SAFE_TOOL_NAMES: set[str] = set()


def register_bot_tool() -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Also hand one registered tool to the autonomous bot controller.

    Stack it under ``@register_tool``. The controller calls its tools from an unsupervised loop,
    so mark only tools that are safe to run that way.
    """
    def decorator(func: Callable):
        def _apply():
            _BOT_SAFE_TOOL_NAMES.add(func.__name__)
        _apply()
        if _is_builtin_module(func):
            _BOT_REREGISTER_CALLS[func.__name__] = _apply
        return func
    return decorator


def get_bot_tool_schemas() -> list[dict]:
    return [
        s for s in TOOL_SCHEMAS
        if s.get("function", {}).get("name") in _BOT_SAFE_TOOL_NAMES
    ]


def reset_all_tools():
    _TOOL_REGISTRY.clear()
    TOOL_SCHEMAS.clear()
    _BOT_SAFE_TOOL_NAMES.clear()
    for apply in _REREGISTER_CALLS.values():
        apply()
    for apply in _BOT_REREGISTER_CALLS.values():
        apply()


@register_tool(description="Get the list of players currently online on the server")
@register_bot_tool()
def get_online_players(source: CommandSource, ai_prefix: str):
    server = source.get_server()
    source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.getting_online_players")}')
    __online_players_api = server.get_plugin_instance('online_player_api')
    if __online_players_api is None:
        if server.is_rcon_running():
            return server.rcon_query("list")
        else:
            return "Unable to get the online player list (online_player_api is missing and RCON is not running)"
    online_players = __online_players_api.get_player_list()
    if online_players:
        return ", ".join(online_players)
    else:
        return "No players are online"


@register_tool(description="Evaluate a mathematical expression. Only digits and the + - * / ( ) operators are allowed.", parameters={
    "type": "object",
    "properties": {
        "expression": {
            "type": "string",
            "description": "Mathematical expression to evaluate, e.g. (2+3)*4. Digits and the + - * / ( ) operators only"
        }
    },
    "required": ["expression"]
})
@register_bot_tool()
def calculator(source: CommandSource, ai_prefix: str, expression: str):
    source.reply(f'{ai_prefix}{source.get_server().rtr("games_ai.tools.calculating_expression", expression=expression)}')
    try:
        if not all(c.isdigit() or c in "+-*/(). " for c in expression):
            return "The expression contains illegal characters"
        result = eval(expression)
        return f"Result: {result}"
    except Exception as e:
        return f"Calculation error: {e}"
    
@register_tool(description="Evaluate a mathematical expression and convert the result into boxes (27 stacks), stacks and items.", parameters={
    "type": "object",
    "properties": {
        "expression": {
            "type": "string",
            "description": "Mathematical expression to evaluate, e.g. (2+3)*4. Digits and the + - * / ( ) operators only"
        },
        "single_limit": {
            "type": "integer",
            "description": "Maximum number of items per stack, default 64"
        }
    },
    "required": ["expression"]
})
@register_bot_tool()
def item_caculator(source: CommandSource, ai_prefix: str, expression: str, single_limit: int = 64):
    source.reply(f'{ai_prefix}{source.get_server().rtr("games_ai.tools.calculating_expression", expression=expression)}')
    try:
        if not all(c.isdigit() or c in "+-*/(). " for c in expression):
            return "The expression contains illegal characters"
        result = eval(expression)
        single = result % single_limit
        box = result // (single_limit*27)
        stack = (result - box*single_limit*27 - single) // single_limit
        return f"Result: {result} = {box} box(es) + {stack} stack(s) + {single} item(s)"
    except Exception as e:
        return f"Calculation error: {e}"


def _skill_file_name(skills) -> tuple[str | None, str]:
    """Validate a skill file name coming from the model; return ``(name, error)``.

    The tool argument is model-generated, so an absolute path or a ``..`` component would let
    a skill edit read, overwrite or delete files outside the skills folder. Only a plain file
    name inside that folder is accepted; ``.md`` is appended when it is missing.
    """
    raw = str(skills or "").strip()
    if not raw:
        return None, "a skill file name is required"
    name = raw if raw.endswith(".md") else raw + ".md"
    core = raw[:-3] if raw.endswith(".md") else raw
    invalid = (
        os.path.isabs(name)
        or os.path.basename(name) != name
        or core in (".", "..")
        or name in (".", "..")
        or (len(name) > 1 and name[1] == ":")      # Windows drive prefix
        or "\x00" in name
    )
    if invalid:
        return None, (f"invalid skill file name {skills!r}: use a plain file name inside the "
                      f"skills folder")
    return name, ""


def _skill_file_path(skills) -> tuple[str | None, str]:
    """The path of one skill file under this instance's skills folder (see the name check)."""
    name, error = _skill_file_name(skills)
    if name is None:
        return None, error
    return os.path.join(os.path.dirname(plugin_config.skills_path), name), ""


@register_tool(description="Read one skill file. Required before chaining several tool calls; one skill per call.", execute_in_hub=True, parameters={
    "type": "object",
    "properties": {
        "skills": {
            "type": "string",
            "description": "File name of the skill file to read"
        }
    },
    "required": ["skills"]
})
def read_skills(source: CommandSource, ai_prefix: str, skills: str):
    server = source.get_server()
    source.reply(f"{ai_prefix}{server.rtr("games_ai.tools.reading_skills", skills=skills)}")
    file_name, error = _skill_file_name(skills)
    if file_name is None:
        return f"Failed to read the skill file: {error}"
    errors = []

    external_content = read_external_skills(file_name)
    if external_content is not None:
        return f"Skill file content:\n{external_content}"

    custom_path = os.path.join(os.path.dirname(plugin_config.skills_path), file_name)

    if os.path.isfile(custom_path):
        try:
            with open(custom_path, mode='r', encoding='utf-8') as f:
                return f"Skill file content:\n{f.read()}"
        except Exception as e:
            errors.append(f"custom skill path read failed: {e}")

    _plugin_root = packed_plugin_file()
    if _plugin_root:
        import zipfile
        try:
            with zipfile.ZipFile(_plugin_root, 'r') as zf:
                zip_path = f"skills/{file_name}"
                if zip_path in zf.namelist():
                    content = zf.read(zip_path).decode('utf-8')
                    return f"Skill file content:\n{content}"
                else:
                    errors.append(f"not found in the bundled skills: {zip_path}")
        except (zipfile.BadZipFile, KeyError, OSError) as e:
            errors.append(f"bundled skills read failed: {e}")

    if plugin_config.builtin_skills_dir:
        builtin_path = os.path.join(plugin_config.builtin_skills_dir, file_name)
        try:
            with open(builtin_path, mode='r', encoding='utf-8') as f:
                return f"Skill file content:\n{f.read()}"
        except Exception as e:
            errors.append(f"bundled skills directory read failed: {e}")

    error_detail = "; ".join(errors) if errors else "the file does not exist in any search path"
    return f"Failed to read the skill file: {error_detail}"

@register_tool(description="Create or overwrite one skill file and register its summary in the skills index.", perm=get_plugin_config_perm, execute_in_hub=True, parameters={
    "type": "object",
    "properties": {
        "skills": {
            "type": "string",
            "description": "File name of the skill file to write"
        },
        "summary": {
            "type": "string",
            "description": "One-line summary of the skill, stored in the skills index"
        },
        "content": {
            "type": "string",
            "description": "Full Markdown content of the skill"
        }
    },
    "required": ["skills", "summary", "content"]
})
def write_skills(source: CommandSource, ai_prefix: str, skills: str, summary: str, content: str):
    server = source.get_server()
    source.reply(f"{ai_prefix}{server.rtr("games_ai.tools.writing_skills", skills=skills)}")
    if not has_permission(source):
        return TOOL_DENIED_LEVEL
    skills_path, error = _skill_file_path(skills)
    if skills_path is None:
        return f"Failed to write the skill file: {error}"
    file_name = os.path.basename(skills_path)
    try:
        with open(skills_path, mode='w', encoding='utf-8') as f:
            f.write(content)

        try:
            with open(plugin_config.skills_path, mode='r', encoding='utf-8') as f:
                index_data = json.load(f)
                if not isinstance(index_data, list):
                    index_data = []
        except (FileNotFoundError, json.JSONDecodeError):
            index_data = []

        found = False
        for item in index_data:
            if item.get("file") == file_name:
                item["description"] = summary
                found = True
                break
        if not found:
            index_data.append({"file": file_name, "description": summary})

        with open(plugin_config.skills_path, mode='w', encoding='utf-8') as f:
            json.dump(index_data, f, ensure_ascii=False, indent=4)

        return "Skill file written successfully"
    except Exception as e:
        return f"Failed to write the skill file: {e}"

@register_tool(description=(
    "Edit an existing skill file by regular-expression replacement. "
    "'old_string' is a Python regular expression matched against the whole file and "
    "'new_string' is the replacement (backreferences such as \\1 or \\g<name> are supported); "
    "every match is replaced. If the pattern does not compile or matches nothing, the same "
    "text is retried as a literal string. Always call read_skills first."
), perm=get_plugin_config_perm, execute_in_hub=True, parameters={
    "type": "object",
    "properties": {
        "skills": {
            "type": "string",
            "description": "File name of the skill file to edit"
        },
        "old_string": {
            "type": "string",
            "description": "Regular expression to search for in the skill file"
        },
        "new_string": {
            "type": "string",
            "description": "Replacement text; backreferences like \\1 and \\g<name> are supported"
        },
        "summary": {
            "type": "string",
            "description": "Optional new one-line summary for the skills index; leave empty to keep the current one"
        }
    },
    "required": ["skills", "old_string", "new_string"]
})
def modify_skills(source: CommandSource, ai_prefix: str, skills: str, old_string: str, new_string: str, summary: str = ""):
    server = source.get_server()
    source.reply(f"{ai_prefix}{server.rtr("games_ai.tools.modifying_skills", skills=skills)}")
    if not has_permission(source):
        return TOOL_DENIED_LEVEL
    skills_path, error = _skill_file_path(skills)
    if skills_path is None:
        return f"Failed to modify the skill file: {error}"
    file_name = os.path.basename(skills_path)
    if not os.path.isfile(skills_path):
        return f"Skill file not found: {file_name}. Use read_skills with the exact file name first."

    count, mode, error = _regex_replace_file(skills_path, old_string, new_string)
    if error:
        return f"Failed to modify skill '{file_name}': {error}"

    index_note = ""
    if summary:
        try:
            with open(plugin_config.skills_path, mode='r', encoding='utf-8') as f:
                index_data = json.load(f)
                if not isinstance(index_data, list):
                    index_data = []
        except (FileNotFoundError, json.JSONDecodeError):
            index_data = []

        found = False
        for item in index_data:
            if item.get("file") == file_name:
                item["description"] = summary
                found = True
                break
        if not found:
            index_data.append({"file": file_name, "description": summary})

        with open(plugin_config.skills_path, mode='w', encoding='utf-8') as f:
            json.dump(index_data, f, ensure_ascii=False, indent=4)
        index_note = " The index summary was updated."

    return f"Skill '{file_name}' modified: replaced {count} occurrence(s) by {mode} matching.{index_note}"

@register_tool(description="Delete one skill file together with its skills-index entry.", perm=get_plugin_config_perm, execute_in_hub=True, parameters={
    "type": "object",
    "properties": {
        "skills": {
            "type": "string",
            "description": "File name of the skill file to delete"
        }
    },
    "required": ["skills"]
})
def delete_skills(source: CommandSource, ai_prefix: str, skills: str):
    server = source.get_server()
    source.reply(f"{ai_prefix}{server.rtr("games_ai.tools.deleting_skills", skills=skills)}")
    if not has_permission(source):
        return TOOL_DENIED_LEVEL
    skills_path, error = _skill_file_path(skills)
    if skills_path is None:
        return f"Failed to delete the skill file: {error}"
    file_name = os.path.basename(skills_path)
    if not os.path.isfile(skills_path):
        return f"Skill file not found: {file_name}. Use read_skills with the exact file name first."
    try:
        os.remove(skills_path)

        try:
            with open(plugin_config.skills_path, mode='r', encoding='utf-8') as f:
                index_data = json.load(f)
                if not isinstance(index_data, list):
                    index_data = []
        except (FileNotFoundError, json.JSONDecodeError):
            index_data = []

        index_data = [item for item in index_data if item.get("file") != file_name]

        with open(plugin_config.skills_path, mode='w', encoding='utf-8') as f:
            json.dump(index_data, f, ensure_ascii=False, indent=4)

        return "Skill file deleted successfully"
    except Exception as e:
        return f"Failed to delete the skill file: {e}"
    
_MAX_SAFE_TIMER_SECONDS = 600


@register_tool(description=(
    "Wait for the given number of seconds before continuing. A wait longer than 600 seconds "
    "needs the allow_long_wait flag set to true, otherwise the call is refused."
), execute_in_hub=True, parameters={
    "type": "object",
    "properties": {
        "duration": {
            "type": "number",
            "description": "Seconds to wait"
        },
        "allow_long_wait": {
            "type": "boolean",
            "description": ("Set to true to wait longer than 600 seconds. Leave it off unless a "
                            "long wait was explicitly asked for.")
        }
    },
    "required": ["duration"]
})
@register_bot_tool()
def setting_timer(source: CommandSource, ai_prefix: str, duration: int, allow_long_wait: bool = False):
    server = source.get_server()
    try:
        seconds = float(duration)
    except (TypeError, ValueError):
        return f"Invalid duration {duration!r}: give the number of seconds to wait"
    if seconds < 0:
        return f"Invalid duration {duration!r}: the wait cannot be negative"
    if seconds > _MAX_SAFE_TIMER_SECONDS and not allow_long_wait:
        return (f"Refusing to wait {seconds:g} seconds: durations over {_MAX_SAFE_TIMER_SECONDS} s "
                f"need allow_long_wait=true. Call the tool again with allow_long_wait=true if "
                f"that long wait is intended.")
    source.reply(f"{ai_prefix}{server.rtr("games_ai.tools.setting_timer", duration=duration)}")
    time.sleep(seconds)
    return f"Timer finished after {duration} second(s)"

@register_tool(description="Read the custom tools file (tools.py)", perm=get_plugin_config_perm, execute_in_hub=True)
def read_custom_tools(source: CommandSource, ai_prefix: str):
    server = source.get_server()
    source.reply(f"{ai_prefix}{server.rtr("games_ai.tools.reading_custom_tools")}")
    if not has_permission(source):
        return TOOL_DENIED_LEVEL
    if not os.path.isfile(plugin_config.tools_path):
        return f"Custom tools file not found: {plugin_config.tools_path}"
    try:
        with open(plugin_config.tools_path, mode='r', encoding='utf-8') as f:
            tools_content = f.read()
        return f"Custom tools file content:\n{tools_content}"
    except Exception as e:
        return f"Failed to read the custom tools file: {e}"

@register_tool(description=(
    "Edit the custom tools file (tools.py) by regular-expression replacement. "
    "'old_string' is a Python regular expression matched against the whole file and "
    "'new_string' is the replacement (backreferences such as \\1 or \\g<name> are supported); "
    "every match is replaced. If the pattern does not compile or matches nothing, the same "
    "text is retried as a literal string. Always call read_custom_tools first."
), perm=get_plugin_config_perm, execute_in_hub=True, parameters={
    "type": "object",
    "properties": {
        "old_string": {
            "type": "string",
            "description": "Regular expression to search for in the custom tools file"
        },
        "new_string": {
            "type": "string",
            "description": "Replacement text; backreferences like \\1 and \\g<name> are supported"
        }
    },
    "required": ["old_string", "new_string"]
})
def modify_custom_tools(source: CommandSource, ai_prefix: str, old_string: str, new_string: str):
    server = source.get_server()
    source.reply(f"{ai_prefix}{server.rtr("games_ai.tools.modifying_custom_tools")}")
    if not has_permission(source):
        return TOOL_DENIED_LEVEL
    if not os.path.isfile(plugin_config.tools_path):
        return f"Custom tools file not found: {plugin_config.tools_path}"

    count, mode, error = _regex_replace_file(plugin_config.tools_path, old_string, new_string)
    if error:
        return f"Failed to modify the custom tools file: {error}"
    return (
        f"Custom tools file modified: replaced {count} occurrence(s) by {mode} matching. "
        f"Call reload_plugin to apply the change."
    )

@register_tool(description="Append new tool code to the end of the custom tools file. Read the file and the related skills first.", perm=get_plugin_config_perm, execute_in_hub=True, parameters={
    "type": "object",
    "properties": {
        "tools": {
            "type": "string",
            "description": "Python source code to append; it must be valid Python and register its tools with the @register_tool decorator"
        },
    },
    "required": ["tools"]
})
def append_custom_tools(source: CommandSource, ai_prefix: str, tools: str):
    server = source.get_server()
    source.reply(f"{ai_prefix}{server.rtr("games_ai.tools.appending_custom_tools")}")
    if not has_permission(source):
        return TOOL_DENIED_LEVEL
    if not os.path.isfile(plugin_config.tools_path):
        return f"Custom tools file not found: {plugin_config.tools_path}"
    try:
        with open(plugin_config.tools_path, mode='r', encoding='utf-8') as f:
            existing = f.read()
        new_content = existing.rstrip("\n") + "\n\n" + tools.strip() + "\n"
        with open(plugin_config.tools_path, mode='w', encoding='utf-8') as f:
            f.write(new_content)
        return "Tool code appended successfully"
    except Exception as e:
        return f"Failed to append tool code: {e}"

@register_tool(description="Reload the plugin so that new or changed skills and tools take effect", execute_in_hub=True)
def reload_plugin(source: CommandSource, ai_prefix: str):
    server = source.get_server()
    source.reply(f"{ai_prefix}{server.rtr("games_ai.tools.reloading_plugin")}")
    # No source on purpose: with the AI round's source, the reload command would run with
    # that source's `!!ask ...` Info, and the cluster fan-out would broadcast the ask line to
    # every node (each node then running its own AI round). MCDR uses a PluginCommandSource
    # without an Info instead, so the reload runs here and nothing is fanned out.
    server.execute_command("!!gamesai reload")
    return "Plugin reloaded"


@register_tool(description="Get the position and dimension of a player", parameters={
    "type": "object",
    "properties": {
        "player": {
            "type": "string",
            "description": "Name of the player to query"
        }
    },
    "required": ["player"]
})
@register_bot_tool()
def get_player_position(source: CommandSource, ai_prefix: str, player: str):
    server = source.get_server()
    source.reply(f'{ai_prefix}{server.rtr("games_ai.tools.getting_player_position", player=player)}')
    api = server.get_plugin_instance('minecraft_data_api')
    if api is None:
        return "Unable to get the minecraft_data_api plugin instance; check that it is installed and loaded"
    try:
        data = api.get_player_info(player)
        if data is None:
            return f"Timed out while querying player {player}, please try again later"
        pos = data.get('Pos', [])
        dim_raw = data.get('Dimension', '')
        if not pos or len(pos) < 3:
            return f"Could not parse coordinates from the data of player {player}"
        dim_map = {
            'minecraft:overworld': 'Overworld',
            'minecraft:the_nether': 'The Nether',
            'minecraft:the_end': 'The End',
        }
        dim_name = dim_map.get(dim_raw, dim_raw)
        return f"Player {player} position: ({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f}), dimension: {dim_name}"
    except ValueError as e:
        return f"Failed to query player {player}: {e}"
    except Exception as e:
        return f"Failed to get information for player {player}: {e}"
