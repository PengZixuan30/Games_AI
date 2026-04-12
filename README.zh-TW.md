# GamesAI

[English](/README.md) | [简中](/README.zh-CN.md) | 繁中

> [!NOTE]
> 歡迎使用版本 0.3.1，此版本修復了一些問題，加入查詢公共資料庫 key 列表與 value 列表的功能，並加入繁體中文（台灣）支援

> [!IMPORTANT]
> 0.2.1 版本更新將幫助指令由 !!openai 改為 !!gamesai

## 安裝

在 MCDR 主控台中使用以下指令安裝插件

`!!MCDR plugin install games_ai`

---

或者前往 [MCDR 插件倉庫](https://mcdreforged.com/zh-CN/plugin/games_ai) 取得並安裝至你的插件目錄內

如果選擇手動安裝，請先安裝 Python 套件 OpenAI，使用以下指令安裝
```bash
pip install openai
```

## 使用

在任何地方輸入指令 `!!gamesai` 以顯示此插件的所有功能

你也可以直接輸入 `!!ask` 向 AI 提問或聊天

---

輸入 `!!data` 取得資料庫指令的相關資訊

> [!TIP]
> 更新至 0.3.0 及以上版本時會自動新增資料庫

`!!data` 的指令如下：
|指令|用途|
|---|---|
|`!!data add <key> <value>`|在公共資料庫內新增一筆資料，其中 key 不可包含空格，value 可為任意字串|
|`!!data del <key>`|在公共資料庫內刪除一筆資料，無論 key 是否存在|
|`!!data read <key>`|讀取公共資料庫中 key 對應的 value|
|`!!data list`|讀取公共資料庫中的所有內容|
|`!!data list keys`|讀取公共資料庫中的所有 key|

## 設定

預設設定檔結構如下：

```json
{
    "system_message": "請使用簡潔的語言回答，但帶有適度的情感，始終使用語言為 zh_tw，若你想取得線上玩家列表，請回覆 get_players；若你想取得伺服器白名單（即全體成員名單），請回覆 get_whitelist。你是 Minecraft 伺服器的一名機器人",
    "prefix": "[GamesAI]",
    "permission": 3,
    "base_url":"<Your API Base URL>",
    "ai_model":"<Your AI Model>",
    "api_key":"<Your API Key>",
    "max_history": 10
}
```

---

以下是每個參數的簡介：

### 1. system_message:
值的型別：str

預設值：見上方檔案中的內容

填入你的預設提示詞，若未填入此項，則預設使用上方檔案中的值

### 2. prefix
值的型別：str

預設值：\[GamesAI\]

填入此 AI 的名稱，以在 AI 的回覆之前加上一個前置詞，可包含 Minecraft 格式化代碼

### 3. permission
值的型別：int

預設值：3

執行 `!!data` 等指令所需達到的權限，請見 [MCDR 權限相關文件](https://docs.mcdreforged.com/zh-cn/latest/permission.html)

### 4. base_url
> [!WARNING]
> 必須填入此項，否則 MCDR 將會直接卸載插件

值的型別：str

預設值：<無>

填入你的 API 伺服器位址

### 5. ai_model
> [!WARNING]
> 必須填入此項，否則 MCDR 將會直接卸載插件

值的型別：str

預設值：<無>

填入你需要使用的 AI 模型

### 6. api_key
> [!WARNING]
> 必須填入此項，否則 MCDR 將會直接卸載插件

值的型別：str

預設值：<無>

填入你的 API 金鑰

### 7. max_history
值的型別：int

預設值：10

填入每位玩家最大可保留的歷史記錄數量，與公共資料庫無關