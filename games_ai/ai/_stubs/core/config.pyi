# Generated from games_ai/core/config.py by tools/build_tool_stubs.py -- do not edit.
from _typeshed import Incomplete

class SyncPluginConfig:
    prefix: str
    allow_permission: int
    data_path: str
    tools_path: str
    skills_path: str
    builtin_skills_dir: str
    skills_description: dict[str, str]
    mineflayer_init_js_path: str
    bot_username: str
    all_ai: dict
    default_ai: str
    websocket_uri: str
    websocket_force_server: bool
    websocket_name: str
    websocket_allow_app_id: list[str]
    websocket_token_ttl_hours: int
    websocket_auto_enroll: bool
    websocket_identity_file: str
    cross_server_mode: str
    cross_server_name: str
    debug_mode: bool

plugin_config: Incomplete
