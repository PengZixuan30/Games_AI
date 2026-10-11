# Generated from games_ai/core/logger.py by tools/build_tool_stubs.py -- do not edit.
from .config import plugin_config as plugin_config
from _typeshed import Incomplete

PLUGIN_LOGGER_NAME: str
_server: Incomplete

def attach(server) -> None:
    """Take this load's server, and keep the plugin's stdlib records inside MCDR's logger.

    Called once from ``on_load`` (and again from ``_start_cross_server``, which is where the
    plugin's own server reference is kept, so a reload cannot leave this module pointing at the
    previous instance).
    """
def _target(server=None):
    """MCDR's logger when a server is known, this plugin's stdlib logger otherwise."""
def log(level: str, message: str, server=None) -> None:
    """One line through MCDR's logger -- never through the root logger."""
def debug_line(message: str, server=None) -> None:
    """Bookkeeping that must not narrate a busy cluster.

    DEBUG by default; INFO while ``!!gamesai debug`` is on, which is what that switch is for.
    """
def safe(server, level: str, message: str, *, tag: str = '') -> None:
    """Log through ``server``'s logger and never let a log line break the caller.

    ``server`` may be None (then nothing is logged), and a logger that raises is ignored: this
    is what background threads use for lines nobody is waiting for.
    """
def verbose(server, message: str, *, tag: str = 'GamesAI') -> None:
    """A line that is only interesting while ``!!gamesai debug`` is on: INFO then, DEBUG else."""
def step(server, prefix: str):
    '''The "one line per step" callback the updater takes (``log=...``).'''
