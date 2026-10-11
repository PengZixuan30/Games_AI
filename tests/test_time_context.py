"""The time reading: what it says, when it is refreshed, and where its clock comes from.

Two problems made this worth rewriting, and both are pinned here:

* the reading used to be refreshed on a round counter alone, so a conversation resumed after a
  night away still told the model yesterday's clock -- now a reading older than
  :data:`TIME_REFRESH_SECONDS` is refreshed whatever the counter says;
* it used to be a bare local time -- now every reading carries the numeric offset, names the
  zone when the name can be trusted, and reports how long ago the previous reading and the
  previous message were.

The zone is detected from the machine (``games_ai/core/clock.py``) and deliberately cannot be
configured, so the tests here never depend on where they run: the zone is injected into the
clock, and the clock's own view of "now" is passed in as an argument.
"""
import datetime
import datetime
import io
import logging
import os
import re
import threading

import pytest
import yaml

from _helpers.paths import LANG_DIR
from games_ai.ai.chat_param import (TIME_INJECT_INTERVAL, TIME_REFRESH_SECONDS, ChatParam,
                                    _epoch_or_none, _time_reading)
from games_ai.core import clock
from games_ai.core.config import SyncPluginConfig

#: The shape the model is given: an ISO date-time with its numeric offset, seconds precision.
ISO_WITH_OFFSET = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")


class FakeServer:
    """What a time reading asks of a server: nothing at all, and that is the point.

    ``rtr`` raises: the reading is English in the code -- it is addressed to the model, not to a
    player -- so a translated line reaching it would mean that rule was broken. A test that needs
    a translated frame for something else passes its own ``rtr``.
    """

    def __init__(self, rtr=None):
        self.logger = logging.getLogger("gamesai_time_probe")
        self._rtr = rtr

    def rtr(self, key, **kwargs):
        if self._rtr is None:
            raise AssertionError("the time reading must not be translated: " + key)
        return self._rtr(key, **kwargs)


@pytest.fixture
def server():
    probe = FakeServer()
    probe.logger.addHandler(logging.NullHandler())
    yield probe


@pytest.fixture(autouse=True)
def machine_zone(monkeypatch):
    """A fixed clock offset and a fixed zone name for every test in this module: +08:00.

    ``clock.local`` is the one function that reads the machine's offset and ``clock.detect`` the
    one that asks the machine for a zone name, so replacing those two makes both the label logic
    and the durations decidable without depending on where the tests run.
    """
    fixed = datetime.timezone(datetime.timedelta(hours=8), "Asia/Shanghai")

    def local(moment):
        return datetime.datetime.fromtimestamp(moment, fixed)

    monkeypatch.setattr(clock, "local", local)
    monkeypatch.setattr(clock, "now", lambda: 1_760_000_000.0)
    monkeypatch.setattr(clock, "detect", lambda: clock.Zone(None, "Asia/Shanghai", "system"))


def bare_param(*, rounds=0, last_read=None, last_message=None, response_list=None):
    """A ChatParam with only the state a time reading touches -- no database, no API client."""
    param = ChatParam.__new__(ChatParam)
    param.server = FakeServer()
    param._ctx_lock = threading.RLock()
    param.response_list = [] if response_list is None else response_list
    param.response_queue = []
    param._rounds_since_time = rounds
    param._last_time_read = last_read
    param._last_message_at = last_message
    return param


def lines(message):
    return str(message["content"]).splitlines()


# ------------------------------------------------------------------ what the model is told

def test_every_reading_carries_an_offset_and_seconds(server):
    """The reading is machine-readable: ISO date-time, numeric offset, no sub-second noise."""
    stamp = clock.timestamp(1_760_000_000.0)

    assert ISO_WITH_OFFSET.match(stamp), f"an ISO timestamp with its offset: {stamp!r}"


def test_the_zone_is_named_when_it_can_be_trusted(monkeypatch):
    resolved = datetime.timezone(datetime.timedelta(hours=8), "Asia/Shanghai")

    monkeypatch.setattr(clock, "detect", lambda: clock.Zone(None, "", "offset"))
    assert clock.zone_label(1_760_000_000.0) == "UTC+08:00", \
        "with no name at all, the offset is still honest about the zone"

    monkeypatch.setattr(clock, "detect", lambda: clock.Zone(resolved, "Asia/Shanghai", "system"))
    assert clock.zone_label(1_760_000_000.0) == "Asia/Shanghai (+08:00)", \
        "an IANA name the runtime can resolve is cross-checked against the clock"


