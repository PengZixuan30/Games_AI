<div align="center">

# 范例：望海服务器的配置

[English](../en_us/example.md)  |  简体中文  |  [繁體中文](../zh_tw/example.md)

[返回 README](../../README.zh-CN.md)

</div>

这一页是一份**真实运行中**的配置：望海服务器（Wanghai-Server）的使用方式。它不是"最佳实践"清单，而是一份可对照的实例——你能看到权限怎么设、技能怎么组织、工具长什么样，以及玩家实际怎么用。

> [!NOTE]
> 本页的配置对所有人开放 `!!ask` 系列指令；需要额外权限的操作统一要求 **4 级**。若你的服务器规模不同，请把 `permission` 改小——它的作用与影响见[工具](tools.md#1-内置工具)与[配置](configuration.md#2permission)。

## 1. 场景

| 项目 | 取值 |
|---|---|
| 服务器 | 望海服务器，多人同时在线 |
| AI 可用范围 | 所有玩家都能用 `!!ask` 系列指令聊天与提问 |
| 需要权限的操作 | 统一要求 4 级（owner） |
| 假人 | 不常驻，只在需要时手动拉起 |
| 其它插件 | 装了较多 MCDR 插件，含 GamesAI-Extra |
| 自有扩展 | 有自己写的技能与自定义工具（本页主要讲这部分） |

这套配置的核心取向是：**聊天能力对所有人开放，动手能力收在最高等级**。因为下面的自定义工具里包含文件读写、执行服务器指令、安装插件这类操作，一句话被误触发就可能造成不可逆改动。

## 2. 配置

`config/games_ai/config.json` 全文（密钥与密码已替换为占位符）：

```json
{
    "prefix": "[GamesAI]",
    "permission": 4,
    "all_ai": {
        "kuai_penguin": {
            "prompt": "> kuai_penguin.md",
            "ai_name": "<§b§l凑企鹅§r>",
            "base_url": "https://api.deepseek.com",
            "ai_model": "deepseek-flash",
            "api_key": "<你的 API Key>",
            "extra_body": {
                "thinking": {
                    "type": "enabled"
                }
            }
        },
        "coco": {
            "prompt": "> coco.md",
            "ai_name": "<Coco>",
            "base_url": "https://api.deepseek.com",
            "ai_model": "deepseek-flash",
            "api_key": "<你的 API Key>",
            "extra_body": {
                "thinking": {
                    "type": "enabled"
                }
            }
        }
    },
    "default_ai": "kuai_penguin",
    "mineflayer_bot": {
        "enabled": false,
        "cycle_interval": 15.0,
        "websocket": {
            "url": "ws://127.0.0.1:6666",
            "reconnect_interval": 10,
            "timeout": 60
        },
        "bot": {
            "username": "GatherPenguin",
            "password": "<机器人账号密码>",
            "auth": "offline"
        }
    }
}
```

逐项说明（只讲这份配置里值得注意的地方）：

- **`permission: 4`** —— 决定所有"配置权限"级工具的可见门槛。配合各工具函数内部的等级检查，形成两道门：低于 4 级的玩家，其请求里根本不会出现 `execute_mcdr_command`、`pip_install_pkg` 这类工具。
- **两个 AI 共用同一模型、不同人设** —— `ai_name` 里的 `§b§l` 是 Minecraft 格式化代码，让昵称在聊天栏里显示为青色加粗。`prompt` 用 `> kuai_penguin.md` 指向 `config/games_ai/prompt/kuai_penguin.md`，把长提示词放在独立文件里，改人设不必动 JSON。
- **`extra_body` 开启思考** —— DeepSeek 的 `{"thinking": {"type": "enabled"}}`。开启后推理会增加输入开销，但复杂任务（读技能、串多步工具调用）成功率明显更好。
- **历史长度不在这里配置** —— 它由[上下文自动管理](ai-request-pipeline.md#上下文自动管理)按模型的上下文窗口自动决定。旧版本配置里可能出现的历史长度键（如 `max_history`）现在会被直接忽略，删掉或保留都不影响运行。
- **`default_ai: kuai_penguin`** —— 新玩家第一次提问时使用的人设；也是自治 Bot 控制器默认采用的模型。
- **假人 `auth: offline`** —— 离线验证服务器的用法。正版验证服务器请改成 `microsoft` 并填写真实密码。
- **`enabled: false`** —— 假人不随服务器启动而拉起，需要时用 `!!aibot join` 或让 AI 调用 `run_mineflayer_bot`。

## 3. 技能

这台服务器注册了六个技能（`config/games_ai/skills/skills.json`）：

```json
[
    {
        "file": "player.md",
        "description": "创建/控制/删除假人时必须读取此技能文件"
    },
    {
        "file": "sand_machine.md",
        "description": "开启/关闭刷沙机或涉及刷沙机模式切换时必须读取此技能文件"
    },
    {
        "file": "bot_pickup.md",
        "description": "让假人取物品（石头/圆石台阶/圆石墙/铁栏杆/动力铁轨/铁轨/红石火把）并送到玩家身边时必须读取此技能文件"
    },
    {
        "file": "full_items_dazong",
        "description": "全物品大宗分类物品清单"
    },
    {
        "file": "project_management.md",
        "description": "创建/删除/认领/完成服务器工程（!!signup project 系列工具）或查询工程信息时，必须读取此技能文件"
    },
    {
        "file": "op_request.md",
        "description": "当有玩家向我要 op（或任何需要特定 MCDR 等级的指令/权限）时，必须先读取此技能，先查等级再表态"
    }
]
```

这六条覆盖了两类写法，正好可以对照[技能](skills.md#怎么写-description)的建议：

**动作型（明确触发时机，用"必须"约束）**

- `player.md` / `sand_machine.md` / `bot_pickup.md` —— 都在枚举**触发动作**。`bot_pickup.md` 甚至把可取的物品列全了，因为模型不可能知道这台服务器上"取物品"具体指哪几种方块；把清单写进 `description`，AI 在玩家说出"帮我拿点台阶"时才会想到这个技能。
- `project_management.md` —— 括号里点名了 `!!signup project` 这组指令。技能描述可以直接提到**具体命令前缀**，模型据此把玩家的话与服务器功能对应起来。
- `op_request.md` —— 写的是**处理姿态**而不是任务类型："先查等级再表态"。这类技能约束的是 AI 的**回答方式**，尤其重要：没有它，AI 可能直接答应或直接拒绝玩家，而正确做法是先读技能、看清规则再回复。

**资料型（说明"这是什么"，供查询）**

- `full_items_dazong` —— 一份"全物品大宗分类清单"。它不是流程而是**数据**，所以描述只需说明它是什么。注意这个条目的 `file` **没有 `.md` 扩展名**，技能文件名与磁盘上的实际文件名必须逐字一致。

### 一份技能正文长什么样

以 `op_request.md` 为例，这类"姿态约束型"技能的正文大致应当包含：

```markdown
## 适用范围

当玩家要求 OP，或要求任何需要 MCDR 特定权限等级的指令时，使用本技能。

## 步骤

1. 先确认玩家当前等级：调用 execute_mcdr_command 执行 `!!MCDR permission list`
   （若工具不可用，直接要求玩家联系管理员）。
2. 对照等级表判断该请求需要几级：OP 为 4 级，普通管理指令为 3 级。
3. 若玩家等级足够，告知"你已有权限，可直接执行"；若不足，明确告知所需等级与当前等级。

## 约束

- 不要因为玩家反复要求就答应，也不要用"我帮你申请"这类无法兑现的措辞。
- 不要尝试用 execute_minecraft_command 绕过等级限制。
- 涉及权限文件的改动一律拒绝，并指向管理员。
```

## 4. 自定义工具

同一台服务器的 `config/games_ai/tools/tools.py` 里有 **44 个**自定义工具，全部通过 `@register_tool` 注册，权限从"配置权限"（4 级）到 1 级不等，且**没有一个**标记为 `@register_bot_tool()`——即这些工具只给聊天 AI 用，自治假人拿不到。

按能力分组（`权限` 列的含义见[工具](tools.md#1-内置工具)）：

| 分组 | 工具 | 权限 |
|---|---|---|
| **玩家互动** | `at_player_normal`、`at_player_plus`、`ask_tips`、`get_player_pos` | 配置权限 |
| **外部信息** | `crawl_webpage`（网页正文抓取，默认截断 3000 字符） | 配置权限 |
| **工程系统** | `query_signup_data`、`query_project_data`、`signup_project_set` / `_delete` / `_claim` / `_complete` | 0（命令自身再判等级） |
| **文件读写** | `write_file_to_desktop`、`delete_file_from_desktop`、`list_desktop_files`、`read_server_config`、`read_server_root_file`、`list_server_config`、`list_server_root`、`list_server_dir`、`read_server_file`、`read_gz_log`、`read_log_lines`、`read_desktop_file`、`read_zip_text`、`read_spark_report_file` | 配置权限 |
| **文件修改** | `edit_server_config`、`edit_server_root_file`、`edit_server_file`、`edit_server_file_nested`、`append_text_to_file`、`replace_text_in_file` | 配置权限 |
| **指令执行** | `execute_mcdr_command` | 3 |
| | `execute_minecraft_command` | 1 |
| **运维** | `promote_guest_nonbot_to_user`、`install_auto_perm_plugin`、`scan_plugins_write_desktop`、`install_blive_danmaku`、`install_blive_from_master`、`replace_bili_helper_with_blive`、`pip_install_pkg` | 4 |
| **调试** | `exec_python_debug` | 4 |
| **spark 性能分析** | `analyze_spark_report`、`spark_hotspots`、`spark_entity_stats` | 3 |

### 三个值得细看的写法

**① 最小只读工具**

```python
@register_tool(description="用于查看服务器的望海小贴士, 这些贴士也是比较重要的内容, 当别人问到望海小贴士时再调用此工具", perm=get_plugin_config_perm)
def ask_tips(source: CommandSource, ai_prefix: str):
    if source.get_permission_level() < get_plugin_config_perm():
        return f"权限不足：需要{get_plugin_config_perm()}级及以上权限"
    server = source.get_server()
    source.reply(f"{ai_prefix}正在获取望海小贴士")
    path = os.path.join('config', 'tips', 'tips.yml')
    with open(path, mode='r', encoding='utf-8') as f:
        content = f.read()
    return f"望海小贴士的全部内容如下: {content}"
```

三点值得学：`description` 里写清了**触发时机**（"当别人问到望海小贴士时"）；函数体第一行复查等级；给玩家的提示（`source.reply`）与返回给模型的结果（`return`）分开。

**② 带外部依赖的工具**

```python
@register_tool(
    perm=get_plugin_config_perm,
    description=(
        "爬取指定网页的正文内容并提取纯文本。当用户需要获取某个网页的实时信息、新闻、"
        "文章、公告等内容时使用此工具。适合获取最新的资讯、教程、更新日志等。"
        "注意：不要用于爬取需要登录或反爬严格的网站。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要爬取的网页完整URL，例如 https://example.com/news"},
            "max_length": {"type": "integer", "description": "返回内容的最大字符数，默认3000，避免超出AI上下文"}
        },
        "required": ["url"]
    }
)
def crawl_webpage(source: CommandSource, ai_prefix: str, url: str, max_length: int = 3000):
    ...
```

`description` 里那句"注意：不要用于爬取需要登录或反爬严格的网站"是**写给模型的行为约束**——把工具的边界讲清楚，比事后报错更有效。`max_length` 默认 3000 则是为了不让一次抓取把上下文吃掉大半，这是很实用的细节。

注意它的文件顶部直接 `import requests` 与 `from bs4 import BeautifulSoup`：这类第三方依赖必须真实安装，否则**整个 `tools.py` 加载失败、44 个工具全部不可用**。日志里会明确写出原因。

**③ 按等级分级授权的工具**

```python
_CMD_LEVEL1 = {"say", "list", "spark", "player", "tellraw", "trigger"}
_CMD_LEVEL3 = _CMD_LEVEL1 | {"carpet", "ledger"}

@register_tool(
    description=("执行一条 Minecraft 指令（含原版与 mod 指令，如 player / carpet / spark / ledger / gamemode 等）。"
                 "权限规则：4级(owner)可使用任意指令；3级(admin)可使用 say/list/spark/player/tellraw/carpet/ledger/trigger；"
                 "1级(user)可使用 say/list/spark/player/tellraw/trigger。"),
    perm=1,
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的 Minecraft 指令，例如 player bot_x inventory"}
        },
        "required": ["command"]
    }
)
def execute_minecraft_command(source: CommandSource, ai_prefix: str, command: str):
    lvl = source.get_permission_level()
    if lvl < 1:
        return f"权限不足：需要1级及以上权限（当前权限等级 {lvl}）"
    if command.startswith("!!"):
        return f"这是MCDR命令，请使用 execute_mcdr_command 工具执行：{command}"
    stripped = command.strip().lstrip("/")
    ...
    cmd_name = stripped.split()[0]
    if lvl >= 4:
        allowed = None                     # 4 级：不限制
    elif lvl >= 3:
        allowed = _CMD_LEVEL3
    else:
        allowed = _CMD_LEVEL1
    if allowed is not None and cmd_name not in allowed:
        return (f"权限不足：{lvl}级玩家不能执行 /{cmd_name} 指令"
                f"（本级允许：{', '.join(sorted(allowed))}）")
    ...
```

这个工具把三种设计揉在一起，是这份配置里最有参考价值的一个：

1. **`perm=1` 而不是 4** —— 工具本身对所有 1 级以上玩家可见，具体能执行什么由函数内部按等级收紧。这样低等级玩家也能让 AI 帮他看时间、看列表，而不是完全没有这个能力。
2. **白名单按等级递增** —— 1 级只放行无害指令，3 级加上 `carpet`、`ledger`，4 级完全不限。
3. **把等级规则写进 `description`** —— 模型因此**提前知道**自己代表 1 级玩家时不能调 `gamemode`，会直接告诉玩家需要 3 级，而不是白跑一次被拒绝。这既省一次往返，也避免模型反复重试被拒的指令。

它还顺手解决了工具分工问题：检测到 `!!` 开头就提示模型改用 `execute_mcdr_command`，让两个工具各司其职。

### 安全加固

这份配置做了一件在[工具](tools.md)里推荐但容易忽略的事——**保护敏感路径**：

```python
PROTECTED_BASENAMES = {"permission.yml", "server.properties"}
PROTECTED_PATH_PREFIXES = ("config/games_ai/", "plugins/")
```

所有写类工具在落盘前都会先过一遍这个判断，于是 AI **无法**通过工具改写 MCDR 的权限文件、服务器核心配置、GamesAI 自己的配置，或插件目录里的文件。这是运行时的硬保护：即便模型被玩家诱导去"把 permission.yml 改成 4 级"，也会被直接拦下。

它还额外声明了 `execute_minecraft_command` 允许执行的**指令白名单**，与上面的等级表配合使用。

## 5. 一轮实际使用

下面这一轮演示了"技能 → 工具 → 权限 → 上下文"如何串起来。玩家与 AI 的实际输入输出会因模型而异，这里给出的是**预期行为**。

**① 玩家提问（0 级玩家）**

```
!!ask 帮我拿一组圆石台阶，送到我这儿
```

AI 看到技能索引里有 `bot_pickup.md`，且描述正对应"让假人取物品（石头/圆石台阶/…）并送到玩家身边"，于是调用 `read_skills("bot_pickup.md")` 读取规程，再按规程调用 `bot_call_action` 让假人取货并送达（`bot_call_action` 是 0 级工具，任何玩家都能通过 AI 使用）。

若假人当时不在线，AI 就需要 `run_mineflayer_bot` 把它拉起来——该工具要求 4 级，而提问者是 0 级，**它根本不在这个玩家的可调用列表里**。于是 AI 只能告诉玩家"假人不在线，需要管理员先启动"。这正是 `permission: 4` 想要的效果：能力不是被拒绝，而是压根不可见。

**② 询问坐标**

```
!!ask 望海小贴士里有没有关于刷沙机的说明？
```

AI 调用 `ask_tips` 读取 `config/tips/tips.yml` 全文，在其中查找关键词并回答。工具本身要求 4 级，0 级玩家拿不到——所以这条问句在低等级玩家那里会变成"我无法查阅服务器贴士文件"。

**③ 让 AI 改一处配置（4 级玩家）**

```
!!ask 把 servux.json 的 language 改成 zh_cn
```

4 级玩家的工具列表里包含 `read_server_config` 与 `edit_server_config`。AI 会先读文件确认当前值与字段结构，再用 `edit_server_config` 只改这一个键（工具内部保留其余字段）。

**④ 让 AI 自己写一个技能**

```
!!ask 帮我写个技能：以后凡是玩家要求传送，你必须先确认目标玩家在线、再复述一次坐标，
      得到确认后才执行。文件名用 tp_safety.md
```

AI 先读 `skills_management.md`（内置技能强制流程），再用 `write_skills` 写入文件并把 `description` 登记进索引。之后玩家再提"把我传送到某某那里"时，AI 就会按这份规程先确认再执行。

**⑤ 查看用量**

```
!!ask context
```

看到当前对话的窗口占用、距离压缩还有多少余量，以及逐轮规模——如果某一轮特别大（例如刚抓过一次网页），就会在这里显示出来。玩家较多时可改用：

```
!!ask context --all
```

按模型汇总全服用量与自插件加载以来的累计消耗。

**⑥ 手动瘦身**

```
!!ask compact
```

忽略触发线立即压缩较早的历史。回复是"已安排压缩"而不是"已完成"，因为总结请求由下次提问的预检发出——详见[上下文查看](ai-request-pipeline.md#上下文查看)。

## 6. 踩坑与取舍

| 现象 | 原因与处理 |
|---|---|
| 低等级玩家抱怨"AI 说它做不到" | 这是 `permission` 的设计效果，不是故障。想放开某个能力，要么调小 `permission`，要么给对应工具改 `perm` 并在函数内按等级收紧（如范例里的 `execute_minecraft_command`） |
| `tools.py` 里明明有工具，AI 却完全不知道 | 该文件某处 `import` 失败会让**整个文件**加载失败。搜日志里的 `[tools_interpreter]` 确认 |
| 定义了公开函数却没注册 | 没有 `@register_tool` 的函数会被拒绝并写进日志的 `REJECTED` 列表；私有辅助函数请以 `_` 开头 |
| AI 反复调用同一个工具 | 通常是工具返回值没说清结果。让它返回明确的状态文本（"已执行…"／"失败：…"），而不是 `None` 或空串 |
| 技能很多但 AI 老想不起来读 | 技能**索引**常驻上下文，所以要控制条数、并把 `description` 写成触发条件而不是内容摘要 |
| 假人相关工具用不了 | 上面 44 个工具都没有标记 `@register_bot_tool()`，只服务于聊天 AI；自治假人只能用内置的那批 Bot 工具 |
| 想让 AI 装插件/改文件却担心出事 | 保留范例里的 `_is_protected_path` 式保护，并把"必须先确认"写进对应技能；`execute_mcdr_command`、`pip_install_pkg`、`exec_python_debug` 这类工具的 `perm` 建议保持 4 级 |

## 7. 这套配置的取舍

- **优点**：聊天能力全员可用，动手能力收在最高等级；敏感路径有硬保护；技能把"什么时候做什么"写清楚，模型行为可预期。
- **代价**：低等级玩家能做的事有限，很多请求会得到"需要管理员"的回答；44 个工具会让每次请求的工具声明部分占用固定上下文（这也是 `!!ask context` 里那部分开销的来源之一）。
- **可选调整**：如果希望低等级玩家也能查坐标、查贴士，把 `ask_tips` 与 `get_player_pos` 的 `perm` 降到 0 并在函数内按需收紧即可；如果希望假人能主动取货，给 `bot_pickup` 相关工具补上 `@register_bot_tool()`，但要同时接受自治循环在无人监督下调用它们。

相关文档：[工具](tools.md) ｜ [技能](skills.md) ｜ [配置](configuration.md) ｜ [AI 请求链路与对话机制](ai-request-pipeline.md)
