<div align="center">

# GamesAI for MCDReforged

English  |  [简体中文](/README.zh-CN.md)  |  [繁體中文](/README.zh-TW.md)

[Report an Issue](https://github.com/PengZixuan30/Games_AI/issues/new)  |  [Share an Idea](https://github.com/PengZixuan30/Games_AI/discussions/new/choose)  |  [Join QQ Group](https://qm.qq.com/q/jDQQaUPNmw)

[Go to Fabric Version](https://github.com/PengZixuan30/GamesAI)

</div>

> [!NOTE]
> **GamesAI Plugin/Mod QQ Group: 849544707** — Join us to discuss issues, share feedback, and exchange prompt, skills, tools configurations!

> [!NOTE]
> Welcome to version 0.7.2! This release brings **context inspection**: `!!ask context` shows the window usage of a conversation, how many tokens are left before compression, the per-round sizes and the cache-hit rate; `!!ask context --all` sums every player's usage per model; `!!ask compact` compresses the older history on demand. It also fixes questions like `!!ask stop it.` being dropped by a command node, and concurrent reloads being able to switch the bot off; unload and hot reload are no longer held up by the bot shutting down. See [What's New](docs/en_us/changelog.md#whats-new) for details.

<details>
<summary>Table of Contents (click to expand)</summary>

- [GamesAI for MCDReforged](#gamesai-for-mcdreforged)
  - [Installation](#installation)
  - [Usage](#usage)
  - [Technical Documentation](#technical-documentation)
  - [The Role of AI in This Project](#the-role-of-ai-in-this-project)
  - [Acknowledgements \& Disclaimer](#acknowledgements--disclaimer)
  - [Sponsorship \& Contributors](#sponsorship--contributors)
  - [License](#license)

</details>

## Installation

Run the following command in the MCDR console to install the plugin:

`!!MCDR plugin install games_ai`

---

Alternatively, get it from the [MCDR Plugin Repository](https://mcdreforged.com/plugin/games_ai) and place it in your plugin directory.

If you choose to install manually, install the Python packages `openai`, `requests`, and `websockets` first:

```bash
pip install openai requests websockets
```

## Usage

Type `!!gamesai` anywhere to display all available features of this plugin.

|Command|Description|
|---|---|
|`!!gamesai clear`|Clear your own chat history. Chat history is unrelated to the public database.|
|`!!gamesai clearall`|Clear all players' chat history. Chat history is unrelated to the public database.|
|`!!gamesai reload`|Reload the plugin configuration file. See [Hot Reload](docs/en_us/hot-reload.md#hot-reload) for details.|
|`!!gamesai check`|Check for plugin updates and force-refresh the context-window table.|
|`!!gamesai speedtest [model]`|Test API server connection latency. If no model is specified, all models are tested.|
|`!!gamesai config get <key>`|Read a configuration value.|
|`!!gamesai config set <key> <value>`|Update a configuration value (auto type-adapts; automatically triggers [Hot Reload](docs/en_us/hot-reload.md#hot-reload)).|

---

You can also use `!!ask` directly to ask the AI questions, chat, or ask it to do things for you.

|Command|Description|
|---|---|
|`!!ask <content>`|Ask the AI a question, chat, or ask it to do something. `<content>` is what you want the AI to do or the question you want to ask.|
|`!!ask -n <content>`|Ask the AI without using conversation history (current conversation is still saved).|
|`!!ask -f <content>`|Force-ask without waiting: the request is merged into the round that is currently running (alias: `-forced`). See [AI Request Pipeline & Chat Mechanism](docs/en_us/ai-request-pipeline.md#ai-request-pipeline--chat-mechanism).|
|`!!ask switch <model>`|Switch the AI model for your current conversation (`<model>` is the AI_ID or nickname). The history is cleared and the old model summarizes it right before your next request, handing the summary to the new model. See [Summary Hand-off on Model Switch](docs/en_us/ai-request-pipeline.md#summary-hand-off-on-model-switch).|
|`!!ask stop`|Immediately stop everything you have in flight: your running round (tool calls included), a running `!!ask -n` request and a task you delegated to the bot. The interrupted step is deleted from the history and queued `!!ask -f` messages are discarded. See [Stopping a running round](docs/en_us/ai-request-pipeline.md#stopping-a-running-round).|
|`!!ask context [player]`|Show the context usage: model and window source, how much of the window is used, how many tokens are left before compression, the per-round sizes and the cache-hit rate. Without a player name it shows your own. See [Context Inspection](docs/en_us/ai-request-pipeline.md#context-inspection).|
|`!!ask context --all`|Sum the context usage of every player on the server, grouped by model (models with zero usage are not listed); hover for the totals since the plugin was loaded. See [Context Inspection](docs/en_us/ai-request-pipeline.md#context-inspection).|
|`!!ask compact`|Compress the older history right now, ignoring the compression triggers. It is performed by the preflight of your next question, so the command itself never blocks. See [Context Inspection](docs/en_us/ai-request-pipeline.md#context-inspection).|

---

Type `!!data` for information about database commands.

> [!TIP]
> The database is automatically created when upgrading to version 0.3.0 or above.

|Command|Description|
|---|---|
|`!!data write <key> <value>`|Add a data entry to the public database. `<key>` must not contain spaces; `<value>` can be any string.|
|`!!data add <key> <value>`|Append `<value>` to an existing key in the public database. Creates a new key if it does not exist.|
|`!!data del <key>`|Delete a data entry from the public database, regardless of whether the key exists.|
|`!!data read <key>`|Read the value associated with a key from the public database.|
|`!!data list`|Read all entries in the public database.|
|`!!data list keys`|Read all keys in the public database.|

---

## Technical Documentation

The technical details live in [`docs/en_us/`](docs/en_us/) — how a request is built and kept inside the window, what every configuration key does, how tools and skills work, how the bot is driven, and what to do when something fails.

| Document | Contents |
|---|---|
| [AI Request Pipeline](docs/en_us/ai-request-pipeline.md) | Request chain, the stateless `!!ask -n`, the `!!ask switch` hand-off, `!!ask stop`, automatic context management, per-user state |
| [Configuration](docs/en_us/configuration.md) | Every key of `config.json`: `prefix`, `permission`, `all_ai` (incl. `context_window`), `default_ai`, `mineflayer_bot` |
| [Tools](docs/en_us/tools.md) | The 26 built-in tools, writing your own in `tools.py`, registering tools from your own plugin, permissions and visibility |
| [Skills](docs/en_us/skills.md) | What skills are for, the built-in ones, `skills.json`, letting the AI write them, registering them from your own plugin |
| [Example](docs/en_us/example.md) | A real server configuration end to end: config, six skills, 44 custom tools, a walkthrough round and the pitfalls |
| [Mineflayer Bot](docs/en_us/mineflayer-bot.md) | Prerequisites, commands, how it works, supported actions, bot control tools |
| [Hot Reload](docs/en_us/hot-reload.md) | Triggering a reload, what happens during one, following it from your plugin |
| [Troubleshooting](docs/en_us/troubleshooting.md) | `!!ask` errors, bot errors, logging & debugging |
| [Changelog](docs/en_us/changelog.md) | Release notes of every published version |

> The same documents in other languages: [简体中文](docs/zh_cn/) · [繁體中文](docs/zh_tw/).

---

## The Role of AI in This Project

GamesAI is an AI-powered plugin, and AI also plays an important role in how this project itself is maintained:

1. This README was originally typeset by the author (yello) and has since been fully revised by AI;
2. All translation files (`lang/*.yml`) are maintained by AI;
3. Logic checks before each release are performed by AI;
4. Issues reported for snapshot/development builds are investigated by AI;
5. GitHub issues and PRs are first triaged by AI before reaching the maintainer.

## Acknowledgements & Disclaimer

Special thanks to [WangHai Server](https://github.com/Wanghai-Server) for providing the foundation for testing this plugin.

Special thanks to [william-song-shy (William Song)](https://github.com/william-song-shy) for suggesting the `!!ask` no-history mode.

Special thanks to [ZhangZuoqian (张作乾)](https://github.com/ZhangZuoqian) for suggesting the `!!gamesai speedtest` command.

All content generated by AI (LLM) models is unrelated to this plugin.

All consequences arising from custom tools are unrelated to this plugin.

## Sponsorship & Contributors

Sponsorship address: [Afdian](https://ifdian.net/a/yello)

Those who sponsor GamesAI will appear in the following sponsor list (currently no sponsors):

| # | Sponsor | Amount | Date |
|---|---------|--------|------|
| - | - | - | - |

## License

MIT License, Copyright (c) 2026 yello

<div align = "center">

---

[Back to Top](#gamesai-for-mcdreforged)

</div>
