<div align="center">

# 測試

[English](../en_us/testing.md)  |  [简体中文](../zh_cn/testing.md)  |  繁體中文

[返回 README](../../README.zh-TW.md)

</div>

GamesAI 的整套校驗套件就在本倉庫裡：執行器是 pytest，每次改動都要通過它。`tests/` 下的模組會自己拉起所需的對端、hub、節點與資料庫，因此跑測試不需要 Minecraft 伺服器、不需要 MCDR 實例、不需要 API key，也不需要連網。

## 安裝 pytest

測試套件執行在插件自己的解譯器上（Python 3.12 或更高版本）。在這台解譯器裡安裝 pytest：

```bash
python -m pip install pytest
```

測試還會 import 插件本身，因此插件的執行期依賴也要能被同一個解譯器 import：`mcdreforged`、`websockets`、`openai` 與 `requests`。已經在跑插件的機器上這四個都有。

## 執行測試

在倉庫根目錄執行 pytest。根目錄的 `pytest.ini` 設定 `testpaths = tests`，並把倉庫與 `tests/` 放進 `sys.path`，所以測試模組可以直接 `import games_ai` 和 `_helpers`，不必自己拼路徑：

```bash
python -m pytest
```

只改一個方向時，跑單一模組就夠了：

```bash
python -m pytest tests/test_layout.py
```

`-k` 按名字挑選，匹配測試 id 的任意部分：

```bash
python -m pytest -k clear
```

文件檢查器可以單獨跑：

```bash
python -m pytest tests/docs
```

> [!TIP]
> `python -m pytest --collect-only -q` 只列出會被收集的用例、不執行任何測試；`-p no:cacheprovider` 讓 pytest 不往倉庫裡寫 `.pytest_cache/` 目錄。

## 各目錄的職責

|路徑|職責|
|---|---|
|`pytest.ini`|pytest 設定：`testpaths = tests` 讓不帶參數的 `python -m pytest` 收集這個目錄，`pythonpath = . tests` 把倉庫與 `tests/` 放進 `sys.path`。|
|`tests/conftest.py`|所有套件共享的 fixture：給要拉起 hub、節點或協定原型的套件用的 `free_port` 工廠、安靜日誌的預設設定，以及把外掛的倉庫相對路徑（`skills_path`、`data_path`）釘在暫存目錄裡的會話級兜底。|
|`tests/test_*.py`|測試模組：線協議與幀、入網與 token、路由、AI 請求鏈路、更新輪次，以及倉庫自身的佈局。|
|`tests/_helpers/`|共享助手 —— `paths.py`（倉庫路徑）、`pkg.py`（把插件原始碼當文字讀）與 `wait.py`（輪詢代替 sleep）—— 以及三個協定原型 `ws_async.py`、`ws_sync_hub.py`、`ws_sync_node.py`。|
|`tests/docs/`|文件檢查器：編碼與換行符、三語結構一致性、README 一致性與整潔度、README 裡的 JSON 塊。|
|`tests/js/`|假人測試的 Node.js 一側：vendored 的 `ws` 模組副本，`test_bot_js.py` 會把它複製到自己在暫存目錄裡建構的 harness 旁邊。|

## 執行測試需要什麼

- `PATH` 上的 Python 3.12 或更高版本（`python --version`），與插件宣告的下限一致。
- 該解譯器裡裝有 pytest（`python -m pytest --version`）。
- 插件的執行期依賴能被它 import：`mcdreforged`、`websockets`、`openai` 與 `requests`。
- 只有 JavaScript 假人測試需要 `PATH` 裡有 Node.js：`tests/test_bot_js.py` 會啟動真實的 `node` 行程，其餘模組沒有它也能跑。
- 本機空閒的 TCP 埠：要起 hub 或節點的套件會向系統申請一個 `127.0.0.1` 上的埠。

## 執行測試不需要什麼

- 不需要 Minecraft 伺服器，也不需要執行中的 MCDR 實例：對端都在行程內啟動。
- 不需要 API key，也不需要 AI 服務商：請求鏈路跑在樁上，什麼都不會發出去。
- 不需要 Minecraft 帳號：假人測試把 Minecraft 一側打樁，只用 JavaScript 說 hub 協定。
- 不需要連網：套件本身不下載任何東西，依賴要麼已安裝、要麼已 vendored（`tests/js/` 下的 `ws` 模組）。插件自己的背景刷新（上下文視窗表與更新檢查）在會啟動跨服鏈路的套件裡仍可能發出一次請求；離線時它會失敗、被記入日誌且不改變任何結果，也沒有任何檢查依賴它。

## 測試不會往倉庫裡寫檔案

套件把自己的狀態放在倉庫之外：

- 插件設定、資料庫、節點表與快取檔案都建在作業系統的暫存目錄（或 pytest 自己的 `tmp_path`）裡，跑完不留測試資料。
- `tests/js/node_modules/` 下 vendored 的 `ws` 模組屬於倉庫，只會被讀取。
- 執行留下的痕跡只有 Python 的 `__pycache__/` 目錄；`-p no:cacheprovider` 還能讓 pytest 的 `.pytest_cache/` 也不進倉庫。
