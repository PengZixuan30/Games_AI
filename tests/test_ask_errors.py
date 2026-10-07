"""`!!ask` must survive every provider failure and say what the player can do about it.

A failure used to leave the `!!ask` path as an exception, and MCDR then crashed while
formatting its own error; the player only ever saw that the command broke. Each bucket below
(wrong key, rate limit, broken connection, other status, anything else) now has to produce one
localized reply and a full traceback in the plugin's log, in both the history branch
(`!!ask hi`) and the no-history branch (`!!ask -n hi`).

Since 0.8.0 the reply also carries what the *status code itself* means (402 insufficient
balance, 404 model not found, ...) and the operator's detail line is a WARNING, so it is
readable without turning `!!gamesai debug` on first.
"""
import logging
import os
from types import SimpleNamespace

import httpx
import pytest
import yaml
from openai import (APIConnectionError, APIStatusError, AuthenticationError, NotFoundError,
                    RateLimitError)
from mcdreforged.command.builder.callback import DirectCallbackInvoker, ScheduledCallback

import games_ai
import games_ai.chat_param as chat_param
from _helpers.paths import LANG_DIR
from games_ai.chat_param import describe_http_status
from games_ai.config import plugin_config

MODEL = "test-model"

#: The `ask_error` bucket each provider failure lands in, and the label this suite knows it by.
CASE_BUCKETS = (
    ("authentication", "authentication"),
    ("rate_limit", "rate_limit"),
    ("connection", "connection"),
    ("api_status", "status_500"),
    ("api_status", "status_402"),
    ("api_status", "status_404"),
    ("api_status", "status_418"),
    ("unexpected", "unexpected"),
)


class LogCapture(logging.Handler):
    """Keeps every record the plugin logs through this instance's server logger."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def tracebacks(self) -> list[str]:
        formatter = logging.Formatter()
        return [formatter.format(record) for record in self.records if record.exc_info]

    def warnings(self) -> list[str]:
        return [record.getMessage() for record in self.records if record.levelno == logging.WARNING]


class FakeServer:
    """The plugin's view of MCDR: a data folder, a logger, the real translation table."""

    def __init__(self, folder, lang):
        self.folder = folder
        self.lang = lang
        self.logger = logging.getLogger("ask-error-server")

    def rtr(self, translation_key, *args, **kwargs):
        node = self.lang
        for part in translation_key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if not isinstance(node, str):
            return translation_key
        try:
            return node.format(*args, **kwargs)
        except (IndexError, KeyError) as exc:
            return "<FORMAT ERROR {}: {}>".format(translation_key, exc)

    def get_data_folder(self):
        return self.folder

    def get_permission_level(self, player):
        return 4

    def execute_command(self, raw, source=None):
        return None

    def say(self, message, **kwargs):
        return None


class FakeSource:
    def __init__(self, server, who="Steve", permission=4, console=False, command="!!ask hi"):
        self.server = server
        self.player = None if console else who
        self.permission = permission
        self.console = console
        self.command = command
        self.received = []

    def get_server(self):
        return self.server

    def get_info(self):
        return type("Info", (), {"content": self.command})()

    def get_permission_level(self):
        return self.permission

    @property
    def is_console(self):
        return self.console

    @property
    def is_player(self):
        return not self.console

    def reply(self, message, **kwargs):
        self.received.append(message)

    def text(self):
        return "\n".join(str(item) for item in self.received)

    def __str__(self):
        return "console" if self.console else str(self.player)


class Capture:
    """The command-tree sink ``register_commands`` writes into."""

    def __init__(self):
        self.roots = []

    def register_command(self, node):
        self.roots.append(node)

    def register_help_message(self, **kwargs):
        return None


def read_lang(name: str) -> dict:
    with open(os.path.join(LANG_DIR, name + ".yml"), encoding="utf-8") as handle:
        return yaml.safe_load(handle.read())


@pytest.fixture(scope="module")
def english():
    """The real English table: the server stub and the expectation are read from it alike."""
    return read_lang("en_us")


