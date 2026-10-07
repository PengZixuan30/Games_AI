"""Run the real embedded bot JS against a real GamesAI hub, then through BotPeerClient.

This is the stage-2 integration test: the JS text is taken verbatim from
games_ai/mineflayer_service_files.py, the Minecraft-side dependencies are stubbed (the bot never
has to log in), and the hub client socket is the real `ws` package.
"""
import io
import logging
import os
import shutil
import subprocess
import threading

import pytest

import games_ai
from _helpers.paths import JS_DIR, PKG
from _helpers.wait import wait_until
from games_ai.cross_server import CrossServerManager
from games_ai.mineflayer import clear_bot_peer, get_mineflayer_client, set_bot_peer

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("test")

STUBS = """// ---- test stubs: the bot must not log into Minecraft for this test ----
const Module = require('module');
const realLoad = Module._load;
Module._load = function (request, parent, isMain) {
    if (request === 'vec3') {
        return class Vec3 { constructor(x, y, z) { this.x = x; this.y = y; this.z = z; } };
    }
    if (request === 'mineflayer') {
        return { createBot: () => { throw new Error('the bot must not be created in this test'); } };
    }
    if (request === 'mineflayer-pathfinder' || request === 'mineflayer-mcefly') {
        throw new Error('optional plugin not installed in this test');
    }
    return realLoad.apply(this, arguments);
};

"""

DRIVER = """

// ---- test driver: register on the hub with a fake, already-joined bot ----
config.enabled = true;
config.websocket.url = process.env.HUB_URL;
config.websocket.reconnect_interval = 1;
config.bot.username = 'TestBot';
bot = { entity: { position: { x: 0, y: 64, z: 0 } }, chat: (m) => console.log('[test] bot.chat ' + m) };
connectToHub();
console.log('[test] driver started against ' + config.websocket.url);
"""


@pytest.fixture
def bot_harness(tmp_path):
    """The embedded bot JS plus the vendored `ws` module, assembled outside the repository.

    The suite used to write `bot_harness.js` into `tests/js/` and copy the `ws` module into
    `tests/js/node_modules/`; a pytest run may not write inside the checkout. The harness is
    assembled under ``tmp_path`` instead, with the vendored module tree copied next to it, which
    is where node's own resolution finds ``require('ws')``.
    """
    if shutil.which("node") is None:
        pytest.skip("node is not on PATH: the JavaScript bot test cannot run")

    source = io.open(os.path.join(PKG, "mineflayer_service_files.py"), encoding="utf-8").read()
    marker = '_INIT_JS_CONTENT = r"""'
    start = source.index(marker) + len(marker)
    bot_js = source[start:source.index('"""', start)]

    shutil.copytree(os.path.join(JS_DIR, "node_modules"),
                    os.path.join(str(tmp_path), "node_modules"))
    with io.open(os.path.join(str(tmp_path), "bot_harness.js"), "w",
                 encoding="utf-8", newline="") as handle:
        handle.write(STUBS + bot_js + DRIVER)
    return str(tmp_path)


@pytest.fixture
def hub(free_port):
    """A real hub on a free loopback port, stopped however the test ends."""
    uri = "ws://127.0.0.1:{}".format(free_port())
    manager = CrossServerManager(uri, name="host-a", version="0.8.0", logger=log)
    mode = manager.start(timeout=5)
    yield manager, uri, mode
    manager.stop()


@pytest.fixture
def bot_process(bot_harness, hub):
    """The bot as a real `node` process, with its output pumped into a list.

    Teardown terminates whatever is still running, so a failing assertion cannot leave a node
    process (or a registered bot peer) behind for the next test.
    """
    _manager, uri, _mode = hub
    env = dict(os.environ, HUB_URL=uri)
    node = subprocess.Popen(
        ["node", "bot_harness.js"], cwd=bot_harness, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        errors="replace",
    )
    lines = []

    def pump():
        for line in node.stdout:
            lines.append(line.rstrip())

    threading.Thread(target=pump, daemon=True).start()
    yield node, lines

    if node.poll() is None:
        node.terminate()
        try:
            node.wait(timeout=10)
        except subprocess.TimeoutExpired:
            node.kill()
            node.wait(timeout=10)
    clear_bot_peer()


def test_the_embedded_bot_js_registers_and_answers_actions(hub, bot_process):
    manager, _uri, mode = hub
    node, lines = bot_process

    assert mode == "server", f"manager hosts the hub: {(mode, manager.reason)}"

    assert wait_until(lambda: "TestBot" in manager.peers, timeout=15), \
        f"the bot registered on the hub: {manager.peers}"
    assert wait_until(lambda: any("Registered on hub" in l for l in lines), timeout=5), \
        f"hello_ack was accepted by the bot: {lines[-6:]}"

    set_bot_peer(manager, "TestBot", log)
    client = get_mineflayer_client()
    assert client is not None, "BotPeerClient resolves"
    assert client.is_connected, "BotPeerClient.is_connected"

    result = client.send_command("chat", {"message": "hello from the test"}, timeout=5)
    assert set(result.keys()) >= {"request_id", "status", "data"}, f"legacy result shape: {result}"
    assert result.get("status") == "success" and result.get("data", {}).get("message") == "Message sent", \
        f"chat answered with success: {result}"
    assert wait_until(lambda: any("bot.chat hello from the test" in l for l in lines), timeout=5), \
        f"the bot really ran the action: {lines[-6:]}"

    result = client.send_command("this_action_does_not_exist", {}, timeout=5)
    assert result.get("status") == "error", f"unknown action reports an error status: {result}"
    assert "Unknown action" in str(result.get("data")), f"error payload carries the reason: {result}"

    reply = manager.send_to("TestBot", "bot_action",
                            data={"action": "chat", "params": {"message": "x"}},
                            wait=True, timeout=5)
    assert reply and reply.get("ok"), f"a direct bot_action round trip works: {reply}"

    node.terminate()
    try:
        node.wait(timeout=10)
    except subprocess.TimeoutExpired:
        node.kill()

    assert wait_until(lambda: "TestBot" not in manager.peers, timeout=10), \
        f"the hub notices the bot is gone: {manager.peers}"
    assert not client.is_connected, "BotPeerClient.is_connected follows"

    try:
        client.send_command("chat", {"message": "anyone?"}, timeout=2)
        raised = None
    except Exception as exc:
        raised = exc
    assert isinstance(raised, ConnectionError), \
        "send_command raises when the bot is gone: {}".format(
            type(raised).__name__ if raised else "no exception")

    clear_bot_peer()
    assert get_mineflayer_client() is None, "clear_bot_peer forgets the link"
