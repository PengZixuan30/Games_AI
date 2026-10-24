"""The pre-0.8.0 import path of the tool registry, end to end.

The registry moved into the ``ai`` subpackage, but ``games_ai.games_ai_tool`` was the documented
import for custom tools and for plugins that register one, so ``games_ai/games_ai_tool.py`` keeps
that path working by re-exporting the registry's public names -- the same objects, which is what
makes a tool registered through either path land in the one registry the plugin reads.

The shared contract of every legacy path (exact public surface, same objects, nothing in the
package importing it) is pinned in ``tests/test_compat_modules.py``. This suite adds the
registry-specific half: a real legacy ``tools.py`` is loaded by the plugin and its tool really
lands in the one registry.
"""
import sys

import games_ai
from games_ai.ai import games_ai_tool as registry
from games_ai.ai import tools_interpreter
from games_ai.core.config import plugin_config


def test_a_legacy_tools_file_registers_into_the_same_registry(tmp_path, monkeypatch):
    """The point of the module: a ``tools.py`` written before 0.8.0 keeps working unchanged."""
    path = tmp_path / "tools.py"
    path.write_text(
        "from mcdreforged.command.command_source import CommandSource\n"
        "from games_ai.games_ai_tool import register_tool, get_plugin_config_perm\n"
        "\n"
        "@register_tool(description=\"Written against the old path\", perm=get_plugin_config_perm)\n"
        "def legacy_tool(source: CommandSource, ai_prefix: str):\n"
        "    return \"done\"\n",
        encoding="utf-8", newline="\n")
    monkeypatch.setattr(plugin_config, "tools_path", str(path))
    lines: list = []
    try:
        loaded, _ = tools_interpreter.load_external_tools(log=lines.append)
        handler = games_ai.get_tool_handler("legacy_tool")

        assert "legacy_tool" in loaded, f"the legacy file loads: {lines}"
        assert handler is not None and handler is registry._TOOL_REGISTRY.get("legacy_tool"), \
            "its tool is in the one registry the plugin reads"
        assert registry._TOOL_REGISTRY["legacy_tool"].resolve_perm() == plugin_config.allow_permission, \
            "get_plugin_config_perm came from the same module as well"
    finally:
        tools_interpreter._clear_external_tools()
        sys.modules.pop("external_tools", None)
