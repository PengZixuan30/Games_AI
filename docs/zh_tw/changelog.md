<div align="center">

# 本次更新

[English](../en_us/changelog.md)  |  [简体中文](../zh_cn/changelog.md)  |  繁體中文

[返回 README](../../README.zh-TW.md)

</div>

## Version 0.7.3

### 🎯 核心亮點

- **🧱 system 只剩一條** —— prompt 與技能列表合併為一條 system 訊息，目前時間從中移出。部分上游（Qwen3.5/3.6/3.8 的 chat template 等）只允許下標 0 是 system，此前會直接回傳 `System message must be at the beginning`，這些模型完全不可用。
- **⏱️ 目前時間改由 `user` 訊息承載** —— 寫在提問正前方：第 1 輪注入，之後每 20 輪再注入一次。它會寫入歷史，因此相鄰兩輪之間的提示詞前綴完全一致，服務商的前綴快取可以持續命中（此前時間在 system 首行、每輪都變，等於每輪把整段歷史重新計費一次）。
- **🗄️ 公共資料改用 `assistant`** —— 它是資料而不是命令；公共資料庫為空時這條訊息完全不發送。
- **🧩 連續的 `user` 訊息在送出前合併成一條** —— 時間 + 提問、技能提示 + 提問、`!!ask -f` 的多條補充、上一輪失敗後的重問都會合併。

### 1. 請求裡的訊息結構

| 順序 | role | 內容 |
|---|---|---|
| 1 | `system` | 該模型的 prompt + 技能列表（**只有一條**） |
| 2 | `assistant` | 公共資料列表（資料庫為空時不發送） |
| 3… | 任意 | 對話歷史（提問正前方是一條 `user` 角色的時間訊息） |
| 末 | `user` | 本輪提問 |

- **技能提示改角色** —— `!!ask /技能.md` 注入的「先讀這個技能」提示由 `system` 改為 `user`；
- **無歷史路徑保持一致** —— `!!ask -n` 同樣是單一 system + 有資料時的 `assistant` + 合併後的一條 `user`；
- **`response_ai(data=None)` 受支援** —— 公共資料庫沒有任何記錄時不注入任何 data 訊息（此前會發一條空的「公共資料列表:」）。

### 2. 輪次切分與快取

- 連在一起的 `user` 訊息現在算**同一個回合**：否則每一條注入的時間都會被算成獨立一輪，`KEEP_ROUNDS = 10` 實際只剩 5 輪對話，壓縮邊界也會把一回合的時間與問題切開；
- 時間注入的計數在 `!!ask switch` 清空歷史時歸零（`!!ask clear` 直接銷毀物件），**壓縮不歸零** —— 壓縮視為同一段對話的延續；
- 合併只作用於**送出的請求**，歷史裡仍分別保存，因此 `!!ask context` 的統計與本地估算口徑不受影響。

### 3. 修復

- **清理殘留 Node 行程的兩處呼叫** —— `run_node()`（啟動前清理）與「偵測到不支援的伺服器版本 → 重裝依賴並重啟假人」路徑上的 `_kill_mineflayer_process()` 都補上了缺失的行程參數，此前會拋 `TypeError` 並被 `try/except` 吞掉，只留下一條日誌；
- **除錯日誌欄位更名** —— `!!gamesai debug` 的請求頭部由 `system=` 改為 `preamble=`（該位置現在也可能包含一條 assistant 訊息）。

### 4. 文件

- 三語技術文件新增「請求裡的訊息結構」一節，並同步更新請求鏈路、`!!ask -n` 一致性條目與「每玩家狀態」裡的 `system_message` 說明。

### ⚠️ 已知問題

- 歷史壓縮摘要與切換模型轉接摘要**仍以 `system` 訊息注入**（本次未改動），因此在只允許一條 system 的上游上，這兩條路徑仍可能被拒絕。

### 升級提示

- **設定無需改動**；
- 升級後第一次請求會重建提示詞前綴，舊的前綴快取會失效一次，之後恢復正常。

## Version 0.7.2

### 🎯 核心亮點

