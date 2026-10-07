"""websocket.allow_app_id: accept your own service, keep the architecture, trust it fully."""
import json
import logging

import pytest

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as raw_connect

import games_ai
from games_ai.config import plugin_config
from games_ai.cross_server import CrossServerManager
from games_ai.websockets_client import APP_ID, APP_ID_BOT
from games_ai.websockets_server import CrossServerHub

from _helpers.wait import wait_until

LOG = logging.getLogger("hub")


def close_code(exc):
    """The close code of a refused handshake."""
    return getattr(getattr(exc, "rcvd", None), "code", None)


def join(uri, hub, name, app):
    """Register a raw peer; the hub issues one token per node (docs/token-enrollment.md)."""
    conn = raw_connect(uri)
    conn.send(json.dumps({"type": "hello", "app": app, "protocol": 1, "server": name,
                          "token": hub.issue(name, app=app), "version": "0.8.0"}))
    return conn, json.loads(conn.recv(timeout=3))


def collect(peers, seen, timeout=0.3):
    """Move whatever each peer was sent into ``seen``, for the old ``sleep(0.3)`` worth of time.

    ``wait_until`` cannot be told that a frame will *not* arrive, so the poll keeps returning
    False and simply uses the bound up: an absence after it is as strong as it was in the
    stand-alone script, and a positive case still reads everything that did arrive.
    """
    def drain(conn, into):
        try:
            while True:
                into.append(json.loads(conn.recv(timeout=0.1)).get("action"))
        except Exception:
            return                      # nothing more waiting on this connection

    def poll():
        for name, (conn, _) in peers.items():
            drain(conn, seen[name])
        return False

    wait_until(poll, timeout=timeout)
    return seen


@pytest.fixture
def hub(free_port):
    """The hub under test: it admits ``my_service`` on top of the built-in ids."""
    hub = CrossServerHub("127.0.0.1", free_port(), name="host-a", logger=LOG,
                         extra_app_ids=["my_service"])
    assert hub.start(timeout=5), "hub started"
    yield hub
    hub.stop()


@pytest.fixture
def uri(hub):
    return "ws://127.0.0.1:{}".format(hub.port)


@pytest.fixture
def peers(hub, uri):
    """One peer of each kind -- custom service, instance, bot -- closed however the test ends."""
    opened = {name: join(uri, hub, name, app) for name, app in
              (("my-service-host", "my_service"), ("host-b", APP_ID), ("Steve", APP_ID_BOT))}
    yield opened
    for conn, _ in opened.values():
        conn.close()


def test_a_service_listed_in_allow_app_id_may_connect(hub, peers):
    assert hub.accepted_apps >= {APP_ID, APP_ID_BOT}, \
        f"the built-in ids stay accepted: {hub.accepted_apps}"
    assert "my_service" in hub.accepted_apps, f"the configured id is admitted: {hub.accepted_apps}"
    assert hub.command_apps == {"games_ai_mcdr", "my_service"}, \
        f"cluster commands exclude only the bot: {hub.command_apps}"

    _, ack = peers["my-service-host"]
    assert ack.get("type") == "hello_ack", f"it is accepted: {ack}"
    assert ack.get("app") == APP_ID, f"the ack still identifies the hub as games_ai: {ack}"
    assert ack.get("you") == "my_service", f"and echoes the identity it accepted: {ack}"

    assert wait_until(lambda: sorted(hub.peers) == ["Steve", "host-b", "my-service-host"], timeout=0.3), \
        f"all three kinds are online: {hub.peers}"
    assert hub.peer_apps == {"my-service-host": "my_service", "host-b": APP_ID, "Steve": APP_ID_BOT}, \
        f"the identities are recorded apart: {hub.peer_apps}"
    assert hub.peers_of(APP_ID_BOT) == ["Steve"], \
        f"the custom peer is not mistaken for a bot: {hub.peers_of(APP_ID_BOT)}"


