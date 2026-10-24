<div align="center">

# 架构

[English](../en_us/architecture.md)  |  简体中文  |  [繁體中文](../zh_tw/architecture.md)

[返回 README](../../README.zh-CN.md)

</div>

插件是一个 Python 包 `games_ai/`，包内模块按职责分组。本页是它的地图：哪个包负责什么、各部分之间允许怎样依赖、新模块该放在哪里。

## 包的结构

```text
games_ai/
  __init__.py     入口：元数据、MCDR 生命周期、装配、!!ask 链路
  requirements.txt
  core/           设置、日志、依赖门、权限、存储
  commands/       !!data、!!gamesai config、!!aibot、!!gamesai clear、!!gamesai node 背后的处理函数
  cluster/        跨服链路：角色决定、hub、节点客户端、远程命令源
  ai/             请求链路：会话、服务商客户端、上下文窗口表、工具、技能
  bot/            Mineflayer 假人：进程、控制器、内嵌 init.js
  update/         自更新与驱动它的 24 小时轮次
  ui/             游戏内帮助文本
```

这些目录里各有一个 `__init__.py`，也就是该包的门面：它转出插件其它部分从该包引用的模块与名字，入口模块因此不必知道某个名字住在哪个文件里。需要第三方包的模块里的名字用 `__getattr__` 首次访问时才导入（这样早早 import 一个包仍然不碰第三方），同时在 `if TYPE_CHECKING:` 块里再声明一次 —— 那个块永不执行，但编辑器与类型检查器读的就是它，因此 `from .ai import ChatParam` 拿到的是真实签名而不是 `Any`。

包根目录在入口模块旁边保留了一个兼容模块：`games_ai_tool.py` 以子包出现之前的旧路径再导出工具注册表，因为既有的 `config/games_ai/tools/tools.py` 与其他插件导入的就是它。它只为插件之外的代码存在 —— 本包内没有任何模块 import 它 —— 新代码请用 `ai/games_ai_tool.py`（见[工具](tools.md)，契约由 `tests/test_tool_compat.py` 锁定）。

## 各包的职责

|路径|职责|
|---|---|
|`core/`|`clock.py`（AI 被告知的那个时钟：时区判定、时间戳与时长）、`config.py`（`plugin_config` 单例）、`logger.py`（日志桥）、`deps.py`（依赖门与 pip 修复）、`permission.py`（唯一的权限规则）与 `database.py`（公开数据库与历史存储）。|
|`commands/`|每个命令组一个模块：`data.py`、`settings.py`、`aibot.py`、`clear.py` 与 `node.py`。它们只负责回复调用者；需要的入口状态由一次 `attach()` 调用注入。|
|`cluster/`|`cross_server.py`（角色决定与管理器）、`websockets_server.py`（hub）、`websockets_client.py`（节点客户端与握手探测）与 `ws_command.py`（远程命令源与会话注册表）。|
|`ai/`|`chat_param.py`（会话与请求链路）、`openai_api.py`（服务商客户端）、`context_table.py` 及其生成的 `context_table_data.py`、`games_ai_tool.py`（工具注册表）、`tools_interpreter.py`、`external_skills_loader.py` 与 `register_extra_plugin.py`；`tools_stub_files.py` 负责在用户的工具目录里播种（`tools.py` 骨架，以及复制到它旁边的生成式 `_stubs/` 存根树，见[工具](tools.md)）。|
|`bot/`|`mineflayer.py`（Node 进程）、`mineflayer_ai.py`（自主控制器）与 `mineflayer_service_files.py`（内嵌的 `init.js`、`package.json` 及其写入函数）。|
|`update/`|`updater.py`（下载、校验并替换插件自身文件）与 `update_round.py`（24 小时检查与集群协同轮次）。|
|`ui/`|`help.py`：游戏内帮助文本与它的 `send_help` 构造器。|

## 各部分如何依赖

- 入口模块可以 import 任何包；**任何包都不得 import 入口模块** —— 违反时 `tests/test_layout.py` 会失败。
- `core/` 是地基：其它包都可以 import 它，而它只 import 标准库与 MCDR。
- 依赖门优先：在什么都没装的机器上 import `games_ai` 也必须成功。入口模块从各包的**门面**（`__init__.py`）取名：门面把不需要第三方的名字 eager 导入，其余首次访问时才导入（PEP 562），因此早早 import 一个包也不会把第三方包拖上门前的导入链。

## 新模块放在哪里

- 按"它回答什么问题"选包，而不是按"谁调用它"：集群传输放 `cluster/`，面向模型的代码放 `ai/`，假人代码放 `bot/`，玩家能输入的命令处理函数放 `commands/`，玩家读到的文本放 `ui/`，各处共用的东西放 `core/`。
- 需要第三方包的模块必须在依赖门之后导入，因此除了 `core/` 之外哪里都可以：`core/` 要保持"什么都没装的机器也能 import"。
- 把新文件加进 `tests/test_layout.py` 的 `KNOWN_MODULES`；若别处要用它的名字，就加进所属包的 `__init__.py` —— 该模块不需要第三方就 eager 导出，需要就写进 `_LAZY_NAMES`。该套件还会检查导入图保持无环、每个门面的 `__all__` 可解析、门面的 eager 导入门前安全、入口不越过门面直接引用模块，以及门前闭包不拉入任何第三方包。
- 新增、改名或删除模块都会让随包发布的编辑器存根过期：用 `python tools/build_tool_stubs.py` 重新生成（需要 `mypy` 的 `stubgen`；生成的树会提交进仓库，`--check` 只校验不写入）。在存根与源码重新一致之前，`tests/test_tool_stubs.py` 会失败。

## 入口模块保留什么

- MCDR 元数据与生命周期：`PLUGIN_METADATA`、`on_load`、`on_unload`、`on_server_startup` 与 `_deps_*` 修复路径。
- 装配：把配置写进 `plugin_config`、命令树、跨服链路的启动与停止、身份文件、假人栈，以及把入口的实时状态交给需要它的模块的那些 `attach()` 调用。
- `!!ask` 链路本身（`ask_ai` 与它的分发器）——唯一仍留在入口模块里的命令组。
