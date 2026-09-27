<div align="center">

# 熱重載

[English](../en_us/hot-reload.md)  |  [简体中文](../zh_cn/hot-reload.md)  |  繁體中文

[返回 README](../../README.zh-TW.md)

</div>

GamesAI 提供了完善的熱重載機制，讓你在不重啟伺服器的情況下套用設定、工具和技能的變更。

## 觸發熱重載

熱重載可透過以下方式觸發：

|方式|說明|
|---|---|
|`!!gamesai reload`|管理員手動執行，重新載入全部設定、工具與技能。|
|`!!gamesai config set <key> <value>`|修改設定項後自動觸發重載。|
|AI 工具 `reload_plugin`|AI 在修改工具程式碼或技能檔案後呼叫，確保變更立即生效。|
|`!!aibot set <key> <value>`|修改 Bot 設定後自動觸發重載。|

## 重載期間發生了什麼

執行熱重載時，插件會依次執行以下操作：

1. **重新讀取設定檔** (`config/games_ai/config.json`) — 套用 `prefix`、`permission`、`all_ai`、`default_ai` 等全部設定變更（含單模型 `context_window`）。
2. **全量重建工具註冊（0.6.4+）** — 徹底清空工具註冊表，然後從所有來源重建：內建工具透過註冊重放恢復、自訂 `tools.py` 重新匯入、註冊過工具的插件被重新載入以重新執行註冊程式碼（見第 4、6 步）。
3. **重新載入 Skills** (`config/games_ai/skills/skills.json`) — 刷新技能索引，AI 系統提示中的可用技能列表同步更新。
4. **重新載入自訂工具** (`config/games_ai/tools/tools.py`) — 熱載入自訂工具程式碼，無需重啟 MCDR。
5. **重啟 Mineflayer Bot**（如已啟用）— 停止現有 Bot 程序和 WebSocket 連線，套用新設定後重新啟動。
6. **重載註冊過工具的插件與已註冊的擴展插件** — 重新載入所有透過 `@register_tool` 註冊過工具的第三方插件（0.6.4 起自動追蹤）以及 `REGISTER_PLUGIN_LIST` 中的插件（[見下方](#讓自己的-mcdr-插件跟隨-gamesai-熱重載)）。重載失敗或找不到的插件會從重載列表中移除。
7. **派發 `games_ai.reload` 事件** — 通知所有監聽了此事件的其他 MCDR 插件（[見下方](#方式二透過監聽事件回應熱重載)）。

> [!NOTE]
> 熱重載**不會遺失**玩家的聊天歷史記錄。

## 讓自己的 MCDR 插件跟隨 GamesAI 熱重載

如果你開發了依賴 GamesAI 的 MCDR 插件（例如註冊了自訂工具或技能），你可能希望插件在 GamesAI 熱重載時同步刷新。GamesAI 提供了兩種方式：

### 方式一：使用 `register_self()` 自動重載（推薦）

這是最簡單的方式。在你的插件 `on_load` 中呼叫 `register_self()`，將插件加入 GamesAI 的重載列表：

> [!NOTE]
> 自 0.6.4 起，透過 `@register_tool` 註冊過工具的插件在熱重載時會自動重新載入（由工具註冊表自動追蹤），因此 `register_self()` 僅適用於未註冊工具的插件（如只註冊技能的插件）或需要自訂重載邏輯的插件。

```python
from games_ai.register_extra_plugin import register_self

def on_load(server, old):
    register_self(server.get_self_metadata().id)
```

每次執行 `!!gamesai reload` 時，你的插件會被 MCDR 自動重載（呼叫 `server.reload_plugin()`）。如果重載失敗，插件會被卸載並從重載列表中移除。

如果你的插件需要**自訂重載邏輯**（不僅僅呼叫預設的 `reload_plugin`），可以傳入自訂 reloader 函式作為第二個參數。除了普通函式外，也可以傳入方法（`self.xxx`）或 lambda 運算式：

```python
from mcdreforged.command.command_source import CommandSource
from games_ai.register_extra_plugin import register_self

def my_reloader(source: CommandSource):
    # 自訂重載邏輯
    server = source.get_server()
    server.logger.info("執行我的自訂重載邏輯...")
    # 例如：重新讀取自己的設定檔、重建資料庫連線等

def on_load(server, old):
    register_self(server.get_self_metadata().id, my_reloader)
```

> [!IMPORTANT]
> 自訂 reloader 函式的**第一個參數必須為 `CommandSource`**（如上例中的 `source`），GamesAI 會將觸發熱重載的命令源傳入該參數。

當自訂 reloader 拋出例外時，插件會被自動卸載並從重載列表中移除，同時在日誌中記錄失敗原因。

### 方式二：透過監聽事件回應熱重載

如果你的插件不想被卸載/重載，只想在 GamesAI 熱重載完成時收到通知並執行一些邏輯，可以監聽 `games_ai.reload` 事件：

```python
from mcdreforged.api.all import *

def on_load(server: PluginServerInterface, old):
    server.register_event_listener("games_ai.reload", on_gamesai_reload)

def on_gamesai_reload(server: PluginServerInterface):
    server.logger.info("GamesAI 已完成熱重載，我正在同步處理...")
    # 例如：重新讀取 GamesAI 的最新設定
    # 例如：刷新自己快取的工具列表
```

> [!NOTE]
> 事件回呼的第一個參數始終是 `PluginServerInterface`，由 MCDR 自動補齊。

> [!TIP]
> `games_ai.reload` 事件在**重載完成後**派發，所以監聽器拿到的已經是重載後的最新狀態。

## 兩種方式對比

`register_self()` 根據是否傳入第二個參數（自訂 reloader）有不同的行為：

|特性|`register_self()` 不傳 reloader|`register_self()` 傳入自訂 reloader|監聽 `games_ai.reload` 事件|
|---|---|---|---|
|觸發時機|重載過程中（第 6 步）|重載過程中（第 6 步）|重載完成後（第 7 步）|
|插件行為|MCDR 卸載後重載（`on_load` 重新執行）|插件保持載入，僅呼叫自訂函式|插件不受影響|
|失敗處理|插件被卸載，從重載列表移除|插件被卸載，從重載列表移除|例外不會卸載插件|
|工具/Skills|`on_load` 自動重新註冊|無需重新註冊（插件未卸載，註冊保持有效）|無需處理|
|適用場景|插件需要完整刷新程式碼|插件只需重讀設定、刷新快取等輕量操作|插件只需收到通知或同步狀態|

> [!NOTE]
> 註冊在 GamesAI 中的工具（`@register_tool`）和 Skills（`register_skills()`）的生命週期與註冊它們的插件綁定。只要插件未被 MCDR 卸載，已註冊的工具和 Skills 就會一直有效。因此使用自訂 reloader 時**無需**重新註冊。
