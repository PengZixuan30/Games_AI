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
          "extra_body": {}
      }
    },
  "default_ai": "<Your AI ID>",
  "mineflayer_bot": {
      "enabled": false,
      "cycle_interval": 15.0,
      "bot": {
          "username": "<Your Minecraft Bot Username>",
          "password": "<Your Minecraft Bot Password>",
          "auth": "microsoft"
      }
  },
  "websocket": {
      "uri": "ws://127.0.0.1:8080",
      "force_server": false,
      "allow_app_id": [],
      "name": "",
      "token_ttl_hours": -1,
      "auto_enroll": true,
      "identity_file": ""
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

該值同時決定向玩家 AI 提供哪些**工具**：`perm` 高於玩家權限等級的工具不會傳給 AI 模型，模型既看不到也無法呼叫。管理資料、技能、自訂工具或啟停 Bot 的內建工具都使用該值（透過 `get_plugin_config_perm`），並在每次請求時即時讀取，重載後立即生效。

但它並不是所有指令的門檻：`!!gamesai reload`、`!!gamesai check`、`!!gamesai debug`、`!!gamesai debug thread`、`!!gamesai speedtest` 以及只影響自己的 `!!gamesai clear` 對任何來源都執行，`!!ask` 也對所有玩家開放（該等級只決定模型能看到哪些工具）。會檢查該等級的是 `!!gamesai clear <name>`、`!!gamesai clearall`、`!!data` 各子指令、`!!gamesai config get/set`、`!!aibot join/leave/set` 與 `!!gamesai node …`（不帶參數的 `!!gamesai clear` 只涉及自己的歷史，不需要該等級）。

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
> 用 `!!ask context --all` 可以看到每個設定的 AI 條目**實際**被用了多少上下文、以及自其對話建立以來累計消耗了多少 token（重啟後仍然累計）（含快取命中率）。若某個 100 萬視窗的模型長期只用到幾萬 token，就說明上面這個覆寫值可以放心調小——視窗越小，壓縮越早介入，長對話的每次請求就越便宜。詳見[上下文檢視](ai-request-pipeline.md#上下文檢視)。

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

**假人的連線位址**：假人不自己監聽連接埠，而是作為客戶端接入叢集 —— 位址與角色由頂層的 [6.websocket](#6websocket) 決定，詳見[跨服連線](cross-server.md)。



**bot**：Minecraft 帳號憑證 — `username`、`password`、`auth`（microsoft/mojang/offline）。伺服器位址自動從 `server.properties` 中檢測。


> [!TIP]
> 修改設定後，使用 `!!gamesai reload` 使更改生效。`!!gamesai config set` 同樣會重載，但它只處理頂層鍵，並會拒絕 `all_ai` 與 `mineflayer_bot` 這類複雜設定區塊（點分鍵會被當成新的頂層鍵寫入，而不會被解析到對應的子鍵）——Bot 憑證請改用 `!!aibot set`。詳見[熱重載](hot-reload.md#熱重載)。

## 6.websocket

跨服連線設定，完整說明見[跨服連線](cross-server.md)。

- `websocket.uri` — 叢集位址（預設 `"ws://127.0.0.1:8080"`）。能連上 GamesAI hub 就以客戶端接入；連不上且連接埠空閒則以本機為 hub 監聽 —— 但如果本機已持有節點身份就例外：已入網的實例會保持客戶端身份並持續重試，直到用 `!!gamesai node forget` 丟棄其 token。`host` 按字面綁定，要讓別的機器連上需寫 `0.0.0.0` 或本機內網 IP。
- `websocket.force_server` — 強制本機做 hub（預設 `false`；連接埠被佔時報錯並退回 local 模式）。
- 從舊版本升級：舊的 `mineflayer_bot.websocket.url` 會自動遷移到 `websocket.uri`，舊區塊被刪除。
- `websocket.allow_app_id` — 字串列表（預設 `[]`）。額外允許哪些握手 ID 接入本 hub（例如你自己的服務），避免被 `4005` 拒絕；hub 不為這些 ID 做專項適配，且它們被視為完全可信。詳見[跨服連線](cross-server.md#握手-id)。
- `websocket.token_ttl_hours` — 簽發給節點的 token 有效期（小時，預設 `-1` 永久）。簽發時固化，只在握手時校驗，不會中斷進行中的連線；跨主機建議設一個值。詳見[跨服連線](cross-server.md)。
- `websocket.auto_enroll` — 本機沒有身份時是否自動向 hub 發出註冊請求（預設 `true`）。
- `websocket.identity_file` — 自訂本機身份檔案路徑（預設 `config/games_ai/cross_server/identity.json`）。維運寫了哪個檔案就用哪個：該值按原樣使用（相對路徑按工作目錄解析），並且**不會**對舊預設位置做自動遷移。
- `websocket.name` — 本實例在叢集裡的名字。預設 `""` = 按實例目錄派生：`<實例目錄名>-<路徑雜湊前 6 位>`（如 `survival-9f31ab`），所以同機兩個實例不會撞名，改機器名也不會讓註冊失效。改名字需要重新入網（`!!gamesai node forget` 後再 `node claim`）。

## 7. 外掛更新

**沒有任何可設定項。** 自動更新完全按跨服角色決定（見[跨服連線](cross-server.md#叢集更新)）：

- **單機**（local 模式）在啟動時與每 24 小時檢查一次，自己安裝新版本；
- **hub** 同樣如此，並且額外協調整個叢集：節點先裝，hub 阻塞等到它們以新版本回來，最後才裝自己；
- **客戶端**從不檢查、從不自行安裝 —— 由 hub 決定。在客戶端輸入 `!!gamesai check` 會在 hub 上執行。

產物永遠來自本外掛自己的 GitHub release（`ghfast.top` 鏡像是第二來源），並且只有公告的尺寸、sha256 **以及**封存檔內的外掛 id 與版本全部相符才會使用。這裡**刻意沒有** `!!MCDR plugin install` 兜底：一輪失敗就結束並如實報告（再執行一次 `!!gamesai check` 開新一輪，或手動 `!!MCDR plugin install -U -y games_ai`）。
