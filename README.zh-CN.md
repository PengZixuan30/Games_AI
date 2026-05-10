<div align="center">

# GamesAI

[English](/README.md)  |  简体中文  |  [繁體中文](/README.zh-TW.md)

[反馈问题](https://github.com/PengZixuan30/Games_AI/issues/new)  |  [反馈想法](https://github.com/PengZixuan30/Games_AI/issues/new)

</div>

> [!NOTE]
> 欢迎使用版本0.5.0，当前版本加入了自定义工具的功能，加入了诸多新的工具，修复了一些问题。见[本次更新](#本次更新)

> [!IMPORTANT]
> 此版本加入了自定义工具的功能，会在配置文件夹创建tools.py文件。见[自定义工具](#自定义工具)

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
  - [工具与自定义工具](#工具与自定义工具)
    - [工具](#工具)
    - [自定义工具](#自定义工具)
  - [本次更新](#本次更新)
    - [1.加入了自定义工具的功能](#1加入了自定义工具的功能)
    - [2.加入了一些新的工具](#2加入了一些新的工具)
  - [鸣谢与声明](#鸣谢与声明)
  - [许可证](#许可证)

</details>

## 安装

在MCDR控制台中使用如下命令以安装插件

`!!MCDR plugin install games_ai`

---

或者在[MCDR插件仓库](https://mcdreforged.com/plugin/games_ai)中获取并安装到你的插件目录内

如果选择手动安装，请先安装Python包OpenAI和requests，使用如下命令安装
```bash
pip install openai requests
```

## 使用

在任何地方输入命令`!!gamesai`以显示这个插件的所有功能

<details>
<summary>

有关`!!gamesai`的所有指令(点击展开)</summary>

|指令|用途|
|---|---|
|`!!gamesai clear`|清除玩家的历史聊天记录，历史聊天记录与公共数据库无关|
|`!!gamesai clearall`|清除所有玩家的历史聊天记录，历史聊天记录与公共数据库无关|
|`!!gamesai reload`|重新加载插件配置文件|
|`!!gamesai check`|检查插件更新|

</details>

---

你也可以直接输入`!!ask`向AI提问或者聊天或者帮你做一些事情

<details>
<summary>

有关`!!ask`的所有指令(点击展开)</summary>

|指令|用途|
|---|---|
|`!!ask <content>`|向AI提问或者聊天或者帮你做一些事情，content为你想让AI做的事情或者你想问AI的问题|
|`!!ask -m <model> <content>`|使用指定的模型向AI提问或者聊天或者帮你做一些事情，model为你想使用的模型的AI_ID或昵称，content为你想让AI做的事情或者你想问AI的问题|

</details>

---

输入`!!data`获取有关数据库指令的信息

> [!TIP]
> 更新到0.3.0及以上版本时会自动添加数据库

<details>
<summary>

有关`!!gamesai`的所有指令(点击展开)</summary>

|指令|用途|
|---|---|
|`!!data write <key> <value>`|在公共数据库内添加一条数据，其中key不能包含空格，value可以是任意字符串|
|`!!data add <key> <value>`|将value追加到公共数据库中的key中，不存在时自动创建新key|
|`!!data del <key>`|在公共数据库内删除一条数据，无论key是否存在|
|`!!data read <key>`|读取公共数据库中key对应的value|
|`!!data list`|读取公共数据库中的所有内容|
|`!!data list keys`|读取公共数据库中的所有key|

</details>

## 配置

默认配置文件结构如下:

```json
{
  "prefix": "[GamesAI]",
  "permission": 3,
  "max_history": 10,
  "all_ai": {
      "<Your AI ID>":{
          "prompt": "你是一名成熟、稳重的Minecraft机器人工具，你的名字叫做“GamesAI”",
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

<details>

<summary>点击展开</summary>

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

</details>

## 工具与自定义工具
### 工具
GamesAI插件提供了很多自带的工具，见下表。如果你想要更多的工具，可以选择[向作者投稿](https://github.com/PengZixuan30/Games_AI/issues/new)或者选择[自定义工具](#自定义工具)

<details>
<summary>点击查看所有的自带工具</summary>

|工具ID|传入参数|用途|
|:---:|:---:|:---|
|get_online_players|无|获取服务器内在线的玩家列表。依赖于`online_player_api`插件，不存在时自动关闭此工具|
|get_whitelist_name|无|获取服务器完整的白名单列表。依赖于`whitelist_api`插件，不存在时自动关闭此工具|
|add_to_whitelist|`name`|将某个玩家添加到白名单中。依赖于`whitelist_api`插件，不存在时自动关闭此工具|
|remove_from_whitelist|`name`|将某个玩家从白名单删除。依赖于`whitelist_api`插件，不存在时自动关闭此工具|
|search_minecraft_wiki|`query`|让AI搜索Minecraft Wiki，以确保回答更准确|
|calculator|`expression`|简单的数学表达式计算器|
|item_caculator|`expression`,`single_limit`|数学表达式计算器，并将最终结果转换为物品计数法，即 盒、组、个，自动适应物品的堆叠数，不存在时默认使用64|
|add_pos_pos|`name`,`pos`,`dimension`|在指定位置添加一个坐标点。依赖于`where2go`或`location_marker`插件，两者都存在时，优先使用`where2go`，均不存在时，自动关闭此工具|
|add_pos_here|`name`|在玩家的位置添加一个坐标点，控制台执行时自动关闭此工具。依赖于`where2go`或`location_marker`插件，两者都存在时，优先使用`where2go`，均不存在时，自动关闭此工具|
|remove_pos|`name`|删除一个坐标点，`where2go`版本会自动将name转换为id。依赖于`where2go`或`location_marker`插件，两者都存在时，优先使用`where2go`，均不存在时，自动关闭此工具|
|search_pos|`name`|搜索一个坐标点。依赖于`where2go`或`location_marker`插件，两者都存在时，优先使用`where2go`，均不存在时，自动关闭此工具|
|get_all_pos|无|获取所有的坐标点列表.依赖于`where2go`或`location_marker`插件，两者都存在时，优先使用`where2go`，均不存在时，自动关闭此工具|
|ai_read_data|`key`|读取一条数据库内容|
|ai_read_all_keys|无|获取数据库中所有的键|
|ai_write_data|`key`,`value`|向数据库中写入一条数据\(覆写模式\)|
|ai_add_data|`key`,`value`|向数据库中写入一条数据\(追加模式\)|
|ai_del_data|`key`|删除数据库中的一条数据|

</details>

### 自定义工具
通过修改`config/games_ai/tools/tools.py`文件来实现自定义修改工具

先来看看默认值如何

```python
from mcdreforged.command.command_source import CommandSource
from games_ai.games_ai_tool import register_tool

@register_tool(description="My Custom Tool")
def my_custom_tool(source: CommandSource, ai_prefix: str):
    return "Tool execution completed"
```

> [!IMPORTANT]
> 代码中的`from games_ai.games_ai_tool import register_tool`和函数定义前的`@register_tool`必须存在

可见，这是十分简单的结构。

接下来我将告诉你如何实践，比如下面的例子：搜索baidu.com

<details>

<summary>点击展开</summary>

想要知道如何实现搜索baidu.com，参考GamesAI源代码中的工具`search_minecraft_wiki`无疑是最好的选择：

```python
@register_tool(description="搜索Minecraft Wiki以获取相关信息, 请不要使用此方法搜索与Minecraft无关的东西。如果返回了Search results页面, 你可以通过先浏览此页面, 再进行一次精确查询", tr_key="searching_minecraft_wiki", parameters={
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "要搜索的内容，例如某个物品、怪物、机制等的名称。"
        }
    },
    "required": ["query"]
})
def search_minecraft_wiki(source: CommandSource, ai_prefix: str, query: str):
    source.reply(f'{ai_prefix}{source.get_server().rtr("games_ai.tools.searching_minecraft_wiki", query=query)}')
    lang = source.get_server().get_mcdr_language()
    if lang == "en_us":
        search_url = f"https://minecraft.wiki/?search={query}"
    else:
        search_url = f"https://zh.minecraft.wiki/?search={query}"
    response = requests.get(search_url)
    if response.status_code == 200:
        return f"一下是搜索内容 {query} 的结果:\n{response.content.decode('utf-8')}"
    else:
        return "无法访问Minecraft Wiki进行搜索"
```

首先来看工具的注册，其中的`description`类似于提示词，是必填项，是给AI提供的；其中的`tr_key`是内部方法，外部编写tools.py时不需要包含此项；而`parameters`就是AI需要传入的参数，可根据实际情况决定是否填写，其中的`properties`用于填写所有的传入参数，其中的`required`项则表示有哪些参数是必填的，注意`properties`与函数定义中传入参数的位置关系，应该需要一一对应。

例如：
```python
@register_tool(description="搜索百度")
```

但是，搜索百度肯定需要传入搜索内容，所以：
```python
@register_tool(description="搜索百度", parameters={
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "要搜索的内容"
        }
    },
    "required": ["query"]
})
```

好了，你已经学会如何注册工具了，接下来就可以写函数定义了：
```python
def search_baidu(source: CommandSource, ai_prefix: str, query: str):
```

上面的代码中，`source`和`ai_prefix`项必须编写，因为它们始终会被传入

接下来写函数体：
```python
def search_baidu(source: CommandSource, ai_prefix: str, query: str):
    ...
    return ...
```

函数体中可以是任何你需要的操作，最后记得一定要`return`，否则AI将无法正确处理结果

`tools.py`的完整示例：
```python
import requests
from games_ai.games_ai_tool import register_tool

@register_tool(
    description="使用百度搜索互联网上的信息。当你需要查找实时信息、新闻、百科知识等时使用此工具。",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "要在百度搜索的关键词或问题"
            }
        },
        "required": ["query"]
    }
)
def search_baidu(source, ai_prefix: str, query: str):
    source.reply(f'{ai_prefix}正在搜索百度：{query}...')

    try:
        url = "https://www.baidu.com/s"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        response = requests.get(url, params={"wd": query}, headers=headers, timeout=10)

        if response.status_code != 200:
            return f"百度搜索失败，HTTP 状态码：{response.status_code}"

        # 简单提取页面文本（去除 HTML 标签）
        import re
        text = response.text
        # 移除 script 和 style 标签内容
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # 移除 HTML 标签
        text = re.sub(r'<[^>]+>', '', text)
        # 合并多余空白
        text = re.sub(r'\s+', ' ', text).strip()

        # 截断过长内容（保留前 3000 字符，适合 AI 上下文）
        max_len = 3000
        if len(text) > max_len:
            text = text[:max_len] + "\n...(内容已截断)"

        return f"百度搜索「{query}」的结果：\n{text}"

    except requests.Timeout:
        return "百度搜索请求超时，请稍后重试"
    except Exception as e:
        return f"百度搜索出错：{str(e)}"
```

</details>

## 本次更新
### 1.加入了自定义工具的功能
本次更新加入了自定义工具的功能，让你拥有更多元的体验。配置方法见[自定义工具](#自定义工具)

### 2.加入了一些新的工具
加入了一些新的工具，主要包含计算器类和坐标管理器类。

---

另外，本次更新修复了一些问题

## 鸣谢与声明
特别感谢望海公社服务器为此插件的测试提供了基础

AI\(LLM\)模型生成的一切内容与此插件无关

自定义工具造成的一切后果与本插件无关

## 许可证
本插件使用MIT协议，由yello持有

<div align = "center">

---

[回到顶部](#gamesai)

</div>