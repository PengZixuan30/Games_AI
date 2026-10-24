<div align="center">

# 本次更新

[English](../en_us/changelog.md)  |  [简体中文](../zh_cn/changelog.md)  |  繁體中文

[返回 README](../../README.zh-TW.md)

</div>

## Version 0.8.0

- **不開 debug 也能看懂報錯**：失敗的請求現在會印出一條 WARNING 日誌列，含狀態碼、它的在地化含義與服務商的 Request ID（以前是 DEBUG 列）；玩家回覆裡，只要失敗不是金鑰錯誤或限流，含義就緊接在狀態碼之後（例如 `HTTP 402 (API Key 餘額不足)`），401 與 429 保留各自的句子，已經點明了原因。
- **對話歷史會落盤**：每個 `ChatParam` 在每輪結束後寫入 `config/games_ai/database/public_database.db` 的 `chat_history` 表，並在每次外掛載入時還原 —— 重載、更新、重啟乃至移除外掛都不會再遺失任何人的對話。它和 `!!data` 是同一個資料庫檔案（不同的表），叢集裡這份儲存屬於 hub；刪掉該檔案會同時丟掉兩者。`!!ask context` 顯示的那些數字也隨對話一起存下（上次請求用量、本輪計數、最近一次壓縮），重載後就回來了；只有「目前佔用」是載入時按還原出的歷史重新估算的，因為工具 schema 屬於下一次請求。
- **給其他使用者的助手捎話**：新增工具 `send_message_to_player_ai`，讓目前使用者的助手把一則訊息交給**任何人**的對話。它是單向的（對方下次提問時才會讀到，不會喚醒對方），並且對所有人開放：唯一的要求是目標已經擁有對話 —— **不比較也不查詢任何權限等級**（兩邊都不查），所以一次轉達不可能往 `permission.yml` 寫入名字。主控台自己的對話同樣是合法目標（鍵名 `Server Control Panel`）。
- **`!!ask stop` 會保留這一輪已經寫下的內容**：停止一輪不再刪除它打斷的那一步。提問、注入的提示（時間、技能）以及每一個結果已經回來的工具呼叫都留在歷史裡，也留在落盤的對話裡；只有末尾那個結果從未到達的工具呼叫會被丟棄（一整批未完成的平行呼叫會整批丟棄，因為服務商拒收沒有結果的 `tool_calls` 訊息）。排隊的 `!!ask -f` 訊息也不再被丟棄 —— 下一輪會照常合併它們。
- **可以按名字清除某個玩家的歷史**：新增的 `!!gamesai clear <name>` 會刪除另一個玩家的對話 —— 記憶體裡的和落盤的那一列 —— 並且需要設定的 `permission` 等級（不帶名字的 `!!gamesai clear` 只涉及你自己的歷史，仍然不需要任何等級）。目標玩家仍在途的那一輪會先被停掉，而一份已經不再是註冊對話的對話絕不會被再次落盤，所以這次清除不會被打斷它的那一輪撤銷。
- **工具作用域**：新增 `execute_in_hub` 註冊參數（預設 `false`）。每次跨服請求由發起方上傳本機可執行的工具 schema，hub 據此決定哪些呼叫在本機執行、哪些回傳給發起方，模型不會再看到兩邊都沒有的工具。權限由發起方用自己的 `permission.yml` 重新裁定；回傳呼叫不自動重試，逾時如實回報「結果未知」。
- **角色記憶與寬限期**：判定結果寫入 `config/games_ai/cross_server/role.json`，曾經是 client 的實例重載後會等待 hub（預設 15 秒）而不是搶連接埠；本機綁不上的位址永不判 hub；hub 自身重載仍立即判定；**沒有身份**的實例在 hub 始終不回來時仍然會接管。
- **鏈路的執行期狀態集中到一個目錄**：節點的 token（`identity.json`）、hub 的節點表（`nodes.json`）與角色記憶（`role.json`）都放在 `config/games_ai/cross_server/`。
- **外掛自己下載並替換自己**：不再使用 `!!MCDR plugin install`。新版本從本外掛自己的 GitHub release 下載（`https://ghfast.top/<位址>` 為第二來源），只有公告的尺寸、sha256 **以及**封存檔內的外掛 id 與版本全部相符才會被接受；安裝過程是卸載外掛 → 刪除舊檔案 → 移入已校驗的檔案 → 重新載入 —— 新檔案起不來時會還原 `.bak` 並用舊版本重新載入。任何一步失敗都會結束這一輪並說明原因；這裡**刻意沒有**退回 MCDR 安裝器的兜底。
- **叢集更新先節點、後 hub**：hub 先命令每台線上節點，阻塞等到它們都 `staged` **並且**以新版本重連回來，最後才替換自己的檔案。節點的跨服角色每次載入只判定一次，正是這個順序擋住了「hub 不在時載入的節點搶佔 hub 連接埠」。已入網實例**永不**接管 hub 角色（hub 徹底沒了時的出路是先執行 `!!gamesai node forget`），跨服客戶端完全不跑更新檢查，`!!gamesai check` 是在 hub 上執行、由它發起並協調整輪更新的指令。
- **插件自己安裝 Python 依賴套件**：啟動時缺少 `openai`、`requests` 或 `websockets` 不再代表插件閒置或根本無法載入。它會報出缺哪些套件、用 pip 補裝（先用本機 pip 設定，失敗後改用阿里雲 PyPI 鏡像重試，pip 的每一行都寫進日誌），裝好能 import 之後自動重載自己。為此 `requirements.txt` 從插件根目錄移入套件內：根目錄的 `requirements.txt` 未滿足時 MCDR 會直接拒絕載入插件，那樣插件就永遠沒有機會自我修復。

