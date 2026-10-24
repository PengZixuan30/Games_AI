"""The tool registry under its pre-0.8.0 import path.

The registry moved to :mod:`games_ai.ai.games_ai_tool` when the package grew its subpackages, but
``games_ai.games_ai_tool`` was the documented path for years: an existing
``config/games_ai/tools/tools.py`` and other plugins that register a tool import it. This module
keeps that path working by re-exporting the registry's public names -- the very same objects, so a
tool registered through either path lands in the one registry the plugin reads -- and nothing
else: no module of the plugin imports it (it exists for code outside), and new code belongs on the
real path (see ``docs/*/tools.md``).

``tests/test_tool_compat.py`` pins the contract: this module exposes exactly the public surface of
:mod:`games_ai.ai.games_ai_tool`, so a name added there cannot silently stay missing here. Private
names are deliberately not re-exported; ``get_tool_handler`` is the public way to reach a handler.
"""

from .ai.games_ai_tool import (TOOL_PLUGIN_IDS, TOOL_SCHEMAS, ToolHandler, append_custom_tools,
                               calculator, delete_skills, get_bot_tool_schemas,
                               get_hub_tool_schemas_for_perm, get_local_tool_schemas_for_perm,
                               get_online_players, get_plugin_config_perm, get_player_position,
                               get_request_tool_schemas, get_tool_handler,
                               get_tool_schemas_for_perm, item_caculator, modify_custom_tools,
                               modify_skills, packed_plugin_file, read_custom_tools, read_skills,
                               register_bot_tool, register_tool, reload_plugin, reset_all_tools,
                               setting_timer, write_skills)
