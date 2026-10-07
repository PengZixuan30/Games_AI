"""The dependency repair of a plugin that has not got its Python packages yet.

Pins the shape that makes the repair possible at all (the entry module imports while openai and
websockets are absent), the behaviour of the aborted on_load (report, install once, reload only
after a verified install, otherwise log the command and stop), and the two-attempt install order
(machine pip configuration first, the Aliyun mirror second). Nothing here touches the network.
"""
import ast
import json
import logging
import os
import subprocess
import sys
import threading
import time

import pytest

import games_ai
from games_ai import deps

from _helpers.paths import PKG, REPO_ROOT
from _helpers.pkg import module_text

# The child imports the plugin on a real interpreter with both third-party names blocked at the
# finder; it runs with the repository as its working directory, which is where ``games_ai`` is.
BLOCKER = r'''
import json, sys, importlib.machinery
BLOCKED = ("openai", "websockets")
_original = importlib.machinery.PathFinder.find_spec


def _blocked(cls, fullname, path=None, target=None):
    if fullname.split(".")[0] in BLOCKED:
        return None
    return _original(fullname, path, target)


importlib.machinery.PathFinder.find_spec = classmethod(_blocked)
out = {}
try:
    import games_ai
except BaseException as error:
    out["error"] = "%s: %s" % (type(error).__name__, error)
else:
    out["pending"] = games_ai._deps_pending
    out["gated"] = [n for n in ("setup_openai_logging", "CrossServerManager", "ChatParam",
                                "AutonomousBotController", "update_round", "APIStatusError")
                    if hasattr(games_ai, n)]
    out["safe"] = [n for n in ("plugin_config", "logger", "register_tool", "SessionRegistry",
                               "get_default_init_hash", "CONTROLLER_THREAD_NAMES",
                               "_deps_start_install", "_deps_install_thread", "on_load")
                   if hasattr(games_ai, n)]
    out["unsatisfied"] = games_ai.deps.unsatisfied()
    out["loaded"] = [n for n in BLOCKED if n in sys.modules]
print(json.dumps(out))
'''


def _function_source(source, name):
    """The source of one top-level function, from its def to the next top-level def."""
    match = None
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            match = node
            break
    if match is None:
        return ""
    lines = source.splitlines()
    end = len(lines)
    for node in ast.parse(source).body:
        if node.lineno > match.lineno and getattr(node, "col_offset", 1) == 0:
            end = node.lineno - 1
            break
    return "\n".join(lines[match.lineno - 1:end])


class FakeServer:
    """Only what the aborted path touches, with counters so 'it registered nothing' is provable."""

    def __init__(self, folder):
        self.logger = logging.getLogger("deps_probe")
        self.logger.addHandler(logging.NullHandler())
        self.logger.setLevel(logging.CRITICAL)
        self._folder = folder
        self.rtr_calls = []
        self.register_command_calls = []
        self.register_help_message_calls = []
        self.said = []
        self.reload_calls = []

    def get_data_folder(self):
        return self._folder

    def get_self_metadata(self):
        return type("Meta", (), {"version": "0.8.0-probe", "id": "games_ai"})()

    def rtr(self, key, **kwargs):
        self.rtr_calls.append((key, kwargs))
        return key

    def register_command(self, *args, **kwargs):
        self.register_command_calls.append((args, kwargs))

    def register_help_message(self, *args, **kwargs):
        self.register_help_message_calls.append((args, kwargs))

    def say(self, text):
        self.said.append(text)

    def reload_plugin(self, plugin_id):
        self.reload_calls.append(plugin_id)
        return self.reload_result

    reload_result = True

    def rtr_keys(self):
        return [key for key, _ in self.rtr_calls]

    def rtr_kwargs(self, key):
        for call_key, kwargs in self.rtr_calls:
            if call_key == key:
                return kwargs
        return {}


@pytest.fixture
def server(tmp_path):
    """A fake MCDR server whose data folder is this test's own tmp folder."""
    folder = tmp_path / "data"
    folder.mkdir()
    return FakeServer(str(folder))


@pytest.fixture
def entry_source():
    return module_text("__init__.py")


@pytest.fixture
def deps_source():
    return module_text("deps")


