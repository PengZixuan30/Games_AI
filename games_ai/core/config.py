class SyncPluginConfig:
    prefix: str = "[GamesAI]"
    allow_permission: int = 3

    data_path: str = "config/games_ai/database/public_database.db"
    tools_path: str = "config/games_ai/tools/tools.py"
    skills_path: str = "config/games_ai/skills/skills.json"
    builtin_skills_dir: str = ""
    skills_description: dict[str, str] = {}

    mineflayer_init_js_path: str = "config/games_ai/mineflayer/init.js"
    bot_username: str = "Bot"

    all_ai: dict = {}
    default_ai: str = ""

    # Cross-server link, owned by cross_server.py. ``cross_server_mode`` is written by the
    # background decision on load: "server" (this instance listens), "client" (this instance
    # dials another one) or "local" (no cross-server, everything runs here).
    websocket_uri: str = "ws://127.0.0.1:8080"
    websocket_force_server: bool = False
    # Peer name override; empty means "derive it from the instance directory" (see
    # ``_default_instance_name``: directory name + a short hash of its path).
    websocket_name: str = ""
    # Extra handshake ids admitted by this hub on top of ``games_ai_mcdr`` / ``mineflayer_bot``.
    websocket_allow_app_id: list[str] = []
    # Hub side: how long a token the hub issues stays valid, in hours; -1 = unlimited. The
    # value is copied into the node entry when the token is issued, so changing it affects the
    # next issuance only.
    websocket_token_ttl_hours: int = -1
    # Node side: ask the hub to record an enrolment request when this instance has no identity.
    websocket_auto_enroll: bool = True
    # Node side: override for the identity file path; empty means
    # "<plugin data folder>/cross_server/identity.json".
    websocket_identity_file: str = ""
    cross_server_mode: str = "local"
    # This instance's name on the link; set by _apply_config from ``websocket_name`` or derived.
    cross_server_name: str = ""

    debug_mode: bool = False

plugin_config = SyncPluginConfig()
