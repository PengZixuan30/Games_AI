<div align="center">

# 架構

[English](../en_us/architecture.md)  |  [简体中文](../zh_cn/architecture.md)  |  繁體中文

[返回 README](../../README.zh-TW.md)

</div>

外掛是一個 Python 套件 `games_ai/`，套件內的模組按職責分組。本頁是它的地圖：哪個套件負責什麼、各部分之間允許怎樣依賴、新模組該放在哪裡。

## 套件的結構

```text
games_ai/
  __init__.py     入口：中介資料、MCDR 生命週期、裝配、!!ask 鏈路
  requirements.txt
  core/           設定、日誌、依賴閘、權限、儲存
  commands/       !!data、!!gamesai config、!!aibot、!!gamesai clear、!!gamesai node 背後的處理函式
  cluster/        跨服鏈路：角色決定、hub、節點客戶端、遠端指令來源
  ai/             請求鏈路：會話、服務商客戶端、上下文視窗表、工具、技能
  bot/            Mineflayer 假人：行程、控制器、內嵌 init.js
  update/         自更新與驅動它的 24 小時輪次
  ui/             遊戲內說明文字
```

這些目錄裡各有一個 `__init__.py`，也就是該套件的門面：它轉出外掛其它部分從該套件引用的模組與名字，入口模組因此不必知道某個名字住在哪個檔案裡。需要第三方套件的模組裡的名字用 `__getattr__` 首次存取時才匯入（這樣早早 import 一個套件仍然不碰第三方），同時在 `if TYPE_CHECKING:` 區塊裡再宣告一次 —— 那個區塊永不執行，但編輯器與型別檢查器讀的就是它，因此 `from .ai import ChatParam` 拿到的是真實簽名而不是 `Any`。

套件根目錄在入口模組旁邊保留了一個相容模組：`games_ai_tool.py` 以子套件出現之前的舊路徑再匯出工具登錄表，因為既有的 `config/games_ai/tools/tools.py` 與其他外掛匯入的就是它。它只為外掛之外的程式碼存在 —— 本套件內沒有任何模組 import 它 —— 新程式碼請用 `ai/games_ai_tool.py`（見[工具](tools.md)，契約由 `tests/test_tool_compat.py` 鎖定）。

## 各套件的職責

|路徑|職責|
|---|---|
|`core/`|`clock.py`（AI 被告知的那個時鐘：時區判定、時間戳與時長）、`config.py`（`plugin_config` 單例）、`logger.py`（日誌橋）、`deps.py`（依賴閘與 pip 修復）、`permission.py`（唯一的權限規則）與 `database.py`（公開資料庫與歷史儲存）。|
|`commands/`|每個指令組一個模組：`data.py`、`settings.py`、`aibot.py`、`clear.py` 與 `node.py`。它們只負責回覆呼叫者；需要的入口狀態由一次 `attach()` 呼叫注入。|
|`cluster/`|`cross_server.py`（角色決定與管理器）、`websockets_server.py`（hub）、`websockets_client.py`（節點客戶端與握手探測）與 `ws_command.py`（遠端指令來源與會話註冊表）。|
|`ai/`|`chat_param.py`（會話與請求鏈路）、`openai_api.py`（服務商客戶端）、`context_table.py` 及其生成的 `context_table_data.py`、`games_ai_tool.py`（工具登錄表）、`tools_interpreter.py`、`external_skills_loader.py` 與 `register_extra_plugin.py`；`tools_stub_files.py` 負責在使用者的工具目錄裡播種（`tools.py` 骨架，以及複製到它旁邊的生成式 `_stubs/` 存根樹，見[工具](tools.md)）。|
|`bot/`|`mineflayer.py`（Node 行程）、`mineflayer_ai.py`（自主控制器）與 `mineflayer_service_files.py`（內嵌的 `init.js`、`package.json` 及其寫入函式）。|
|`update/`|`updater.py`（下載、校驗並替換外掛自身檔案）與 `update_round.py`（24 小時檢查與叢集協同輪次）。|
|`ui/`|`help.py`：遊戲內說明文字與它的 `send_help` 建構器。|

## 各部分如何依賴

- 入口模組可以 import 任何套件；**任何套件都不得 import 入口模組** —— 違反時 `tests/test_layout.py` 會失敗。
- `core/` 是地基：其它套件都可以 import 它，而它只 import 標準庫與 MCDR。
- 依賴閘優先：在什麼都沒裝的機器上 import `games_ai` 也必須成功。入口模組從各套件的**門面**（`__init__.py`）取名：門面把不需要第三方的名字 eager 匯入，其餘首次存取時才匯入（PEP 562），因此早早 import 一個套件也不會把第三方套件拖上門前的匯入鏈。

## 新模組放在哪裡

- 按「它回答什麼問題」選套件，而不是按「誰呼叫它」：叢集傳輸放 `cluster/`，面向模型的程式碼放 `ai/`，假人程式碼放 `bot/`，玩家能輸入的指令處理函式放 `commands/`，玩家讀到的文字放 `ui/`，各處共用的東西放 `core/`。
- 需要第三方套件的模組必須在依賴閘之後匯入，因此除了 `core/` 之外哪裡都可以：`core/` 要保持「什麼都沒裝的機器也能 import」。
- 把新檔案加進 `tests/test_layout.py` 的 `KNOWN_MODULES`；若別處要用它的名字，就加進所屬套件的 `__init__.py` —— 該模組不需要第三方就 eager 匯出，需要就寫進 `_LAZY_NAMES`。該套件還會檢查匯入圖保持無環、每個門面的 `__all__` 可解析、門面的 eager 匯入門前安全、入口不越過門面直接引用模組，以及門前閉包不拉入任何第三方套件。
- 新增、改名或刪除模組都會讓隨外掛發布的編輯器存根過期：用 `python tools/build_tool_stubs.py` 重新產生（需要 `mypy` 的 `stubgen`；產生的樹會提交進倉庫，`--check` 只校驗不寫入）。在存根與原始碼重新一致之前，`tests/test_tool_stubs.py` 會失敗。

## 入口模組保留什麼

- MCDR 中介資料與生命週期：`PLUGIN_METADATA`、`on_load`、`on_unload`、`on_server_startup` 與 `_deps_*` 修復路徑。
- 裝配：把設定寫進 `plugin_config`、指令樹、跨服鏈路的啟動與停止、身份檔案、假人堆疊，以及把入口的即時狀態交給需要它的模組的那些 `attach()` 呼叫。
- `!!ask` 鏈路本身（`ask_ai` 與它的分發器）——唯一仍留在入口模組裡的指令組。
