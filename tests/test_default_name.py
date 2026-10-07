"""V3: the derived instance name, and the hub refusing to take a name over.

Two failures are covered here:
  1. ``websocket.name`` defaulted to the hostname: every instance on one machine shared it, and
     a hub keys its node table by name, so the second enrolment silently took the first node's
     token away (4001, not retryable -> that node stayed down until a reload).
  2. ``hub.issue`` overwrote an enrolled name without asking, so the operator had no way to
     tell "I am replacing this node" from "a second instance is stealing this name".
"""
import logging
import os
import re
import socket

import games_ai
from games_ai.websockets_server import CrossServerHub

from _helpers.paths import LANG_DIR
from _helpers.pkg import module_text, package_text


def _instance(tmp_path, *parts):
    """A fake instance directory: ``<tmp>/<parts>/config/games_ai`` is its data folder."""
    root = tmp_path.joinpath(*parts)
    (root / "config" / "games_ai").mkdir(parents=True, exist_ok=True)
    return root


class FakeLogger:
    def __init__(self):
        self.records = []

    def _add(self, level, msg):
        self.records.append((level, str(msg)))

    def debug(self, msg, *a, **k):
        self._add("DEBUG", msg)

    def info(self, msg, *a, **k):
        self._add("INFO", msg)

    def warning(self, msg, *a, **k):
        self._add("WARNING", msg)

    def error(self, msg, *a, **k):
        self._add("ERROR", msg)

    def exception(self, msg, *a, **k):
        self._add("ERROR", msg)


class FakeServer:
    """A plugin interface stub: only the data folder and the two logging/text entry points."""

    def __init__(self, root=None, folder="auto"):
        self.logger = FakeLogger()
        if folder == "auto":
            self._folder = os.path.join(root, "config", "games_ai") if root else None
        else:
            self._folder = folder

    def get_data_folder(self):
        if self._folder is None:
            raise RuntimeError("this interface has no data folder")
        return self._folder

    def rtr(self, key, **kw):
        params = ",".join("{}={}".format(k, v) for k, v in sorted(kw.items()))
        return "[{} {}]".format(key.split(".")[-1], params)


class FakeManager:
    is_server = True
    is_client = False
    mode = "server"

    def __init__(self, hub):
        self.hub = hub


class FakeSource:
    def __init__(self, server, perm=4, console=True):
        self._server = server
        self._perm = perm
        self._console = console
        self.replies = []
        self.player = None if console else "Steve"

    def get_server(self):
        return self._server

    def get_permission_level(self):
        return self._perm

    @property
    def is_console(self):
        return self._console

    def reply(self, message, **kwargs):
        self.replies.append(str(message))


def test_two_instances_with_the_same_directory_name_differ(tmp_path):
    root_a = _instance(tmp_path, "a", "server")
    root_b = _instance(tmp_path, "b", "server")
    srv_a, srv_b = FakeServer(root=str(root_a)), FakeServer(root=str(root_b))

    name_a = games_ai._default_instance_name(srv_a)
    name_b = games_ai._default_instance_name(srv_b)
    assert name_a != name_b, \
        f"two instances with the same directory name differ: {name_a} vs {name_b}"
    assert games_ai._default_instance_name(srv_a) == name_a, "the name is deterministic"
    assert name_a.startswith("server-"), f"it starts with the directory name: {name_a}"
    assert re.fullmatch(r"server-[0-9a-f]{6}", name_a), \
        f"a 6 hex digit suffix makes it unique: {name_a}"
    assert re.fullmatch(r"[0-9A-Za-z._-]+", name_a), \
        f"it only holds characters that can be typed in a command: {name_a}"
    assert games_ai._instance_root(srv_a) == os.path.abspath(root_a), \
        f"the instance root is the parent of config/: {games_ai._instance_root(srv_a)}"
    assert games_ai._default_instance_name(FakeServer(root=str(root_a))) == name_a, \
        "the same name comes from the same directory only"


def test_the_hostname_plays_no_part_in_the_name(tmp_path, monkeypatch):
    srv_a = FakeServer(root=str(_instance(tmp_path, "a", "server")))
    name_a = games_ai._default_instance_name(srv_a)

    def hostname_must_not_be_called():
        raise AssertionError("socket.gethostname() must not take part in naming an instance")

    monkeypatch.setattr(socket, "gethostname", hostname_must_not_be_called)

    assert games_ai._default_instance_name(srv_a) == name_a, "the hostname plays no part in the name"


