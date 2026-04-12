# GamesAI

English | [简中](/README.zh-CN.md) | [繁中](/README.zh-TW.md)

> [!NOTE]
> Welcome to version 0.3.1. This release fixes several issues, adds the ability to query key lists and value lists from public databases, and introduces support for Traditional Chinese \(Taiwan\).

> [!IMPORTANT]
> Version 0.2.1 changes the help command from `!!openai` to `!!gamesai`.

## Installation

Use the following command in the MCDR console to install the plugin:

`!!MCDR plugin install games_ai`

---

Alternatively, get and install it from the [MCDR Plugin Repository](https://mcdreforged.com/en/plugin/games_ai) into your plugin directory.

If you choose manual installation, please install the Python package OpenAI first using the following command:

```bash
pip install openai
```

## Usage

Enter the command `!!gamesai` anywhere to display all features of this plugin.

You can also directly enter `!!ask` to ask questions or chat with the AI.

---

Enter `!!data` to get information about database commands.

> [!TIP]
> When updating to version 0.3.0 or higher, the database will be automatically added.

The commands for `!!data` are as follows:

|Command|Purpose|
|---|---|
|`!!data add <key> <value>`|Adds a piece of data to the public database, where key cannot contain spaces and value can be any string.|
|`!!data del <key>`|Deletes a piece of data from the public database, regardless of whether the key exists.|
|`!!data read <key>`|Reads the value corresponding to the key in the public database.|
|`!!data list`|Read all contents from the public database.|
|`!!data list keys`|Read all keys from the public database.|

## Configuration

The default configuration file structure is as follows:

```json
{
    "system_message": "Use concise language to answer, but with a certain degree of emotion, always use language zh_cn. If you want to get a list of online players, reply get_players; if you want to get the server whitelist (i.e., the list of all members), reply get_whitelist. You are a bot on a Minecraft server.",
    "prefix": "[GamesAI]",
    "permission": 3,
    "base_url":"<Your API Base URL>",
    "ai_model":"<Your AI Model>",
    "api_key":"<Your API Key>",
    "max_history": 10
}
```

---

The following is a brief introduction to each parameter:

### 1. system_message
Value type: str

Default value: See the content in the file above

Description: Enter your default prompt. If this item is left empty, the value in the file above will be used by default.

### 2. prefix
Value type: str

Default value: \[GamesAI\]

Description: Enter the name of this AI to add a prefix before the AI's replies, which can contain Minecraft formatting codes.

### 3. permission
Value type: int

Default value: 3

Description: The minimum permission level required to execute commands such as !!data. See MCDR Permission Documentation (https://docs.mcdreforged.com/zh-cn/latest/permission.html).

### 4. base_url
> [!WARNING]
> This item must be filled in, otherwise MCDR will unload the plugin directly.

Value type: str

Default value: None

Description: Enter your API server address.

### 5. ai_model
> [!WARNING]
> This item must be filled in, otherwise MCDR will unload the plugin directly.

Value type: str

Default value: None

Description: Enter the AI model you wish to use.

### 6. api_key
> [!WARNING]
> This item must be filled in, otherwise MCDR will unload the plugin directly.

Value type: str

Default value: None

Description: Enter your API key.

### 7. max_history
Value type: int

Default value: 10

Description: Enter the maximum number of conversation history entries to retain per player. This is unrelated to the public database.