- **排隊提問只得到一條合併回答**：對話已在回答時再送的 `!!ask` 不再啟動第二輪。對話現在有原子的輪次持有者（一把鎖加 `active` 旗標，而不只是 `is_stopped` 事件）；等待的玩家會立刻收到與平時相同的「思考中」提示，輪次結束後排隊的問題按到達順序作為**一條合併的後續輪**送出，回答串流給該輪持有者。`!!ask stop` 會保留排隊問題並在之後送出；伺服器變更提示在輪次開始前寫入（不會落進工具呼叫群組中間），輪次準備階段的例外會被記錄並照常回覆，不會再讓對話卡在「執行中」。
- **技能工具只動技能目錄內的檔案**：`write_skills`/`modify_skills`/`delete_skills`/`read_skills` 拒絕絕對路徑、`..` 穿越與帶子目錄的檔名 —— 模型收到錯誤，而不是讀寫／刪除 `skills/` 之外的檔案。
- **重載不會把 AI 輪次推給叢集**：叢集廣播只會送出來源真正輸入的指令；重載工具不再把 AI 輪次的指令來源傳給 `!!gamesai reload`；節點會直接拒絕被廣播的 `!!ask`。工作階段 id 按實例唯一，一個實例的回傳不會再落到另一個實例的本機玩家身上。
- **不認識的遠端玩家仍然未知**：跨服權限查詢透過 MCDR 的權限管理器並傳入 `auto_add=False`，沒見過的名字一律 0 級，路由指令不再改寫 `permission.yml`。
- **公共資料庫只有一條加鎖連線**：`!!data` 與 AI 工具共用一條 SQLite 連線並使用原子 append，兩條並行 `add` 都會保留；卸載時關閉連線，資料路徑變化時重新開啟。
- **壞的重載輸入不再阻止外掛載入**：損壞或不是清單的 `skills.json` 會被記錄並當作「沒有技能」；設定中已刪除模型的對話會保留舊用戶端並打一條警告，而不是讓重載失敗（正在回答的對話會被跳過）。
- **機器人啟停以真實行程為準**：設定寫著啟用但行程已經崩潰的機器人會被強制重載重啟；停用會取消仍在等待伺服器的啟動；在 `run_node` 期間被中止的啟動會殺掉剛建立的行程，不會繼續建立控制器。
- **失敗的動作不再弄死機器人**：內嵌 `init.js` 動作 switch 中的例外會作為錯誤幀回傳（行程繼續執行）；失敗的 `goto` 總會清空尋路目標，而不是讓機器人繼續走。
- **更新輪次如實回報**：ack 逾時記為可糾正的 `timeout`（節點稍後仍可回報 `staged`）而不是 `failed`；沒有回報版本的節點會被照常下令，而不是拿空字串去比較；回滾只有在還原出的封存檔與備份逐位元組一致後才宣稱成功。
- **上下文壓縮不再阻塞指令處理**：摘要請求在上下文鎖之外執行（唯讀的 `!!ask context` 不會再在 MCDR 指令執行緒上等上近一分鐘），摘要產生期間追加的訊息也不會遺失（替換被跳過，並在下一次預檢重試）。
- **`setting_timer` 預設拒絕無上限等待**：超過 600 秒的等待會被拒絕並提示重試方式，除非模型明確傳入 `allow_long_wait=true`。
- **擴充外掛卸載不再把「排隊」誤報成 not found**：`on_unload` 本身執行在 MCDR 的外掛操作鏈裡，此時再卸載另一個外掛只會被排隊，而 MCDR 的 `unload_plugin` 對「已排隊」和「外掛不存在」都回傳 `None`。現在日誌會檢查 MCDR 是否仍持有該外掛的實例：排隊會以 INFO 記錄，只有確實已不存在的外掛才會被回報為 not found 並從卸載清單移除。
- **`!!ask context --all` 現在按設定的 AI 條目彙總，而不是按上游模型**：兩個 `all_ai` 條目即使指向同一個 `ai_model`，過去也會被合併成一列（列名取最先讀到的那段對話），於是玩家分散在兩個助手時指令仍顯示「1 個模型」。現在每一列是一個設定條目（列名用 `ai_name`），懸停顯示 `all_ai` id 與服務商實際計費的上游 `ai_model`。無法讀取用量的對話會寫一條日誌並被跳過，不再從合計裡悄悄消失。
- **帶顏色的 `ai_name` 不再把 `!!ask context --all` 列的後半段刷成白色**：`ai_name` 允許包含 § 格式代碼（設定文件中有說明），在灰色的模型列裡它們會覆蓋列顏色，而 `§r` 會讓名字之後的內容變成預設白色。現在名字之後會重置並重新設為灰色，設定的名字保留自己的顏色，人數／佔用／本輪數字恢復灰色。

本次更新的主題是**跨服連線**：多個 MCDR 實例可以組成一個叢集，共用同一個 AI、同一份對話歷史與同一份公共資料庫。

### 🌐 跨服連線