def test_spaces_and_punctuation_collapse_into_dashes():
    assert games_ai._sanitize_instance_name("My Server (EU)!") == "My-Server-EU", \
        f"spaces and punctuation collapse into dashes: {games_ai._sanitize_instance_name('My Server (EU)!')}"
    assert games_ai._sanitize_instance_name("生存服") == "", \
        f"a name that sanitizes to nothing reads as empty: {games_ai._sanitize_instance_name('生存服')}"
    assert len(games_ai._sanitize_instance_name("x" * 200)) == games_ai._INSTANCE_NAME_MAX, \
        "an overlong directory name is capped"
    assert games_ai._sanitize_instance_name("") == "" \
        and games_ai._sanitize_instance_name(None) == "", "empty and missing text are safe"


def test_a_cjk_directory_still_yields_a_usable_name(tmp_path):
    cjk_root = _instance(tmp_path, "生存服")

    cjk_name = games_ai._default_instance_name(FakeServer(root=str(cjk_root)))

    assert re.fullmatch(r"gamesai-[0-9a-f]{6}", cjk_name), \
        f"a CJK directory still yields a usable name: {cjk_name}"


def test_without_a_data_folder_the_current_directory_is_used():
    assert games_ai._instance_root(FakeServer(folder=None)) == os.path.abspath(os.getcwd()), \
        f"without a data folder the current directory is used: " \
        f"{games_ai._instance_root(FakeServer(folder=None))}"
    assert re.fullmatch(r"[0-9A-Za-z._-]+-[0-9a-f]{6}",
                        games_ai._default_instance_name(FakeServer(folder=None))), \
        "and it still produces a name"


def test_the_resolver_prefers_a_configured_name(tmp_path):
    srv_a = FakeServer(root=str(_instance(tmp_path, "a", "server")))
    name_a = games_ai._default_instance_name(srv_a)

    resolved, derived = games_ai._resolve_cross_server_name(srv_a, "")
    assert derived and resolved == name_a, f"an empty websocket.name is derived: {resolved}"

    resolved, derived = games_ai._resolve_cross_server_name(srv_a, "alpha")
    assert (resolved, derived) == ("alpha", False), \
        f"a configured websocket.name wins untouched: {(resolved, derived)}"

    resolved, derived = games_ai._resolve_cross_server_name(srv_a, "   ")
    assert derived and resolved == name_a, f"whitespace counts as unset: {resolved}"


def test_the_source_derives_the_name_through_the_resolver():
    source_text = package_text()

    assert "plugin_config.cross_server_name, name_is_derived = " in source_text \
        and "_resolve_cross_server_name(" in source_text, \
        "_apply_config goes through the resolver"
    assert "websocket.name is empty, so this instance is" in source_text \
        and "_instance_root(server) or 'the current directory'" in source_text, \
        "and says which name it derived and from where"
    assert "cross_server_name = plugin_config.websocket_name or socket.gethostname()" \
        not in source_text, "the hostname is no longer a fallback"


def test_the_hub_refuses_to_take_a_name_over(tmp_path, free_port):
    log = logging.getLogger("gamesai-name-test")
    log.handlers = [logging.NullHandler()]
    log.setLevel(logging.DEBUG)
    captured = []

    class Capture(logging.Handler):
        def emit(self, record):
            captured.append(record)

    handler = Capture()
    log.addHandler(handler)
    try:
        node_file = str(tmp_path / "cross_server_nodes.json")
        hub = CrossServerHub("127.0.0.1", free_port(), name="hub", logger=log, node_file=node_file)
        hub.enrol("alpha", app="games_ai_mcdr", ip="10.0.0.5")
        token1 = hub.issue("alpha", app="games_ai_mcdr", issued_by="tester", ip="10.0.0.5",
                           require_pending=True)
        assert bool(token1) and hub.verify("alpha", "games_ai_mcdr", token1) == "ok", \
            "a pending name gets its token"

        before = hub.fingerprint("alpha")
        second = hub.issue("alpha", app="games_ai_mcdr", issued_by="tester", ip="10.0.0.9",
                           require_pending=True)
        assert second is None, "a second token for an enrolled name is refused"
        assert hub.verify("alpha", "games_ai_mcdr", token1) == "ok", \
            "...so the first node is not knocked offline"
        assert hub.fingerprint("alpha") == before, "...and the fingerprint has not moved"

        captured.clear()
        hub.enrol("alpha", app="games_ai_mcdr", ip="10.0.0.9")
        assert any(record.levelno == logging.WARNING and "already enrolled" in record.getMessage()
                   for record in captured), \
            f"re-enrolling under a taken name warns the operator: " \
            f"{[record.getMessage() for record in captured]}"
        assert hub.is_pending("alpha"), "...and the request is still visible in node pending"

        rotated = hub.rotate("alpha", issued_by="tester")
        assert bool(rotated) and rotated != token1 \
            and hub.verify("alpha", "games_ai_mcdr", rotated) == "ok", \
            "node rotate still replaces the token on purpose"
        assert hub.verify("alpha", "games_ai_mcdr", token1) == "unknown", \
            "the rotated-away token is dead"
        assert bool(hub.issue("alpha", app="games_ai_mcdr", issued_by="tester", replace=True)), \
            "replace=True is the explicit way to take a name over"

        assert hub.revoke("alpha"), "revoking frees the name"
        hub.enrol("alpha", app="games_ai_mcdr", ip="10.0.0.5")
        assert bool(hub.issue("alpha", app="games_ai_mcdr", issued_by="tester", ip="10.0.0.5",
                              require_pending=True)), \
            "after a revoke a fresh enrolment can be issued"

        hub.enrol("beta", app="games_ai_mcdr", ip="10.0.0.6")
        beta_token = hub.issue("beta", app="games_ai_mcdr", issued_by="tester", ip="10.0.0.6",
                               require_pending=True)
        reloaded = CrossServerHub("127.0.0.1", free_port(), name="hub", logger=log,
                                  node_file=node_file)
        assert reloaded.is_enrolled("beta") and reloaded.issue("beta", require_pending=True) is None, \
            "the guard survives a hub restart"
        assert reloaded.verify("beta", "", beta_token) == "ok", \
            "...and the stored token still verifies there"

        hub.enrol("gamma")
        assert hub.issue("delta", require_pending=True) is None, \
            "a name that never asked is still refused"
        assert bool(hub.issue("gamma", issued_by="tester", require_pending=True)), \
            "a plainly new name is still issued"
    finally:
        log.removeHandler(handler)


