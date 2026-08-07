REGISTER_PLUGIN_LIST: list[str] = []

def register_self(plugin_id: str):
    if plugin_id:
        if plugin_id not in REGISTER_PLUGIN_LIST:
            REGISTER_PLUGIN_LIST.append(plugin_id)
