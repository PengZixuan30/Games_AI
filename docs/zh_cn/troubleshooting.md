<div align="center">

# 故障排查

[English](../en_us/troubleshooting.md)  |  简体中文  |  [繁體中文](../zh_tw/troubleshooting.md)

[返回 README](../../README.zh-CN.md)

</div>

## 缺少 Python 依赖包

插件需要 `openai`、`requests`、`websockets`。它不要求你先装好：启动时发现缺包会在日志里说明（`缺少 Python 依赖包：...`），自动用 pip 补装并重载自己。

- **两次尝试**：第一次用本机 pip 配置执行 `pip install <包名>`（不附加任何 index/代理参数，因此 pip.ini、`PIP_INDEX_URL` 与代理照常生效）；失败后第二次改用阿里云 PyPI 镜像（`https://mirrors.aliyun.com/pypi/simple/`）重试，日志里会有一行说明，并且只请求仍然缺的包。
- **pip 的每一行输出都写进日志**，前缀 `[deps]`，装得慢也不会看着像卡死。只有包真的能 import 之后插件才重载自己，重载后的实例会打一条 `依赖已就绪，插件已恢复正常（...）`。
- **两次都失败**时日志会打出 `依赖安装失败：...` 和可以直接复制的命令（`python -m pip install openai requests websockets`）：

```bash
python -m pip install openai requests websockets
```

然后执行 `!!MCDR plugin reload games_ai`。在此之前插件处于"已加载但不工作"的状态：不注册命令、不启动 bot 与跨服连接。
- 包清单在插件内的 `games_ai/requirements.txt`。它**故意不放在插件根目录**：MCDR 会在导入插件前检查根目录的 `requirements.txt`，缺包就直接拒绝加载 —— 那样插件就永远没有机会自我修复。
- 通过插件仓库安装（`!!MCDR plugin install games_ai`）不再会预先装好这些依赖：MCDR 只读取插件根目录的 `requirements.txt`，而清单现在位于包内，因此仓库安装与其它启动方式一样，走同一套自我修复。
- 如果 pip 没有解释器 `site-packages` 的写权限（Python 装在 `Program Files`、以服务账户运行等），安装会以 pip 自己的报错失败；请用 MCDR 所运行的用户安装，或在 `--user` 目录位于该解释器 `sys.path` 上时加 `--user`。

## `!!ask` 错误

|症状|可能原因|解决方法|
|---|---|---|
|HTTP 400|请求体格式错误|检查 `extra_body` 格式是否与 API 提供商的要求一致。|
|HTTP 401|API Key 无效|检查 AI 配置中的 `api_key`。|
|HTTP 404|模型不存在|检查 `ai_model` 名称是否正确。|
|HTTP 429|请求频率过高|稍后重试，或升级 API 套餐。|
|超时/无响应|网络问题或 API 响应慢|使用 `!!gamesai speedtest` 检查延迟。尝试更换模型。|
|「未知函数」回复|AI 调用了不存在的工具|通常无害——AI 会重试其他方法。|

> 失败请求的日志行现在是 WARNING，含状态码、含义与服务商的 Request ID（不必先开 `!!gamesai debug`）。回复里，只要失败不是密钥错误或限流，含义就紧跟在状态码之后（例如 `HTTP 402 (API Key 余额不足)`）；401 与 429 各有自己的句子，已经点明了原因。

## Mineflayer Bot 错误

