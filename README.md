<div align="center">

# GamesAI

English  |  [简体中文](/README.zh-CN.md)  |  [繁體中文](/README.zh-TW.md)

[Report Issue](https://github.com/PengZixuan30/Games_AI/issues/new)  |  [Feedback & Ideas](https://github.com/PengZixuan30/Games_AI/issues/new)

</div>

> [!NOTE]
> Welcome to version 0.4.2. This release fixes some issues, adds AI auto-query Minecraft Wiki functionality, and refactors part of the code structure. See [This Update](#this-update) for details.

> [!IMPORTANT]
> Due to the addition of multi-model support starting from version 0.4.0, the configuration file has undergone major changes. Please update your configuration file accordingly.

<details>
<summary>Table of Contents (click to expand)</summary>

- [GamesAI](#gamesai)
  - [Installation](#installation)
  - [Usage](#usage)
  - [Configuration](#configuration)
    - [1. prefix](#1-prefix)
    - [2. permission](#2-permission)
    - [3. max\_history](#3-max_history)
    - [4. all\_ai](#4-all_ai)
    - [5. default\_ai](#5-default_ai)
  - [This Update](#this-update)
    - [1. Added AI auto-query Minecraft Wiki functionality](#1-added-ai-auto-query-minecraft-wiki-functionality)
    - [2. Refactored part of the code structure](#2-refactored-part-of-the-code-structure)
    - [3. Added new command `!!gamesai reload`](#3-added-new-command-gamesai-reload)
  - [Acknowledgements \& Disclaimer](#acknowledgements--disclaimer)
  - [License](#license)

</details>

## Installation

Use the following command in the MCDR console to install the plugin:

`!!MCDR plugin install games_ai`

---

Alternatively, you can obtain it from the [MCDR Plugin Repository](https://mcdreforged.com/plugin/games_ai) and install it into your plugin directory.

If you choose to install manually, please install the Python packages `openai` and `requests` first using the following command:
```bash
pip install openai requests
```

## Usage

Enter the command `!!gamesai` anywhere to display all functions of this plugin.

The `!!gamesai` commands are as follows:
| Command | Description |
|---|---|
| `!!gamesai clear` | Clear the player's chat history. Chat history is independent of the public database. |
| `!!gamesai clearall` | Clear all players' chat history. Chat history is independent of the public database. |
| `!!gamesai reload` | Reload the plugin configuration file. |
| `!!gamesai check` | Check for plugin updates. |

---

You can also directly type `!!ask` to ask the AI a question, chat, or have it do something for you.

The `!!ask` commands are as follows:
| Command | Description |
|---|---|
| `!!ask <content>` | Ask the AI a question, chat, or have it do something for you. `content` is what you want the AI to do or the question you want to ask. |
| `!!ask -m <model> <content>` | Use a specific model to ask the AI. `model` is the AI_ID or nickname of the model you want to use, and `content` is what you want the AI to do or the question you want to ask. |

---

Type `!!data` to get information about database-related commands.

> [!TIP]
> When updating to version 0.3.0 or later, the database will be automatically created.

The `!!data` commands are as follows:

| Command | Description |
|---------|-------------|
| `!!data write <key> <value>` | Add a data entry to the public database. The key cannot contain spaces, while the value can be any string. |
| `!!data add <key> <value>` | Append the value to an existing key in the public database. If the key does not exist, it will be created automatically. |
| `!!data del <key>` | Delete a data entry from the public database. Works regardless of whether the key exists. |
| `!!data read <key>` | Read the value associated with the key from the public database. |
| `!!data list` | Read all contents of the public database. |
| `!!data list keys` | Read all keys in the public database. |

## Configuration

The default configuration file structure is as follows:

```json
{
  "prefix": "[GamesAI]",
  "permission": 3,
  "max_history": 10,
  "all_ai": {
      "<Your AI ID>": {
          "prompt": "Answer concisely but with some emotion. You are a bot in a Minecraft server.",
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

Below is a brief description of each parameter:

### 1. prefix
Type: str

Default: \[GamesAI\]

The plugin's display name, which will be prefixed to the plugin's replies. Minecraft formatting codes are allowed.

### 2. permission
Type: int

Default: 3

The required permission level to execute commands such as `!!data`. See [MCDR Permission Documentation](https://docs.mcdreforged.com/en/latest/permission.html).

### 3. max_history
Type: int

Default: 10

The maximum number of chat history entries to keep per player. This is independent of the public database.

### 4. all_ai
Type: dict

Default: As shown in the file.

Contains information for all AI models. It consists of multiple dictionaries, each representing an AI model. The key of each dictionary is the internal **AI_ID** used by the plugin.

**prompt**: This option is used to write system prompts for each AI model.

**ai_name**: This option is similar to the prefix function, but you now need to set it separately for each model. Minecraft formatting codes are allowed.

**base_url**, **ai_model**, **api_key**: Same functionality as previous related settings, but you now need to set them separately for each model.

**thinking**: This option is used to enable/disable the model's thinking mode. If not specified, it defaults to false. Do not enable this for models that do not support thinking mode, as it may cause errors.

### 5. default_ai
Type: str

Default: \<Your AI ID\>

The model used when a user simply types `!!ask` (without specifying a model). This should be one of the keys inside the `all_ai` dictionary (i.e., an internal `AI_ID`). If set incorrectly, the `!!ask` command will not function properly.

## This Update
### 1. Added AI auto-query Minecraft Wiki functionality
In version 0.4.2, AI auto-query Minecraft Wiki functionality has been added. When a user asks a question using the `!!ask` command, the AI will automatically determine whether the question is related to Minecraft. If it is, it will automatically query the Minecraft Wiki and use the results as part of the prompt to provide more accurate answers.

### 2. Refactored part of the code structure
In version 0.4.2, part of the code structure has been refactored to improve code readability and maintainability, while also laying the groundwork for future custom skills functionality.

### 3. Added new command `!!gamesai reload`
In version 0.4.2, a new command `!!gamesai reload` has been added. This command allows you to bypass the tedious process of unloading and reloading the plugin, and simply reload the configuration file to see the changes take effect.

## Acknowledgements & Disclaimer
Special thanks to Wanghai Commune Server for providing the foundation for testing this plugin.

Any content generated by AI (LLM) models is independent of this plugin.

## License
This plugin is licensed under the MIT License, held by yello.