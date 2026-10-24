# Generated from games_ai/ai/games_ai_tool.py by tools/build_tool_stubs.py -- do not edit.
from ..core.config import plugin_config as plugin_config
from ..core.permission import TOOL_DENIED_LEVEL as TOOL_DENIED_LEVEL, has_permission as has_permission
from .external_skills_loader import read_external_skills as read_external_skills
from _typeshed import Incomplete
from dataclasses import dataclass
from mcdreforged.command.command_source import CommandSource as CommandSource
from typing import Callable, ParamSpec, TypeVar

_P = ParamSpec('_P')
_R = TypeVar('_R')
_ARCHIVE_SUFFIXES: Incomplete

def packed_plugin_file() -> str | None:
    """The archive this module is running from, or ``None`` for an unpacked (directory) install.

    ``__file__`` inside a packed plugin is
    ``<plugins>/Something.mcdr/games_ai/ai/games_ai_tool.py``, so the first parent with an archive
    suffix is the file MCDR loaded. Walking up (rather than counting ``dirname`` calls) keeps this
    correct wherever the module sits inside the package -- it moved once already.
    """

@dataclass
class ToolHandler:
    func: Callable
    schema: dict
    perm: int | Callable[[], int]
    execute_in_hub: bool = ...
    def resolve_perm(self) -> int: ...

_TOOL_REGISTRY: dict[str, ToolHandler]
TOOL_SCHEMAS: list[dict]
_REREGISTER_CALLS: dict[str, Callable[[], None]]
_BOT_REREGISTER_CALLS: dict[str, Callable[[], None]]
TOOL_PLUGIN_IDS: set[str]

def _is_builtin_module(func: Callable) -> bool: ...
def _build_schema(func_name: str, description: str, parameters: dict | None) -> dict: ...
def register_tool(*, description: str, perm: int | Callable[[], int] | None = 0, parameters: dict | None = None, execute_in_hub: bool = False) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    '''Register one function as a tool the model may call.

    The decorated function keeps its own signature. The plugin supplies its first two parameters
    -- ``source: CommandSource`` (the source that triggered the request) and ``ai_prefix: str``
    (the name to reply with) -- and everything after them is the tool\'s own arguments, declared
    in ``parameters`` and passed in that order.

    :param description: what the model reads to decide whether to call the tool. It is sent
        verbatim, so write it as a prompt for the model, not as a note for a human: when to use
        it, what has to happen first, and what it returns when it fails.
    :param parameters: the tool\'s arguments as an OpenAI function-calling JSON Schema
        (``{"type": "object", "properties": {...}, "required": [...]}``). Omit it for a tool with
        no arguments; an argument with a default must not be listed in ``required``.
    :param perm: the minimum MCDR permission level at which the tool is *offered* -- an ``int``,
        or a zero-argument callable such as :func:`get_plugin_config_perm` to follow
        ``config.json``. Above the caller\'s level the tool never reaches the model; keep the check
        inside the function as well, because the call runs on behalf of the asking player.
    :param execute_in_hub: where the tool runs when several instances share one AI. ``False``
        (default) means the asking player\'s own server: the instance uploads its tool list and a
        call is routed back there. ``True`` means this instance, the one running the AI -- its
        files, its database, its bot -- and the tool is then offered for every request.
    :return: the decorated function, unchanged. The string it returns is the whole result the
        model sees, so return the content, what was done, or a readable reason for a failure
        rather than raising; text for the player goes through ``source.reply(f"{ai_prefix}...")``
        and is never shown to the model.

    Stack :func:`register_bot_tool` under it to let the autonomous controller call the tool too.
    '''
def get_tool_handler(name: str) -> ToolHandler | None: ...
def get_tool_schemas_for_perm(perm_level: int) -> list[dict]: ...
def get_hub_tool_schemas_for_perm(perm_level: int) -> list[dict]:
    """The tools the hub itself offers for one permission level.

    Only :attr:`ToolHandler.execute_in_hub` tools: everything else describes the server the
    player is on, and that server advertises its own copies (see
    :func:`get_local_tool_schemas_for_perm`).
    """
