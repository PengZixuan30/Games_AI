"""The clock the AI is told about: the server's own time zone, ISO timestamps and durations.

A time reading has to answer three questions a bare ``datetime.now()`` cannot: *when* is it, *in
which zone* is that, and *how long* ago was the previous one. This module owns all three, and it
deliberately has **no configuration**: the zone is the machine's own (see :func:`detect`), because
a Minecraft server already runs in exactly one time zone -- the operator's -- and a knob for it
would only let the plugin disagree with every clock in the room.

The zone name comes from the first source that yields one:

* ``TZ`` -- the POSIX convention, honoured explicitly so a launcher that sets it is believed;
* the system's own record -- ``/etc/timezone`` or the ``/etc/localtime`` link on POSIX, the
  ``TimeZoneKeyName`` registry value on Windows (``China Standard Time`` and friends, which is a
  display name rather than an IANA id);
* the C library's display name (``time.tzname``), which may be localized.

The **offset** never comes from those names: it is read from the system clock itself
(``datetime.fromtimestamp(...).astimezone()``), so daylight saving and a clock that was just
changed are always right. A name is only printed next to that offset when it agrees with it --
an IANA zone whose rules disagree with the machine (a stale cache, a zone changed while the plugin
runs) is dropped instead of being printed beside a contradicting offset. When no name survives,
the reading still carries ``UTC+08:00``: a reading with only an offset is honest, a reading with a
wrong zone name is not.
"""
import datetime
import logging
import os
import time
from typing import NamedTuple

#: The POSIX convention for naming a zone; honoured on every platform when set explicitly.
TZ_ENV = "TZ"
#: POSIX keeps the zone name here, or links ``/etc/localtime`` into the zoneinfo tree instead.
POSIX_ZONE_FILE = "/etc/timezone"
POSIX_LOCALTIME = "/etc/localtime"
POSIX_ZONEINFO_DIRS = ("/usr/share/zoneinfo", "/usr/lib/zoneinfo", "/usr/share/lib/zoneinfo")
#: Windows keeps the zone id (not an IANA name) in the registry.
WINDOWS_ZONE_KEY = r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation"
WINDOWS_ZONE_VALUE = "TimeZoneKeyName"

_log = logging.getLogger("games_ai.clock")

#: The detected zone, resolved once per process: nothing here changes while the plugin runs.
_zone: "Zone | None" = None
_warned = False


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
    return time.time()


def local(moment: float) -> datetime.datetime:
    """``moment`` in the machine's own zone, with the numeric offset attached."""
    return datetime.datetime.fromtimestamp(moment).astimezone()


def timestamp(moment: float | None = None) -> str:
    """An ISO-8601 timestamp with its offset: ``2026-10-11T13:49:50+08:00``."""
    return _at(moment).replace(microsecond=0).isoformat()


def zone_label(moment: float | None = None) -> str:
    """The zone to name in a reading: ``Asia/Shanghai (+08:00)``, or ``UTC+08:00`` alone.

    The name is dropped when it disagrees with the offset the machine reports for that moment:
    the offset is what the timestamp was actually written in, so it is the one that cannot lie.
    """
    at = _at(moment)
    offset = _offset_text(at.utcoffset())
    zone = detect()
    if zone.name and (zone.tzinfo is None or _agrees(zone.tzinfo, moment, at)):
        return "{} ({})".format(zone.name, offset)
    return "UTC" + offset


def describe(moment: float | None = None) -> str:
    """One line for the load log: the label plus the source the name came from."""
    return "{} [{}]".format(zone_label(moment), detect().source)


def format_duration(seconds: float) -> str:
    """A compact whole-second duration: ``42s``, ``3m 12s``, ``4h 12m``, ``2d 3h``.

    Negative input -- a clock that moved backwards -- reads as ``0s``: the reading already shows
    the current time, and "minus four minutes" would only invite the model to reason about it.
    """
    total = int(max(0.0, float(seconds)))
    if total < 60:
        return "{}s".format(total)
    if total < 3600:
        return "{}m {}s".format(total // 60, total % 60)
    if total < 86400:
        return "{}h {}m".format(total // 3600, (total % 3600) // 60)
    return "{}d {}h".format(total // 86400, (total % 86400) // 3600)


def detect() -> Zone:
    """The zone a reading is written in, detected once per process."""
    global _zone
    if _zone is None:
        _zone = _detect()
    return _zone


def reset_cache() -> None:
    """Forget the detected zone (tests, and a reload that wants the environment read again)."""
    global _zone, _warned
    _zone = None
    _warned = False


def _at(moment: float | None) -> datetime.datetime:
    return local(now() if moment is None else moment)


def _detect() -> Zone:
    global _warned
    env = (os.environ.get(TZ_ENV) or "").strip()
    if env:
        # An operator-supplied name is believed only when the runtime knows it: a typo in TZ
        # should not be printed to the model as if it were a zone.
        tzinfo = _zoneinfo(env)
        if tzinfo is not None:
            return Zone(tzinfo, env, "env")
    for name in _system_candidates():
        tzinfo = _zoneinfo(name)
        return Zone(tzinfo, name, "system")
    if not _warned:
        _warned = True
        _log.warning("no time zone could be detected; time readings carry the numeric offset only")
    return Zone(None, "", "offset")


def _system_candidates():
    """The zone names the operating system itself reports, best first."""
    name = _windows_zone_name() if os.name == "nt" else _posix_zone_name()
    for candidate in (name, (time.tzname or ("",))[0]):
        if candidate and candidate.strip():
            yield candidate.strip()


def _windows_zone_name() -> str:
    try:
        import winreg
    except ImportError:                      # not Windows after all
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, WINDOWS_ZONE_KEY) as key:
            return str(winreg.QueryValueEx(key, WINDOWS_ZONE_VALUE)[0] or "").strip()
    except OSError:
        return ""


def _posix_zone_name() -> str:
    try:
        with open(POSIX_ZONE_FILE, encoding="utf-8") as handle:
            name = handle.read().strip()
        if name:
            return name
    except OSError:
        pass
    try:
        target = os.path.realpath(POSIX_LOCALTIME)
    except OSError:
        return ""
    for marker in POSIX_ZONEINFO_DIRS:
        if marker in target:
            return target.split(marker, 1)[1].strip("/")
    return ""


def _zoneinfo(name: str):
    """The IANA zone for ``name``, or None when the name is not one this runtime can resolve.

    ``zoneinfo`` needs the system's zone database; on a Windows machine without the ``tzdata``
    package it has none, which is not an error here -- the offset is read from the clock instead.

    An IANA name is ``Area/Location``, so a slash is normal; what is rejected are the path-like
    values a ``TZ`` variable or a link target can carry (``/etc/localtime``, ``:Asia/Shanghai``).
    """
    if not name or name.startswith(("/", ":")) or "\\" in name or ".." in name:
        return None
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    except ImportError:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def _agrees(tzinfo, moment: float | None, at: datetime.datetime) -> bool:
    """Whether ``tzinfo`` puts that moment at the same offset the machine's clock reports."""
    stamp = now() if moment is None else moment
    try:
        return datetime.datetime.fromtimestamp(stamp, tzinfo).utcoffset() == at.utcoffset()
    except (OverflowError, OSError, ValueError):
        return False


def _offset_text(offset) -> str:
    """"+08:00" for a timedelta, "UTC+08:00" when there is none to report."""
    total = int((offset or datetime.timedelta()).total_seconds())
    sign = "-" if total < 0 else "+"
    total = abs(total)
    return "{}{:02d}:{:02d}".format(sign, total // 3600, (total % 3600) // 60)
