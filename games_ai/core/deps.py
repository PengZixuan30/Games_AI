"""Which Python packages this plugin needs, and the only place that runs pip.

The plugin has to be importable on a machine where none of those packages exists yet, so
``games_ai/__init__.py`` imports this module (standard library only) before anything else and
skips its third-party imports while something is missing. That is also why the manifest lives in
``games_ai/requirements.txt`` instead of the plugin root: MCDR reads a **root** ``requirements.txt``
before the plugin is imported at all and refuses to load the plugin when a package is missing,
which would keep the repair below from ever running.

Installing is deliberately narrow:

* only names that are actually missing are handed to pip -- never ``--upgrade``, because on
  Windows the ``.pyd`` of an already imported package cannot be replaced (``WinError 5``);
* the first attempt uses the machine's own pip configuration, the second one the Aliyun mirror;
* after both attempts failed nothing is retried: the caller logs the failure and the command the
  user can run himself.

The state file is *not* a setting. It lives in the plugin's ``cache/`` folder (the same one the
context window table uses) and only serves three things: keeping a second instance from starting
another pip while one is running, letting the instance that comes back after the self-reload say
"recovered" out loud, and keeping the last outcome for whoever reads the log later. No user-facing
switch reads or writes it.
"""
import collections
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time

__all__ = [
    'ALIYUN_INDEX_URL',
    'CACHE_DIR_NAME',
    'PER_ATTEMPT_TIMEOUT_SECONDS',
    'REQUIREMENTS',
    'STALE_INSTALL_SECONDS',
    'begin_install',
    'finish_install',
    'install',
    'install_once',
    'manual_command',
    'missing',
    'note_recovered',
    'pip_argv',
    'read_state',
    'state_path',
    'unimportable',
    'unsatisfied',
    'write_state',
]

# Keep in sync with games_ai/requirements.txt; a probe suite asserts the two agree.
REQUIREMENTS = ('openai', 'requests', 'websockets')

# The second attempt goes to a mirror, because a first attempt that fails is usually a network
# that cannot reach PyPI at all.
ALIYUN_INDEX_URL = 'https://mirrors.aliyun.com/pypi/simple/'

# One attempt must not hang the repair forever. The output is streamed, so a slow install is
# visible instead of silent; 300 s covers a cold ``openai`` install (measured: about 85 s).
PER_ATTEMPT_TIMEOUT_SECONDS = 300

# An ``installing`` record older than this is the leftover of a killed MCDR, not a live install.
STALE_INSTALL_SECONDS = 900

STATE_FILE_NAME = 'dependency_install.json'

# The plugin's cache folder inside its data folder, shared with the context window table.
CACHE_DIR_NAME = 'cache'

_TAIL_LINES = 40


# --------------------------------------------------------------------------------------
#   What is missing
# --------------------------------------------------------------------------------------

def missing() -> list[str]:
    """The distributions of :data:`REQUIREMENTS` that have no metadata at all."""
    names = []
    for name in REQUIREMENTS:
        try:
            importlib.metadata.version(name)
        except Exception:
            names.append(name)
    return names


def unimportable() -> list[str]:
    """The distributions that are installed but cannot be imported (a broken install)."""
    names = []
    for name in REQUIREMENTS:
        try:
            if importlib.util.find_spec(name) is None:
                names.append(name)
        except Exception:
            names.append(name)
    return names


def unsatisfied() -> list[str]:
    """Every requirement that is missing or not importable, in :data:`REQUIREMENTS` order."""
    broken = set(missing()) | set(unimportable())
    return [name for name in REQUIREMENTS if name in broken]


def manual_command(names) -> str:
    """The command a user can run himself when both pip attempts failed."""
    return 'python -m pip install ' + ' '.join(names or REQUIREMENTS)


# --------------------------------------------------------------------------------------
#   Running pip
# --------------------------------------------------------------------------------------

