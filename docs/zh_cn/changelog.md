<div align="center">

# 本次更新

[English](../en_us/changelog.md)  |  简体中文  |  [繁體中文](../zh_tw/changelog.md)

[返回 README](../../README.zh-CN.md)

</div>

## Version 0.8.1

0.8.0 自更新的修复版本。**运行 0.8.0 或 0.8.0-SNAPSHOT 的实例必须先手动安装一次 0.8.1**（`!!MCDR plugin install -U -y games_ai`），因为坏掉的自加载逻辑正是自更新本身要执行的代码；手动安装这一次之后，自更新恢复正常。

- **自更新现在用 MCDR 枚举出的路径加载插件**：替换文件时传给 `ServerInterface.load_plugin` 的是归档的**绝对路径**，而 MCDR 会拿它和从 `plugin_directories` 枚举出的路径逐字比较 —— 默认配置里的 `plugins` 是相对路径，两者永远不相等，于是 MCDR 根本没有执行加载（只打了一行「正在从 … 加载插件」）却返回 `False`；更新器把它当成「拒绝加载」并回滚，而回滚同样什么都没加载，插件就这样留在未加载状态。现在更新器会把 MCDR 为这个文件枚举出的路径拼写原样传回去（文件夹是符号链接/junction 时用文件同一性比较兜底），新版本与每一次回滚都通过 MCDR 报告的版本复核：什么都没加载的替换不会再被报告成成功，也不会再谎称「旧版本已恢复」。
- **卸载后的失败提示仍然可读**：回滚没能把旧归档加载回来时插件处于未加载状态，MCDR 已经没有它的翻译资源；失败提示现在会退回到可读的英文句子，而不是未翻译的键名。

## Version 0.8.0

> **本版本已知问题**：当 `plugin_directories` 为相对路径（默认配置）时，0.8.0 的自更新无法加载下载的归档，因此运行 0.8.0 的实例需要手动安装一次 0.8.1（见上方 0.8.1 的说明）。

- **不开 debug 也能看懂报错**：失败的请求现在会打出一条 WARNING 日志行，含状态码、它的本地化含义与服务商的 Request ID（以前是 DEBUG 行）；玩家回复里，只要失败不是密钥错误或限流，含义就紧跟在状态码之后（例如 `HTTP 402 (API Key 余额不足)`），401 与 429 保留各自的句子，已经点明了原因。
- **对话历史会落盘**:每个 `ChatParam` 在每轮结束后写入 `config/games_ai/database/public_database.db` 的 `chat_history` 表,并在每次插件加载时还原 —— 重载、更新、重启乃至卸载插件都不会再丢失任何人的对话。它和 `!!data` 是同一个数据库文件(不同的表),集群里这份存储属于 hub;删掉该文件会同时丢掉两者。`!!ask context` 显示的那些数字也随对话一起存下（上次请求用量、本轮计数、最近一次压缩），重载后就回来了；只有"当前占用"是加载时按还原出的历史重新估算的，因为工具 schema 属于下一次请求。
- **给其他用户的助手捎话**:新增工具 `send_message_to_player_ai`,让当前用户的助手把一条消息交给**任何人**的对话。它是单向的(对方下次提问时才会读到,不会唤醒对方),并且对所有人开放:唯一的要求是目标已经拥有对话 —— **不比较也不查询任何权限等级**(两边都不查),所以一次转达不可能往 `permission.yml` 写入名字。控制台自己的对话同样是合法目标(键名 `Server Control Panel`)。
- **`!!ask stop` 会保留这一轮已经写下的内容**：停止一轮不再删除它打断的那一步。提问、注入的提示（时间、技能）以及每一个结果已经回来的工具调用都留在历史里，也留在落盘的对话里；只有末尾那个结果从未到达的工具调用会被丢弃（一整批未完成的并行调用会整体丢弃，因为服务商拒收没有结果的 `tool_calls` 消息）。排队的 `!!ask -f` 消息也不再被丢弃 —— 下一轮会照常合并它们。
- **可以按名字清除某个玩家的历史**：新增的 `!!gamesai clear <name>` 会删除另一个玩家的对话 —— 内存里的和落盘的那一行 —— 并且需要配置的 `permission` 等级（不带名字的 `!!gamesai clear` 只涉及你自己的历史，仍然不需要任何等级）。目标玩家仍在途的那一轮会先被停掉，而一份已经不再是注册对话的对话绝不会被再次落盘，所以这次清除不会被打断它的那一轮撤销。
- **工具作用域**：新增 `execute_in_hub` 注册参数（默认 `false`）。每次跨服请求由发起方上传本机可执行的工具 schema，hub 据此决定哪些调用在本机执行、哪些回传给发起方，模型不会再看到两边都没有的工具。权限由发起方用自己的 `permission.yml` 重新裁定；回传调用不自动重试，超时如实报告"结果未知"。
- **角色记忆与宽限期**：判定结果写入 `config/games_ai/cross_server/role.json`，曾经是 client 的实例重载后会等待 hub（默认 15 秒）而不是抢端口；本机绑不上的地址永不判 hub；hub 自身重载仍立即判定；**没有身份**的实例在 hub 始终不回来时仍然会接管。
- **链路的运行时状态集中在一个目录**：节点的 token（`identity.json`）、hub 的节点表（`nodes.json`）与角色记忆（`role.json`）都放在 `config/games_ai/cross_server/`。
- **插件自己下载并替换自己**：不再使用 `!!MCDR plugin install`。新版本从本插件自己的 GitHub release 下载（`https://ghfast.top/<地址>` 为第二来源），只有公告的尺寸、sha256 **以及**归档内的插件 id 与版本全部相符才会被接受;安装过程是卸载插件 → 删除旧文件 → 移入校验过的文件 → 重新加载 —— 新文件起不来时会恢复 `.bak` 并用旧版本重新加载。任何一步失败都会结束这一轮并说明原因;这里**刻意没有**退回 MCDR 安装器的兜底。
- **集群更新先节点、后 hub**：hub 先命令每台在线节点，阻塞等到它们都 `staged` **并且**以新版本重连回来，最后才替换自己的文件。节点的跨服角色每次加载只判定一次,正是这个顺序挡住了"hub 不在时加载的节点抢占 hub 端口"。已入网实例**永不**接管 hub 角色（hub 彻底没了时的出路是先执行 `!!gamesai node forget`），跨服客户端完全不跑更新检查，`!!gamesai check` 是在 hub 上执行、由它发起并协调整轮更新的命令。
- **插件自己安装 Python 依赖包**：启动时缺少 `openai`、`requests` 或 `websockets` 不再意味着插件闲置或根本无法加载。它会报出缺哪些包、用 pip 补装（先用本机 pip 配置，失败后改用阿里云 PyPI 镜像重试，pip 的每一行都写进日志），装好能 import 之后自动重载自己。为此 `requirements.txt` 从插件根目录移入包内：根目录的 `requirements.txt` 不满足时 MCDR 会直接拒绝加载插件，那样插件就永远没有机会自我修复。