def _install_case(monkeypatch, server, *, install_result=(True, "local", ""), missing_after=(),
                  missing_before=("openai",), reload_result=True):
    """Run the worker body once with pip replaced. Returns the calls the fake pip received."""
    calls = []
    state = {"missing": list(missing_before)}

    def fake_install(names, log, abort, retry_log=None):
        calls.append({"names": list(names), "retry_log": retry_log, "log": log})
        state["missing"] = list(missing_after)
        return install_result

    monkeypatch.setattr(deps, "install", fake_install)
    monkeypatch.setattr(deps, "unsatisfied", lambda: list(state["missing"]))
    server.reload_result = reload_result
    games_ai._deps_install_thread.__wrapped__(server, list(missing_before))
    return calls, state


def test_the_entry_module_imports_while_its_packages_are_absent():
    blocked_proc = subprocess.run([sys.executable, "-c", BLOCKER], cwd=REPO_ROOT,
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=120)
    assert blocked_proc.returncode == 0, \
        f"the blocker subprocess ran: {(blocked_proc.returncode, blocked_proc.stderr[-400:])}"
    try:
        blocked = json.loads(blocked_proc.stdout.strip().splitlines()[-1])
    except Exception as error:
        pytest.fail(f"blocker output is json: {(error, blocked_proc.stdout[-300:])}")

    assert "error" not in blocked, \
        f"import games_ai succeeds without openai and websockets: {blocked.get('error')}"
    assert blocked.get("pending") is True, f"the gate is tripped: {blocked.get('pending')}"
    assert blocked.get("loaded") == [], \
        f"no third-party name was imported for real: {blocked.get('loaded')}"
    assert blocked.get("gated") == [], \
        f"the gated names are not in the module namespace: {blocked.get('gated')}"
    assert len(blocked.get("safe") or []) == 9, \
        f"the third-party-free names are there: {blocked.get('safe')}"
    assert blocked.get("unsatisfied") == ["openai", "websockets"], \
        f"the missing list is reported: {blocked.get('unsatisfied')}"


def _evaluated_annotation_hits(source):
    """Annotations/defaults evaluated at import time that name a gated symbol (they would raise)."""
    tree = ast.parse(source)
    gated = {"setup_openai_logging", "AutonomousBotController", "set_bot_controller", "get_bot_controller",
             "force_abort_thread", "CONTROLLER_THREAD_NAMES", "ChatParam", "NonHistoryChatParam",
             "register_no_history", "unregister_no_history", "stop_no_history", "set_remote_tool_router",
             "describe_http_status", "MODE_CLIENT", "MODE_LOCAL", "MODE_SERVER", "CrossServerManager",
             "PROBE_GAMES_AI", "PROBE_UNREACHABLE", "probe_hub_detail", "token_fingerprint",
             "update_round", "requests", "APIConnectionError", "APIStatusError", "AuthenticationError",
             "RateLimitError"}

    def _names(node):
        return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} if node is not None else set()

    found = []
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and _names(node.annotation) & gated:
            found.append((node.lineno, ast.unparse(node)[:70]))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotations = [a.annotation for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs
                           if a.annotation]
            if node.returns:
                annotations.append(node.returns)
            for annotation in annotations:
                if _names(annotation) & gated:
                    found.append((node.lineno, ast.unparse(annotation)[:60]))
            for default in list(node.args.defaults) + [d for d in node.args.kw_defaults if d]:
                if _names(default) & gated:
                    found.append((node.lineno, ast.unparse(default)[:60]))
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if _names(base) & gated:
                    found.append((node.lineno, ast.unparse(base)[:60]))
    return found


