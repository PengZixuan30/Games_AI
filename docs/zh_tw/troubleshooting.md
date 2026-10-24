<div align="center">

# 故障排除

[English](../en_us/troubleshooting.md)  |  [简体中文](../zh_cn/troubleshooting.md)  |  繁體中文

[返回 README](../../README.zh-TW.md)

</div>

## 缺少 Python 依賴套件

插件需要 `openai`、`requests`、`websockets`。它不要求你先裝好：啟動時發現缺套件會在日誌裡說明（`缺少 Python 依賴套件：...`），自動用 pip 補裝並重載自己。

- **兩次嘗試**：第一次用本機 pip 設定執行 `pip install <套件>`（不附加任何 index/代理參數，因此 pip.ini、`PIP_INDEX_URL` 與代理照常生效）；失敗後第二次改用阿里雲 PyPI 鏡像（`https://mirrors.aliyun.com/pypi/simple/`）重試，日誌裡會有一行說明，並且只請求仍然缺的套件。
- **pip 的每一行輸出都寫進日誌**，前綴 `[deps]`，裝得慢也不會看起來像卡住。只有套件真的能 import 之後插件才重載自己，重載後的實例會印出一行 `依賴已就緒，插件已恢復正常（...）`。
- **兩次都失敗**時日誌會印出 `依賴安裝失敗：...` 和可直接複製的指令（`python -m pip install openai requests websockets`）：

```bash
python -m pip install openai requests websockets
```

然後執行 `!!MCDR plugin reload games_ai`。在此之前插件處於「已載入但不運作」的狀態：不註冊指令、不啟動 bot 與跨伺服器連線。
- 套件清單在插件內的 `games_ai/requirements.txt`。它**刻意不放在插件根目錄**：MCDR 會在匯入插件前檢查根目錄的 `requirements.txt`，缺套件就直接拒絕載入 —— 那樣插件就永遠沒有機會自我修復。
- 透過插件倉庫安裝（`!!MCDR plugin install games_ai`）不再會預先裝好這些依賴：MCDR 只讀取插件根目錄的 `requirements.txt`，而清單現在位於套件內，因此倉庫安裝與其它啟動方式一樣，走同一套自我修復。
- 如果 pip 沒有解譯器 `site-packages` 的寫入權限（Python 裝在 `Program Files`、以服務帳戶執行等），安裝會以 pip 自己的錯誤失敗；請用 MCDR 所執行的使用者安裝，或在 `--user` 目錄位於該解譯器 `sys.path` 上時加上 `--user`。

## `!!ask` 錯誤

|症狀|可能原因|解決方法|
|---|---|---|
|HTTP 400|請求體格式錯誤|檢查 `extra_body` 格式是否與 API 提供商的要求一致。|
|HTTP 401|API Key 無效|檢查 AI 設定中的 `api_key`。|
|HTTP 404|模型不存在|檢查 `ai_model` 名稱是否正確。|
|HTTP 429|請求頻率過高|稍後重試，或升級 API 方案。|
|逾時/無回應|網路問題或 API 回應慢|使用 `!!gamesai speedtest` 檢查延遲。嘗試更換模型。|
|「未知函式」回覆|AI 呼叫了不存在的工具|通常無害——AI 會重試其他方法。|

> 失敗請求的日誌列現在是 WARNING，含狀態碼、含義與服務商的 Request ID（不必先開 `!!gamesai debug`）。回覆裡，只要失敗不是金鑰錯誤或限流，含義就緊接在狀態碼之後（例如 `HTTP 402 (API Key 餘額不足)`）；401 與 429 各有自己的句子，已經點明了原因。

## Mineflayer Bot 錯誤

