"""Every log line this plugin writes goes through here.

Two problems used to be solved in four different places, which is why they live in one module
now:

* a record logged through the standard library (``logging.getLogger("games_ai...")``)
  propagates to the **root** logger, where the host prints it in a bare
  ``LEVEL:name:message`` format next to MCDR's own lines. :func:`attach` keeps MCDR's handlers
  on the ``games_ai`` logger and cuts propagation, so every such call -- including future ones
  -- stays inside MCDR's log;
* "visible only while ``!!gamesai debug`` is on" used to be copied into each class that wanted
  a bookkeeping line (both ``ChatParam`` classes had their own ``_log``, and ``__init__.py``
  had ``_chat_log`` for the same rule with a different tag). That rule is :func:`verbose` now;
  the only thing a caller chooses is the tag in front of the line.

Which function belongs where:

* :func:`log` and :func:`debug_line` -- this plugin's own bookkeeping where no ``server`` is in
  scope. They use the server handed to :func:`attach`, and fall back to the ``games_ai`` stdlib
  logger (which :func:`attach` wires into MCDR) so an early or detached call is still not lost;
* :func:`verbose` and :func:`safe` -- an explicit server: a class logging about itself, or code
  that must never fail because of a log line.

The configured ``prefix`` is deliberately **not** added here: callers write what the line is
about, and :func:`step` takes the prefix it should put in front of an updater step.

The OpenAI SDK's records are bridged separately, by ``openai_api.setup_openai_logging``: that
one rewrites what the SDK logs about its own HTTP calls, not what this plugin logs.
"""
import logging

from .config import plugin_config

#: The stdlib logger :func:`attach` wires into MCDR; everything under it lands in MCDR's log.
PLUGIN_LOGGER_NAME = "games_ai"

#: The server of the current load, set by :func:`attach`.
_server = None


def attach(server) -> None:
    """Take this load's server, and keep the plugin's stdlib records inside MCDR's logger.

    Called once from ``on_load`` (and again from ``_start_cross_server``, which is where the
    plugin's own server reference is kept, so a reload cannot leave this module pointing at the
    previous instance).
    """
    global _server
    _server = server
    plugin_logger = logging.getLogger(PLUGIN_LOGGER_NAME)
    for handler in getattr(getattr(server, "logger", None), "handlers", None) or []:
        if handler not in plugin_logger.handlers:
            plugin_logger.addHandler(handler)
    plugin_logger.propagate = False
    plugin_logger.setLevel(logging.INFO)


def _target(server=None):
    """MCDR's logger when a server is known, this plugin's stdlib logger otherwise."""
    chosen = server if server is not None else _server
    logger = getattr(chosen, "logger", None) if chosen is not None else None
    return logger if logger is not None else logging.getLogger(PLUGIN_LOGGER_NAME + ".standalone")


def log(level: str, message: str, server=None) -> None:
    """One line through MCDR's logger -- never through the root logger."""
    getattr(_target(server), level)(message)


def debug_line(message: str, server=None) -> None:
    """Bookkeeping that must not narrate a busy cluster.

    DEBUG by default; INFO while ``!!gamesai debug`` is on, which is what that switch is for.
    """
    log("info" if plugin_config.debug_mode else "debug", message, server)


def safe(server, level: str, message: str, *, tag: str = "") -> None:
    """Log through ``server``'s logger and never let a log line break the caller.

    ``server`` may be None (then nothing is logged), and a logger that raises is ignored: this
    is what background threads use for lines nobody is waiting for.
    """
    logger = getattr(server, "logger", None) if server is not None else None
    if logger is None:
        return
    try:
        getattr(logger, level)(f"[{tag}] {message}" if tag else message)
    except Exception:
        pass


def verbose(server, message: str, *, tag: str = "GamesAI") -> None:
    """A line that is only interesting while ``!!gamesai debug`` is on: INFO then, DEBUG else."""
    safe(server, "info" if plugin_config.debug_mode else "debug", message, tag=tag)


def step(server, prefix: str):
    """The "one line per step" callback the updater takes (``log=...``)."""
    return lambda message: safe(server, "info", f"{prefix} {message}")
