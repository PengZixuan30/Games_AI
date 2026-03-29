# Game's AI

[English](/README.md) | [中文](/README.zh-CN.md)

## Installation

In the MCDR console, use the following command to install the plugin:

`!!MCDR plugin install games_ai`

Alternatively, you can download it from the [MCDR Plugin Repository](https://mcdreforged.com/en/plugins) and place it in your plugin directory.

This plugin also requires some Python packages. Install them with:
```bash
pip install openai
```

## Usage
Enter the command `!!openai` anywhere to display all available functions of this plugin.

You can also use `!!ask` to directly ask questions or chat with the AI.

## Configuration
The configuration file structure is as follows:

```json
{
    "system_message": "使用简洁的语言回答,但请带有一定的情感,始终使用语言为zh_cn,如果你想获取在线玩家列表,请回复get_players;如果你想获取服务器白名单(既全体成员名单),请回复get_whitelist。你是Minecraft服务器的一名机器人",
    "prefix": "[OpenAI]",
    "base_url":"https://api.deepseek.com",
    "ai_model":"deepseek-chat",
    "api_key":"<Your API Key>",
    "max_history": 10
}
```

Below is a description of each parameter:

### 1. system_message
Type: str

Fill in your default system prompt. If left blank, the value shown in the configuration above will be used.

### 2. prefix
Type: str

Default: "[OpenAI]"

The name of the AI, which will be added as a prefix before the AI's replies.

### 3. base_url
> [!WARNING]
> This field is required. If missing, MCDR will unload the plugin immediately.

Type: str

Default: "https://api.deepseek.com"

The API server address.

### 4. ai_model
> [!WARNING]
> This field is required. If missing, MCDR will unload the plugin immediately.

Type: str

Default: "deepseek-chat"

The AI model to be used.

### 5. api_key
> [!WARNING]
> This field is required. If missing, MCDR will unload the plugin immediately.

Type: str

Default: (none)

Your API key.

### 6. max_history
Type: int

Default: 10

The maximum number of conversation history entries to keep per player.
