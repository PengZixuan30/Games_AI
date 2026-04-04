# Games AI

English | [中文](/README.zh-CN.md)

> [!NOTE]
> Welcome to version 0.2.1. This version has updated English support and fixed many legacy issues.

> [!IMPORTANT]
> This update will cause the command to switch from `!!openai` to `!!gamesai`.

## Installation
Use the following command in the MCDR console to install the plugin:

`!!MCDR plugin install games_ai`

Alternatively, download it from the [MCDR Plugin Repository](https://mcdreforged.com/en/plugin/games_ai) and place it in your plugin directory.

This plugin also requires some Python packages. Install them with:
```bash
pip install openai
```

## Usage
Enter the command `!!gamesai` anywhere to display all functions of this plugin.

You can also directly enter `!!ask` to ask questions or chat with the AI.

## Configuration
The configuration file structure is as follows:

```json
{
    "system_message": "Answer in concise language with some emotion, always use en_us language. If you want to get the online player list, reply get_players; if you want to get the server whitelist (i.e., all member list), reply get_whitelist. You are a robot on the Minecraft server",
    "prefix": "[GamesAI]",
    "base_url":"<Your API Base URL>",
    "ai_model":"<Your AI Model>",
    "api_key":"<Your API Key>",
    "max_history": 10
}
```

Below is a description of each parameter:
### 1. system_message:
Type: str

Default: See the content in the file above

Fill in your default prompt. If not filled, the default value above will be used.

### 2. prefix
Type: str

Default: "\[GamesAI\]"

Fill in the name of this AI, which will be added as a prefix before the AI's replies.

### 3. base_url
> [!WARNING]
> This must be filled in, otherwise MCDR will unload the plugin immediately.

Type: str

Default: "https://api.deepseek.com"

Fill in your API server address.

### 4. ai_model
> [!WARNING]
> This must be filled in, otherwise MCDR will unload the plugin immediately.

Type: str

Default: "deepseek-chat"

Fill in the AI model you want to use.

### 5. api_key
> [!WARNING]
> This must be filled in, otherwise MCDR will unload the plugin immediately.

Type: str

Default: <none>

Fill in your API key.

### 6. max_history
Type: int

Default: 10

Fill in the maximum number of history records to keep per player.
