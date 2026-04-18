<div align="center">

# GamesAI

[English](/README.md)  |  [简体中文](/README.zh-CN.md)  |  繁體中文

[回報問題](https://github.com/PengZixuan30/Games_AI/issues/new)  |  [分享想法](https://github.com/PengZixuan30/Games_AI/issues/new)

</div>

> [!NOTE]
> 歡迎使用版本 0.3.2，目前版本修復了一些問題，將公共資料庫的新增資料指令分為覆寫與追加兩種模式。請見[本次更新](#本次更新)

> [!IMPORTANT]
> 0.2.1 版本更新將幫助指令由 `!!openai` 轉為 `!!gamesai`

<details>
<summary>目錄（點擊展開）</summary>

- [GamesAI](#gamesai)
  - [安裝](#安裝)
  - [使用方式](#使用方式)
  - [設定](#設定)
    - [1. system\_message:](#1-system_message)
    - [2. prefix](#2-prefix)
    - [3. permission](#3-permission)
    - [4. base\_url](#4-base_url)
    - [5. ai\_model](#5-ai_model)
    - [6. api\_key](#6-api_key)
    - [7. max\_history](#7-max_history)
  - [鳴謝與聲明](#鳴謝與聲明)
  - [本次更新](#本次更新)

</details>

## 安裝

在 MCDR 控制台中使用以下指令以安裝插件：

`!!MCDR plugin install games_ai`

---

或者從 [MCDR 插件倉庫](https://mcdreforged.com/zh-CN/plugin/games_ai) 取得並安裝到你的插件目錄內。

如果選擇手動安裝，請先安裝 Python 套件 OpenAI，使用以下指令安裝：
```bash
pip install openai
```

## 使用方式

在任何地方輸入指令 `!!gamesai` 以顯示這個插件的所有功能。

你也可以直接輸入 `!!ask` 向 AI 提問或聊天。

---

輸入 `!!data` 取得關於資料庫指令的資訊。

> [!TIP]
> 更新到 0.3.0 及以上版本時會自動新增資料庫。

`!!data` 的指令如下：

| 指令 | 用途 |
|------|------|
| `!!data write <key> <value>` | 在公共資料庫內新增一筆資料，其中 key 不能包含空格，value 可以是任意字串 |
| `!!data add <key> <value>` | 將 value 追加到公共資料庫中的 key 中，不存在時自動建立新 key |
| `!!data del <key>` | 在公共資料庫內刪除一筆資料，無論 key 是否存在 |
| `!!data read <key>` | 讀取公共資料庫中 key 對應的 value |
| `!!data list` | 讀取公共資料庫中的所有內容 |
| `!!data list keys` | 讀取公共資料庫中的所有 key |

## 設定

預設設定檔結構如下：

```json
{
    "system_message": "使用簡潔的語言回答，但請帶有一定的情感。如果你想取得線上玩家列表，請回覆 get_players；如果你想取得伺服器白名單（即全體成員名單），請回覆 get_whitelist。你是 Minecraft 伺服器的一名機器人",
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
值的型態：str

預設值：見上方檔案中的內容

填入你的預設提示詞，如果不填入此項，則預設使用上面檔案中的值。

### 2. prefix
值的型態：str

預設值：\[GamesAI\]

填入這個 AI 的名稱，以在 AI 的回覆之前加上一個前綴，可以包含 Minecraft 格式化代碼。

### 3. permission
值的型態：int

預設值：3

執行 `!!data` 等指令所必須達到的權限，請見 [MCDR 權限相關文件](https://docs.mcdreforged.com/zh-cn/latest/permission.html)。

### 4. base_url
> [!WARNING]
> 必須填入此項，否則會導致錯誤。

值的型態：str

預設值：\<無\>

填入你的 API 伺服器位址。

### 5. ai_model
> [!WARNING]
> 必須填入此項，否則會導致錯誤。

值的型態：str

預設值：\<無\>

填入你需要使用的 AI 模型。

### 6. api_key
> [!WARNING]
> 必須填入此項，否則會導致錯誤。

值的型態：str

預設值：\<無\>

填入你的 API 金鑰。

### 7. max_history
值的型態：int

預設值：10

填入每個玩家最大可保留的歷史記錄，與公共資料庫無關。

## 鳴謝與聲明

特別感謝望海公社伺服器為此插件的測試提供了基礎。

AI（LLM）模型生成的一切內容與此插件無關。

## 本次更新

本次更新主要區分了 `!!data write` 和 `!!data add` 指令，一個用於覆寫，一個用於追加。

本次更新還在讀取資料（`!!data read`）之後加入了使用 `!!data write` 指令複製到輸入框的功能（例如：key 為 test，value 為 test，則複製到輸入框的文字為 `!!data write test test`），但如果資料過長，可能無法複製；同時也加入了複製到剪貼簿的功能。
