<div align="center">

# GamesAI for MCDReforged

[English](/README.md)  |  [简体中文](/README.zh-CN.md)  |  繁體中文

[回報問題](https://github.com/PengZixuan30/Games_AI/issues/new)  |  [提供想法](https://github.com/PengZixuan30/Games_AI/discussions/new/choose)  |  [加入Q群](https://qm.qq.com/q/jDQQaUPNmw)

[轉至Fabric版本](https://github.com/PengZixuan30/GamesAI)

</div>

> [!NOTE]
> **GamesAI 插件/模組 QQ 交流群：849544707** — 歡迎加入交流群討論問題、回饋建議，以及分享 prompt、skills、tools 等設定！

> [!NOTE]
> 歡迎使用版本 0.7.2！本次更新帶來了**上下文檢視**：`!!ask context` 可以隨時查看目前對話的視窗佔用、距離壓縮還剩多少餘量、逐輪規模與快取命中率，`!!ask context --all` 按模型彙總全服所有玩家的用量，`!!ask compact` 可立即壓縮較早的歷史。同時修掉了 `!!ask stop it.` 這類提問被指令節點丟棄、以及並行重載可能關閉假人功能的問題；卸載與熱重載也不再被假人停機拖住。詳見[本次更新](docs/zh_tw/changelog.md#本次更新)。

<details>
<summary>目錄（點擊展開）</summary>

- [GamesAI for MCDReforged](#gamesai-for-mcdreforged)
  - [安裝](#安裝)
  - [使用](#使用)
  - [技術文件](#技術文件)
  - [AI 在本專案中的角色](#ai-在本專案中的角色)
  - [致謝與聲明](#致謝與聲明)
  - [贊助與貢獻者名單](#贊助與貢獻者名單)
  - [授權條款](#授權條款)

</details>

## 安裝

在 MCDR 主控台中使用下列指令以安裝插件：

`!!MCDR plugin install games_ai`

---

或者從 [MCDR 插件倉庫](https://mcdreforged.com/plugin/games_ai) 取得並安裝到你的插件目錄中。

如果選擇手動安裝，請先安裝 Python 套件 `openai`、`requests` 和 `websockets`，使用下列指令安裝：

```bash
pip install openai requests websockets
```

## 使用

在任何地方輸入指令 `!!gamesai` 以顯示此插件的所有功能。

|指令|用途|
|---|---|
|`!!gamesai clear`|清除玩家的歷史聊天記錄，歷史聊天記錄與公共資料庫無關。|
|`!!gamesai clearall`|清除所有玩家的歷史聊天記錄，歷史聊天記錄與公共資料庫無關。|
|`!!gamesai reload`|重新載入插件設定檔。詳見[熱重載](docs/zh_tw/hot-reload.md#熱重載)|
|`!!gamesai check`|檢查插件更新，並強制刷新上下文視窗表。|
|`!!gamesai speedtest [model]`|測試 API 伺服器連線延遲，不指定模型時測試全部。|
|`!!gamesai config get <key>`|讀取一個設定項的值。|
|`!!gamesai config set <key> <value>`|修改一個設定項的值（自動適配舊值型別，修改後自動觸發[熱重載](docs/zh_tw/hot-reload.md#熱重載)）。|

---

你也可以直接輸入 `!!ask` 向 AI 提問、聊天或請它幫你做一些事情。

|指令|用途|
|---|---|
|`!!ask <content>`|向 AI 提問、聊天或請它幫你做一些事情。`<content>` 為你想讓 AI 做的事情或你想問 AI 的問題。|
|`!!ask -n <content>`|向 AI 提問但不使用歷史記錄（當前對話仍會被儲存）。|
|`!!ask -f <content>`|強制提問：不等待目前這輪結束，將訊息併入正在執行的對話輪（別名 `-forced`）。詳見[AI 請求鏈路與對話機制](docs/zh_tw/ai-request-pipeline.md#ai-請求鏈路與對話機制)。|
|`!!ask switch <model>`|切換目前對話使用的 AI 模型，`<model>` 為 AI_ID 或暱稱。切換時清空歷史，並在你下次提問前由舊模型壓縮為摘要轉接給新模型，詳見[切換模型時的摘要轉接](docs/zh_tw/ai-request-pipeline.md#切換模型時的摘要轉接)。|
|`!!ask stop`|立即停止你名下所有正在進行的對話：執行中的對話輪（含工具呼叫）、正在進行的 `!!ask -n` 提問、以及你委派給 Bot 的任務。未完成的一步會從歷史中刪除，`!!ask -f` 佇列訊息會被丟棄。詳見[停止正在進行的對話](docs/zh_tw/ai-request-pipeline.md#停止正在進行的對話)。|
|`!!ask context [玩家]`|查看上下文佔用：模型與視窗來源、已用比例、距離壓縮還剩多少餘量、逐輪規模與快取命中。不填玩家即查看自己。詳見[上下文檢視](docs/zh_tw/ai-request-pipeline.md#上下文檢視)。|
|`!!ask context --all`|按模型彙總全服所有玩家的上下文用量（零用量的模型不列出），懸停可看自插件載入以來的累計用量。詳見[上下文檢視](docs/zh_tw/ai-request-pipeline.md#上下文檢視)。|
|`!!ask compact`|立即壓縮較早的歷史（忽略視窗觸發線），由你下次提問前的預檢完成，指令本身不阻塞。詳見[上下文檢視](docs/zh_tw/ai-request-pipeline.md#上下文檢視)。|

---

輸入 `!!data` 取得有關資料庫指令的資訊。

> [!TIP]
> 更新至 0.3.0 及以上版本時會自動新增資料庫。

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
| [設定](docs/zh_tw/configuration.md) | `config.json` 的全部鍵：`prefix`、`permission`、`all_ai`（含 `context_window`）、`default_ai`、`mineflayer_bot` |
| [工具](docs/zh_tw/tools.md) | 26 個內建工具、在 `tools.py` 裡自訂、在自己的插件裡註冊、權限與可見性 |
| [技能](docs/zh_tw/skills.md) | 技能能解決什麼、內建技能、`skills.json`、讓 AI 自己維護、在自己的插件裡註冊 |
| [範例](docs/zh_tw/example.md) | 一台真實伺服器的完整設定：設定、六個技能、44 個自訂工具、一輪實操與踩坑 |
| [Mineflayer Bot](docs/zh_tw/mineflayer-bot.md) | 環境需求、指令、工作原理、支援的操作、Bot 控制工具 |
| [熱重載](docs/zh_tw/hot-reload.md) | 如何觸發重載、重載期間發生了什麼、如何讓自己的插件跟隨重載 |
| [故障排除](docs/zh_tw/troubleshooting.md) | `!!ask` 報錯、Bot 報錯、日誌與除錯 |
| [更新日誌](docs/zh_tw/changelog.md) | 各個已發布版本的更新說明 |

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
