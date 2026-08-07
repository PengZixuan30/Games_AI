<div align="center">

# GamesAI for MCDReforged

[English](/README.md)  |  [简体中文](/README.zh-CN.md)  |  繁體中文

[回報問題](https://github.com/PengZixuan30/Games_AI/issues/new)  |  [提供想法](https://github.com/PengZixuan30/Games_AI/discussions/new/choose)  |  [加入Q群](https://qm.qq.com/q/jDQQaUPNmw)

[轉至Fabric版本](https://github.com/PengZixuan30/GamesAI)

</div>

> [!NOTE]
> **GamesAI 插件/模組 QQ 交流群：849544707** — 歡迎加入交流群討論問題、回饋建議，以及分享 prompt、skills、tools 等設定！

> [!NOTE]
> 歡迎使用版本 0.6.1！本次更新引入了 **擴展插件系統**——為 MCDR 插件開發者提供 `register_self()` 和 `register_skills()` API。見[本次更新](#本次更新)

<details>
<summary>目錄（點擊展開）</summary>

- [GamesAI for MCDReforged](#gamesai-for-mcdreforged)
  - [安裝](#安裝)
  - [使用](#使用)
  - [|`!!data list keys`|讀取公共資料庫中的所有 key。|](#data-list-keys讀取公共資料庫中的所有-key)
  - [使用 Mineflayer Bot](#使用-mineflayer-bot)
    - [環境需求](#環境需求)
    - [指令](#指令)
    - [工作原理](#工作原理)
    - [支援的操作](#支援的操作)
    - [Bot 控制 AI 工具](#bot-控制-ai-工具)
    - [設定](#設定)
  - [設定](#設定-1)
    - [1.prefix](#1prefix)
    - [2.permission](#2permission)
    - [3.max\_history](#3max_history)
    - [4.all\_ai](#4all_ai)
    - [5.default\_ai](#5default_ai)
    - [6.mineflayer\_bot](#6mineflayer_bot)
  - [工具與Skills](#工具與skills)
    - [內建工具](#內建工具)
    - [在設定檔案中自訂工具](#在設定檔案中自訂工具)
    - [在自己的MCDR插件中自訂工具](#在自己的mcdr插件中自訂工具)
    - [內建Skills](#內建skills)
    - [在設定檔案中新增Skills](#在設定檔案中新增skills)
    - [在自己的MCDR插件中註冊Skills](#在自己的mcdr插件中註冊skills)
  - [故障排除](#故障排除)
    - [`!!ask` 錯誤](#ask-錯誤)
    - [Mineflayer Bot 錯誤](#mineflayer-bot-錯誤)
    - [日誌與除錯](#日誌與除錯)
  - [本次更新](#本次更新)
    - [Version 0.6.1](#version-061)
      - [🎯 核心亮點](#-核心亮點)
      - [1. 擴展插件系統](#1-擴展插件系統)
      - [2. 驗證與穩定性](#2-驗證與穩定性)
    - [Version 0.6.0](#version-060)
      - [🎯 核心亮點](#-核心亮點-1)
      - [1. Mineflayer Bot 整合](#1-mineflayer-bot-整合)
      - [2. 設定系統重製](#2-設定系統重製)
      - [3. OpenAI 日誌橋接](#3-openai-日誌橋接)
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
|`!!gamesai reload`|重新載入插件設定檔。|
|`!!gamesai check`|檢查插件更新。|
|`!!gamesai speedtest [model]`|測試 API 伺服器連線延遲，不指定模型時測試全部。|
|`!!gamesai config get <key>`|讀取一個設定項的值。|
|`!!gamesai config set <key> <value>`|修改一個設定項的值（自動適配舊值型別）。|

---

你也可以直接輸入 `!!ask` 向 AI 提問、聊天或請它幫你做一些事情。

|指令|用途|
|---|---|
|`!!ask <content>`|向 AI 提問、聊天或請它幫你做一些事情。`<content>` 為你想讓 AI 做的事情或你想問 AI 的問題。|
|`!!ask -m <model> <content>`|使用指定的模型向 AI 提問、聊天或請它幫你做一些事情。`<model>` 為你想使用的模型的 AI_ID 或暱稱，`<content>` 為你想讓 AI 做的事情或你想問 AI 的問題。|
|`!!ask -n <content>`|向 AI 提問但不使用歷史記錄（當前對話仍會被儲存）。|
|`!!ask -n -m <model> <content>`|使用指定的模型且不使用歷史記錄提問。|

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

---

## 使用 Mineflayer Bot

GamesAI 0.6.0 引入了基於 [Mineflayer](https://github.com/PrismarineJS/mineflayer) 的全自主 Minecraft 機器人。AI 可以直接控制機器人在遊戲世界中尋路、挖掘、建造、合成、戰鬥和互動。

### 環境需求

- 伺服器需安裝 **Node.js >= 18** 和 **npm**
- 插件首次啟動時自動安裝 npm 依賴（`mineflayer`、`ws`、`vec3`、`mineflayer-pathfinder`、`mineflayer-mcefly`）
- 一個用於 Bot 的 Minecraft 帳號（Microsoft/Mojang/離線）

### 指令

|指令|用途|
|---|---|
|`!!aibot join`|啟用 Bot 並讓其加入伺服器。|
|`!!aibot leave`|讓 Bot 離開伺服器並停用。|
|`!!aibot set <key> <value>`|設定 Bot 身份（`username`/`password`/`auth`）。|

### 工作原理

```
玩家 !!ask → GamesAI 插件 → WS 客戶端 (Python) → WS 伺服器 (Node.js) → Mineflayer Bot
                                                                           ↓
                                                                    Minecraft 伺服器

AI（自主控制器）:
  get_state → 分析狀態 → bot_call_action(goto/dig/attack/...) → 循環
```

插件啟動一個 Node.js 程序執行 WebSocket 伺服器，Python WebSocket 客戶端（插件內建）透過本地連線與其通訊，形成 MCDR 與 Mineflayer Bot 之間的橋樑。Bot 啟動後，**自主 AI 控制器**會定時讀取機器人狀態、檢查聊天訊息，並自主決定執行什麼操作。

### 支援的操作

Bot 支援 20+ 種操作，透過 `bot_call_action` AI 工具呼叫：

|操作|描述|
|---|---|
|`goto`|A* 尋路到座標 `{x, y, z, range?}`|
|`efly`|鞘翅飛行到座標（需裝備鞘翅）|
|`dig`|挖掘指定座標的方塊|
|`place`|在指定位址放置方塊|
|`attack`|按名稱攻擊附近實體，或攻擊最近敵對生物|
|`useOn`|右鍵實體（如村民交易）|
|`equip` / `unequip`|裝備/卸下盔甲或手持物品|
|`mount` / `dismount`|騎乘或離開載具和動物|
|`craft`|合成物品（背包或工作台）|
|`lookAt`|看向座標或直接設定 yaw/pitch|
|`sleep` / `wake`|在床上睡覺或起床|
|`activateBlock`|右鍵方塊（打開儲物箱、按下按鈕）|
|`setControlState`|控制載具移動（前進/後退/跳躍）|
|`viewContainer` / `takeFromContainer` / `putToContainer`|容器管理|
|`openFurnace` / `furnacePutInput` / `furnacePutFuel` / `furnaceTakeOutput`|熔爐操作|
|`nearbyEntities` / `findBlocks` / `getBlock`|世界查詢|
|`stop` / `stopEfly`|停止所有移動或鞘翅飛行|

### Bot 控制 AI 工具

除 `bot_call_action` 外，還有以下專用 AI 工具：

|工具|描述|
|---|---|
|`bot_chat`|讓 Bot 在公共聊天中傳送訊息。|
|`bot_whisper`|讓 Bot 向某個玩家傳送私聊訊息。|
|`bot_get_state`|取得 Bot 完整狀態（30+ 欄位）。|
|`bot_start` / `bot_stop`|啟動或停止 Bot。|
|`delegate_to_bot`|將複雜的 Minecraft 任務委派給自主控制器。|

### 設定

完整設定參考見 [6.mineflayer_bot](#6mineflayer_bot)。關鍵要點：

- 將 `mineflayer_bot.enabled` 設為 `true`（或使用 `!!aibot join`）以啟動 Bot
- `mineflayer_bot.bot.username` / `password` / `auth` — Bot 的 Minecraft 登入憑證。**使用者名稱必須匹配 `[a-zA-Z0-9_]+`**（僅限英文字母、數字和底線）。
- `mineflayer_bot.cycle_interval` — 自主 AI 決策間隔（秒）
- `mineflayer_bot.websocket` — 內部設定，除非明確知道用途否則不要修改

## 設定

預設設定檔結構如下：

```json
{
  "prefix": "[GamesAI]",
  "permission": 3,
  "max_history": 10,
  "all_ai": {
      "<Your AI ID>":{
          "prompt": "你是一名成熟、穩重的 Minecraft 機器人工具，你的名字叫做「GamesAI」",
          "ai_name": "[GamesAI]",
          "base_url": "<Your API Base URL>",
          "ai_model": "<Your AI Model>",
          "api_key": "<Your API Key>",
          "extra_body": {}
      }
    },
  "default_ai": "<Your AI ID>",
  "mineflayer_bot": {
      "enabled": false,
      "cycle_interval": 15.0,
      "websocket": {
          "url": "ws://127.0.0.1:8080",
          "reconnect_interval": 10,
          "timeout": 60
      },
      "bot": {
          "username": "<Your Minecraft Bot Username>",
          "password": "<Your Minecraft Bot Password>",
          "auth": "microsoft"
      }
  }
```

---

以下是每個參數的簡介：

### 1.prefix
值的類型：`str`

預設值：`[GamesAI]`

填入插件的名稱，以在插件的回覆之前加上一個前綴，可包含 Minecraft 格式化程式碼。

### 2.permission
值的類型：`int`

預設值：`3`

執行 `!!data` 等指令所必須達到的權限等級，請參閱 [MCDR 權限相關文件](https://docs.mcdreforged.com/zh-cn/latest/permission.html)。

### 3.max_history
值的類型：`int`

預設值：`10`

填入每個玩家最多可保留的歷史記錄數量，與公共資料庫無關。設定為 `0` 時完全停用歷史記錄功能。

### 4.all_ai
值的類型：`dict`

預設值：見檔案

填入所有的 AI 資訊，由多個字典組成，每個字典為一個 AI 模型，字典的鍵即為插件內部的 AI_ID。

**prompt**：此設定用於為每個 AI 編寫提示詞。使用 `> xxx.md` 將提示詞指向 `config/games_ai/prompt/xxx.md` 檔案，不限檔案類型

**ai_name**：此設定與 `prefix` 功能類似，但你需要單獨為每個模型設定，可包含 Minecraft 格式化程式碼。

**base_url**、**ai_model**、**api_key**：與以往的相關設定功能相同，但你需要單獨為每個模型設定。

**extra_body**：請參考各 API 提供商對 `extra_body` 項的說明以編寫。對於 DeepSeek 使用者，想要移植原有 `thinking` 的，直接填寫 `{"thinking": {"type": "enabled"}}`。未填寫時預設 `{}`（空）。

### 5.default_ai
值的類型：`str`

預設值：`<Your AI ID>`

填入當使用者直接使用 `!!ask` 時所使用的模型，應填入 `all_ai` 字典中的某一個鍵（即插件內部的 AI_ID）。若填寫錯誤，將導致無法正常使用 `!!ask` 指令。

### 6.mineflayer_bot
值的類型：`dict`

預設值：見上方

Mineflayer 自主 Bot 代理的設定項。

**enabled**：是否在啟動時拉起 Bot。需要 Node.js >= 18。

**cycle_interval**：自主 AI 決策循環間隔秒數（預設：15.0）。

**websocket**：內部 WebSocket 連線參數 — `url`、`reconnect_interval`、`timeout`。

> [!WARNING]
> WebSocket 的 `url` 中 host **必須**設為 `127.0.0.1`。請確保所選埠號未被佔用——插件會在啟動時自動檢查埠號衝突，若埠號被佔用將自動停用 Bot。
> 除非你明確知道自己在做什麼，否則我們不建議你修改 `websocket` 內的設定。

**bot**：Minecraft 帳號憑證 — `username`、`password`、`auth`（microsoft/mojang/offline）。伺服器位址自動從 `server.properties` 中檢測。

> [!WARNING]
> `username` 必須符合正則表達式 `[a-zA-Z0-9_]+`（僅限英文字母、數字和底線，不含空格）。若使用者名稱包含非法字元，`!!aibot join` 將被拒絕。

## 工具與Skills

> [!TIP]
> 部分內建工具已遷移至 [GamesAI-Extra](https://github.com/PengZixuan30/Games_AI-Extra) 插件（如座標點管理、位置追蹤等）。安裝後可獲得額外工具。

### 內建工具

GamesAI 插件提供了許多內建工具，請見下表。如果你想要更多工具，可以選擇[向作者投稿](https://github.com/PengZixuan30/Games_AI/issues/new)、[在設定檔案中自訂工具](#在設定檔案中自訂工具)、或[在自己的MCDR插件中註冊工具](#在自己的mcdr插件中自訂工具)。

<details>
<summary>點擊檢視所有內建工具</summary>

|工具 ID|傳入參數|用途|
|:---:|:---:|:---|
|get_online_players|無|取得伺服器中線上的玩家列表。依賴於 `online_player_api` 插件，不存在時自動關閉此工具。|
|get_whitelist_name|無|取得伺服器完整的白名單列表。依賴於 `whitelist_api` 插件，不存在時自動關閉此工具。|
|add_to_whitelist|`name`|將某個玩家新增到白名單中。依賴於 `whitelist_api` 插件，不存在時自動關閉此工具。|
|remove_from_whitelist|`name`|將某個玩家從白名單中移除。依賴於 `whitelist_api` 插件，不存在時自動關閉此工具。|
|search_minecraft_wiki|`query`|讓 AI 搜尋 Minecraft Wiki，以確保回答更準確。|
|calculator|`expression`|簡單的數學表達式計算機。|
|item_caculator|`expression`、`single_limit`|數學表達式計算機，並將最終結果轉換為物品計數法，即「盒、組、個」，自動適應物品的堆疊數，未指定時預設使用 64。|
|ai_read_data|`key`|讀取一筆資料庫內容。|
|ai_read_all_keys|無|取得資料庫中的所有鍵。|
|ai_read_all_data|無|一次性讀取資料庫中所有鍵值對。|
|ai_write_data|`key`、`value`|向資料庫中寫入一筆資料（覆寫模式）。|
|ai_add_data|`key`、`value`|向資料庫中寫入一筆資料（追加模式）。|
|read_skills|`skills`|讀取已註冊的技能指導檔案，引導 AI 執行特定任務。||write_skills|`skills`、`summary`、`content`|建立或覆寫一個技能檔案並註冊到技能索引中|
|modify_skills|`skills`、`summary`、`content`|修改已有技能檔案並更新索引中的簡介|
|delete_skills|`skills`|刪除一個技能檔案並從技能索引中移除|
|read_custom_tools|無|讀取目前自訂 `tools.py` 檔案的內容|
|modify_custom_tools|`tools`|用新程式碼替換整個自訂 `tools.py` 檔案|
|append_custom_tools|`tools`|向自訂 `tools.py` 檔案末尾追加新工具程式碼|
|setting_timer|`duration`|暫停執行指定秒數後再繼續下一步操作|
|reload_plugin|無|熱重載插件以套用設定、技能和自訂工具的變更，不會遺失聊天記錄|
|ai_del_data|`key`|刪除資料庫中的一筆資料|
|bot_chat|`message`|讓 Mineflayer 機器人在 Minecraft 聊天中傳送訊息。|
|bot_whisper|`username`, `message`|讓機器人私訊某個玩家。|
|bot_get_state|無|取得機器人完整狀態（30+ 欄位）。|
|bot_call_action|`action`, `params`|向機器人傳送任意指令（goto、dig、place、attack 等）。|
|bot_start|無|啟動 Mineflayer 機器人（如果未執行）。|
|bot_stop|無|停止 Mineflayer 機器人。|
|delegate_to_bot|`task`|將複雜的 Minecraft 任務委派給自主 Bot 控制器。|

</details>

### 在設定檔案中自訂工具

透過修改 `config/games_ai/tools/tools.py` 檔案來實作自訂工具。

先來看看預設內容：

```python
from mcdreforged.command.command_source import CommandSource
from games_ai.games_ai_tool import register_tool

@register_tool(description="My Custom Tool")
def my_custom_tool(source: CommandSource, ai_prefix: str):
    return "Tool execution completed"
```

> [!IMPORTANT]
> 程式碼中的 `from games_ai.games_ai_tool import register_tool` 和函式定義前的 `@register_tool` 必須存在。

> [!TIP]
> 在 0.5.7+ 版本中，AI 可以**自主讀取、修改和追加**自訂工具檔案。只需讓 AI 幫你新增工具——它會先讀取目前檔案，編寫新程式碼，然後重新載入插件。

`description` 是必填項，告訴 AI 此工具的用途。`parameters` 字典（可選）定義了 AI 應傳入的參數，遵循 [OpenAI function calling 格式](https://platform.openai.com/docs/guides/function-calling)。函式簽名必須包含 `source: CommandSource` 和 `ai_prefix: str` 作為前兩個參數，其後跟隨 `parameters` 中定義的參數。

> [!TIP]
> 在 `@register_tool` 旁添加 `@register_bot_tool()` 裝飾器（同樣從 `games_ai.games_ai_tool` 匯入），可以讓該工具被自主 Mineflayer Bot 控制器使用。不加則只能透過 `!!ask` 由聊天 AI 呼叫。

### 在自己的MCDR插件中自訂工具

如果你在開發獨立的 MCDR 插件，可以直接在插件程式碼中註冊工具，無需修改 `tools.py`：

```python
from games_ai.games_ai_tool import register_tool, register_bot_tool

@register_tool(
    description="你的自訂工具的描述",
    parameters={...}  # 可選
)
@register_bot_tool()  # 可選 — 讓該工具可被 Mineflayer Bot 控制器使用
def my_plugin_tool(source: CommandSource, ai_prefix: str, ...):
    source.reply(f'{ai_prefix}正在執行我的工具...')
    return "工具執行結果"
```

> [!IMPORTANT]
> 你的插件**必須**在 `mcdreforged.plugin.json` 中將 `games_ai` 的版本依賴設為 `>= 0.4.1`，否則匯入會失敗。如果使用了 `@register_bot_tool()`，最低版本應為 `>= 0.6.0`。

你的插件需要在 `mcdreforged.plugin.json` 中將 `games_ai` 列為依賴，以確保 GamesAI 先載入：

```json
{
    "id": "my_plugin",
    "dependencies": {
        "mcdreforged": ">=2.15.0",
        "games_ai": ">=0.4.1"
    }
}
```

以此方式註冊的工具與內建工具完全相同——AI 可以直接呼叫，如果需要也可以使用 `@register_bot_tool()` 標記為 Bot 可用工具。

如果你希望你的插件在 GamesAI 執行 `!!gamesai reload` 時**自動重新載入**（例如 AI 透過 `modify_custom_tools` 修改了工具程式碼後），在你的插件 `on_load` 中呼叫 `register_self()`：

```python
from games_ai.register_extra_plugin import register_self

def on_load(server, old):
    register_self(server.get_self_metadata().id)
```

這樣你的插件會隨 GamesAI 的設定和工具一起重新載入，工具程式碼的修改會立即生效。

### 內建Skills

GamesAI 內建了以下技能檔案，AI 在執行相關操作前會自動讀取：

| 技能檔案 | 描述 |
|---|---|
| `skills_management.md` | 指導 AI 如何正確讀取、寫入、修改和刪除技能檔案。 |
| `custom_tools_management.md` | 指導 AI 如何安全地讀取、修改和追加自訂工具程式碼。 |
| `mineflayer_bot_guide.md` | 指導 AI 如何操控 Mineflayer 機器人（僅在 Bot 執行時可用）。 |

> [!TIP]
> Skills 就像 AI 的「標準作業程序 (SOP)」——確保 AI 每次都遵循正確的工作流程。

### 在設定檔案中新增Skills

Skills 技能系統讓你可以編寫指導檔案來規範 AI 處理特定任務的方式——例如白名單管理、假人控制等。

技能檔案存放在 `config/games_ai/skills/` 目錄下，格式為 Markdown（`.md`）。要註冊一項技能，編輯 `config/games_ai/skills/skills.json`。以下是一個範例設定（`whitelist.md` 和 `player.md` 僅為範例檔名，並非插件內建檔案）：

```json
[
    {
        "file": "whitelist.md",
        "description": "新增／刪除／查詢白名單時都應讀取此技能檔案"
    },
    {
        "file": "player.md",
        "description": "建立／控制／刪除假人時必須讀取此技能檔案"
    }
]
```

- **`file`** — 技能檔案名稱（相對於 `skills` 資料夾）。
- **`description`** — 展示給 AI 的簡短提示，說明何時應當讀取此技能。

技能註冊後會出現在 AI 的系統提示中。AI 可以使用 **`read_skills`** 工具在執行相關任務前讀取技能檔案的完整內容。

### 在自己的MCDR插件中註冊Skills

你可以從自己的 MCDR 插件中以程式設計方式註冊技能檔案，使其自動出現在 AI 的系統提示中：

```python
from games_ai.external_skills_loader import register_skills

def on_load(server, old):
    register_skills(
        file_name="my_skill.md",
        description="執行 XYZ 操作前應讀取此技能檔案",
        content="""## 我的技能

此技能指導 AI 如何...
- 步驟 1：...
- 步驟 2：...
"""
    )
```

> [!IMPORTANT]
> 你的插件**必須**在 `mcdreforged.plugin.json` 中將 `games_ai` 的版本依賴設為 `>= 0.6.1`。

- **`file_name`** — 技能檔案名稱（AI 的 `read_skills` 工具透過此名稱定位檔案）。
- **`description`** — 展示給 AI 的簡短提示，說明何時應當讀取此技能。
- **`content`** — 技能檔案的完整 Markdown 內容。

以此方式註冊的技能與 `skills.json` 中定義的技能完全相同——它們會出現在 AI 的系統提示中的「Available skills」列表裡，並可透過 `read_skills` 工具讀取。

## 故障排除

### `!!ask` 錯誤

|症狀|可能原因|解決方法|
|---|---|---|
|HTTP 400|請求體格式錯誤|檢查 `extra_body` 格式是否與 API 提供商的要求一致。|
|HTTP 401|API Key 無效|檢查 AI 設定中的 `api_key`。|
|HTTP 404|模型不存在|檢查 `ai_model` 名稱是否正確。|
|HTTP 429|請求頻率過高|稍後重試，或升級 API 方案。|
|逾時/無回應|網路問題或 API 回應慢|使用 `!!gamesai speedtest` 檢查延遲。嘗試更換模型。|
|「未知函式」回覆|AI 呼叫了不存在的工具|通常無害——AI 會重試其他方法。|

### Mineflayer Bot 錯誤

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

### 日誌與除錯

- 啟用除錯模式：`!!gamesai debug` — 顯示完整 AI 提示詞和工具呼叫結果。
- Mineflayer Bot 日誌在 MCDR 主控台以 `[Mineflayer]` 前綴顯示。
- OpenAI SDK HTTP 日誌自動路由至 MCDR 主控台（詳見 [OpenAI 日誌橋接](#3-openai-日誌橋接)）。
- 如果以上方法均無效，請檢查 `config/games_ai/config.json` 是否存在設定錯誤。

## 本次更新

### Version 0.6.1

#### 🎯 核心亮點

- **🔌 擴展插件系統** — 為 MCDR 插件開發者提供 `register_self()` 和 `register_skills()` API
- **🛡️ 輸入驗證** — `!!aibot join` 時驗證 Bot 使用者名稱合法性
- **📋 日誌改進** — 已註冊插件重新載入/卸載生命週期的詳細日誌

#### 1. 擴展插件系統

第三方 MCDR 插件現在可以更深度地與 GamesAI 整合：

- **`register_self(plugin_id)`** — 在你的插件 `on_load` 中呼叫，使其在 `!!gamesai reload` 時自動重新載入。這對於註冊了自訂工具、需要在 AI 修改後同步設定/Skills 變更的插件至關重要。
- **`register_skills(file_name, description, content)`** — 從插件程式碼中以程式設計方式註冊技能檔案，無需手動編輯 `skills.json`。技能會出現在 AI 的系統提示中，並可透過 `read_skills` 工具讀取。

#### 2. 驗證與穩定性

- `!!aibot join` 現在會驗證 Bot 使用者名稱——拒絕包含非法字元（非 `[a-zA-Z0-9_]`）的使用者名稱。
- 修復了走訪 `REGISTER_PLUGIN_LIST` 時刪除元素可能導致跳過條目的 Bug。
- 為擴展插件的生命週期（重新載入/卸載狀態）新增了完整的日誌記錄。

### Version 0.6.0

#### 🎯 核心亮點

- **🤖 Mineflayer Bot** — 由 AI 透過 WebSocket 全自主控制的 Minecraft 機器人
- **⚙️ 設定系統重製** — 型別自適應設定、`!!aibot` 管理指令、輸入驗證
- **📋 日誌橋接** — OpenAI/httpx SDK 日誌無縫路由至 MCDR 日誌系統

#### 1. Mineflayer Bot 整合

0.6.0 最大的新特性：基於 Mineflayer 的全自主 Minecraft 機器人，透過 WebSocket 指令介面由 AI 控制。

**支援的操作**（20+）：`goto`（A* 尋路）、`efly`（鞘翅飛行）、`dig`、`place`、`attack`、`useOn`、`equip`/`unequip`（裝備/卸下盔甲）、`mount`/`dismount`（騎乘/離開）、`craft`（合成）、容器與熔爐管理、`lookAt`、`setControlState` 等。

**擴展 `get_state`**：30+ 欄位 — 位置、視角 (yaw/pitch)、速度、盔甲 (head/chest/legs/feet)、氧氣、經驗、世界時間、天氣、維度、睡眠狀態等。

**自訂物理引擎**：擊退回應（透過 `entity_velocity` 封包）和實體碰撞/擠壓。尋路時自動暫停物理以避免干擾。

**Bot 管理**：
- `!!aibot join` / `!!aibot leave` — 生命週期控制
- `!!aibot set username/password/auth` — 設定 Bot 身份，含輸入驗證
- `bot_start` / `bot_stop` 工具 — AI 自主控制
- `delegate_to_bot` — 將複雜任務移交給自主控制器

**其他改進**：死亡自動重生、預設啟用物理引擎、`path_update` noPath 檢測（無法到達時立即返回錯誤）、聊天訊息自動去除 `§` 字元。

#### 2. 設定系統重製

- **型別自適應 `set_config`**：`!!gamesai config set` 現在讀取舊值的型別並自動將新值轉換為匹配型別。設定 float 為 `"20"` 仍保持 float，bool 保持 bool 等。型別不匹配錯誤會被捕捉並報告。
- **`!!aibot set` 指令**：無需手動編輯 JSON 即可管理 Bot 的使用者名稱、密碼和認證方式。使用者名稱/密碼驗證為 `[a-zA-Z0-9_]`，auth 限制為 `microsoft`/`mojang`/`offline`。

#### 3. OpenAI 日誌橋接

> [!NOTE]
> 徹底解決了舊版 OpenAI SDK 原始日誌會佔用 MCDR 主控台導致輸入失常及顯示異常的問題。

`openai` 和 `httpx` Python 日誌現已完全重定向至 MCDR Logger：
- 所有 HTTP 請求/回應日誌出現在 MCDR 主控台
- 原始 handler 已清除、propagation 已停用 — 無重複 stderr 輸出

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
