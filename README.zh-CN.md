<div align="center">

# GamesAI

[English](/README.md)  |  简体中文  |  [繁體中文](/README.zh-TW.md)

[反馈问题](https://github.com/PengZixuan30/Games_AI/issues/new)  |  [反馈想法](https://github.com/PengZixuan30/Games_AI/issues/new)

</div>

> [!NOTE]
> 欢迎使用版本0.4.0，当前版本修复了一些问题，加入了多模型支持，加入了自动检查更新的功能。见[本次更新](#本次更新)

> [!IMPORTANT]
> 由于多模型支持的添加，配置文件大改，请注意及时修改配置文件

<details>
<summary>目录(点击展示)</summary>

- [GamesAI](#gamesai)
  - [安装](#安装)
  - [使用](#使用)
  - [配置](#配置)
    - [1.prefix](#1prefix)
    - [2.permission](#2permission)
    - [3.max\_history](#3max_history)
    - [4.all\_ai](#4all_ai)
    - [5.default\_ai](#5default_ai)
  - [本次更新](#本次更新)
    - [1.加入了自动检查更新](#1加入了自动检查更新)
    - [2.加入了多模型支持](#2加入了多模型支持)
  - [鸣谢与声明](#鸣谢与声明)
  - [许可证](#许可证)

</details>

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
> 更新到0.3.0及以上版本时会自动添加数据库

`!!data`的指令如下:
|指令|用途|
|---|---|
|`!!data write <key> <value>`|在公共数据库内添加一条数据，其中key不能包含空格，value可以是任意字符串|
|`!!data add <key> <value>`|将value追加到公共数据库中的key中，不存在时自动创建新key|
|`!!data del <key>`|在公共数据库内删除一条数据，无论key是否存在|
|`!!data read <key>`|读取公共数据库中key对应的value|
|`!!data list`|读取公共数据库中的所有内容|
|`!!data list keys`|读取公共数据库中的所有key|

## 配置

默认配置文件结构如下:

```json
{
  "prefix": "[GamesAI]",
  "permission": 3,
  "max_history": 10,
  "all_ai": {
      "<Your AI ID>":{
          "prompt": "使用简洁的语言回答,但请带有一定的情感,如果你想获取在线玩家列表,请回复get_players;如果你想获取服务器白名单(既全体成员名单),请回复get_whitelist。你是Minecraft服务器的一名机器人",
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

以下是每个参数的简介:

### 1.prefix
值的类型: str

默认值: \[GamesAI\]

填入插件的名称，以在插件的回复之前加上一个前缀，可以包含Minecraft格式化代码

### 2.permission
值的类型：int

默认值：3

执行`!!data`等指令所必须达到的权限，见[MCDR权限相关文档](https://docs.mcdreforged.com/zh-cn/latest/permission.html)


### 3.max_history
值的类型: int

默认值: 10

填入每个玩家最大可的保留历史记录，与公共数据库无关，现在每个玩家的聊天记录将被**所有模型**使用

### 4.all_ai
值的类型: dict

默认值：见文件

填入所有的AI信息，由多个字典组成，每个字典为一个AI模型，字典的键即为插件内部的AI_ID

**prompt**: 这项配置与以前的system_message功能相同，但是你现在需要单独为每一个模型设置

**ai_name**: 这项配置与以前的prefix功能类似，但是你现在需要单独为每一个模型设置，可以包含Minecraft格式化代码

**base_url**, **ai_model**, **api_key**: 与以前的相关配置功能相同，但是你现在需要单独为每一个模型设置

### 5.default_ai
值的类型: str

默认值: \<\Your AI ID\>

填入当用户直接使用`!!ask`时使用的模型，应该填入all_ai字典中的某一个键\(即为插件内部的AI_ID\)，如果错填，会导致无法正常使用`!!ask`指令

## 本次更新
### 1.加入了自动检查更新
这个版本加入了自动检查更新的功能，每24h检查一次\(不可修改\)，如果可以更新，将使用MCDR插件管理器进行更新

### 2.加入了多模型支持
这个版本加入了多模型支持，并允许用户使用`!!ask -m <model> <content>`指令实现多模型切换，也可以继续使用`!!ask`指令，将会使用默认值访问AI。`<model>`项支持模糊识别，即使输入的是不完整的AI_ID或AI的名字，也可以正常访问。

## 鸣谢与声明
特别感谢望海公社服务器为此插件的测试提供了基础

AI\(LLM\)模型生成的一切内容与此插件无关

## 许可证
本插件使用MIT协议，由yello持有