- **自動決定角色**：外掛啟動時探測 `websocket.uri`。能連上且確認對端是 GamesAI → 本機以**客戶端**接入；連不上且連接埠空閒 → 本機自己**監聽**並成為 hub；開啟 `force_server` → 強制當 hub（連接埠被佔則報錯並退回 local）。
- **不是 GamesAI 就不碰**：`uri` 被其他服務佔用時，跨服功能整體停用（既不當客戶端也不起服務端），本機功能完全照舊。
- **互相辨識**：`hello` / `hello_ack` 都帶 `"app": "games_ai"` 與協定版本，對不上就以專用關閉碼拒絕；啟動前的探測帶 `"probe": true`，**只回答不登記**，不會污染線上名單、也不會誤觸頂號。
- **每 node 專屬 token**：新實例先在 hub 上 `!!gamesai node pending` 查看、`node token <名字>` 簽發（只有等待中的名字可簽發），再到該實例 `node claim <token>` 領取；hub 只存 `sha256` 雜湊，明文 token 只在回覆裡出現一次。關閉碼 `683`（需要註冊）與 `683`（token 過期）均不可重試；有效期由 hub 的 `websocket.token_ttl_hours` 控制（預設 `-1` 永久），只在握手時校驗。機器人由 hub 自動簽發，無需人工。
- **`websocket.name`**：可覆寫本實例在叢集裡的名字。留空時按**實例目錄**派生（`<目錄名>-<路徑雜湊前 6 位>`，如 `survival-9f31ab`），同機雙實例不會撞名，改機器名也不影響註冊。
- **握手 ID 區分 peer 種類**：`games_ai_mcdr`（實例）與 `mineflayer_bot`（假人）兩種身分，hub 依它自動適配 —— 叢集廣播只發給可信實例，絕不發給假人；`hello_ack` 的 `app` 恆為 hub 自己的 `games_ai_mcdr`，並用 `you` 欄位告訴對端被認成了什麼。
- **`websocket.allow_app_id`**：字串列表設定，讓你自己的服務接入本 hub 時不被 `683` 拒絕。hub 不為這些 ID 做專項適配（它們就是普通 peer），但它們會被**完全信任**，可像 GamesAI 實例一樣觸發指令執行，所以只填自己控制的服務。
- **身分用實例目錄**：客戶端名稱預設由實例目錄派生，也可以用 `websocket.name` 指定。同名後到者仍會頂掉先到者（舊連線收到 `683` 並帶著原因結束），並且 hub **拒絕**為已經註冊過的名字再簽發 token —— 那會把在線的那個節點頂下線（`683`，不可重試）；要刻意替換請用 `!!gamesai node rotate <name>`。
- **角色會被記住**：判定結果寫入 `config/games_ai/cross_server/role.json`，曾經是 client 的實例會等待 hub（預設 15 秒）而不是搶連接埠；hub 自身重載仍立即判定。本機綁不上的位址永不判 hub；**沒有身份**的實例在 hub 始終不回來時仍然會接管。
- **鏈路的執行期狀態集中到一個目錄**：`config/games_ai/cross_server/` 存放節點的 token（`identity.json`）、hub 的節點表（`nodes.json`）與角色記憶（`role.json`）。
- **local 模式仍有本機鏈路**：在本機回環（`127.0.0.1` 隨機連接埠）上會起一個只服務本機 peer 的 hub，讓假人在任何模式下都有地方接入。
- **機器人不能指揮 hub**：`mineflayer_bot` 由 hub 在回環位址上自動簽發（隧道/反向代理會讓 hub 把所有來源都看成回環），因此 hub 在路由之前就拒收機器人身份發來的 `command`、`command_cluster`、`exec_cluster`、`tool_call`、`event` 幀（`reply` 與 `ping` 照收），並記一條 warning。
- **註冊有頻率與容量上限**：每個 IP 每分鐘最多 10 次新名字請求，等待清單上限 32 條、7 天自動過期；已註冊節點握手時若 `last_seen` 沒變，不再重寫節點表。
- **幀在發送前先量尺寸**：超過 1 MiB 時，工具結果會變成一條誠實的錯誤、串流輸出會變成一行提示，因此對端不會用 `683` 關閉鏈路、把正在跑的對話一起帶走。
- **對端斷開會喚醒等待中的呼叫**：節點崩潰（或 hub/node 停止）會立即釋放所有等待中的呼叫並回「結果未知、不要重試」，而不是讓它們各自撞滿 120 秒逾時。

### 🧩 指令按類路由

- **A 類（交給 hub 執行）**：`!!ask`（含 `-n/-f/switch/stop/compact/context`）、`!!data`、`!!gamesai clear [name]`、`!!gamesai speedtest`、`!!gamesai config get/set`、`!!aibot join/leave/set`。
- **B 類（本機執行）**：各指令的說明文字。
- **C 類（叢集廣播）**：`!!gamesai clearall`、`reload`、`debug`、`debug thread` —— hub 與所有客戶端各自執行；發起方自己那台的輸出不加前綴，其他台加 `[實例名]`。（`!!gamesai check` 屬於 A 類：檢查更新是 hub 的決定，接著由它協調整個叢集。）
- **內部呼叫永不轉發**：沒有 Info 的呼叫（例如我們自己的 `server.execute_command()`）留在原地，否則 `reload` 會在叢集裡來回彈。
- **權限**：遠端玩家取 `min(客戶端上報等級, hub 側 permission.yml)`，hub 不認識這個名字就是 0；遠端控制台恆為 4。

### 🎨 富文本回傳

- 跨服回傳使用 **MCDR 自己的 JSON 文字物件**（`to_json_object()` / `from_json_object()`），顏色、粗體/斜體/底線/刪除線、hover 文字、四種點擊動作（`run_command` / `suggest_command` / `copy_to_clipboard` / `open_url`）與巢狀列表全部保真，因此 `!!data read` 的寫入/複製按鈕在客戶端一樣可用。
- 遠端指令由一個只繼承 `CommandSource` **基底類別**的 `WebSocketCommandSource` 代表（發起者可能是玩家也可能是控制台），`source.reply()` 就是串流回傳通道。

### 🤖 假人接入叢集

