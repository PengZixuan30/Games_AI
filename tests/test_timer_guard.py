"""``setting_timer`` refuses long waits unless the model explicitly asks for one.

An AI round may pass a huge ``duration`` (hours or days) by mistake: the tool used to sleep for
exactly that long while the whole round -- and its only thread -- was blocked. Durations over 600
seconds are now refused with a message that tells the model how to retry for an intentional long
wait; with ``allow_long_wait=True`` the wait is unconditional.
"""
import logging
from types import SimpleNamespace

import pytest

from games_ai.ai import games_ai_tool
from games_ai.ai.games_ai_tool import setting_timer


class FakeServer:
    def __init__(self):
        self.logger = logging.getLogger("timer-server")

    def rtr(self, key, **kwargs):
        return key.format(**kwargs)


class FakeSource:
    def __init__(self, server):
        self.server = server
        self.received = []

    def get_server(self):
        return self.server

    def get_permission_level(self):
        return 4

    def get_info(self):
        return SimpleNamespace(content="")

    @property
    def player(self):
        return "Steve"

    @property
    def is_player(self):
        return True

    @property
    def is_console(self):
        return False

    def reply(self, message, **kwargs):
        self.received.append(str(message))


@pytest.fixture
def sleepy(monkeypatch):
    sleeps = []
    monkeypatch.setattr(games_ai_tool.time, "sleep", lambda seconds: sleeps.append(seconds))
    return SimpleNamespace(sleeps=sleeps, source=FakeSource(FakeServer()))


def test_a_long_wait_is_refused_by_default(sleepy):
    result = setting_timer(sleepy.source, "[AI] ", 3600)
    assert "allow_long_wait=true" in result, "the retry hint is part of the tool result: {}".format(result)
    assert sleepy.sleeps == [], "no sleep happened"


def test_a_long_wait_runs_when_it_is_explicitly_allowed(sleepy):
    result = setting_timer(sleepy.source, "[AI] ", 3600, allow_long_wait=True)
    assert sleepy.sleeps == [3600.0], "the explicit long wait really sleeps"
    assert "Timer finished" in result


def test_a_short_wait_still_runs_by_default(sleepy):
    assert setting_timer(sleepy.source, "[AI] ", 5) == "Timer finished after 5 second(s)"
    assert sleepy.sleeps == [5.0]
    assert setting_timer(sleepy.source, "[AI] ", 600) == "Timer finished after 600 second(s)"


def test_negative_and_invalid_durations_are_refused(sleepy):
    assert "negative" in setting_timer(sleepy.source, "[AI] ", -5)
    assert "Invalid duration" in setting_timer(sleepy.source, "[AI] ", "soon")
    assert sleepy.sleeps == []
