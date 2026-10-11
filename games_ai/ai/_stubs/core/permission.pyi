# Generated from games_ai/core/permission.py by tools/build_tool_stubs.py -- do not edit.
from .config import plugin_config as plugin_config
from mcdreforged.command.command_source import CommandSource as CommandSource

TOOL_DENIED_LEVEL: str
TOOL_DENIED_NOT_ALLOWED: str

def has_permission(source: CommandSource) -> bool:
    """Whether ``source`` may use a gated command: its level against the configured one.

    ``>=`` rather than ``>``: the configured value is the lowest level that is allowed, so a
    player at exactly that level passes -- the same rule the wire command source reports for a
    request that travelled from another instance.
    """
def _denied_message(source: CommandSource) -> str:
    """The localized refusal for one source, prefix included."""
def require_permission(source: CommandSource) -> bool:
    """Gate a command or help handler: refuse with a reply and return ``False`` when too low.

    Call sites read ``if not require_permission(source): return`` -- the reply has already been
    sent, so there is nothing left for the caller to answer with.
    """
