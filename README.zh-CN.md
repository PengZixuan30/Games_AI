<div align="center">

# GamesAI

[English](/README.md)  |  简体中文  |  [繁體中文](/README.zh-TW.md)

[反馈问题](https://github.com/PengZixuan30/Games_AI/issues/new)  |  [反馈想法](https://github.com/PengZixuan30/Games_AI/issues/new)

</div>

> [!NOTE]
> 欢迎使用版本0.4.2，当前版本修复了一些问题，加入了AI自动查询Minecraft Wiki的功能，重构了部分代码结构。见[本次更新](#本次更新)

> [!IMPORTANT]
> 由于0.4.0版本起的多模型支持的添加，配置文件大改，请注意及时修改配置文件

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
    - [1.加入了AI自动查询Minecraft Wiki的功能](#1加入了ai自动查询minecraft-wiki的功能)
    - [2.重构了部分代码结构](#2重构了部分代码结构)
    - [3.加入了新的指令`!!gamesai reload`](#3加入了新的指令gamesai-reload)
  - [鸣谢与声明](#鸣谢与声明)
  - [许可证](#许可证)

</details>

## 安装

在MCDR控制台中使用如下命令以安装插件

`!!MCDR plugin install games_ai`

---

或者在[MCDR插件仓库](https://mcdreforged.com/zh-CN/plugin/games_ai)中获取并安装到你的插件目录内

如果选择手动安装，请先安装Python包OpenAI和requests，使用如下命令安装
```bash
pip install openai requests
```

## 使用

在任何地方输入命令`!!gamesai`以显示这个插件的所有功能

`!!gamesai`的指令如下:
|指令|用途|
|---|---|
|`!!gamesai clear`|清除玩家的历史聊天记录，历史聊天记录与公共数据库无关|
|`!!gamesai clearall`|清除所有玩家的历史聊天记录，历史聊天记录与公共数据库无关|
|`!!gamesai reload`|重新加载插件配置文件|
|`!!gamesai check`|检查插件更新|

---

你也可以直接输入`!!ask`向AI提问或者聊天或者帮你做一些事情

`!!ask`的指令如下:
|指令|用途|
|---|---|
|`!!ask <content>`|向AI提问或者聊天或者帮你做一些事情，content为你想让AI做的事情或者你想问AI的问题|
|`!!ask -m <model> <content>`|使用指定的模型向AI提问或者聊天或者帮你做一些事情，model为你想使用的模型的AI_ID或昵称，content为你想让AI做的事情或者你想问AI的问题|

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
          "prompt": "使用简洁的语言回答,但请带有一定的情感,你是Minecraft服务器的一名机器人",
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

填入每个玩家最大可的保留历史记录，与公共数据库无关

### 4.all_ai
值的类型: dict

默认值：见文件

填入所有的AI信息，由多个字典组成，每个字典为一个AI模型，字典的键即为插件内部的AI_ID

**prompt**: 这项配置用于为每个AI编写提示词

**ai_name**: 这项配置与prefix功能类似，但是你现在需要单独为每一个模型设置，可以包含Minecraft格式化代码

**base_url**, **ai_model**, **api_key**: 与以前的相关配置功能相同，但是你现在需要单独为每一个模型设置

**thinking**: 这项配置用于 启用/禁用 模型的思考模式，不填时默认为false，切勿为没有思考模式的模型启用此项，那可能会出错

### 5.default_ai
值的类型: str

默认值: \<Your AI ID\>

填入当用户直接使用`!!ask`时使用的模型，应该填入all_ai字典中的某一个键\(即为插件内部的AI_ID\)，如果错填，会导致无法正常使用`!!ask`指令

## 本次更新
### 1.加入了AI自动查询Minecraft Wiki的功能
在0.4.2版本中，加入了AI自动查询Minecraft Wiki的功能，当用户使用`!!ask`指令提问时，AI会自动判断用户的问题是否与Minecraft相关，如果相关，会自动查询Minecraft Wiki并将查询结果作为提示词的一部分，以提供更准确的回答

### 2.重构了部分代码结构
在0.4.2版本中，重构了部分代码结构，以提高代码的可读性和可维护性，同时也为未来的自定义skills功能做好了准备

### 3.加入了新的指令`!!gamesai reload`
在0.4.2版本中，加入了新的指令`!!gamesai reload`，使用这个指令可以让你摆脱繁琐的卸载再加载的过程，直接重新加载配置文件即可看到修改后的效果

## 鸣谢与声明
特别感谢望海公社服务器为此插件的测试提供了基础

AI\(LLM\)模型生成的一切内容与此插件无关

## 许可证
本插件使用MIT协议，由yello持有