# GamesAI

[English](/README.md) | 中文

> [!NOTE]
> 欢迎使用版本0.3.0，当前版本加入了公共数据库，修复了一些问题

> [!IMPORTANT]
> 0.2.1版本更新将帮助命令由`!!openai`转为`!!gamesai`

## 安装

在MCDR控制台中使用如下命令以安装插件

`!!MCDR plugin install games_ai`

---

或者在[MCDR插件仓库](https://mcdreforged.com/zh-CN/plugin/games_ai)中获取并安装到你的插件目录内

如果选择手动安装，请先安装Python包OpenAI,使用如下命令安装
```bash
pip install openai
```

## 使用

在任何地方输入命令`!!gamesai`以显示这个插件的所有功能

你也可以直接输入`!!ask`向AI提问或者聊天

---

输入`!!data`获取有关数据库指令的信息

> [!TIP]
> 更新到当前版本时会自动添加数据库

`!!data`的指令如下:
|指令|用途|
|---|---|
|`!!data add <key> <value>`|在公共数据库内添加一条数据，其中key不能包含空格，value可以是任意字符串|
|`!!data del <key>`|在公共数据库内删除一条数据，无论key是否存在|
|`!!data read <key>`|读取公共数据库中key对应的value|

## 配置

默认配置文件结构如下:

```json
{
    "system_message": "使用简洁的语言回答,但请带有一定的情感,始终使用语言为zh_cn,如果你想获取在线玩家列表,请回复get_players;如果你想获取服务器白名单(既全体成员名单),请回复get_whitelist。你是Minecraft服务器的一名机器人",
    "prefix": "[GamesAI]",
    "permission": 3,
    "base_url":"<Your API Base URL>",
    "ai_model":"<Your AI Model>",
    "api_key":"<Your API Key>",
    "max_history": 10
}
```

以下是每个参数的简介:

### 1.system_message:
值的类型: str

默认值：见上方文件中的内容

填入你的默认提示词，如果不填入此项，则默认使用上面文件中的值

### 2.prefix
值的类型: str

默认值: \[GamesAI\]

填入这个AI的名称，以在AI的回复之前加上一个前缀，可以包含Minecraft格式化代码

### 3.permission
值的类型：int

默认值：3

执行`!!data`等指令所必须达到的权限，见[MCDR权限相关文档](https://docs.mcdreforged.com/zh-cn/latest/permission.html)

### 4.base_url
> [!WARNING]
> 必须填入此项，否则MCDR将会直接卸载插件

值的类型: str

默认值：<无>

填入你的API服务器地址

### 5.ai_model
> [!WARNING]
> 必须填入此项，否则MCDR将会直接卸载插件

值的类型: str

默认值: <无>

填入你需要使用的AI模型

### 6.api_key
> [!WARNING]
> 必须填入此项，否则MCDR将会直接卸载插件

值的类型: str

默认值: <无>

填入你的API密钥

### 6.max_history
值的类型: int

默认值: 10

填入每个玩家最大可的保留历史记录，与公共数据库无关
