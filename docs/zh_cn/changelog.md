<div align="center">

# 本次更新

[English](../en_us/changelog.md)  |  简体中文  |  [繁體中文](../zh_tw/changelog.md)

[返回 README](../../README.zh-CN.md)

</div>

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
- 时间注入的计数在 `!!ask switch` 清空历史时归零(`!!ask clear` 直接销毁对象),**压缩不归零** —— 压缩视为同一段对话的延续;
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

- **🔍 上下文查看** — 三条只读指令把上下文管理从"看不见"变成"看得见"：`!!ask context` 查看某个对话的窗口占用、距离压缩还有多少余量、逐轮规模与缓存命中；`!!ask context --all` 按模型汇总全服所有玩家的用量；`!!ask compact` 立即压缩较早的历史。三者共用同一套快照读取，边跑边看不影响正在进行的轮次。
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
- 悬停显示该模型**自插件加载以来**的累计：输入、输出、合计、缓存命中（0.1% 精度，截断而非四舍五入）、推理 token；
- **零用量不列出**：没人持有上下文、也没有任何消耗的模型不会出现在列表里；
- 不显示玩家名，也不设权限限制。

为了让"压缩后仍能看到压缩前的用量"成立，`ChatParam` 新增了四个**永不重置**的累计计数器（`_total_prompt/completion/cached/reasoning_tokens`）：原来只有每轮计数（每轮清零）和最近一次计数（每次请求覆盖），压缩一次就把账抹掉了。**注意：这些累计从本次插件加载开始记，之前的调用无法追溯。**

### 3. 手动压缩：`!!ask compact`

- 忽略窗口触发线与"轮次不超过 10 轮就跳过"的提前返回，把较早的对话立即压缩为摘要；
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
- **首次连接退避**：WebSocket 客户端在首次连上之前使用短间隔（新配置项 `mineflayer_bot.websocket.first_connect_interval`，默认 `0.5` 秒），不再因为 Node 还在启动就白等一整个 `reconnect_interval`（默认 10 秒）；连上之后仍用配置的间隔。

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
- **🛑 `!!ask stop`** — 一次停止你名下所有正在进行的内容：运行中的对话轮（含工具调用）、正在进行的 `!!ask -n` 提问、以及委派给 Bot 的任务。未完成的一步会从历史中删除，不会留下写了一半的对话。
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
- **新增远程表** —— `data/context_windows.json` 在本仓库维护（**249 条**，覆盖 19 家厂商与各托管平台，核验日期 2026-09-11；来源与口径见 [`data/context_windows.sources.md`](https://github.com/PengZixuan30/Games_AI/blob/main/data/context_windows.sources.md)）。插件在启动时与 24 小时更新检查时获取，并缓存到 `config/games_ai/cache/context_windows.json`；`!!gamesai check` 会无视 24 小时 TTL 强制刷新。维护者可编辑该 JSON 后执行 `python tools/build_context_table.py` 重新同步内置表并校验。
- **刷新链路合并为一条** —— 窗口表刷新与启动 / 24 小时更新检查共用同一条线程，不再单独再起一个线程；并发刷新也不会重复下载两次表。

### 5. 其他改进

- `response_chat` 新增单次请求 `timeout`，并返回 `(message, usage)`；
- 新增 `context_table` 模块：表匹配、校验、缓存与静默离线兜底；版本内置表改放在生成式模块 `games_ai/context_table_data.py`（每条一行），不再内联在逻辑模块里；
- **内置工具的文本已全部英文化** —— 26 个内置工具的 `description` 与参数说明，**以及回传给模型的工具返回值**（执行结果、错误与权限提示）均为英文，函数调用提示词不再混用中英；只有发给玩家的提示仍保持本地化；
- **`modify_skills` 与 `modify_custom_tools` 改为编辑而非整体重写** —— 两者都接收 `old_string`（Python 正则）与 `new_string`（支持 `\1` 等反向引用），替换所有匹配而不是覆写整个文件。正则无法编译或匹配不到时退回字面文本替换；完全匹配不到则不写入任何内容并明确告知模型。`modify_skills` 仍保留可选参数 `summary`，用于同步技能索引；
- `!!gamesai debug` 会输出窗口、用量、校准系数与每一次压缩过程；
- **新增 `!!ask stop` 指令** —— 在下一个检查点中止该玩家运行中的对话轮（进行中的请求无法真正中断），从历史中删除未完成的一步，丢弃 `!!ask -f` 排队消息，同时也会停止正在进行的 `!!ask -n` 提问与委派给自治 Bot 的任务。详见[停止正在进行的对话](ai-request-pipeline.md#停止正在进行的对话)；
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

`games_ai/chat_param.py` 引入 `BasicChatParam` / `ChatParam`:

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
