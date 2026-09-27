<div align="center">

# 工具

[English](../en_us/tools.md)  |  [简体中文](../zh_cn/tools.md)  |  繁體中文

[返回 README](../../README.zh-TW.md)

</div>

工具（tools）是提供給模型的**函式**：模型可以主動呼叫它們來做事——查資料、讀檔案、執行指令、操控假人。這一頁講清三件事：插件自帶哪些工具、怎麼自己加工具、以及工具的權限與可見性怎麼決定。

## 1. 內建工具

下表由插件的工具註冊表匯出，`權限` 欄表示**向 AI 提供該工具**所需的最低 MCDR 權限等級，`Bot` 欄表示該工具是否同時提供給自治 Bot 控制器（否則只有聊天 AI 能用）。

<details>
<summary>點擊查看全部內建工具（26 個）</summary>

| 工具 | 參數 | 權限 | Bot | 說明 |
|---|---|:---:|:---:|---|
| `get_online_players` | 無 | 0 | ✅ | 取得線上玩家清單。依賴 `online_player_api` 插件，插件缺失時退回 RCON `list` 查詢 |
| `get_player_position` | `player` | 0 | ✅ | 查詢指定玩家的座標與維度。依賴 `minecraft_data_api` 插件，缺失時該工具不會註冊 |
| `calculator` | `expression` | 0 | ✅ | 四則運算表達式計算器 |
| `item_caculator` | `expression`、`single_limit`（可選） | 0 | ✅ | 計算表達式並換算成「盒 / 組 / 個」，`single_limit` 為單組堆疊數（預設 64） |
| `setting_timer` | `duration` | 0 | ✅ | 等待指定秒數後再繼續 |
| `read_skills` | `skills` | 0 | — | 讀取一個已註冊的技能檔案。**不提供**給 Bot |
| `reload_plugin` | 無 | 0 | — | 熱重載插件，使設定、技能與自訂工具的變更生效 |
| `ai_read_data` | `key` | 0 | — | 讀取公共資料庫中的一個鍵 |
| `ai_read_all_keys` | 無 | 0 | — | 列出公共資料庫的所有鍵 |
| `ai_read_all_data` | 無 | 0 | — | 一次讀取公共資料庫的全部鍵值對 |
| `ai_write_data` | `key`、`value` | 設定權限 | — | 覆寫寫入一筆公共資料 |
| `ai_add_data` | `key`、`value` | 設定權限 | — | 追加寫入一筆公共資料 |
| `ai_del_data` | `key` | 設定權限 | — | 刪除一筆公共資料 |
| `write_skills` | `skills`、`summary`、`content` | 設定權限 | — | 建立或覆寫技能檔案，並登記到技能索引 |
| `modify_skills` | `skills`、`old_string`、`new_string`、`summary`（可選） | 設定權限 | — | 以正規表達式替換修改技能檔案；`summary` 非空時同步更新索引 |
| `delete_skills` | `skills` | 設定權限 | — | 刪除技能檔案並移除索引條目 |
| `read_custom_tools` | 無 | 設定權限 | — | 讀取自訂 `tools.py` 的內容 |
| `modify_custom_tools` | `old_string`、`new_string` | 設定權限 | — | 以正規表達式替換修改自訂 `tools.py` |
| `append_custom_tools` | `tools` | 設定權限 | — | 向自訂 `tools.py` 末尾追加工具程式碼 |
| `run_mineflayer_bot` | 無 | 設定權限 | — | 啟動 Mineflayer 假人 |
| `stop_mineflayer_bot` | 無 | 設定權限 | ✅ | 停止 Mineflayer 假人 |
| `bot_chat` | `message` | 0 | ✅ | 讓假人在公頻發言 |
| `bot_whisper` | `username`、`message` | 0 | ✅ | 讓假人私訊某玩家 |
| `bot_get_state` | 無 | 0 | ✅ | 取得假人的完整狀態（30 餘個欄位） |
| `bot_call_action` | `action`、`params`（可選） | 0 | ✅ | 向假人下發任意動作（`goto`、`dig`、`place`、`attack` 等） |
| `delegate_to_bot` | `task`、`username`（可選） | 0 | ✅ | 把複雜任務交給自治 Bot 控制器，由它自行拆解執行 |

</details>

關於這張表的三點說明：

