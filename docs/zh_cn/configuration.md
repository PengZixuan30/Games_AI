<div align="center">

# 配置

[English](../en_us/configuration.md)  |  简体中文  |  [繁體中文](../zh_tw/configuration.md)

[返回 README](../../README.zh-CN.md)

</div>

默认配置文件结构如下:

```json
{
  "prefix": "[GamesAI]",
  "permission": 3,
  "all_ai": {
      "<Your AI ID>":{
          "prompt": "你是一名成熟、稳重的Minecraft机器人工具，你的名字叫做“GamesAI”",
          "ai_name": "[GamesAI]",
          "base_url": "<Your API Base URL>",
          "ai_model": "<Your AI Model>",
          "api_key": "<Your API Key>",
          "extra_body": {},
          "context_window": null
      }
    },
  "default_ai": "<Your AI ID>",
  "mineflayer_bot": {
      "enabled": false,
      "cycle_interval": 15.0,
      "websocket": {
          "url": "ws://127.0.0.1:8080",
          "reconnect_interval": 10,
          "timeout": 60,
          "first_connect_interval": 0.5
      },
      "bot": {
          "username": "<Your Minecraft Bot Username>",
          "password": "<Your Minecraft Bot Password>",
          "auth": "microsoft"
      }
  }
}
```

---

以下是每个参数的简介:

## 1.prefix
值的类型: str

默认值: \[GamesAI\]

填入插件的名称，以在插件的回复之前加上一个前缀，可以包含Minecraft格式化代码

## 2.permission
值的类型：int

默认值：3

执行`!!data`等指令所必须达到的权限，见[MCDR权限相关文档](https://docs.mcdreforged.com/zh-cn/latest/permission.html)

自 0.6.4 起，该值同时决定向玩家 AI 提供哪些**工具**：`perm` 高于玩家权限等级的工具不会传给 AI 模型，模型既看不到也无法调用。管理数据、技能、自定义工具或启停 Bot 的内置工具都使用该值（通过 `get_plugin_config_perm`），并在每次请求时实时读取，重载后立即生效。

## 3.all_ai
值的类型: dict

默认值：见文件

填入所有的AI信息，由多个字典组成，每个字典为一个AI模型，字典的键即为插件内部的AI_ID

**prompt**: 这项配置用于为每个AI编写提示词。使用`> xxx.md`将提示词指向`config/games_ai/prompt/xxx.md`文件，不限文件类型

**ai_name**: 这项配置与prefix功能类似，但是你现在需要单独为每一个模型设置，可以包含Minecraft格式化代码

**base_url**, **ai_model**, **api_key**: 与以前的相关配置功能相同，但是你现在需要单独为每一个模型设置

**extra_body**：请参考各API提供商对 `extra_body` 项的说明以编写。对于DeepSeek用户，想要移植原有 `thinking` 的，直接填写 `{"thinking": {"type": "enabled"}}`。不填时默认 `{}`（空）。

**context_window**（可选）：为该模型覆盖[上下文自动管理](ai-request-pipeline.md#上下文自动管理)所使用的上下文窗口（单位 token）。留空（`null`）时使用上下文窗口表中的数值。对于窗口极大的模型，可作为成本控制开关，例如 `"context_window": 65536`。

> [!TIP]
> 用 `!!ask context --all` 可以看到每个模型**实际**被用了多少上下文、以及自插件加载以来累计消耗了多少 token（含缓存命中率）。若某个 100 万窗口的模型长期只用到几万 token，就说明上面这个覆盖值可以放心调小——窗口越小，压缩越早介入，长对话的每次请求就越便宜。详见[上下文查看](ai-request-pipeline.md#上下文查看)。

## 4.default_ai
值的类型: str

默认值: \<Your AI ID\>

填入当用户直接使用`!!ask`时使用的模型，应该填入all_ai字典中的某一个键(即为插件内部的AI_ID)，如果错填，会导致无法正常使用`!!ask`指令

## 5.mineflayer_bot
值的类型: `dict`

默认值: 见上方

Mineflayer 自主 Bot 代理的配置项。

**enabled**: 是否在启动时拉起 Bot。需要 Node.js >= 18。

**cycle_interval**: 自主 AI 决策循环间隔秒数（默认: 15.0）。

**websocket**: 内部 WebSocket 连接参数 — `url`、`reconnect_interval`、`timeout`、`first_connect_interval`。

**first_connect_interval**: **首次连接成功之前**的重试间隔秒数（默认: 0.5）。Node 服务启动并打开端口需要一点时间，若首次连接失败就按 `reconnect_interval`（默认 10 秒）退避，假人上线会凭空多等这么久；因此首次连接阶段使用这个更短的间隔，**连上过一次之后**才恢复使用 `reconnect_interval`。

> [!WARNING]
> WebSocket 的 `url` 中 host **必须**设为 `127.0.0.1`。请确保所选端口未被占用——插件会在启动时自动检查端口冲突，若端口被占用将自动禁用 Bot。
> 除非你明确知道自己在做什么，否则我们不建议你修改 `websocket` 内的配置。

**bot**: Minecraft 账号凭据 — `username`、`password`、`auth`（microsoft/mojang/offline）。服务器地址自动从 `server.properties` 中检测。

> [!WARNING]
> `username` 必须符合正则表达式 `[a-zA-Z0-9_]+`（仅限英文字母、数字和下划线，不含空格）。若用户名包含非法字符，`!!aibot join` 将被拒绝。

> [!TIP]
> 修改配置后，使用 `!!gamesai reload` 或 `!!gamesai config set` 使更改生效。详见[热重载](hot-reload.md#热重载)。