def get_local_tool_schemas_for_perm(perm_level: int) -> list[dict]:
    """The tools this instance would run on its own side, for one permission level.

    This is what a client uploads with a crossing request: the hub adds the list to its own
    hub-bound tools, so the model only ever sees tools that one of the two can really run.
    """
def get_request_tool_schemas(perm_level: int, uploaded: list[dict] | None = None) -> list[dict]:
    """The tool list of one request.

    ``uploaded`` is the list a client sent with its request, or None for a request that was
    made here: a local request runs everything itself, so it is offered everything. For a
    crossing request the hub owns its hub-bound tools (permission-filtered as always) and the
    origin owns the rest, which is why an uploaded copy never replaces a name the hub already
    has and a tool neither side has is never advertised.
    """
def _schema_name(schema) -> str:
    """The function name of one tool schema (empty for anything that is not a schema)."""
def get_plugin_config_perm() -> int:
    """The configured ``permission`` level, for a ``perm=`` that follows the config.

    ``@register_tool(perm=get_plugin_config_perm)`` reads it again on every request, so changing
    ``permission`` in ``config.json`` needs no code change.
    """
def _regex_replace_file(path: str, old_string: str, new_string: str) -> tuple[int, str, str]:
    """
    Replace text in a file, treating ``old_string`` as a Python regular expression.

    Falls back to a literal (non-regex) replacement when the pattern does not compile or
    matches nothing, so a plain-text edit containing characters such as ``(`` or ``.``
    still works. Backreferences (``\\1``, ``\\g<name>``) are interpreted in regex mode only.

    :return: ``(replacements, mode, error)`` — ``error`` is empty on success.
    """

_BOT_SAFE_TOOL_NAMES: set[str]

def register_bot_tool() -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Also hand one registered tool to the autonomous bot controller.

    Stack it under ``@register_tool``. The controller calls its tools from an unsupervised loop,
    so mark only tools that are safe to run that way.
    """
def get_bot_tool_schemas() -> list[dict]: ...
def reset_all_tools() -> None: ...
def get_online_players(source: CommandSource, ai_prefix: str): ...
def calculator(source: CommandSource, ai_prefix: str, expression: str): ...
def item_caculator(source: CommandSource, ai_prefix: str, expression: str, single_limit: int = 64): ...
def _skill_file_name(skills) -> tuple[str | None, str]:
    """Validate a skill file name coming from the model; return ``(name, error)``.

    The tool argument is model-generated, so an absolute path or a ``..`` component would let
    a skill edit read, overwrite or delete files outside the skills folder. Only a plain file
    name inside that folder is accepted; ``.md`` is appended when it is missing.
    """
def _skill_file_path(skills) -> tuple[str | None, str]:
    """The path of one skill file under this instance's skills folder (see the name check)."""
def read_skills(source: CommandSource, ai_prefix: str, skills: str): ...
def write_skills(source: CommandSource, ai_prefix: str, skills: str, summary: str, content: str): ...
def modify_skills(source: CommandSource, ai_prefix: str, skills: str, old_string: str, new_string: str, summary: str = ''): ...
def delete_skills(source: CommandSource, ai_prefix: str, skills: str): ...

_MAX_SAFE_TIMER_SECONDS: int

def setting_timer(source: CommandSource, ai_prefix: str, duration: int, allow_long_wait: bool = False): ...
def read_custom_tools(source: CommandSource, ai_prefix: str): ...
def modify_custom_tools(source: CommandSource, ai_prefix: str, old_string: str, new_string: str): ...
def append_custom_tools(source: CommandSource, ai_prefix: str, tools: str): ...
def reload_plugin(source: CommandSource, ai_prefix: str): ...
def get_player_position(source: CommandSource, ai_prefix: str, player: str): ...