- **`設定權限`** 指的是 `config.json` 裡的 `permission` 值。該值決定這些工具對**哪個等級**的玩家開放；等級不足的玩家，其 AI 請求裡根本不會出現這些工具，模型也就無從呼叫。
- **`Bot` 欄的差異是有意為之**：發給 Bot 控制器的工具集刻意收窄（例如 `read_skills`、資料庫讀寫、技能與工具管理都不給它），以免自治迴圈在無人監督時改動技能或資料。
- **`perm` 只是第一道門**。內建工具與自訂工具裡的敏感操作，通常還會在函式內部再次檢查呼叫者的實際權限等級（`source.get_permission_level()`）。兩道門都過不了，指令就不會執行。

> [!TIP]
> 需要更多工具時，有三條路：裝 [GamesAI-Extra](https://github.com/PengZixuan30/Games_AI-Extra)（座標點管理、白名單管理、Minecraft Wiki 搜尋等）、在 `tools.py` 裡自己寫、或在自己的 MCDR 插件裡註冊。

## 2. 在 `tools.py` 中自訂工具

自訂工具寫在這個檔案裡：

```
config/games_ai/tools/tools.py
```

插件首次啟動時會產生一份帶範例工具的骨架檔案。它的最小形態是這樣：

```python
from mcdreforged.command.command_source import CommandSource
from games_ai.games_ai_tool import register_tool

@register_tool(description="我的自訂工具")
def my_custom_tool(source: CommandSource, ai_prefix: str):
    return "工具執行完成"
```

三條硬性要求：

1. `from games_ai.games_ai_tool import register_tool` 必須存在；
2. 函式必須帶 `@register_tool(...)` 裝飾器。**沒有裝飾器的公開函式不會註冊**——插件載入時會掃描檔案並把它們列進日誌，提示 `Functions in external tools.py WITHOUT @register_tool() decorator (REJECTED)`。私有輔助函式請以 `_` 開頭，它們會被跳過而不是被判為錯誤；
3. 函式簽名前兩個參數必須是 `source: CommandSource` 與 `ai_prefix: str`，其餘參數與 `parameters` 中宣告的順序一致。

### 參數定義

`description` 與 `parameters` 會**原樣**成為模型的工具說明，所以它們是寫給模型看的提示詞，不是寫給人的註解：

```python
@register_tool(
    description="讀取一個已註冊的技能檔案。執行相關任務前應先讀取它。",
    parameters={
        "type": "object",
        "properties": {
            "skills": {"type": "string", "description": "技能檔案名，例如 skills_management.md"}
        },
        "required": ["skills"]
    }
)
def read_skills(source: CommandSource, ai_prefix: str, skills: str):
    ...
```

- 參數結構遵循 OpenAI function calling 的 JSON Schema；**不寫 `parameters` 就是無參工具**；
- 帶預設值的參數（如 `max_length: int = 3000`）不要放進 `required`，模型可以省略它們；
- `description` 裡值得寫清三件事：**什麼時候用**、**需要什麼前置條件**、**失敗時會回傳什麼**。模型只會看到這段文字和你 `return` 的字串。

### 回傳值

`return` 的字串就是模型看到的全部結果。因此：

- **唯讀工具**回傳內容本身；
- **寫入操作**回傳「做了什麼」（例如 `已執行Minecraft命令：/say hello`），讓模型能確認結果；
- **失敗**回傳可讀原因（`權限不足：需要3級及以上權限`），而不是拋例外或回傳 `None`。

給玩家的提示走 `source.reply(f"{ai_prefix}正在...")`，它只出現在聊天欄，模型看不到。兩者要分開寫。

### 權限

```python
from games_ai.games_ai_tool import register_tool, get_plugin_config_perm

@register_tool(description="管理員專用工具", perm=get_plugin_config_perm)
def my_admin_tool(source: CommandSource, ai_prefix: str):
    if source.get_permission_level() < get_plugin_config_perm():
        return f"權限不足：需要{get_plugin_config_perm()}級及以上權限"
    ...
```

- `perm` 可以是固定整數，也可以是回傳整數的零參函式；`get_plugin_config_perm` 會動態跟隨 `config.json` 的 `permission` 變化，改設定後無需改程式碼；
- **`perm` 只控制「工具是否交給模型」**。一旦工具發出去了，真正執行時仍應像上面那樣再查一次呼叫者等級——因為工具是**代表提問玩家**執行的，而模型可能被誘導去呼叫它。
- 若還需要按等級區分**同一工具的不同行為**，把等級判斷寫進函式內即可（例如一個工具在 4 級時不限指令，在 1/3 級時只允許白名單內的指令）。

### 給自治 Bot 使用

預設情況下自訂工具只給聊天 AI 用。要讓 Bot 控制器也能呼叫，疊加第二個裝飾器：

```python
from games_ai.games_ai_tool import register_tool, register_bot_tool

@register_tool(description="讓假人把物品丟給玩家")
@register_bot_tool()
def give_item(source: CommandSource, ai_prefix: str, player: str):
    ...
```

Bot 控制器在無人監督的迴圈裡呼叫這些工具，因此**只給那些冪等或可安全重試的工具加這個裝飾器**。

### 讓 AI 自己寫

`read_custom_tools`、`modify_custom_tools`、`append_custom_tools` 三個工具的組合，讓 AI 能讀取、精確編輯、追加這個檔案；改完後它應當呼叫 `reload_plugin` 讓變更生效。內建技能 `custom_tools_management.md` 會強制它先向你確認需求、參數、權限等級與期望回傳值，再動手寫程式碼。

編輯採用**正規表達式替換**語意：`old_string` 是 Python 正規表達式（對整份檔案匹配），`new_string` 支援 `\1`、`\g<name>` 反向引用，**所有匹配都會被替換**；正規表達式不合法或匹配不到時退回按字面文字替換，仍匹配不到則不寫入任何內容並明確告知模型。

### 依賴與載入行為

`tools.py` 是**普通 Python 模組**，插件在每次載入與熱重載時執行它：

- 頂部 `import` 的第三方套件必須真實存在。`import requests` 之類的敘述一旦失敗，整個檔案載入失敗、**所有**自訂工具都不會註冊（日誌會給出原因）；
- 因此需要外部依賴時，要嘛先用 pip 裝好，要嘛把 `import` 放進函式內部並在失敗時回傳可讀錯誤；
- 每次 `!!gamesai reload` 都會重新執行該檔案，所以改動工具程式碼不需要重啟伺服器。

> [!WARNING]
> 自訂工具能對伺服器做**真實且可能不可逆**的改動：改檔案、執行指令、裝依賴、重啟插件都只是一次函式呼叫。如果你提供了這類工具，請在相應技能檔案裡寫清「必須先確認」的規則，並在函式內部按等級收緊——技能約束模型，函式內的檢查才是執行時的最後一道防線。

## 3. 在自己的 MCDR 插件中註冊工具

不修改 `tools.py`，直接在插件程式碼裡註冊：

```python
from games_ai.games_ai_tool import register_tool, register_bot_tool

@register_tool(
    description="你的工具說明",
    parameters={...}          # 可選
)
@register_bot_tool()          # 可選：讓 Bot 控制器也能呼叫
def my_plugin_tool(source: CommandSource, ai_prefix: str, ...):
    source.reply(f"{ai_prefix}正在執行...")
    return "工具執行結果"
```

要點：

- 你的插件必須在 `mcdreforged.plugin.json` 中宣告依賴，以確保 GamesAI 先載入：

```json
{
    "id": "my_plugin",
    "dependencies": {
        "mcdreforged": ">=2.15.0",
        "games_ai": ">=0.6.1"
    }
}
```

- 用 `@register_bot_tool()` 時把版本門檻設為 `>= 0.6.0` 以上；
- 以插件身分註冊的工具與內建工具、`tools.py` 裡的工具**完全等價**：同樣的權限規則、同樣出現在模型的可呼叫清單裡；
- **凡是註冊過工具的插件，都會在 GamesAI 熱重載時自動重載**，工具程式碼始終跟隨最新版本，無需額外處理。若你的插件只註冊技能（不註冊工具），或需要自己的重載邏輯，再使用 `register_self()`——見[熱重載](hot-reload.md#熱重載)。

## 4. 排查

| 現象 | 檢查點 |
|---|---|
| AI 說沒有某個工具可用 | `config.json` 的 `permission` 是否高於該玩家等級（`perm` 更高的工具根本不會發給模型） |
| 自訂工具全部失效 | MCDR 日誌裡搜 `[tools_interpreter]`：載入失敗會印出例外原因；被拒絕的函式會列在 `REJECTED` 後面 |
| 工具被呼叫但什麼都沒發生 | 函式內部的等級檢查回傳了「權限不足」字串——模型會看到這句話，但不會執行任何操作 |
| 改完 `tools.py` 沒生效 | 執行 `!!gamesai reload`，或讓 AI 呼叫 `reload_plugin` |
| 想知道某個工具到底傳了什麼給模型 | 開 `!!gamesai debug`，工具呼叫與回傳值都會進日誌；工具本身的定義可用 `read_custom_tools` 查看 |
