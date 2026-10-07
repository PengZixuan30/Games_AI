"""P5: ``!!ask compact`` must keep the newest KEEP_ROUNDS rounds verbatim.

The lang message and both docstrings have always promised "the newest 10 rounds are kept as
they are", but ``force=True`` used to hand *every* round to the summarizer and keep none:
``old_rounds = rounds if force else ...`` / ``keep_rounds = [] if force else ...``. The forced
path is the manual ``!!ask compact`` (its only caller), so the player was told the newest 10
rounds survive while the whole history was replaced by one summary. This suite pins the fixed
behaviour: the same slice as the automatic path, a refusal while the history is within
KEEP_ROUNDS, and no ``force`` flag left anywhere.
"""
import os
import re
import threading

import pytest

from _helpers.paths import LANG_DIR
from _helpers.pkg import module_text

from games_ai.chat_param import KEEP_ROUNDS, ChatParam


class FakeServer:
    """Only ``rtr`` is used by the compression (the summary prefix)."""

    def rtr(self, key, **kwargs):
        return "SUMMARY-PREFIX" if key == "games_ai.context.summary_prefix" else key


def make_chat_param(round_count, *, running=False):
    """A ChatParam whose round splitting and summarizing are stubbed out."""
    state = {
        "preamble": [{"role": "system", "content": "PRE"}],
        "rounds": [[{"role": "user", "content": "round {}".format(i)},
                    {"role": "assistant", "content": "answer {}".format(i)}]
                   for i in range(round_count)],
        "summarized": [],
    }
    cp = ChatParam.__new__(ChatParam)
    cp._ctx_lock = threading.RLock()
    cp.server = FakeServer()
    cp.response_list = list(state["preamble"]) + [m for g in state["rounds"] for m in g]
    cp._last_compress = None
    cp._last_estimate = 0
    cp._last_base_estimate = 0
    cp._pending_compaction = False
    cp.context_window = lambda: 1000
    cp._log = lambda *a, **k: None
    cp.is_stopped = threading.Event()
    if not running:
        cp.is_stopped.set()

    def split():
        return list(state["preamble"]), [list(g) for g in state["rounds"]]

    def summarize(old_rounds, existing):
        state["summarized"].append([list(g) for g in old_rounds])
        return "SUM"

    cp._split_rounds = split
    cp._split_rounds_locked = split
    cp._summarize = summarize
    return cp, state


def read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def test_the_forced_path_is_gone_from_the_source():
    source = module_text("chat_param")

    assert KEEP_ROUNDS == 10, f"KEEP_ROUNDS is 10: {KEEP_ROUNDS}"
    assert re.search(r"def _compress_old_rounds\(self\) -> bool:", source) is not None, \
        "_compress_old_rounds takes no force flag"
    assert re.search(r"def _compress_old_rounds_locked\(self\) -> bool:", source) is not None, \
        "_compress_old_rounds_locked takes no force flag"
    assert "force=" not in source, "no force= call is left in chat_param.py"
    assert '"forced"' not in source, "the record no longer stores a forced flag"
    assert "self._compress_old_rounds()" in source, "the deferred call is a plain compression"


def test_the_lang_message_and_the_code_agree():
    for lang, needle in (("en_us", "newest 10 rounds"),):
        text = read(os.path.join(LANG_DIR, "{}.yml".format(lang)))
        assert needle in text, \
            "{}: compact_success promises the newest 10 rounds: {}".format(
                lang, [l for l in text.splitlines() if "compact_success" in l])
    for lang in ("zh_cn", "zh_tw"):
        text = read(os.path.join(LANG_DIR, "{}.yml".format(lang)))
        line = [l for l in text.splitlines() if "compact_success" in l]
        assert bool(line) and "10" in line[0], \
            "{}: compact_success still names the kept rounds: {}".format(lang, line)


def test_the_replacement_rule():
    cp, state = make_chat_param(12)
    result = cp._compress_old_rounds()

    assert result is True, f"12 rounds: compression reports success: {result}"
    assert len(state["summarized"]) == 1 and len(state["summarized"][0]) == 2, \
        "12 rounds: exactly the 2 oldest are summarized: {}".format(
            [len(s) for s in state["summarized"]])
    kept = list(state["rounds"][-KEEP_ROUNDS:])
    expected = (state["preamble"] + [{"role": "system", "content": "SUMMARY-PREFIX\nSUM"}]
                + [m for g in kept for m in g])
    assert cp.response_list == expected, \
        f"12 rounds: the 10 newest are kept verbatim: {cp.response_list}"
    assert cp._last_compress and cp._last_compress.get("rounds") == 2, \
        f"12 rounds: the record counts the replaced rounds: {cp._last_compress}"
    assert sorted(cp._last_compress) == ["after", "before", "ok", "rounds", "time"], \
        f"12 rounds: the record keeps its shape: {sorted(cp._last_compress)}"


@pytest.mark.parametrize("count", [10, 3, 0], ids=["ten rounds", "three rounds", "no rounds"])
def test_a_history_within_keep_rounds_is_left_alone(count):
    cp, state = make_chat_param(count)
    result = cp._compress_old_rounds()

    assert result is False, f"{count} rounds: no compression: {result}"
    assert state["summarized"] == [], \
        f"{count} rounds: no summarizing request: {state['summarized']}"


def test_compact_with_no_round_at_all():
    cp, _state = make_chat_param(0)

    assert cp.compact_history() == "empty", "no round at all -> empty"
    assert cp._pending_compaction is False, "no round at all -> nothing pending"


def test_compact_of_a_history_within_keep_rounds():
    cp, state = make_chat_param(10)

    assert cp.compact_history() == "empty", "10 rounds -> empty (they are the kept ones)"
    assert cp._pending_compaction is False, "10 rounds -> nothing pending"
    assert state["summarized"] == [], \
        f"10 rounds -> no summarizing request: {state['summarized']}"


def test_compact_schedules_and_the_deferred_compression_keeps_the_newest_rounds():
    cp, state = make_chat_param(11)

    assert cp.compact_history() == "scheduled", "11 rounds -> scheduled"
    assert cp._pending_compaction is True, "11 rounds -> pending flag set"

    cp._apply_pending_compaction()

    assert cp._pending_compaction is False, "the deferred compression clears the flag"
    assert len(state["summarized"]) == 1 and len(state["summarized"][0]) == 1, \
        "the deferred compression replaces only the oldest round: {}".format(
            [len(s) for s in state["summarized"]])
    assert len(cp.response_list) == 1 + 1 + 10 * 2, \
        f"the deferred compression keeps the newest 10 rounds: {len(cp.response_list)}"


def test_compact_while_a_round_is_in_flight():
    cp, state = make_chat_param(11, running=True)

    assert cp.compact_history() == "running", "a round in flight -> running"
    assert cp._pending_compaction is False, "a round in flight -> nothing scheduled"
    assert state["summarized"] == [], "a round in flight -> no summarizing request"


def test_compact_of_thirty_rounds_summarizes_the_twenty_oldest():
    cp, state = make_chat_param(30)

    assert cp.compact_history() == "scheduled", "30 rounds -> scheduled"

    cp._apply_pending_compaction()

    assert len(state["summarized"][0]) == 20 and len(cp.response_list) == 1 + 1 + 20, \
        "30 rounds -> 20 oldest summarized, 10 kept: {}".format(
            (len(state["summarized"][0]), len(cp.response_list)))