def test_it_is_trusted_like_an_instance_but_the_bot_is_still_left_out(hub, peers):
    seen = {"my-service-host": [], "host-b": [], "Steve": []}

    hub.broadcast("exec_cluster", data={"n": 1}, apps=hub.command_apps)
    collect(peers, seen)

    assert "exec_cluster" in seen["my-service-host"], \
        f"the custom service receives a cluster command: {seen}"
    assert "exec_cluster" in seen["host-b"], f"the GamesAI instance receives it too: {seen}"
    assert "exec_cluster" not in seen["Steve"], f"the bot never receives it: {seen}"


def test_an_unlisted_custom_id_is_still_refused(hub, uri):
    try:
        with raw_connect(uri) as conn:
            conn.send(json.dumps({"type": "hello", "app": "other_service", "protocol": 1, "server": "x"}))
            conn.recv(timeout=3)
    except ConnectionClosed as exc:
        code = close_code(exc)
    else:
        pytest.fail("an unlisted id is closed: the frame was answered")
    assert code == 4005, f"an unlisted id -> 4005: {code}"


def test_a_hub_without_the_setting_keeps_refusing_it(free_port):
    plain_port = free_port()
    plain = CrossServerHub("127.0.0.1", plain_port, name="host-c", logger=LOG)
    assert plain.start(timeout=5), "the hub did not start"
    try:
        with raw_connect("ws://127.0.0.1:{}".format(plain_port)) as conn:
            conn.send(json.dumps({"type": "hello", "app": "my_service", "protocol": 1, "server": "x"}))
            conn.recv(timeout=3)
    except ConnectionClosed as exc:
        code = close_code(exc)
    else:
        pytest.fail("without allow_app_id the id is refused: the frame was answered")
    finally:
        plain.stop()
    assert code == 4005, f"without allow_app_id -> 4005: {code}"


def test_the_manager_carries_the_setting_into_the_hub_it_builds(free_port):
    manager = CrossServerManager("ws://127.0.0.1:{}".format(free_port()), name="host-d",
                                 allow_app_id=["my_service"], logger=LOG)
    try:
        assert manager.start(timeout=5) == "server", f"the manager becomes the hub: {manager.reason}"
        assert "my_service" in manager.hub.accepted_apps, \
            f"the hub it built admits the id: {manager.hub.accepted_apps}"
    finally:
        manager.stop()


ALLOW_APP_ID_CASES = (
    (["a", "b"], ["a", "b"], "a plain list"),
    ("solo", ["solo"], "a single string is tolerated"),
    (["dup", "dup", " "], ["dup"], "duplicates and blanks are dropped"),
    ([1, None, "ok"], ["ok"], "non-strings are dropped"),
    ({}, [], "a dict is ignored"),
)


@pytest.fixture(autouse=True)
def plugin_config_state():
    """Put every ``plugin_config`` field back after ``_apply_config`` wrote through them.

    ``monkeypatch`` cannot undo a mutation the code under test performs itself, and those
    fields are process-wide: the next suite in this pytest process would inherit the parsed
    config of this one. Autouse, because it also has to undo the instance attributes
    ``monkeypatch`` itself leaves behind when it restores a class default.
    """
    saved = dict(vars(plugin_config))
    yield
    for key in [key for key in vars(plugin_config) if key not in saved]:
        delattr(plugin_config, key)
    vars(plugin_config).update(saved)


@pytest.mark.parametrize("raw, expected, label", ALLOW_APP_ID_CASES,
                         ids=[case[2] for case in ALLOW_APP_ID_CASES])
def test_allow_app_id_config_parsing(raw, expected, label, monkeypatch, tmp_path):
    class FakeServer:
        logger = logging.getLogger("fake")

        def rtr(self, key, **kw):
            return key

        def get_mcdr_language(self):
            return "zh_cn"

    # _apply_config derives a prompt folder from skills_path; keep it under tmp_path so the
    # conversion never writes inside the repository.
    monkeypatch.setattr(plugin_config, "skills_path", str(tmp_path / "skills" / "skills.json"))
    cfg = {"prefix": "p", "permission": 3, "all_ai": {}, "default_ai": "",
           "mineflayer_bot": {}, "websocket": {"uri": "ws://x:1", "allow_app_id": raw}}
    games_ai._apply_config(FakeServer(), cfg)
    assert plugin_config.websocket_allow_app_id == expected, \
        f"allow_app_id: {label}: {plugin_config.websocket_allow_app_id}"
