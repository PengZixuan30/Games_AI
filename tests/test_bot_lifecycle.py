"""Bot lifecycle: a crashed bot can be restarted, and a disabled one cannot come back alone.

* ``!!aibot join`` / the run tool used to compare the config value only: after a crash (or a
  failed first launch) the config said ``enabled: true`` while no process ran, so "already joined"
  was the answer and nothing started. A forced reload now re-reads the real process state.
* A launch that was still waiting for the Minecraft server kept its own thread: disabling the bot
  meanwhile did not stop it, so a node process and an AI controller started after the operator
  had left. The disable path cancels the wait, and the launch checks the abort flag after the
  blocking ``run_node`` and before it creates the controller.
"""
import json
import logging
import os
from types import SimpleNamespace

import pytest

import games_ai
from games_ai.commands import aibot as aibot_commands
from games_ai.core.config import plugin_config


class FakeServer:
    def __init__(self):
        self.logger = logging.getLogger("bot-lifecycle")
        self.executed = []
        self.said = []

    def rtr(self, key, **kwargs):
        return key

    def execute_command(self, raw):
        self.executed.append(raw)

    def say(self, message, **kwargs):
        self.said.append(str(message))

    def is_server_running(self):
        return True


@pytest.fixture
def not_running(monkeypatch):
    monkeypatch.setattr(games_ai, "is_node_running", lambda: False, raising=False)


@pytest.fixture
def running(monkeypatch):
    monkeypatch.setattr(games_ai, "is_node_running", lambda: True, raising=False)


def test_a_forced_toggle_rewrites_the_config_and_reloads(tmp_path, monkeypatch):
    folder = tmp_path / "games_ai"
    (folder / "skills").mkdir(parents=True)
    config_path = folder / "config.json"
    config_path.write_text(json.dumps({"mineflayer_bot": {"enabled": True}}), encoding="utf-8")
    monkeypatch.setattr(plugin_config, "skills_path", str(folder / "skills" / "skills.json"))
    monkeypatch.setattr(plugin_config, "prefix", "[GamesAI]")
    server = FakeServer()

    assert aibot_commands._toggle_aibot(server, True) is True
    assert server.executed == [], "nothing to do when the config already says enabled"

    assert aibot_commands._toggle_aibot(server, True, force=True) is False
    assert server.executed == ["!!gamesai reload"], \
        "force re-reads the real state even when the config value already matches"


def test_the_run_tool_forces_a_reload_when_the_process_is_dead(tmp_path, monkeypatch, not_running):
    folder = tmp_path / "games_ai"
    (folder / "skills").mkdir(parents=True)
    (folder / "config.json").write_text(json.dumps({"mineflayer_bot": {"enabled": True}}), encoding="utf-8")
    monkeypatch.setattr(plugin_config, "skills_path", str(folder / "skills" / "skills.json"))
    monkeypatch.setattr(plugin_config, "prefix", "[GamesAI]")
    monkeypatch.setattr(plugin_config, "bot_username", "Bot")
    calls = []
    monkeypatch.setattr(games_ai.aibot_commands, "_toggle_aibot",
                        lambda server, enabled, force=False: calls.append((enabled, force)))
    monkeypatch.setattr(games_ai, "has_permission", lambda source: True)
    source = SimpleNamespace(get_server=lambda: FakeServer(), reply=lambda message, **kw: None)

    games_ai.run_mineflayer_bot.original(source, "[AI] ") if hasattr(games_ai.run_mineflayer_bot, "original") \
        else games_ai.run_mineflayer_bot(source, "[AI] ")

    assert calls == [(True, True)], \
        "a bot whose config says enabled but whose process is dead is restarted (forced reload)"


def test_cancelling_a_pending_launch_sets_the_abort_flag():
    before = games_ai._mineflayer_launch_token
    games_ai._cancel_pending_bot_launch()
    assert games_ai._mineflayer_pending_abort.is_set()
    assert games_ai._mineflayer_wait_thread is None
    assert games_ai._mineflayer_launch_token == before + 1, \
        "the older wait thread is invalidated, so it cannot launch after a newer decision"


def test_the_stop_stack_cancels_a_pending_launch(monkeypatch):
    stopped = []
    monkeypatch.setattr(games_ai, "stop_mineflayer_process", lambda process=None: stopped.append(process))
    monkeypatch.setattr(games_ai, "detach_mineflayer_process", lambda: None)
    monkeypatch.setattr(games_ai, "clear_bot_peer", lambda: None)
    monkeypatch.setattr(games_ai, "set_bot_controller", lambda controller: None)
    monkeypatch.setattr(games_ai, "_autonomous_controller", None, raising=False)
    games_ai._mineflayer_pending_abort.clear()

    games_ai._stop_bot_stack(None, logger=logging.getLogger("bot-stop"))

    assert games_ai._mineflayer_pending_abort.is_set(), \
        "the teardown cancels a launch that is still waiting for the server"


def test_a_launch_does_not_start_when_the_abort_flag_is_set(monkeypatch):
    server = FakeServer()
    launched = []
    monkeypatch.setattr(games_ai, "run_node", lambda *args, **kwargs: launched.append(args))
    monkeypatch.setattr(games_ai.shutil, "which", lambda name: "node")
    monkeypatch.setattr(games_ai.subprocess, "check_output", lambda *a, **k: "v20.0.0")
    games_ai._mineflayer_pending_abort.set()

    games_ai._launch_mineflayer_bot(server, {}, "init.js")

    assert launched == [], "an aborted launch does not create a node process"


def test_an_abort_during_run_node_stops_the_just_created_process(monkeypatch):
    server = FakeServer()
    stopped = []
    peers = []

    def run_node(*args, **kwargs):
        games_ai._mineflayer_pending_abort.set()   # the unload/disable happens while it runs

    monkeypatch.setattr(games_ai, "run_node", run_node)
    monkeypatch.setattr(games_ai.shutil, "which", lambda name: "node")
    monkeypatch.setattr(games_ai.subprocess, "check_output", lambda *a, **k: "v20.0.0")
    monkeypatch.setattr(games_ai, "stop_mineflayer_process", lambda process=None: stopped.append(True))
    monkeypatch.setattr(games_ai, "set_bot_peer", lambda *a, **k: peers.append(True))
    monkeypatch.setattr(games_ai, "AutonomousBotController", lambda **kwargs: (_ for _ in ()).throw(
        AssertionError("no controller may be built after a cancelled launch")))
    games_ai._mineflayer_pending_abort.clear()

    games_ai._launch_mineflayer_bot(server, {}, "init.js")

    assert stopped == [True], "the node process created by the aborted launch was killed"
    assert peers == [], "the aborted launch never registered the bot peer"


def test_a_new_launch_intent_clears_a_previous_abort(monkeypatch):
    server = FakeServer()
    launched = []
    monkeypatch.setattr(games_ai, "_write_mineflayer_config", lambda *a, **k: None)
    monkeypatch.setattr(games_ai, "_launch_mineflayer_bot", lambda *a, **k: launched.append(True))
    monkeypatch.setattr(games_ai, "_cross_server",
                        SimpleNamespace(peer_uri="ws://hub", name="hub"), raising=False)
    monkeypatch.setattr(plugin_config, "cross_server_mode", "server")
    games_ai._mineflayer_pending_abort.set()

    games_ai._run_mineflayer_bot(server, {}, "init.js")

    assert not games_ai._mineflayer_pending_abort.is_set(), "the new launch intent clears the old abort"
    assert launched == [True], "the bot is launched again after a clean disable"
    assert games_ai._mineflayer_launch_token > 0, "a launch decision carries its own token"
