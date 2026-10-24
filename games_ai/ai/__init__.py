"""The request path and what the model may call: conversations, the provider client, the
context-window table, the tool registry and the skills index.

This module is the package's front door, and it follows one rule: a name whose module needs a
third-party package is resolved on first use (PEP 562), never at import time. The tool registry,
the tools interpreter, the skills loaders and the generated table need only the standard library
and MCDR, so they are eager; ``chat_param``, ``openai_api`` and ``context_table`` pull
``openai``/``requests`` and are therefore listed in :data:`_LAZY_NAMES` / :data:`_LAZY_MODULES`.
Importing ``games_ai.ai`` has to stay possible on a machine where the plugin is still repairing its
Python packages.
"""
import importlib
from typing import TYPE_CHECKING, Any

from . import context_table_data, external_skills_loader, games_ai_tool, register_extra_plugin
from . import tools_interpreter, tools_stub_files
from .external_skills_loader import EXTERNAL_SKILLS_LIST
from .games_ai_tool import (TOOL_PLUGIN_IDS, get_local_tool_schemas_for_perm,
                            get_plugin_config_perm, get_tool_handler, register_bot_tool,
                            register_tool, reset_all_tools)
from .register_extra_plugin import REGISTER_PLUGIN_LIST
from .tools_interpreter import load_external_tools
from .tools_stub_files import TOOLS_SKELETON, seed_tools_folder

if TYPE_CHECKING:
    # What a type checker reads instead of the runtime ``__getattr__`` below: the names and
    # modules that resolve on first use. The block never runs (``TYPE_CHECKING`` is False), so the
    # dependency gate is untouched -- but an editor now knows the real type of every name this
    # package exports, instead of seeing ``Any``.
    from . import chat_param, context_table, openai_api
    from .chat_param import (ChatParam, NonHistoryChatParam, describe_http_status,
                             register_no_history, set_remote_tool_router, stop_no_history,
                             unregister_no_history)
    from .openai_api import setup_openai_logging

#: Name -> the module that defines it. These modules need a third-party package.
_LAZY_NAMES = {
    "ChatParam": "chat_param",
    "NonHistoryChatParam": "chat_param",
    "describe_http_status": "chat_param",
    "register_no_history": "chat_param",
    "set_remote_tool_router": "chat_param",
    "stop_no_history": "chat_param",
    "unregister_no_history": "chat_param",
    "setup_openai_logging": "openai_api",
}
#: The same modules by name: ``from .ai import chat_param``.
_LAZY_MODULES = {"chat_param", "context_table", "openai_api"}

__all__ = [
    # the modules
    "chat_param", "context_table", "context_table_data", "external_skills_loader",
    "games_ai_tool", "openai_api", "register_extra_plugin", "tools_interpreter",
    "tools_stub_files",
    # the names that need nothing third-party
    "EXTERNAL_SKILLS_LIST", "REGISTER_PLUGIN_LIST", "TOOL_PLUGIN_IDS", "TOOLS_SKELETON",
    "get_local_tool_schemas_for_perm", "get_plugin_config_perm", "get_tool_handler",
    "load_external_tools", "register_bot_tool", "register_tool", "reset_all_tools",
    "seed_tools_folder",
    # the names that do (resolved on first use)
    "ChatParam", "NonHistoryChatParam", "describe_http_status", "register_no_history",
    "set_remote_tool_router", "setup_openai_logging", "stop_no_history", "unregister_no_history",
]


def __getattr__(name: str) -> Any:
    """Resolve one of the third-party names on first use; anything else is a real AttributeError."""
    if name in _LAZY_MODULES:
        return importlib.import_module("." + name, __name__)
    module_name = _LAZY_NAMES.get(name)
    if module_name is None:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    return getattr(importlib.import_module("." + module_name, __name__), name)


def __dir__() -> list:
    return sorted(set(globals()) | set(_LAZY_NAMES) | _LAZY_MODULES)
