<div align="center">

# GamesAI

[English](/README.md)  |  [简体中文](/README.zh-CN.md)  |  繁體中文

[回報問題](https://github.com/PengZixuan30/Games_AI/issues/new)  |  [提供建議](https://github.com/PengZixuan30/Games_AI/issues/new)

</div>

> [!NOTE]
> 歡迎使用版本 0.4.2，當前版本修復了一些問題，加入了 AI 自動查詢 Minecraft Wiki 的功能，重構了部分程式碼結構。詳見[本次更新](#本次更新)

> [!IMPORTANT]
> 由於 0.4.0 版本起的多模型支援的新增，設定檔大改，請注意及時修改設定檔

<details>
<summary>目錄（點擊展開）</summary>

- [GamesAI](#gamesai)
  - [安裝](#安裝)
  - [使用](#使用)
  - [設定](#設定)
    - [1. prefix](#1-prefix)
    - [2. permission](#2-permission)
    - [3. max\_history](#3-max_history)
    - [4. all\_ai](#4-all_ai)
    - [5. default\_ai](#5-default_ai)
  - [本次更新](#本次更新)
    - [1. 加入了 AI 自動查詢 Minecraft Wiki 的功能](#1-加入了-ai-自動查詢-minecraft-wiki-的功能)
    - [2. 重構了部分程式碼結構](#2-重構了部分程式碼結構)
    - [3. 加入了新的指令 `!!gamesai reload`](#3-加入了新的指令-gamesai-reload)
  - [鳴謝與聲明](#鳴謝與聲明)
  - [授權條款](#授權條款)

</details>

## 安裝

在 MCDR 控制台中使用以下指令安裝插件：

`!!MCDR plugin install games_ai`

---

或者從 [MCDR 插件倉庫](https://mcdreforged.com/zh-CN/plugin/games_ai) 獲取並安裝到你的插件目錄內。

如果選擇手動安裝，請先安裝 Python 套件 OpenAI 和 requests，使用以下指令安裝：
```bash
pip install openai requests
```

## 使用

在任何地方輸入指令 `!!gamesai` 以顯示這個插件的所有功能。

`!!gamesai` 的指令如下：
| 指令 | 用途 |
|---|---|
| `!!gamesai clear` | 清除玩家的歷史聊天記錄，歷史聊天記錄與公共資料庫無關 |
| `!!gamesai clearall` | 清除所有玩家的歷史聊天記錄，歷史聊天記錄與公共資料庫無關 |
| `!!gamesai reload` | 重新載入插件設定檔 |
| `!!gamesai check` | 檢查插件更新 |

---

你也可以直接輸入 `!!ask` 向 AI 提問或聊天，或是請 AI 幫你做一些事情。

`!!ask` 的指令如下：
| 指令 | 用途 |
|---|---|
| `!!ask <content>` | 向 AI 提問或聊天，或是請 AI 幫你做一些事情，content 為你想讓 AI 做的事情或你想問 AI 的問題 |
| `!!ask -m <model> <content>` | 使用指定的模型向 AI 提問或聊天，或是請 AI 幫你做一些事情，model 為你想使用的模型的 AI_ID 或暱稱，content 為你想讓 AI 做的事情或你想問 AI 的問題 |

---

輸入 `!!data` 取得有關資料庫指令的資訊。

> [!TIP]
> 更新到 0.3.0 及以上版本時會自動建立資料庫。

`!!data` 的指令如下：

| 指令 | 用途 |
|------|------|
| `!!data write <key> <value>` | 在公共資料庫內新增一筆資料，其中 key 不能包含空格，value 可以是任意字串 |
| `!!data add <key> <value>` | 將 value 附加到公共資料庫中的 key 中，不存在時自動建立新 key |
| `!!data del <key>` | 在公共資料庫內刪除一筆資料，無論 key 是否存在 |
| `!!data read <key>` | 讀取公共資料庫中 key 對應的 value |
| `!!data list` | 讀取公共資料庫中的所有內容 |
| `!!data list keys` | 讀取公共資料庫中的所有 key |

## 設定

預設設定檔結構如下：

```json
{
  "prefix": "[GamesAI]",
  "permission": 3,
  "max_history": 10,
  "all_ai": {
      "<Your AI ID>": {
          "prompt": "使用簡潔的語言回答，但請帶有一定的情感。你是 Minecraft 伺服器的一個機器人。",
          "ai_name": "[GamesAI]",
          "base_url": "<Your API Base URL>",
          "ai_model": "<Your AI Model>",
          "api_key": "<Your API Key>",
          "thinking": false
      }
    },
  "default_ai": "<Your AI ID>"
}
```

---

以下是每個參數的簡介：

### 1. prefix
型別：str

預設值：\[GamesAI\]

填入插件的名稱，以在插件的回覆之前加上一個前綴，可以包含 Minecraft 格式化代碼。

### 2. permission
型別：int

預設值：3

執行 `!!data` 等指令所必須達到的權限等級，見 [MCDR 權限相關文件](https://docs.mcdreforged.com/zh-cn/latest/permission.html)。

### 3. max_history
型別：int

預設值：10

填入每個玩家最大可保留的歷史記錄數量，與公共資料庫無關。

### 4. all_ai
型別：dict

預設值：見檔案

填入所有的 AI 資訊，由多個字典組成，每個字典為一個 AI 模型，字典的鍵即為插件內部的 AI_ID。

**prompt**：此項設定用於為每個 AI 編寫提示詞。

**ai_name**：此項設定與 prefix 功能類似，但現在你需要單獨為每一個模型設定，可以包含 Minecraft 格式化代碼。

**base_url**、**ai_model**、**api_key**：與以前的相關設定功能相同，但現在你需要單獨為每一個模型設定。

**thinking**：此項設定用於啟用/禁用模型的思考模式，不填時預設為 false，切勿為沒有思考模式的模型啟用此項，那可能會出錯。

### 5. default_ai
型別：str

預設值：\<Your AI ID\>

填入當使用者直接使用 `!!ask` 時使用的模型，應該填入 `all_ai` 字典中的某一個鍵（即為插件內部的 AI_ID），如果錯填，會導致無法正常使用 `!!ask` 指令。

## 本次更新
### 1. 加入了 AI 自動查詢 Minecraft Wiki 的功能
在 0.4.2 版本中，加入了 AI 自動查詢 Minecraft Wiki 的功能，當使用者使用 `!!ask` 指令提問時，AI 會自動判斷使用者的問題是否與 Minecraft 相關，如果相關，會自動查詢 Minecraft Wiki 並將查詢結果作為提示詞的一部分，以提供更準確的回答。

### 2. 重構了部分程式碼結構
在 0.4.2 版本中，重構了部分程式碼結構，以提高程式碼的可讀性和可維護性，同時也為未來的自訂 skills 功能做好了準備。

### 3. 加入了新的指令 `!!gamesai reload`
在 0.4.2 版本中，加入了新的指令 `!!gamesai reload`，使用這個指令可以讓你擺脫繁瑣的卸載再載入的過程，直接重新載入設定檔即可看到修改後的效果。

## 鳴謝與聲明
特別感謝望海公社伺服器為此插件的測試提供了基礎。

AI（LLM）模型生成的一切內容與此插件無關。

## 授權條款
本插件使用 MIT 協議，由 yello 持有。