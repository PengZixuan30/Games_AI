<div align="center">

# 故障排除

[English](../en_us/troubleshooting.md)  |  [简体中文](../zh_cn/troubleshooting.md)  |  繁體中文

[返回 README](../../README.zh-TW.md)

</div>

## `!!ask` 錯誤

|症狀|可能原因|解決方法|
|---|---|---|
|HTTP 400|請求體格式錯誤|檢查 `extra_body` 格式是否與 API 提供商的要求一致。|
|HTTP 401|API Key 無效|檢查 AI 設定中的 `api_key`。|
|HTTP 404|模型不存在|檢查 `ai_model` 名稱是否正確。|
|HTTP 429|請求頻率過高|稍後重試，或升級 API 方案。|
|逾時/無回應|網路問題或 API 回應慢|使用 `!!gamesai speedtest` 檢查延遲。嘗試更換模型。|
|「未知函式」回覆|AI 呼叫了不存在的工具|通常無害——AI 會重試其他方法。|

## Mineflayer Bot 錯誤

|症狀|相關日誌|解決方法|
|---|---|---|
|Bot 未啟動（完全沒有 `[Mineflayer]` 日誌）|`Mineflayer bot is enabled but Node.js was not found`|安裝 Node.js >= 18。執行 `node --version` 驗證。|
|Bot 在啟動時被停用|`Mineflayer requires Node.js >= 18, but found v{X}`|將 Node.js 升級到 18 或更高版本。|
|Bot 在啟動時被停用|`WebSocket port {X} is already in use!`|在設定檔案中修改 `websocket.url` 為不同埠號，然後 `!!gamesai reload`。|
|`[Bot] Kicked from server` 伴隨認證原因|`[Bot] Kicked from server. Reason:` 後跟認證錯誤|透過 `!!aibot set` 檢查 `username`/`password`/`auth`。Microsoft 認證需確保帳號已遷移。|
|Bot 卡住不動|`goto` 操作回傳 "No path found" 錯誤|`goto` 操作現在會在無路徑時回傳錯誤。嘗試不同的座標。|
|`[Bot] Disconnected` 後自動重新連線|`[Bot] Disconnected. Reason: ...` 後跟 `Reconnecting in 5 seconds...`|伺服器重啟或短暫斷網後的正常行為。Bot 會在 5 秒後自動重新連線。|
|`[Bot] Died, respawning...`|`[Bot] Died, respawning...`|正常——Bot 死亡後會自動重生，無需干預。|
|Bot 不回應指令|日誌中無 `[WS]` 活動|使用 `!!aibot leave` 然後 `!!aibot join` 重新啟動。若持續存在，檢查 `websocket.url` 埠號是否可存取。|
|日誌中出現 `npm install failed`|`npm install failed (exit {X})` 或 `npm is not installed or not in PATH`|確保 npm 已安裝且在 PATH 中。檢查日誌中的詳細錯誤資訊定位具體套件問題。|
|`Server version '{X}' is not supported`|`[Bot] Error: Server version ... is not supported. Latest supported version is ...`|Minecraft 伺服器升級到了已安裝 mineflayer 不支援的版本。插件會自動偵測到此錯誤，更新 npm 依賴並重啟 Bot。若錯誤持續存在，請檢查伺服器能否存取 npm 源，或在 `config/games_ai/mineflayer/` 下手動執行 `npm install --no-save mineflayer ws vec3 mineflayer-pathfinder mineflayer-mcefly`，然後透過 `!!aibot leave` / `!!aibot join` 重啟 Bot。|

## 日誌與除錯

- **`!!gamesai debug`** — 開關除錯模式。開啟後完整的 AI 請求流程會以 INFO 層級顯示在 MCDR 主控台（完整提示詞、請求開始/結束、`!!ask -f` 入列與合併、輪次生命週期、工具呼叫與結果、上下文視窗/用量/校準係數以及每一次壓縮過程）；關閉後同一批日誌退回 DEBUG 層級。
- **`!!gamesai debug thread`** — 列出 GamesAI 目前持有的執行緒及其 id，用來確認解除載入或熱重載後有沒有留下殘留執行緒：
  - 每行格式為 `#<Python 執行緒 id>  <執行緒名稱>  [daemon|non-daemon]  native=<作業系統執行緒 id>`，正在執行該指令的執行緒會標記 `(current)`；
  - `#id` 是 Python 內部的執行緒識別碼（強制中止針對的就是它），`native=` 是作業系統層級的執行緒 id；
  - 只列出 GamesAI 自己的執行緒（`games_ai@...`，也包含舊版遺留的 `AutonomousBotAI` / `MineflayerBotLog`）：解除載入或 `!!MCDR plugin reload games_ai` 之後仍出現在清單裡的，就是上一實例遺留的執行緒，插件會在下一次載入時自動中止它（若它正卡在阻塞呼叫中，則要等該呼叫返回後才會結束）；
  - 一次最多列出 12 條，其餘以 `... +N` 彙總。
- Mineflayer Bot 日誌在 MCDR 主控台以 `[Mineflayer]` 前綴顯示。
- **上下文相關的排查**（不需要開啟 `!!gamesai debug`，三條都是唯讀、隨時可執行）：
  - **`!!ask context [玩家]`** — 先看這個。視窗是多大、來源是哪一層（設定覆寫 / 模型表 / 預設值）、上下文佔了多少、距離壓縮還剩多少餘量、逐輪規模裡有沒有某一輪異常膨脹。懸停還能看到上次請求的快取命中與推理用量；
  - **`!!ask context --all`** — 全服按模型彙總，用來判斷「是不是所有人都在同一個模型上堆上下文」。懸停裡的**自插件載入以來累計**不會因為壓縮而減少，所以它是核對真實消耗的地方；「目前佔用」在壓縮或 `!!gamesai clear` 之後會掉下來，別把它當累計值；
  - **`!!ask compact`** — 手動壓縮。遠未到 80% 觸發線但你想立刻瘦身時用它；它是**延後執行**的（由你下次提問的預檢發出總結請求），所以看到「已安排」而不是「已完成」是正常的。若回覆「有對話正在進行」，說明有輪次在跑，等它結束或先 `!!ask stop`。
- 關於「假人上下線很慢」：正常路徑下停機是**一次終止 + 有限等待**（毫秒級），啟動慢主要來自 Node 啟動與 Minecraft 登入本身。若在 `!!gamesai reload` 或卸載後看到 `bot_teardown` 執行緒仍在背景收尾，那屬於預期行為（最多再等幾秒）；若看到「WebSocket 連接埠已被佔用」並因此停用了 Bot，請確認沒有第二個插件實例或手動啟動的 Node 在佔用該連接埠。
- **OpenAI 日誌橋接**：插件載入時會把 `openai` 與 `httpx` 兩個 logger 橋接進 MCDR 日誌系統（固定 INFO 層級，與 `!!gamesai debug` 無關），因此 SDK 的 HTTP 請求/回應與警告都會以 `[OpenAI] ` 前綴出現在 MCDR 主控台；載入成功時會印出 `[OpenAI] Logging bridge enabled (level=INFO)` 作為確認。
- 如果以上方法均無效，請檢查 `config/games_ai/config.json` 是否存在設定錯誤。