- Mineflayer 機器人從「**自己開一個 WebSocket 服務端**」改成「**接入叢集的客戶端**」，以機器人使用者名稱註冊，動作仍走原本的 switch，因此所有 bot 工具與自治控制器的行為不變。
- 不再佔用連接埠：舊的機器人位址被佔時不必再改設定，機器人的鏈路也不會和跨服鏈路搶同一個連接埠。
- 啟動順序改為**先決定角色、再寫機器人設定並拉起行程**（機器人連的位址取決於本機角色）。

### 🔧 修復

- **OpenAI 請求日誌沒有橋接到 MCDR 日誌器**：`openai` 2.x/3.x 的 HTTP 依賴已從 `httpx` 換成 `httpx2`，而日誌橋只橋接了 `httpx`，導致 `INFO:httpx2:HTTP Request: ...` 冒泡到 root logger、以裸格式打在 MCDR 主控台裡。現在橋接的 logger 名稱**從已安裝 SDK 的 metadata 推導**，依賴再改名也不會重演。
- **設定遷移**：舊的 `mineflayer_bot.websocket.url` 自動搬到頂層 `websocket.uri` 並刪除舊區塊；新增的 `websocket` 區塊由 MCDR 的 `data_processor` 鉤子在補預設值**之前**處理，不會覆蓋使用者既有的位址。
- **時間讀數改由時鐘驅動刷新，並且帶上了時區**：此前一段對話無論閒置多久都拿最後一輪讀數的時間回答 —— 20 輪在一次會話裡是 20 秒，在下一次就可能是 20 小時 —— 而且讀數只是本地時間字串，沒有任何偏移。現在第 1 輪、每 20 輪、**以及距上次讀數超過 10 分鐘時**都會刷新；讀數是四行：帶伺服器 UTC 偏移的 ISO 時間戳、本讀數所用的時區、距上次讀數的時間、距上一條訊息的時間。兩個基準隨對話一起儲存，重啟與壓縮都不會讓它們失真；沒有基準可量時讀數寫 `unavailable`。時區由外掛從機器上判定（`TZ`、系統自帶記錄、C 函式庫名稱），數字偏移始終取自時鐘本身，因此 DST 與剛被改動過的時鐘都不會算錯 —— 而且刻意不做任何設定項，因為伺服器只執行在一個時區裡，也就是操作者的那個。這四行是寫在程式碼裡的英文而不是翻譯字串（`lang/*.yml` 裡對應的鍵已刪除）：它們是給模型看的，含義不該隨伺服器恰好在用的語言變化。自治控制器自己的時間行同樣換成這套時間戳與時區、同樣用英文；它的訊息每輪重建，因此不需要輪號與時間差兩行。

- **產生的 `tools.py` 骨架檔案匯入了一個已不存在的模組**：首次啟動時 `on_load` 會把 `from games_ai.games_ai_tool import register_tool` 寫進 `config/games_ai/tools/tools.py`，[工具](tools.md) 頁面與內建的 `custom_tools_management` 技能展示的是同一行 —— 三者都寫於模組被收進子套件之前。該匯入會拋 `ModuleNotFoundError`，而 `tools.py` 是當作**一個**模組載入的，因此檔案裡的**每一個**自訂工具都會跟著失敗：日誌裡只有一行 `Failed to load external tools: No module named 'games_ai.games_ai_tool'`，沒有任何工具註冊成功。現在骨架檔案與兩份文件裡的路徑都是 `games_ai.ai.games_ai_tool`；[熱重載](hot-reload.md) 裡的 `register_self` 範例（`games_ai.ai.register_extra_plugin`）與 [技能](skills.md) 裡的 `register_skills` 範例（`games_ai.ai.external_skills_loader`）做了同樣的修正，`tools/build_context_table.py` 也改為重新產生外掛真正讀取的那個檔案（`games_ai/ai/context_table_data.py`），而不是子套件化之前的路徑 —— 在那個路徑上更新表格只會寫出一個沒人引用的模組，隨版本內建的備援表依舊是舊的。新增的文件檢查會匯入這些頁面給出的每一行 `games_ai` 匯入（模組**與**名字），被搬動過的模組再也不能留下一份可複製貼上卻跑不通的範例。

- **更新檢查迴圈不再播報沒人要求的檢查**：載入時與每 24 小時各跑一次的那次檢查，過去會向全服廣播「正在檢查更新」，緊接著再廣播「沒有新版本」—— 每次載入都刷一行，為的卻是一個沒有玩家在等的決定。現在它保持安靜：`正在檢查更新` 與 `沒有新版本` 只寫進除錯日誌（`!!gamesai debug` 可見），只有真的發現新版本時才播報，並接著播報安裝它的那一輪。`!!gamesai check` 不變 —— 有人輸入了指令，所以它照常回報「正在檢查更新」與結果，且只回給輸入者 —— 檢查**失敗**（拿不到目錄或 metadata）在兩條路徑上都保持可見，因為那需要維運介入。（四個情境由 `tests/test_update_notice.py` 鎖定。）

- **遠端指令來源現在實作了整套指令來源 API**：從另一個實例轉發過來的指令由 `WebSocketCommandSource` 代表，為本地玩家/主控台指令來源寫的處理函式不應感到任何差別。`get_info()` 現在存在：它用轉發來的指令列重建該指令的 `Info`，並在 MCDR 允許時於本實例上 finalize，因此 `Info.get_server()` 與 `Info.get_command_source()`（回傳的就是本 source）與本地指令表現一致 —— 而路由過來的**工具呼叫**背後沒有指令，會以 `IllegalCallError` 明確拒絕，而不是憑空編一個。`get_preference()` 在遠端玩家的情況下按名字查本實例的偏好檔案（主控台與未知名字用預設值），於是 `preferred_language_context()` 的解析與本地指令一致。`reply()` 會採用主控台來源的 `console_text`、並接受玩家來源的 `encoding`；兩個 source 在「同一實例上的同一發起者」時相等 —— 與 MCDR 內建指令來源的比較方式一致，也因此和內建來源一樣不可雜湊。`_raw_command` 在轉發來源上明確回傳空：它現在有 `Info`，若無這道守衛，來自鏈路的指令會被再次轉發、叢集指令會被再次擴散，永遠停不下來。`tests/test_ws_command.py` 逐個成員覆蓋了這套 API。