|症状|相关日志|解决方法|
|---|---|---|
|Bot 未启动（完全没有 `[Mineflayer]` 日志）|`Mineflayer bot is enabled but Node.js was not found`|安装 Node.js >= 18。运行 `node --version` 验证。|
|Bot 在启动时被禁用|`Mineflayer requires Node.js >= 18, but found v{X}`|将 Node.js 升级到 18 或更高版本。|
|Bot 启动后一直不上线|日志里没有 `Registered on hub`|确认 `websocket.uri` 指向的 hub 正在运行；Bot 拨号的是插件写进它自己配置里的地址，hub 没起来时按该文件中的 `reconnect_interval`（默认 10 秒）重试。详见[跨服连接](cross-server.md)。|
|`[Bot] Kicked from server` 伴随认证原因|`[Bot] Kicked from server. Reason:` 后跟认证错误|通过 `!!aibot set` 检查 `username`/`password`/`auth`。Microsoft 认证需确保账号已迁移。|
|Bot 卡住不动|`goto` 操作返回 "No path found" 错误|`goto` 操作现在会在无路径时返回错误。尝试不同的坐标。|
|`[Bot] Disconnected` 后自动重连|`[Bot] Disconnected. Reason: ...` 后跟 `Reconnecting in 5 seconds...`|服务器重启或短暂断网后的正常行为。Bot 会在 5 秒后自动重连。|
|`[Bot] Died, respawning...`|`[Bot] Died, respawning...`|正常——Bot 死亡后会自动重生，无需干预。|
|Bot 不响应指令|日志中无 `[WS]` 活动|使用 `!!aibot leave` 然后 `!!aibot join` 重启。若持续存在，检查顶层 `websocket.uri`（`config/games_ai/config.json`）中的地址在 Bot 所在机器上是否可达。|
|日志中出现 `npm install failed`|`npm install failed (exit {X})` 或 `npm is not installed or not in PATH`|确保 npm 已安装且在 PATH 中。检查日志中的详细错误信息定位具体包问题。|
|`Server version '{X}' is not supported`|`[Bot] Error: Server version ... is not supported. Latest supported version is ...`|Minecraft 服务器升级到了已安装 mineflayer 不支持的版本。插件会自动检测到该错误，更新 npm 依赖并重启 Bot。若错误持续存在，请检查服务器能否访问 npm 源，或在 `config/games_ai/mineflayer/` 下手动执行 `npm install --no-save mineflayer ws vec3 mineflayer-pathfinder mineflayer-mcefly`，然后通过 `!!aibot leave` / `!!aibot join` 重启 Bot。|

## 日志与调试

- **`!!gamesai debug`** — 开关调试模式。开启后完整的 AI 请求流程会以 INFO 级别显示在 MCDR 控制台（完整提示词、请求开始/结束、`!!ask -f` 入队与合并、轮次生命周期、工具调用与结果、上下文窗口/用量/校准系数以及每一次压缩过程）；关闭后同一批日志退回 DEBUG 级别。
- **`!!gamesai debug thread`** — 列出 GamesAI 当前持有的线程及其 id，用来确认卸载或热重载后有没有留下残留线程：
  - 每行格式为 `#<Python 线程 id>  <线程名>  [daemon|non-daemon]  native=<操作系统线程 id>`，正在执行该命令的线程会标记 `(current)`；
  - `#id` 是 Python 内部的线程标识（强制中止针对的就是它），`native=` 是操作系统层面的线程 id；
  - 只列出 GamesAI 自己的线程（`games_ai@...`，也包括旧版本遗留的 `AutonomousBotAI` / `MineflayerBotLog` 名字）：卸载或 `!!MCDR plugin reload games_ai` 之后仍出现在列表里的，就是上一实例遗留的线程。下一次加载插件时会自动中止残留的 **bot 控制线程**（`games_ai@autonomous_bot`，或旧版本的 `AutonomousBotAI`），若它正卡在阻塞调用中，则要等该调用返回后才退出；其它残留只会上报 —— 如果某个残留一直不消失，就重启 MCDR；
  - 一次最多列出 12 条，其余以 `... +N` 汇总。