def test_a_zone_name_that_contradicts_the_clock_is_dropped(monkeypatch):
    """A stale cache must never print a name beside an offset that disagrees with it."""
    elsewhere = datetime.timezone(datetime.timedelta(hours=-5), "America/New_York")
    monkeypatch.setattr(clock, "detect", lambda: clock.Zone(elsewhere, "America/New_York",
                                                            "system"))

    assert clock.zone_label(1_760_000_000.0) == "UTC+08:00", \
        "the offset the timestamp was written in wins over a name that does not match it"


def test_the_reading_is_four_english_lines_for_the_model(server):
    """Timestamp, zone and the two elapsed lines -- English literals, not translated strings.

    The fake server's ``rtr`` raises, so this test fails the moment the reading goes back to
    asking the server for a translation.
    """
    message = _time_reading(round_no=7, elapsed_read=192.0, elapsed_message=15_120.0,
                            moment=1_760_000_000.0)

    assert message["role"] == "user", "the reading is a user message, never a second system one"
    assert lines(message) == [
        "Time sampled before round 7: 2025-10-09T16:53:20+08:00",
        "Times without a zone are in the server's time zone (Asia/Shanghai (+08:00)); "
        "ask if something does not fit.",
        "Elapsed since the previous time reading: 3m 12s.",
        "Elapsed since the previous message in this conversation: 4h 12m.",
    ], f"the four lines a reading is made of: {lines(message)}"


def test_a_reading_without_a_baseline_says_so():
    """No baseline -- a new conversation, ``!!ask -n``, an older record -- is not a guess."""
    content = _time_reading(round_no=1, elapsed_read=None, elapsed_message=None,
                            moment=1_760_000_000.0)["content"]

    assert content.count("unavailable") == 2, content
    assert "0s" not in content, f"an unknown duration is not reported as zero: {content}"


def test_the_model_facing_time_text_is_not_in_the_language_files():
    """It is English in the code, so the keys are gone from lang/*.yml -- all three of them."""
    gone = ("user_message.time", "user_message.time_zone", "user_message.time_elapsed_read",
            "user_message.time_elapsed_read_unknown", "user_message.time_elapsed_message",
            "user_message.time_elapsed_message_unknown", "autonomous_bot.time")
    stale = []
    for name in sorted(os.listdir(LANG_DIR)):
        if not name.endswith(".yml"):
            continue
        with io.open(os.path.join(LANG_DIR, name), encoding="utf-8") as handle:
            sections = yaml.safe_load(handle)["games_ai"]
        for dotted in gone:
            section, key = dotted.split(".")
            if key in (sections.get(section) or {}):
                stale.append("{}.{}".format(name, dotted))

    assert not stale, f"the model's clock is not player text: {stale}"


def test_durations_are_compact_and_clamped():
    assert clock.format_duration(42) == "42s"
    assert clock.format_duration(192) == "3m 12s"
    assert clock.format_duration(15_120) == "4h 12m"
    assert clock.format_duration(183_600) == "2d 3h"
    assert clock.format_duration(-90) == "0s", "a clock that moved backwards reads as zero"


def test_the_zone_is_detected_rather_than_configured():
    """There is no knob for the zone, and the machine's own answer is what gets used."""
    knob = [name for name in vars(SyncPluginConfig) if "time" in name.lower() or "zone" in name.lower()]

    assert not knob, f"the clock has no configuration: {knob}"
    assert (TIME_INJECT_INTERVAL, TIME_REFRESH_SECONDS) == (20, 600), \
        "the cadence is pinned in code, so changing it is a visible decision"


def test_the_detected_zone_never_names_a_file_or_a_typo(monkeypatch):
    """``TZ`` is believed only when it is a zone the runtime knows."""
    monkeypatch.setenv("TZ", "Bogus/Zone")
    clock.reset_cache()
    try:
        assert clock._detect().name != "Bogus/Zone", \
            f"a value the runtime cannot resolve is not printed as a zone: {clock._detect()}"
    finally:
        clock.reset_cache()