@pytest.fixture
def env(tmp_path, monkeypatch, english):
    """One plugin load in a throwaway data folder, with the provider call left to the test."""
    server = FakeServer(str(tmp_path), english)
    capture = LogCapture()
    server.logger.addHandler(capture)
    server.logger.setLevel(logging.DEBUG)
    server.logger.propagate = False          # every record stays in `capture`, nothing on stderr

    monkeypatch.setattr(games_ai.logger, "_server", server, raising=False)
    monkeypatch.setattr(games_ai, "_server_ref", server, raising=False)
    monkeypatch.setattr(games_ai, "all_chat_param", {}, raising=False)
    monkeypatch.setattr(games_ai, "_history_frozen", False, raising=False)
    monkeypatch.setattr(games_ai, "_cross_server", None, raising=False)
    monkeypatch.setattr(games_ai, "_player_servers", {}, raising=False)
    monkeypatch.setattr(plugin_config, "prefix", "[GamesAI]")
    monkeypatch.setattr(plugin_config, "data_path",
                        os.path.join(str(tmp_path), "public_database.db"))
    monkeypatch.setattr(plugin_config, "default_ai", MODEL)
    monkeypatch.setattr(plugin_config, "all_ai", {MODEL: {
        "ai_name": "[AI] ", "ai_model": "gpt-test", "base_url": "https://api.example.invalid/v1",
        "api_key": "sk-test", "prompt": "you are a test", "extra_body": {}}})
    monkeypatch.setattr(plugin_config, "skills_description", [])
    monkeypatch.setattr(plugin_config, "allow_permission", 3)
    monkeypatch.setattr(plugin_config, "debug_mode", False)
    try:
        yield SimpleNamespace(server=server, capture=capture, folder=str(tmp_path))
    finally:
        server.logger.removeHandler(capture)
        server.logger.setLevel(logging.NOTSET)
        server.logger.propagate = True


def api_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.example.invalid/v1/chat/completions")


def response(status: int, request_id: str = "") -> httpx.Response:
    resp = httpx.Response(status, request=api_request(),
                          json={"error": {"message": "the provider said no"}})
    if request_id:
        resp._request_id = request_id
    return resp


def bucket_for(label: str) -> str:
    return dict((label, key) for key, label in CASE_BUCKETS)[label]


def make_error(label: str) -> BaseException:
    """The provider failure of one case, built fresh (each SDK error carries its response)."""
    table = {
        "authentication": lambda: AuthenticationError("invalid api key", response=response(401),
                                                      body=None),
        "rate_limit": lambda: RateLimitError("slow down", response=response(429), body=None),
        "connection": lambda: APIConnectionError(request=api_request()),
        "status_500": lambda: APIStatusError("server exploded", response=response(500), body=None),
        "status_402": lambda: APIStatusError("no money", response=response(402, "req_probe_123"),
                                             body=None),
        "status_404": lambda: NotFoundError("no such model", response=response(404), body=None),
        "status_418": lambda: APIStatusError("teapot", response=response(418), body=None),
        "unexpected": lambda: RuntimeError("something else broke"),
    }
    return table[label]()


def expected_reply(lang: dict, key: str, error: BaseException) -> str:
    """The exact line the plugin must print: the localized template filled with the same values.

    The status description is the same table the plugin reads (`error_code_map`), formatted the
    way `_ask_error_reply` does it: a parenthesised meaning when the code has one, nothing when
    it does not.
    """
    status = getattr(error, "status_code", None)
    description = lang["games_ai"]["error_code_map"].get("error{}".format(status), "")
    detail = " ({})".format(description) if description else ""
    text = str(lang["games_ai"]["ask_error"][key]).format(model=MODEL, code=status, error=error,
                                                          detail=detail)
    return "[GamesAI]" + text


def raise_error(error: BaseException):
    def stub(*args, **kwargs):
        raise error
    return stub


