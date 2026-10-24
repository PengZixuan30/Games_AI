<div align="center">

# 工具

[English](../en_us/tools.md)  |  简体中文  |  [繁體中文](../zh_tw/tools.md)

[返回 README](../../README.zh-CN.md)

</div>

工具（tools）是提供给模型的**函数**：模型可以主动调用它们来做事——查数据、读文件、执行指令、操控假人。这一页讲清三件事：插件自带哪些工具、怎么自己加工具、以及工具的权限与可见性是怎么决定的。

## 1. 内置工具

下表由插件的工具注册表导出，`权限` 列表示**向 AI 提供该工具**所需的最低 MCDR 权限等级，`Bot` 列表示该工具是否同时提供给自治 Bot 控制器（否则只有聊天 AI 能用）。

<details>
<summary>点击查看全部内置工具（27 个）</summary>

| 工具 | 参数 | 权限 | Bot | 说明 |
|---|---|:---:|:---:|---|
| `get_online_players` | 无 | 0 | ✅ | 获取在线玩家列表。依赖 `online_player_api` 插件，插件缺失时回退为 RCON `list` 查询 |
| `get_player_position` | `player` | 0 | ✅ | 查询指定玩家的坐标与维度。依赖 `minecraft_data_api` 插件，插件缺失时工具仍会注册，只是每次调用都会返回错误字符串 |
| `calculator` | `expression` | 0 | ✅ | 四则运算表达式计算器 |
| `item_caculator` | `expression`、`single_limit`（可选） | 0 | ✅ | 计算表达式并把结果换算成"盒 / 组 / 个"，`single_limit` 为单组堆叠数（默认 64） |
| `setting_timer` | `duration` | 0 | ✅ | 等待指定秒数后再继续 |
| `read_skills` | `skills` | 0 | — | 读取一个已注册的技能文件。**不提供**给 Bot |
| `reload_plugin` | 无 | 0 | — | 热重载插件，使配置、技能与自定义工具的改动生效 |
| `ai_read_data` | `key` | 0 | — | 读取公共数据库中的一个键 |
| `ai_read_all_keys` | 无 | 0 | — | 列出公共数据库的所有键 |
| `ai_read_all_data` | 无 | 0 | — | 一次性读取公共数据库的全部键值对 |
| `ai_write_data` | `key`、`value` | 配置权限 | — | 覆写写入一条公共数据 |
| `ai_add_data` | `key`、`value` | 配置权限 | — | 追加写入一条公共数据 |
| `ai_del_data` | `key` | 配置权限 | — | 删除一条公共数据 |
| `write_skills` | `skills`、`summary`、`content` | 配置权限 | — | 创建或覆写技能文件，并登记到技能索引 |
| `modify_skills` | `skills`、`old_string`、`new_string`、`summary`（可选） | 配置权限 | — | 以正则替换修改技能文件；`summary` 非空时同步更新索引 |
| `delete_skills` | `skills` | 配置权限 | — | 删除技能文件并移除索引条目 |
| `read_custom_tools` | 无 | 配置权限 | — | 读取自定义 `tools.py` 的内容 |
| `modify_custom_tools` | `old_string`、`new_string` | 配置权限 | — | 以正则替换修改自定义 `tools.py` |
| `append_custom_tools` | `tools` | 配置权限 | — | 向自定义 `tools.py` 末尾追加工具代码 |
| `run_mineflayer_bot` | 无 | 配置权限 | — | 启动 Mineflayer 假人 |
| `stop_mineflayer_bot` | 无 | 配置权限 | ✅ | 停止 Mineflayer 假人 |
| `bot_chat` | `message` | 0 | ✅ | 让假人在公屏发言 |
| `bot_whisper` | `username`、`message` | 0 | ✅ | 让假人私聊某玩家 |
| `bot_get_state` | 无 | 0 | ✅ | 获取假人的完整状态（30 余个字段） |
| `bot_call_action` | `action`、`params`（可选） | 0 | ✅ | 向假人下发任意动作（`goto`、`dig`、`place`、`attack` 等） |
| `delegate_to_bot` | `task`、`username`（可选） | 0 | ✅ | 把复杂任务交给自治 Bot 控制器，由它自行拆解执行 |
| `send_message_to_player_ai` | `target`、`message` | 0 | — | 把当前用户的一条消息转交给**任何人**的对话,对方的助手会在下次提问时读到(单向)。只要目标已经拥有对话就能发,不比较任何权限等级 |

