<div align="center">

# PIM：插件自己的安装管理器

[English](../en_us/pim.md)  |  简体中文  |  [繁體中文](../zh_tw/pim.md)

[返回 README](../../README.zh-CN.md)

</div>

这里的 **PIM** 指 *Plugin Install Manager*（插件安装管理器）：GamesAI 用来维护自己的两套机制 —— **更新器**（下载新的 `.mcdr` 并替换插件自己的文件）与 **Python 包管理器**（安装插件需要的包）。两者都没有配置项、都不问用户任何问题，而且最后都会让插件重新加载自己。

第一次安装插件仍然是 `!!MCDR plugin install games_ai`（其它办法都失败时，手动更新也用它）；它**不再**用于更新插件本身 —— 见下。

本页是总述；每种失败消息的细节留在各自文档里：[troubleshooting.md](troubleshooting.md)（`插件更新`、`缺少 Python 依赖包`）、[cross-server.md](cross-server.md)（集群轮次）与 [configuration.md](configuration.md)（配置项）。

## 更新器

- **产物从哪来**：插件自己的 GitHub release（`https://github.com/PengZixuan30/Games_AI/releases/download/...`）。插件仓库元数据里公告了版本、文件大小与 `sha256`；只有这个 URL 前缀下的产物会被安装。第二来源是同一个 URL 走 `ghfast.top` 镜像 —— 每个来源各两次尝试、合计四次，每次 15 秒超时、总计 300 秒预算。
- **替换之前校验什么**：公告的文件大小、下载内容的 `sha256`，以及**归档内部的插件 id 与版本**（归档里的 `mcdreforged.plugin.json`）。下载的必须是一个有效的 zip，其 `mcdreforged.plugin.json` 必须带上公告的 id 与版本，公告的大小必须在 MCDR 的 100 MiB 上限内；正在运行的实例本身必须是打包的 `.mcdr` / `.pyz` —— 源码目录形式的安装无法替换自己。任何一项不符都会结束这一轮并给出原因，磁盘上什么都不动。
- **替换过程**：一切可能失败的步骤（元数据、下载、校验、磁盘空间、目录可写）都在**插件仍然加载着**的时候做完。然后 MCDR 卸载插件（由此放开对归档的占用），重试删除旧文件（Windows 可能仍然报"文件被占用"），把校验过的文件移动到**同一个路径**（这样 MCDR 对本插件 id 只会保留一个文件），再重新加载插件；随后核对 MCDR 报出的版本，新文件起不来时恢复并加载旧文件。卸载之后的任何失败路径都以一次加载收尾，因此服务器不会在"没有 GamesAI"的状态下继续跑。
- **什么时候跑**：24 小时更新检查（加载时启动）、`!!gamesai check`（随时），以及集群里的协调轮次。集群中由 **hub** 决定并先命令节点：等到每台节点都 `staged` **并且**以新版本重连回来，最后才替换自己的文件。跨服**客户端**从不自己检查、也不自己安装；在客户端上敲 `!!gamesai check` 会由 hub 执行。local 模式下实例独自更新。循环（加载时那次与每 24 小时那次）是安静的：只有真的**发现新版本**时才播报（以及接着安装它的那一轮），"正在检查更新"与"没有新版本"只写进调试日志（`!!gamesai debug` 可见），不会为一个没人要求的检查打扰玩家；`!!gamesai check` 仍然会把这两行回给输入命令的人。
- **刻意不做的事**：不退回 MCDR 安装器。某一步失败就结束这一轮并记录原因（下载不到、大小或哈希不符、文件被锁、新文件没加载起来已回滚）。要手动安装就用 `!!MCDR plugin install -U -y games_ai`，或者再跑一次 `!!gamesai check`。
- **做不到的情况**：以**源码目录**形式运行的实例无法替换自己 —— 日志会说明，只能手动更新（见 [cross-server.md](cross-server.md#集群更新)）。

## Python 包管理器

- **管什么**：`games_ai/requirements.txt` 里列的三个包 —— `openai`、`requests`、`websockets`。
- **为什么插件能自修复**：它的入口模块**不需要**这些包就能导入（第三方导入都在门控之后）。一台什么都没装的机器照样能加载插件，`on_load` 此时只做一件事：报出缺什么、把它装上，然后请 MCDR 重新加载插件。
- **两次尝试**：第一次用本机 pip 配置执行 `python -m pip install --disable-pip-version-check <包名>` —— 不附加任何 index/代理参数，因此 `pip.ini`、`PIP_INDEX_URL` 与代理照常生效；失败后第二次对**仍然缺**的包改用阿里云 PyPI 镜像（`https://mirrors.aliyun.com/pypi/simple/`）重试。会传 `--disable-pip-version-check`，**从不**传 `--upgrade` —— Windows 上已经 import 过的包的 `.pyd` 无法替换。pip 的每一行输出都带 `[deps]` 前缀写进 MCDR 日志，装得慢也能看见进度。
- **装好之后**：再校验一次（必须真的能 import）、写入本次尝试的记录，然后插件用 `reload_plugin` 重载自己。重载回来的实例会在日志里确认：`依赖已就绪，插件已恢复正常（...）`。
- **两次都失败时**：日志会打出 `依赖安装失败：...` 与可以直接复制的命令 —— `python -m pip install openai requests websockets`，然后 `!!MCDR plugin reload games_ai`。在此之前插件"已加载但不工作"：不注册命令、不启动 bot、也不建跨服链路。不会循环重试；下一次启动（或手动重载插件）会再试。
- **清单为什么放在包内**：MCDR 会在导入插件**之前**检查**插件根目录**的 `requirements.txt`，缺包就直接拒绝加载 —— 那样插件就永远没有机会自我修复。`games_ai/requirements.txt` 随包分发（源码目录里可以直接喂给 `pip install -r`）。通过插件仓库安装同样受影响：声明的依赖清单来自插件根目录的 `requirements.txt`，而这个版本已经不再附带它，所以 `!!MCDR plugin install games_ai` 也不会安装任何依赖，插件会在第一次启动时自行修复（首次安装命令仍然可用，只是不再预装任何东西）。
- **记录文件**：`config/games_ai/cache/dependency_install.json`（与上下文窗口表同目录）保存最后一次尝试 —— 状态、包名、`local` 还是 `mirror`、以及 pip 输出的末尾。它不是配置项，也没有任何地方把它当配置读：它用来防止另一个实例同时开第二份 pip，并让重载后的实例确认已恢复。
- **没有开关、没有指令**：修自己的依赖是插件自己的事，所以既没有可配置项，也没有要敲的命令。

## 每台机器、每个实例

- **更新器**是集群感知的：一轮更新，由 hub 排序，各实例替换自己的文件。
- **依赖修复**是按机器、按实例进行的：每个实例只为**它自己的** Python 解释器安装缺的包。两台机器上的两个实例各自修复，而依赖齐全的实例什么都不做 —— 加载时共有两轮、每轮三次 `find_spec` 与三次元数据查询。

## 相关文档

- [troubleshooting.md](troubleshooting.md) —— 具体日志行与对应处理。
- [cross-server.md](cross-server.md) —— 集群更新轮次、入网与角色。
- [configuration.md](configuration.md) —— `websocket` 配置块与更新相关设置。
- [hot-reload.md](hot-reload.md) —— `!!gamesai reload`：重载的是配置，不是插件文件。