- **🔍 上下文檢視** — 三條唯讀指令把上下文管理從「看不見」變成「看得見」：`!!ask context` 查看某段對話的視窗佔用、距離壓縮還剩多少餘量、逐輪規模與快取命中；`!!ask context --all` 按模型彙總全服所有玩家的用量；`!!ask compact` 立即壓縮較早的歷史。三者共用同一套快照讀取，邊跑邊看不影響進行中的輪次。
- **🔧 `!!ask` 改為指令分派器** — 舊的 8 條獨立指令節點合併為 `!!ask` + `!!ask <content>`，子指令改由分派器解析。這是為了修掉一個真實缺陷：`!!ask stop it.` 這類「想對 AI 說的話」會因為 `stop` 是獨立指令節點而被 MCDR 判為**未知參數並整條丟棄**（`!!ask switch it.` 則會把 `it.` 當成模型名）。現在任何一句話都會落到 AI，除非它恰好就是那個子指令。
- **🧹 卸載與熱重載不再被假人拖住** — 停 Node 行程從「逐級升級、最多串行等 21 秒」改為一次終止 + 有限等待（實測 **5 毫秒**）；卸載時把停機搬到獨立執行緒，`on_unload` 只等 1.5 秒；`!!gamesai reload` 增加單飛鎖，避免兩次重載互相把對方的停機當成「連接埠被外來程式佔用」而**把假人功能整個關掉**。
- **🧵 執行緒可觀測** — 新增 `!!gamesai debug thread`，列出插件持有的所有執行緒及其 id；卸載時如實回報仍然存活的執行緒，殘留的舊控制器執行緒會在下次載入時被強制中止，而不是與新實例並存。

### 1. 上下文檢視：`!!ask context`

`!!ask context [玩家]`（不填玩家即查看自己，任何玩家可查任意玩家）：

- **正文**是幾行摘要：模型與視窗來源（設定覆寫 / 模型表 / 預設值）、上下文佔用及佔視窗比例、視窗與輸出上限、距離壓縮觸發還剩多少 token、輪次與訊息數；
- **懸停**放不進正文的細節：三條壓縮觸發線（歷史 80% / 突發 20% / 緊急 95%）、逐輪 token 規模與佔視窗比例、上次請求的輸入/輸出/快取命中/推理用量與本輪累計、最近一次壓縮的時間與前後訊息數。

數字來自 `ChatParam.context_snapshot()`，**在同一把鎖下讀取**：輪次執行緒會追加訊息、壓縮時會整個替換歷史清單，沒有這把鎖就可能讀到寫了一半的歷史。為此 `_split_rounds` / `_drop_oldest_round` / `_truncate_long_messages` / `_compress_old_rounds` 全部改為「公開方法加鎖 → 內部邏輯」的雙層寫法（可重入鎖，因為壓縮內部還會再切分輪次）。

### 2. 全服彙總：`!!ask context --all`

- 按**模型**彙總，每個模型一行：人數、目前上下文佔用合計與佔視窗比例、本輪輸入合計、本輪峰值合計；
- 懸停顯示該模型**自插件載入以來**的累計：輸入、輸出、合計、快取命中（0.1% 精度，截斷而非四捨五入）、推理 token；
- **零用量不列出**：沒人持有上下文、也沒有任何消耗的模型不會出現在清單裡；
- 不顯示玩家名，也不設權限限制。

為了讓「壓縮後仍能看到壓縮前的用量」成立，`ChatParam` 新增了四個**永不重置**的累計計數器（`_total_prompt/completion/cached/reasoning_tokens`）：原來只有每輪計數（每輪歸零）與最近一次計數（每次請求覆寫），壓縮一次就把帳抹掉了。**注意：這些累計從本次插件載入開始記，先前的呼叫無法追溯。**

### 3. 手動壓縮：`!!ask compact`

- 忽略視窗觸發線與「輪次不超過 10 輪就跳過」的提前返回，把較早的對話立即壓縮為摘要；
- 與模型切換的摘要轉接一樣**延後執行**：指令本身不等待總結請求（最長 60 秒），由你下次提問的預檢完成，因此指令立即返回、不阻塞伺服器執行緒；
- 結果分三種如實回報：已安排 / 沒有可壓縮的歷史 / 有輪次正在進行（需等它結束或先 `!!ask stop`）。

