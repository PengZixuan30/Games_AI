"""Remote permission is read without MCDR's ``auto_add`` side effect.

``ServerInterface.get_permission_level(name)`` calls the permission manager with ``auto_add=True``:
an unknown remote player was appended to ``permission.yml`` at the default level and that level was
returned, so a player who never played here could reach AI-bound tools (and every routed command
rewrote the hub's permission file). The cross-server rule says "unknown means 0".
"""
import pytest

import games_ai

REMOTE_CONSOLE_LEVEL = games_ai.REMOTE_CONSOLE_LEVEL


class PermissionManager:
    def __init__(self, levels):
        self.levels = levels
        self.calls = []

    def get_player_permission_level(self, name, auto_add=True):
        self.calls.append((name, auto_add))
        if auto_add:                       # the behaviour this test forbids
            raise AssertionError("the remote lookup must never auto-add")
        return self.levels.get(name)


class BareServer:
    def __init__(self, levels):
        self.permission_manager = PermissionManager(levels)
        self._mcdr_server = type("M", (), {"permission_manager": self.permission_manager})()


@pytest.fixture
def remote(monkeypatch):
    server = BareServer({"known": 2})
    monkeypatch.setattr(games_ai, "_server_ref", server, raising=False)
    return server


def test_an_unknown_remote_player_gets_zero(remote):
    assert games_ai._resolve_remote_permission({"player": "stranger", "permission": 4}) == 0
    assert remote.permission_manager.calls == [("stranger", False)]
    assert remote.permission_manager.levels.get("stranger") is None, "the name was not added"


def test_a_known_remote_player_gets_the_lower_of_the_two(remote):
    assert games_ai._resolve_remote_permission({"player": "known", "permission": 4}) == 2
    assert games_ai._resolve_remote_permission({"player": "known", "permission": 0}) == 0


def test_a_remote_console_keeps_its_level(remote):
    assert games_ai._resolve_remote_permission({"console": True, "player": None}) == REMOTE_CONSOLE_LEVEL


def test_the_public_api_is_kept_as_a_fallback(monkeypatch):
    class LegacyServer:
        def get_permission_level(self, player):
            return 3

    monkeypatch.setattr(games_ai, "_server_ref", LegacyServer(), raising=False)
    assert games_ai._resolve_remote_permission({"player": "known", "permission": 4}) == 3