- **`!!ask` 這一輪重新回到自己的執行緒上**：拆分進子套件時，`ask_ai` 上的 `@new_thread("games_ai@ask_ai")` 裝飾器被丟掉了，於是整輪 AI 請求 —— 服務商往返、串流輸出、工具呼叫，動輒數分鐘 —— 全都跑在 MCDR 的同步 TaskExecutor 上。MCDR 的看門狗在 `advanced.watchdog_threshold`（預設 10 秒）沒有回應後就會判定執行器無回應並**重建**它，每次都把本外掛的執行緒堆疊打進日誌 —— 這就是「一邊回答一邊瘋狂重建執行器」的原因，其它指令也全被堵在這一輪後面。裝飾器已恢復，執行緒名仍是 `games_ai@ask_ai`（`on_unload` 早已在報告這個名字），因此指令立刻返回、整輪在獨立執行緒上串流輸出，與拆分之前完全一致。`tests/test_migration.py` 鎖住這個包裝；`tests/test_ask_errors.py` 的失敗場景改走 `ask_ai.original` 呼叫未裝飾的函式本體，因為失敗必須發生在測試執行緒上。

### 📚 文件

- 新增專門的三語文件 [跨服連線](https://github.com/PengZixuan30/Games_AI/blob/main/docs/zh_tw/cross-server.md)：角色判定、設定、協定框架、指令分級、權限、富文本、假人接入與排障。
- `configuration.md`（新增 `6.websocket` 一節）、`mineflayer-bot.md` 與 `troubleshooting.md` 已按 0.8.0 的跨服行為更新。

### 🧱 內部結構

- **實例設定只有一個來源**：`__init__.py` 裡與 `plugin_config` 並存的 8 個影子全域（訊息前綴、指令權限、模型表、預設模型、資料庫路徑、技能索引、AI 名稱 → ID 的對應、除錯開關）已全部刪除，所有讀取點改為 `plugin_config.<欄位>`（其它模組本來就這麼做），`_apply_config` 每個值只寫一次。名稱 → ID 的對應改為 `_ai_id_for()`，設定變更後不會再失效；`send_help()` 也去掉了在 54 處呼叫點重複傳遞的前綴參數。
- **假人的 JavaScript 獨立成模組**：`games_ai/bot/mineflayer_service_files.py` 收攏了內嵌的 683 行 `init.js`、`package.json`，以及配套的兩個寫入函式與雜湊校驗——它們原本佔 `mineflayer.py` 的 70%，該檔案從 683 行降到 581 行。寫入函式與雜湊校驗都原樣搬進了新模組（`get_default_init_hash()` 比較的仍是同一個摘要），因此這次拆分本身不會重寫任何已部署的 `init.js`；該檔案會被 0.8.0 的假人鏈路改動替換一次，這正是雜湊校驗本來就該做的事。
- **更新路徑獨立成模組**：`games_ai/update/update_round.py` 收攏 24 小時檢查、叢集輪次與版本比較（695 行原本在 `__init__.py` 裡，該檔案現在為 3579 行）。它透過 `attach()` 注入的取值函式**在使用時**讀取實例的即時狀態，因此從不 import 入口模組，也總能拿到目前的跨服管理器。更新的觸發時機與流程沒有任何變化。
- **說明文字獨立成模組**：`gamesai_help` 類別與它的 `send_help` 輔助函式從 `games_ai/__init__.py` 搬進了 `games_ai/ui/help.py`（172 行），入口模組也正是因此降到 3579 行。新模組不從入口模組 import 任何東西 —— 問候語裡的版本號直接來自 MCDR 的外掛中介資料；入口模組仍然轉出這兩個名稱，原本 import 它們的程式不受影響。`!!gamesai` 與各指令的說明列輸出與之前完全一致。
- **權限校驗只有一個出處**：`games_ai/core/permission.py`（58 行）取代了只服務 node 指令的 `_node_require_permission`，以及後來在它旁邊長出來的四十處同樣的比較。`require_permission(source)` 是每個指令與說明處理器呼叫的那道門 —— 它發出本地化拒絕並回傳 `False`；`has_permission(source)` 是它背後的謂詞，供工具包裝函式與說明列表使用；工具回傳給 AI 的兩句話改為常數（`TOOL_DENIED_LEVEL`、`TOOL_DENIED_NOT_ALLOWED`），不再是 8 處與 3 處各寫一遍。它必須獨立成模組，因為 `help.py` 不能 import 入口包。唯一可見的變化：說明頁面與 `!!aibot` 的拒絕訊息現在也帶訊息前綴，與它們列印的其它行一致。
- **node 指令獨立成模組**：`!!gamesai node` 下的八個處理函式 —— pending、token、list、revoke、rotate、claim、status、forget —— 與只被它們使用的助手一起從 `games_ai/__init__.py` 搬進了 `games_ai/commands/node.py`（409 行）。該模組不 import 入口包：即時鏈路、外掛 server 介面、身份檔案與鏈路的重啟/停止都由一次 `attach()` 呼叫注入，與 `update/update_round.py` 已有的做法相同。其餘行為不變 —— 同樣的回覆、同樣的權限門，以及同樣「不經過叢集路由、在輸入處執行」的註冊方式。
- **外掛原始碼現在是一棵子套件樹**：原先並排放在 `games_ai/` 裡的模組按職責分組 —— `core/`（設定、日誌、依賴閘、權限規則、資料庫）、`commands/`（玩家輸入的指令：`!!data`、`!!gamesai config`、`!!aibot`、`!!gamesai clear`、`!!gamesai node`）、`cluster/`（角色決定、hub、節點客戶端、遠端指令來源）、`ai/`（請求鏈路、服務商客戶端、上下文視窗表、工具登錄表、技能索引）、`bot/`（Mineflayer 行程、它的控制器、內嵌 `init.js`）、`update/`（自更新與驅動它的輪次）與 `ui/`（說明文字）。四組指令處理函式離開入口模組搬進 `games_ai/commands/` —— `!!data` 管理器、`!!gamesai config` 與 `!!aibot set`、`!!aibot join`/`leave`、`!!gamesai clear`/`clearall` —— 入口因此從 3642 行降到 3579 行。子套件的 `__init__.py` 同時也是門面：它轉出該套件的公開名字 —— 不需要第三方的 eager 匯入，需要第三方的首次存取時才匯入（PEP 562）—— 因此早早 import 一個套件仍然不會把第三方套件拖上「缺套件也能載入」的門前路徑，而入口模組現在一切取自這些門面。每個門面還用 `if TYPE_CHECKING:` 區塊把懶載入的名字再宣告一次：那個區塊永不執行，但編輯器與型別檢查器讀的就是它，因此 `from .ai import ChatParam` 拿到的是真實簽名而不是 `Any`。`tests/test_layout.py` 現在守護這棵樹 —— 已知子套件與模組、門面（`__all__` 可解析、eager 匯入門前安全、靜態區塊與執行時映射一致、入口不越過門面直接引用模組）、匯入圖無環與門前閉包 —— 新增的三語[架構](architecture.md)頁面把它畫了出來。
- **校驗套件進入倉庫**：執行器換成了 pytest —— 在倉庫根目錄直接執行 `python -m pytest` 就能收集整套 593 個用例（`tests/` 頂層的 42 個測試模組，加上 `tests/docs/` 下的 5 個文件檢查器），設定來自根目錄的 `pytest.ini`；以前逐一啟動它們的自製執行器 `tests/_run_suites.py` 已不存在。每個套件原先各自攜帶的東西現在只有一份：共享 fixture（`free_port`、安靜日誌預設值，以及把外掛的倉庫相對路徑釘在暫存目錄裡的會話級兜底）在 `tests/conftest.py`，助手模組與三個協定原型在 `tests/_helpers/`。它們從自身位置推導倉庫路徑，不再寫死某台機器上的絕對路徑；新增的三語[測試](testing.md)頁面說明怎麼裝 pytest、怎麼跑全部/單個模組/按名字挑選用例，以及跑測試需要什麼。新增的 `tests/test_layout.py` 守護佈局本身 —— 模組清單、入口模組的行數預算、套件內匯入圖無環、依賴閘之前的匯入只需要標準庫與 MCDR，以及檔案層級約定。打包不受影響：MCDR 只打包清單 `resources` 列出的內容，`tests/` 不會進入 `.mcdr`（已對實際打包產物核驗）。

- **編輯器現在能拿到 `games_ai.*` 的真實型別**：外掛會把一個生成出來的 `games_ai/` 存根套件（`.pyi`）播種到 `config/games_ai/tools/`，就在使用者的 `tools.py` 旁邊，因此 VS Code 能在**不需要任何專案設定**的情況下解析 `from games_ai.ai.games_ai_tool import register_tool` 以及其它文件承諾的匯入 —— 此前該匯入會被報為無法解析，外掛裡的每個名字都是 `Any`。與被編輯檔案同目錄的存根套件會被自動找到；對於以 `.mcdr` 打包安裝的情況，這也是唯一途徑：它的原始碼在封存檔裡，語言伺服器讀不到（目錄安裝可以改用 `python.analysis.extraPaths` 指向外掛目錄）。該樹由新增的 `tools/build_tool_stubs.py` 從外掛自身原始碼生成（每個模組一個存根，目前 41 個；`--check` 報告漂移），並帶上 `stubgen` 預設不寫的 docstring，因此把滑鼠停在某個名字上能看到它做什麼，而不只是呼叫形態 —— 文件承諾過、但原始碼裡本來沒有 docstring 的四個助手（`register_bot_tool`、`get_plugin_config_perm`、`register_self`、`register_skills`）在原始碼裡補了簡短說明，因為存根只能發布原始碼裡既有的東西 —— 隨外掛放在 `games_ai/ai/_stubs/`；`games_ai/ai/tools_stub_files.py` —— 同時接管了 `tools.py` 骨架的那個模組，入口模組如今是 3579 行（那次搬出後是 3320 行，Python 版本檢查與恢復的 `ask_ai` 裝飾器又占 11 行） —— 在載入時把它複製出去，且只在檔案缺失或與隨附存根逐位元組不同時才重寫（文字模式寫入會在 Windows 上轉譯行尾，之後就永遠比較不相等）。`register_tool` 與 `register_bot_tool` 補上了它們本來就隱含的 `ParamSpec` 註解，否則被裝飾的工具在編輯器裡會丟掉自己的簽名。`tests/test_tool_stubs.py` 同時守護兩半：隨附存根對原始碼（每模組一個，公開簽名與 `inspect` 逐一比對），以及寫入器對使用者磁碟（絕不改動既有的 `tools.py`、未變化的存根不重寫、LF 行尾、打包安裝從封存檔讀取、不可寫的目錄只記日誌而載入繼續）。

- **工具登錄表 0.8.0 之前的匯入路徑繼續可用**：登錄表搬進了 `ai/`，因此 `games_ai/games_ai_tool.py` 現在是一個相容模組，再匯出它的公開名字 —— 同一批物件，所以無論從哪條路徑註冊，工具都落進外掛讀取的同一個登錄表。既有的 `config/games_ai/tools/tools.py` 以及任何按 `from games_ai.games_ai_tool import register_tool` 寫的外掛（`register_bot_tool`、`get_plugin_config_perm`、`get_tool_handler`、`TOOL_SCHEMAS`、`ToolHandler`、各內建工具函式……）都無需改動；新程式碼請用 `games_ai.ai.games_ai_tool`。該模組只為外掛之外的程式碼存在 —— 本套件內沒有任何模組 import 它，因此它不進入門前的匯入鏈 —— 舊路徑的契約由測試鎖定：`tests/test_compat_modules.py` 管所有舊路徑的共同部分（暴露的集合與真實模組的公開表面完全一致、同一批物件、本套件內無人 import 舊路徑），`tests/test_tool_compat.py` 再加登錄表這一半 —— 一個舊式 `tools.py` 真能載入並註冊進同一個登錄表。私有名字刻意不再匯出，取 handler 的公開途徑是 `get_tool_handler`。
- **另外兩條 0.8.0 之前的匯入路徑也恢復了**：熱重載文件的 `register_self()` 範例匯入的是 `games_ai.register_extra_plugin`，技能文件的 `register_skills()` 範例匯入的是 `games_ai.external_skills_loader`；模組搬進 `ai/` 之後，照那些頁面寫的外掛會在自己的 `on_load` 裡直接 `ModuleNotFoundError`。現在兩條扁平路徑都是相容模組，再匯出真實模組的公開名字 —— 同一批物件，所以從舊路徑註冊自己或注入技能的外掛，落進的正是外掛讀取的那一份重載列表 / 技能清單 —— 而文件繼續把新路徑作為新程式碼的寫法，並註明舊路徑仍然可用。與 `games_ai/games_ai_tool.py` 一樣，本套件內沒有任何模組 import 它們（不進入門前的匯入鏈），且 `tests/test_compat_modules.py` 鎖定契約：公開表面完全一致、同一批物件、舊式熱重載註冊與舊式技能注入都落進共享狀態、本套件內無人 import 舊路徑。

### 📦 依賴自動安裝

- **入口模組不需要第三方套件就能匯入**：檢查與修復都在一個純標準庫模組（`games_ai/core/deps.py`）裡，只有確認什麼都不缺時才匯入第三方。一台什麼都沒裝的機器照樣能載入插件，`on_load` 此時只做一件事：報出缺少的套件、把它們裝上，然後請 MCDR 重新載入插件。
- **兩次嘗試，然後如實回報**：先用本機 pip 設定執行 `pip install <套件>`（不附加任何 index/代理參數），失敗後對仍然缺的套件改用阿里雲 PyPI 鏡像（`https://mirrors.aliyun.com/pypi/simple/`）重試。pip 的每一行輸出都帶 `[deps]` 前綴寫進 MCDR 日誌，裝得慢也能看見進度。
- **只有真的裝好才重載**：套件能被 import 之後才呼叫 `reload_plugin` 重載自己；失敗就印出可直接複製的 `python -m pip install ...` 指令並停下 —— 不重試、不循環，插件保持「已載入但不運作」（無指令、無 bot、無跨伺服器連線）。重載回來的實例會自己確認恢復：`依賴已就緒，插件已恢復正常（...）`。
- **`requirements.txt` 移入套件內**：放在插件根目錄會讓 MCDR 在這段程式碼執行之前就拒絕載入插件。清單仍然隨套件分發（`games_ai/requirements.txt`，在原始碼目錄裡可以直接用 `pip install -r`）；而透過插件倉庫安裝現在同樣依賴這套自我修復，因為 MCDR 只檢查插件根目錄的 `requirements.txt`。
- **最後一次嘗試有記錄**：寫在 `config/games_ai/cache/dependency_install.json`（與上下文視窗表同目錄），用來防止另一個實例同時開第二份 pip，並讓重載後的實例確認已恢復。它不是設定項，也沒有任何地方把它當設定讀。

### ⚠️ 已知問題

- `!!gamesai reload` 屬於 C 類：各實例重載外掛時跨服鏈路本身會斷開，隨後自動重連；這一瞬間正在回傳的輸出可能遺失。
- 叢集指令的輸出不會等待所有實例回齊，先到的先顯示。

### 升級提示

- 設定無需手動修改：舊的 `mineflayer_bot.websocket` 鍵會自動遷移，頂層 `websocket` 區塊由 MCDR 補齊。token 按節點各自簽發（不再有共享口令），兩台實例互連前請先讀 [跨服連線](cross-server.md)。
- **實例名**：`websocket.name` 留空時按實例目錄派生（`<目錄名>-<路徑雜湊前 6 位>`）；想固定叢集裡的名字就明確設定它。
- 連接埠只需在 hub 那台開放。token 明文傳輸（hub 只存 `sha256` 雜湊）；**外掛本身只監聽明文 `ws://`**，跨公網要讓隧道/反向代理提供 TLS（客戶端把 `uri` 指向代理的 `wss://` 即可，`wss://` 只能當客戶端用）。
- **Python 3.12 或更高**：程式碼使用了 PEP 701 的 f-string（在 f-string 運算式裡嵌套同種引號的字串，例如 `f"{server.rtr("games_ai...")}"`），這只有 3.12+ 的剖析器接受。這一點對程式碼來說一直如此；現在 README、測試文件與入口模組頂部的檢查都寫 3.12（原本寫的是 3.11）。模組內部無法給出更友善的提示：解譯器若剖析不了這個檔案，裡面一行程式碼都不會執行。

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
- 時間注入的計數在 `!!ask switch` 清空歷史時歸零（`!!gamesai clear` 直接銷毀物件），**壓縮不歸零** —— 壓縮視為同一段對話的延續；
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

- **🔍 上下文檢視** — 兩條唯讀指令與一次隨需壓縮把上下文管理從「看不見」變成「看得見」：`!!ask context` 查看某段對話的視窗佔用、距離壓縮還剩多少餘量、逐輪規模與快取命中；`!!ask context --all` 按模型彙總全服所有玩家的用量；`!!ask compact` 安排一次對較早歷史的壓縮，在你下次提問時執行。兩條唯讀指令讀取同一份一致的快照，所以輪次執行中檢視是安全的。
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
- 懸停顯示該模型**自這些對話建立以來**的累計：輸入、輸出、合計、快取命中（0.1% 精度，截斷而非四捨五入）、推理 token；它們隨對話一起保存，因此重載或重啟不會歸零；
- **零用量不列出**：沒人持有上下文、也沒有任何消耗的模型不會出現在清單裡；
- 不顯示玩家名，也不設權限限制。

為了讓「壓縮後仍能看到壓縮前的用量」成立，`ChatParam` 新增了四個**永不重置**的累計計數器（`_total_prompt/completion/cached/reasoning_tokens`）：原來只有每輪計數（每輪歸零）與最近一次計數（每次請求覆寫），壓縮一次就把帳抹掉了。**注意：從 0.8.0 起這些累計隨對話一起保存、載入時還原，因此重載或重啟都會保留；只有 0.7.2 之前（那時計數器還不存在）的呼叫無法追溯。**

### 3. 手動壓縮：`!!ask compact`

- 忽略視窗觸發線，直接壓縮較早的對話：最新的 10 輪原樣保留，歷史不超過這 10 輪時回報「沒有可壓縮的歷史」；
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
- **首次連線退避**：WebSocket 客戶端在首次連上之前使用短間隔（新設定項 `mineflayer_bot.websocket.first_connect_interval`，預設 `0.5` 秒），不再因為 Node 還在啟動就白等一整個 `reconnect_interval`（預設 10 秒）；連上之後仍用設定的間隔（該設定項已在 0.8.0 連同整個 `mineflayer_bot.websocket` 區塊一起移除）。

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
- **🛑 `!!ask stop`** — 一次停止你名下所有正在進行的內容：執行中的對話輪（含工具呼叫）、正在進行的 `!!ask -n` 提問、以及委派給 Bot 的任務。未完成的一步會從歷史中刪除，不會留下寫了一半的對話。（0.8.0 已改變這一行為：該輪會保留它已經寫下的內容，詳見上文 0.8.0 的說明）
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
- **新增遠端表** —— `data/context_windows.json` 在本倉庫維護（**249 條**，涵蓋 19 家廠商與各託管平台，核驗日期 683-09-11；來源與口徑見 [`data/context_windows.sources.md`](https://github.com/PengZixuan30/Games_AI/blob/main/data/context_windows.sources.md)）。插件在啟動時與 24 小時更新檢查時取得，並快取到 `config/games_ai/cache/context_windows.json`；`!!gamesai check` 會無視 24 小時 TTL 強制刷新。維護者可編輯該 JSON 後執行 `python tools/build_context_table.py` 重新同步內建表並校驗。
- **刷新鏈路合併為一條** —— 視窗表刷新與啟動 / 24 小時更新檢查共用同一條執行緒，不再另外多起一條；並發刷新也不會重複下載兩次表。

### 5. 其他改進

- `response_chat` 新增單次請求 `timeout`，並回傳 `(message, usage)`；
- 新增 `context_table` 模組：表匹配、校驗、快取與靜默離線備援；版本內建表改放在生成式模組 `games_ai/ai/context_table_data.py`（每條一行），不再內聯在邏輯模組裡；
- **內建工具的文字已全部英文化** —— 26 個內建工具的 `description` 與參數說明，**以及回傳給模型的工具回傳值**（執行結果、錯誤與權限提示）均為英文，函式呼叫提示詞不再混用中英；只有發給玩家的提示仍保持在地化；
- **`modify_skills` 與 `modify_custom_tools` 改為編輯而非整體重寫** —— 兩者都接收 `old_string`（Python 正規表達式）與 `new_string`（支援 `\1` 等反向參照），取代所有匹配而不是覆寫整個檔案。正規表達式無法編譯或匹配不到時退回字面文字取代；完全匹配不到則不寫入任何內容並明確告知模型。`modify_skills` 仍保留可選參數 `summary`，用於同步技能索引；
- `!!gamesai debug` 會輸出視窗、用量、校準係數與每一次壓縮過程；
- **新增 `!!ask stop` 指令** —— 在下一個檢查點中止該玩家執行中的對話輪（進行中的請求無法真正中斷），從歷史中刪除未完成的一步，丟棄 `!!ask -f` 佇列訊息，同時也會停止正在進行的 `!!ask -n` 提問與委派給自治 Bot 的任務（0.8.0 已改變這兩點：被中斷的輪次會保留它的歷史，排隊的 `!!ask -f` 訊息也會被保留並由下一輪合併）。詳見[停止正在進行的對話](ai-request-pipeline.md#停止正在進行的對話)；
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

`games_ai/ai/chat_param.py` 引入 `BasicChatParam` / `ChatParam`：

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
