import importlib.util
import os
import sys
from typing import Callable

from .config import plugin_config
from .games_ai_tool import _TOOL_REGISTRY, TOOL_SCHEMAS

_external_tool_names: set[str] = set()

def _clear_external_tools():
    global _external_tool_names
    for name in list(_external_tool_names):
        handler = _TOOL_REGISTRY.get(name)
        if handler is not None:
            if handler.schema in TOOL_SCHEMAS:
                TOOL_SCHEMAS.remove(handler.schema)
            del _TOOL_REGISTRY[name]
    _external_tool_names.clear()

def load_external_tools(log: Callable[..., None] | None = None) -> tuple[list[str], list[str]]:
    tools_path = plugin_config.tools_path

    if not os.path.isfile(tools_path):
        if log:
            log(f"[tools_interpreter] External tools file not found: {tools_path}")
        return [], []

    _clear_external_tools()

    if "external_tools" in sys.modules:
        del sys.modules["external_tools"]

    before: set[str] = set(_TOOL_REGISTRY.keys())

    try:
        spec = importlib.util.spec_from_file_location("external_tools", tools_path)
        if spec is None or spec.loader is None:
            if log:
                log(f"[tools_interpreter] Cannot create module spec from: {tools_path}")
            return [], []

        module = importlib.util.module_from_spec(spec)
        sys.modules["external_tools"] = module
        spec.loader.exec_module(module)
    except Exception as e:
        if log:
            log(f"[tools_interpreter] Failed to load external tools: {e}")
        return [], []

    after: set[str] = set(_TOOL_REGISTRY.keys())
    new_tool_names: set[str] = after - before
    _external_tool_names.update(new_tool_names)

    loaded: list[str] = sorted(new_tool_names)

    rejected: list[str] = []
    for attr_name in dir(module):
        if attr_name.startswith("_"):
            continue
        obj = getattr(module, attr_name)
        if callable(obj) and attr_name not in _TOOL_REGISTRY:
            rejected.append(attr_name)

    if rejected and log:
        log(
            "[tools_interpreter] Functions in external tools.py WITHOUT "
            f"@register_tool() decorator (REJECTED): {rejected}"
        )

    if loaded and log:
        log(f"[tools_interpreter] Successfully loaded external tools: {loaded}")
    if not loaded and not rejected and log:
        log("[tools_interpreter] No new tools found in external tools.py")

    return loaded, rejected
