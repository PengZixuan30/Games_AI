# Generated from games_ai/core/clock.py by tools/build_tool_stubs.py -- do not edit.
import datetime
from _typeshed import Incomplete
from collections.abc import Generator
from typing import NamedTuple

TZ_ENV: str
POSIX_ZONE_FILE: str
POSIX_LOCALTIME: str
POSIX_ZONEINFO_DIRS: Incomplete
WINDOWS_ZONE_KEY: str
WINDOWS_ZONE_VALUE: str
_log: Incomplete
_zone: Zone | None
_warned: bool

class Zone(NamedTuple):
    """The zone a reading is written in.

    ``tzinfo`` is a :class:`zoneinfo.ZoneInfo` when the name is a real IANA zone the runtime can
    resolve -- then it is used to *check* the name against the clock. ``name`` is empty when only
    the numeric offset is known, and ``source`` says where the name came from (``env``,
    ``system`` or ``offset``), which is what the load log prints.
    """
    tzinfo: object | None
    name: str
    source: str

def now() -> float:
    """The wall clock in epoch seconds -- the one place in a reading that reads it."""
def local(moment: float) -> datetime.datetime:
    """``moment`` in the machine's own zone, with the numeric offset attached."""
def timestamp(moment: float | None = None) -> str:
    """An ISO-8601 timestamp with its offset: ``2026-10-11T13:49:50+08:00``."""
def zone_label(moment: float | None = None) -> str:
    """The zone to name in a reading: ``Asia/Shanghai (+08:00)``, or ``UTC+08:00`` alone.

    The name is dropped when it disagrees with the offset the machine reports for that moment:
    the offset is what the timestamp was actually written in, so it is the one that cannot lie.
    """
def describe(moment: float | None = None) -> str:
    """One line for the load log: the label plus the source the name came from."""
def format_duration(seconds: float) -> str:
    '''A compact whole-second duration: ``42s``, ``3m 12s``, ``4h 12m``, ``2d 3h``.

    Negative input -- a clock that moved backwards -- reads as ``0s``: the reading already shows
    the current time, and "minus four minutes" would only invite the model to reason about it.
    '''
def detect() -> Zone:
    """The zone a reading is written in, detected once per process."""
def reset_cache() -> None:
    """Forget the detected zone (tests, and a reload that wants the environment read again)."""
def _at(moment: float | None) -> datetime.datetime: ...
def _detect() -> Zone: ...
def _system_candidates() -> Generator[Incomplete]:
    """The zone names the operating system itself reports, best first."""
def _windows_zone_name() -> str: ...
def _posix_zone_name() -> str: ...
def _zoneinfo(name: str):
    """The IANA zone for ``name``, or None when the name is not one this runtime can resolve.

    ``zoneinfo`` needs the system's zone database; on a Windows machine without the ``tzdata``
    package it has none, which is not an error here -- the offset is read from the clock instead.

    An IANA name is ``Area/Location``, so a slash is normal; what is rejected are the path-like
    values a ``TZ`` variable or a link target can carry (``/etc/localtime``, ``:Asia/Shanghai``).
    """
def _agrees(tzinfo, moment: float | None, at: datetime.datetime) -> bool:
    """Whether ``tzinfo`` puts that moment at the same offset the machine's clock reports."""
def _offset_text(offset) -> str:
    '''"+08:00" for a timedelta, "UTC+08:00" when there is none to report.'''
