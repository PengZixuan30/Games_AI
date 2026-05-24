class SyncPluginConfig:
    prefix: str = "[GamesAI]"
    allow_permission: int = 3
    max_history: int = 10
    data_path: str = "config/games_ai/database/public_database.db"
    tools_path: str = "config/games_ai/tools/tools.py"
    skills_path: str = "config/games_ai/skills/skills.json"
    
plugin_config = SyncPluginConfig()