<div align="center">

# 测试

[English](../en_us/testing.md)  |  简体中文  |  [繁體中文](../zh_tw/testing.md)

[返回 README](../../README.zh-CN.md)

</div>

GamesAI 的整套校验套件就在本仓库里：运行器是 pytest，每次改动都要通过它。`tests/` 下的模块会自己拉起所需的对端、hub、节点与数据库，因此跑测试不需要 Minecraft 服务器、不需要 MCDR 实例、不需要 API key，也不需要联网。

## 安装 pytest

测试套件运行在插件自己的解释器上（Python 3.12 或更高版本）。在这台解释器里安装 pytest：

```bash
python -m pip install pytest
```

测试还会 import 插件本身，因此插件的运行期依赖也要能被同一个解释器 import：`mcdreforged`、`websockets`、`openai` 与 `requests`。已经在跑插件的机器上这四个都有。

## 运行测试

在仓库根目录执行 pytest。根目录的 `pytest.ini` 设置 `testpaths = tests`，并把仓库与 `tests/` 放进 `sys.path`，所以测试模块可以直接 `import games_ai` 和 `_helpers`，不必自己拼路径：

```bash
python -m pytest
```

只改一个方向时，跑单个模块就够了：

```bash
python -m pytest tests/test_layout.py
```

`-k` 按名字挑选，匹配测试 id 的任意部分：

```bash
python -m pytest -k clear
```

文档检查器可以单独跑：

```bash
python -m pytest tests/docs
```

> [!TIP]
> `python -m pytest --collect-only -q` 只列出会被收集的用例、不执行任何测试；`-p no:cacheprovider` 让 pytest 不往仓库里写 `.pytest_cache/` 目录。

## 各目录的职责

|路径|职责|
|---|---|
|`pytest.ini`|pytest 配置：`testpaths = tests` 让不带参数的 `python -m pytest` 收集这个目录，`pythonpath = . tests` 把仓库与 `tests/` 放进 `sys.path`。|
|`tests/conftest.py`|所有套件共享的 fixture：给要拉起 hub、节点或协议原型的套件用的 `free_port` 工厂、安静日志的默认设置，以及把插件的仓库相对路径（`skills_path`、`data_path`）钉在临时目录里的会话级兜底。|
|`tests/test_*.py`|测试模块：线协议与帧、入网与 token、路由、AI 请求链路、更新轮次，以及仓库自身的布局。|
|`tests/_helpers/`|共享助手 —— `paths.py`（仓库路径）、`pkg.py`（把插件源码当文本读）与 `wait.py`（轮询代替 sleep）—— 以及三个协议原型 `ws_async.py`、`ws_sync_hub.py`、`ws_sync_node.py`。|
|`tests/docs/`|文档检查器：编码与换行符、三语结构一致性、README 一致性与整洁度、README 里的 JSON 块。|
|`tests/js/`|假人测试的 Node.js 一侧：vendored 的 `ws` 模块副本，`test_bot_js.py` 会把它拷到自己在临时目录里构建的 harness 旁边。|

## 运行测试需要什么

- `PATH` 上的 Python 3.12 或更高版本（`python --version`），与插件声明的下限一致。
- 该解释器里装有 pytest（`python -m pytest --version`）。
- 插件的运行期依赖能被它 import：`mcdreforged`、`websockets`、`openai` 与 `requests`。
- 只有 JavaScript 假人测试需要 `PATH` 里有 Node.js：`tests/test_bot_js.py` 会启动真实的 `node` 进程，其余模块没有它也能跑。
- 本机空闲的 TCP 端口：要起 hub 或节点的套件会向系统申请一个 `127.0.0.1` 上的端口。

## 运行测试不需要什么

- 不需要 Minecraft 服务器，也不需要运行中的 MCDR 实例：对端都在进程内启动。
- 不需要 API key，也不需要 AI 服务商：请求链路跑在桩上，什么都不会发出去。
- 不需要 Minecraft 账号：假人测试把 Minecraft 一侧打桩，只用 JavaScript 说 hub 协议。
- 不需要联网：套件本身不下载任何东西，依赖要么已安装、要么已 vendored（`tests/js/` 下的 `ws` 模块）。插件自己的后台刷新（上下文窗口表与更新检查）在会启动跨服链路的套件里仍可能发出一次请求；离线时它会失败、被记入日志且不改变任何结果，也没有任何检查依赖它。

## 测试不会往仓库里写文件

套件把自己的状态放在仓库之外：

- 插件配置、数据库、节点表与缓存文件都建在操作系统的临时目录（或 pytest 自己的 `tmp_path`）里，跑完不留测试数据。
- `tests/js/node_modules/` 下 vendored 的 `ws` 模块属于仓库，只会被读取。
- 运行留下的痕迹只有 Python 的 `__pycache__/` 目录；`-p no:cacheprovider` 还能让 pytest 的 `.pytest_cache/` 也不进仓库。
