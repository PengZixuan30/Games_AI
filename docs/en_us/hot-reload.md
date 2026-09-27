<div align="center">

# Hot Reload

English  |  [简体中文](../zh_cn/hot-reload.md)  |  [繁體中文](../zh_tw/hot-reload.md)

[Back to README](../../README.md)

</div>

GamesAI provides a comprehensive hot-reload mechanism that lets you apply configuration, tool, and skill changes without restarting the server.

## Triggering a Hot Reload

Hot reload can be triggered in the following ways:

|Method|Description|
|---|---|
|`!!gamesai reload`|Run by an admin to reload all configuration, tools, and skills.|
|`!!gamesai config set <key> <value>`|Automatically triggers a reload after modifying a config value.|
|AI tool `reload_plugin`|Called by the AI after modifying tool code or skill files to ensure changes take effect immediately.|
|`!!aibot set <key> <value>`|Automatically triggers a reload after modifying Bot configuration.|

## What Happens During a Hot Reload

When a hot reload is performed, the plugin executes the following steps in order:

1. **Re-read the configuration file** (`config/games_ai/config.json`) — Applies all changes to `prefix`, `permission`, `all_ai`, `default_ai`, etc. (including per-model `context_window`).
2. **Re-register all tools (0.6.4+)** — Completely clears the tool registry and rebuilds it from every source: built-in tools are replayed from recorded registrations, custom `tools.py` tools are re-imported, and plugins that registered tools are reloaded so their registration code runs again (see steps 4 and 6).
3. **Reload Skills** (`config/games_ai/skills/skills.json`) — Refreshes the skill index; the available skills list in the AI's system prompt is updated synchronously.
4. **Reload Custom Tools** (`config/games_ai/tools/tools.py`) — Hot-loads custom tool code without restarting MCDR.
5. **Restart the Mineflayer Bot** (if enabled) — Stops the existing Bot process and WebSocket connection, then restarts with the new configuration.
6. **Reload Plugins that Registered Tools & Registered Extension Plugins** — Reloads every third-party plugin that registered tools via `@register_tool` (tracked automatically since 0.6.4) plus every plugin in `REGISTER_PLUGIN_LIST` ([see below](#making-your-mcdr-plugin-follow-gamesai-hot-reload)). Failed or missing plugins are removed from the reload list.
7. **Dispatch the `games_ai.reload` Event** — Notifies all other MCDR plugins that are listening for this event ([see below](#approach-2-responding-to-hot-reload-via-event-listening)).

> [!NOTE]
> Hot reload **does not** clear players' chat history.

## Making Your MCDR Plugin Follow GamesAI Hot Reload

If you are developing an MCDR plugin that depends on GamesAI (e.g., registering custom tools or skills), you may want your plugin to refresh alongside GamesAI during a hot reload. GamesAI offers two approaches:

### Approach 1: Auto-Reload with `register_self()` (Recommended)

This is the simplest approach. Call `register_self()` in your plugin's `on_load` to add your plugin to GamesAI's reload list:

> [!NOTE]
> Since 0.6.4, plugins that register tools via `@register_tool` are reloaded automatically during hot reload (they are tracked by the tool registry), so `register_self()` is only needed for plugins that don't register tools (e.g. skills-only plugins) or need custom reload logic.

```python
from games_ai.register_extra_plugin import register_self

def on_load(server, old):
    register_self(server.get_self_metadata().id)
```

Each time `!!gamesai reload` is executed, your plugin will be automatically reloaded by MCDR (via `server.reload_plugin()`). If the reload fails, the plugin is unloaded and removed from the reload list.

If your plugin needs **custom reload logic** (beyond the default `reload_plugin`), you can pass a custom reloader function as the second argument. Besides regular functions, you can also pass a method (`self.xxx`) or a lambda expression:

```python
from mcdreforged.command.command_source import CommandSource
from games_ai.register_extra_plugin import register_self

def my_reloader(source: CommandSource):
    # Custom reload logic
    server = source.get_server()
    server.logger.info("Executing my custom reload logic...")
    # e.g., re-read your own config, rebuild database connections, etc.

def on_load(server, old):
    register_self(server.get_self_metadata().id, my_reloader)
```

> [!IMPORTANT]
> The custom reloader function's **first parameter must be `CommandSource`** (as shown by `source` in the example above). GamesAI passes the command source that triggered the hot reload to your function.

When the custom reloader raises an exception, the plugin is automatically unloaded and removed from the reload list, with the failure reason recorded in the log.

### Approach 2: Responding to Hot Reload via Event Listening

If you don't want your plugin to be unloaded/reloaded, but only want to be notified when GamesAI finishes a hot reload and perform some logic, you can listen for the `games_ai.reload` event:

```python
from mcdreforged.api.all import *

def on_load(server: PluginServerInterface, old):
    server.register_event_listener("games_ai.reload", on_gamesai_reload)

def on_gamesai_reload(server: PluginServerInterface):
    server.logger.info("GamesAI hot reload completed, syncing my state...")
    # e.g., re-read GamesAI's latest configuration
    # e.g., refresh my cached tool list
```

> [!NOTE]
> The first argument to the event callback is always `PluginServerInterface`, automatically prepended by MCDR.

> [!TIP]
> The `games_ai.reload` event is dispatched **after** the reload is complete, so listeners always see the latest reloaded state.

## Comparison of the Two Approaches

`register_self()` behaves differently depending on whether a second argument (custom reloader) is passed:

|Feature|`register_self()` without reloader|`register_self()` with custom reloader|Listening to `games_ai.reload` Event|
|---|---|---|---|
|When it fires|During reload (Step 6)|During reload (Step 6)|After reload completes (Step 7)|
|Plugin behavior|MCDR unloads then reloads (`on_load` re-runs)|Plugin stays loaded; only custom function runs|Plugin unaffected|
|Failure handling|Plugin unloaded, removed from reload list|Plugin unloaded, removed from reload list|Exception does not unload plugin|
|Tools/Skills|Auto re-registered by `on_load`|No re-registration needed (plugin not unloaded, registrations persist)|Not needed|
|Best for|Plugins that need a full code refresh|Lightweight operations like re-reading config or refreshing caches|Plugins that only need a notification or state sync|

> [!NOTE]
> Tools (`@register_tool`) and Skills (`register_skills()`) registered with GamesAI are tied to the lifecycle of the plugin that registered them. As long as the plugin is not unloaded by MCDR, the registered tools and skills remain valid. Therefore, **no re-registration is needed** when using a custom reloader.