def test_an_exported_zone_is_used_when_the_runtime_knows_it(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    clock.reset_cache()
    try:
        zone = clock._detect()
        if zone.tzinfo is None:                     # a machine without a zone database
            pytest.skip("this runtime has no IANA zone database (no tzdata)")
        assert (zone.name, zone.source) == ("Asia/Shanghai", "env"), zone
    finally:
        clock.reset_cache()


# ------------------------------------------------------------------ when a reading is refreshed

def test_the_first_round_always_gets_a_reading():
    param = bare_param(rounds=0)

    param._inject_time()

    assert param._rounds_since_time == 1 and len(param.response_list) == 1, \
        f"the first round is told the time: {param.response_list}"
    assert param._last_time_read == 1_760_000_000.0, "and the baseline is recorded"


def test_a_recent_reading_is_not_repeated():
    param = bare_param(rounds=2, last_read=1_760_000_000.0 - 60.0)

    param._inject_time()

    assert param.response_list == [], \
        f"a reading from a minute ago is still fresh: {param.response_list}"


def test_a_stale_reading_is_refreshed_even_between_rounds():
    """The bug this suite exists for: 20 rounds can be 20 seconds or 20 hours."""
    param = bare_param(rounds=3, last_read=1_760_000_000.0 - 2 * TIME_REFRESH_SECONDS)

    param._inject_time()

    assert len(param.response_list) == 1, \
        f"a reading older than {TIME_REFRESH_SECONDS}s is refreshed: {param.response_list}"
    assert param._rounds_since_time == 4, "...without disturbing the round counter"


def test_the_round_counter_still_forces_a_reading():
    param = bare_param(rounds=TIME_INJECT_INTERVAL, last_read=1_760_000_000.0 - 1.0)

    param._inject_time()

    assert len(param.response_list) == 1, \
        "every TIME_INJECT_INTERVAL rounds the model is told the time again"


def test_a_missing_baseline_counts_as_stale():
    """A record written before these fields existed must not silence the reading."""
    param = bare_param(rounds=5, last_read=None)

    param._inject_time()

    assert len(param.response_list) == 1, \
        f"a conversation with no recorded reading gets one: {param.response_list}"
    assert "Elapsed since the previous time reading: unavailable." in \
        param.response_list[0]["content"], \
        f"...and says the elapsed time is unknown: {param.response_list[0]}"


def test_a_clock_that_moved_backwards_still_answers():
    param = bare_param(rounds=0, last_read=1_760_000_000.0 + 3_600.0,
                       last_message=1_760_000_000.0 + 3_600.0)

    param._inject_time()

    content = param.response_list[0]["content"]
    assert "0s." in content, f"elapsed time is clamped, not negative: {content}"


def test_the_reading_lands_in_front_of_the_question():
    param = bare_param(rounds=0, response_list=[{"role": "user", "content": "what time is it?"}])

    param._inject_time()

    assert [message["role"] for message in param.response_list] == ["user", "user"], \
        f"the reading joins the question: {param.response_list}"
    assert param.response_list[1]["content"] == "what time is it?", \
        "...directly in front of it"


# ------------------------------------------------------------------ what the baselines measure

def test_a_real_message_moves_the_message_baseline_only():
    param = bare_param(rounds=1, last_read=1_759_999_000.0)

    param.add_to_response_list("user", "hello")

    assert param._last_message_at == 1_760_000_000.0, "the message baseline moved"
    assert param._last_time_read == 1_759_999_000.0, \
        "a message is not a reading: the reading baseline is untouched"


def test_the_reading_is_not_a_message():
    """Otherwise the "since the previous message" line would always read zero."""
    param = bare_param(rounds=1, last_read=1_759_999_000.0, last_message=1_759_996_400.0)

    param._inject_time()

    assert param._last_message_at == 1_759_996_400.0, \
        "the injected reading must not count as a message"
    assert "Elapsed since the previous message in this conversation: 1h 0m." in \
        param.response_list[0]["content"], \
        f"so the elapsed line still measures the player's message: {param.response_list[0]}"


def test_the_queued_message_baseline_is_taken_when_it_is_written():
    param = bare_param(rounds=1)

    param.forced_add_to_response_list("user", "relayed from another server")

    assert param._last_message_at == 1_760_000_000.0 and param.response_queue, \
        "a queued message is a message as soon as it is written"


def test_an_external_message_moves_the_baseline_too():
    param = bare_param(rounds=1)
    # This path really does format a player-facing frame, so it gets a server that translates.
    param.server = FakeServer(lambda key, **kwargs: "({} says {})".format(key, kwargs.get("sender")))
    param.is_stopped = threading.Event()
    param.is_stopped.set()

    assert param.add_external_message("Alex", "hi", origin="other") == "history"
    assert param._last_message_at == 1_760_000_000.0, \
        "a relayed message counts like any other"


# ------------------------------------------------------------------ what a stored record keeps

def test_a_stored_epoch_is_only_trusted_when_it_is_usable():
    assert _epoch_or_none(None) is None, "a record from an older build has no such key"
    assert _epoch_or_none("yesterday") is None, "...and a damaged value is not a timestamp"
    assert _epoch_or_none(True) is None, "...nor is a boolean"
    assert _epoch_or_none(float("nan")) is None, "...nor is NaN"
    assert _epoch_or_none(1_760_000_000.0 + 3_600.0) is None, \
        "a timestamp the plugin has not reached yet is not trusted"
    assert _epoch_or_none(1_759_000_000) == 1_759_000_000.0, "...a plausible one is kept as a float"
