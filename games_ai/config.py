class SyncPluginConfig:
    prefix: str = "[GamesAI]"
    allow_permission: int = 3
    max_history: int = 10

    data_path: str = "config/games_ai/database/public_database.db"
    tools_path: str = "config/games_ai/tools/tools.py"
    skills_path: str = "config/games_ai/skills/skills.json"
    builtin_skills_dir: str = ""
    skills_description: dict[str, str] = {}

    mineflayer_init_js_path: str = "config/games_ai/mineflayer/init.js"
    bot_username: str = "Bot"

    all_ai: dict = {}
    default_ai: str = ""

    debug_mode: bool = False
    
plugin_config = SyncPluginConfig()