- Mineflayer Bot 日志在 MCDR 控制台以 `[Mineflayer]` 前缀显示。
- **上下文相关的排查**（不需要开启 `!!gamesai debug`：`!!ask context` 与 `!!ask context --all` 是只读的、随时可执行，而 `!!ask compact` 只是登记一次压缩，由你下次提问前的预检执行）：
  - **`!!ask context [玩家]`** — 先看这个。窗口是多大、来源是哪一层（配置覆盖 / 模型表 / 默认值）、上下文占了多少、距离压缩还有多少余量、逐轮规模里有没有某一轮异常膨胀。悬停还能看到上次请求的缓存命中与推理用量；
  - **`!!ask context --all`** — 全服按配置的 AI 条目汇总(行名是该条目的 `ai_name`,悬停显示 `all_ai` id 与上游 `ai_model`),用来判断"是不是所有人都在同一个助手/模型上堆上下文"。悬停里的**自其对话建立以来累计**不会因为压缩而减少(重启后仍然累计)，所以它是核对真实消耗的地方；"当前占用"在压缩或 `!!gamesai clear` 之后会掉下来，别把它当累计值；
  - **`!!ask compact`** — 手动压缩。远未到 80% 触发线但你想立刻瘦身时用它；它是**延迟执行**的（由你下次提问的预检发出总结请求），所以看到"已安排"而不是"已完成"是正常的。历史在 10 轮以内时没有可压缩的内容，会直接回"当前没有可压缩的历史记录。"若回复"有对话正在进行"，说明有轮次在跑，等它结束或先 `!!ask stop`。
- 关于"假人上下线很慢"：正常路径下停机是**一次终止 + 有限等待**（毫秒级），启动慢主要来自 Node 启动与 Minecraft 登录本身。若在 `!!gamesai reload` 或卸载后看到 `bot_teardown` 线程仍在后台收尾，那属于预期行为（最多再等几秒）；若 Bot 一直不上线，检查 `websocket.uri` 指向的 hub 是否可达 —— Bot 不再自己占用端口。
- **OpenAI 日志桥接**：插件加载时会把 `openai` 日志器以及已安装 SDK 依赖的每一个 HTTP 日志器（`httpx`/`httpx2`、`httpcore`/`httpcore2`，以及从 SDK 元数据推导出的名字）桥接进 MCDR 日志系统（固定 INFO 级别，与 `!!gamesai debug` 无关），因此 SDK 的 HTTP 请求、响应与警告都会以 `[OpenAI] ` 前缀出现在 MCDR 控制台；启动时会打印 `[OpenAI] Logging bridge enabled (level=INFO, loggers=…)` 作为确认。

## 插件更新

|现象|原因与处理|
|---|---|
|`更新已终止,两个下载源都失败: …`|GitHub release 与 `ghfast.top` 镜像都没能取到符合公告的文件（共四次尝试）。检查这台机器到 GitHub 的网络，然后重新执行 `!!gamesai check`。|
|`更新已终止,下载的文件未通过校验: …`|尺寸、sha256 或归档内的元数据与发布信息不符。**没有替换任何文件**。通常是代理或杀毒软件改写了下载内容 —— 重试;若持续如此则手工安装。|
|`更新已终止,插件文件无法替换: …`|插件已卸载，但 Windows 仍然锁着文件（杀毒、搜索索引）。旧文件已被重新加载，服务器照常运行；日志里写明了是哪个文件。稍后重试。|
|`更新已终止: … the previous version was restored`|新归档已就位但 MCDR 没能加载它（或加载出来的版本不对），于是恢复了旧文件并重新加载。请把日志片段反馈出来 —— 这是唯一值得深挖的情况。|
|`更新已终止:当前不是 .mcdr 打包安装,无法自行替换文件。`|本实例是源码目录式安装，无法自行替换文件。请手工安装 `.mcdr` 发布包（`!!MCDR plugin install -U -y games_ai`）。|
|更新失败，也没有尝试别的路径|这是刻意的：没有 `!!MCDR plugin install` 兜底（见[跨服联机](cross-server.md#集群更新)）。看清原因后重新执行 `!!gamesai check`，或手工安装。|
|某台节点从不自己更新|跨服客户端不跑更新检查，由 hub 决定。执行 `!!gamesai check`（会在 hub 上执行），或等 hub 的那一轮。|
|日志说本实例"已登记为节点,不会接管 hub 角色"|本实例加载时 hub 没有应答，而已入网实例永不接管 hub 角色。它会一直重试;如果 hub 彻底没了，执行 `!!gamesai node forget` 再重载。|
- 如果以上方法均无效，请检查 `config/games_ai/config.json` 是否存在配置错误。
