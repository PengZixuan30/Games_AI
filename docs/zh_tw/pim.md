<div align="center">

# PIM：插件自己的安裝管理器

[English](../en_us/pim.md)  |  [简体中文](../zh_cn/pim.md)  |  繁體中文

[返回 README](../../README.zh-TW.md)

</div>

這裡的 **PIM** 指 *Plugin Install Manager*（插件安裝管理器）：GamesAI 用來維護自己的兩套機制 —— **更新器**（下載新的 `.mcdr` 並替換插件自己的檔案）與 **Python 套件管理器**（安裝插件需要的套件）。兩者都沒有設定項、都不問使用者任何問題，而且最後都會讓插件重新載入自己。

第一次安裝插件仍然是 `!!MCDR plugin install games_ai`（其他辦法都失敗時，手動更新也用它）；它**不再**用於更新插件本身 —— 見下。

本頁是總述；每種失敗訊息的細節留在各自文件裡：[troubleshooting.md](troubleshooting.md)（`外掛更新`、`缺少 Python 依賴套件`）、[cross-server.md](cross-server.md)（叢集輪次）與 [configuration.md](configuration.md)（設定項）。

## 更新器

- **產物從哪來**：插件自己的 GitHub release（`https://github.com/PengZixuan30/Games_AI/releases/download/...`）。插件倉庫中介資料裡公告了版本、檔案大小與 `sha256`；只有這個 URL 前綴下的產物會被安裝。第二來源是同一個 URL 走 `ghfast.top` 鏡像 —— 每個來源各兩次嘗試、合計四次，每次 15 秒逾時、總計 300 秒預算。
- **替換之前校驗什麼**：公告的檔案大小、下載內容的 `sha256`，以及**封存檔內部的插件 id 與版本**（封存檔裡的 `mcdreforged.plugin.json`）。下載的必須是一個有效的 zip，其 `mcdreforged.plugin.json` 必須帶上公告的 id 與版本，公告的大小必須在 MCDR 的 100 MiB 上限內；正在執行的實例本身必須是打包的 `.mcdr` / `.pyz` —— 原始碼目錄形式的安裝無法替換自己。任何一項不符都會結束這一輪並給出原因，磁碟上什麼都不動。
- **替換過程**：一切可能失敗的步驟（中介資料、下載、校驗、磁碟空間、目錄可寫）都在**插件仍然載入著**的時候做完。然後 MCDR 卸載插件（藉此放開對封存檔的佔用），重試刪除舊檔案（Windows 可能仍然報「檔案被佔用」），把校驗過的檔案移動到**同一個路徑**（這樣 MCDR 對本插件 id 只會保留一個檔案），再重新載入插件；隨後核對 MCDR 報出的版本，新檔案起不來時還原並載入舊檔案。卸載之後的任何失敗路徑都以一次載入收尾，因此伺服器不會在「沒有 GamesAI」的狀態下繼續跑。
- **什麼時候跑**：24 小時更新檢查（載入時啟動）、`!!gamesai check`（隨時），以及叢集裡的協調輪次。叢集中由 **hub** 決定並先命令節點：等到每台節點都 `staged` **並且**以新版本重連回來，最後才替換自己的檔案。跨服**客戶端**從不自己檢查、也不自己安裝；在客戶端上敲 `!!gamesai check` 會由 hub 執行。local 模式下實例獨自更新。迴圈（載入時那次與每 24 小時那次）是安靜的：只有真的**發現新版本**時才播報（以及接著安裝它的那一輪），「正在檢查更新」與「沒有新版本」只寫進除錯日誌（`!!gamesai debug` 可見），不會為一個沒人要求的檢查打擾玩家；`!!gamesai check` 仍然會把這兩行回給輸入指令的人。
- **刻意不做的事**：不退回 MCDR 安裝器。某一步失敗就結束這一輪並記錄原因（下載不到、大小或雜湊不符、檔案被鎖、新檔案沒載入起來已回滾）。要手動安裝就用 `!!MCDR plugin install -U -y games_ai`，或者再跑一次 `!!gamesai check`。
- **做不到的情況**：以**原始碼目錄**形式執行的實例無法替換自己 —— 日誌會說明，只能手動更新（見 [cross-server.md](cross-server.md#叢集更新)）。

## Python 套件管理器

- **管什麼**：`games_ai/requirements.txt` 裡列的三個套件 —— `openai`、`requests`、`websockets`。
- **為什麼插件能自我修復**：它的入口模組**不需要**這些套件就能匯入（第三方匯入都在門控之後）。一台什麼都沒裝的機器照樣能載入插件，`on_load` 此時只做一件事：報出缺什麼、把它裝上，然後請 MCDR 重新載入插件。
- **兩次嘗試**：第一次用本機 pip 設定執行 `python -m pip install --disable-pip-version-check <套件>` —— 不附加任何 index/代理參數，因此 `pip.ini`、`PIP_INDEX_URL` 與代理照常生效；失敗後第二次對**仍然缺**的套件改用阿里雲 PyPI 鏡像（`https://mirrors.aliyun.com/pypi/simple/`）重試。會傳 `--disable-pip-version-check`，**從不**傳 `--upgrade` —— Windows 上已經 import 過的套件的 `.pyd` 無法替換。pip 的每一行輸出都帶 `[deps]` 前綴寫進 MCDR 日誌，裝得慢也能看見進度。
- **裝好之後**：再校驗一次（必須真的能 import）、寫入本次嘗試的記錄，然後插件用 `reload_plugin` 重載自己。重載回來的實例會在日誌裡確認：`依賴已就緒，插件已恢復正常（...）`。
- **兩次都失敗時**：日誌會印出 `依賴安裝失敗：...` 與可直接複製的指令 —— `python -m pip install openai requests websockets`，然後 `!!MCDR plugin reload games_ai`。在此之前插件「已載入但不運作」：不註冊指令、不啟動 bot、也不建跨伺服器連線。不會循環重試；下一次啟動（或手動重載插件）會再試。
- **清單為什麼放在套件內**：MCDR 會在匯入插件**之前**檢查**插件根目錄**的 `requirements.txt`，缺套件就直接拒絕載入 —— 那樣插件就永遠沒有機會自我修復。`games_ai/requirements.txt` 隨套件分發（原始碼目錄裡可以直接餵給 `pip install -r`）。透過插件倉庫安裝同樣受影響：宣告的套件清單來自插件根目錄的 `requirements.txt`，而這個版本已經不再附帶它，所以 `!!MCDR plugin install games_ai` 也不會安裝任何套件，插件會在第一次啟動時自行修復（首次安裝指令仍然可用，只是不再預裝任何東西）。
- **記錄檔**：`config/games_ai/cache/dependency_install.json`（與上下文視窗表同目錄）保存最後一次嘗試 —— 狀態、套件名、`local` 還是 `mirror`、以及 pip 輸出的尾端。它不是設定項，也沒有任何地方把它當設定讀：它用來防止另一個實例同時開第二份 pip，並讓重載後的實例確認已恢復。
- **沒有開關、沒有指令**：修自己的依賴是插件自己的事，所以既沒有可設定項，也沒有要敲的指令。

## 每台機器、每個實例

- **更新器**是叢集感知的：一輪更新，由 hub 排序，各實例替換自己的檔案。
- **依賴修復**是按機器、按實例進行的：每個實例只為**它自己的** Python 解譯器安裝缺的套件。兩台機器上的兩個實例各自修復，而依賴齊全的實例什麼都不做 —— 載入時共有兩輪、每輪三次 `find_spec` 與三次中介資料查詢。

## 相關文件

- [troubleshooting.md](troubleshooting.md) —— 具體日誌行與對應處理。
- [cross-server.md](cross-server.md) —— 叢集更新輪次、入網與角色。
- [configuration.md](configuration.md) —— `websocket` 設定區塊與更新相關設定。
- [hot-reload.md](hot-reload.md) —— `!!gamesai reload`：重載的是設定，不是插件檔案。
