"""Who may run what: the one permission gate every command, help page and tool goes through.

The check itself is a single comparison -- the caller's permission level against
``plugin_config.allow_permission`` -- but the *shape* of the refusal depends on the caller, and
that is what this module owns:

* :func:`require_permission` -- a command or a help handler: answer with the localized refusal
  (prefix included, like every other line those handlers print) and return ``False``;
* :func:`has_permission` -- the predicate behind it, for the two callers that want no reply: the
  tool functions return one of the ``TOOL_DENIED_*`` sentences to the AI instead, and the help
  listing simply *shows* the gated commands when the caller may use them.

The refusal texts are named here rather than written out at each call site so that a wording
change is one edit; ``TOOL_DENIED_LEVEL`` and ``TOOL_DENIED_NOT_ALLOWED`` are returned to the
model verbatim, which is why they are kept in English like the rest of that channel.

This lives in a module of its own because :mod:`games_ai.ui.help` is a leaf: the entry module
imports the help texts, and a helper that imported the entry package back would close that cycle
(``tests/test_layout.py`` pins "no module imports the entry package").
"""
from mcdreforged.command.command_source import CommandSource

from .config import plugin_config

#: What a tool returns when the caller's level is below the configured one.
TOOL_DENIED_LEVEL = ("Permission denied: this tool requires a higher permission level than the "
                     "requesting player has")

#: What the tool wrappers that never mention a level return (the ``!!data`` ones in the entry).
TOOL_DENIED_NOT_ALLOWED = "Permission denied: the requesting player is not allowed to use this tool"


def has_permission(source: CommandSource) -> bool:
    """Whether ``source`` may use a gated command: its level against the configured one.

    ``>=`` rather than ``>``: the configured value is the lowest level that is allowed, so a
    player at exactly that level passes -- the same rule the wire command source reports for a
    request that travelled from another instance.
    """
    return source.get_permission_level() >= plugin_config.allow_permission


def _denied_message(source: CommandSource) -> str:
    """The localized refusal for one source, prefix included."""
    return (f"{plugin_config.prefix}"
            f"{source.get_server().rtr('games_ai.no_permission', permission=plugin_config.allow_permission)}")


def require_permission(source: CommandSource) -> bool:
    """Gate a command or help handler: refuse with a reply and return ``False`` when too low.

    Call sites read ``if not require_permission(source): return`` -- the reply has already been
    sent, so there is nothing left for the caller to answer with.
    """
    if has_permission(source):
        return True
    source.reply(_denied_message(source))
    return False