def test_the_source_keeps_that_shape(entry_source, deps_source):
    assert "from __future__" not in entry_source and "from __future__" not in deps_source, \
        "no 'from __future__ import annotations' anywhere in the plugin " \
        "(forward references are strings)"
    assert 'dict[str, "ChatParam"]' in entry_source \
        and '"CrossServerManager | None"' in entry_source \
        and '"AutonomousBotController | None"' in entry_source \
        and 'chat_param: "ChatParam"' in entry_source, \
        "the gated names inside annotations are string forward references"
    assert _evaluated_annotation_hits(entry_source) == [], \
        f"nothing evaluated at import time names a gated symbol: " \
        f"{_evaluated_annotation_hits(entry_source)}"
    assert entry_source.index("_deps_pending = bool(deps.unsatisfied())") \
        < entry_source.index("    from .openai_api import"), "the gate is computed before the gated imports"
    assert "\nfrom .openai_api import" not in entry_source \
        and "    from .openai_api import setup_openai_logging" in entry_source, \
        "openai_api is imported inside the gate only"
    assert "\nfrom .mineflayer_ai import" not in entry_source, \
        "mineflayer_ai is imported inside the gate only"
    assert "\nfrom .chat_param import" not in entry_source, \
        "chat_param is imported inside the gate only"
    assert "\nfrom .cross_server import" not in entry_source, \
        "cross_server is imported inside the gate only"
    assert "\nfrom .websockets_client import" not in entry_source, \
        "websockets_client is imported inside the gate only"
    assert "\nfrom . import update_round" not in entry_source, \
        "update_round is imported inside the gate only"
    assert "\nimport requests\n" not in entry_source, \
        "requests is imported inside the gate only"
    assert "\nfrom openai import" not in entry_source, \
        "openai's exception classes are imported inside the gate only"
    assert "CONTROLLER_THREAD_NAMES = ()" in entry_source, \
        "the controller thread names have a safe value without them"
    assert "if not _deps_pending:\n    _install_tool_router()" in entry_source, \
        "the tool router is only installed with the packages present"
    assert "def on_server_startup(server: PluginServerInterface):\n    if _deps_pending:\n        return" \
        in entry_source, "on_server_startup steps aside while the packages are missing"
    assert "_DEP_INSTALL_ABORT.set()" in entry_source \
        and "if _deps_pending:" in _function_source(entry_source, "on_unload"), \
        "on_unload aborts a running pip"
    assert isinstance(ast.parse(entry_source), ast.Module), \
        "the parser view of the file is valid python"

    _deps_imports = set()
    for _node in ast.walk(ast.parse(deps_source)):
        if isinstance(_node, ast.Import):
            _deps_imports |= {alias.name.split(".")[0] for alias in _node.names}
        elif isinstance(_node, ast.ImportFrom) and _node.level == 0 and _node.module:
            _deps_imports.add(_node.module.split(".")[0])
    assert _deps_imports <= {"__future__", "collections", "importlib", "json", "os", "subprocess",
                             "sys", "threading", "time"}, \
        f"deps.py's imports are standard library only: {sorted(_deps_imports)}"
    assert "from ." not in deps_source and "import games_ai" not in deps_source, \
        "deps.py never imports the package it belongs to"
    assert "auto_install" not in entry_source and "auto_install" not in deps_source, \
        "there is no user-facing switch anywhere"
    assert "install_deps" not in entry_source and "install_deps" not in deps_source, \
        "there is no user-facing command anywhere"
    assert "server.reload_plugin(" in _function_source(entry_source, "_deps_install_thread"), \
        "the repair uses reload_plugin from the install thread"
    assert "execute_command" not in _function_source(entry_source, "_deps_install_thread"), \
        "the repair never issues a console command"
    assert "register_command" not in _function_source(entry_source, "_deps_start_install") \
        and "register_help_message" not in _function_source(entry_source, "_deps_start_install"), \
        "the aborted on_load registers no command"
    assert ".say(" not in _function_source(entry_source, "_deps_start_install"), \
        "the aborted on_load does not talk to players (the server is not up yet)"


def test_the_manifest_moved_into_the_package():
    root_manifest = os.path.join(REPO_ROOT, "requirements.txt")
    package_manifest = os.path.join(PKG, "requirements.txt")

    assert not os.path.exists(root_manifest), \
        "no requirements.txt at the plugin root (MCDR would refuse to load the plugin)"
    assert os.path.isfile(package_manifest), "the manifest is inside the package"

    with open(package_manifest, "rb") as handle:
        raw_manifest = handle.read()
    assert not raw_manifest.startswith(b"\xef\xbb\xbf"), \
        "the manifest has no BOM (MCDR would silently stop checking it)"
    assert b"\r\n" not in raw_manifest, "the manifest is LF only"
    lines = [line.strip() for line in raw_manifest.decode("utf-8").splitlines()
             if line.strip() and not line.strip().startswith("#")]
    assert lines == list(deps.REQUIREMENTS), \
        f"the manifest and deps.REQUIREMENTS agree: {(lines, list(deps.REQUIREMENTS))}"

    assert "games_ai@deps_install" in games_ai._PLUGIN_THREAD_NAMES \
        and "games_ai@deps_pip" in games_ai._PLUGIN_THREAD_NAMES, \
        "the new thread names are registered for the debug listing"