|症狀|相關日誌|解決方法|
|---|---|---|
|Bot 未啟動（完全沒有 `[Mineflayer]` 日誌）|`Mineflayer bot is enabled but Node.js was not found`|安裝 Node.js >= 18。執行 `node --version` 驗證。|
|Bot 在啟動時被停用|`Mineflayer requires Node.js >= 18, but found v{X}`|將 Node.js 升級到 18 或更高版本。|
|Bot 啟動後一直不上線|日誌裡沒有 `Registered on hub`|確認 `websocket.uri` 指向的 hub 正在執行；Bot 撥號的是插件寫進它自己設定裡的位址，hub 沒起來時按該檔案中的 `reconnect_interval`（預設 10 秒）重試。詳見[跨服連線](cross-server.md)。|
|`[Bot] Kicked from server` 伴隨認證原因|`[Bot] Kicked from server. Reason:` 後跟認證錯誤|透過 `!!aibot set` 檢查 `username`/`password`/`auth`。Microsoft 認證需確保帳號已遷移。|
|Bot 卡住不動|`goto` 操作回傳 "No path found" 錯誤|`goto` 操作現在會在無路徑時回傳錯誤。嘗試不同的座標。|
|`[Bot] Disconnected` 後自動重新連線|`[Bot] Disconnected. Reason: ...` 後跟 `Reconnecting in 5 seconds...`|伺服器重啟或短暫斷網後的正常行為。Bot 會在 5 秒後自動重新連線。|
|`[Bot] Died, respawning...`|`[Bot] Died, respawning...`|正常——Bot 死亡後會自動重生，無需干預。|
|Bot 不回應指令|日誌中無 `[WS]` 活動|使用 `!!aibot leave` 然後 `!!aibot join` 重新啟動。若持續存在，檢查頂層 `websocket.uri`（`config/games_ai/config.json`）中的位址在 Bot 所在機器上是否可達。|
|日誌中出現 `npm install failed`|`npm install failed (exit {X})` 或 `npm is not installed or not in PATH`|確保 npm 已安裝且在 PATH 中。檢查日誌中的詳細錯誤資訊定位具體套件問題。|
|`Server version '{X}' is not supported`|`[Bot] Error: Server version ... is not supported. Latest supported version is ...`|Minecraft 伺服器升級到了已安裝 mineflayer 不支援的版本。插件會自動偵測到此錯誤，更新 npm 依賴並重啟 Bot。若錯誤持續存在，請檢查伺服器能否存取 npm 源，或在 `config/games_ai/mineflayer/` 下手動執行 `npm install --no-save mineflayer ws vec3 mineflayer-pathfinder mineflayer-mcefly`，然後透過 `!!aibot leave` / `!!aibot join` 重啟 Bot。|

## 日誌與除錯

- **`!!gamesai debug`** — 開關除錯模式。開啟後完整的 AI 請求流程會以 INFO 層級顯示在 MCDR 主控台（完整提示詞、請求開始/結束、`!!ask -f` 入列與合併、輪次生命週期、工具呼叫與結果、上下文視窗/用量/校準係數以及每一次壓縮過程）；關閉後同一批日誌退回 DEBUG 層級。
- **`!!gamesai debug thread`** — 列出 GamesAI 目前持有的執行緒及其 id，用來確認解除載入或熱重載後有沒有留下殘留執行緒：
  - 每行格式為 `#<Python 執行緒 id>  <執行緒名稱>  [daemon|non-daemon]  native=<作業系統執行緒 id>`，正在執行該指令的執行緒會標記 `(current)`；
  - `#id` 是 Python 內部的執行緒識別碼（強制中止針對的就是它），`native=` 是作業系統層級的執行緒 id；
  - 只列出 GamesAI 自己的執行緒（`games_ai@...`，也包含舊版遺留的 `AutonomousBotAI` / `MineflayerBotLog` 名稱）：解除載入或 `!!MCDR plugin reload games_ai` 之後仍出現在清單裡的，就是上一實例遺留的執行緒。下一次載入外掛時會自動中止殘留的 **bot 控制執行緒**（`games_ai@autonomous_bot`，或舊版的 `AutonomousBotAI`），若它正卡在阻塞呼叫中，則要等該呼叫返回後才會結束；其它殘留只會上報 —— 如果某個殘留一直不消失，就重新啟動 MCDR；
  - 一次最多列出 12 條，其餘以 `... +N` 彙總。