# `response_chat` is what both response_ai implementations call; the stub replaces the call the
# SDK would make, so no network is involved and the failure is exactly the one under test.
def run_case(env, monkeypatch, lang, key: str, label: str, error: BaseException, *,
             no_history: bool, source=None):
    """Run one `!!ask` with a stubbed failing provider; returns the source it answered."""
    source = source or FakeSource(env.server,
                                  command="!!ask -n hi" if no_history else "!!ask hi")
    monkeypatch.setattr(chat_param, "response_chat", raise_error(error))
    env.capture.records.clear()
    escaped = None
    try:
        games_ai.ask_ai(source, {"content": "hi"}, no_history=no_history)
    except BaseException as exc:                      # noqa: BLE001 - the point of the test
        escaped = exc
    assert escaped is None, \
        f"no exception escapes ({label}, no_history={no_history}): {escaped!r}"
    assert expected_reply(lang, key, error) in source.text(), \
        f"the player gets the localized {key} line ({label}): {source.text()}"
    traces = env.capture.tracebacks()
    assert any("Traceback" in text and type(error).__name__ in text for text in traces), \
        "the full traceback is logged ({}, no_history={}): {}".format(
            label, no_history,
            [text[:200] for text in traces] or [r.getMessage() for r in env.capture.records])
    return source


def reply_for(env, monkeypatch, label: str, *, no_history: bool = False) -> str:
    """One `!!ask` with a stubbed failing provider, returning only what the player was shown."""
    source = FakeSource(env.server, command="!!ask -n hi" if no_history else "!!ask hi")
    monkeypatch.setattr(chat_param, "response_chat", raise_error(make_error(label)))
    env.capture.records.clear()
    games_ai.ask_ai(source, {"content": "hi"}, no_history=no_history)
    return source.text()


@pytest.mark.parametrize("label", [label for _key, label in CASE_BUCKETS])
def test_every_bucket_in_the_history_branch(env, monkeypatch, english, label):
    run_case(env, monkeypatch, english, bucket_for(label), label, make_error(label),
             no_history=False)


@pytest.mark.parametrize("label", [label for _key, label in CASE_BUCKETS])
def test_the_same_buckets_in_the_no_history_branch(env, monkeypatch, english, label):
    run_case(env, monkeypatch, english, bucket_for(label), label, make_error(label),
             no_history=True)


def test_the_buckets_are_really_different_messages(env, monkeypatch):
    seen_replies = {label: reply_for(env, monkeypatch, label) for _key, label in CASE_BUCKETS}

    assert len(set(seen_replies.values())) == len(CASE_BUCKETS), \
        f"every case has its own reply: {sorted(seen_replies.items())}"
    assert ("HTTP 429" not in seen_replies["authentication"]
            and "API key" in seen_replies["authentication"]), \
        f"a wrong key is not reported as a rate limit: {seen_replies['authentication']}"
    assert "500" in seen_replies["status_500"] and "server exploded" in seen_replies["status_500"], \
        f"the status bucket carries the code and the provider text: {seen_replies['status_500']}"
    assert "could not be reached" in seen_replies["connection"], \
        f"a connection failure says the provider was unreachable: {seen_replies['connection']}"
    assert ("could not be reached" not in seen_replies["unexpected"]
            and "something else broke" in seen_replies["unexpected"]), \
        f"an unknown failure is not dressed up as an API error: {seen_replies['unexpected']}"


def test_what_the_status_code_means_reaches_the_player(env, monkeypatch):
    seen_replies = {label: reply_for(env, monkeypatch, label) for _key, label in CASE_BUCKETS}

    assert "HTTP 402 (Insufficient API Key balance)" in seen_replies["status_402"], \
        f"402 says the balance is empty: {seen_replies['status_402']}"
    assert "HTTP 404 (Requested resource or model does not exist)" in seen_replies["status_404"], \
        f"404 says the model does not exist: {seen_replies['status_404']}"
    assert "HTTP 500 (API server internal error)" in seen_replies["status_500"], \
        f"500 says it is a server error: {seen_replies['status_500']}"
    assert ("HTTP 418," in seen_replies["status_418"]
            and "Unknown error" not in seen_replies["status_418"]), \
        f"an unmapped status adds no parenthesis: {seen_replies['status_418']}"
    assert "418" in seen_replies["status_418"], \
        f"...and still reports the code: {seen_replies['status_418']}"
    assert ("HTTP 429" in seen_replies["rate_limit"]
            and "API Key invalid or not provided" not in seen_replies["authentication"]), \
        "the buckets without a status code stay untouched: ({}, {})".format(
            seen_replies["rate_limit"], seen_replies["authentication"])

    assert (describe_http_status(env.server, 402) == "Insufficient API Key balance"
            and describe_http_status(env.server, 418) == ""
            and describe_http_status(env.server, None) == ""), \
        "the shared table answers the mapped codes and stays silent on the rest: {}".format(
            (describe_http_status(env.server, 402), describe_http_status(env.server, 418),
             describe_http_status(env.server, None)))
    detail = chat_param._ai_error_detail("x", make_error("status_418"), env.server)
    assert "Unknown error (HTTP 418)" in detail, \
        f"...while the log line still names an unmapped code: {detail}"


