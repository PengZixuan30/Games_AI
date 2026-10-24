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
          "extra_body": {}
      }
    },
  "default_ai": "<Your AI ID>",
  "mineflayer_bot": {
      "enabled": false,
      "cycle_interval": 15.0,
      "bot": {
          "username": "<Your Minecraft Bot Username>",
          "password": "<Your Minecraft Bot Password>",
          "auth": "microsoft"
      }
  },
  "websocket": {
      "uri": "ws://127.0.0.1:8080",
      "force_server": false,
      "allow_app_id": [],
      "name": "",
      "token_ttl_hours": -1,
      "auto_enroll": true,
      "identity_file": ""
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

该值同时决定向玩家 AI 提供哪些**工具**：`perm` 高于玩家权限等级的工具不会传给 AI 模型，模型既看不到也无法调用。管理数据、技能、自定义工具或启停 Bot 的内置工具都使用该值（通过 `get_plugin_config_perm`），并在每次请求时实时读取，重载后立即生效。

但它并不是所有命令的门槛：`!!gamesai reload`、`!!gamesai check`、`!!gamesai debug`、`!!gamesai debug thread`、`!!gamesai speedtest` 以及只影响自己的 `!!gamesai clear` 对任何来源都执行，`!!ask` 也对所有玩家开放（该等级只决定模型能看到哪些工具）。会检查该等级的是 `!!gamesai clear <name>`、`!!gamesai clearall`、`!!data` 各子命令、`!!gamesai config get/set`、`!!aibot join/leave/set` 与 `!!gamesai node …`（不带参数的 `!!gamesai clear` 只涉及自己的历史，不需要该等级）。

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
> 用 `!!ask context --all` 可以看到每个配置的 AI 条目**实际**被用了多少上下文、以及自其对话建立以来累计消耗了多少 token(重启后仍然累计)（含缓存命中率）。若某个 100 万窗口的模型长期只用到几万 token，就说明上面这个覆盖值可以放心调小——窗口越小，压缩越早介入，长对话的每次请求就越便宜。详见[上下文查看](ai-request-pipeline.md#上下文查看)。

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

**假人的连接地址**：假人不自己监听端口，而是作为客户端接入集群 —— 地址与角色由顶层的 [6.websocket](#6websocket) 决定，详见[跨服连接](cross-server.md)。



**bot**: Minecraft 账号凭据 — `username`、`password`、`auth`（microsoft/mojang/offline）。服务器地址自动从 `server.properties` 中检测。


> [!TIP]
> 修改配置后，使用 `!!gamesai reload` 使更改生效。`!!gamesai config set` 同样会重载，但它只处理顶层键，并会拒绝 `all_ai` 与 `mineflayer_bot` 这类复杂配置块（点分键会被当成新的顶层键写入，而不会被解析到对应的子键）——Bot 凭据请改用 `!!aibot set`。详见[热重载](hot-reload.md#热重载)。

## 6.websocket

跨服连接设置，完整说明见[跨服连接](cross-server.md)。

- `websocket.uri` — 集群地址（默认 `"ws://127.0.0.1:8080"`）。能连上 GamesAI hub 就以客户端接入；连不上且端口空闲则以本机为 hub 监听 —— 但如果本机已持有节点身份就例外：已入网的实例会保持客户端身份并持续重试，直到用 `!!gamesai node forget` 丢弃其 token。`host` 按字面绑定，要让别的机器连上需写 `0.0.0.0` 或本机内网 IP。
- `websocket.force_server` — 强制本机做 hub（默认 `false`；端口被占时报错并退回 local 模式）。
- 从旧版本升级：旧的 `mineflayer_bot.websocket.url` 会自动迁移到 `websocket.uri`，旧块被删除。
- `websocket.allow_app_id` — 字符串列表（默认 `[]`）。额外允许哪些握手 ID 接入本 hub（例如你自己的服务），避免被 `4005` 拒绝；hub 不为这些 ID 做专项适配，且它们被视为完全可信。详见[跨服连接](cross-server.md#握手-id)。
- `websocket.token_ttl_hours` — 签发给节点的 token 有效期（小时，默认 `-1` 永久）。签发时固化，只在握手时校验，不会中断进行中的连接；跨主机建议设一个值。详见[跨服连接](cross-server.md)。
- `websocket.auto_enroll` — 本机没有身份时是否自动向 hub 发出注册请求（默认 `true`）。
- `websocket.identity_file` — 自定义本机身份文件路径（默认 `config/games_ai/cross_server/identity.json`）。运维写了哪个文件就用哪个：该值按原样使用（相对路径按工作目录解析），并且**不会**对旧默认位置做自动迁移。
- `websocket.name` — 本实例在集群里的名字。默认 `""` = 按实例目录派生：`<实例目录名>-<路径哈希前 6 位>`（如 `survival-9f31ab`），所以同机两个实例不会撞名，改机器名也不会让注册失效。改名字需要重新入网（`!!gamesai node forget` 后再 `node claim`）。

## 7. 插件更新

**没有任何可配置项。** 自动更新完全按跨服角色决定（见[跨服联机](cross-server.md#集群更新)）：

- **单机**（local 模式）在启动时与每 24 小时检查一次，自己安装新版本；
- **hub** 同样如此，并且额外协调整个集群：节点先装，hub 阻塞等到它们以新版本回来，最后才装自己；
- **客户端**从不检查、从不自行安装 —— 由 hub 决定。在客户端输入 `!!gamesai check` 会在 hub 上执行。

产物永远来自本插件自己的 GitHub release（`ghfast.top` 镜像是第二来源），并且只有公告的尺寸、sha256 **以及**归档内的插件 id 与版本全部相符才会使用。这里**刻意没有** `!!MCDR plugin install` 兜底：一轮失败就结束并如实报告（再执行 `!!gamesai check` 开新一轮，或手工 `!!MCDR plugin install -U -y games_ai`）。
