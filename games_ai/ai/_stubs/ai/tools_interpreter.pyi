# Generated from games_ai/ai/tools_interpreter.py by tools/build_tool_stubs.py -- do not edit.
from ..core.config import plugin_config as plugin_config
from .games_ai_tool import TOOL_SCHEMAS as TOOL_SCHEMAS, _TOOL_REGISTRY as _TOOL_REGISTRY
from typing import Callable

_external_tool_names: set[str]

def _clear_external_tools() -> None: ...
def load_external_tools(log: Callable[..., None] | None = None) -> tuple[list[str], list[str]]: ...
