<div align="center">

# PIM: the plugin's own installer

English  |  [简体中文](../zh_cn/pim.md)  |  [繁體中文](../zh_tw/pim.md)

[Back to README](../../README.md)

</div>

**PIM** here means *Plugin Install Manager*: the two mechanisms with which GamesAI maintains
itself -- the **updater**, which fetches a new `.mcdr` and replaces the plugin's own file, and the
**Python package manager**, which installs the packages the plugin needs. Neither has a setting,
neither asks the user anything, and both end with the plugin loading itself again.

`!!MCDR plugin install games_ai` is still how the plugin is installed the first time (and how an
update is done by hand when everything else failed). What it is *not* used for any more is
updating itself -- see below.

This page is the overview; the details of each failure message stay where they belong:
[troubleshooting.md](troubleshooting.md) (`Plugin Updates`, `Missing Python Packages`),
[cross-server.md](cross-server.md) (the cluster round) and
[configuration.md](configuration.md) (the settings).

## The updater

- **Where the artifact comes from**: the plugin's own GitHub release
  (`https://github.com/PengZixuan30/Games_AI/releases/download/...`). The plugin catalogue entry
  announces the version, the file size and the `sha256`; only assets under that URL prefix are
  ever installed. The second source is the same URL behind the `ghfast.top` mirror -- two attempts
  per source, four in total, each with a 15 second timeout and a 300 second budget for all of them.
- **What is checked before anything is replaced**: the announced size, the `sha256` of the
  download, and the plugin **id and version inside the archive** (its `mcdreforged.plugin.json`).
  The download must be a valid zip whose `mcdreforged.plugin.json` carries the announced id and
  version and whose announced size is under MCDR's 100 MiB limit, and the running install must
  itself be a packed `.mcdr` / `.pyz` -- a source-directory install cannot replace itself. A
  mismatch ends the round with a reason and touches nothing on disk.
- **How the swap happens**: everything that can fail (metadata, download, verification, free disk
  space, writability of the folder) is done **while the plugin is still loaded**. Then MCDR
  unloads the plugin -- which drops its handle on the archive -- the old file is deleted with
  retries (Windows may still report "used by another process"), the verified file is moved onto
  the **same path** (so MCDR keeps exactly one file for this plugin id) and the plugin is loaded
  again; the version MCDR reports is checked, and the previous file is restored and loaded if the
  new one does not come up. Every failure after the unload ends with a load, so the server never
  keeps running without GamesAI.
- **When it runs**: the 24 hour update check (armed at load), `!!gamesai check` on demand, and -- in
  a cluster -- the coordinated round. The **hub** decides and orders the nodes first: it waits
  until every node is staged *and* has reconnected announcing the new version, and only then
  replaces its own file. A cross-server **client** never checks and never installs on its own; a
  `!!gamesai check` typed on a client is executed on the hub. In local mode an instance updates
  alone. The loop -- the check on load and the 24 hour ones -- is quiet: it announces only a
  release it actually finds (and the round that installs it), while "checking" and "no new version"
  go to the debug log, so nothing reaches the players for a check nobody asked for. A
  `!!gamesai check` still reports both lines, to whoever typed it.
- **What is deliberately not done**: there is no fallback to MCDR's installer. When a step fails,
  the round ends and the reason is logged (unreachable download, size or hash mismatch, a locked
  file, a new file that did not load and was rolled back). Install by hand with
  `!!MCDR plugin install -U -y games_ai`, or run `!!gamesai check` again.
- **Where it cannot work**: an instance running from a **source directory** cannot replace itself.
  The log says so, and the update has to be done by hand (see
  [cross-server.md](cross-server.md#cluster-updates)).

## The Python package manager

- **What it manages**: the three packages listed in `games_ai/requirements.txt` -- `openai`,
  `requests` and `websockets`.
- **Why the plugin can repair them at all**: its entry module imports **without** them (the
  third-party imports sit behind a gate). A machine that has none of them still loads the plugin,
  and `on_load` then does exactly one thing: report what is missing, install it, and ask MCDR to
  load the plugin again.
- **Two attempts**: the first one runs
  `python -m pip install --disable-pip-version-check <packages>` with the machine's own pip
  configuration -- no index or proxy argument is added, so `pip.ini`, `PIP_INDEX_URL` and a proxy
  keep working. If that fails, the second one retries the packages that are **still** missing
  against the Aliyun PyPI mirror (`https://mirrors.aliyun.com/pypi/simple/`).
  `--disable-pip-version-check` is passed; `--upgrade` never is, because on Windows the `.pyd` of
  an already imported package cannot be replaced. Every pip line goes to the MCDR log with a
  `[deps]` prefix, so a slow install is visible while it runs.
- **After a successful install**: the packages are checked again (they must really import), the
  attempt is recorded, and the plugin reloads itself (`reload_plugin`). The instance that comes
  back confirms it in the log: `Dependencies are ready; the plugin is fully loaded again (...)`.
- **When both attempts fail**: the log prints `Could not install: ...` and the exact command to run
  by hand -- `python -m pip install openai requests websockets`, then
  `!!MCDR plugin reload games_ai`. Until then the plugin is loaded but idle: it registers no
  command and starts neither the bot nor the cross-server link. Nothing is retried in a loop; the
  next start (or a manual plugin reload) tries again.
- **Why the manifest sits inside the package**: MCDR checks a `requirements.txt` at the **plugin
  root** *before* the plugin is imported and refuses to load the plugin while a package is missing
  -- which would leave the plugin no chance to repair itself. `games_ai/requirements.txt` ships with
  the package (a source checkout can feed it to `pip install -r`). The catalogue install is
  affected too: the declared package list comes from a `requirements.txt` at the plugin root, which
  this version no longer ships, so `!!MCDR plugin install games_ai` installs no packages either and
  the plugin repairs them on its first start (the first-install command still works, it just no
  longer pre-installs anything).
- **The record**: `config/games_ai/cache/dependency_install.json` (next to the context window
  table) keeps the last attempt -- its status, the packages, `local` or `mirror` and pip's tail. It
  is not a setting and nothing reads it as one: it keeps a second instance from starting another
  pip while one is running, and lets the reloaded instance confirm the recovery.
- **No switch, no command**: repairing its own dependencies is the plugin's business, so there is
  nothing to configure and nothing to type.

## Per machine, per instance

- The **updater** is cluster-aware: one round, ordered by the hub, each instance replacing its own
  file.
- The **package repair** is per machine and per instance: every instance installs the packages for
  **its own** Python interpreter, and only the ones missing there. Two instances on two machines
  repair independently, and an instance that has everything installed does nothing at all -- two
  rounds of three `find_spec` calls and three metadata lookups at load.

## Related

- [troubleshooting.md](troubleshooting.md) -- the exact log lines and what to do about them.
- [cross-server.md](cross-server.md) -- the cluster update round, enrolment and roles.
- [configuration.md](configuration.md) -- the `websocket` block and the update settings.
- [hot-reload.md](hot-reload.md) -- `!!gamesai reload`, which reloads the configuration, not the
  plugin file.
