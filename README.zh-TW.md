<div align="center">

# GamesAI for MCDReforged

[English](/README.md)  |  [简体中文](/README.zh-CN.md)  |  繁體中文

[回報問題](https://github.com/PengZixuan30/Games_AI/issues/new)  |  [提供想法](https://github.com/PengZixuan30/Games_AI/discussions/new/choose)  |  [加入Q群](https://qm.qq.com/q/jDQQaUPNmw)

[轉至Fabric版本](https://github.com/PengZixuan30/GamesAI)

</div>

> [!NOTE]
> **GamesAI 插件/模組 QQ 交流群：849544707** — 歡迎加入交流群討論問題、回饋建議，以及分享 prompt、skills、tools 等設定！

> [!NOTE]
> 歡迎使用版本 0.8.0！本次加入**跨服連線**：多個 MCDR 實例透過 WebSocket 組成一個叢集，其中一台成為 hub，承載 AI、對話歷史與公共資料庫，其餘實例以客戶端接入、轉發玩家的指令（叢集級指令由它們自己執行）；工具仍留在各實例本地 —— 每個請求都攜帶發起實例本地的工具 schema；假人（Mineflayer bot）也從「自己監聽連接埠」改為接入叢集的客戶端。詳見[跨服連線文件](docs/zh_tw/cross-server.md)。每條對話也會**落盤**（存在與 `!!data` 同一個資料庫檔案的 `chat_history` 表裡），重載、更新、重啟乃至移除外掛都不會再遺失；新增的 `send_message_to_player_ai` 工具還能讓目前使用者的助手把一則訊息轉交給另一個使用者的對話。最新的改動讓 `!!ask stop` 保留本輪已寫入的歷史，並新增依名字清理歷史的 `!!gamesai clear <name>`。

<details>
<summary>目錄（點擊展開）</summary>

- [GamesAI for MCDReforged](#gamesai-for-mcdreforged)
  - [安裝](#安裝)
  - [快速上手](#快速上手)
    - [1. 首次啟動：讓外掛自己把依賴裝好](#1-首次啟動讓外掛自己把依賴裝好)
    - [2. 設定一個 AI](#2-設定一個-ai)
    - [3. 驗證連通並問出第一句話](#3-驗證連通並問出第一句話)
    - [4. 對話存在哪裡（以及怎麼清理）](#4-對話存在哪裡以及怎麼清理)
    - [5. 給 AI 加能力：工具與技能（可選）](#5-給-ai-加能力工具與技能可選)
    - [6. 讓 AI 開一個假人（可選）](#6-讓-ai-開一個假人可選)
    - [7. 把多台實例連成叢集（可選）](#7-把多台實例連成叢集可選)
    - [8. 日常維護](#8-日常維護)
    - [指令速查](#指令速查)
  - [技術文件](#技術文件)
  - [AI 在本專案中的角色](#ai-在本專案中的角色)
  - [致謝與聲明](#致謝與聲明)
  - [贊助與貢獻者名單](#贊助與貢獻者名單)
  - [授權條款](#授權條款)

</details>

## 安裝

在 MCDR 主控台中使用下列指令以安裝插件：

`!!MCDR plugin install games_ai`

環境需求：Python 3.12 或更高、MCDReforged 2.15.0 或更高（清單宣告 `mcdreforged >= 2.15.0`；外掛執行在 MCDR 自己的直譯器上）。僅在啟用 Mineflayer 假人時才需要 Node.js 18+ 與 npm。

---

或者從 [MCDR 插件倉庫](https://mcdreforged.com/plugin/games_ai) 取得並安裝到你的插件目錄中。

如果選擇手動安裝：插件的 Python 套件由它自己處理 —— 首次啟動時檢查 `openai`、`requests`、`websockets`，缺哪個就用 pip 補裝（先用本機 pip 設定，失敗了再改用阿里雲 PyPI 鏡像重試），裝好之後自動重載插件。只有兩次都失敗時才需要你介入，日誌裡會給出可直接複製的指令（`python -m pip` 形式）：

```bash
python -m pip install openai requests websockets
```

`!!MCDR plugin install games_ai` 也無法預先安裝任何東西：套件清單位於外掛內部（`games_ai/requirements.txt`），而 MCDR 只讀取外掛根目錄下的 `requirements.txt`，然後才載入外掛。因此哪種安裝方式一開始都缺這些套件，外掛會在首次啟動時自行補裝（見 [PIM](docs/zh_tw/pim.md)）；只有兩次 pip 嘗試都失敗時，才用上面的手動指令，裝完後執行 `!!MCDR plugin reload games_ai` 讓外掛重新載入。

從舊版本升級無需手動改設定：舊的 `mineflayer_bot.websocket.url` 會在首次載入時遷移為頂層的 `websocket.uri`。叢集中，執行舊版本的節點無法聽從 hub 的更新順序，所以要在每個實例上手動安裝一次新版本（`!!MCDR plugin install -U -y games_ai`）。只有 hub 需要有可被存取的連接埠，而 `wss://` 的 uri 只能作為客戶端。

插件會自己維護自己：更新器會替換插件自己的檔案（叢集感知、下載校驗、失敗回滾），Python 套件管理器會補裝缺少的套件。兩者見 [PIM：插件自己的安裝管理器](docs/zh_tw/pim.md)。

## 快速上手

### 1. 首次啟動：讓外掛自己把依賴裝好

把外掛放進 `plugins/`，啟動伺服器（已經裝過時執行 `!!MCDR plugin reload games_ai` 即可）。首次啟動時它會檢查三個 Python 套件（`openai`、`requests`、`websockets`），缺哪個就用 pip 補裝 —— 先用本機 pip 設定，失敗後改用阿里雲 PyPI 鏡像重試 —— 然後重載自己：

```text
Installing the missing Python package(s) with pip: ...
[deps] ...
Dependencies installed; reloading the plugin...
Dependencies are ready; the plugin is fully loaded again (openai, requests, websockets)
```

這期間外掛處於「已載入但不運作」狀態：不註冊指令、不啟動假人，也不建立跨服連線。兩次嘗試都失敗時，日誌會印出 `Could not install: ...` 以及需要手動執行的指令（`python -m pip install openai requests websockets`）；執行它，再 `!!MCDR plugin reload games_ai`。詳見 [PIM：Python 套件管理器](docs/zh_tw/pim.md#python-套件管理器)與[缺少 Python 依賴套件](docs/zh_tw/troubleshooting.md#缺少-python-依賴套件)。

### 2. 設定一個 AI

打開 `config/games_ai/config.json`（首次啟動時自動產生），填好一個 `all_ai` 條目和 `default_ai`：

```json
{
  "all_ai": {
    "<你的 AI ID>": {
      "prompt": "你是一个成熟可靠的 Minecraft 助手。",
      "ai_name": "[GamesAI]",
      "base_url": "<你的 API Base URL>",
      "ai_model": "<你的 AI 模型>",
      "api_key": "<你的 API Key>",
      "extra_body": {}
    }
  },
  "default_ai": "<你的 AI ID>"
}
```

- `all_ai` 裡每個條目是一個模型，條目的鍵就是外掛的內部 AI_ID。
- `base_url`、`ai_model`、`api_key` 分別是服務商的 OpenAI 相容介面位址、模型名與金鑰。
- `ai_name` 是 AI 回覆時使用的前綴（支援 Minecraft 格式碼）。
- `extra_body` 會原樣傳給服務商 —— 例如思考模型可以寫 `{"thinking": {"type": "enabled"}}`。
- `default_ai` 必須正好等於 `all_ai` 裡的某個鍵：它就是直接 `!!ask` 時使用的模型。
- 可選的 `context_window` 用來覆蓋該模型的[上下文自動管理](docs/zh_tw/ai-request-pipeline.md#上下文自動管理)視窗。

提示詞很長時不必寫進設定檔：把 `prompt` 寫成 `"> my_prompt.md"`，正文會從 `config/games_ai/prompt/my_prompt.md` 讀取。

改完執行 `!!gamesai reload`。`!!gamesai config get <key>` 與 `!!gamesai config set <key> <value>` 可以處理頂層簡單鍵，但 `config set` 會拒絕複雜的 `all_ai` 與 `mineflayer_bot` 區塊，也不會解析帶點的鍵，這兩塊請在檔案裡改。全部鍵的含義見[設定](docs/zh_tw/configuration.md#3all_ai)。

### 3. 驗證連通並問出第一句話

`!!gamesai speedtest` 會向每個模型的 `<base_url>/models` 發一次請求並印出延遲（`!!gamesai speedtest <model>` 只測一個）。然後直接和它說話：

```text
!!ask 你好，你在嗎？
```

`!!ask` 對所有玩家開放。圍繞它的還有：`!!ask -n <content>` 不帶歷史回答，`!!ask -f <content>`（別名 `--forced`）把問題併入正在執行的那一輪，`!!ask switch <model>` 把對話交給另一個模型（舊模型先做摘要轉接），`!!ask stop` 停掉你名下所有在途工作並**保留本輪已經寫入的內容**，`!!ask context [玩家]` / `!!ask context --all` 查看上下文佔用。詳見 [AI 請求鏈路](docs/zh_tw/ai-request-pipeline.md#上下文檢視)與[停止正在進行的對話](docs/zh_tw/ai-request-pipeline.md#停止正在進行的對話)。

### 4. 對話存在哪裡（以及怎麼清理）

每條對話都會在每輪結束後寫入 `config/games_ai/database/public_database.db` 的 `chat_history` 表（與 `!!data` 同一個檔案、不同的表），並在每次外掛載入時恢復。因此重載、更新、重啟乃至移除外掛都不會再遺失。

`!!gamesai clear` 刪除你自己的對話；`!!gamesai clear <name>` 刪除指定玩家的對話（需要設定的 `permission` 等級，會先停掉對方正在跑的那一輪）；`!!gamesai clearall` 刪除所有人的（同樣需要權限）。詳見[對話持久化](docs/zh_tw/ai-request-pipeline.md#對話持久化)。

### 5. 給 AI 加能力：工具與技能（可選）

外掛自帶 27 個內建工具（世界查詢、公共資料、技能、假人）。一次請求能拿到哪些工具，取決於玩家的 MCDR 權限等級與設定裡的 `permission` —— 低等級玩家根本看不到管理類工具。

- **自訂工具**：首次啟動會產生 `config/games_ai/tools/tools.py`，裡面帶一個 `@register_tool` 骨架；把你的函式寫進去，然後 `!!gamesai reload`。詳見[工具](docs/zh_tw/tools.md#2-在-toolspy-中自訂工具)。
- **技能**：`config/games_ai/skills/skills.json` 是技能索引，AI 透過 `read_skills` 讀取其中列出的檔案，也可以自己寫和維護。詳見[技能](docs/zh_tw/skills.md#3-加入自己的技能)。

### 6. 讓 AI 開一個假人（可選）

伺服器上需要安裝 Node.js 18+ 與 npm。然後設定憑證並啟動：

```text
!!aibot set username <Minecraft 帳號名>
!!aibot set password <密碼>
!!aibot set auth microsoft
!!aibot join
```

`!!aibot leave` 再次停掉它。`config.json` 裡對應的設定是 `mineflayer_bot` 下的 `enabled`、`cycle_interval`（自治控制器多久決策一次，預設 15 秒）與 `bot.username` / `bot.password` / `bot.auth`（`microsoft`、`mojang` 或 `offline`）。假人作為客戶端接入叢集，自己不開連接埠；伺服器位址從 `server.properties` 讀取。`username`/`password`/`auth` 只在 Node 程序（重）啟動時讀取，所以改完要用 `!!aibot set` 並重啟（`!!aibot leave`，再 `!!aibot join`）；`!!gamesai config set` 會拒絕整個 `mineflayer_bot` 區塊。詳見 [Mineflayer 假人](docs/zh_tw/mineflayer-bot.md#指令)。

### 7. 把多台實例連成叢集（可選）

其中一台成為 **hub**（擁有 AI、對話歷史與公共資料庫），其餘實例作為**客戶端**接入並轉發玩家的指令；工具仍各實例自帶。在每台實例 `config.json` 的 `websocket` 區塊裡指向 hub：

```json
{
  "websocket": {
    "uri": "ws://<hub 位址>:8080",
    "force_server": false,
    "name": ""
  }
}
```

在該位址上探測到 GamesAI hub 的實例會成為客戶端；什麼都沒探測到（且自己綁得住該位址）的實例會當 hub，`force_server` 則強制當 hub。入網按節點進行：在 hub 上用 `!!gamesai node pending` 看等待名單，`!!gamesai node token <name>` 簽發 token，目標實例自己用 `!!gamesai node claim <token>` 入網。`websocket.name` 留空時由實例目錄派生。叢集更新由 hub 排序 —— 先節點、後 hub。其餘鍵（`allow_app_id`、`token_ttl_hours`、`auto_enroll`、`identity_file`）見[設定 §6](docs/zh_tw/configuration.md#6websocket)；完整說明見[跨服連線](docs/zh_tw/cross-server.md#註冊每個實例一份-token)與[叢集更新](docs/zh_tw/cross-server.md#叢集更新)。

### 8. 日常維護

- `!!gamesai reload` 重新讀取設定、技能與工具，必要時重啟假人；跨服鏈路繼續執行。`websocket.*` 的改動要用 `!!MCDR plugin reload games_ai`（或 `!!gamesai node claim` / `node forget`，它們會重建鏈路），因為鏈路是在載入時建立的。詳見[熱重載](docs/zh_tw/hot-reload.md#觸發熱重載)。
- `!!gamesai check` 檢查是否有新版本，並刷新上下文視窗表；叢集裡由 hub 協調。外掛會更新自己的檔案（下載校驗、失敗回滾）並自我修復 Python 套件 —— 見 [PIM](docs/zh_tw/pim.md)。
- `!!gamesai debug` 切換完整請求日誌；`!!gamesai debug thread` 列出外掛持有的執行緒。
- `!!data` 管理 AI 可讀的公共鍵值資料庫。
- 出問題了？看[故障排除](docs/zh_tw/troubleshooting.md)，裡面按日誌行給出處理辦法。

---

### 指令速查

輸入 `!!gamesai` 可查看遊戲內功能清單（`!!gamesai node …` 用於叢集註冊，`!!aibot …` 用於假人）；下表列出的是最常用的指令。

|指令|用途|
|---|---|
|`!!gamesai clear`|清除你自己的歷史聊天記錄。它存放在公共資料庫檔案的獨立資料表中，該指令會刪除你那一列。`!!gamesai clear <name>` 改為清除另一位玩家的歷史記錄，需要達到設定中的 `permission` 等級；該玩家還在執行的對話輪會先被停止。|
|`!!gamesai clearall`|清除所有玩家的歷史聊天記錄（包括已儲存的列）。|
|`!!gamesai reload`|重新載入設定、技能與工具並重啟 Bot；跨服鏈路會繼續執行。詳見[熱重載](docs/zh_tw/hot-reload.md#熱重載)。|
|`!!gamesai check`|檢查插件更新，並強制刷新上下文視窗表。叢集裡由 hub 執行並發起一輪更新：節點先裝、hub 最後裝（見[跨服連線](docs/zh_tw/cross-server.md#叢集更新)）。|
|`!!gamesai speedtest [model]`|測試 API 伺服器連線延遲，不指定模型時測試全部。|
|`!!gamesai config get <key>`|讀取一個設定項的值。|
|`!!gamesai config set <key> <value>`|修改一個設定項的值（自動適配舊值型別，修改後自動觸發[熱重載](docs/zh_tw/hot-reload.md#熱重載)）。|
|`!!gamesai node <pending\|token\|list\|revoke\|rotate\|claim\|status\|forget>`|叢集註冊與節點管理；見[跨服連線](docs/zh_tw/cross-server.md#註冊每個實例一份-token)。|
|`!!aibot join \| leave`|啟動或停止假人（Mineflayer bot）；`!!aibot set <key> <value>` 可修改假人憑證並重載。見 [Mineflayer Bot](docs/zh_tw/mineflayer-bot.md)。|

---

你也可以直接輸入 `!!ask` 向 AI 提問、聊天或請它幫你做一些事情。

|指令|用途|
|---|---|
|`!!ask <content>`|向 AI 提問、聊天或請它幫你做一些事情。`<content>` 為你想讓 AI 做的事情或你想問 AI 的問題。|
|`!!ask -n <content>`|向 AI 提問但不使用歷史記錄（當前對話仍會被儲存）。|
|`!!ask -f <content>`|強制提問：不等待目前這輪結束，將訊息併入正在執行的對話輪（別名 `--forced`）。詳見[AI 請求鏈路與對話機制](docs/zh_tw/ai-request-pipeline.md#ai-請求鏈路與對話機制)。|
|`!!ask switch <model>`|切換目前對話使用的 AI 模型，`<model>` 為 AI_ID 或暱稱。切換時清空歷史，並在你下次提問前由舊模型壓縮為摘要轉接給新模型，詳見[切換模型時的摘要轉接](docs/zh_tw/ai-request-pipeline.md#切換模型時的摘要轉接)。|
|`!!ask stop`|立即停止你名下所有正在進行的對話：執行中的對話輪（含工具呼叫）、正在進行的 `!!ask -n` 提問、以及你委派給 Bot 的任務。**本輪已經寫入的內容會保留在歷史裡** —— 只有結果始終沒有回來的工具呼叫會被丟棄；`!!ask -f` 佇列訊息會保留，由你下一輪合併。詳見[停止正在進行的對話](docs/zh_tw/ai-request-pipeline.md#停止正在進行的對話)。|
|`!!ask context [玩家]`|查看上下文佔用：模型與視窗來源、已用比例、距離壓縮還剩多少餘量、逐輪規模與快取命中。不填玩家即查看自己。詳見[上下文檢視](docs/zh_tw/ai-request-pipeline.md#上下文檢視)。|
|`!!ask context --all`|按模型彙總全服所有玩家的上下文用量（零用量的模型不列出），懸停可看該模型自這些對話建立以來的累計用量（重載與重啟都不會遺失）。詳見[上下文檢視](docs/zh_tw/ai-request-pipeline.md#上下文檢視)。|
|`!!ask compact`|立即壓縮較早的歷史（忽略視窗觸發線），由你下次提問前的預檢完成，指令本身不阻塞。詳見[上下文檢視](docs/zh_tw/ai-request-pipeline.md#上下文檢視)。|

---

輸入 `!!data` 取得有關資料庫指令的資訊。

> [!TIP]
> 資料庫會在首次啟動時自動建立，無需額外的升級步驟。

|指令|用途|
|---|---|
|`!!data write <key> <value>`|在公共資料庫中新增一筆資料，其中 `<key>` 不可包含空格，`<value>` 可為任意字串。|
|`!!data add <key> <value>`|將 `<value>` 追加到公共資料庫中的 `<key>`，不存在時自動建立新 key。|
|`!!data del <key>`|在公共資料庫中刪除一筆資料，無論 key 是否存在。|
|`!!data read <key>`|讀取公共資料庫中 `<key>` 對應的 `<value>`。|
|`!!data list`|讀取公共資料庫中的所有內容。|
|`!!data list keys`|讀取公共資料庫中的所有 key。|

---

## 技術文件

技術細節集中在 [`docs/zh_tw/`](docs/zh_tw/)：請求如何組裝並控制在視窗內、每個設定項的含義、工具與技能系統如何運作、機器人如何被驅動、出問題時怎麼排查。

| 文件 | 內容 |
|---|---|
| [AI 請求鏈路](docs/zh_tw/ai-request-pipeline.md) | 請求鏈路、無歷史 `!!ask -n`、`!!ask switch` 摘要轉接、`!!ask stop`、上下文自動管理、每玩家狀態 |
| [設定](docs/zh_tw/configuration.md) | `config.json` 的全部鍵：`prefix`、`permission`、`all_ai`（含 `context_window`）、`default_ai`、`mineflayer_bot`、`websocket`（`uri`、`force_server`、`allow_app_id`、`name`、`token_ttl_hours`、`auto_enroll`、`identity_file`）以及自我更新行為 |
| [工具](docs/zh_tw/tools.md) | 27 個內建工具、在 `tools.py` 裡自訂、在自己的插件裡註冊、權限與可見性 |
| [技能](docs/zh_tw/skills.md) | 技能能解決什麼、內建技能、`skills.json`、讓 AI 自己維護、在自己的插件裡註冊 |
| [範例](docs/zh_tw/example.md) | 一台真實伺服器的完整設定：設定、六個技能、44 個自訂工具、一輪實操與踩坑 |
| [Mineflayer Bot](docs/zh_tw/mineflayer-bot.md) | 環境需求、指令、工作原理、支援的操作、Bot 控制工具 |
| [熱重載](docs/zh_tw/hot-reload.md) | 如何觸發重載、重載期間發生了什麼、如何讓自己的插件跟隨重載 |
| [跨服連線](docs/zh_tw/cross-server.md) | 叢集角色、每節點註冊、指令路由、叢集更新、工具作用域 |
| [PIM](docs/zh_tw/pim.md) | 外掛自己的安裝管理器：自我更新與 Python 依賴補裝 |
| [故障排除](docs/zh_tw/troubleshooting.md) | `!!ask` 報錯、Bot 報錯、日誌與除錯 |
| [測試](docs/zh_tw/testing.md) | 怎麼裝 pytest、怎麼跑全部/單個模組/按名字挑選用例、`tests/` 各部分的職責，以及跑測試需要什麼 |
| [架構](docs/zh_tw/architecture.md) | 按職責劃分的套件樹、各部分之間允許怎樣依賴、依賴閘，以及新模組該放在哪裡 |
| [更新日誌](docs/zh_tw/changelog.md) | 各版本的更新說明 |

> 相同文件的其他語言版本：[English](docs/en_us/) · [简体中文](docs/zh_cn/)。

---

## AI 在本專案中的角色

GamesAI 本身是 AI 驅動的插件，而 AI 也在本專案自身的維護中扮演重要角色：

1. 本 README 最初由作者（yello）排版，後全部交由 AI 修改；
2. 所有翻譯檔案（`lang/*.yml`）均由 AI 修改；
3. 每次發布前的邏輯檢查由 AI 完成；
4. 快照/開發版本中出現的問題將由 AI 排查；
5. GitHub 回饋的 issue、PR 等將先由 AI 排查問題，再交由維護者處理。

## 致謝與聲明

特別感謝 [WangHai Server](https://github.com/Wanghai-Server) 為此插件的測試提供了基礎。

特別感謝 [william-song-shy (William Song)](https://github.com/william-song-shy) 為 `!!ask` 無歷史模式提供的建議。

特別感謝 [ZhangZuoqian (張作乾)](https://github.com/ZhangZuoqian) 為測速指令提供的建議。

AI（LLM）模型生成的一切內容與此插件無關。

自訂工具造成的一切後果與本插件無關。

## 贊助與貢獻者名單

贊助地址：[愛發電](https://ifdian.net/a/yello)

為GamesAI贊助的將會出現在下列的贊助者名單中（當前沒有贊助者）：

| # | 贊助者 | 金額 | 日期 |
|---|--------|------|------|
| - | - | - | - |

## 授權條款

MIT 授權條款，版權所有 (c) 2026 yello

<div align = "center">

---

[回到頂端](#gamesai-for-mcdreforged)

</div>
