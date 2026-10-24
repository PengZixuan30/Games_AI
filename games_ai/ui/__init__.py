"""What the players see: the in-game help texts.

This module is the package's front door: the entry module imports the help class and its builder
from here. Nothing in this package needs a third-party package, so everything is imported eagerly.
"""
from . import help
from .help import gamesai_help, plugin_version, send_help

__all__ = [
    # the module
    "help",
    # the names
    "gamesai_help", "plugin_version", "send_help",
]