- **排队提问只得到一条合并回答**：对话已在回答时再发的 `!!ask` 不再启动第二轮。对话现在有原子的轮次持有者（一把锁加 `active` 标志，而不只是 `is_stopped` 事件）；等待的玩家会立刻收到与平时相同的“思考中”提示,轮次结束后排队的问题按到达顺序作为**一条合并的后续轮**发出,回答串流给该轮持有者。`!!ask stop` 会保留排队问题并在之后发出;服务器变更提示在轮次开始前写入(不会落进工具调用组中间),轮次准备阶段的异常会被记录并照常回复,不会再让对话卡在“运行中”。
- **技能工具只动技能目录内的文件**：`write_skills`/`modify_skills`/`delete_skills`/`read_skills` 拒绝绝对路径、`..` 穿越与带子目录的文件名 —— 模型收到错误,而不是读写/删除 `skills/` 之外的文件。
- **重载不会把 AI 轮次推给集群**：集群广播只会发送来源真正输入的命令;重载工具不再把 AI 轮次的命令来源传给 `!!gamesai reload`;节点会直接拒绝被广播的 `!!ask`。会话 id 按实例唯一,一个实例的回传不会再落到另一个实例的本地玩家身上。
- **不认识的远端玩家仍然未知**：跨服权限查询通过 MCDR 的权限管理器并传入 `auto_add=False`,没见过的名字一律 0 级,路由命令不再改写 `permission.yml`。
- **公共数据库只有一条加锁连接**：`!!data` 与 AI 工具共用一条 SQLite 连接并使用原子 append,两条并发 `add` 都会保留;卸载时关闭连接,数据路径变化时重新打开。
- **坏的重载输入不再阻止插件加载**：损坏或不是列表的 `skills.json` 会被记录并当作“没有技能”;配置中已删除模型的对话会保留旧客户端并打一条警告,而不是让重载失败(正在回答的对话会被跳过)。
- **机器人启停以真实进程为准**：配置写着启用但进程已经崩溃的机器人会被强制重载重启;禁用会取消仍在等待服务器的启动;在 `run_node` 期间被中止的启动会杀掉刚创建的进程,不会继续创建控制器。
- **失败的动作不再弄死机器人**：内嵌 `init.js` 动作 switch 中的异常会作为错误帧回传(进程继续运行);失败的 `goto` 总会清空寻路目标,而不是让机器人继续走。
- **更新轮次如实汇报**：ack 超时记为可纠正的 `timeout`(节点稍后仍可上报 `staged`)而不是 `failed`;没有上报版本的节点会被照常下令,而不是拿空字符串去比较;回滚只有在恢复出的归档与备份逐字节一致后才宣称成功。
- **上下文压缩不再阻塞命令处理**：摘要请求在上下文锁之外执行(只读的 `!!ask context` 不会再在 MCDR 命令线程上等上近一分钟),摘要生成期间追加的消息也不会丢失(替换被跳过,并在下一次预检重试)。
- **`setting_timer` 默认拒绝无上限等待**：超过 600 秒的等待会被拒绝并提示重试方式,除非模型显式传入 `allow_long_wait=true`。
- **扩展插件卸载不再把“排队”误报成 not found**：`on_unload` 本身运行在 MCDR 的插件操作链里,此时再卸载另一个插件只会被排队,而 MCDR 的 `unload_plugin` 对“已排队”和“插件不存在”都返回 `None`。现在日志会检查 MCDR 是否仍持有该插件的实例:排队会以 INFO 记录,只有确实已不存在的插件才报告为 not found 并从卸载列表移除。
- **`!!ask context --all` 现在按配置的 AI 条目汇总，而不是按上游模型**：两个 `all_ai` 条目即使指向同一个 `ai_model`,过去也会被合并成一行(行名取最先读到的那段对话),于是玩家分散在两个助手时命令仍显示“1 个模型”。现在每一行是一个配置条目(行名用 `ai_name`),悬停显示 `all_ai` id 与服务商实际计费的上游 `ai_model`。无法读取用量的对话会写一条日志并被跳过,不再从合计里悄悄消失。
- **带颜色的 `ai_name` 不再把 `!!ask context --all` 行的后半段刷成白色**：`ai_name` 允许包含 § 格式代码(配置文档中有说明),在灰色的模型行里它们会覆盖行颜色,而 `§r` 会让名字之后的内容变成默认白色。现在名字之后会重置并重新设为灰色,配置的名字保留自己的颜色,人数/占用/本轮数字恢复灰色。

本次更新的主题是**跨服连接**：多个 MCDR 实例可以组成一个集群，共用同一个 AI、同一份对话历史和同一份公共数据库。

### 🌐 跨服连接

- **自动定角色**：插件启动时探测 `websocket.uri`。能连上且确认对端是 GamesAI → 本机做**客户端**接入；连不上且端口空闲 → 本机自己**监听**并成为 hub；`force_server` 打开 → 强制做 hub（端口被占则报错并退回 local）。
- **不是 GamesAI 就不碰**：`uri` 被别的服务占用时，跨服功能整体停用（既不当客户端也不起服务端），本机功能完全照旧。
- **互认握手**：`hello` / `hello_ack` 都带 `"app": "games_ai"` 与协议版本，对不上就以专用关闭码拒绝；启动前的探测带 `"probe": true`，**只回答不登记**，不会污染在线名单、也不会误触顶号。
- **每 node 专属 token**：新实例先在 hub 上 `!!gamesai node pending` 查看、`node token <名字>` 签发（只有等待中的名字可签发），再到该实例 `node claim <token>` 领取；hub 只存 `sha256` 哈希，明文 token 只在回复里出现一次。关闭码 `683`（需要注册）与 `683`（token 过期）均不可重试；有效期由 hub 的 `websocket.token_ttl_hours` 控制（默认 `-1` 永久），只在握手时校验。机器人由 hub 自动签发，无需人工。
- **`websocket.name`**：可覆盖本实例在集群里的名字。留空时按**实例目录**派生（`<目录名>-<路径哈希前 6 位>`，如 `survival-9f31ab`），同机双实例不会撞名，改机器名也不影响注册。
- **握手 ID 区分 peer 种类**：`games_ai_mcdr`（实例）与 `mineflayer_bot`（假人）两种身份，hub 按它自动适配 —— 集群广播只发给可信实例，绝不发给假人；`hello_ack` 的 `app` 恒为 hub 自己的 `games_ai_mcdr`，并用 `you` 字段告诉对端被认成了什么。
- **`websocket.allow_app_id`**：字符串列表配置，让你自己的服务接入本 hub 时不被 `683` 拒绝。hub 不为这些 ID 做专项适配（它们就是普通 peer），但它们会被**完全信任**，可像 GamesAI 实例一样触发命令执行，所以只填自己控制的服务。
- **身份用实例目录**：客户端名默认由实例目录派生，也可以用 `websocket.name` 指定。同名后到者仍会顶掉先到者（旧连接收到 `683` 并带着原因退出），并且 hub **拒绝**为已经注册过的名字再签发 token —— 那会把在线的那个节点顶下线（`683`，不可重试）；要刻意替换请用 `!!gamesai node rotate <name>`。
- **角色会被记住**：判定结果写入 `config/games_ai/cross_server/role.json`，曾经是 client 的实例会等待 hub（默认 15 秒）而不是抢端口；hub 自身重载仍立即判定。本机绑不上的地址永不判 hub；**没有身份**的实例在 hub 始终不回来时仍然会接管。
- **链路的运行时状态集中在一个目录**：`config/games_ai/cross_server/` 存放节点的 token（`identity.json`）、hub 的节点表（`nodes.json`）与角色记忆（`role.json`）。
- **local 模式仍有本地链路**：本地回环（`127.0.0.1` 随机端口）上会起一个只服务本机 peer 的 hub，让假人在任何模式下都有地方接入。
- **机器人不能指挥 hub**：`mineflayer_bot` 由 hub 在回环地址上自动签发（隧道/反向代理会让 hub 把所有来源都看成回环），因此 hub 在路由之前就拒收机器人身份发来的 `command`、`command_cluster`、`exec_cluster`、`tool_call`、`event` 帧（`reply` 与 `ping` 照收），并记一条 warning。
- **注册有频率与容量上限**：每个 IP 每分钟最多 10 次新名字请求，等待列表上限 32 条、7 天自动过期；已注册节点握手时若 `last_seen` 没变，不再重写节点表。
- **帧在发送前先量尺寸**：超过 1 MiB 时，工具结果会变成一条诚实的错误、流式输出会变成一行提示，因此对端不会用 `683` 关闭链路、把正在跑的对话一起带走。
- **对端断开会唤醒等待中的调用**：节点崩溃（或 hub/node 停止）会立即释放所有等待中的调用并回"结果未知、不要重试"，而不是让它们各自撞满 120 秒超时。

