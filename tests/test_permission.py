"""One gate for every permission check: the rule, its refusal and the texts a tool hands back.

``games_ai/core/permission.py`` replaced a node-only helper plus the forty copies of the same
comparison that had grown beside it, so this module pins what "one place" means: the rule itself,
the refusal every command path prints, the two sentences that go back to the model instead, and
the fact that no call site went back to comparing levels by hand.
"""
import re

import pytest

from _helpers.pkg import module_names, module_text
from games_ai.core import permission
from games_ai.core.config import plugin_config


class FakeServer:
    """Enough of a server for ``rtr``: the key plus the arguments, so a test can read them back."""

    def rtr(self, key, **kwargs):
        rendered = ",".join("{}={}".format(name, value) for name, value in sorted(kwargs.items()))
        return "[{} {}]".format(key, rendered)


class FakeSource:
    """A command source that records what was replied to it."""

    def __init__(self, level, console=False):
        self.level = level
        self.console = console
        self.replies = []

    def get_permission_level(self):
        return self.level

    def get_server(self):
        return FakeServer()

    @property
    def is_console(self):
        return self.console

    def reply(self, message):
        self.replies.append(message)


@pytest.fixture
def configured(monkeypatch):
    """Set the configured level (and prefix) for one test; ``monkeypatch`` restores them."""
    def _configured(level, prefix="[GamesAI]"):
        monkeypatch.setattr(plugin_config, "allow_permission", level, raising=False)
        monkeypatch.setattr(plugin_config, "prefix", prefix, raising=False)
    return _configured


def test_the_rule_is_the_configured_level_or_higher(configured):
    configured(3)

    assert permission.has_permission(FakeSource(3)), "the configured level itself is allowed"
    assert permission.has_permission(FakeSource(4)), "and so is anything above it"
    assert not permission.has_permission(FakeSource(2)), "one level below is not"


def test_the_gate_is_silent_when_the_level_is_enough(configured):
    configured(3)

    source = FakeSource(3)

    assert permission.require_permission(source) is True, "the gate lets the caller through"
    assert source.replies == [], f"and answers nothing: {source.replies}"


def test_the_gate_answers_with_the_localized_refusal(configured):
    configured(3, prefix="[T]")

    source = FakeSource(1)

    assert permission.require_permission(source) is False, "the gate stops the caller"
    assert len(source.replies) == 1, f"exactly one reply: {source.replies}"
    reply = source.replies[0]
    assert reply.startswith("[T]"), f"the refusal carries the message prefix: {reply}"
    assert "games_ai.no_permission" in reply, f"the localized key is what is answered: {reply}"
    assert "permission=3" in reply, f"and it names the level that would be required: {reply}"


def test_the_refusal_follows_the_configured_level(configured):
    configured(4, prefix="[T]")

    source = FakeSource(3)

    assert permission.require_permission(source) is False, "level 3 is below a configured 4"
    assert "permission=4" in source.replies[0], f"the reply names the new level: {source.replies[0]}"


def test_the_tool_texts_are_the_sentences_the_model_gets():
    assert permission.TOOL_DENIED_LEVEL == (
        "Permission denied: this tool requires a higher permission level than the "
        "requesting player has"), "the level-aware tool refusal is unchanged"
    assert permission.TOOL_DENIED_NOT_ALLOWED == (
        "Permission denied: the requesting player is not allowed to use this tool"), \
        "the data-tool refusal is unchanged"


def test_every_tool_that_checks_a_level_returns_the_shared_text():
    """The eight call sites hand back the constant instead of spelling the sentence out.

    The registry module is named by its full path: ``games_ai_tool.py`` alone now also matches
    the compatibility re-export at the package root (see tests/test_tool_compat.py).
    """
    for name in ("ai/games_ai_tool.py", "__init__.py"):
        text = module_text(name)
        assert "Permission denied" not in text, f"{name} writes a refusal out by hand"
        assert "has_permission(source)" in text, f"{name} does not ask the shared predicate"


def test_the_help_pages_go_through_the_same_gate(configured):
    from games_ai.ui.help import gamesai_help

    configured(3, prefix="[T]")
    refused = FakeSource(1)
    gamesai_help.data_help(refused)
    assert len(refused.replies) == 1 and "games_ai.no_permission" in refused.replies[0], \
        f"a gated help page refuses through the gate: {refused.replies}"

    configured(3, prefix="[T]")
    allowed = FakeSource(3)
    gamesai_help.data_help(allowed)
    assert allowed.replies and "games_ai.no_permission" not in "".join(map(str, allowed.replies)), \
        f"and prints its lines when the level is enough: {allowed.replies}"


def test_the_help_listing_shows_the_gated_commands_only_with_the_level(configured):
    from games_ai.ui.help import gamesai_help

    configured(3)
    refused = FakeSource(1)
    gamesai_help.all_help(refused)
    assert "clear_other_help" not in "".join(map(str, refused.replies)), \
        "the listing hides the management commands from a player below the level"

    configured(3)
    allowed = FakeSource(3)
    gamesai_help.all_help(allowed)
    assert "clear_other_help" in "".join(map(str, allowed.replies)), \
        "and shows them once the level is enough"


def test_no_call_site_compares_permission_levels_by_hand():
    """The point of the module: the comparison lives in one file only."""
    hand_written = re.compile(r"get_permission_level\(\)\s*[<>]=?\s*plugin_config\.allow_permission")
    offenders = [name for name in module_names()
                 if name != "core/permission.py" and hand_written.search(module_text(name))]

    assert not offenders, f"every gate goes through games_ai.core.permission: {offenders}"
