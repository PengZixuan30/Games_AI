<div align="center">

# 使用 Mineflayer Bot

[English](../en_us/mineflayer-bot.md)  |  简体中文  |  [繁體中文](../zh_tw/mineflayer-bot.md)

[返回 README](../../README.zh-CN.md)

</div>

GamesAI 内置基于 [Mineflayer](https://github.com/PrismarineJS/mineflayer) 的全自主 Minecraft 机器人。AI 可以直接控制机器人在游戏世界中寻路、挖掘、建造、合成、战斗和交互。

## 环境要求

- 服务器需安装 **Node.js >= 18** 和 **npm**
- 插件首次启动时自动安装 npm 依赖（`mineflayer`、`ws`、`vec3`、`mineflayer-pathfinder`、`mineflayer-mcefly`），并在已安装的 mineflayer 不支持当前服务器版本时（例如服务器升级后）自动刷新依赖
- 一个用于 Bot 的 Minecraft 账号（Microsoft/Mojang/离线）

## 指令

|指令|用途|
|---|---|
|`!!aibot join`|启用 Bot 并让其加入服务器。|
|`!!aibot leave`|让 Bot 离开服务器并禁用。|
|`!!aibot set <key> <value>`|配置 Bot 身份（`username`/`password`/`auth`）。|

## 工作原理

```mermaid
flowchart LR
    A["玩家"] -->|"!!ask"| B["GamesAI 插件 (Python)"]
    B -->|"bot_action"| D["跨服 hub"]
    H["JS Bot 进程 (Node.js)"] -->|"以 mineflayer_bot 注册"| D
    H --> E["Mineflayer Bot"]
    E --> F["Minecraft 服务器"]
    B --> G["自主控制器 (AI)"]
    G -->|"get_state → 分析状态 →<br/>bot_call_action(goto / dig / attack / …)"| D
```

插件把 JS Bot 进程当作集群里的一个 peer：它接入 hub 并以 `mineflayer_bot` 身份注册，插件通过 hub 向它发送 `bot_action` 请求。Bot 启动后，**自主 AI 控制器**会定时读取机器人状态、检查聊天消息，并自主决定执行什么操作。

## 支持的操作

Bot 支持 20+ 种操作，通过 `bot_call_action` AI 工具调用：

|操作|描述|
|---|---|
|`goto`|A* 寻路到坐标 `{x, y, z, range?}`|
|`dig`|挖掘指定坐标的方块|
|`place`|在指定坐标放置方块|
|`attack`|按名称攻击附近实体，或攻击最近敌对生物|
|`useOn`|右键实体（如村民交易）|
|`equip` / `unequip`|装备/卸下盔甲或手持物品|
|`mount` / `dismount`|骑乘或离开载具和动物|
|`craft`|合成物品（背包或工作台）|
|`lookAt`|看向坐标或直接设置 yaw/pitch|
|`sleep` / `wake`|在床上睡觉或起床|
|`activateBlock`|右键方块（打开箱子、按下按钮）|
|`setControlState`|控制载具移动（前进/后退/跳跃）|
|`viewContainer` / `takeFromContainer` / `putToContainer`|容器管理|
|`openFurnace` / `furnacePutInput` / `furnacePutFuel` / `furnaceTakeOutput`|熔炉操作|
|`nearbyEntities` / `findBlocks` / `getBlock`|世界查询|
|`stop` / `stopEfly`|停止所有移动或鞘翅飞行|

## Bot 控制 AI 工具

除 `bot_call_action` 外，还有以下专用 AI 工具：

|工具|描述|
|---|---|
|`bot_chat`|让 Bot 在公共聊天中发送消息。|
|`bot_whisper`|让 Bot 向某个玩家发送私聊消息。|
|`bot_get_state`|获取 Bot 完整状态（30+ 字段）。|
|`run_mineflayer_bot` / `stop_mineflayer_bot`|启动或停止 Bot。需要达到配置的 `permission` 权限等级。|
|`delegate_to_bot`|将复杂的 Minecraft 任务委派给自主控制器。|

## 配置

完整配置参考见 [5.mineflayer_bot](configuration.md#5mineflayer_bot)。关键要点：

- 将 `mineflayer_bot.enabled` 设为 `true`（或使用 `!!aibot join`）以启动 Bot
- `mineflayer_bot.bot.username` / `password` / `auth` — Bot 的 Minecraft 登录凭据。**用户名必须匹配 `[a-zA-Z0-9_]+`**（仅限英文字母、数字和下划线）；`!!aibot set` 对 `password` 施加同样的限制，因此含有其他字符的密码只能手工写入 `config.json`。
- `mineflayer_bot.cycle_interval` — 自主 AI 决策间隔（秒）
- `websocket.uri` / `websocket.force_server`（顶层）— 集群地址与角色；Bot 作为客户端接入该地址。详见[跨服连接](cross-server.md)

> [!NOTE]
> 修改 Bot 配置后，执行 `!!gamesai reload`（或使用 `!!aibot set`）即可生效。`cycle_interval` 与 AI 相关设置会立即作用于运行中的 Bot；`username`、`password` 和 `auth` 只在 Node 进程（重新）启动时读取，因此修改后需要先停止再启动 Bot（`!!aibot leave`，然后 `!!aibot join`）。`!!gamesai config set` 会拒绝 `mineflayer_bot`（以及 `all_ai`），无法设置这些键。
