<div align="center">

# GamesAI for MCDReforged

[English](/README.md)  |  [简体中文](/README.zh-CN.md)  |  繁體中文

[回報問題](https://github.com/PengZixuan30/Games_AI/issues/new)  |  [提供想法](https://github.com/PengZixuan30/Games_AI/discussions/new/choose)  |  [加入Q群](https://qm.qq.com/q/jDQQaUPNmw)

[轉至Fabric版本](https://github.com/PengZixuan30/GamesAI)

</div>

> [!NOTE]
> **GamesAI 插件/模組 QQ 交流群：849544707** — 歡迎加入交流群討論問題、回饋建議，以及分享 prompt、skills、tools 等設定！

> [!NOTE]
> 歡迎使用版本 0.5.11！當前版本修復了一個關鍵競態條件 Bug，該 Bug 在使用阻塞工具（如 `setting_timer`）時會導致 HTTP 400 錯誤和歷史記錄損壞。見[本次更新](#本次更新)

> [!IMPORTANT]
> **0.5.10 破壞性變更**：`thinking` 布林設定已被通用 `extra_body` 字典替代。如果你使用了 `"thinking": true`，必須遷移為 `"extra_body": {"thinking": {"type": "enabled"}}`。詳見[遷移指南](#1-extra_body--通用-api-參數設定破壞性變更)。

> [!NOTE]
> **0.5.11 Bug 修復**：修復了阻塞工具（如 `setting_timer`）執行期間，不完整的 tool_calls 洩露到共享歷史導致的競態條件，該問題會造成持續的 HTTP 400 錯誤和歷史記錄損壞。詳見[本次更新](#version-0511)。

<details>
<summary>目錄（點擊展開）</summary>

- [GamesAI for MCDReforged](#gamesai-for-mcdreforged)
  - [安裝](#安裝)
  - [使用](#使用)
  - [設定](#設定)
    - [1.prefix](#1prefix)
    - [2.permission](#2permission)
    - [3.max\_history](#3max_history)
    - [4.all\_ai](#4all_ai)
    - [5.default\_ai](#5default_ai)
  - [工具、Skills 與自訂工具](#工具skills-與自訂工具)
    - [工具](#工具)
    - [Skills 技能](#skills-技能)
    - [自訂工具](#自訂工具)
  - [本次更新](#本次更新)
    - [Version 0.5.11](#version-0511)
      - [1. 歷史記錄競態條件修復](#1-歷史記錄競態條件修復)
    - [Version 0.5.10](#version-0510)
      - [1. `extra_body` — 通用 API 參數設定（破壞性變更）](#1-extra_body--通用-api-參數設定破壞性變更)
    - [Version 0.5.9](#version-059)
      - [1. System 訊息重構](#1-system-訊息重構)
      - [2. 新增 `ai_read_all_data` 工具](#2-新增-ai_read_all_data-工具)
      - [3. 資料庫即時注入](#3-資料庫即時注入)
      - [4. Thinking 訊息樣式](#4-thinking-訊息樣式)
      - [5. Bug 修復與穩定性](#5-bug-修復與穩定性)
  - [致謝與聲明](#致謝與聲明)
  - [贊助與貢獻者名單](#贊助與貢獻者名單)
  - [授權條款](#授權條款)

</details>

## 安裝

在 MCDR 主控台中使用下列指令以安裝插件：

`!!MCDR plugin install games_ai`

---

或者從 [MCDR 插件倉庫](https://mcdreforged.com/plugin/games_ai) 取得並安裝到你的插件目錄中。

如果選擇手動安裝，請先安裝 Python 套件 `openai` 和 `requests`，使用下列指令安裝：

```bash
pip install openai requests
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
  "default_ai": "<Your AI ID>"
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

## 工具、Skills 與自訂工具

### 工具
GamesAI 插件提供了許多內建工具，請見下表。如果你想要更多工具，可以選擇[向作者投稿](https://github.com/PengZixuan30/Games_AI/issues/new)或使用[自訂工具](#自訂工具)。

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
|add_pos_pos|`name`、`pos`、`dimension`|在指定位置新增一個座標點。依賴於 `where2go` 或 `location_marker` 插件，兩者都存在時優先使用 `where2go`，均不存在時自動關閉此工具。|
|add_pos_here|`name`|在玩家的位置新增一個座標點，主控台執行時自動關閉此工具。依賴於 `where2go` 或 `location_marker` 插件，兩者都存在時優先使用 `where2go`，均不存在時自動關閉此工具。|
|remove_pos|`name`|刪除一個座標點，`where2go` 版本會自動將 name 轉換為 id。依賴於 `where2go` 或 `location_marker` 插件，兩者都存在時優先使用 `where2go`，均不存在時自動關閉此工具。|
|search_pos|`name`|搜尋一個座標點。依賴於 `where2go` 或 `location_marker` 插件，兩者都存在時優先使用 `where2go`，均不存在時自動關閉此工具。|
|get_all_pos|無|取得所有座標點列表。依賴於 `where2go` 或 `location_marker` 插件，兩者都存在時優先使用 `where2go`，均不存在時自動關閉此工具。|
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
|reload_plugin|無|熱重載插件以套用設定、技能和自訂工具的變更，不會遺失聊天記錄||ai_del_data|`key`|刪除資料庫中的一筆資料。|

</details>

### Skills 技能

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

> [!TIP]
> GamesAI 內建了兩個**技能檔案**：`skills_management.md`（如何管理技能檔案）和 `custom_tools_management.md`（如何修改自訂工具）。AI 在修改技能或工具之前會自動讀取這些檔案。

> [!TIP]
> Skills 就像 AI 的「標準作業程序 (SOP)」——確保 AI 每次都遵循正確的工作流程。

### 自訂工具
透過修改 `config/games_ai/tools/tools.py` 檔案來實作自訂工具。

先來看看預設值：

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
> 在 0.5.7+ 版本中，AI 可以**自主讀取、修改和追加**自訂工具檔案。只需讓 AI 幫你新增工具——它會先讀取目前檔案，編寫新程式碼（使用 `append_custom_tools` 追加而非覆蓋），然後重載插件。

可見，這是非常簡單的結構。

接下來我將告訴你如何實作，以下面的例子來說明：搜尋 baidu.com。

<details>

<summary>點擊展開</summary>

想要知道如何實作搜尋 baidu.com，參考 GamesAI 原始碼中的工具 `search_minecraft_wiki` 無疑是最好的選擇：

```python
@register_tool(description="搜尋 Minecraft Wiki 以取得相關資訊，請不要使用此方法搜尋與 Minecraft 無關的內容。如果回傳了 Search results 頁面，你可以先瀏覽此頁面，再進行一次精確查詢", tr_key="searching_minecraft_wiki", parameters={
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "要搜尋的內容，例如某個物品、怪物、機制等的名稱。"
        }
    },
    "required": ["query"]
})
def search_minecraft_wiki(source: CommandSource, ai_prefix: str, query: str):
    source.reply(f'{ai_prefix}{source.get_server().rtr("games_ai.tools.searching_minecraft_wiki", query=query)}')
    lang = source.get_server().get_mcdr_language()
    if lang == "en_us":
        search_url = f"https://minecraft.wiki/?search={query}"
    else:
        search_url = f"https://zh.minecraft.wiki/?search={query}"
    response = requests.get(search_url)
    if response.status_code == 200:
        return f"以下是搜尋內容 {query} 的結果：\n{response.content.decode('utf-8')}"
    else:
        return "無法存取 Minecraft Wiki 進行搜尋"
```

首先來看工具的註冊，其中的 `description` 類似於提示詞，是必填項，是提供給 AI 的；其中的 `tr_key` 是內部方法，外部編寫 `tools.py` 時不需要包含此項；而 `parameters` 就是 AI 需要傳入的參數，可根據實際情況決定是否填寫，其中的 `properties` 用於填寫所有傳入參數，其中的 `required` 項則表示有哪些參數是必填的，注意 `properties` 與函式定義中傳入參數的位置關係，需要一一對應。

例如：

```python
@register_tool(description="搜尋百度")
```

但是，搜尋百度肯定需要傳入搜尋內容，所以：

```python
@register_tool(description="搜尋百度", parameters={
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "要搜尋的內容"
        }
    },
    "required": ["query"]
})
```

好了，你已經學會如何註冊工具了，接下來就可以寫函式定義了：

```python
def search_baidu(source: CommandSource, ai_prefix: str, query: str):
```

上面的程式碼中，`source` 和 `ai_prefix` 項必須編寫，因為它們始終會被傳入。

接下來寫函式本體：

```python
def search_baidu(source: CommandSource, ai_prefix: str, query: str):
    ...
    return ...
```

函式本體中可以是任何你需要的操作，最後記得一定要 `return`，否則 AI 將無法正確處理結果。

`tools.py` 的完整範例：

```python
import requests
from games_ai.games_ai_tool import register_tool

@register_tool(
    description="使用百度搜尋網際網路上的資訊。當你需要尋找即時資訊、新聞、百科知識等時使用此工具。",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "要在百度搜尋的關鍵字或問題"
            }
        },
        "required": ["query"]
    }
)
def search_baidu(source, ai_prefix: str, query: str):
    source.reply(f'{ai_prefix}正在搜尋百度：{query}...')

    try:
        url = "https://www.baidu.com/s"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        response = requests.get(url, params={"wd": query}, headers=headers, timeout=10)

        if response.status_code != 200:
            return f"百度搜尋失敗，HTTP 狀態碼：{response.status_code}"

        # 簡單擷取頁面文字（移除 HTML 標籤）
        import re
        text = response.text
        # 移除 script 和 style 標籤內容
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # 移除 HTML 標籤
        text = re.sub(r'<[^>]+>', '', text)
        # 合併多餘空白
        text = re.sub(r'\s+', ' ', text).strip()

        # 截斷過長內容（保留前 3000 個字元，適合 AI 上下文）
        max_len = 3000
        if len(text) > max_len:
            text = text[:max_len] + "\n...（內容已截斷）"

        return f"百度搜尋「{query}」的結果：\n{text}"

    except requests.Timeout:
        return "百度搜尋請求逾時，請稍後重試"
    except Exception as e:
        return f"百度搜尋出錯：{str(e)}"
```

</details>

## 本次更新

### Version 0.5.11

#### 1. 歷史記錄競態條件修復

修復了對話歷史系統中的一個關鍵競態條件，該問題在使用 `setting_timer` 等阻塞工具時觸發：

- **問題**：當工具函式阻塞請求執行緒時（如計時器中的 `time.sleep()`），包含 `tool_calls` 的 assistant 訊息會立即寫入共享歷史列表，但此時工具結果尚未回傳。如果在阻塞期間發起另一個請求，該請求會讀到不完整的對話（有 assistant tool_calls 但無 tool result），導致 API 回傳 HTTP 400 錯誤。此污染狀態會持續影響後續所有請求，直到手動清除歷史記錄。
- **修復**：引入基於 `threading.Lock` 的執行緒安全歷史管理，按使用者+AI 組合加鎖。每個請求現在操作歷史的本地副本，儲存時使用 `extend`（追加模式）而非覆寫寫入，確保多執行緒歷史按時間順序正確保留，互不覆蓋。

### Version 0.5.10

#### 1. `extra_body` — 通用 API 參數設定（破壞性變更）

之前的 `thinking` 布林設定項已被替換為通用的 `extra_body` 字典。請參考各 API 提供商的說明以編寫此項。

> [!WARNING]
> **破壞性變更**：如果你之前使用了 `"thinking": true`，請按如下方式遷移：
>
> ```json
> // 之前 (0.5.9)
> { "thinking": true }
>
> // 之後 (0.5.10) — 適用於 DeepSeek 使用者
> { "extra_body": { "thinking": { "type": "enabled" } } }
> ```
>
> 對於其他 API 提供商，請查閱其文件以了解正確的 `extra_body` 格式。

### Version 0.5.9

#### 1. System 訊息重構

發送給 AI 的 system 提示詞現已重構為 **四條獨立訊息**：

1. **目前時間與語言** — 目前伺服器時間和 MCDR 語言設定
2. **AI 提示詞** — `all_ai` 中設定的模型專屬 system prompt
3. **已註冊 Skills** — 目前已註冊的技能列表（含內建技能）
4. **資料庫內容** — 目前公共資料庫的資料

這一分離提升了對 system 訊息格式有嚴格要求的模型（如 DeepSeek）的相容性，同時也讓提示詞結構更清晰、易於維護。

#### 2. 新增 `ai_read_all_data` 工具

新增內建工具 `ai_read_all_data`，允許 AI 一次性讀取公共資料庫中的所有鍵值對。此前 AI 需要先呼叫 `ai_read_all_keys` 取得所有 key，再逐個呼叫 `ai_read_data` 讀取——現在可以一步完成。

#### 3. 資料庫即時注入

每次 `!!ask` 請求時，目前公共資料庫的內容會自動注入到 system 訊息中。這意味著 AI 無需先呼叫工具就能掌握最新的資料庫狀態，提升資料相關查詢的回應品質。

#### 4. Thinking 訊息樣式

「正在思考⋯⋯」狀態訊息現在使用 Minecraft 灰色格式（`§7...§r`），使其與 AI 的實際回覆在視覺上有明顯區分。

#### 5. Bug 修復與穩定性

- 修復了 `ai_read_all_data` 回傳非字串值（`list[tuple]`）導致 DeepSeek 等嚴格 API 回傳 HTTP 400 錯誤的問題。工具呼叫結果現在始終回傳正確格式的字串。

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
