# Game's AI

[English](/README.md) | [中文](/README.zh-CN.md)

## 安装
在MCDR控制台中使用如下命令以安装插件

`!!MCDR plugin install games_ai`

或者在[MCDR插件仓库](https://mcdreforged.com/zh-CN/plugins)中获取并安装到你的插件目录内

这个插件也需要一些Python包,使用如下命令安装
```bash
pip install openai
```

## 使用
在任何地方输入命令`!!openai`以显示这个插件的所有功能

你也可以直接输入`!!ask`向AI提问或者聊天

## 配置
配置文件结构如下:
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

以下是每个参数的简介:
### 1.system_message:
值的类型: str

填入你的默认提示词，如果不填入此项，则默认使用上面文件中的值

### 2.prefix
值的类型: str

默认值: "\[OpenAI\]"

填入这个AI的名称，以在AI的回复之前加上一个前缀

### 3.base_url
> [!WARNING]
> 必须填入此项，否则MCDR将会直接卸载插件

值的类型: str

默认值:"https://api.deepseek.com"

填入你的API服务器地址

### 4.ai_model
> [!WARNING]
> 必须填入此项，否则MCDR将会直接卸载插件

值的类型: str

默认值: "deepseek-chat"

填入你需要使用的AI模型

### 5.api_key
> [!WARNING]
> 必须填入此项，否则MCDR将会直接卸载插件

值的类型: str

默认值: <无>

填入你的API密钥

### 6.max_history
值的类型: int

默认值: 10

填入每个玩家最大可的保留历史记录
