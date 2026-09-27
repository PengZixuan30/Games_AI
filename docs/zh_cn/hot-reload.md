<div align="center">

# 热重载

[English](../en_us/hot-reload.md)  |  简体中文  |  [繁體中文](../zh_tw/hot-reload.md)

[返回 README](../../README.zh-CN.md)

</div>

GamesAI 提供了完善的热重载机制，让你在不重启服务器的情况下应用配置、工具和技能的变更。

## 触发热重载

热重载可通过以下方式触发：

|方式|说明|
|---|---|
|`!!gamesai reload`|管理员手动执行，重新加载全部配置、工具与技能。|
|`!!gamesai config set <key> <value>`|修改配置项后自动触发重载。|
|AI 工具 `reload_plugin`|AI 在修改工具代码或技能文件后调用，确保变更立即生效。|
|`!!aibot set <key> <value>`|修改 Bot 配置后自动触发重载。|

## 重载期间发生了什么

执行热重载时，插件会依次执行以下操作：

1. **重新读取配置文件** (`config/games_ai/config.json`) — 应用 `prefix`、`permission`、`all_ai`、`default_ai` 等全部配置变更(含单模型 `context_window`)。
2. **全量重建工具注册（0.6.4+）** — 彻底清空工具注册表，然后从所有来源重建：内置工具通过注册重放恢复、自定义 `tools.py` 重新导入、注册过工具的插件被重载以重新执行注册代码（见第 4、6 步）。
3. **重新加载 Skills** (`config/games_ai/skills/skills.json`) — 刷新技能索引，AI 系统提示中的可用技能列表同步更新。
4. **重新加载自定义工具** (`config/games_ai/tools/tools.py`) — 热加载自定义工具代码，无需重启 MCDR。
5. **重启 Mineflayer Bot**（如已启用）— 停止现有 Bot 进程和 WebSocket 连接，应用新配置后重新启动。
6. **重载注册过工具的插件与已注册的扩展插件** — 重载所有通过 `@register_tool` 注册过工具的第三方插件（0.6.4 起自动追踪）以及 `REGISTER_PLUGIN_LIST` 中的插件（[见下方](#让自己的-mcdr-插件跟随-gamesai-热重载)）。重载失败或找不到的插件会从重载列表中移除。
7. **派发 `games_ai.reload` 事件** — 通知所有监听了此事件的其他 MCDR 插件（[见下方](#方式二通过监听事件响应热重载)）。

> [!NOTE]
> 热重载**不会丢失**玩家的聊天历史记录。

## 让自己的 MCDR 插件跟随 GamesAI 热重载

如果你开发了依赖 GamesAI 的 MCDR 插件（例如注册了自定义工具或技能），你可能希望插件在 GamesAI 热重载时同步刷新。GamesAI 提供了两种方式：

### 方式一：使用 `register_self()` 自动重载（推荐）

这是最简单的方式。在你的插件 `on_load` 中调用 `register_self()`，将插件加入 GamesAI 的重载列表：

> [!NOTE]
> 自 0.6.4 起，通过 `@register_tool` 注册过工具的插件在热重载时会自动重载（由工具注册表自动追踪），因此 `register_self()` 仅适用于未注册工具的插件（如只注册技能的插件）或需要自定义重载逻辑的插件。

```python
from games_ai.register_extra_plugin import register_self

def on_load(server, old):
    register_self(server.get_self_metadata().id)
```

每次执行 `!!gamesai reload` 时，你的插件会被 MCDR 自动重载（调用 `server.reload_plugin()`）。如果重载失败，插件会被卸载并从重载列表中移除。

如果你的插件需要**自定义重载逻辑**（不仅仅调用默认的 `reload_plugin`），可以传入自定义 reloader 函数作为第二个参数。除了普通函数外，也可以传入方法（`self.xxx`）或 lambda 表达式：

```python
from mcdreforged.command.command_source import CommandSource
from games_ai.register_extra_plugin import register_self

def my_reloader(source: CommandSource):
    # 自定义重载逻辑
    server = source.get_server()
    server.logger.info("执行我的自定义重载逻辑...")
    # 例如：重新读取自己的配置文件、重建数据库连接等

def on_load(server, old):
    register_self(server.get_self_metadata().id, my_reloader)
```

> [!IMPORTANT]
> 自定义 reloader 函数的**第一个参数必须为 `CommandSource`**（如上例中的 `source`），GamesAI 会将触发热重载的命令源传入该参数。

当自定义 reloader 抛出异常时，插件会被自动卸载并从重载列表中移除，同时在日志中记录失败原因。

### 方式二：通过监听事件响应热重载

如果你的插件不想被卸载/重载，只想在 GamesAI 热重载完成时收到通知并执行一些逻辑，可以监听 `games_ai.reload` 事件：

```python
from mcdreforged.api.all import *

def on_load(server: PluginServerInterface, old):
    server.register_event_listener("games_ai.reload", on_gamesai_reload)

def on_gamesai_reload(server: PluginServerInterface):
    server.logger.info("GamesAI 已完成热重载，我正在同步处理...")
    # 例如：重新读取 GamesAI 的最新配置
    # 例如：刷新自己缓存的工具列表
```

> [!NOTE]
> 事件回调的第一个参数始终是 `PluginServerInterface`，由 MCDR 自动补齐。

> [!TIP]
> `games_ai.reload` 事件在**重载完成后**派发，所以监听器拿到的已经是重载后的最新状态。

## 两种方式对比

`register_self()` 根据是否传入第二个参数（自定义 reloader）有不同的行为：

|特性|`register_self()` 不传 reloader|`register_self()` 传入自定义 reloader|监听 `games_ai.reload` 事件|
|---|---|---|---|
|触发时机|重载过程中（第 6 步）|重载过程中（第 6 步）|重载完成后（第 7 步）|
|插件行为|MCDR 卸载后重载（`on_load` 重新执行）|插件保持加载，仅调用自定义函数|插件不受影响|
|失败处理|插件被卸载，从重载列表移除|插件被卸载，从重载列表移除|异常不会卸载插件|
|工具/Skills|`on_load` 自动重新注册|无需重新注册（插件未卸载，注册保持有效）|无需处理|
|适用场景|插件需要完整刷新代码|插件只需重读配置、刷新缓存等轻量操作|插件只需收到通知或同步状态|

> [!NOTE]
> 注册在 GamesAI 中的工具（`@register_tool`）和 Skills（`register_skills()`）的生命周期与注册它们的插件绑定。只要插件未被 MCDR 卸载，已注册的工具和 Skills 就会一直有效。因此使用自定义 reloader 时**无需**重新注册。
