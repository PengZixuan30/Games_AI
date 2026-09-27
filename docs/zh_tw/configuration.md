<div align="center">

# 設定

[English](../en_us/configuration.md)  |  [简体中文](../zh_cn/configuration.md)  |  繁體中文

[返回 README](../../README.zh-TW.md)

</div>

預設設定檔結構如下：

```json
{
  "prefix": "[GamesAI]",
  "permission": 3,
  "all_ai": {
      "<Your AI ID>":{
          "prompt": "你是一名成熟、穩重的 Minecraft 機器人工具，你的名字叫做「GamesAI」",
          "ai_name": "[GamesAI]",
          "base_url": "<Your API Base URL>",
          "ai_model": "<Your AI Model>",
          "api_key": "<Your API Key>",
          "extra_body": {},
          "context_window": null
      }
    },
  "default_ai": "<Your AI ID>",
  "mineflayer_bot": {
      "enabled": false,
      "cycle_interval": 15.0,
      "websocket": {
          "url": "ws://127.0.0.1:8080",
          "reconnect_interval": 10,
          "timeout": 60,
          "first_connect_interval": 0.5
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

## 1.prefix
值的類型：`str`

預設值：`[GamesAI]`

填入插件的名稱，以在插件的回覆之前加上一個前綴，可包含 Minecraft 格式化程式碼。

## 2.permission
值的類型：`int`

預設值：`3`

執行 `!!data` 等指令所必須達到的權限等級，請參閱 [MCDR 權限相關文件](https://docs.mcdreforged.com/zh-cn/latest/permission.html)。

自 0.6.4 起，該值同時決定向玩家 AI 提供哪些**工具**：`perm` 高於玩家權限等級的工具不會傳給 AI 模型，模型既看不到也無法呼叫。管理資料、技能、自訂工具或啟停 Bot 的內建工具都使用該值（透過 `get_plugin_config_perm`），並在每次請求時即時讀取，重載後立即生效。

## 3.all_ai
值的類型：`dict`

預設值：見檔案

填入所有的 AI 資訊，由多個字典組成，每個字典為一個 AI 模型，字典的鍵即為插件內部的 AI_ID。

**prompt**：此設定用於為每個 AI 編寫提示詞。使用 `> xxx.md` 將提示詞指向 `config/games_ai/prompt/xxx.md` 檔案，不限檔案類型

**ai_name**：此設定與 `prefix` 功能類似，但你需要單獨為每個模型設定，可包含 Minecraft 格式化程式碼。

**base_url**、**ai_model**、**api_key**：與以往的相關設定功能相同，但你需要單獨為每個模型設定。

**extra_body**：請參考各 API 提供商對 `extra_body` 項的說明以編寫。對於 DeepSeek 使用者，想要移植原有 `thinking` 的，直接填寫 `{"thinking": {"type": "enabled"}}`。未填寫時預設 `{}`（空）。

**context_window**（可選）：為該模型覆寫[上下文自動管理](ai-request-pipeline.md#上下文自動管理)所使用的上下文視窗（單位 token）。留空（`null`）時使用上下文視窗表中的數值。對於視窗極大的模型，可作為成本控制開關，例如 `"context_window": 65536`。

> [!TIP]
> 用 `!!ask context --all` 可以看到每個模型**實際**被用了多少上下文、以及自插件載入以來累計消耗了多少 token（含快取命中率）。若某個 100 萬視窗的模型長期只用到幾萬 token，就說明上面這個覆寫值可以放心調小——視窗越小，壓縮越早介入，長對話的每次請求就越便宜。詳見[上下文檢視](ai-request-pipeline.md#上下文檢視)。

## 4.default_ai
值的類型：`str`

預設值：`<Your AI ID>`

填入當使用者直接使用 `!!ask` 時所使用的模型，應填入 `all_ai` 字典中的某一個鍵（即插件內部的 AI_ID）。若填寫錯誤，將導致無法正常使用 `!!ask` 指令。

## 5.mineflayer_bot
值的類型：`dict`

預設值：見上方

Mineflayer 自主 Bot 代理的設定項。

**enabled**：是否在啟動時拉起 Bot。需要 Node.js >= 18。

**cycle_interval**：自主 AI 決策循環間隔秒數（預設：15.0）。

**websocket**：內部 WebSocket 連線參數 — `url`、`reconnect_interval`、`timeout`、`first_connect_interval`。

**first_connect_interval**：**首次連線成功之前**的重試間隔秒數（預設: 0.5）。Node 服務啟動並開啟連接埠需要一點時間，若首次連線失敗就按 `reconnect_interval`（預設 10 秒）退避，假人上線會憑空多等這麼久；因此首次連線階段使用這個更短的間隔，**連上過一次之後**才恢復使用 `reconnect_interval`。

> [!WARNING]
> WebSocket 的 `url` 中 host **必須**設為 `127.0.0.1`。請確保所選埠號未被佔用——插件會在啟動時自動檢查埠號衝突，若埠號被佔用將自動停用 Bot。
> 除非你明確知道自己在做什麼，否則我們不建議你修改 `websocket` 內的設定。

**bot**：Minecraft 帳號憑證 — `username`、`password`、`auth`（microsoft/mojang/offline）。伺服器位址自動從 `server.properties` 中檢測。

> [!WARNING]
> `username` 必須符合正則表達式 `[a-zA-Z0-9_]+`（僅限英文字母、數字和底線，不含空格）。若使用者名稱包含非法字元，`!!aibot join` 將被拒絕。

> [!TIP]
> 修改設定後，使用 `!!gamesai reload` 或 `!!gamesai config set` 使更改生效。詳見[熱重載](hot-reload.md#熱重載)。