def pip_argv(names, index_url: str | None = None) -> list[str]:
    """The pip command line of one attempt.

    ``index_url`` is only set for the mirror attempt: the first attempt must let pip use whatever
    this machine is configured with (pip.ini, ``PIP_INDEX_URL``, a proxy), so no index or proxy
    argument is passed at all.
    """
    argv = [sys.executable, '-X', 'utf8', '-m', 'pip', 'install', '--disable-pip-version-check']
    if index_url:
        argv += ['-i', index_url]
    return argv + [str(name) for name in names]


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill pip and whatever it started (same approach as the node shutdown in mineflayer.py)."""
    if proc.poll() is not None:
        return
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        else:
            proc.terminate()
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass


def install_once(names, log, abort, index_url: str | None = None) -> tuple[bool, str]:
    """Run one ``pip install`` and stream its output.

    A reader thread pumps pip's stdout/stderr line by line into ``log`` while this thread only
    waits: that way an abort (MCDR shutting down) or the per-attempt timeout is noticed within
    half a second instead of after the next line arrives. Returns ``(returncode == 0, tail)``;
    ``tail`` is the last few output lines, or ``"aborted"`` / ``"timeout"``.
    """
    names = list(names)
    if not names:
        return True, ''
    argv = pip_argv(names, index_url)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
        bufsize=1,
        creationflags=creationflags,
    )
    tail: collections.deque = collections.deque(maxlen=_TAIL_LINES)

    def _pump():
        try:
            for raw_line in proc.stdout:
                line = raw_line.rstrip()
                if not line:
                    continue
                tail.append(line)
                try:
                    log(line)
                except Exception:
                    pass
        except (OSError, ValueError):
            pass
        finally:
            try:
                proc.stdout.close()
            except (OSError, ValueError):
                pass

    threading.Thread(target=_pump, name='games_ai@deps_pip', daemon=True).start()

    deadline = time.monotonic() + PER_ATTEMPT_TIMEOUT_SECONDS
    while True:
        try:
            proc.wait(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            pass
        if abort is not None and abort.is_set():
            _kill_tree(proc)
            return False, 'aborted'
        if time.monotonic() > deadline:
            _kill_tree(proc)
            return False, 'timeout'

    return proc.returncode == 0, '\n'.join(tail)[-400:]


def install(names, log, abort, retry_log=None) -> tuple[bool, str, str]:
    """Install the missing packages, machine pip configuration first, Aliyun mirror second.

    :return: ``(ok, phase, detail)`` where ``phase`` is ``"local"`` or ``"mirror"``. Nothing is
        retried when the mirror attempt failed too; the caller reports it.
    """
    pending = [str(name) for name in names]
    if not pending:
        return True, 'local', ''

    ok, detail = install_once(pending, log, abort, index_url=None)
    if ok:
        return True, 'local', detail
    if abort is not None and abort.is_set():
        return False, 'local', 'aborted'

    # The first attempt may have installed some of them before failing, so only ask for what is
    # still missing. If the metadata says everything is there, the failure was something else
    # (a warning pip returns non-zero for) and it is not worth a second download.
    still = [name for name in pending if name in unsatisfied()]
    if not still:
        return True, 'local', detail

    if retry_log is not None:
        try:
            retry_log(still)
        except Exception:
            pass
    ok, detail = install_once(still, log, abort, index_url=ALIYUN_INDEX_URL)
    return ok, 'mirror', detail


# --------------------------------------------------------------------------------------
#   The record of the last attempt
# --------------------------------------------------------------------------------------

def state_path(server) -> str:
    """The record of the last repair attempt, in the plugin's cache folder."""
    return os.path.join(server.get_data_folder(), CACHE_DIR_NAME, STATE_FILE_NAME)


def read_state(server) -> dict:
    try:
        with open(state_path(server), 'r', encoding='utf-8') as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_state(server, **fields) -> None:
    """Merge ``fields`` into the state file. Never raises: a read-only data folder must not stop
    the install itself."""
    try:
        path = state_path(server)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = read_state(server)
        data.update(fields)
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _self_version(server) -> str:
    try:
        return str(server.get_self_metadata().version)
    except Exception:
        return ''


def begin_install(server, names) -> tuple[bool, str]:
    """Claim the repair.

    :return: ``(False, "running")`` when another instance is visibly installing right now,
        otherwise ``(True, "")`` after writing the ``installing`` record.
    """
    state = read_state(server)
    if state.get('status') == 'installing':
        try:
            age = time.time() - float(state.get('ts') or 0)
        except (TypeError, ValueError):
            age = STALE_INSTALL_SECONDS + 1.0
        if age < STALE_INSTALL_SECONDS:
            return False, 'running'
    write_state(server, status='installing', ts=time.time(),
                packages=[str(name) for name in names], version=_self_version(server))
    return True, ''


def finish_install(server, ok, detail='', phase='') -> None:
    write_state(server, status='installed' if ok else 'failed', ts=time.time(),
                phase=str(phase), detail=str(detail)[-400:])


def note_recovered(server) -> list[str]:
    """Called by the normal ``on_load``: the packages are there, so report the repaired names once.

    A ``failed`` record counts as well -- the user may have installed the packages by hand and
    reloaded the plugin. The record turns ``ready`` so the next instance stays quiet.
    """
    state = read_state(server)
    if state.get('status') not in ('installed', 'failed'):
        return []
    write_state(server, status='ready', ts=time.time())
    packages = state.get('packages')
    return [str(name) for name in packages] if isinstance(packages, list) else []