### 🧩 命令按类路由

- **A 类（交给 hub 执行）**：`!!ask`（含 `-n/-f/switch/stop/compact/context`）、`!!data`、`!!gamesai clear [name]`、`!!gamesai speedtest`、`!!gamesai config get/set`、`!!aibot join/leave/set`。
- **B 类（本地执行）**：各命令的帮助文本。
- **C 类（集群广播）**：`!!gamesai clearall`、`reload`、`debug`、`debug thread` —— hub 与所有客户端各自执行；发起方自己那台的输出不加前缀，其他台加 `[实例名]`。（`!!gamesai check` 属于 A 类：检查更新是 hub 的决定，随后由它协调整个集群。）
- **内部调用永不转发**：`server.execute_command()` 这类没有 Info 的调用留在原地，否则 `reload` 会在集群里来回弹。
- **权限**：远端玩家取 `min(客户端上报等级, hub 侧 permission.yml)`，hub 不认识这个名字就是 0；远端控制台恒为 4。

### 🎨 富文本回传

- 跨服回传使用 **MCDR 自己的 JSON 文本对象**（`to_json_object()` / `from_json_object()`），颜色、粗体/斜体/下划线/删除线、hover 文本、四种点击动作（`run_command` / `suggest_command` / `copy_to_clipboard` / `open_url`）与嵌套列表全部保真，因此 `!!data read` 的写入/复制按钮在客户端一样能用。
- 远端命令由一个只继承 `CommandSource` **基类**的 `WebSocketCommandSource` 代表（发起者可能是玩家也可能是控制台，所以不冒充任何子类），`source.reply()` 就是流式回传通道。

### 🤖 假人接入集群

- Mineflayer 机器人从「**自己开一个 WebSocket 服务端**」改成「**接入集群的客户端**」，以机器人用户名注册，动作仍走原来的 switch，因此所有 bot 工具与自治控制器的行为不变。
- 不再占用端口：旧的机器人地址被占时不必再改配置，机器人的链路也不会和跨服链路抢同一个端口。
- 启动顺序改为**先定角色、再写机器人配置并拉起进程**（机器人连的地址取决于本机角色）。

### 🔧 修复

- **OpenAI 请求日志没有桥接到 MCDR 日志器**：`openai` 2.x/3.x 的 HTTP 依赖已从 `httpx` 换成 `httpx2`，而日志桥只桥接了 `httpx`，导致 `INFO:httpx2:HTTP Request: ...` 冒泡到 root logger、以裸格式打在 MCDR 控制台里。现在桥接的 logger 名字**从已安装 SDK 的元数据推导**，依赖再改名也不会重演。
- **配置迁移**：旧的 `mineflayer_bot.websocket.url` 自动搬到顶层 `websocket.uri` 并删除旧块；新增的 `websocket` 块由 MCDR 的 `data_processor` 钩子在补默认值**之前**处理，不会覆盖用户已有的地址。
- **时间读数改由时钟驱动刷新，并且带上了时区**：此前一段对话无论闲置多久都拿最后一轮读数的时间回答 —— 20 轮在一次会话里是 20 秒，在下一次就可能是 20 小时 —— 而且读数只是本地时间串，没有任何偏移。现在第 1 轮、每 20 轮、**以及距上次读数超过 10 分钟时**都会刷新；读数是四行：带服务器 UTC 偏移的 ISO 时间戳、本读数所用的时区、距上次读数的时间、距上一条消息的时间。两个基线随对话一起存储，重启与压缩都不会让它们失真；没有基线可量时读数写 `unavailable`。时区由插件从机器上判定（`TZ`、系统自带记录、C 库名称），数字偏移始终取自时钟本身，因此 DST 与刚被改动过的时钟都不会算错 —— 而且刻意不做任何配置项，因为服务器只运行在一个时区里，也就是操作者的那个。这四行是写在代码里的英文而不是翻译串（`lang/*.yml` 里对应的键已删除）：它们是给模型看的，含义不该随服务器恰好在用的语言变化。自主控制器自己的时间行同样换成这套时间戳与时区、同样用英文；它的消息每轮重建，因此不需要轮号与时间差两行。

- **生成的 `tools.py` 骨架文件导入了一个已不存在的模块**：首次启动时 `on_load` 会把 `from games_ai.games_ai_tool import register_tool` 写进 `config/games_ai/tools/tools.py`，[工具](tools.md) 页面与内置的 `custom_tools_management` 技能展示的是同一行 —— 三者都写于模块被收进子包之前。该导入会抛 `ModuleNotFoundError`，而 `tools.py` 是作为**一个**模块加载的，因此文件里的**每一个**自定义工具都会跟着失败：日志里只有一行 `Failed to load external tools: No module named 'games_ai.games_ai_tool'`，没有任何工具注册成功。现在骨架文件与两个文档里的路径都是 `games_ai.ai.games_ai_tool`；[热重载](hot-reload.md) 里的 `register_self` 示例（`games_ai.ai.register_extra_plugin`）与 [技能](skills.md) 里的 `register_skills` 示例（`games_ai.ai.external_skills_loader`）做了同样的修正，`tools/build_context_table.py` 也改为重新生成插件真正读取的那个文件（`games_ai/ai/context_table_data.py`），而不是子包化之前的路径 —— 在那个路径上更新表只会写出一个没人引用的模块，随版本内置的兜底表依旧是旧的。新增的文档检查会导入这些页面给出的每一行 `games_ai` 导入（模块**与**名字），被移动过的模块再也不能留下一份可复制粘贴却跑不通的示例。

- **更新检查循环不再播报没人要求的检查**：加载时与每 24 小时各跑一次的那次检查，过去会向全服广播「正在检查更新」，紧接着再广播「没有新版本」—— 每次加载都刷一行，为的却是一个没有玩家在等的决定。现在它保持安静：`正在检查更新` 与 `没有新版本` 只写进调试日志（`!!gamesai debug` 可见），只有真的发现新版本时才播报，并接着播报安装它的那一轮。`!!gamesai check` 不变 —— 有人敲了命令，所以它照常回报「正在检查更新」与结果，且只回给输入者 —— 检查**失败**（拿不到目录或元数据）在两条路径上都保持可见，因为那需要运维介入。（四个场景由 `tests/test_update_notice.py` 锁定。）

- **远程命令源现在实现了整套命令源 API**：从另一个实例转发过来的命令由 `WebSocketCommandSource` 代表，为本地玩家/控制台命令源写的处理函数不应感到任何差别。`get_info()` 现在存在：它用转发来的命令行重建该命令的 `Info`，并在 MCDR 允许时在本实例上 finalize，因此 `Info.get_server()` 与 `Info.get_command_source()`（返回的就是本 source）与本地命令表现一致 —— 而路由过来的**工具调用**背后没有命令，会以 `IllegalCallError` 明确拒绝，而不是凭空编一个。`get_preference()` 在远程玩家的情况下按名字查本实例的偏好文件（控制台与未知名字用默认值），于是 `preferred_language_context()` 的解析与本地命令一致。`reply()` 会采用控制台源的 `console_text`、并接受玩家源的 `encoding`；两个 source 在"同一实例上的同一发起者"时相等 —— 与 MCDR 内建命令源的比较方式一致，也因此和内建源一样不可哈希。`_raw_command` 在转发源上显式返回空：它现在有 `Info`，若无这道守卫，来自链路的命令会被再次转发、集群命令会被再次扩散，永远停不下来。`tests/test_ws_command.py` 逐个成员覆盖了这套 API。