def test_the_aborted_on_load(server, monkeypatch):
    started_threads = []
    monkeypatch.setattr(games_ai, "_deps_pending", True)
    monkeypatch.setattr(games_ai, "_DEP_INSTALL_STARTED", False)
    monkeypatch.setattr(games_ai, "_deps_install_thread",
                        lambda _server, names: started_threads.append(list(names)))
    monkeypatch.setattr(deps, "unsatisfied", lambda: ["openai"])
    data_path_before = games_ai.plugin_config.data_path

    games_ai.on_load(server, None)

    assert "games_ai.dependency.missing_notice" in server.rtr_keys(), \
        f"the missing packages are reported: {server.rtr_keys()}"
    assert server.rtr_kwargs("games_ai.dependency.missing_notice").get("packages") == "openai", \
        f"...with the names in the message: {server.rtr_calls}"
    assert started_threads == [["openai"]], f"one install thread is started: {started_threads}"
    assert not server.register_command_calls and not server.register_help_message_calls, \
        f"nothing is registered: {(server.register_command_calls, server.register_help_message_calls)}"
    assert server.said == [], f"no player message is sent: {server.said}"
    assert games_ai.plugin_config.data_path == data_path_before, \
        "the rest of on_load did not run (the data path is still the class default)"
    assert deps.read_state(server).get("status") == "installing", \
        f"the attempt is claimed in the state file: {deps.read_state(server)}"


def test_one_attempt_per_plugin_instance(server, monkeypatch):
    started_threads = []
    monkeypatch.setattr(games_ai, "_deps_pending", True)
    monkeypatch.setattr(games_ai, "_DEP_INSTALL_STARTED", True)
    monkeypatch.setattr(games_ai, "_deps_install_thread",
                        lambda _server, names: started_threads.append(list(names)))
    monkeypatch.setattr(deps, "unsatisfied", lambda: ["openai"])

    games_ai.on_load(server, None)

    assert "games_ai.dependency.missing_notice" in server.rtr_keys(), \
        "the missing notice is still printed"
    assert started_threads == [], f"but no second pip run is started: {started_threads}"


def test_another_instance_installing_right_now(server, monkeypatch):
    deps.write_state(server, status="installing", ts=time.time(), packages=["openai"])
    started_threads = []
    monkeypatch.setattr(games_ai, "_deps_pending", True)
    monkeypatch.setattr(games_ai, "_DEP_INSTALL_STARTED", False)
    monkeypatch.setattr(games_ai, "_deps_install_thread",
                        lambda _server, names: started_threads.append(list(names)))

    games_ai.on_load(server, None)

    assert started_threads == [], f"the run is refused: {started_threads}"
    assert "games_ai.dependency.install_in_progress" in server.rtr_keys(), \
        f"...and said so: {server.rtr_keys()}"


def test_a_verified_install_reloads_the_plugin(server, monkeypatch):
    calls, _ = _install_case(monkeypatch, server, install_result=(True, "local", ""),
                             missing_after=())

    assert [c["names"] for c in calls] == [["openai"]], \
        f"pip was asked for the missing package: {calls}"
    assert server.reload_calls == ["games_ai"], \
        f"the plugin asked MCDR for a reload: {server.reload_calls}"
    assert "games_ai.dependency.installed_reloading" in server.rtr_keys(), \
        f"the reload is announced: {server.rtr_keys()}"
    assert deps.read_state(server).get("status") == "installed", \
        f"the state file records the success: {deps.read_state(server)}"
    assert "games_ai.dependency.installing" in server.rtr_keys(), \
        f"the attempt is announced before pip runs: {server.rtr_keys()}"


def test_a_failed_install_never_reloads(server, monkeypatch):
    _install_case(monkeypatch, server, install_result=(False, "mirror", "boom"),
                  missing_after=("openai",))

    assert server.reload_calls == [], f"no reload happened: {server.reload_calls}"
    assert "games_ai.dependency.install_failed" in server.rtr_keys(), \
        f"the failure is reported: {server.rtr_keys()}"
    assert server.rtr_kwargs("games_ai.dependency.install_failed").get("packages") == "openai", \
        "...with the packages"
    assert server.rtr_kwargs("games_ai.dependency.manual_hint").get("command") \
        == "python -m pip install openai", f"...and the manual command: {server.rtr_calls}"
    assert deps.read_state(server).get("status") == "failed", \
        f"the state file records the failure: {deps.read_state(server)}"
    assert deps.read_state(server).get("phase") == "mirror", \
        f"the phase is recorded too: {deps.read_state(server)}"