### 4. `!!ask` 指令分派器

- 註冊節點從 8 條減為 2 條（`!!ask`、`!!ask <content>`），子指令在 `ask_ai_dispatcher` 中按**詞**精確匹配，長邏輯一律放在獨立函式裡；
- 修掉的真實缺陷：`!!ask stop it.` 以前會報 `Unknown Argument` 並**什麼都不執行**；`!!ask switch it.` 會回覆「模型不存在」；
- 關鍵詞規則：`switch` / `stop` 必須**恰好是那個詞**才當子指令，帶任何多餘文字一律視為對 AI 的提問；`-n` / `--no-history` / `-f` / `--forced` 作為前置旗標，後接內容；
- 連帶修好：`!!ask -n`（缺內容）以前直接報 `Unknown Command`，現在作為普通提問；`!!ask contextual` 之類的詞不再被 `context` 前綴吞掉。

### 5. 卸載、重載與假人停機

- **Node 停機**：由「`terminate` → 等 3 秒 → `kill` → 等 3 秒 → Windows `taskkill /T /F` → 等 10 秒 → 再等 5 秒」改為一次 `terminate` + 2 秒等待，逾時後依平台追加一次強制手段，實測 **5 毫秒**完成；行程句柄先與模組狀態**解綁**再終止，因此下一個實例看到的是乾淨狀態；
- **非同步卸載**：`on_unload` 只同步等待 1.5 秒，其餘停機交給 `games_ai@bot_teardown` 背景執行緒；該執行緒只使用 `threading`/`subprocess`/`socket` 與**作為參數綁定**的日誌器，不讀模組全域、不碰 MCDR 物件（插件此時已卸載）；
- **重載單飛**：`!!gamesai reload` 加非阻塞鎖，重入時直接回「已有一次重載正在進行」；兩次重載並行時，後者的連接埠探測會把前者未結束的 Node 當成外來程式，進而把 `mineflayer_bot.enabled` 寫成 `false` 並再觸發一次重載——這條破壞路徑已封死；
- **連接埠探測**改為先等待進行中的停機完成（最多 5 秒），不再誤判；
- **首次連線退避**：WebSocket 客戶端在首次連上之前使用短間隔（新設定項 `mineflayer_bot.websocket.first_connect_interval`，預設 `0.5` 秒），不再因為 Node 還在啟動就白等一整個 `reconnect_interval`（預設 10 秒）；連上之後仍用設定的間隔。

### 6. 自治 Bot 控制器

- **協作停止優先**：新增 `_stop_event` 打斷週期間的等待，閒置控制器立即結束，不必再等滿一個 `cycle_interval`；
- **強制中止**：協作停止逾時後，`force_abort_thread` 透過 `PyThreadState_SetAsyncExc` 向控制器執行緒注入 `_ControllerAbort`（繼承 `BaseException`，不會被迴圈內的 `except Exception` 吞掉）。它**無法打斷阻塞中的 C 呼叫**（socket 讀取 / HTTP 請求），但會在該呼叫返回的瞬間生效；命中多個執行緒時會回滾；
- **AI 請求逾時**：控制器新增 `ai_timeout`（預設 120 秒），避免一個卡住的請求按 SDK 預設值掛住十分鐘；
- **殘留執行緒治理**：卸載後仍存活的舊控制器執行緒會在**下一次載入**時被中止（含舊版本的 `AutonomousBotAI` 執行緒名），並安裝執行緒例外鉤子把注入的中止記錄成一行日誌而不是一整段 traceback。

### 7. 其他改進與修復