def test_the_bot_provisioning_keeps_its_no_human_step_path():
    server_source = module_text("websockets_server")

    assert 'issued_by="auto-enrolment", ip=ip, replace=True' in server_source, \
        "the bot provisioning keeps its no-human-step path"


def test_the_node_token_command_refuses_a_taken_name(tmp_path, free_port, monkeypatch):
    hub = CrossServerHub("127.0.0.1", free_port(), name="hub",
                         logger=logging.getLogger("gamesai-name-test"),
                         node_file=str(tmp_path / "cross_server_nodes.json"))
    hub.enrol("beta", app="games_ai_mcdr", ip="10.0.0.6")
    hub.issue("beta", app="games_ai_mcdr", issued_by="tester", ip="10.0.0.6", require_pending=True)
    monkeypatch.setattr(games_ai, "_cross_server", FakeManager(hub), raising=False)
    server = FakeServer(root=str(_instance(tmp_path, "a", "server")))

    fingerprint = hub.fingerprint("beta")
    source = FakeSource(server)
    games_ai._node_token(source, {"name": "beta"})
    assert any("token_name_taken" in reply for reply in source.replies), \
        f"!!gamesai node token refuses a name that is taken: {source.replies}"
    assert not any("token_issued" in reply for reply in source.replies), \
        "...prints no token at all"
    assert hub.fingerprint("beta") == fingerprint, "...and mints nothing"
    assert any("name=beta" in reply for reply in source.replies), \
        f"...and passes the offending name to the message: {source.replies}"

    hub.enrol("epsilon", app="games_ai_mcdr", ip="10.0.0.8")
    issuing = FakeSource(server)
    games_ai._node_token(issuing, {"name": "epsilon"})
    assert any("token_issued" in reply for reply in issuing.replies), \
        f"a pending name still gets its token: {issuing.replies}"

    unknown = FakeSource(server)
    games_ai._node_token(unknown, {"name": "zeta"})
    assert any("token_not_pending" in reply for reply in unknown.replies), \
        f"an unknown name still gets the not-pending line: {unknown.replies}"


def test_every_language_carries_the_new_text():
    texts, values, counts = {}, {}, {}
    for lang in ("en_us", "zh_cn", "zh_tw"):
        path = os.path.join(LANG_DIR, lang + ".yml")
        with open(path, "rb") as handle:
            raw = handle.read()
        assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""), \
            f"{lang}: still CRLF only"
        texts[lang] = raw.decode("utf-8")
        found = re.search(r'token_name_taken: "(.*)"', texts[lang])
        values[lang] = found.group(1) if found else ""
        counts[lang] = len(re.findall(r"^\s+[A-Za-z0-9_]+:", texts[lang], re.M))

    assert all(values.values()), f"all three languages carry the new key: {values}"
    assert len(set(values.values())) == 3, "the three texts are different"
    assert len(set(counts.values())) == 1, f"the key sets still match: {counts}"
    assert all(any("\u4e00" <= ch <= "\u9fff" for ch in values[lang])
               for lang in ("zh_cn", "zh_tw")), "the CJK texts are CJK"
    assert all("node rotate" in value for value in values.values()), \
        "every language names the rotate command"
    assert all("websocket.name" in value for value in values.values()), \
        "and every language gives the instance a name to set"