- **`!!ask` 这一轮重新回到自己的线程上**：拆分进子包时，`ask_ai` 上的 `@new_thread("games_ai@ask_ai")` 装饰器被丢掉了，于是整轮 AI 请求 —— 服务商往返、流式输出、工具调用，动辄数分钟 —— 全都跑在 MCDR 的同步 TaskExecutor 上。MCDR 的看门狗在 `advanced.watchdog_threshold`（默认 10 秒）没有响应后就会判定执行器无响应并**重建**它，每次都把本插件的线程栈打进日志 —— 这就是"一边回答一边疯狂重建执行器"的原因，其它命令也全被堵在这一轮后面。装饰器已恢复，线程名仍是 `games_ai@ask_ai`（`on_unload` 早已在报告这个名字），因此命令立刻返回、整轮在独立线程上流式输出，与拆分之前完全一致。`tests/test_migration.py` 锁住这个包装；`tests/test_ask_errors.py` 的失败场景改走 `ask_ai.original` 调用未装饰的函数体，因为失败必须发生在测试线程上。

### 📚 文档

- 新增专门的三语文档 [跨服连接](https://github.com/PengZixuan30/Games_AI/blob/main/docs/zh_cn/cross-server.md)：角色判定、配置、协议帧、命令分级、权限、富文本、假人接入与排障。
- `configuration.md`（新增 `6.websocket` 一节）、`mineflayer-bot.md` 与 `troubleshooting.md` 已按 0.8.0 的跨服行为更新。

### 🧱 内部结构

- **实例设置只有一个来源**：`__init__.py` 里与 `plugin_config` 并存的 8 个影子全局（消息前缀、命令权限、模型表、默认模型、数据库路径、技能索引、AI 名称到 ID 的映射、调试开关）已全部删除，所有读取点改为 `plugin_config.<字段>`（其它模块本来就这么做），`_apply_config` 每个值只写一次。名称到 ID 的映射改为 `_ai_id_for()`，配置改动后不会再失效；`send_help()` 也去掉了在 54 处调用点重复传递的前缀参数。
- **假人的 JavaScript 独立成模块**：`games_ai/bot/mineflayer_service_files.py` 收拢了内嵌的 683 行 `init.js`、`package.json`，以及配套的两个写入函数与哈希校验——它们原本占 `mineflayer.py` 的 70%，该文件从 683 行降到 581 行。写入函数与哈希校验都原样搬进了新模块（`get_default_init_hash()` 比较的仍是同一个摘要），因此这次拆分本身不会重写任何已部署的 `init.js`；该文件会被 0.8.0 的假人链路改动替换一次，这正是哈希校验本该做的事。
- **更新链路独立成模块**：`games_ai/update/update_round.py` 收拢 24 小时检查、集群轮次与版本比较（695 行原本在 `__init__.py` 里，该文件现在为 3579 行）。它通过 `attach()` 注入的取值函数**在使用时**读取实例的实时状态，因此从不 import 入口模块，也总能拿到当前的跨服管理器。更新的触发时机与流程没有变化。
- **帮助文本独立成模块**：`gamesai_help` 类与它的 `send_help` 辅助函数从 `games_ai/__init__.py` 搬进了 `games_ai/ui/help.py`（172 行），入口模块也正是因此降到 3579 行。新模块不从入口模块 import 任何东西 —— 问候语里的版本号直接来自 MCDR 的插件元数据；入口模块仍然转出这两个名字，原先 import 它们的代码不受影响。`!!gamesai` 与各命令的帮助行输出与之前完全一致。
- **权限校验只有一个出处**：`games_ai/core/permission.py`（58 行）取代了只服务 node 命令的 `_node_require_permission`，以及后来在它旁边长出来的四十处同样的比较。`require_permission(source)` 是每个命令与帮助处理器调用的那道门 —— 它发出本地化拒绝并返回 `False`；`has_permission(source)` 是它背后的谓词，供工具包装函数与帮助列表使用；工具返回给 AI 的两句话改为常量（`TOOL_DENIED_LEVEL`、`TOOL_DENIED_NOT_ALLOWED`），不再是 8 处与 3 处各写一遍。它必须独立成模块，因为 `help.py` 不能 import 入口包。唯一可见的变化：帮助页面与 `!!aibot` 的拒绝消息现在也带消息前缀，与它们打印的其它行一致。
- **node 命令独立成模块**：`!!gamesai node` 下的八个处理函数 —— pending、token、list、revoke、rotate、claim、status、forget —— 与只被它们使用的助手一起从 `games_ai/__init__.py` 搬进了 `games_ai/commands/node.py`（409 行）。该模块不 import 入口包：实时链路、插件 server 接口、身份文件与链路的重启/停止都由一次 `attach()` 调用注入，与 `update/update_round.py` 已有的做法相同。其余行为不变 —— 同样的回复、同样的权限门，以及同样"不经过集群路由、在输入处执行"的注册方式。
- **插件源码现在是一棵子包树**：原先并排放在 `games_ai/` 里的模块按职责分组 —— `core/`（设置、日志、依赖门、权限规则、数据库）、`commands/`（玩家输入的命令：`!!data`、`!!gamesai config`、`!!aibot`、`!!gamesai clear`、`!!gamesai node`）、`cluster/`（角色决定、hub、节点客户端、远程命令源）、`ai/`（请求链路、服务商客户端、上下文窗口表、工具注册表、技能索引）、`bot/`（Mineflayer 进程、它的控制器、内嵌 `init.js`）、`update/`（自更新与驱动它的轮次）与 `ui/`（帮助文本）。四组命令处理器离开入口模块搬进 `games_ai/commands/` —— `!!data` 管理器、`!!gamesai config` 与 `!!aibot set`、`!!aibot join`/`leave`、`!!gamesai clear`/`clearall` —— 入口因此从 3642 行降到 3579 行。子包的 `__init__.py` 同时也是门面：它转出该包的公开名字 —— 不需要第三方的 eager 导入，需要第三方的首次访问时才导入（PEP 562）—— 因此早早 import 一个包仍然不会把第三方包拖上"缺包也能加载"的门前路径，而入口模块现在一切取自这些门面。每个门面还用 `if TYPE_CHECKING:` 块把懒加载的名字再声明一次：那个块永不执行，但编辑器与类型检查器读的就是它，因此 `from .ai import ChatParam` 拿到的是真实签名而不是 `Any`。`tests/test_layout.py` 现在守护这棵树 —— 已知子包与模块、门面（`__all__` 可解析、eager 导入门前安全、静态块与运行时映射一致、入口不越过门面直接引用模块）、导入图无环与门前闭包 —— 新增的三语[架构](architecture.md)页面把它画了出来。
- **校验套件进入仓库**：运行器换成了 pytest —— 在仓库根目录直接执行 `python -m pytest` 就能收集整套 593 个用例（`tests/` 顶层的 42 个测试模块，加上 `tests/docs/` 下的 5 个文档检查器），配置来自根目录的 `pytest.ini`；以前逐个启动它们的自研运行器 `tests/_run_suites.py` 已不存在。每个套件原先各自携带的东西现在只有一份：共享 fixture（`free_port`、安静日志默认值，以及把插件的仓库相对路径钉在临时目录里的会话级兜底）在 `tests/conftest.py`，助手模块与三个协议原型在 `tests/_helpers/`。它们从自身位置推导仓库路径，不再写死某台机器上的绝对路径；新增的三语[测试](testing.md)页面说明怎么装 pytest、怎么跑全部/单个模块/按名字筛选用例，以及跑测试需要什么。新增的 `tests/test_layout.py` 守护布局本身 —— 模块清单、入口模块的行数预算、包内导入图无环、依赖门之前的导入只需要标准库与 MCDR，以及文件级约定。打包不受影响：MCDR 只打包清单 `resources` 列出的内容，`tests/` 不会进入 `.mcdr`（已对实际打包产物核验）。

- **编辑器现在能拿到 `games_ai.*` 的真实类型**：插件会把一个生成出来的 `games_ai/` 存根包（`.pyi`）播种到 `config/games_ai/tools/`，就在用户的 `tools.py` 旁边，因此 VS Code 能在**不需要任何工程配置**的情况下解析 `from games_ai.ai.games_ai_tool import register_tool` 以及其它文档承诺的导入 —— 此前该导入会被报为无法解析，插件里的每个名字都是 `Any`。与被编辑文件同目录的存根包会被自动找到；对以 `.mcdr` 打包安装的情况，这也是唯一途径：它的源码在归档里，语言服务器读不到（目录安装可以改用 `python.analysis.extraPaths` 指向插件目录）。该树由新增的 `tools/build_tool_stubs.py` 从插件自身源码生成（每个模块一个存根，目前 41 个；`--check` 报告漂移），并带上 `stubgen` 默认不写的文档字符串，因此把鼠标停在某个名字上能看到它做什么，而不只是调用形态 —— 文档承诺过、但源码里本来没有文档字符串的四个助手（`register_bot_tool`、`get_plugin_config_perm`、`register_self`、`register_skills`）在源码里补了简短的说明，因为存根只能发布源码里已有的东西 —— 随包放在 `games_ai/ai/_stubs/`；`games_ai/ai/tools_stub_files.py` —— 同时接管了 `tools.py` 骨架的那个模块，入口模块如今是 3579 行（那次搬出后是 3320 行，Python 版本检查与恢复的 `ask_ai` 装饰器又占 11 行） —— 在加载时把它复制出去，且只在文件缺失或与随包存根逐字节不同时才重写（文本模式写入会在 Windows 上翻译行尾，之后就永远比较不相等）。`register_tool` 与 `register_bot_tool` 补上了它们本来就隐含的 `ParamSpec` 注解，否则被装饰的工具在编辑器里会丢掉自己的签名。`tests/test_tool_stubs.py` 同时守护两半：随包存根对源码（每模块一个，公开签名与 `inspect` 逐一比对），以及写入器对用户磁盘（绝不改动已有的 `tools.py`、未变化的存根不重写、LF 行尾、打包安装从归档读取、不可写的目录只记日志而加载继续）。

- **工具注册表 0.8.0 之前的导入路径继续可用**：注册表搬进了 `ai/`，因此 `games_ai/games_ai_tool.py` 现在是一个兼容模块，再导出它的公开名字 —— 同一批对象，所以无论从哪条路径注册，工具都落进插件读取的同一个注册表。既有的 `config/games_ai/tools/tools.py` 以及任何按 `from games_ai.games_ai_tool import register_tool` 写的插件（`register_bot_tool`、`get_plugin_config_perm`、`get_tool_handler`、`TOOL_SCHEMAS`、`ToolHandler`、各内置工具函数……）都无需改动；新代码请用 `games_ai.ai.games_ai_tool`。该模块只为插件之外的代码存在 —— 本包内没有任何模块 import 它，因此它不进入门前的导入链 —— 旧路径的契约由测试锁定：`tests/test_compat_modules.py` 管所有旧路径的共同部分（暴露的集合与真实模块的公开表面完全一致、同一批对象、本包内无人 import 旧路径），`tests/test_tool_compat.py` 再加注册表这一半 —— 一个旧式 `tools.py` 真能加载并注册进同一个注册表。私有名字刻意不再导出，取 handler 的公开途径是 `get_tool_handler`。
- **另外两条 0.8.0 之前的导入路径也恢复了**：热重载文档的 `register_self()` 示例导入的是 `games_ai.register_extra_plugin`，技能文档的 `register_skills()` 示例导入的是 `games_ai.external_skills_loader`；模块搬进 `ai/` 之后，照那些页面写的插件会在自己的 `on_load` 里直接 `ModuleNotFoundError`。现在两条扁平路径都是兼容模块，再导出真实模块的公开名字 —— 同一批对象，所以从旧路径注册自己或注入技能的插件，落进的正是插件读取的那一份重载列表 / 技能列表 —— 而文档继续把新路径作为新代码的写法，并注明旧路径仍然可用。与 `games_ai/games_ai_tool.py` 一样，本包内没有任何模块 import 它们（不进入门前的导入链），且 `tests/test_compat_modules.py` 锁定契约：公开表面完全一致、同一批对象、旧式热重载注册与旧式技能注入都落进共享状态、本包内无人 import 旧路径。

### 📦 依赖自动安装

- **入口模块不需要第三方包就能导入**：检查与修复都在一个纯标准库模块（`games_ai/core/deps.py`）里，只有确认什么都不缺时才导入第三方。一台什么都没装的机器照样能加载插件，`on_load` 此时只做一件事：报出缺失的包、把它们装上，然后请 MCDR 重新加载插件。
- **两次尝试，然后如实汇报**：先用本机 pip 配置执行 `pip install <包名>`（不附加任何 index/代理参数），失败后对仍然缺的包改用阿里云 PyPI 镜像（`https://mirrors.aliyun.com/pypi/simple/`）重试。pip 的每一行输出都带 `[deps]` 前缀写进 MCDR 日志，装得慢也能看见进度。
- **只有真的装好才重载**：包能被 import 之后才调用 `reload_plugin` 重载自己；失败就打出可以直接复制的 `python -m pip install ...` 命令并停下 —— 不重试、不循环，插件保持"已加载但不工作"（无命令、无 bot、无跨服连接）。重载回来的实例会自己确认恢复：`依赖已就绪，插件已恢复正常（...）`。
- **`requirements.txt` 移入包内**：放在插件根目录会让 MCDR 在这段代码运行之前就拒绝加载插件。清单仍然随包分发（`games_ai/requirements.txt`，在源码目录里可以直接用 `pip install -r`）；而通过插件仓库安装现在同样依赖这套自我修复，因为 MCDR 只检查插件根目录的 `requirements.txt`。
- **最后一次尝试有记录**：写在 `config/games_ai/cache/dependency_install.json`（与上下文窗口表同目录），用来防止另一个实例同时开第二份 pip，并让重载后的实例确认已恢复。它不是配置项，也没有任何地方把它当配置读。

### ⚠️ 已知问题

- `!!gamesai reload` 属于 C 类：各实例重载插件时跨服链路本身会断开，随后自动重连；这一瞬间正在回传的输出可能丢失。
- 集群命令的输出不会等待所有实例回齐，先到的先显示。

### 升级提示

- 配置无需手动改动：旧的 `mineflayer_bot.websocket` 键会自动迁移，顶层 `websocket` 块由 MCDR 补齐。token 按节点各自签发（不再有共享口令），两台实例互联前请先读 [跨服连接](cross-server.md)。
- **实例名**：`websocket.name` 留空时按实例目录派生（`<目录名>-<路径哈希前 6 位>`）；想固定集群里的名字就显式设置它。
- 端口只需在 hub 那台开放。token 明文传输（hub 只存 `sha256` 哈希）；**插件本身只监听明文 `ws://`**，跨公网要让隧道/反向代理提供 TLS（客户端把 `uri` 指向代理的 `wss://` 即可，`wss://` 只能当客户端用）。
- **Python 3.12 或更高**：代码使用了 PEP 701 的 f-string（在 f-string 表达式里嵌套同种引号的字符串，例如 `f"{server.rtr("games_ai...")}"`），这只有 3.12+ 的解析器接受。这一点对代码来说一直如此；现在 README、测试文档与入口模块顶部的检查都写 3.12（原来写的是 3.11）。模块内部无法给出更友好的提示：解释器若解析不了这个文件，里面一行代码都不会执行。

## Version 0.7.3

### 🎯 核心亮点

- **🧱 system 只剩一条** — prompt 与技能列表合并为一条 system 消息,当前时间从中移出。部分上游(Qwen3.5/3.6/3.8 的 chat template 等)只允许下标 0 是 system,此前会直接返回 `System message must be at the beginning`,这些模型完全不可用。
- **⏱️ 当前时间改由 `user` 消息承载** — 写在提问正前方:第 1 轮注入,之后每 20 轮再注入一次。它写入历史,因此相邻两轮之间的提示词前缀完全一致,服务商的前缀缓存可以持续命中(此前时间在 system 首行、每轮都变,等于每轮把整段历史重新计费一次)。
- **🗄️ 公共数据改用 `assistant`** — 它是资料而不是命令;公共数据库为空时这条消息完全不发送。
- **🧩 连续的 `user` 消息在发出前合并成一条** — 时间 + 提问、技能提示 + 提问、`!!ask -f` 的多条补充、上一轮失败后的重问都会合并。

### 1. 请求里的消息结构

| 顺序 | role | 内容 |
|---|---|---|
| 1 | `system` | 该模型的 prompt + 技能列表(**只有一条**) |
| 2 | `assistant` | 公共数据列表(数据库为空时不发送) |
| 3… | 任意 | 对话历史(提问正前方是一条 `user` 角色的时间消息) |
| 末 | `user` | 本轮提问 |

- **技能提示改角色** — `!!ask /技能.md` 注入的"先读这个技能"提示由 `system` 改为 `user`;
- **无历史路径保持一致** — `!!ask -n` 同样是单条 system + 有数据时的 `assistant` + 合并后的一条 `user`;
- **`response_ai(data=None)` 受支持** — 公共数据库没有任何记录时不注入任何 data 消息(此前会发一条空的"公共数据列表:")。

### 2. 轮次切分与缓存

- 连在一起的 `user` 消息现在算**同一个回合**:否则每一条注入的时间都会被算成独立一轮,`KEEP_ROUNDS = 10` 实际只剩 5 轮对话,压缩边界也会把一回合的时间与问题切开;
- 时间注入的计数在 `!!ask switch` 清空历史时归零(`!!gamesai clear` 直接销毁对象),**压缩不归零** —— 压缩视为同一段对话的延续;
- 合并只作用于**发出的请求**,历史里仍分别保存,因此 `!!ask context` 的统计与本地估算口径不受影响。

### 3. 修复

- **清理残留 Node 进程的两处调用** — `run_node()`(启动前清理)与"检测到不支持的服务器版本 → 重装依赖并重启假人"路径上的 `_kill_mineflayer_process()` 都补上了缺失的进程参数,此前会抛 `TypeError` 并被 `try/except` 吞掉,只留下一条日志;
- **调试日志字段更名** — `!!gamesai debug` 的请求头部由 `system=` 改为 `preamble=`(该位置现在也可能包含一条 assistant 消息)。

### 4. 文档

- 三语技术文档新增「请求里的消息结构」一节,并同步更新请求链路、`!!ask -n` 一致性条目与"每玩家状态"里的 `system_message` 说明。

### ⚠️ 已知问题

- 历史压缩摘要与切模型转接摘要**仍以 `system` 消息注入**(本次未改动),因此在只允许一条 system 的上游上,这两条路径仍可能被拒绝。

### 升级提示

- **配置无需改动**;
- 升级后第一次请求会重建提示词前缀,旧的前缀缓存会失效一次,之后恢复正常。

## Version 0.7.2

### 🎯 核心亮点

- **🔍 上下文查看** — 两条只读指令与一次按需压缩把上下文管理从"看不见"变成"看得见"：`!!ask context` 查看某个对话的窗口占用、距离压缩还有多少余量、逐轮规模与缓存命中；`!!ask context --all` 按模型汇总全服所有玩家的用量；`!!ask compact` 安排一次对较早历史的压缩，在你下次提问时执行。两条只读指令读取同一份一致的快照，所以轮次运行中查看是安全的。
- **🔧 `!!ask` 改为命令分发器** — 旧的 8 条独立命令节点合并为 `!!ask` + `!!ask <content>`，子指令改由分发器解析。这是为了修掉一个真实缺陷：`!!ask stop it.` 这类"想对 AI 说的话"会因为 `stop` 是独立命令节点而被 MCDR 判为**未知参数并整条丢弃**（`!!ask switch it.` 则会把 `it.` 当模型名）。现在任何一句话都会落到 AI，除非它恰好就是那个子指令。
- **🧹 卸载与热重载不再被假人拖住** — 停 Node 进程从"逐级升级、最多串行等 21 秒"改为一次终止 + 有限等待（实测 **5 毫秒**）；卸载时把停机搬到独立线程，`on_unload` 只等 1.5 秒；`!!gamesai reload` 增加单飞锁，避免两次重载互相把对方的停机当成"端口被外来程序占用"从而**把假人功能整个关掉**。
- **🧵 线程可观测** — 新增 `!!gamesai debug thread`，列出插件持有的所有线程及其 id；卸载时如实报告仍然存活的线程，残留的旧控制器线程会在下次加载时被强制中止，而不是与新实例并存。

### 1. 上下文查看：`!!ask context`

`!!ask context [玩家]`（不填玩家即查看自己，任何玩家可查任意玩家）：

- **正文**是几行摘要：模型与窗口来源（配置覆盖 / 模型表 / 默认值）、上下文占用及占窗口比例、窗口与输出上限、距离压缩触发还有多少 token、轮次与消息数；
- **悬停**放不进正文的细节：三条压缩触发线（历史 80% / 突发 20% / 紧急 95%）、逐轮 token 规模与占窗口比例、上次请求的输入/输出/缓存命中/推理用量与本轮累计、最近一次压缩的时间与前后消息数。

数字来自 `ChatParam.context_snapshot()`，**在同一把锁下读取**：轮次线程会追加消息、压缩时会整个替换历史列表，没有这把锁就可能读到写了一半的历史。为此 `_split_rounds` / `_drop_oldest_round` / `_truncate_long_messages` / `_compress_old_rounds` 全部改为"公有方法加锁 → 内部逻辑"的双层写法（可重入锁，因为压缩内部还会再切分轮次）。

### 2. 全服汇总：`!!ask context --all`

- 按**模型**汇总，每个模型一行：人数、当前上下文占用合计与占窗口比例、本轮输入合计、本轮峰值合计；
- 悬停显示该模型**自这些对话创建以来**的累计：输入、输出、合计、缓存命中（0.1% 精度，截断而非四舍五入）、推理 token；它们随对话一起保存，因此重载或重启不会清零；
- **零用量不列出**：没人持有上下文、也没有任何消耗的模型不会出现在列表里；
- 不显示玩家名，也不设权限限制。

为了让"压缩后仍能看到压缩前的用量"成立，`ChatParam` 新增了四个**永不重置**的累计计数器（`_total_prompt/completion/cached/reasoning_tokens`）：原来只有每轮计数（每轮清零）和最近一次计数（每次请求覆盖），压缩一次就把账抹掉了。**注意：从 0.8.0 起这些累计随对话一起保存、加载时还原，因此重载或重启都会保留；只有 0.7.2 之前（那时计数器还不存在）的调用无法追溯。**

### 3. 手动压缩：`!!ask compact`

- 忽略窗口触发线，直接压缩较早的对话：最新的 10 轮原样保留，历史不超过这 10 轮时回报"没有可压缩的历史"；
- 与模型切换的摘要转接一样**延迟执行**：指令本身不等待总结请求（最长 60 秒），由你下次提问的预检完成，所以命令立即返回、不阻塞服务器线程；
- 结果分三种如实回报：已安排 / 没有可压缩的历史 / 有轮次正在进行（需等它结束或先 `!!ask stop`）。

### 4. `!!ask` 命令分发器

- 注册节点从 8 条减为 2 条（`!!ask`、`!!ask <content>`），子指令在 `ask_ai_dispatcher` 中按**词**精确匹配，长逻辑一律在独立函数里；
- 修复的真实缺陷：`!!ask stop it.` 以前会报 `Unknown Argument` 并**什么都不执行**；`!!ask switch it.` 会回复"模型不存在"；
- 关键词规则：`switch` / `stop` 必须**恰好是那个词**才当子指令，带任何多余文本一律视为对 AI 的提问；`-n` / `--no-history` / `-f` / `--forced` 作为前缀旗标，后接内容；
- 连带修好：`!!ask -n`（缺内容）以前直接报 `Unknown Command`，现在作为普通提问；`!!ask contextual` 之类的词不再被 `context` 前缀吞掉。

### 5. 卸载、重载与假人停机

- **Node 停机**：由"`terminate` → 等 3 秒 → `kill` → 等 3 秒 → Windows `taskkill /T /F` → 等 10 秒 → 再等 5 秒"改为一次 `terminate` + 2 秒等待，超时后按平台追加一次强制手段，实测 **5 毫秒**完成；进程句柄先与模块状态**解绑**再终止，因此下一个实例看到的是干净状态；
- **异步卸载**：`on_unload` 只同步等待 1.5 秒，剩余停机交给 `games_ai@bot_teardown` 后台线程；该线程只使用 `threading`/`subprocess`/`socket` 与**作为参数绑定**的日志器，不读模块全局、不碰 MCDR 对象（插件此时已卸载）；
- **重载单飞**：`!!gamesai reload` 加非阻塞锁，重入时直接回"已有一次重载正在进行"；两次重载并发时后者的端口探测会把前者未退出的 Node 当成外来程序，进而把 `mineflayer_bot.enabled` 写成 `false` 并再触发一次重载——这条破坏路径已封死；
- **端口探测**改为先等待正在进行的停机完成（最多 5 秒），不再误判；
- **首次连接退避**：WebSocket 客户端在首次连上之前使用短间隔（新配置项 `mineflayer_bot.websocket.first_connect_interval`，默认 `0.5` 秒），不再因为 Node 还在启动就白等一整个 `reconnect_interval`（默认 10 秒）；连上之后仍用配置的间隔（该配置项已在 0.8.0 连同整个 `mineflayer_bot.websocket` 块一起移除）。

### 6. 自治 Bot 控制器

- **协作停止优先**：新增 `_stop_event` 打断周期间的等待，空闲控制器立即结束，不必再等满一个 `cycle_interval`；
- **强制中止**：协作停止超时后，`force_abort_thread` 通过 `PyThreadState_SetAsyncExc` 向控制器线程注入 `_ControllerAbort`（继承 `BaseException`，不会被循环内的 `except Exception` 吞掉）。它**无法打断阻塞中的 C 调用**（socket 读 / HTTP 请求），但会在该调用返回的瞬间生效；命中多个线程时会回滚；
- **AI 请求超时**：控制器新增 `ai_timeout`（默认 120 秒），避免一个卡住的请求按 SDK 默认值挂住十分钟；
- **残留线程治理**：卸载后仍存活的旧控制器线程会在**下一次加载**时被中止（含旧版本的 `AutonomousBotAI` 线程名），并安装线程异常钩子把注入的中止记录成一行日志而不是一整段 traceback。

### 7. 其他改进与修复

- 新增 `!!gamesai debug thread` 与 `games_ai.debug.threads_header` 文案：列出插件持有的线程（`#id`、名称、daemon、`native=`、`(current)`），每次最多 12 条；
- 全部线程统一命名为 `games_ai@...`（`games_ai@autonomous_bot`、`games_ai@ws_client`、`games_ai@update_loop`、`games_ai@update_timer`、`games_ai@data_*`、`games_ai@bot_teardown` 等），旧名 `AutonomousBotAI` / `MineflayerBotLog` 仍被识别；
- **修复 `mineflayer_bot.enabled` 被误关闭**：写 `config.json` 前先确保目录存在，不再依赖调用者的工作目录；
- `stop_mineflayer_bot` 补充 `@register_bot_tool()` 标记，自治 Bot 现在能真正调用它；
- 卸载与热重载共用 `_stop_bot_stack()`，每一步独立容错：某一步失败不会再连带把 WebSocket 客户端与 Node 进程留在原地；
- `response_chat` 的 `response_list` 补上类型注解；
- 文档重构：三语 README 只保留简介 / 安装 / 使用 / 指令总览 / 技术文档链接等入口，技术细节移入 `docs/<语言>/` 下的**九个**文件（AI 请求链路、Mineflayer Bot、配置、工具、技能、范例、热重载、故障排查、更新日志），并随插件一起打包。原有「工具与 Skills」一页已拆分为独立的工具与技能两页并按当前实现重写（补齐权限与 Bot 可见性两列、修正与代码不符的参数说明），另新增一页真实服务器范例。

## Version 0.7.1

### 🎯 核心亮点

- **🧮 上下文自动管理** — 固定的 `max_history` 配置已移除。插件会自动解析各模型的上下文窗口、从服务商返回的 `usage` 获取真实用量，并且只在上下文确实过大时才压缩对话。
- **🔀 `!!ask switch` 的摘要转接** — [#20](https://github.com/PengZixuan30/Games_AI/issues/20) 社区投票选出**方案 B1**：切换时立即清空原历史，由**旧模型**在你下次提问前把它压缩成一段中性事实摘要（与自动上下文压缩同一时机）—— 切换不再阻塞，新模型拿到事实而不沾旧风格。
- **🛑 `!!ask stop`** — 一次停止你名下所有正在进行的内容：运行中的对话轮（含工具调用）、正在进行的 `!!ask -n` 提问、以及委派给 Bot 的任务。未完成的一步会从历史中删除，不会留下写了一半的对话。（0.8.0 已改变这一行为：该轮会保留它已经写下的内容，详见上文 0.8.0 的说明）
- **🪶 无状态的 `!!ask -n`** — 单次提问不再创建（然后丢弃）一个完整的对话对象：`NonHistoryChatParam` 不保留历史、队列与上下文记账，并按端点复用同一个 HTTP 客户端。
- **📊 请求用量感知** — `response_chat` 现在会返回服务商的 `usage`，插件因此能掌握每次请求的真实输入量，并按 `base_url|model` 校准本地估算。
- **🧩 新增 `context_window` 选项** — `all_ai` 中每个 AI 可选填写的窗口覆盖值，对于窗口极大的模型可作为成本控制开关。

### 1. 上下文自动管理

每次请求都会与模型自身的上下文窗口比对，只有确实需要时才压缩对话。完整说明见[上下文自动管理](ai-request-pipeline.md#上下文自动管理)。

- **窗口来源**：单模型 `context_window` → 远程表 [`data/context_windows.json`](https://github.com/PengZixuan30/Games_AI/blob/main/data/context_windows.json)（GitHub Raw，jsDelivr 备用，缓存 24 小时）→ 版本内置表 → 保守默认值（`32768`）。
- **触发条件**（每次请求**前后**都会检查）：当前上下文达到窗口 **80%**，或单次请求达到窗口 **20%** —— 后者用于捕捉"一次读取大日志"这类突发增长。
- **压缩方式**：最近 **10 轮**始终原样保留；更早的轮次替换为一条中性事实摘要（由当前模型生成，不带工具）。若仍不足，则截断超长消息并丢弃最旧轮次，保证下一次请求一定能装下。
- **校准**：本地 token 估算会按 `base_url|model` 与真实 `usage` 对齐，几轮内收敛。

### 2. 切换模型时的摘要转接

`!!ask switch <model>` 现在实现 [#20](https://github.com/PengZixuan30/Games_AI/issues/20) 投票选出的**方案 B1**（投票已结束）：

- 摘要请求被**延后**，与自动上下文压缩完全一致：指令只负责清空历史并保存快照，由**旧模型**在你**下次请求之前**写出中性事实摘要（讨论主题、已确认结论、未完成事项、用户明确要求 —— 不带工具、60 秒超时）。因此切换会立即返回，不再被摘要请求阻塞；
- 原历史在切换时即被清空，旧模型的回复不再影响新模型的语气与人设；
- 摘要作为新会话的第一条 system 消息注入，并附带"请以自己的设定与风格继续"的提示；
- 延后的摘要失败时本轮仍会正常回答，并告知玩家上一段对话已被丢弃；
- 切换到当前已在使用的模型不会改动任何东西；没有历史时也不会多发请求；
- 切换前会等待运行中的轮次结束，并重置工具计数、强制请求队列与用量计数。

详见[切换模型时的摘要转接](ai-request-pipeline.md#切换模型时的摘要转接)。

### 3. `!!ask -n` 的无状态路径

单次提问过去会创建一个完整的 `ChatParam`（历史、队列、生命周期事件、校准状态、上下文管理），回答完就丢弃。现在改由 `NonHistoryChatParam` 处理 —— 一个自包含、什么都不保留的类：

- **不保留任何状态** —— 整轮只活在 `response_ai` 内部，返回即释放；不会注册进 `all_chat_param`，没有历史、队列、`is_stopped` 事件与工具计数；
- **不做上下文管理** —— 不做 token 估算、不做用量校准、不压缩历史，因此也不会产生额外的摘要请求；
- **回答完全一致** —— 与常规路径相同的 system 消息、相同的按权限过滤工具、相同的回复格式与错误上报；工具调用同样在同一轮内执行并回注；
- **单轮超窗保险** —— 若整个请求超过模型窗口的 80%，则把最新一条消息截断到剩余空间（有历史的路径仍然使用完整的上下文管理）；
- **共享 HTTP 客户端** —— 客户端按 `base_url` + API Key 缓存，连续 `-n` 不必每次都重建连接池并重做 TLS 握手。

细节见[无历史路径](ai-request-pipeline.md#无历史路径ask--n)。

### 4. 配置与行为变更

- **`max_history` 已移除** —— 旧配置文件仍可正常使用，该键会被直接忽略。
- **新增 `context_window`**（可选，位于每个 AI 条目内）—— 见 [3.all_ai](configuration.md#3all_ai)。
- **新增远程表** —— `data/context_windows.json` 在本仓库维护（**249 条**，覆盖 19 家厂商与各托管平台，核验日期 683-09-11；来源与口径见 [`data/context_windows.sources.md`](https://github.com/PengZixuan30/Games_AI/blob/main/data/context_windows.sources.md)）。插件在启动时与 24 小时更新检查时获取，并缓存到 `config/games_ai/cache/context_windows.json`；`!!gamesai check` 会无视 24 小时 TTL 强制刷新。维护者可编辑该 JSON 后执行 `python tools/build_context_table.py` 重新同步内置表并校验。
- **刷新链路合并为一条** —— 窗口表刷新与启动 / 24 小时更新检查共用同一条线程，不再单独再起一个线程；并发刷新也不会重复下载两次表。

### 5. 其他改进

- `response_chat` 新增单次请求 `timeout`，并返回 `(message, usage)`；
- 新增 `context_table` 模块：表匹配、校验、缓存与静默离线兜底；版本内置表改放在生成式模块 `games_ai/ai/context_table_data.py`（每条一行），不再内联在逻辑模块里；
- **内置工具的文本已全部英文化** —— 26 个内置工具的 `description` 与参数说明，**以及回传给模型的工具返回值**（执行结果、错误与权限提示）均为英文，函数调用提示词不再混用中英；只有发给玩家的提示仍保持本地化；
- **`modify_skills` 与 `modify_custom_tools` 改为编辑而非整体重写** —— 两者都接收 `old_string`（Python 正则）与 `new_string`（支持 `\1` 等反向引用），替换所有匹配而不是覆写整个文件。正则无法编译或匹配不到时退回字面文本替换；完全匹配不到则不写入任何内容并明确告知模型。`modify_skills` 仍保留可选参数 `summary`，用于同步技能索引；
- `!!gamesai debug` 会输出窗口、用量、校准系数与每一次压缩过程；
- **新增 `!!ask stop` 指令** —— 在下一个检查点中止该玩家运行中的对话轮（进行中的请求无法真正中断），从历史中删除未完成的一步，丢弃 `!!ask -f` 排队消息，同时也会停止正在进行的 `!!ask -n` 提问与委派给自治 Bot 的任务（0.8.0 已改变这两点：被中断的轮次会保留它的历史，排队的 `!!ask -f` 消息也会被保留并由下一轮合并）。详见[停止正在进行的对话](ai-request-pipeline.md#停止正在进行的对话)；
- 未映射的 HTTP 错误码兜底文案改为翻译键（`games_ai.error_code_map.error_unknown`），与其它错误码一样跟随玩家语言；
- `custom_tools_management` 技能新增强制的"Step 0"：AI 必须**在编写任何工具代码之前**先向用户确认需求、参数、权限等级与期望返回值，并对有风险或不可逆的行为再次确认。

## Version 0.7.0

### 🎯 核心亮点

- **🧠 每玩家 ChatParam 架构** — 每个玩家的对话现在由一个专属 `ChatParam` 对象管理:它拥有对话历史、系统消息、强制请求队列与轮次生命周期事件。历史处理、模型切换、强制提问都经由该对象。
- **🔀 模型切换:`!!ask switch <model>`** — 随时切换当前对话使用的 AI 模型。0.7.0 暂时**完全保留历史**;处理策略已由 [#20](https://github.com/PengZixuan30/Games_AI/issues/20) 社区投票决定(方案 B1,摘要转接),并在 0.7.1 实现。
- **⚡ 强制提问:`!!ask -f <content>`** — 在轮次仍在运行时插入问题:消息会被合并进运行中的轮次(或由自动补轮回答),无需等待上一个回复结束。
- **🗑️ 移除的命令** — `!!ask -m <model> <content>`、`!!ask --model ...` 及其 `-n` / `--no-history` 组合已被移除;请改用 `!!ask switch <model>` + `!!ask -n <content>`。
- **📋 调试日志** — `!!gamesai debug` 现在可以让完整的 AI 请求流程在 MCDR 控制台可见(模型切换、强制请求入队/合并、轮次生命周期、工具调用)。

### 1. ChatParam:每玩家一个对话对象

`games_ai/ai/chat_param.py` 引入 `BasicChatParam` / `ChatParam`:

- `response_list` — 该玩家的对话历史;
- `system_message` — 每轮重建(当前时间、prompt、技能列表、公共数据);
- `response_queue` — 等待合并的 `!!ask -f` 消息;
- `is_stopped` — 轮次生命周期事件,用于串行化每个玩家的轮次;
- `trim_response_list()` — 有界历史(`max_history × 2 + tool_count × 2`,已在 0.7.1 由上下文自动管理取代);
- `reload_ai_info()` — `!!gamesai reload` 后刷新 AI 配置与客户端。

所有玩家对象保存在 `all_chat_param` 中;`!!gamesai clear` / `!!gamesai clearall` 会删除它们。

### 2. 完整请求链路

`!!ask <content>` → `ask_ai` 构建用户消息 → 玩家的 `ChatParam` → `response_ai` 组装请求(system 消息 + 历史 + 按权限过滤的工具)→ 经复用的客户端(`openai_api.response_chat`)访问 OpenAI 兼容 API → 回复发送给玩家;工具调用被执行并回填,直到 AI 给出最终文本回复。详见[AI 请求链路与对话机制](ai-request-pipeline.md#ai-请求链路与对话机制)。

### 3. 其他改进与修复

- `!!ask switch <model>` 现在附带本地化确认消息,并就地更新对话(0.7.0 保留历史);
- `response_chat` 改为注入 `OpenAI` 客户端(每个 AI 配置一个)并附带类型检查;Mineflayer 自主控制器已适配新签名;
- `!!gamesai reload` 会刷新现有 `ChatParam` 对象(重建客户端),并在热重载路径中刷新 `AutonomousBotController` 配置;
- 强制请求流程有了完整的调试日志(入队、合并、补轮)。