- Mineflayer Bot 日誌在 MCDR 主控台以 `[Mineflayer]` 前綴顯示。
- **上下文相關的排查**（不需要開啟 `!!gamesai debug`：`!!ask context` 與 `!!ask context --all` 是唯讀的、隨時可執行，而 `!!ask compact` 只是登記一次壓縮，由你下次提問前的預檢執行）：
  - **`!!ask context [玩家]`** — 先看這個。視窗是多大、來源是哪一層（設定覆寫 / 模型表 / 預設值）、上下文佔了多少、距離壓縮還剩多少餘量、逐輪規模裡有沒有某一輪異常膨脹。懸停還能看到上次請求的快取命中與推理用量；
  - **`!!ask context --all`** — 全服按設定的 AI 條目彙總（行名是該條目的 `ai_name`，懸停顯示 `all_ai` id 與上游 `ai_model`），用來判斷「是不是所有人都在同一個助手／模型上堆上下文」。懸停裡的**自其對話建立以來累計**不會因為壓縮而減少（重啟後仍然累計），所以它是核對真實消耗的地方；「目前佔用」在壓縮或 `!!gamesai clear` 之後會掉下來，別把它當累計值；
  - **`!!ask compact`** — 手動壓縮。遠未到 80% 觸發線但你想立刻瘦身時用它；它是**延後執行**的（由你下次提問的預檢發出總結請求），所以看到「已安排」而不是「已完成」是正常的。歷史在 10 輪以內時沒有可壓縮的內容，會直接回「目前沒有可壓縮的歷史記錄。」若回覆「有對話正在進行」，說明有輪次在跑，等它結束或先 `!!ask stop`。
- 關於「假人上下線很慢」：正常路徑下停機是**一次終止 + 有限等待**（毫秒級），啟動慢主要來自 Node 啟動與 Minecraft 登入本身。若在 `!!gamesai reload` 或卸載後看到 `bot_teardown` 執行緒仍在背景收尾，那屬於預期行為（最多再等幾秒）；若 Bot 一直不上線，檢查 `websocket.uri` 指向的 hub 是否可達 —— Bot 不再自己佔用連接埠。
- **OpenAI 日誌橋接**：外掛載入時會把 `openai` 日誌器以及已安裝 SDK 依賴的每一個 HTTP 日誌器（`httpx`/`httpx2`、`httpcore`/`httpcore2`，以及從 SDK 中繼資料推導出的名稱）橋接進 MCDR 日誌系統（固定 INFO 層級，與 `!!gamesai debug` 無關），因此 SDK 的 HTTP 請求、回應與警告都會以 `[OpenAI] ` 前綴出現在 MCDR 主控台；啟動時會印出 `[OpenAI] Logging bridge enabled (level=INFO, loggers=…)` 作為確認。

## 外掛更新

|現象|原因與處理|
|---|---|
|`更新已終止，兩個下載來源都失敗：…`|GitHub release 與 `ghfast.top` 鏡像都沒能取到符合公告的檔案（共四次嘗試）。檢查這台機器到 GitHub 的網路，然後重新執行 `!!gamesai check`。|
|`更新已終止，下載的檔案未通過校驗：…`|尺寸、sha256 或封存檔內的中繼資料與發布資訊不符。**沒有替換任何檔案**。通常是代理或防毒軟體改寫了下載內容 —— 重試；若持續如此則手動安裝。|
|`更新已終止，外掛檔案無法替換：…`|外掛已卸載，但 Windows 仍然鎖著檔案（防毒、搜尋索引）。舊檔案已被重新載入，伺服器照常運作；日誌裡寫明了是哪個檔案。稍後重試。|
|`更新已終止：… the previous version was restored`|新封存檔已就位但 MCDR 沒能載入它（或載入出來的版本不對），於是還原了舊檔案並重新載入。請把日誌片段回報出來 —— 這是唯一值得深挖的情況。|
|`更新已終止：目前不是 .mcdr 封裝安裝，無法自行替換檔案。`|本實例是原始碼目錄式安裝，無法自行替換檔案。請手動安裝 `.mcdr` 發布包（`!!MCDR plugin install -U -y games_ai`）。|
|更新失敗，也沒有嘗試別的路徑|這是刻意的：沒有 `!!MCDR plugin install` 兜底（見[跨服連線](cross-server.md#叢集更新)）。看清原因後重新執行 `!!gamesai check`，或手動安裝。|
|某台節點從不自己更新|跨服客戶端不跑更新檢查，由 hub 決定。執行 `!!gamesai check`（會在 hub 上執行），或等 hub 的那一輪。|
|日誌說本實例「已登記為節點,不會接管 hub 角色」|本實例載入時 hub 沒有應答，而已入網實例永不接管 hub 角色。它會一直重試；如果 hub 徹底沒了，執行 `!!gamesai node forget` 再重新載入。|
- 如果以上方法均無效，請檢查 `config/games_ai/config.json` 是否存在設定錯誤。