- 新增 `!!gamesai debug thread` 與 `games_ai.debug.threads_header` 文案：列出插件持有的執行緒（`#id`、名稱、daemon、`native=`、`(current)`），每次最多 12 條；
- 全部執行緒統一命名為 `games_ai@...`（`games_ai@autonomous_bot`、`games_ai@ws_client`、`games_ai@update_loop`、`games_ai@update_timer`、`games_ai@data_*`、`games_ai@bot_teardown` 等），舊名 `AutonomousBotAI` / `MineflayerBotLog` 仍被識別；
- **修復 `mineflayer_bot.enabled` 被誤關閉**：寫 `config.json` 前先確保目錄存在，不再依賴呼叫者的工作目錄；
- `stop_mineflayer_bot` 補上 `@register_bot_tool()` 標記，自治 Bot 現在能真正呼叫它；
- 卸載與熱重載共用 `_stop_bot_stack()`，每一步獨立容錯：某一步失敗不會再連帶把 WebSocket 客戶端與 Node 行程留在原地；
- `response_chat` 的 `response_list` 補上型別標註；
- 文件重構：三語 README 只保留簡介 / 安裝 / 使用 / 指令總覽 / 技術文件連結等入口，技術細節移入 `docs/<語言>/` 下的**九個**檔案（AI 請求鏈路、Mineflayer Bot、設定、工具、技能、範例、熱重載、疑難排解、更新日誌），並隨插件一起打包。原有「工具與 Skills」一頁已拆分為獨立的工具與技能兩頁並按當前實作重寫（補齊權限與 Bot 可見性兩欄、修正與程式碼不符的參數說明），另新增一頁真實伺服器範例。

## Version 0.7.1

### 🎯 核心亮點