def test_pip_claims_success_but_the_package_still_does_not_import(server, monkeypatch):
    _install_case(monkeypatch, server, install_result=(True, "local", ""),
                  missing_after=("openai",))

    assert server.reload_calls == [], f"no reload happened: {server.reload_calls}"
    assert "games_ai.dependency.install_failed" in server.rtr_keys(), "the failure is reported"
    assert deps.read_state(server).get("status") == "failed", \
        "the state file records the failure"


def test_an_aborted_install_never_reloads(server, monkeypatch):
    _install_case(monkeypatch, server, install_result=(False, "local", "aborted"),
                  missing_after=("openai",))

    assert server.reload_calls == [], f"no reload happened: {server.reload_calls}"
    assert "games_ai.dependency.install_failed" in server.rtr_keys(), "the failure is reported"


def test_an_exception_inside_the_repair_is_contained(server, monkeypatch):
    monkeypatch.setattr(deps, "unsatisfied", lambda: ["openai"])
    monkeypatch.setattr(deps, "install",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no pip at all")))

    games_ai._deps_install_thread.__wrapped__(server, ["openai"])

    assert server.reload_calls == [], f"no reload happened: {server.reload_calls}"
    assert "games_ai.dependency.install_failed" in server.rtr_keys() \
        and "games_ai.dependency.manual_hint" in server.rtr_keys(), \
        f"the failure and the manual command are logged: {server.rtr_keys()}"
    assert deps.read_state(server).get("status") == "failed", \
        "the state file records the failure"


def test_a_reload_that_does_not_report_success_is_only_logged(server, monkeypatch):
    _install_case(monkeypatch, server, install_result=(True, "local", ""), missing_after=(),
                  reload_result=False)

    assert server.reload_calls == ["games_ai"], \
        f"the reload was still attempted once: {server.reload_calls}"
    assert "games_ai.dependency.manual_hint" in server.rtr_keys(), \
        f"the manual command is offered as the fallback: {server.rtr_keys()}"


def test_two_attempts_machine_configuration_first_the_aliyun_mirror_second(monkeypatch):
    assert all(arg not in deps.pip_argv(["openai"]) for arg in ("-i", "--index-url")), \
        f"the first attempt passes no index: {deps.pip_argv(['openai'])}"
    assert deps.pip_argv(["openai"], index_url=deps.ALIYUN_INDEX_URL)[-1] == "openai" \
        and deps.ALIYUN_INDEX_URL in deps.pip_argv(["openai"], index_url=deps.ALIYUN_INDEX_URL), \
        f"the mirror attempt carries the Aliyun index: " \
        f"{deps.pip_argv(['openai'], index_url=deps.ALIYUN_INDEX_URL)}"
    assert "--upgrade" not in deps.pip_argv(["openai"], index_url=deps.ALIYUN_INDEX_URL), \
        "pip is never asked to upgrade"
    assert deps.pip_argv(["openai"])[0] == sys.executable, \
        f"the interpreter that runs MCDR runs pip too: {deps.pip_argv(['openai'])}"

    retry_calls = []
    state = {"missing": ["openai", "websockets"]}

    def fake_once(names, log, abort, index_url=None):
        retry_calls.append((list(names), index_url))
        state["missing"] = ["websockets"] if len(retry_calls) == 1 else []
        return len(retry_calls) > 1, "tail %d" % len(retry_calls)

    monkeypatch.setattr(deps, "install_once", fake_once)
    monkeypatch.setattr(deps, "unsatisfied", lambda: list(state["missing"]))
    notice = []

    ok, phase, detail = deps.install(
        ["openai", "websockets"], lambda line: None, threading.Event(),
        retry_log=lambda pending: notice.append(list(pending)))

    assert retry_calls == [(["openai", "websockets"], None),
                           (["websockets"], deps.ALIYUN_INDEX_URL)], \
        f"the mirror attempt asks only for what is still missing: {retry_calls}"
    assert notice == [["websockets"]], f"the mirror retry is announced: {notice}"
    assert (ok, phase) == (True, "mirror"), f"the successful phase is reported as the mirror: {(ok, phase)}"

    retry_calls.clear()
    state["missing"] = ["openai"]
    ok, phase, _ = deps.install(["openai"], lambda line: None, threading.Event())
    assert (ok, phase, len(retry_calls)) == (True, "local", 1), \
        f"a first attempt that worked is not retried: {(ok, phase, retry_calls)}"

    retry_calls.clear()
    state["missing"] = ["openai"]

    def always_fail(names, log, abort, index_url=None):
        retry_calls.append((list(names), index_url))
        return False, "nope"

    monkeypatch.setattr(deps, "install_once", always_fail)
    abort_event = threading.Event()
    abort_event.set()
    ok, phase, detail = deps.install(["openai"], lambda line: None, abort_event)
    assert (ok, phase, detail, len(retry_calls)) == (False, "local", "aborted", 1), \
        f"an abort stops before the mirror attempt: {(ok, phase, detail, retry_calls)}"


def test_the_pip_child_is_streamed_and_can_be_aborted(monkeypatch):
    lines = []
    monkeypatch.setattr(deps, "pip_argv", lambda names, index_url=None: [
        sys.executable, "-c", "import time;print('child-line',flush=True);time.sleep(30)"])
    abort_event = threading.Event()
    threading.Timer(1.5, abort_event.set).start()
    started = time.monotonic()

    ok, detail = deps.install_once(["openai"], lines.append, abort_event)

    elapsed = time.monotonic() - started
    assert "child-line" in lines, f"the child's output is streamed while it runs: {lines}"
    assert (ok, detail) == (False, "aborted"), f"an abort returns quickly: {(ok, detail)}"
    assert elapsed < 15, f"...without waiting for the child to finish: {elapsed}"


def test_the_state_file(server, tmp_path):
    assert deps.read_state(server) == {}, "a missing record reads as empty"
    assert deps.CACHE_DIR_NAME == "cache" \
        and deps.state_path(server).endswith(os.path.join("cache", deps.STATE_FILE_NAME)), \
        f"the record lives in the plugin's cache folder, next to the context table: " \
        f"{deps.state_path(server)}"
    assert deps.write_state(server, status="installing") is None \
        and os.path.isfile(deps.state_path(server)), \
        f"writing creates the cache folder on demand: {deps.state_path(server)}"
    assert deps.begin_install(server, ["openai"]) == (True, ""), "the first claim wins"
    assert deps.begin_install(server, ["openai"])[0] is False, \
        "a second claim while installing is refused"

    with open(deps.state_path(server), "w", encoding="utf-8") as handle:
        handle.write("{not json")
    assert deps.read_state(server) == {}, "a corrupt record reads as empty instead of raising"

    deps.write_state(server, status="installing",
                     ts=time.time() - deps.STALE_INSTALL_SECONDS - 10)
    assert deps.begin_install(server, ["openai"])[0] is True, \
        "a killed MCDR leaves a stale record that does not block the next start"

    deps.finish_install(server, True, "tail", "local")
    assert deps.note_recovered(server) == ["openai"], \
        f"the recovered names are reported once: {deps.read_state(server)}"
    assert deps.note_recovered(server) == [], "...and then the record is quiet"

    blocked_path = tmp_path / "blocked" / "a-file"
    blocked_path.parent.mkdir()
    blocked_path.write_text("x", encoding="utf-8")
    deps.write_state(FakeServer(str(blocked_path)))
    assert True, "an unwritable data folder cannot break the repair"

    assert deps.manual_command([]) == "python -m pip install " + " ".join(deps.REQUIREMENTS), \
        f"the manual command names every requirement: {deps.manual_command([])}"
    assert deps.unsatisfied() == [], \
        f"this machine satisfies the manifest (the probe runs on the real interpreter): " \
        f"{deps.unsatisfied()}"


def test_the_pending_guards_of_the_other_events(server, monkeypatch):
    monkeypatch.setattr(games_ai, "_deps_pending", True)
    monkeypatch.setattr(games_ai, "_DEP_INSTALL_ABORT", threading.Event())

    games_ai.on_server_startup(server)
    guarded_startup = list(server.said)
    aborted = False
    try:
        games_ai.on_unload(server)
    except BaseException as error:
        aborted = "%s: %s" % (type(error).__name__, error)
    abort_set = games_ai._DEP_INSTALL_ABORT.is_set()

    assert guarded_startup == [], f"on_server_startup sends nothing while idle: {guarded_startup}"
    assert aborted is False, f"on_unload returns without raising: {aborted}"
    assert abort_set, "on_unload aborts a running pip"