</details>

关于这张表的四点说明：

- **`配置权限`** 指的是 `config.json` 里的 `permission` 值。该值决定了这些工具对**哪个等级**的玩家开放；等级不足的玩家，其 AI 请求里根本不会出现这些工具，模型也就无法调用。
- **`Bot` 列的差异是有意为之**：发给 Bot 控制器的工具集被刻意收窄（例如 `read_skills`、数据库读写、技能与工具管理都不给它），以免自治循环在无人监督时改动技能或数据。
- **`perm` 只是第一道门**。内置工具与自定义工具里的敏感操作，通常还会在函数内部再次检查调用者的实际权限等级（`source.get_permission_level()`）。两道门都过不了，指令就不会执行。
- **`send_message_to_player_ai` 是唯一的跨用户写入。**它对所有用户开放,而且**任何人都可以写给任何人**:转达那一刻唯一的检查是"目标已经拥有对话"(转达永远不会创建对话),**不比较也不查询任何权限等级** —— 两边的等级都不查,所以一次转达不可能往 `permission.yml` 里写入名字。消息会以 `user` 角色存进对方的对话,并在正文里标明发送者,由对方的助手在下次提问时读到。控制台自己的对话也是合法目标,用它的键名 `Server Control Panel` 指定。

> [!TIP]
> 需要更多工具时，有三条路：装 [GamesAI-Extra](https://github.com/PengZixuan30/Games_AI-Extra)（坐标点管理、白名单管理、Minecraft Wiki 搜索等）、在 `tools.py` 里自己写、或在自己的 MCDR 插件里注册。

## 2. 在 `tools.py` 中自定义工具

自定义工具写在这个文件里：

```
config/games_ai/tools/tools.py
```

插件首次启动时会生成一份带示例工具的骨架文件。它的最小形态是这样：

```python
from mcdreforged.command.command_source import CommandSource
from games_ai.ai.games_ai_tool import register_tool

@register_tool(description="我的自定义工具")
def my_custom_tool(source: CommandSource, ai_prefix: str):
    return "工具执行完成"
```

三条硬性要求：

1. `from games_ai.ai.games_ai_tool import register_tool` 必须存在；
2. 函数必须带 `@register_tool(...)` 装饰器。**没有装饰器的公开函数不会注册**——插件加载时会扫描文件并把它们列进日志，提示 `Functions in external tools.py WITHOUT @register_tool() decorator (REJECTED)`。私有辅助函数请以 `_` 开头，它们会被跳过而不是被判为错误。该扫描会列出所有不是已注册工具的公开可调用对象，因此文件顶部导入的名字（骨架文件导入的 `register_tool` 与 `CommandSource`）同样会出现在 `REJECTED` 之后；
3. 函数签名前两个参数必须是 `source: CommandSource` 与 `ai_prefix: str`，其余参数与 `parameters` 中声明的顺序一致。

已存在的文件也可能导入旧的扁平路径 `from games_ai.games_ai_tool import ...`：该模块作为注册表的兼容再导出被保留（同一批对象，工具落在同一个注册表里），旧文件无需改动即可继续工作。新文件请使用上面的路径。

### 编辑器类型：生成的 `games_ai/` 文件夹

插件会在 `tools.py` 旁边维护一个生成出来的 `games_ai/` 存根包（`.pyi`）。它让编辑器（装了 Pylance 的 VS Code）在你编辑该文件时能解析 `from games_ai.ai.games_ai_tool import register_tool`：没有它，这个导入会被报为无法解析，插件里的每个名字都退化成 `Any`。存根同时带着插件的签名与文档字符串，因此把鼠标停在某个名字或被装饰的工具上时，能看到它做什么、需要什么参数，而不只是"它存在"。不需要任何配置 —— 与被编辑文件同目录的存根包会被自动找到；对于以 `.mcdr` 打包安装的情况，这也是唯一能拿到类型的途径，因为此时插件源码在归档里、语言服务器读不到（目录安装可以改用 `python.analysis.extraPaths` 指向插件目录、直接解析真实源码；打包安装没有可指的目标）。

该文件夹由插件自身源码生成（仓库里的 `tools/build_tool_stubs.py`），每次加载时只要文件缺失或内容不同就会刷新，因此插件升级会把新类型一起带来。不要手工编辑它（下次加载会覆盖），也不要 import 它：里面没有任何东西会运行。删掉它没有副作用，下次加载会重新写回。

### 参数定义

`description` 与 `parameters` 会**原样**成为模型的工具说明，所以它们是写给模型看的提示词，不是写给人的注释：

```python
@register_tool(
    description="读取一个已注册的技能文件。执行相关任务前应先读取它。",
    parameters={
        "type": "object",
        "properties": {
            "skills": {"type": "string", "description": "技能文件名，例如 skills_management.md"}
        },
        "required": ["skills"]
    }
)
def read_skills(source: CommandSource, ai_prefix: str, skills: str):
    ...
```

- 参数结构遵循 OpenAI function calling 的 JSON Schema；**不写 `parameters` 就是无参工具**；
- 带默认值的参数（如 `max_length: int = 3000`）不要放进 `required`，模型可以省略它们；
- `description` 里值得写清三件事：**什么时候用**、**需要什么前置条件**、**失败时会返回什么**。模型只会看到这段文字和你 `return` 的字符串。

### 返回值

`return` 的字符串就是模型看到的全部结果。因此：

- **只读工具**返回内容本身；
- **写操作**返回"做了什么"（例如 `已执行Minecraft命令：/say hello`），让模型能确认结果；
- **失败**返回可读原因（`权限不足：需要3级及以上权限`），而不是抛异常或返回 `None`。

给玩家的提示走 `source.reply(f"{ai_prefix}正在...")`，它只出现在聊天栏，模型看不到。两者要分开写。

### 权限

```python
from games_ai.ai.games_ai_tool import register_tool, get_plugin_config_perm

@register_tool(description="管理员专用工具", perm=get_plugin_config_perm)
def my_admin_tool(source: CommandSource, ai_prefix: str):
    if source.get_permission_level() < get_plugin_config_perm():
        return f"权限不足：需要{get_plugin_config_perm()}级及以上权限"
    ...
```

- `perm` 可以是固定整数，也可以是返回整数的零参函数；`get_plugin_config_perm` 会动态跟随 `config.json` 的 `permission` 变化，改配置后无需改代码；
- **`perm` 只控制"工具是否交给模型"**。一旦工具发出去了，真正执行时仍应像上面那样再查一次调用者等级——因为工具是**代表提问玩家**执行的，而模型可能被诱导去调用它。
- 若还需要按等级区分**同一工具的不同行为**，把等级判断写进函数体即可（例如一个工具在 4 级时不限指令，在 1/3 级时只允许白名单内的指令）。

### 集群作用域：`execute_in_hub`

多个 MCDR 实例共用一个 AI 时（见[跨服连接](cross-server.md)），每个工具只在**一台**机器上执行，由这个参数决定是哪台：

```python
@register_tool(description="在提问玩家所在的服务器上执行")                 # 默认：false
@register_tool(description="在跑 AI 的那台实例上执行", execute_in_hub=True)  # hub
```

- **`false`（默认）** —— 工具描述的是**提问玩家自己的服务器**。玩家所在实例随请求上传自己的工具列表，hub 提供它，调用被回传给那台实例执行 —— 用的是**那台机器**的 `source.get_server()`、它的插件、它的命令和它的权限表。
- **`true`** —— 工具属于**跑 AI 的那台实例**（hub）：它提示词背后的技能文件、公共数据库、假人、它自己的 `tools.py`。无论玩家在哪台实例，它都会出现在请求里，并且**始终在 hub 上执行**。

集群里要注意的三条：

- 来自其它实例的请求，hub 只会提供自己的 `true` 工具；所以**只装在 hub 上**的 `false` 工具，对 node 上的玩家永远不会出现 —— 要么把那台实例也装上同样的代码，要么把工具标成 `true`；
- 两边同名时只提供一份，且 **hub 的那份胜出**；
- **文件不会同步**：每台实例各有自己的 `config/games_ai/tools/tools.py`，AI 写的工具只会落进 hub 那一份。要让某台 node 也有，只能人工把那份文件复制过去，并在那台执行 `!!gamesai reload` —— 没有任何机制会替你写别的实例的文件。

### 给自治 Bot 使用

默认情况下自定义工具只给聊天 AI 用。要让 Bot 控制器也能调用，叠加第二个装饰器：

```python
from games_ai.ai.games_ai_tool import register_tool, register_bot_tool

@register_tool(description="让假人把物品丢给玩家")
@register_bot_tool()
def give_item(source: CommandSource, ai_prefix: str, player: str):
    ...
```

Bot 控制器在无人监督的循环里调用这些工具，因此**只给那些幂等或可安全重试的工具加这个装饰器**。

### 让 AI 自己写

`read_custom_tools`、`modify_custom_tools`、`append_custom_tools` 三个工具的组合，让 AI 能读取、精确编辑、追加这个文件；改完后它应当调用 `reload_plugin` 让改动生效。内置技能 `custom_tools_management.md` 会强制它先向你确认需求、参数、权限等级与期望返回值，再动手写代码。

编辑采用**正则替换**语义：`old_string` 是 Python 正则（对整份文件匹配），`new_string` 支持 `\1`、`\g<name>` 反向引用，**所有匹配都会被替换**；正则不合法或匹配不到时退回按字面文本替换，仍匹配不到则不写入任何内容并明确告知模型。

### 依赖与加载行为

`tools.py` 是**普通 Python 模块**，插件在每次加载与热重载时执行它：

- 顶部 `import` 的第三方库必须真实存在。`import requests` 之类的语句一旦失败，整个文件加载失败、**所有**自定义工具都不会注册（日志会给出原因）；
- 因此需要外部依赖时，要么先用 pip 装好，要么把 `import` 放进函数内部并在失败时返回可读错误；
- 每次 `!!gamesai reload` 都会重新执行该文件，所以改动工具代码不需要重启服务器。

> [!WARNING]
> 自定义工具能对服务器做**真实且可能不可逆**的改动：改文件、执行指令、装依赖、重启插件都只是一次函数调用。如果你提供了这类工具，请在相应技能文件里写清"必须先确认"的规则，并在函数内部按等级收紧——技能约束模型，函数内的检查才是运行时的最后一道防线。

## 3. 在自己的 MCDR 插件中注册工具

不修改 `tools.py`，直接在插件代码里注册：

```python
from games_ai.ai.games_ai_tool import register_tool, register_bot_tool

@register_tool(
    description="你的工具说明",
    parameters={...}          # 可选
)
@register_bot_tool()          # 可选：让 Bot 控制器也能调用
def my_plugin_tool(source: CommandSource, ai_prefix: str, ...):
    source.reply(f"{ai_prefix}正在执行...")
    return "工具执行结果"
```

要点：

- 你的插件必须在 `mcdreforged.plugin.json` 中声明依赖，以确保 GamesAI 先加载：

```json
{
    "id": "my_plugin",
    "dependencies": {
        "mcdreforged": ">=2.15.0",
        "games_ai": ">=0.6.1"
    }
}
```

- 用 `@register_bot_tool()` 时把版本门槛设为 `>= 0.6.0` 以上；
- 以插件身份注册的工具与内置工具、`tools.py` 里的工具**完全等价**：同样的权限规则、同样出现在模型的可调用列表里，`execute_in_hub` 的规则也一样（默认 `false` = 在玩家所在实例执行；属于 AI 实例的工具要传 `True`）；
- **凡是注册过工具的插件，都会在 GamesAI 热重载时自动重载**，工具代码始终跟随最新版本，无需额外处理。若你的插件只注册技能（不注册工具），或需要自己的重载逻辑，再使用 `register_self()`——见[热重载](hot-reload.md#热重载)。

## 4. 排查

| 现象 | 检查点 |
|---|---|
| AI 说没有某个工具可用 | `config.json` 的 `permission` 是否高于该玩家等级（`perm` 更高的工具根本不会发给模型） |
| 工具在 hub 上的玩家能用，别的实例上的玩家用不了 | 它是 `execute_in_hub=False` 且只有 hub 有：标成 `true`，或把同样的代码装到那台实例上（见上面"集群作用域"） |
| 自定义工具全部失效 | MCDR 日志里搜 `[tools_interpreter]`：加载失败会打印异常原因；被拒绝的函数会列在 `REJECTED` 后面 |
| 工具被调用但什么都没发生 | 函数内部的等级检查返回了"权限不足"字符串——模型会看到这句话，但不会执行任何操作 |
| 改完 `tools.py` 没生效 | 执行 `!!gamesai reload`，或让 AI 调用 `reload_plugin` |
| 想知道某个工具到底传了什么给模型 | 开 `!!gamesai debug`，每次工具调用都会记录工具名与结果长度（不记录参数与结果正文）。定义在 `tools.py` 里的工具可用 `read_custom_tools` 查看 |