- **🧮 上下文自動管理** — 固定的 `max_history` 設定已移除。插件會自動解析各模型的上下文視窗、從服務商回傳的 `usage` 取得真實用量，並且只在上下文確實過大時才壓縮對話。
- **🔀 `!!ask switch` 的摘要轉接** — [#20](https://github.com/PengZixuan30/Games_AI/issues/20) 社群投票選出**方案 B1**：切換時立即清空原歷史，由**舊模型**在你下次提問前把它壓縮成一段中性事實摘要（與自動上下文壓縮同一時機）—— 切換不再阻塞，新模型拿到事實而不沾舊風格。
- **🛑 `!!ask stop`** — 一次停止你名下所有正在進行的內容：執行中的對話輪（含工具呼叫）、正在進行的 `!!ask -n` 提問、以及委派給 Bot 的任務。未完成的一步會從歷史中刪除，不會留下寫了一半的對話。
- **🪶 無狀態的 `!!ask -n`** — 單次提問不再建立（然後丟棄）一個完整的對話物件：`NonHistoryChatParam` 不保留歷史、佇列與上下文記帳，並按端點複用同一個 HTTP 用戶端。
- **📊 請求用量感知** — `response_chat` 現在會回傳服務商的 `usage`，插件因此能掌握每次請求的真實輸入量，並依 `base_url|model` 校準本地估算。
- **🧩 新增 `context_window` 選項** — `all_ai` 中每個 AI 可選填的視窗覆寫值，對於視窗極大的模型可作為成本控制開關。

### 1. 上下文自動管理

每次請求都會與模型自身的上下文視窗比對，只有確實需要時才壓縮對話。完整說明見[上下文自動管理](ai-request-pipeline.md#上下文自動管理)。

- **視窗來源**：單模型 `context_window` → 遠端表 [`data/context_windows.json`](https://github.com/PengZixuan30/Games_AI/blob/main/data/context_windows.json)（GitHub Raw，jsDelivr 備用，快取 24 小時）→ 版本內建表 → 保守預設值（`32768`）。
- **觸發條件**（每次請求**前後**都會檢查）：目前上下文達到視窗 **80%**，或單次請求達到視窗 **20%** —— 後者用於捕捉「一次讀取大日誌」這類突發成長。
- **壓縮方式**：最新 **10 輪**始終原樣保留；更早的輪次替換為一則中性事實摘要（由目前模型產生，不帶工具）。若仍不足，則截斷超長訊息並丟棄最舊輪次，保證下一次請求一定能裝得下。
- **校準**：本地 token 估算會依 `base_url|model` 與真實 `usage` 對齊，數輪內收斂。

### 2. 切換模型時的摘要轉接

`!!ask switch <model>` 現在實作 [#20](https://github.com/PengZixuan30/Games_AI/issues/20) 投票選出的**方案 B1**（投票已結束）：

- 摘要請求被**延後**，與自動上下文壓縮完全一致：指令只負責清空歷史並保存快照，由**舊模型**在你**下次請求之前**寫出中性事實摘要（討論主題、已確認結論、未完成事項、使用者明確要求 —— 不帶工具、60 秒逾時）。因此切換會立即返回，不再被摘要請求阻塞；
- 原歷史在切換時即被清空，舊模型回覆不再影響新模型的口氣與人設；
- 摘要作為新會話的第一條 system 訊息注入，並附帶「請以自己的設定與風格繼續」的提示；
- 延後的摘要失敗時本輪仍會正常回答，並告知玩家上一段對話已被丟棄；
- 切換到目前已在使用的模型不會改動任何東西；沒有歷史時也不會多發請求；
- 切換前會等待執行中的輪次結束，並重置工具計數、強制請求佇列與用量計數。

詳見[切換模型時的摘要轉接](ai-request-pipeline.md#切換模型時的摘要轉接)。

### 3. `!!ask -n` 的無狀態路徑

單次提問過去會建立一個完整的 `ChatParam`（歷史、佇列、生命週期事件、校準狀態、上下文管理），回答完就丟棄。現在改由 `NonHistoryChatParam` 處理 —— 一個自包含、什麼都不保留的類別：

- **不保留任何狀態** —— 整輪只活在 `response_ai` 內部，回傳即釋放；不會註冊進 `all_chat_param`，沒有歷史、佇列、`is_stopped` 事件與工具計數；
- **不做上下文管理** —— 不做 token 估算、不做用量校準、不壓縮歷史，因此也不會產生額外的摘要請求；
- **回答完全一致** —— 與一般路徑相同的 system 訊息、相同的按權限篩選工具、相同的回覆格式與錯誤回報；工具呼叫同樣在同一輪內執行並回注；
- **單輪超窗保險** —— 若整個請求超過模型視窗的 80%，則把最新一則訊息截斷到剩餘空間（有歷史的路徑仍然使用完整的上下文管理）；
- **共享 HTTP 用戶端** —— 用戶端按 `base_url` + API Key 快取，連續 `-n` 不必每次都重建連線池並重做 TLS 握手。

細節見[無歷史路徑](ai-request-pipeline.md#無歷史路徑ask--n)。

### 4. 設定與行為變更

- **`max_history` 已移除** —— 舊設定檔仍可正常使用，該鍵會被直接忽略。
- **新增 `context_window`**（可選，位於每個 AI 條目內）—— 見 [3.all_ai](configuration.md#3all_ai)。
- **新增遠端表** —— `data/context_windows.json` 在本倉庫維護（**249 條**，涵蓋 19 家廠商與各託管平台，核驗日期 2026-09-11；來源與口徑見 [`data/context_windows.sources.md`](https://github.com/PengZixuan30/Games_AI/blob/main/data/context_windows.sources.md)）。插件在啟動時與 24 小時更新檢查時取得，並快取到 `config/games_ai/cache/context_windows.json`；`!!gamesai check` 會無視 24 小時 TTL 強制刷新。維護者可編輯該 JSON 後執行 `python tools/build_context_table.py` 重新同步內建表並校驗。
- **刷新鏈路合併為一條** —— 視窗表刷新與啟動 / 24 小時更新檢查共用同一條執行緒，不再另外多起一條；並發刷新也不會重複下載兩次表。

### 5. 其他改進

- `response_chat` 新增單次請求 `timeout`，並回傳 `(message, usage)`；
- 新增 `context_table` 模組：表匹配、校驗、快取與靜默離線備援；版本內建表改放在生成式模組 `games_ai/context_table_data.py`（每條一行），不再內聯在邏輯模組裡；
- **內建工具的文字已全部英文化** —— 26 個內建工具的 `description` 與參數說明，**以及回傳給模型的工具回傳值**（執行結果、錯誤與權限提示）均為英文，函式呼叫提示詞不再混用中英；只有發給玩家的提示仍保持在地化；
- **`modify_skills` 與 `modify_custom_tools` 改為編輯而非整體重寫** —— 兩者都接收 `old_string`（Python 正規表達式）與 `new_string`（支援 `\1` 等反向參照），取代所有匹配而不是覆寫整個檔案。正規表達式無法編譯或匹配不到時退回字面文字取代；完全匹配不到則不寫入任何內容並明確告知模型。`modify_skills` 仍保留可選參數 `summary`，用於同步技能索引；
- `!!gamesai debug` 會輸出視窗、用量、校準係數與每一次壓縮過程；
- **新增 `!!ask stop` 指令** —— 在下一個檢查點中止該玩家執行中的對話輪（進行中的請求無法真正中斷），從歷史中刪除未完成的一步，丟棄 `!!ask -f` 佇列訊息，同時也會停止正在進行的 `!!ask -n` 提問與委派給自治 Bot 的任務。詳見[停止正在進行的對話](ai-request-pipeline.md#停止正在進行的對話)；
- 未對應的 HTTP 錯誤碼兜底文案改為翻譯鍵（`games_ai.error_code_map.error_unknown`），與其他錯誤碼一樣跟隨玩家語言；
- `custom_tools_management` 技能新增強制的「Step 0」：AI 必須**在撰寫任何工具程式碼之前**先向使用者確認需求、參數、權限等級與期望回傳值，並對有風險或不可逆的行為再次確認。

## Version 0.7.0

### 🎯 核心亮點

- **🧠 每玩家 ChatParam 架構** — 每個玩家的對話現在由一個專屬 `ChatParam` 物件管理：它擁有對話歷史、系統訊息、強制請求佇列與輪次生命週期事件。歷史處理、模型切換、強制提問都經由該物件。
- **🔀 模型切換：`!!ask switch <model>`** — 隨時切換目前對話使用的 AI 模型。0.7.0 暫時**完全保留歷史**；處理策略已由 [#20](https://github.com/PengZixuan30/Games_AI/issues/20) 社群投票決定（方案 B1，摘要轉接），並在 0.7.1 實作。
- **⚡ 強制提問：`!!ask -f <content>`** — 在輪次仍在執行時插入問題：訊息會被合併進執行中的輪次（或由自動補輪回答），無需等待上一個回覆結束。
- **🗑️ 移除的指令** — `!!ask -m <model> <content>`、`!!ask --model ...` 及其 `-n` / `--no-history` 組合已被移除；請改用 `!!ask switch <model>` + `!!ask -n <content>`。
- **📋 除錯日誌** — `!!gamesai debug` 現在可以讓完整的 AI 請求流程在 MCDR 主控台可見（模型切換、強制請求入隊/合併、輪次生命週期、工具呼叫）。
### 1. ChatParam：每玩家一個對話物件

`games_ai/chat_param.py` 引入 `BasicChatParam` / `ChatParam`：

- `response_list` — 該玩家的對話歷史；
- `system_message` — 每輪重建（目前時間、prompt、技能列表、公共資料）；
- `response_queue` — 等待合併的 `!!ask -f` 訊息；
- `is_stopped` — 輪次生命週期事件，用於序列化每個玩家的輪次；
- `trim_response_list()` — 有界歷史（`max_history × 2 + tool_count × 2`，已於 0.7.1 由上下文自動管理取代）；
- `reload_ai_info()` — `!!gamesai reload` 後刷新 AI 設定與使用者端。

所有玩家物件保存在 `all_chat_param` 中；`!!gamesai clear` / `!!gamesai clearall` 會刪除它們。

### 2. 完整請求鏈路

`!!ask <content>` → `ask_ai` 構建使用者訊息 → 玩家的 `ChatParam` → `response_ai` 組裝請求（system 訊息 + 歷史 + 按權限篩選的工具）→ 經複用的使用者端（`openai_api.response_chat`）存取 OpenAI 相容 API → 回覆發送給玩家；工具呼叫被執行並回填，直到 AI 給出最終文字回覆。詳見[AI 請求鏈路與對話機制](ai-request-pipeline.md#ai-請求鏈路與對話機制)。

### 3. 其他改進與修復

- `!!ask switch <model>` 現在附帶本地化確認訊息，並就地更新對話（0.7.0 保留歷史）；
- `response_chat` 改為注入 `OpenAI` 使用者端（每個 AI 設定一個）並附帶型別檢查；Mineflayer 自主控制器已適配新簽名；
- `!!gamesai reload` 會刷新既有 `ChatParam` 物件（重建使用者端），並在熱重載路徑中刷新 `AutonomousBotController` 設定；
- 強制請求流程有了完整的除錯日誌（入隊、合併、補輪）。