def test_the_operator_sees_the_detail_without_debug(env, monkeypatch, english):
    assert plugin_config.debug_mode is False, "debug mode is off for this test"

    for no_history in (False, True):
        branch = "no_history" if no_history else "history"
        run_case(env, monkeypatch, english, "api_status", "status_402_warn_" + branch,
                 APIStatusError("no money", response=response(402, "req_probe_123"), body=None),
                 no_history=no_history)
        lines = env.capture.warnings()
        joined = "\n".join(lines)
        assert bool(lines), "a WARNING line is logged ({}): {}".format(
            branch, [record.getMessage()[:120] for record in env.capture.records])
        assert "[Code: 402]" in joined, f"...with the status code ({branch}): {joined}"
        assert "Insufficient API Key balance" in joined, \
            f"...with the localized meaning ({branch}): {joined}"
        assert "[request ID: req_probe_123]" in joined, \
            f"...with the provider request id ({branch}): {joined}"


def test_the_real_registered_ask_callback_survives_it_too(env, monkeypatch, english):
    tree = Capture()
    games_ai.register_commands(tree, {})
    ask_callback = None
    for root in tree.roots:
        if "!!ask" in getattr(root, "literals", set()):
            for child in root.get_children():
                ask_callback = child._callback
    assert ask_callback is not None, "the registered !!ask callback was found"

    source = FakeSource(env.server, command="!!ask hi")
    error = AuthenticationError("invalid api key", response=response(401), body=None)
    monkeypatch.setattr(chat_param, "response_chat", raise_error(error))
    env.capture.records.clear()
    escaped = None
    try:
        ScheduledCallback(ask_callback, (source, {"content": "hi"}), lambda e: e).invoke(
            DirectCallbackInvoker())
    except BaseException as exc:                      # noqa: BLE001 - the point of the test
        escaped = exc
    assert escaped is None, f"MCDR's invocation of !!ask does not raise: {escaped!r}"
    assert expected_reply(english, "authentication", error) in source.text(), \
        f"and the player still got the localized line: {source.text()}"


def test_the_ai_name_lookup(env, monkeypatch):
    entry = {"ai_name": "[AI] ", "ai_model": "gpt-test", "base_url": "", "api_key": "",
             "prompt": "", "extra_body": {}}
    monkeypatch.setattr(plugin_config, "all_ai", {MODEL: dict(entry), "second": dict(entry)})

    assert games_ai._ai_id_for("[AI] ") == "second", \
        f"a configured ai_name resolves to its id: {games_ai._ai_id_for('[AI] ')}"
    assert games_ai._ai_id_for(MODEL) == MODEL, \
        f"an id passes through unchanged: {games_ai._ai_id_for(MODEL)}"
    assert games_ai._ai_id_for("nope") == "nope", "an unknown name passes through unchanged"
    assert games_ai._ai_id_for(MODEL) is not None, \
        "the lookup is a plain call, not a @new_thread body (it returns, it does not defer)"


@pytest.mark.parametrize("name", ["zh_cn", "zh_tw"])
def test_the_reply_is_localized_in_the_other_languages(name):
    lang = read_lang(name)
    texts = {key: lang["games_ai"]["ask_error"][key] for key, _label in CASE_BUCKETS}

    assert all(isinstance(text, str) and text.strip() for text in texts.values()), \
        f"{name} has all five ask_error lines: {texts}"
    assert all(any("\u4e00" <= ch <= "\u9fff" for ch in text) for text in texts.values()), \
        f"{name} writes them in its own language: {texts}"
    assert "{detail}" in texts["api_status"], \
        f"{name} fills the status meaning into the reply: {texts['api_status']}"
    assert all(isinstance(lang["games_ai"]["error_code_map"].get("error{}".format(code)), str)
               for code in (402, 404, 500, 503)), \
        f"{name} maps the codes the reply can mention: {lang['games_ai']['error_code_map']}"
