<div align="center">

# 故障排查

[English](../en_us/troubleshooting.md)  |  简体中文  |  [繁體中文](../zh_tw/troubleshooting.md)

[返回 README](../../README.zh-CN.md)

</div>

## `!!ask` 错误

|症状|可能原因|解决方法|
|---|---|---|
|HTTP 400|请求体格式错误|检查 `extra_body` 格式是否与 API 提供商的要求一致。|
|HTTP 401|API Key 无效|检查 AI 配置中的 `api_key`。|
|HTTP 404|模型不存在|检查 `ai_model` 名称是否正确。|
|HTTP 429|请求频率过高|稍后重试，或升级 API 套餐。|
|超时/无响应|网络问题或 API 响应慢|使用 `!!gamesai speedtest` 检查延迟。尝试更换模型。|
|「未知函数」回复|AI 调用了不存在的工具|通常无害——AI 会重试其他方法。|

## Mineflayer Bot 错误

|症状|相关日志|解决方法|
|---|---|---|
|Bot 未启动（完全没有 `[Mineflayer]` 日志）|`Mineflayer bot is enabled but Node.js was not found`|安装 Node.js >= 18。运行 `node --version` 验证。|
|Bot 在启动时被禁用|`Mineflayer requires Node.js >= 18, but found v{X}`|将 Node.js 升级到 18 或更高版本。|
|Bot 在启动时被禁用|`WebSocket port {X} is already in use!`|在配置文件中修改 `websocket.url` 为不同端口，然后 `!!gamesai reload`。|
|`[Bot] Kicked from server` 伴随认证原因|`[Bot] Kicked from server. Reason:` 后跟认证错误|通过 `!!aibot set` 检查 `username`/`password`/`auth`。Microsoft 认证需确保账号已迁移。|
|Bot 卡住不动|`goto` 操作返回 "No path found" 错误|`goto` 操作现在会在无路径时返回错误。尝试不同的坐标。|
|`[Bot] Disconnected` 后自动重连|`[Bot] Disconnected. Reason: ...` 后跟 `Reconnecting in 5 seconds...`|服务器重启或短暂断网后的正常行为。Bot 会在 5 秒后自动重连。|
|`[Bot] Died, respawning...`|`[Bot] Died, respawning...`|正常——Bot 死亡后会自动重生，无需干预。|
|Bot 不响应指令|日志中无 `[WS]` 活动|使用 `!!aibot leave` 然后 `!!aibot join` 重启。若持续存在，检查 `websocket.url` 端口是否可访问。|
|日志中出现 `npm install failed`|`npm install failed (exit {X})` 或 `npm is not installed or not in PATH`|确保 npm 已安装且在 PATH 中。检查日志中的详细错误信息定位具体包问题。|
|`Server version '{X}' is not supported`|`[Bot] Error: Server version ... is not supported. Latest supported version is ...`|Minecraft 服务器升级到了已安装 mineflayer 不支持的版本。插件会自动检测到该错误，更新 npm 依赖并重启 Bot。若错误持续存在，请检查服务器能否访问 npm 源，或在 `config/games_ai/mineflayer/` 下手动执行 `npm install --no-save mineflayer ws vec3 mineflayer-pathfinder mineflayer-mcefly`，然后通过 `!!aibot leave` / `!!aibot join` 重启 Bot。|

## 日志与调试

- **`!!gamesai debug`** — 开关调试模式。开启后完整的 AI 请求流程会以 INFO 级别显示在 MCDR 控制台（完整提示词、请求开始/结束、`!!ask -f` 入队与合并、轮次生命周期、工具调用与结果、上下文窗口/用量/校准系数以及每一次压缩过程）；关闭后同一批日志退回 DEBUG 级别。
- **`!!gamesai debug thread`** — 列出 GamesAI 当前持有的线程及其 id，用来确认卸载或热重载后有没有留下残留线程：
  - 每行格式为 `#<Python 线程 id>  <线程名>  [daemon|non-daemon]  native=<操作系统线程 id>`，正在执行该命令的线程会标记 `(current)`；
  - `#id` 是 Python 内部的线程标识（强制中止针对的就是它），`native=` 是操作系统层面的线程 id；
  - 只列出 GamesAI 自己的线程（`games_ai@...`，也包括旧版本遗留的 `AutonomousBotAI` / `MineflayerBotLog`）：卸载或 `!!MCDR plugin reload games_ai` 之后仍出现在列表里的，就是上一实例遗留的线程，插件会在下一次加载时自动中止它（若它正卡在阻塞调用中，则要等该调用返回后才退出）；
  - 一次最多列出 12 条，其余以 `... +N` 汇总。
- Mineflayer Bot 日志在 MCDR 控制台以 `[Mineflayer]` 前缀显示。
- **上下文相关的排查**（不需要开启 `!!gamesai debug`，三条都是只读、随时可执行）：
  - **`!!ask context [玩家]`** — 先看这个。窗口是多大、来源是哪一层（配置覆盖 / 模型表 / 默认值）、上下文占了多少、距离压缩还有多少余量、逐轮规模里有没有某一轮异常膨胀。悬停还能看到上次请求的缓存命中与推理用量；
  - **`!!ask context --all`** — 全服按模型汇总，用来判断"是不是所有人都在同一个模型上堆上下文"。悬停里的**自插件加载以来累计**不会因为压缩而减少，所以它是核对真实消耗的地方；"当前占用"在压缩或 `!!gamesai clear` 之后会掉下来，别把它当累计值；
  - **`!!ask compact`** — 手动压缩。远未到 80% 触发线但你想立刻瘦身时用它；它是**延迟执行**的（由你下次提问的预检发出总结请求），所以看到"已安排"而不是"已完成"是正常的。若回复"有对话正在进行"，说明有轮次在跑，等它结束或先 `!!ask stop`。
- 关于"假人上下线很慢"：正常路径下停机是**一次终止 + 有限等待**（毫秒级），启动慢主要来自 Node 启动与 Minecraft 登录本身。若在 `!!gamesai reload` 或卸载后看到 `bot_teardown` 线程仍在后台收尾，那属于预期行为（最多再等几秒）；若看到"WebSocket 端口已被占用"并因此禁用了 Bot，请确认没有第二个插件实例或手动启动的 Node 在占用该端口。
- **OpenAI 日志桥接**：插件加载时会把 `openai` 与 `httpx` 两个 logger 桥接进 MCDR 日志系统（固定 INFO 级别，与 `!!gamesai debug` 无关），因此 SDK 的 HTTP 请求/响应与警告都会以 `[OpenAI] ` 前缀出现在 MCDR 控制台；加载成功时会打印 `[OpenAI] Logging bridge enabled (level=INFO)` 作为确认。
- 如果以上方法均无效，请检查 `config/games_ai/config.json` 是否存在配置错误。
