<div align="center">

# GamesAI for MCDReforged

[English](/README.md)  |  简体中文  |  [繁體中文](/README.zh-TW.md)

[反馈问题](https://github.com/PengZixuan30/Games_AI/issues/new)  |  [反馈想法](https://github.com/PengZixuan30/Games_AI/discussions/new/choose)  |  [加入Q群](https://qm.qq.com/q/jDQQaUPNmw)

[转至Fabric版本](https://github.com/PengZixuan30/GamesAI)

</div>

> [!NOTE]
> **GamesAI 插件/模组 QQ 交流群：849544707** — 欢迎加入交流群讨论问题、反馈建议，以及分享 prompt、skills、tools 等配置！

> [!NOTE]
> 欢迎使用版本 0.7.3！本次更新重做了**请求里的消息结构**：system 消息只剩一条（prompt + 技能列表），当前时间改由提问前的 `user` 消息承载并定期重注，公共数据改用 `assistant`，连续的 `user` 消息会在发出前合并为一条——因此那些"只允许一条 system"的模型（如 Qwen3.5 系列）可以正常使用了，长会话的前缀缓存也能持续命中。详见[本次更新](docs/zh_cn/changelog.md#本次更新)。

<details>
<summary>目录(点击展示)</summary>

- [GamesAI for MCDReforged](#gamesai-for-mcdreforged)
  - [安装](#安装)
  - [使用](#使用)
  - [技术文档](#技术文档)
  - [AI 在本项目中的角色](#ai-在本项目中的角色)
  - [鸣谢与声明](#鸣谢与声明)
  - [赞助与贡献者名单](#赞助与贡献者名单)
  - [许可证](#许可证)

</details>

## 安装

在MCDR控制台中使用如下命令以安装插件

`!!MCDR plugin install games_ai`

---

或者在[MCDR插件仓库](https://mcdreforged.com/plugin/games_ai)中获取并安装到你的插件目录内

如果选择手动安装，请先安装Python包OpenAI、requests和websockets，使用如下命令安装
```bash
pip install openai requests websockets
```

## 使用

在任何地方输入命令`!!gamesai`以显示这个插件的所有功能

|指令|用途|
|---|---|
|`!!gamesai clear`|清除玩家的历史聊天记录，历史聊天记录与公共数据库无关|
|`!!gamesai clearall`|清除所有玩家的历史聊天记录，历史聊天记录与公共数据库无关|
|`!!gamesai reload`|重新加载插件配置文件。详见[热重载](docs/zh_cn/hot-reload.md#热重载)|
|`!!gamesai check`|检查插件更新，并强制刷新上下文窗口表|
|`!!gamesai speedtest [model]`|测试 API 服务器连接延迟，不指定模型时测试全部|
|`!!gamesai config get <key>`|读取一个配置项的值。|
|`!!gamesai config set <key> <value>`|修改一个配置项的值（自动适配旧值类型，修改后自动触发[热重载](docs/zh_cn/hot-reload.md#热重载)）。|

---

你也可以直接输入`!!ask`向AI提问或者聊天或者帮你做一些事情

|指令|用途|
|---|---|
|`!!ask <content>`|向AI提问或者聊天或者帮你做一些事情，content为你想让AI做的事情或者你想问AI的问题|
|`!!ask -n <content>`|向AI提问但不使用历史记录（当前对话仍会被保存）|
|`!!ask -f <content>`|强制提问：不等待当前轮结束，将消息并入正在运行的对话轮（别名 `-forced`）。详见[AI 请求链路与对话机制](docs/zh_cn/ai-request-pipeline.md#ai-请求链路与对话机制)。|
|`!!ask switch <model>`|切换当前对话使用的 AI 模型，model为AI_ID或昵称。切换时清空历史，并在你下次提问前由旧模型压缩为摘要转接给新模型，详见[切换模型时的摘要转接](docs/zh_cn/ai-request-pipeline.md#切换模型时的摘要转接)。|
|`!!ask stop`|立即停止你名下所有正在进行的对话：运行中的对话轮（含工具调用）、正在进行的 `!!ask -n` 提问、以及你委派给 Bot 的任务。未完成的一步会从历史中删除，`!!ask -f` 排队消息会被丢弃。详见[停止正在进行的对话](docs/zh_cn/ai-request-pipeline.md#停止正在进行的对话)。|
|`!!ask context [玩家]`|查看上下文占用：模型与窗口来源、已用比例、距离压缩还有多少余量、逐轮规模与缓存命中。不填玩家即查看自己。详见[上下文查看](docs/zh_cn/ai-request-pipeline.md#上下文查看)。|
|`!!ask context --all`|按模型汇总全服所有玩家的上下文用量（零用量的模型不列出），悬停可看自插件加载以来的累计用量。详见[上下文查看](docs/zh_cn/ai-request-pipeline.md#上下文查看)。|
|`!!ask compact`|立即压缩较早的历史（忽略窗口触发线），由你下次提问前的预检完成，指令本身不阻塞。详见[上下文查看](docs/zh_cn/ai-request-pipeline.md#上下文查看)。|

---

输入`!!data`获取有关数据库指令的信息

> [!TIP]
> 更新到0.3.0及以上版本时会自动添加数据库

|指令|用途|
|---|---|
|`!!data write <key> <value>`|在公共数据库内添加一条数据，其中key不能包含空格，value可以是任意字符串|
|`!!data add <key> <value>`|将value追加到公共数据库中的key中，不存在时自动创建新key|
|`!!data del <key>`|在公共数据库内删除一条数据，无论key是否存在|
|`!!data read <key>`|读取公共数据库中key对应的value|
|`!!data list`|读取公共数据库中的所有内容|
|`!!data list keys`|读取公共数据库中的所有key|

---

## 技术文档

技术细节集中在 [`docs/zh_cn/`](docs/zh_cn/)：请求如何组装并保持在窗口内、每个配置项的含义、工具与技能系统如何工作、机器人如何被驱动、出问题时怎么排查。

| 文档 | 内容 |
|---|---|
| [AI 请求链路](docs/zh_cn/ai-request-pipeline.md) | 请求链路、无历史 `!!ask -n`、`!!ask switch` 摘要转接、`!!ask stop`、上下文自动管理、每玩家状态 |
| [配置](docs/zh_cn/configuration.md) | `config.json` 的全部键：`prefix`、`permission`、`all_ai`（含 `context_window`）、`default_ai`、`mineflayer_bot` |
| [工具](docs/zh_cn/tools.md) | 26 个内置工具、在 `tools.py` 里自定义、在自己的插件里注册、权限与可见性 |
| [技能](docs/zh_cn/skills.md) | 技能能解决什么、内置技能、`skills.json`、让 AI 自己维护、在自己的插件里注册 |
| [范例](docs/zh_cn/example.md) | 一台真实服务器的完整配置：配置、六个技能、44 个自定义工具、一轮实操与踩坑 |
| [Mineflayer Bot](docs/zh_cn/mineflayer-bot.md) | 环境要求、指令、工作原理、支持的操作、Bot 控制工具 |
| [热重载](docs/zh_cn/hot-reload.md) | 如何触发重载、重载期间发生了什么、如何让自己的插件跟随重载 |
| [故障排查](docs/zh_cn/troubleshooting.md) | `!!ask` 报错、Bot 报错、日志与调试 |
| [更新日志](docs/zh_cn/changelog.md) | 各个已发布版本的更新说明 |

> 相同文档的其它语言版本：[English](docs/en_us/) · [繁體中文](docs/zh_tw/)。

---

## AI 在本项目中的角色

GamesAI 本身是 AI 驱动的插件,而 AI 也在本项目自身的维护中扮演重要角色:

1. 本 README 最初由作者(yello)排版,后全部交由 AI 修改;
2. 所有翻译文件(`lang/*.yml`)均由 AI 修改;
3. 每次发布前的逻辑检查由 AI 完成;
4. 快照/开发版本中出现的问题将由 AI 排查;
5. GitHub 反馈的 issue、PR 等将先由 AI 排查问题,再交由维护者处理。

## 鸣谢与声明
特别感谢 [WangHai Server](https://github.com/Wanghai-Server) 为此插件的测试提供了基础

特别感谢 [william-song-shy (William Song)](https://github.com/william-song-shy) 为 `!!ask` 无历史模式提供的建议。

特别感谢 [ZhangZuoqian (张作乾)](https://github.com/ZhangZuoqian) 为测速指令提供的建议。

AI\(LLM\)模型生成的一切内容与此插件无关

自定义工具造成的一切后果与本插件无关

## 赞助与贡献者名单

赞助地址：[爱发电](https://ifdian.net/a/yello)

为GamesAI赞助的将会出现在下列的赞助者名单中（当前没有赞助者）：

| # | 赞助者 | 金额 | 日期 |
|---|--------|------|------|
| - | - | - | - |

## 许可证
MIT License, Copyright (c) 2026 yello

<div align = "center">

---

[回到顶部](#gamesai-for-mcdreforged)

</div>
