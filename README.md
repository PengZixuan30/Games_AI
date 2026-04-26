<div align="center">

# GamesAI

English  |  [简体中文](/README.zh-CN.md)  |  [繁體中文](/README.zh-TW.md)

[Report Issue](https://github.com/PengZixuan30/Games_AI/issues/new)  |  [Feedback & Ideas](https://github.com/PengZixuan30/Games_AI/issues/new)

</div>

> [!NOTE]
> Welcome to version 0.4.0. This release fixes several issues, adds multi-model support, and introduces automatic update checking. See [this update](#this-update) for details.

> [!IMPORTANT]
> Due to the addition of multi-model support, the configuration file has undergone major changes. Please update your configuration accordingly.

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
    - [1. Added automatic update checking](#1-added-automatic-update-checking)
    - [2. Added multi-model support](#2-added-multi-model-support)
  - [Acknowledgements \& Disclaimer](#acknowledgements--disclaimer)
  - [License](#license)

</details>

## Installation

Use the following command in the MCDR console to install the plugin:

`!!MCDR plugin install games_ai`

---

Alternatively, you can obtain it from the [MCDR Plugin Repository](https://mcdreforged.com/plugin/games_ai) and install it into your plugin directory.

If you choose to install manually, please install the Python package `openai` first using the following command:
```bash
pip install openai
```

## Usage

Enter the command `!!gamesai` anywhere to display all functions of this plugin.

You can also directly type `!!ask` to ask the AI a question or chat.

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
          "prompt": "Answer concisely but with some emotion. If you want to get the online player list, respond with get_players; if you want to get the server whitelist (i.e., the full member list), respond with get_whitelist. You are a bot in a Minecraft server.",
          "ai_name": "[ServerAI]",
          "base_url": "<Your API Base URL>",
          "ai_model": "<Your AI Model>",
          "api_key": "<Your API Key>"
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

The maximum number of chat history entries to keep per player. This is independent of the public database. Each player's chat history is now shared across **all models**.

### 4. all_ai
Type: dict

Default: As shown in the file.

Contains information for all AI models. It consists of multiple dictionaries, each representing an AI model. The key of each dictionary is the internal **AI_ID** used by the plugin.

**prompt**: This option serves the same function as the previous **system_message**, but you now need to set it separately for each model.

**ai_name**: This option serves a similar function as the previous **prefix**, but you now need to set it separately for each model. Minecraft formatting codes are allowed.

**base_url**, **ai_model**, **api_key**: Same functionality as previous related settings, but you now need to set them separately for each model.

### 5. default_ai
Type: str

Default: \<\Your AI ID\>

The model used when a user simply types `!!ask` (without specifying a model). This should be one of the keys inside the `all_ai` dictionary (i.e., an internal `AI_ID`). If set incorrectly, the `!!ask` command will not function properly.

## This Update
### 1. Added automatic update checking
This version introduces automatic update checking, which runs every 24 hours (non-configurable). If an update is available, the MCDR plugin manager will be used to perform the update.

### 2. Added multi-model support
This version adds support for multiple AI models. Users can now use the `!!ask -m <model> <content>` command to switch between models, while the simple `!!ask` command continues to use the default model. The `<model>` parameter supports fuzzy matching: even if the user enters an incomplete AI_ID or AI name, the plugin can still recognize it.

## Acknowledgements & Disclaimer
Special thanks to Wanghai Commune Server for providing the foundation for testing this plugin.

Any content generated by AI (LLM) models is independent of this plugin.

## License
This plugin is licensed under the MIT License. Copyright (c) yello.