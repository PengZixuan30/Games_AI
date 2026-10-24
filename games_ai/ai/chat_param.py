from abc import ABC, abstractmethod
from collections.abc import Callable
from openai import OpenAI
import json, datetime, math, threading, time

from .openai_api import response_chat
from ..core.config import plugin_config
from ..core import clock, logger
from . import context_table
from .context_table import resolve_context_window, resolve_max_output
from .games_ai_tool import get_request_tool_schemas, get_tool_handler
from .external_skills_loader import EXTERNAL_SKILLS_LIST
from ..cluster.ws_command import WebSocketCommandSource

from mcdreforged.command.command_source import CommandSource
from mcdreforged.plugin.si.server_interface import ServerInterface
from openai.types.chat.chat_completion_message_function_tool_call import ChatCompletionMessageFunctionToolCall

# ── context management tuning ───────────────────────────────────────────────
KEEP_ROUNDS = 10                 # always keep the latest N rounds verbatim
TRIGGER_HISTORY_RATIO = 0.80     # compress when the current context >= 80% of the window
TRIGGER_REQUEST_RATIO = 0.20     # compress when one request >= 20% of the window
EMERGENCY_RATIO = 0.95           # pre-flight safety line
EMERGENCY_TARGET_RATIO = 0.85    # reduce down to this ratio in emergencies
MESSAGE_TOKEN_CAP_RATIO = 0.08   # per-message cap (tool results / long messages)
MESSAGE_TOKEN_CAP_ABS = 16000
SUMMARY_INPUT_RATIO = 0.30       # summarization input budget (share of the window)
SUMMARY_TIMEOUT = 60             # seconds
TOOLS_FIXED_OVERHEAD = 200       # provider-side tool/chat-template scaffolding
NON_HISTORY_WINDOW_RATIO = 0.80  # last-resort trim line for single-round (no-history) requests
TIME_INJECT_INTERVAL = 20        # rounds between two time injections (the first round always gets one)
# The other half of the rule: a reading older than this is stale no matter how few rounds have
# passed, so a conversation resumed after a night away is told the new time before it answers.
# Ten minutes matches the default of the DSH time-context package this reading is modelled on;
# it is deliberately not a configuration knob.
TIME_REFRESH_SECONDS = 600
CALIBRATION_ALPHA = 0.30
CALIBRATION_MIN = 0.5
CALIBRATION_MAX = 3.0

_ASCII_TOKEN_DIVISOR = 4.0       # latin text ≈ 4 chars / token
_MESSAGE_OVERHEAD = 4            # role + delimiters per message

_CJK_RANGES = (
    (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF),
    (0x3040, 0x30FF), (0xAC00, 0xD7AF),
)

_calibration_store: dict[str, float] = {}
_calibration_lock = threading.Lock()

# What a provider HTTP status means, for the operator's log line (see _ai_error_detail). The
# player-facing sentence is built by `ask_ai`, which knows the action to recommend.
_ERROR_CODE_KEYS = {
    400: "games_ai.error_code_map.error400",
    401: "games_ai.error_code_map.error401",
    402: "games_ai.error_code_map.error402",
    403: "games_ai.error_code_map.error403",
    404: "games_ai.error_code_map.error404",
    408: "games_ai.error_code_map.error408",
    422: "games_ai.error_code_map.error422",
    429: "games_ai.error_code_map.error429",
    500: "games_ai.error_code_map.error500",
    502: "games_ai.error_code_map.error502",
    503: "games_ai.error_code_map.error503",
}


def _calibration_key(base_url: str, model: str) -> str:
    return f"{base_url}|{model}"


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    for low, high in _CJK_RANGES:
        if low <= code <= high:
            return True
    return False


def estimate_text_tokens(text: str) -> int:
    """
    Rough token estimation that works across tokenizers and languages.

    latin: ~4 characters per token; CJK: ~1 token per character. The systematic
    bias of a specific provider/model is corrected by the usage calibration below.
    """
    if not text:
        return 0
    cjk = 0
    for ch in text:
        if _is_cjk(ch):
            cjk += 1
    latin = len(text) - cjk
    return int(latin / _ASCII_TOKEN_DIVISOR + cjk * 1.0) + 1


def _shrink_text(text: str, cap_tokens: int) -> str:
    """Return the longest prefix of ``text`` that estimates within ``cap_tokens``."""
    if cap_tokens <= 0:
        return ""
    if estimate_text_tokens(text) <= cap_tokens:
        return text
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if estimate_text_tokens(text[:mid]) <= cap_tokens:
            low = mid
        else:
            high = mid - 1
    return text[:low]


def _int_at(usage: dict, section: str, key: str) -> int:
    """One nested usage counter (``prompt_tokens_details.cached_tokens`` etc.), or 0."""
    try:
        value = (usage.get(section) or {}).get(key)
        return int(value or 0)
    except (AttributeError, TypeError, ValueError):
        return 0


def _role_counts(messages) -> dict[str, int]:
    """How many messages of each role the history holds (for ``!!ask context``)."""
    counts: dict[str, int] = {}
    for msg in messages:
        role = _msg_role(msg) or "?"
        counts[role] = counts.get(role, 0) + 1
    return counts


def _msg_role(msg) -> str | None:
    if isinstance(msg, dict):
        return msg.get("role")
    return getattr(msg, "role", None)


def _msg_tool_calls(msg):
    """The ``tool_calls`` of a message, or None (dicts and SDK objects)."""
    if isinstance(msg, dict):
        return msg.get("tool_calls")
    return getattr(msg, "tool_calls", None)


def _msg_content(msg) -> str:
    content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
    return str(content) if content else ""


def _int_or_zero(value) -> int:
    """One stored counter, or 0 when it is missing or not a number."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _json_safe(value):
    """A JSON-primitive-only copy of a provider value.

    The raw usage dict and the compression note travel inside the stored conversation record, and
    that record is written with ``json.dumps``: one value the encoder cannot handle would lose the
    **whole** conversation, so anything that is not a plain primitive, list or dict is turned into
    a string at the leaf.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return str(value)


def message_to_json(msg) -> dict:
    """One history message as a plain, JSON-serializable dict.

    ``response_ai`` appends the SDK's ``ChatCompletionMessage`` object to the history exactly as
    the provider returned it, so the stored list is a mix of dicts and SDK objects. This is the
    single normal form the history store writes -- and the form the provider accepts again on the
    next request. ``reasoning_content`` survives on purpose: providers that return it require it
    back in the tool-call round that produced it.
    """
    if isinstance(msg, dict):
        source = msg
    else:
        try:
            source = msg.model_dump()
        except Exception:
            source = {"role": getattr(msg, "role", "assistant"),
                      "content": getattr(msg, "content", "") or ""}
    message: dict = {"role": str(source.get("role") or "assistant"),
                     "content": "" if source.get("content") is None else str(source.get("content"))}
    tool_calls = source.get("tool_calls")
    if tool_calls:
        calls: list[dict] = []
        for call in tool_calls:
            if isinstance(call, dict):
                function = call.get("function") or {}
                call_id, call_type = call.get("id"), call.get("type")
            else:
                function = getattr(call, "function", None)
                call_id, call_type = getattr(call, "id", None), getattr(call, "type", None)
            if isinstance(function, dict):
                name, arguments = function.get("name"), function.get("arguments")
            else:
                name = getattr(function, "name", None)
                arguments = getattr(function, "arguments", None)
            calls.append({
                "id": str(call_id or ""),
                "type": str(call_type or "function"),
                "function": {"name": str(name or ""), "arguments": str(arguments or "")},
            })
        message["tool_calls"] = calls
    for key in ("tool_call_id", "reasoning_content"):
        value = source.get(key)
        if value:
            message[key] = str(value)
    return message


def json_to_message(raw) -> dict | None:
    """The inverse of :func:`message_to_json`; None for anything unusable.

    A stored conversation is data from an earlier run (possibly of an older plugin version), so
    every message is validated here instead of being trusted: an unknown role, a message that is
    not an object or a tool result without its ``tool_call_id`` would otherwise travel straight
    into the next request.
    """
    if not isinstance(raw, dict):
        return None
    if raw.get("role") not in ("system", "user", "assistant", "tool"):
        return None
    message = message_to_json(raw)
    if message.get("role") == "tool" and not message.get("tool_call_id"):
        return None
    return message


def _elapsed_line(label: str, seconds: float | None) -> str:
    """One elapsed line: the duration when a baseline exists, "unavailable" when it does not."""
    duration = "unavailable" if seconds is None else clock.format_duration(seconds)
    return "{}: {}.".format(label, duration)


def _time_reading(*, round_no: int, elapsed_read: float | None, elapsed_message: float | None,
                  moment: float | None = None) -> dict:
    """
    The time reading as a ``user`` message: when it is, in which zone, and how long ago the
    previous reading and the previous message were.

    Written at request time (never as a second system message, which strict chat templates
    reject) so that the system block itself never changes and stays a cacheable prefix. The zone
    is the machine's own (see ``core.clock``): a Minecraft server already runs in exactly one
    time zone -- the operator's -- so there is nothing to configure and nothing to guess.

    The four lines are **English written here, not translated strings**: this text is addressed to
    the model, not to a player. Sending it through ``rtr`` would tie the model's clock to the
    language the server happens to run in, and would hide a model-facing message in language files
    that are read for player text.

    ``elapsed_read`` and ``elapsed_message`` are None when there is no baseline to measure from
    (a brand-new conversation, the stateless ``!!ask -n`` path, a record written before these
    baselines existed): the reading says so instead of inventing a number.
    """
    at = clock.now() if moment is None else moment
    return {
        "role": "user",
        "content": "\n".join((
            "Time sampled before round {}: {}".format(round_no, clock.timestamp(at)),
            "Times without a zone are in the server's time zone ({}); ask if something does not "
            "fit.".format(clock.zone_label(at)),
            _elapsed_line("Elapsed since the previous time reading", elapsed_read),
            _elapsed_line("Elapsed since the previous message in this conversation",
                          elapsed_message),
        )),
    }


def _epoch_or_none(value) -> float | None:
    """A stored epoch, or None when it is missing, not a number, or in the future.

    The stored record can come from an older build (no such key), from a damaged file, or from a
    machine whose clock was wrong when it was written. A timestamp the plugin has not reached yet
    is treated as unknown rather than trusted: the elapsed lines are measured against it.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number > clock.now() + 60:
        return None
    return number


def _insert_before_last_user(messages: list, message: dict) -> bool:
    """
    Put ``message`` immediately in front of the newest ``user`` message — the question it
    belongs to. Returns False when the list holds no user message at all.
    """
    for index in range(len(messages) - 1, -1, -1):
        if _msg_role(messages[index]) == "user":
            messages.insert(index, message)
            return True
    return False


def _data_message(server: 'ServerInterface', data: list[tuple[str, str]]) -> dict:
    """The public database dump as an ``assistant`` message (reference material, not an order)."""
    return {
        "role": "assistant",
        "content": f'{str(server.rtr("games_ai.user_message.data_list"))}{data}',
    }


def _merge_adjacent_user_messages(messages: list) -> list:
    """
    Join directly adjacent ``user`` messages into one, for the outgoing request only.

    Two user messages in a row are legal but unwelcome: some providers require strict
    user/assistant alternation, and a model that receives "the player said A" and "the player
    said B" as two separate turns may answer only the last one. The plugin produces such pairs
    on purpose — the injected time, the injected "read this skill first" note, a question
    retried after a failed round, ``!!ask -f`` — and they are one turn for the model, so they
    leave as one message.

    The stored history is left untouched: this only shapes what is sent, so the history, the
    token estimates, ``_split_rounds`` and ``!!ask context`` keep describing exactly the
    messages that exist. The merge is deterministic, so the next request still starts with the
    same prefix and the provider cache keeps hitting.
    """
    merged: list = []
    for msg in messages:
        if merged and _msg_role(merged[-1]) == "user" and _msg_role(msg) == "user":
            previous = merged[-1]
            content = f"{_msg_content(previous)}\n\n{_msg_content(msg)}"
            previous = dict(previous) if isinstance(previous, dict) else {"role": "user"}
            previous["role"] = "user"
            previous["content"] = content
            merged[-1] = previous
            continue
        merged.append(msg)
    return merged


def _msg_text(msg) -> str:
    """All token-relevant text of a message (content + tool calls + reasoning + ids)."""
    parts: list[str] = []
    content = _msg_content(msg)
    if content:
        parts.append(content)

    tool_calls = msg.get("tool_calls") if isinstance(msg, dict) else getattr(msg, "tool_calls", None)
    if tool_calls:
        for tc in tool_calls:
            if isinstance(tc, dict):
                function = tc.get("function") or {}
                name = function.get("name", "")
                arguments = function.get("arguments", "")
                call_id = tc.get("id", "")
            else:
                function = getattr(tc, "function", None)
                name = getattr(function, "name", "")
                arguments = getattr(function, "arguments", "")
                call_id = getattr(tc, "id", "")
            parts.append(f"{name} {arguments} {call_id}")

    reasoning = msg.get("reasoning_content") if isinstance(msg, dict) else getattr(msg, "reasoning_content", None)
    if reasoning:
        # With `tools` present the provider folds reasoning_content back into the
        # context, so it is counted as well (usage calibration keeps this accurate).
        parts.append(str(reasoning))

    if isinstance(msg, dict):
        call_id = msg.get("tool_call_id")
        if call_id:
            parts.append(str(call_id))
    return "\n".join(parts)


# ── where a tool call runs ──────────────────────────────────────────────────
# The AI runs on the hub, but some tools describe the server the player is on: positions,
# online players and anything a custom tool does there. Such a call is handed to the instance
# the request came from, which runs it and answers with the result string.
#
# The router is installed by the plugin package on load (see ``__init__._install_tool_router``):
# this module cannot import its own package, because the package imports this module.

_remote_tool_router: Callable[[CommandSource, str, dict, str], str] | None = None


def set_remote_tool_router(router: Callable[[CommandSource, str, dict, str], str] | None) -> None:
    """Install the function that runs a tool call on the instance the request came from."""
    global _remote_tool_router
    _remote_tool_router = router


def describe_http_status(server: 'ServerInterface', status) -> str:
    """The localized meaning of one provider HTTP status, or "" when this build has none.

    The table lives here because this module owns the status codes, and both readers share it so
    the operator's log line and the player's reply can never describe the same code differently:
    :func:`_ai_error_detail` (which falls back to ``error_unknown``) and
    ``__init__._ask_error_reply`` (which simply omits the parenthesis when there is nothing to
    add).
    """
    if status is None:
        return ""
    try:
        key = _ERROR_CODE_KEYS.get(int(status))
    except (TypeError, ValueError):
        return ""
    if key is None:
        return ""
    try:
        return str(server.rtr(key, code=status))
    except Exception:
        return ""


def _log_failure(server: 'ServerInterface', tag: str, prefix_text: str, error: Exception) -> None:
    """One failed AI request, at a level the operator sees without ``!!gamesai debug``.

    The detail line (status code, its localized meaning, the provider's request id) used to go
    through ``ChatParam._log``, i.e. to DEBUG unless debug mode was on -- which hid exactly the
    part that says what to change. A failure is not a normal flow, so it is a WARNING and always
    visible. ``tag`` keeps the class name in front of the line, as the per-class loggers did.
    """
    try:
        server.logger.warning(f"[{tag}]{_ai_error_detail(prefix_text, error, server)}")
    except Exception:
        pass


def _ai_error_detail(prefix_text: str, error: Exception, server: 'ServerInterface') -> str:
    """One log line about a failed AI request: status code, localized text, provider request id.

    The player-facing sentence is not written here: ``ask_ai`` owns it (``_ask_error_reply``),
    because only the caller can tell a bad key from a rate limit. What stays here is the detail
    an operator needs, and its status description comes from :func:`describe_http_status` -- the
    very text the player's reply now carries as well.
    """
    status = getattr(error, "status_code", None)
    if status is None:
        return f"{prefix_text}: {error}"
    description = describe_http_status(server, status)
    if not description:
        try:
            description = str(server.rtr("games_ai.error_code_map.error_unknown", code=status))
        except Exception:
            description = "?"
    response = getattr(error, "response", None)
    request_id = getattr(response, "_request_id", None) if response is not None else None
    rid = f" [request ID: {request_id}]" if request_id else ""
    return f"{prefix_text}: [Code: {status}] {description}{rid}\n{error}"


def _uploaded_tools(source: CommandSource) -> list[dict] | None:
    """The schemas the asking instance uploaded, or None for a request made on this instance."""
    if isinstance(source, WebSocketCommandSource):
        return list(source.tools)
    return None


def _uploaded_tool_names(source: CommandSource) -> set[str]:
    """The tool names the asking instance said it can run on its own side."""
    names: set[str] = set()
    for schema in _uploaded_tools(source) or []:
        if not isinstance(schema, dict):
            continue
        function = schema.get("function")
        if isinstance(function, dict) and function.get("name"):
            names.add(str(function["name"]))
    return names


def _runs_on_origin(handler, source: CommandSource, func_name: str) -> bool:
    """True when this call has to be handed to the instance the request came from.

    A tool that is not hub-bound acts on the asking player's own server, so on a request that
    crossed the link it belongs there. A name this instance does not know at all goes over as
    well when the origin uploaded it: only that side can run it, and it answers with its own
    "this server does not provide tool X" when it cannot either.
    """
    if not isinstance(source, WebSocketCommandSource):
        return False
    if handler is None:
        return func_name in _uploaded_tool_names(source)
    return not handler.execute_in_hub


def dispatch_tool_call(handler, source: CommandSource, ai_prefix: str, func_name: str,
                       func_args: dict) -> tuple[str, bool]:
    """Run one tool call, here or on the instance it belongs to.

    The single place a tool is invoked, for every caller. Returns ``(result_text, ok)`` and
    never lets a routed failure escape: the model gets an honest string instead, and the AI
    round keeps going. A *local* tool that raises still propagates to the caller, which turns
    it into the usual ``Error while executing function ...`` result.

    Routing blocks until the origin answers. That is safe here and only here: this runs on the
    AI loop thread, which may wait -- a link thread must never do it (see
    ``__init__._on_cross_message``).
    """
    if _runs_on_origin(handler, source, func_name):
        router = _remote_tool_router
        if router is None:
            return (f"{func_name} belongs to {source.origin}, but this instance has no "
                    f"cross-server router to hand it over.", False)
        try:
            return str(router(source, func_name, func_args, ai_prefix)), True
        except Exception as e:
            return f"Failed to run {func_name} on {source.origin}: {e}", False
    return str(handler.func(source, ai_prefix, **func_args)), True


class BasicChatParam(ABC):
    """
    A abstract basic class about ChatParam Object.
    """

    allow_type = [
        'system',
        'user',
        'assistant',
        'tool'
    ]

    # Class-level default so a ChatParam-like test double built with ``__new__`` still supports
    # the history-version check of the compression (the first mutation writes the instance copy).
    _ctx_version: int = 0

    def __init__(
        self,
        server: 'ServerInterface',
        *,
        model_id: str | None = None,
    ):
        self.server = server
        self.model_id: str | None = model_id
        self.ai_info: dict = plugin_config.all_ai.get(self.model_id, {})
        self.openai_client: OpenAI | None = None
        self.response_list: list[dict] = []
        self.system_message: list[dict] = []

        self.response_queue: list[dict] = []

        self.tool_count: int = 0

        self.is_stopped = threading.Event()
        self.is_stopped.set()

        # context management state
        self._last_prompt_tokens: int = 0        # real input size of the last request
        self._round_max_total_tokens: int = 0    # max total_tokens of this round
        self._last_base_estimate: int = 0        # uncalibrated estimate of the last request
        self._last_estimate: int = 0             # calibrated estimate of the last request
        self._last_usage: dict | None = None     # raw usage of the last answered request
        self._last_compress: dict | None = None  # what the last compression did, and when
        self._round_prompt_tokens: int = 0       # prompt tokens charged in this round
        self._round_cached_tokens: int = 0       # of which served from the provider's cache
        self._round_reasoning_tokens: int = 0    # of which reasoning tokens

        # Lifetime accumulators: they are never reset, unlike `_round_*` (cleared for every
        # round) and `_last_*` (overwritten by every request). Compression rewrites the
        # history but these keep counting, which is what `!!ask context --all` reports as
        # "spent since this conversation was created" -- they are stored with the conversation
        # (see ``ChatParam.to_record``), so a restart does not reset them either.
        self._total_prompt_tokens: int = 0
        self._total_completion_tokens: int = 0
        self._total_cached_tokens: int = 0
        self._total_reasoning_tokens: int = 0

        # Guards `response_list`/`response_queue` and the state above, so that a command can
        # take a consistent snapshot while a round is running. Re-entrant because the helpers
        # it wraps (e.g. _split_rounds) are called from methods that already hold it.
        self._ctx_lock = threading.RLock()

        # Bumped by every mutation of `response_list`. The summarizer snapshots it, sends its
        # request *outside* the lock and replaces the history only when it is unchanged, so a
        # message appended during that request can never be lost (see _compress_old_rounds).
        self._ctx_version: int = 0

        # `!!ask stop` support: a running round compares its epoch snapshot with this
        # counter, so a stop request is never lost even if another round starts later.
        self._stop_epoch: int = 0
        self._round_epoch: int = 0
        self._stop_lock = threading.Lock()

        # pending model-switch hand-off (see change_model / _apply_pending_hand_off)
        self._pending_hand_off: dict | None = None

        # pending manual compaction (see compact_history / _apply_pending_compaction).
        # Set when a player asks for one, executed by the next preflight, so the command
        # itself never waits for the summarizing request.
        self._pending_compaction: bool = False

        # Rounds counted for the periodic time injection (see _inject_time): the first round
        # of a conversation always gets one, then every TIME_INJECT_INTERVAL rounds. It is
        # reset whenever the history is dropped for good (`!!gamesai clear` destroys the object,
        # `!!ask switch` clears the list); compression keeps counting, because the
        # conversation continues.
        self._rounds_since_time: int = 0

        # The other half of that rule, and what the reading's elapsed lines are measured from:
        # when the last reading was written, and when the last real message entered the history
        # (the reading itself is not a message and does not touch the second one). Both are
        # stored with the conversation, so a restart does not make them lie; None means "no
        # baseline", which the reading reports as unavailable.
        self._last_time_read: float | None = None
        self._last_message_at: float | None = None

    def _apply_pending_hand_off(self, source: CommandSource | None = None) -> None:
        """
        Summarize a conversation that was switched away, before the next request.

        This is the deferred half of the ``!!ask switch`` hand-off (option B1): like the
        normal context compression, the extra summarizing request is sent from the round
        that needs it instead of inside the command, so the switch itself never blocks.
        The previous model writes the summary; the old history was already cleared, so the
        result is injected as the first system message of the new conversation.
        """
        pending = self._pending_hand_off
        if pending is None:
            return
        self._pending_hand_off = None
        self._log(
            f"switch hand-off: summarizing {len(pending['messages'])} snapshot message(s) "
            f"with model={(pending.get('ai_info') or {}).get('ai_model', '')}"
        )

        summary = self._summary_request(
            self._transcript_lines(pending["messages"]),
            client=pending.get("client"),
            ai_info=pending.get("ai_info"),
        )
        if summary:
            prefix = str(self.server.rtr("games_ai.context.switch_summary_prefix"))
            with self._ctx_lock:
                self.response_list.insert(0, {"role": "system", "content": f"{prefix}\n{summary}"})
                self._ctx_version += 1
            self._log(
                f"switch hand-off applied: summary of {len(summary)} chars injected as the first "
                f"system message (history now {len(self.response_list)} message(s))"
            )
            return

        self._log("switch hand-off failed: previous conversation dropped")
        if source is not None:
            # the AI's own name prefix already identifies the model answering now
            ai_prefix = self.ai_info.get("ai_name", "")
            source.reply(f"{ai_prefix}{self.server.rtr('games_ai.user_message.switch_summary_failed')}")

    def _has_switch_summary(self) -> bool:
        """True when the history currently carries a model-switch hand-off summary."""
        prefix = str(self.server.rtr("games_ai.context.switch_summary_prefix"))
        return any(
            _msg_role(m) == "system" and (_msg_content(m) or "").startswith(prefix)
            for m in self.response_list
        )

    def _describe_history(self, preamble_count: int) -> str:
        """Compact description of the request that is about to be sent (debug logging)."""
        counts: dict[str, int] = {}
        for msg in self.response_list:
            role = _msg_role(msg) or "?"
            counts[role] = counts.get(role, 0) + 1
        return (
            f"preamble={preamble_count}, history={len(self.response_list)} {counts}, "
            f"hand-off summary={'yes' if self._has_switch_summary() else 'no'}"
        )

    def request_stop(self) -> bool:
        """
        Ask the running round of this conversation to abort (used by ``!!ask stop``).

        An in-flight HTTP request cannot be cancelled, so the round stops at its next
        checkpoint: before the next request, right after a response arrives, or between
        two tool calls of a batch.

        What the round already wrote **stays in the history** -- the question, the injected
        notes and every completed tool call keep their place, and queued ``!!ask -f``
        messages stay queued so the next round merges them as usual. The only thing that is
        dropped is a trailing assistant message whose tool calls never got their results
        (see :meth:`_drop_unanswered_tool_call`).

        :return: True when a round was actually running (and will abort).
        """
        with self._stop_lock:
            if self.is_stopped.is_set():
                return False
            self._stop_epoch += 1
            return True

    def begin_round(self) -> None:
        """Take the epoch snapshot a round compares against (see :meth:`stop_requested`)."""
        with self._stop_lock:
            self._round_epoch = self._stop_epoch

    def stop_requested(self) -> bool:
        """True when :meth:`request_stop` was called after the current round started."""
        with self._stop_lock:
            return self._round_epoch != self._stop_epoch

    def _drop_unanswered_tool_call(self) -> int:
        """
        Drop the one thing an interrupted round must not leave behind (``!!ask stop``).

        Everything the round already wrote stays in the history: the question it was
        answering, the injected notes (time, skill) and every tool call that came back with
        its results. Only a **trailing assistant message whose tool calls never got their
        results** is removed -- providers reject a ``tool_calls`` message without matching
        tool messages, and a half-finished call is not something the next question should
        inherit.

        :return: how many messages were dropped (0 or 1).
        """
        messages = self.response_list
        with self._ctx_lock:
            if messages and _msg_role(messages[-1]) == "assistant" and _msg_tool_calls(messages[-1]):
                del messages[-1:]
                self._ctx_version += 1
                self._log("stop: dropped the trailing tool call that never got its result")
                return 1
        return 0

    def _abort_interrupted_round(self) -> None:
        """Finish a round that ``!!ask stop`` interrupted (keep the history, validate, release).

        The round is not marked stopped here any more: this conversation owns its round through
        :meth:`ChatParam.try_claim_round` / :meth:`ChatParam.release_round`, and the queued
        questions of a merged conversation are sent afterwards (see ``ask_ai``).
        """
        dropped = self._drop_unanswered_tool_call()
        self._validate_sequence()
        self._log(
            f"response_ai aborted by stop: kept {len(self.response_list)} message(s) "
            f"({dropped} unfinished tool call dropped), queue={len(self.response_queue)}"
        )

    @property
    def get_response_list(self) -> list[dict]:
        return self.response_list

    @property
    def get_response_queue(self) -> list[dict]:
        return self.response_queue
    
    @property
    def get_openai_client(self) -> OpenAI | None:
        return self.openai_client

    @property
    def get_model_id(self) -> str | None:
        return self.model_id

    @property
    def get_is_stopped(self) -> bool:
        return self.is_stopped.is_set()

    @abstractmethod
    def build_openai_client(self) -> None:
        """
        Build a OpenAI client object
        """
        pass

    def build_system_message(self) -> list[dict]:
        """
        Prompt + the list of skills the model may load, joined into **one** system message.

        Two things are deliberate here:

        * a single message, because backends whose chat template accepts only one leading
          system message (Qwen3.5/3.6/3.8 and friends) reject a split block with
          ``System message must be at the beginning``;
        * the time is *not* part of it any more — it is injected at request time (see
          :meth:`ChatParam._inject_time`), so this block is byte-identical from round to
          round and stays a cacheable prefix for the provider.

        Stored in ``self.system_message`` and returned; every history-based parameter
        object starts its request with exactly this message.
        """
        prompt = str(self.ai_info.get("prompt", ""))

        skills = plugin_config.skills_description
        default_skills = [
            {"file": "skills_management.md", "description": str(self.server.rtr("games_ai.builtin_skills.skills_management"))},
            {"file": "custom_tools_management.md", "description": str(self.server.rtr("games_ai.builtin_skills.custom_tools_management"))},
            {"file": "mineflayer_bot_guide.md", "description": str(self.server.rtr("games_ai.builtin_skills.mineflayer_bot_guide", username=plugin_config.bot_username))},
        ]
        external_skills: list[dict[str, str]] = []
        if EXTERNAL_SKILLS_LIST:
            for i in EXTERNAL_SKILLS_LIST:
                file = i.get("file")
                description = i.get("description")
                if file is None or description is None:
                    continue
                external_skills.append({"file": file, "description": description})
        if external_skills:
            skills_file_list = str(self.server.rtr("games_ai.user_message.skills", skills=[*skills, *default_skills, *external_skills]))
        else:
            skills_file_list = str(self.server.rtr("games_ai.user_message.skills", skills=[*skills, *default_skills]))

        parts = [part for part in (prompt, skills_file_list) if part]
        self.system_message.clear()
        self.system_message.append({
            "role": "system",
            "content": "\n\n".join(parts),
        })

        return self.system_message

    @abstractmethod
    def add_to_response_list(self, type: str, content: str, *, args: dict | None = None) -> None:
        """
        Add a message to response queue
        """
        pass

    @abstractmethod
    def forced_add_to_response_list(self, type: str, content: str) -> None:
        """
        Forced add a message to response queue
        """
        pass

    @abstractmethod
    def tool_call(self, source: CommandSource, tool_calls: list[ChatCompletionMessageFunctionToolCall]) -> None:
        """
        Auto run tools.
        """
        pass

    @abstractmethod
    def response_ai(self, source: CommandSource, data: list[tuple[str, str]] | None = None) -> None:
        """
        Response AI loop

        ``data`` is the public database content to attach to the request; ``None`` (or an
        empty list) means the database holds nothing and no data message is sent.
        """
        pass

    @abstractmethod
    def change_model(self, source: CommandSource, model_id: str) -> None:
        """
        Change the model and re-build a OpenAI client object and re-build system message
        """
        pass

    # ── context management ──────────────────────────────────────────────

    def context_window(self) -> int:
        """Effective context window: config override -> table -> conservative default."""
        return self._window_for(self.ai_info)

    def context_window_source(self) -> str:
        """Where the effective window comes from: ``config``, ``table`` or ``default``."""
        return context_table.window_source(
            str(self.ai_info.get("ai_model", "")),
            self.ai_info.get("context_window"),
        )

    def _window_for(self, ai_info: dict) -> int:
        """Same resolution for an arbitrary AI entry (the switch hand-off uses the old one)."""
        return resolve_context_window(
            str(ai_info.get("ai_model", "")),
            ai_info.get("context_window"),
        )

    def context_snapshot(self) -> dict:
        """
        Read-only snapshot of everything ``!!ask context`` shows.

        Taken under :attr:`_ctx_lock` so it can never observe a half-rewritten history (the
        round thread appends messages and replaces the whole list when it compresses), and
        assembled only from plain values: the caller may format it however it likes without
        touching this object again.

        The per-round sizes are estimated with the same formula the window management uses,
        so the numbers here and in the debug log agree.
        """
        with self._ctx_lock:
            preamble, rounds = self._split_rounds()
            usage = dict(self._last_usage) if self._last_usage else None
            snapshot = {
                "model": str(self.ai_info.get("ai_model", "")),
                "model_label": str(self.ai_info.get("ai_name") or self.model_id or ""),
                "running": not self.is_stopped.is_set(),
                "window": self.context_window(),
                "window_source": self.context_window_source(),
                "max_output": resolve_max_output(str(self.ai_info.get("ai_model", ""))),
                "estimate": self._last_estimate,
                "base_estimate": self._last_base_estimate,
                "calibration": round(self._calibration_factor(), 3),
                "last_prompt": self._last_prompt_tokens,
                "round_max_total": self._round_max_total_tokens,
                "round_prompt": self._round_prompt_tokens,
                "round_cached": self._round_cached_tokens,
                "round_reasoning": self._round_reasoning_tokens,
                "last_usage": usage,
                "rounds": len(rounds),
                "messages": len(self.response_list),
                "roles": _role_counts(self.response_list),
                "summaries": sum(
                    1 for m in (preamble + [m for r in rounds for m in r])
                    if _msg_role(m) == "system"
                ),
                "hand_off": self._has_switch_summary(),
                "queued": len(self.response_queue),
                "last_compress": dict(self._last_compress) if self._last_compress else None,
                "round_tokens": [sum(
                    estimate_text_tokens(_msg_text(m)) + _MESSAGE_OVERHEAD for m in group
                ) for group in rounds],
            }
        return snapshot

    def context_usage(self) -> dict:
        """
        The handful of numbers ``!!ask context --all`` sums up per model.

        Separate from :meth:`context_snapshot` because the server-wide view only needs a few
        values per player and must stay cheap: it reads them for every object in
        ``all_chat_param``, and it must not pay for the per-round estimates that only the
        single-player card shows.

        :return: ``window`` (the effective window of the player's model, for the share in the
                 server-wide view), ``estimate`` (the context the player is currently holding;
                 it drops when the history is compressed), and the round/lifetime counters
                 (which keep growing across compressions, so the spent total is never lost).
        """
        with self._ctx_lock:
            return {
                # the configured AI entry (the ``all_ai`` key) and the upstream model are kept
                # apart: two entries may use the same upstream model, and the server-wide view
                # groups by the entry while showing the upstream model on the hover
                "model_id": str(self.model_id or ""),
                "model": str(self.ai_info.get("ai_model", "")),
                "label": str(self.ai_info.get("ai_name") or self.model_id or ""),
                "window": int(self.context_window()),
                "estimate": int(self._last_estimate),
                "messages": len(self.response_list),
                "rounds": len(self._split_rounds_locked()[1]),
                "round_prompt": int(self._round_prompt_tokens),
                "round_max_total": int(self._round_max_total_tokens),
                "total_prompt": int(self._total_prompt_tokens),
                "total_completion": int(self._total_completion_tokens),
                "total_cached": int(self._total_cached_tokens),
                "total_reasoning": int(self._total_reasoning_tokens),
            }

    def refresh_context_estimate(self) -> None:
        """Recompute the held-context estimate from the state this object currently has.

        Used after a stored conversation was restored: the record knows the messages but not the
        numbers of the request that produced them, and the next round only happens when the player
        asks again -- until then ``!!ask context`` would claim there was never a request. The
        system prompt is rebuilt here and the history is summed with the very formula
        :meth:`_estimate_request_tokens` uses, then the calibration factor is applied.

        Tool schemas are assembled by the round and are not known here, so this is a floor: the
        next request replaces the number with its own full estimate.
        """
        if not self.system_message:
            self.build_system_message()
        with self._ctx_lock:
            total = 0
            for message in self.system_message:
                total += estimate_text_tokens(_msg_content(message)) + _MESSAGE_OVERHEAD
            for message in self.response_list:
                total += estimate_text_tokens(_msg_text(message)) + _MESSAGE_OVERHEAD
            self._last_base_estimate = int(total)
            self._last_estimate = int(total * self._calibration_factor())

    def context_stats(self) -> dict:
        preamble, rounds = self._split_rounds()
        return {
            "window": self.context_window(),
            "max_output": resolve_max_output(str(self.ai_info.get("ai_model", ""))),
            "last_prompt_tokens": self._last_prompt_tokens,
            "round_max_total_tokens": self._round_max_total_tokens,
            "base_estimate": self._last_base_estimate,
            "estimate": self._last_estimate,
            "calibration": round(self._calibration_factor(), 3),
            "rounds": len(rounds),
            "messages": len(self.response_list),
        }

    def _calibration_factor(self) -> float:
        key = _calibration_key(str(self.ai_info.get("base_url", "")), str(self.ai_info.get("ai_model", "")))
        with _calibration_lock:
            return _calibration_store.get(key, 1.0)

    def _update_calibration(self, base_estimate: int, real_prompt_tokens: int) -> None:
        """EMA-adjust the calibration factor so that base_estimate * factor ~= real."""
        if base_estimate <= 0 or real_prompt_tokens <= 0:
            return
        target = min(max(real_prompt_tokens / base_estimate, CALIBRATION_MIN), CALIBRATION_MAX)
        key = _calibration_key(str(self.ai_info.get("base_url", "")), str(self.ai_info.get("ai_model", "")))
        with _calibration_lock:
            old = _calibration_store.get(key)
            value = target if old is None else (1 - CALIBRATION_ALPHA) * old + CALIBRATION_ALPHA * target
            _calibration_store[key] = min(max(value, CALIBRATION_MIN), CALIBRATION_MAX)
        self._log(
            f"calibration updated: {key} -> {_calibration_store[key]:.3f} "
            f"(base_estimate={base_estimate}, real={real_prompt_tokens}, target={target:.3f})"
        )

    def _record_usage(self, usage: dict | None) -> None:
        """
        Remember what the provider charged for one request.

        The raw dict is kept as well (not just the three ints), because it carries the cache
        and reasoning counters that ``!!ask context`` shows, and because a provider that
        answers without usage must not leave the previous request's numbers on display.
        """
        if not usage:
            self._last_usage = None
            return
        try:
            prompt = int(usage.get("prompt_tokens") or 0)
            completion = int(usage.get("completion_tokens") or 0)
            total = int(usage.get("total_tokens") or (prompt + completion))
        except (TypeError, ValueError):
            self._last_usage = None
            return
        with self._ctx_lock:
            self._last_usage = dict(usage)
            if prompt > 0:
                self._last_prompt_tokens = prompt
                cached = _int_at(usage, "prompt_tokens_details", "cached_tokens")
                reasoning = _int_at(usage, "completion_tokens_details", "reasoning_tokens")
                self._round_prompt_tokens += prompt
                self._round_cached_tokens += cached
                self._round_reasoning_tokens += reasoning
                # lifetime totals: survive every round boundary and every compression
                self._total_prompt_tokens += prompt
                self._total_completion_tokens += completion
                self._total_cached_tokens += cached
                self._total_reasoning_tokens += reasoning
                self._update_calibration(self._last_base_estimate, prompt)
            if total > self._round_max_total_tokens:
                self._round_max_total_tokens = total
        self._log(
            f"usage: prompt={prompt}, completion={completion}, total={total}, "
            f"round_max_total={self._round_max_total_tokens}, window={self.context_window()}, "
            f"calibration={self._calibration_factor():.3f}"
        )

    def _estimate_request_tokens(self, system: list[dict], tools: list[dict] | None) -> int:
        total = 0
        for msg in system:
            total += estimate_text_tokens(_msg_content(msg)) + _MESSAGE_OVERHEAD
        for msg in self.response_list:
            total += estimate_text_tokens(_msg_text(msg)) + _MESSAGE_OVERHEAD
        if tools:
            try:
                total += estimate_text_tokens(json.dumps(tools, ensure_ascii=False)) + TOOLS_FIXED_OVERHEAD
            except (TypeError, ValueError):
                total += TOOLS_FIXED_OVERHEAD
        self._last_base_estimate = total
        return int(total * self._calibration_factor())

    def _split_rounds(self) -> tuple[list, list[list]]:
        """
        Split the history into rounds (one user message plus its assistant/tool follow-ups)
        and a preamble of leading system messages.

        Runs under :attr:`_ctx_lock`: a command thread takes its snapshot through this, while
        the round thread may be appending to or replacing the very same list.
        """
        with self._ctx_lock:
            return self._split_rounds_locked()

    def _split_rounds_locked(self) -> tuple[list, list[list]]:
        pending: list = []
        rounds: list[list] = []
        for msg in self.response_list:
            role = _msg_role(msg)
            if role == "system":
                pending.append(msg)
                continue
            if role == "user":
                # Two consecutive user messages are one turn: the injected time message sits
                # right in front of the question it belongs to (an unanswered question
                # followed by a new one is one turn as well). Without this, every injected
                # time would count as a round of its own and KEEP_ROUNDS would keep half of
                # the real conversation.
                if rounds and not pending and _msg_role(rounds[-1][-1]) == "user":
                    rounds[-1].append(msg)
                else:
                    rounds.append(pending + [msg])
                    pending = []
                continue
            # assistant / tool / anything else
            if rounds:
                if pending:
                    rounds[-1].extend(pending)
                    pending = []
                rounds[-1].append(msg)
            else:
                rounds.append(pending + [msg])
                pending = []
        preamble: list = []
        if pending:
            if rounds:
                rounds[-1].extend(pending)
            else:
                preamble = pending
        return preamble, rounds

    def _drop_oldest_round(self) -> bool:
        """Drop the oldest round (split + edit + replace must be atomic against a snapshot)."""
        with self._ctx_lock:
            return self._drop_oldest_round_locked()

    def _drop_oldest_round_locked(self) -> bool:
        preamble, rounds = self._split_rounds_locked()
        if len(rounds) <= 1:
            return False
        removed = rounds[0]
        rest: list = []
        for group in rounds[1:]:
            rest.extend(group)
        self.response_list = list(preamble) + rest
        self._log(f"dropped oldest round ({len(removed)} message(s))")
        return True

    def _truncate_long_messages(self, cap_tokens: int) -> bool:
        """Shrink oversized messages (split + edit + replace, atomic against a snapshot)."""
        with self._ctx_lock:
            return self._truncate_long_messages_locked(cap_tokens)

    def _truncate_long_messages_locked(self, cap_tokens: int) -> bool:
        changed = False
        new_list: list = []
        for msg in self.response_list:
            if isinstance(msg, dict) and _msg_role(msg) in ("tool", "user", "system"):
                content = msg.get("content")
                if isinstance(content, str) and estimate_text_tokens(content) > cap_tokens:
                    kept = _shrink_text(content, cap_tokens)
                    note = str(self.server.rtr("games_ai.context.truncated", orig=len(content), kept=len(kept)))
                    new_msg = dict(msg)
                    new_msg["content"] = f"{kept}\n{note}"
                    new_list.append(new_msg)
                    changed = True
                    continue
            new_list.append(msg)
        if changed:
            self.response_list = new_list
            self._log(f"truncated oversized message(s) to <= {cap_tokens} tokens")
        return changed

    def _emergency_reduce(self, system: list[dict], tools: list[dict] | None, target_ratio: float) -> None:
        """Guarantee the next request fits: truncate huge messages, then drop rounds."""
        window = self.context_window()
        target = int(window * target_ratio)
        if self._estimate_request_tokens(system, tools) <= target:
            return
        cap = min(int(window * MESSAGE_TOKEN_CAP_RATIO), MESSAGE_TOKEN_CAP_ABS)
        cap = max(cap, 1024)
        self._truncate_long_messages(cap)
        while self._estimate_request_tokens(system, tools) > target:
            if not self._drop_oldest_round():
                break
        self._log(
            f"emergency reduce done: estimate={self._estimate_request_tokens(system, tools)}, "
            f"target={target}, stats={self.context_stats()}"
        )

    @staticmethod
    def _transcript_lines(messages) -> list[str]:
        """``Role: text`` lines of a message collection; tool results are skipped as bulky."""
        parts: list[str] = []
        for msg in messages:
            role = _msg_role(msg)
            if role == "tool":
                continue
            text = _msg_content(msg)
            if not text:
                continue
            label = {"user": "User", "assistant": "Assistant", "system": "System"}.get(role, str(role))
            parts.append(f"{label}: {text}")
        return parts

    def _summary_request(self, parts: list[str], *, client: OpenAI | None = None,
                         ai_info: dict | None = None) -> str | None:
        """
        One neutral factual summary request (no tools).

        ``client``/``ai_info`` default to the current model; the model-switch hand-off
        passes the *previous* ones so that the old model writes its own summary.
        """
        client = client if client is not None else self.openai_client
        ai_info = ai_info if ai_info is not None else self.ai_info
        if client is None or not parts:
            return None
        window = self._window_for(ai_info)
        parts = self._limit_summary_input(parts, window)
        prompt = str(self.server.rtr("games_ai.context.summary_prompt"))
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "\n".join(parts)},
        ]
        self._log(
            f"summarize request -> model={ai_info.get('ai_model', '')}, "
            f"input={len(messages[1]['content'])} chars (window {window})"
        )
        try:
            reply, _usage = response_chat(
                client,
                model=ai_info.get("ai_model", ""),
                response_list=messages,
                tools=None,
                extra_body=ai_info.get("extra_body", {}),
                timeout=SUMMARY_TIMEOUT,
            )
        except Exception as e:
            self._log(f"summarize failed: {e}")
            return None
        content = getattr(reply, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
        return None

    def _summarize(self, rounds: list[list], existing_summaries: list) -> str | None:
        """Compress old rounds into a neutral factual summary (no tools, content only)."""
        parts: list[str] = []
        for msg in existing_summaries:
            text = _msg_content(msg)
            if text:
                parts.append(f"[existing summary] {text}")
        for group in rounds:
            parts.extend(self._transcript_lines(group))
        return self._summary_request(parts)

    def _limit_summary_input(self, parts: list[str], window: int) -> list[str]:
        """Keep the newest part of the summarization input within its own budget."""
        cap = max(int(window * SUMMARY_INPUT_RATIO), 1024)
        kept: list[str] = []
        total = 0
        for part in reversed(parts):
            tokens = estimate_text_tokens(part)
            if kept and total + tokens > cap:
                break
            kept.append(part)
            total += tokens
        kept.reverse()
        if kept and estimate_text_tokens(kept[-1]) > cap:
            kept[-1] = _shrink_text(kept[-1], cap) + "\n..."
        return kept

    def _compress_old_rounds(self) -> bool:
        """
        Replace all but the newest KEEP_ROUNDS rounds with one summary system message.

        A history that holds no more than KEEP_ROUNDS rounds is left alone: the rounds a
        compression keeps verbatim are the only ones it has, so there is nothing older to
        replace and no summarizing request is spent on it. The manual ``!!ask compact``
        reports that as "no history to compact" instead of scheduling the work.

        The summarizing request is a network call that may take up to
        :data:`SUMMARY_TIMEOUT` seconds, so it runs **outside** :attr:`_ctx_lock`: holding the
        lock across it made a read-only command (``!!ask context``) block the MCDR command
        thread for that long. The history is snapshotted under the lock, summarized without
        it, and replaced only when :attr:`_ctx_version` is unchanged -- otherwise a message
        appended by another thread during the request would be lost, so the replacement is
        skipped and the next preflight retries.
        """
        with self._ctx_lock:
            preamble, rounds = self._split_rounds_locked()
            if len(rounds) <= KEEP_ROUNDS:
                self._log(f"compress skipped: {len(rounds)} round(s) <= KEEP_ROUNDS({KEEP_ROUNDS})")
                return False
            old_rounds = rounds[:-KEEP_ROUNDS]
            keep_rounds = rounds[-KEEP_ROUNDS:]
            existing_summaries = [m for group in old_rounds for m in group if _msg_role(m) == "system"]
            version = self._ctx_version

        summary = self._summarize(old_rounds, existing_summaries)

        with self._ctx_lock:
            if self._ctx_version != version:
                self._log("compression skipped: the history changed while the summary was requested")
                return False
            new_list: list = list(preamble)
            if summary:
                prefix = str(self.server.rtr("games_ai.context.summary_prefix"))
                new_list.append({"role": "system", "content": f"{prefix}\n{summary}"})
            for group in keep_rounds:
                new_list.extend(group)

            before, after = len(self.response_list), len(new_list)
            self.response_list = new_list
            self._ctx_version += 1
            self._last_compress = {
                "time": datetime.datetime.now().strftime("%H:%M:%S"),
                "rounds": len(old_rounds),
                "before": before,
                "after": after,
                "ok": bool(summary),
            }
            self._log(
                f"compressed {len(old_rounds)} old round(s): messages {before} -> {after}, "
                f"summary={'ok' if summary else 'failed(dropped)'}, est={self._last_estimate}, "
                f"window={self.context_window()}"
            )
        return True

    def _compress_old_rounds_locked(self) -> bool:
        """Compatibility name: the compression no longer runs under the lock (see above)."""
        return self._compress_old_rounds()

    def _validate_sequence(self) -> None:
        """Drop orphan tool messages / broken tool-call groups before sending."""
        try:
            cleaned: list = []
            index = 0
            messages = self.response_list
            while index < len(messages):
                msg = messages[index]
                role = _msg_role(msg)
                if role == "assistant":
                    tool_calls = msg.get("tool_calls") if isinstance(msg, dict) else getattr(msg, "tool_calls", None)
                    if tool_calls:
                        expected = set()
                        for tc in tool_calls:
                            call_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                            if call_id:
                                expected.add(call_id)
                        following: list = []
                        cursor = index + 1
                        while cursor < len(messages) and _msg_role(messages[cursor]) == "tool":
                            call_id = messages[cursor].get("tool_call_id") if isinstance(messages[cursor], dict) else getattr(messages[cursor], "tool_call_id", None)
                            following.append((call_id, messages[cursor]))
                            cursor += 1
                        present = {call_id for call_id, _ in following if call_id}
                        if expected - present:
                            self._log(f"validate: dropped assistant with unanswered tool_calls {sorted(expected - present)}")
                            index = cursor
                            continue
                        cleaned.append(msg)
                        for _, tool_msg in following:
                            cleaned.append(tool_msg)
                        index = cursor
                        continue
                if role == "tool":
                    call_id = msg.get("tool_call_id") if isinstance(msg, dict) else getattr(msg, "tool_call_id", None)
                    known = set()
                    for prev in cleaned:
                        if _msg_role(prev) == "assistant":
                            prev_calls = prev.get("tool_calls") if isinstance(prev, dict) else getattr(prev, "tool_calls", None)
                            for tc in prev_calls or []:
                                value = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                                if value:
                                    known.add(value)
                    if call_id and call_id in known:
                        cleaned.append(msg)
                    else:
                        self._log(f"validate: dropped orphan tool message (tool_call_id={call_id})")
                    index += 1
                    continue
                cleaned.append(msg)
                index += 1
            if len(cleaned) != len(self.response_list):
                with self._ctx_lock:
                    self.response_list = cleaned
                    self._ctx_version += 1
        except Exception as e:
            self._log(f"validate_sequence error: {e}")

    def manage_context(self, system: list[dict], tools: list[dict] | None, *, preflight: bool = False,
                       source: CommandSource | None = None) -> None:
        """
        Keep the request within the model window.

        Called before every request (``preflight=True``) and after every request
        (post-round). Compression keeps the newest KEEP_ROUNDS rounds verbatim and
        replaces older rounds with a neutral summary; if that is not enough, giant
        messages are truncated and the oldest rounds are dropped. A pending model-switch
        hand-off is applied here as well, i.e. right before the next request.
        """
        try:
            if preflight:
                self._apply_pending_hand_off(source)
                self._apply_pending_compaction()
            window = self.context_window()
            if window <= 0:
                return
            estimate = self._estimate_request_tokens(system, tools)
            self._last_estimate = estimate

            if preflight:
                if estimate >= EMERGENCY_RATIO * window:
                    self._log(f"preflight emergency: estimate={estimate} >= {EMERGENCY_RATIO:.0%} of window {window}")
                    self._emergency_reduce(system, tools, EMERGENCY_TARGET_RATIO)
                elif estimate >= TRIGGER_HISTORY_RATIO * window:
                    self._log(f"preflight compress: estimate={estimate} >= {TRIGGER_HISTORY_RATIO:.0%} of window {window}")
                    self._compress_old_rounds()
                    self._emergency_reduce(system, tools, EMERGENCY_TARGET_RATIO)
                return

            trigger = None
            if self._round_max_total_tokens and self._round_max_total_tokens >= TRIGGER_REQUEST_RATIO * window:
                trigger = f"burst({self._round_max_total_tokens} >= {TRIGGER_REQUEST_RATIO:.0%})"
            elif self._last_prompt_tokens and self._last_prompt_tokens >= TRIGGER_HISTORY_RATIO * window:
                trigger = f"history({self._last_prompt_tokens} >= {TRIGGER_HISTORY_RATIO:.0%})"
            if trigger:
                self._log(f"context trigger {trigger} of window {window}, compressing")
                self._compress_old_rounds()
                self._emergency_reduce(system, tools, EMERGENCY_TARGET_RATIO)
        except Exception as e:
            self._log(f"manage_context error: {e}")

    def wait_until_stop(self) -> None:
        """
        Wait this round stop
        """
        self.is_stopped.wait()

    def _log(self, msg: str) -> None:
        """Bookkeeping line: visible once ``!!gamesai debug`` is on (see logger.verbose)."""
        logger.verbose(self.server, msg, tag="ChatParam")

    def context_view(self) -> list[tuple[str, str]]:
        """
        Render :meth:`context_snapshot` as ``(line, hover)`` pairs for ``!!ask context``.

        Kept next to the state it describes (and not in the command layer) so the thresholds
        shown here are the very constants the window management uses; the text comes from
        ``self.server.rtr``, like everywhere else in this class.

        The produced text is deliberately short — the chat box only gets a few lines — while
        the hover carries the details that would not fit, such as the per-round sizes.
        """
        snap = self.context_snapshot()
        window = max(int(snap.get("window") or 0), 1)

        def fmt(value) -> str:
            try:
                return f"{int(value):,}"
            except (TypeError, ValueError):
                return str(value)

        def cache_rate(cached, total) -> str:
            """
            Cache hit share as a percentage with 0.1% resolution.

            Truncated rather than rounded, so the displayed rate is never higher than the real
            one. The share is capped at 100%: some providers report a cached count that also
            counts tokens of an earlier attempt, and a rate above 100% would only be noise.
            """
            if not total or total <= 0:
                return "—"
            return f"{math.floor(1000 * min(cached, total) / total) / 10:.1f}%"

        def ratio_line(used: int, key: str) -> str:
            return str(self.server.rtr(key, used=fmt(used), window=fmt(snap["window"]),
                                       percent=round(100 * used / window)))

        source = str(self.server.rtr(f"games_ai.context_view.source_{snap.get('window_source', 'default')}"))
        title = str(self.server.rtr("games_ai.context_view.card_title",
                                    model=snap.get("model_label") or snap.get("model"),
                                    window=fmt(snap["window"]), source=source))

        estimated = bool(snap.get("estimate"))
        if estimated:
            usage_line = ratio_line(int(snap["estimate"]), "games_ai.context_view.card_usage_est")
        else:
            usage_line = str(self.server.rtr("games_ai.context_view.card_usage_none"))
        # the last request's cache hit share rides along on the header line: it is the number
        # people actually want to see at a glance, and it needs no hover to read
        last = snap.get("last_usage") or {}
        if last:
            usage_line = f"{usage_line}  {self.server.rtr('games_ai.context_view.card_cache')} " \
                         f"{cache_rate(_int_at(last, 'prompt_tokens_details', 'cached_tokens'), last.get('prompt_tokens') or 0)}"
        if snap.get("running"):
            usage_line = f"{usage_line}  {self.server.rtr('games_ai.context_view.card_running')}"

        output_note = str(self.server.rtr("games_ai.context_view.output_note"))
        emergency_line = int(EMERGENCY_RATIO * window)
        history_line = int(TRIGGER_HISTORY_RATIO * window)
        burst_line = int(TRIGGER_REQUEST_RATIO * window)
        used_real = int(snap.get("last_prompt") or 0)
        used_burst = int(snap.get("round_max_total") or 0)

        if estimated and int(snap["estimate"]) >= emergency_line:
            remaining = str(self.server.rtr("games_ai.context_view.card_at_emergency", limit=fmt(emergency_line)))
        elif used_burst >= burst_line:
            remaining = str(self.server.rtr(
                "games_ai.context_view.card_remaining",
                remaining=fmt(max(0, burst_line - used_burst)),
                trigger=str(self.server.rtr("games_ai.context_view.trigger_burst",
                                            used=fmt(used_burst), threshold=fmt(burst_line))),
                output_note=output_note))
        elif used_real >= history_line:
            remaining = str(self.server.rtr(
                "games_ai.context_view.card_remaining",
                remaining=fmt(max(0, history_line - used_real)),
                trigger=str(self.server.rtr("games_ai.context_view.trigger_history",
                                            used=fmt(used_real), threshold=fmt(history_line))),
                output_note=output_note))
        elif used_real or estimated:
            used = max(used_real, int(snap.get("estimate") or 0))
            remaining = str(self.server.rtr(
                "games_ai.context_view.card_remaining",
                remaining=fmt(max(0, history_line - used)), trigger="",
                output_note=output_note))
        else:
            remaining = str(self.server.rtr(
                "games_ai.context_view.card_no_request",
                threshold=fmt(history_line), output_note=output_note))

        scale = str(self.server.rtr(
            "games_ai.context_view.card_scale", rounds=snap.get("rounds", 0),
            messages=snap.get("messages", 0), summaries=snap.get("summaries", 0),
            hand_off=str(self.server.rtr("games_ai.context_view.yes" if snap.get("hand_off")
                                         else "games_ai.context_view.no"))))
        if snap.get("queued"):
            scale = f"{scale}  {self.server.rtr('games_ai.context_view.card_queue', queued=snap['queued'])}"

        # hover: thresholds, per-round sizes, last-request usage, last compression
        hover_trigger = str(self.server.rtr(
            "games_ai.context_view.hover_trigger",
            history=fmt(history_line), burst=fmt(burst_line), emergency=fmt(emergency_line)))
        round_tokens = list(snap.get("round_tokens") or [])
        rounds_text: list[str] = []
        if round_tokens:
            shown = round_tokens[-10:]
            for offset, size in enumerate(shown):
                rounds_text.append(f"#{len(round_tokens) - len(shown) + offset + 1}  {fmt(size)}"
                                   f"  ({round(100 * size / window)}%)")
            if len(round_tokens) > len(shown):
                rounds_text.insert(0, f"... +{len(round_tokens) - len(shown)}")
        hover_rounds = str(self.server.rtr(
            "games_ai.context_view.hover_rounds", rounds="\n".join(rounds_text) or "-"))
        usage = snap.get("last_usage") or {}
        if usage:
            hover_usage = str(self.server.rtr(
                "games_ai.context_view.hover_usage",
                prompt=fmt(usage.get("prompt_tokens") or 0),
                completion=fmt(usage.get("completion_tokens") or 0),
                total=fmt(usage.get("total_tokens") or 0),
                cached=fmt(_int_at(usage, "prompt_tokens_details", "cached_tokens")),
                cached_percent=cache_rate(_int_at(usage, "prompt_tokens_details", "cached_tokens"),
                                          usage.get("prompt_tokens") or 0),
                reasoning=fmt(_int_at(usage, "completion_tokens_details", "reasoning_tokens")),
                round_prompt=fmt(snap.get("round_prompt") or 0),
                round_cached=fmt(snap.get("round_cached") or 0),
                round_cached_percent=cache_rate(snap.get("round_cached") or 0,
                                                snap.get("round_prompt") or 0),
                round_reasoning=fmt(snap.get("round_reasoning") or 0),
            ))
        else:
            hover_usage = str(self.server.rtr("games_ai.context_view.hover_usage_none"))
        compress = snap.get("last_compress")
        if compress:
            hover_compress = str(self.server.rtr(
                "games_ai.context_view.hover_compress", time=compress.get("time", "?"),
                rounds=compress.get("rounds", 0), before=compress.get("before", 0),
                after=compress.get("after", 0),
                status=str(self.server.rtr("games_ai.context_view.hover_compress_ok" if compress.get("ok")
                              else "games_ai.context_view.hover_compress_fail")),
            ))
        else:
            hover_compress = str(self.server.rtr("games_ai.context_view.hover_compress_none"))
        hover_scale = "\n".join([hover_trigger, hover_rounds, hover_usage, hover_compress])

        return [
            (title, f"{snap.get('model')}\n{snap.get('messages', 0)} message(s)"),
            (usage_line, hover_usage),
            (str(self.server.rtr(
                "games_ai.context_view.card_window", window=fmt(snap["window"]),
                max_output=fmt(snap.get("max_output") or 0))), hover_trigger),
            (remaining, hover_trigger),
            (scale, hover_scale),
        ]

    def reload_ai_info(self) -> bool:
        """Re-read this conversation's model from the config (hot reload).

        A model the config no longer has (removed or renamed while the conversation is live)
        must not abort the reload: the warning is logged and the previous client/info are kept,
        so the conversation keeps answering until the player switches or the config gains the
        model again. The reload itself continues (see ``_reload_body``).

        :return: True when the conversation now uses a configured model, False when the
                 previous one was kept.
        """
        new_info = plugin_config.all_ai.get(self.model_id, {})
        if not new_info:
            logger.log("warning",
                       f"{plugin_config.prefix} Conversation of {self.model_id!r} keeps its previous "
                       f"model: it is no longer configured", self.server)
            return False
        old_info = self.ai_info
        self.ai_info = new_info
        try:
            self.build_openai_client()
            self.build_system_message()
        except Exception:
            self.ai_info = old_info
            raise
        return True

    # ── manual compaction (``!!ask compact``) ───────────────────────────

    def is_running(self) -> bool:
        """True while a round of this conversation is in flight (for messages/commands)."""
        return not self.is_stopped.is_set()

    def try_claim_round(self) -> bool:
        """Atomically take this conversation's round ownership.

        :return: True when the caller now owns the round and must call :meth:`release_round`
                 (or :meth:`finish_round_or_take_next` when it runs a merged sequence).
        """
        self._ensure_round_state()
        with self._round_lock:
            if self._round_active:
                return False
            self._round_active = True
            self.is_stopped.clear()
            self.begin_round()
            return True

    def queue_pending_ask(self, source: CommandSource, message: str) -> None:
        """Queue one question asked while another round owns this conversation.

        The owner thread drains the queue when its round ends and sends the questions in
        arrival order as one merged round (see ``ask_ai``).
        """
        self._ensure_round_state()
        with self._round_lock:
            self._pending_asks.append((source, message))

    def finish_round_or_take_next(self) -> tuple[list[tuple[CommandSource, str]], bool] | None:
        """Finish the current round of an owned sequence, or start its next merged round.

        :return: ``(batch, True)`` while the owner must run another round; ``None`` when the
                 sequence is finished and the round ownership has been released.
        """
        self._ensure_round_state()
        with self._round_lock:
            if self._pending_asks:
                batch = self._pending_asks
                self._pending_asks = []
                self.is_stopped.clear()
                self.begin_round()
                return batch, True
            if self.response_queue:
                # Only `!!ask -f`/relayed leftovers: the next round's response_ai merges them.
                self.is_stopped.clear()
                self.begin_round()
                return [], True
            self._round_active = False
            self.is_stopped.set()
            return None

    def release_round(self) -> None:
        """Release this conversation's round ownership (idempotent safety net)."""
        self._ensure_round_state()
        with self._round_lock:
            self._round_active = False
            self.is_stopped.set()

    def is_round_active(self) -> bool:
        """True while some thread owns this conversation's round (or merged sequence)."""
        self._ensure_round_state()
        with self._round_lock:
            return self._round_active

    def _ensure_round_state(self) -> None:
        """Create the ownership/stop state on objects built without ``__init__`` (test doubles)."""
        if "_round_lock" not in self.__dict__:
            self._round_lock = threading.Lock()
            self._round_active = False
            self._pending_asks = []
        if "_stop_lock" not in self.__dict__:
            self._stop_lock = threading.Lock()
            self._stop_epoch = 0
            self._round_epoch = 0
        if "is_stopped" not in self.__dict__:
            self.is_stopped = threading.Event()
            self.is_stopped.set()

    def compact_history(self) -> str:
        """
        Summarize the older rounds and keep only the newest ``KEEP_ROUNDS`` verbatim.

        This is the manual counterpart of the automatic compression in
        :meth:`manage_context`, and it uses the very same summarizing request and
        replacement rule -- the only difference is that it ignores the window triggers, so
        a player can decide to compact now instead of waiting for the 80% line. A history
        that holds no more than ``KEEP_ROUNDS`` rounds has nothing older to replace, so it
        answers ``"empty"`` and no summarizing request is spent.

        Like the model-switch hand-off, the summarizing request is **deferred** to the next
        preflight: sending it here would block the command thread (and therefore the server
        thread) for up to :data:`SUMMARY_TIMEOUT` seconds, while the round that needs the
        smaller context is the one that should pay for it. That is also why the caller is
        told ``"scheduled"`` rather than ``"done"``.

        The round is claimed for the short inspection below, so the scheduling cannot race a
        round that just started.

        :return: ``"scheduled"`` (deferred, applied before the next request),
                 ``"empty"`` (nothing older than the kept rounds, so nothing to compact),
                 or ``"running"`` (a round is in flight; retry, or ``!!ask stop`` first)
        """
        if not self.try_claim_round():
            self._log("compact rejected: a round is in flight")
            return "running"
        try:
            rounds = self._split_rounds()[1]
            if not rounds:
                self._log("compact rejected: the history holds no round yet")
                return "empty"
            if len(rounds) <= KEEP_ROUNDS:
                # The newest KEEP_ROUNDS rounds are kept verbatim, so a forced compaction could
                # only throw away rounds the ordinary rule keeps.
                self._log(f"compact rejected: all {len(rounds)} round(s) are within KEEP_ROUNDS({KEEP_ROUNDS})")
                return "empty"
            self._pending_compaction = True
            self._log(
                f"compact scheduled by the player: {len(self.response_list)} message(s) now, "
                f"applied right before the next request"
            )
            return "scheduled"
        finally:
            self.release_round()

    def _apply_pending_compaction(self) -> None:
        """
        Run a manual compaction that was requested earlier (deferred half of
        :meth:`compact_history`). Called from the preflight, so the forced compression is
        then handled by the ordinary flow of that same preflight.
        """
        if not self._pending_compaction:
            return
        self._pending_compaction = False
        self._log("applying the deferred manual compaction")
        # The player asked for it, so the window triggers play no part -- the ordinary
        # replacement rule (newest KEEP_ROUNDS rounds stay) is the one that runs.
        self._compress_old_rounds()


class ChatParam(BasicChatParam):
    """
    Chat parameter handler for managing chat interactions with the AI.

    This class extends :class:`BasicChatParam` and provides additional functionality for
    building an OpenAI client, adding messages to the response list, and handling forced
    additions to the response queue.
    """

    def __init__(
        self,
        server: 'ServerInterface',
        *,
        model_id: str | None = None,
    ):
        super().__init__(server, model_id=model_id)
        # Round ownership: exactly one thread may run this conversation's rounds at a time.
        # `is_stopped` mirrors that state for waiters, but an Event cannot be claimed
        # atomically, so the claim/release pair below is what actually serialises rounds.
        # Questions asked while a round is running are collected and sent afterwards as one
        # merged round by the owning thread (see ``ask_ai``).
        self._round_lock = threading.Lock()
        self._round_active = False
        self._pending_asks: list[tuple[CommandSource, str]] = []
        self.build_openai_client()

    def build_openai_client(self) -> None:
        if self.model_id is None:
            raise TypeError("model_id must be string")
        api_key = self.ai_info.get("api_key")
        base_url = self.ai_info.get("base_url")
        if api_key is None or base_url is None:
            raise AttributeError("api_key and base_url missing")
        self.openai_client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )

    def add_to_response_list(self, type: str, content: str, *, args: dict | None = None) -> None:
        if type not in self.allow_type:
            raise TypeError("Response type must be 'system', 'user', 'assistant', 'tool'")
        if not isinstance(type, str) or not isinstance(content, str):
            raise TypeError("type or content must be string")
        new = {}
        if args:
            new = args
        new["role"] = type
        new["content"] = content
        self._note_message_time()
        with self._ctx_lock:
            self.response_list.append(new)
            self._ctx_version += 1

    def forced_add_to_response_list(self, type: str, content: str) -> None:
        if type not in ['system', 'user']:
            raise TypeError("Forced add to response queue by type must be 'system' or 'user'")
        if not isinstance(type, str) or not isinstance(content, str):
            raise TypeError("type or content must be string")
        new = {}
        new["role"] = type
        new["content"] = content
        # Another thread may drain the queue at this very moment (response_ai), so the append
        # happens under the same lock as the drain. The baseline is taken here, when the message
        # was written, not when the next round happens to merge it.
        self._note_message_time()
        with self._ctx_lock:
            self.response_queue.append(new)

    def _merge_response_queue_locked(self) -> int:
        """Move every queued message into the history; returns how many were merged.

        The queue is filled from other threads -- ``!!ask -f`` and a message relayed by another
        user -- so the drain must be one atomic step: ``extend`` followed by ``clear`` could
        drop a message appended in between, and the sender would never know.
        """
        with self._ctx_lock:
            if not self.response_queue:
                return 0
            merged = len(self.response_queue)
            self.response_list.extend(self.response_queue)
            self.response_queue.clear()
            self._ctx_version += 1
            return merged

    def has_history(self) -> bool:
        """True when this conversation holds anything worth storing."""
        with self._ctx_lock:
            return bool(self.response_list or self.response_queue)

    def to_record(self) -> dict:
        """Snapshot of this conversation, ready to be stored (see ChatHistoryStore).

        Taken under :attr:`_ctx_lock` so a running round can never be cut in half: the stored
        state is exactly one state of the history, never a mixture of two.

        The ``usage`` block carries what a restart cannot recompute: the real input size of the
        last request, that round's counters and the raw usage dict behind the cache-hit share, so
        ``!!ask context`` shows the numbers it showed before. The held-context *estimate* is not
        in there on purpose -- :meth:`restore` recomputes it from the messages
        (:meth:`refresh_context_estimate`), which stays true when the window, the model or the
        history changed while the plugin was down. Both keys are optional for a reader: a record
        written before this existed simply has neither.
        """
        with self._ctx_lock:
            return {
                "messages": [message_to_json(msg) for msg in self.response_list],
                "queue": [message_to_json(msg) for msg in self.response_queue],
                "totals": {
                    "prompt": int(self._total_prompt_tokens),
                    "completion": int(self._total_completion_tokens),
                    "cached": int(self._total_cached_tokens),
                    "reasoning": int(self._total_reasoning_tokens),
                },
                "usage": {
                    "last_usage": _json_safe(self._last_usage),
                    "last_prompt": int(self._last_prompt_tokens),
                    "round_max_total": int(self._round_max_total_tokens),
                    "round_prompt": int(self._round_prompt_tokens),
                    "round_cached": int(self._round_cached_tokens),
                    "round_reasoning": int(self._round_reasoning_tokens),
                },
                "last_compress": _json_safe(self._last_compress),
                "rounds_since_time": int(self._rounds_since_time),
                # The time reading's two baselines. They ride along with the conversation so a
                # restart neither re-reads a stale clock nor loses how long the player was away;
                # a record written before they existed simply has neither key (see restore).
                "last_time_read": self._last_time_read,
                "last_message_at": self._last_message_at,
            }

    def restore(self, record: dict) -> int:
        """Fill this conversation from a stored record; returns how many messages were kept.

        Never raises on bad data: unusable messages are dropped one by one (see
        :func:`json_to_message`) and the survivors pass the same orphan-tool guard a round uses,
        because the stored conversation may come from an older build. The ``usage`` and
        ``last_compress`` keys are optional, so a record written before they existed restores the
        same way -- with zeroed counters instead of a skipped row.
        """
        messages = [m for m in (json_to_message(raw) for raw in (record.get("messages") or [])) if m]
        queue = [m for m in (json_to_message(raw) for raw in (record.get("queue") or []))
                 if m and m.get("role") in ("system", "user")]
        stored_totals = record.get("totals")
        stored_usage = record.get("usage")
        totals = stored_totals if isinstance(stored_totals, dict) else {}
        usage = stored_usage if isinstance(stored_usage, dict) else {}
        compress = record.get("last_compress")
        raw_usage = usage.get("last_usage")
        with self._ctx_lock:
            self.response_list = messages
            self.response_queue = queue
            self._ctx_version += 1
            self._total_prompt_tokens = _int_or_zero(totals.get("prompt"))
            self._total_completion_tokens = _int_or_zero(totals.get("completion"))
            self._total_cached_tokens = _int_or_zero(totals.get("cached"))
            self._total_reasoning_tokens = _int_or_zero(totals.get("reasoning"))
            self._last_usage = raw_usage if isinstance(raw_usage, dict) else None
            self._last_prompt_tokens = _int_or_zero(usage.get("last_prompt"))
            self._round_max_total_tokens = _int_or_zero(usage.get("round_max_total"))
            self._round_prompt_tokens = _int_or_zero(usage.get("round_prompt"))
            self._round_cached_tokens = _int_or_zero(usage.get("round_cached"))
            self._round_reasoning_tokens = _int_or_zero(usage.get("round_reasoning"))
            self._last_compress = compress if isinstance(compress, dict) else None
            self._rounds_since_time = _int_or_zero(record.get("rounds_since_time"))
            self._last_time_read = _epoch_or_none(record.get("last_time_read"))
            self._last_message_at = _epoch_or_none(record.get("last_message_at"))
        self._validate_sequence()
        self.refresh_context_estimate()
        return len(self.response_list)

    def add_external_message(self, sender: str, text: str, origin: str = "") -> str:
        """Put one message from another user into this conversation.

        Where it lands is decided by what this conversation is doing right now:

        * **idle** -- straight into the history, so it is stored together with it and read at the
          next question; the time injection and the merge of adjacent user messages then place it
          in front of that question, exactly like the server-change note;
        * **a round in flight** -- into the queue, which the running round merges at a safe point
          (never in the middle of a tool-call group, which providers reject).

        The message is always appended, never inserted before an unanswered question: the two
        look identical from here, and inserting would put a second delivery *in front of* the
        first one. The text is wrapped in a fixed, localized frame that names the sender and
        marks it as third-party content, so the receiving model cannot mistake it for its own
        user's words.

        :return: ``"history"`` or ``"queued"`` -- where the message landed.
        """
        content = str(self.server.rtr("games_ai.user_message.external_message",
                                      sender=sender, origin=origin or "-", message=text))
        with self._ctx_lock:
            if self.is_stopped.is_set():
                self._note_message_time()
                self.response_list.append({"role": "user", "content": content})
                self._ctx_version += 1
                return "history"
        self.forced_add_to_response_list("user", content)
        return "queued"

    def tool_call(self, source: CommandSource, tool_calls: list[ChatCompletionMessageFunctionToolCall]) -> None:
        ai_prefix = self.ai_info.get("ai_name", "")
        for tool_call in tool_calls:
            if self.stop_requested():
                self._log(f"stop requested: skipping the remaining {len(tool_calls)} tool call(s)")
                break
            func_name = tool_call.function.name
            handler = get_tool_handler(func_name)
            self.tool_count += 1

            if handler is None and not _runs_on_origin(handler, source, func_name):
                result = f"Unknown function: {func_name}"
                source.reply(f'{ai_prefix}{self.server.rtr("games_ai.tools.unknown_function",func_name=func_name)}')
            else:
                try:
                    func_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                    result, ok = dispatch_tool_call(handler, source, ai_prefix, func_name, func_args)
                    if ok:
                        source.reply(f'{ai_prefix}{self.server.rtr("games_ai.tools.tool_success")}')
                    else:
                        source.reply(f'{ai_prefix}{self.server.rtr("games_ai.tools.execution_error",func_name=func_name,ex=result)}')
                except Exception as e:
                    result = f"Error while executing function {func_name}: {e}"
                    source.reply(f'{ai_prefix}{self.server.rtr("games_ai.tools.execution_error",func_name=func_name,ex=e)}')

            self.add_to_response_list("tool", result, args={"tool_call_id": tool_call.id})
            self._log(f"tool_call: {func_name} (tool_count={self.tool_count}, result_chars={len(result)})")

    def _time_is_due(self, moment: float) -> bool:
        """Whether this round gets a reading: the first one, every N rounds, or a stale one.

        The round rule alone cannot keep the model's clock honest -- twenty rounds can be twenty
        seconds or twenty hours -- so a reading older than :data:`TIME_REFRESH_SECONDS` is
        refreshed whatever the counter says. A missing baseline (a record written before these
        fields existed) counts as stale.
        """
        if self._rounds_since_time == 1:
            return True
        if (self._rounds_since_time - 1) % TIME_INJECT_INTERVAL == 0:
            return True
        return (self._last_time_read is None
                or (moment - self._last_time_read) >= TIME_REFRESH_SECONDS)

    def _note_message_time(self, moment: float | None = None) -> None:
        """Remember when a real message entered this conversation (the reading's second baseline).

        Only real messages count. The time reading is placed by :meth:`_inject_time` and must not
        touch this: it says how long ago the previous message was, and it is not one itself.
        """
        self._last_message_at = clock.now() if moment is None else moment

    def _inject_time(self) -> None:
        """
        Put a time reading in front of this round's question, as a ``user`` message.

        The message is **stored in the history** rather than added to the outgoing request
        only: the next request must start with exactly the same prefix for the provider's
        cache to hit, and a timestamp that existed for a single request would shift
        everything behind it and invalidate the whole history.

        Cadence: whichever comes first -- the first round of a conversation, every
        :data:`TIME_INJECT_INTERVAL` rounds, or a reading older than
        :data:`TIME_REFRESH_SECONDS`. The last rule is what keeps a conversation that was left
        alone for a night from answering with yesterday's clock. Compression does not reset
        the state (the conversation continues); ``!!ask switch`` does (the history is gone).
        """
        moment = clock.now()
        self._rounds_since_time += 1
        if not self._time_is_due(moment):
            return
        message = _time_reading(
            round_no=self._rounds_since_time,
            elapsed_read=None if self._last_time_read is None else moment - self._last_time_read,
            elapsed_message=(None if self._last_message_at is None
                             else moment - self._last_message_at),
            moment=moment,
        )
        with self._ctx_lock:
            if not _insert_before_last_user(self.response_list, message):
                self.response_list.append(message)
            self._ctx_version += 1
        self._last_time_read = moment
        self._log(
            f"time injected in front of the question "
            f"(round {self._rounds_since_time} of this conversation)"
        )

    def _preamble(self, data: list[tuple[str, str]] | None) -> list[dict]:
        """
        The leading block of the request: the single system message, plus the public data
        list when the database actually holds something.

        The data is a separate ``assistant`` message on purpose (reference material rather
        than an instruction) and it is skipped entirely when there is nothing to send — an
        empty "public data" message would only spend tokens and confuse the model. ``data``
        may therefore be ``None``.
        """
        preamble = list(self.build_system_message())
        if data:
            preamble.append(_data_message(self.server, data))
        return preamble

    def response_ai(self, source: CommandSource, data: list[tuple[str, str]] | None = None) -> None:
        # Every caller that did not claim the round through ``try_claim_round`` (``ask_ai``
        # claims before it comes here; tests call this directly) gets a temporary ownership,
        # so the round state is released even when any part of the setup below raises. The
        # body is wrapped as a whole for the same reason: the setup used to sit outside the
        # try and a failure there left the conversation "running" forever (see is_stopped).
        claimed_here = False
        self._ensure_round_state()
        with self._round_lock:
            if not self._round_active:
                self._round_active = True
                claimed_here = True
                self.is_stopped.clear()
        try:
            self.begin_round()
            self._round_max_total_tokens = 0

            merged_leftover = self._merge_response_queue_locked()
            if merged_leftover:
                self._log(f"response_ai start: merged {merged_leftover} leftover queued message(s) into history")

            # after the queue merge: the time belongs directly in front of this round's question
            self._inject_time()
            system = self._preamble(data)

            ai_model = self.ai_info.get("ai_model", "")
            ai_prefix = self.ai_info.get("ai_name", "")
            # the hub owns its hub-bound tools, the asking instance owns the rest (see games_ai_tool)
            ai_tools = get_request_tool_schemas(source.get_permission_level(), _uploaded_tools(source))
            extra_body = self.ai_info.get("extra_body", {})
            self._log(
                f"response_ai start: model={ai_model}, history={len(self.response_list)}, "
                f"queue={len(self.response_queue)}, stats={self.context_stats()}"
            )
            while True:
                # `!!ask stop` aborts here when it arrived while nothing was in flight
                if self.stop_requested():
                    self._abort_interrupted_round()
                    return
                # keep the request that is about to be sent inside the window
                self.manage_context(system, ai_tools, preflight=True, source=source)
                self._log(f"request -> model={ai_model}, {self._describe_history(len(system))}")
                ai_reply, usage = response_chat(
                    self.openai_client,
                    model=ai_model,
                    # adjacent user messages (time + question, skill note + question, a retried
                    # question, `!!ask -f` batches) leave as one message
                    response_list=system + _merge_adjacent_user_messages(self.response_list),
                    tools=ai_tools,
                    extra_body=extra_body
                )
                # the round may have been stopped while this request was in flight:
                # drop the step instead of using the answer
                if self.stop_requested():
                    self._abort_interrupted_round()
                    return
                self._record_usage(usage)
                with self._ctx_lock:
                    self.response_list.append(ai_reply)
                    self._ctx_version += 1
                if ai_reply.content:
                    source.reply(f"{ai_prefix}{ai_reply.content}")

                if ai_reply.tool_calls:
                    self.tool_call(source, ai_reply.tool_calls)

                merged_now = self._merge_response_queue_locked()
                has_queue = bool(merged_now)

                if has_queue:
                    self._log(f"merged {merged_now} queued message(s) into running round (continue)")

                # evaluate the window triggers after every request of this round
                self.manage_context(system, ai_tools)

                if ai_reply.tool_calls or has_queue:
                    continue
                self._validate_sequence()
                self._log(f"response_ai finished: history={len(self.response_list)}, stats={self.context_stats()}")
                break
        except Exception as e:
            # The player-facing sentence is not written here any more: `ask_ai` owns it
            # (see _ask_error_reply in __init__.py), because only the caller can tell a bad
            # key from a rate limit, and an exception raised here used to escape all the way
            # into MCDR. What stays here is the detail an operator needs: the provider's
            # status code, its localized description and its request id -- at WARNING, so it
            # is readable without turning !!gamesai debug on first.
            _log_failure(self.server, "ChatParam", "response_ai error", e)
            raise
        finally:
            if claimed_here:
                with self._round_lock:
                    self._round_active = False
                    self.is_stopped.set()

    def change_model(self, source: CommandSource, model_id: str) -> str:
        """
        Switch the model with a summary hand-off (v0.7.1, option B1 of issue #20).

        The current conversation is compressed by the **old** model into one neutral,
        factual system message (topic, settled conclusions, open items) and the raw history
        is cleared, so the new model's persona is not shaped by the old model's replies.

        The summarizing request is **deferred**: like the normal context compression it is
        sent right before the next request (see :meth:`_apply_pending_hand_off`), so the
        switch command returns immediately. If it fails then, the history simply stays
        cleared and the player is told.

        :return: ``"same"`` (already on that model), ``"scheduled"`` (hand-off pending),
                 or ``"empty"`` (nothing to hand over)
        """
        if model_id == self.model_id:
            return "same"

        # Never rewrite the history of a running round: wait for it, then claim the ownership
        # so a newly queued ask cannot start in the same instant (see try_claim_round).
        self._ensure_round_state()
        while True:
            self.wait_until_stop()
            if self.try_claim_round():
                break
            time.sleep(0.01)
        try:
            had_history = bool(self.response_list)
            if had_history:
                # keep the old conversation + old model so the hand-off can be produced later;
                # switching again before that request keeps the original snapshot
                self._pending_hand_off = {
                    "client": self.openai_client,
                    "ai_info": self.ai_info,
                    "messages": list(self.response_list),
                }

            self.model_id = model_id
            self.ai_info: dict = plugin_config.all_ai.get(self.model_id, {})
            self.build_openai_client()
            self.build_system_message()

            with self._ctx_lock:                # another thread may be handing a message over
                self.response_list.clear()
                self.response_queue.clear()
                self._ctx_version += 1
            self._rounds_since_time = 0     # new conversation: the next round injects the time again
            # ...and with no baselines to measure from, that reading says "unavailable" for both
            # elapsed lines instead of measuring against a conversation that is gone.
            self._last_time_read = None
            self._last_message_at = None
            self.tool_count = 0
            self._last_prompt_tokens = 0
            self._round_max_total_tokens = 0
            self._last_base_estimate = 0
            self._last_estimate = 0
            self._log(
                f"switch: model_id={self.model_id}, had_history={had_history}, "
                f"hand_over={'scheduled' if self._pending_hand_off else 'none'}"
            )
            return "scheduled" if self._pending_hand_off else "empty"
        finally:
            self.release_round()


class NonHistoryChatParam:
    """
    Stateless one-shot counterpart of :class:`ChatParam` (used by ``!!ask -n``).

    The class is self-contained on purpose: it shares no helper, attribute or lifecycle
    with ``BasicChatParam``, so nothing from the history machinery can be reached here.

    It deliberately keeps none of it:

    * no ``response_list`` / ``response_queue`` — the conversation lives inside
      :meth:`response_ai` and is released when that call returns,
    * no context management — no token estimation, no calibration, no trimming,
      no summarization request, no ``is_stopped`` event, no round statistics,
    * no model switching / skill injection — a throwaway object is rebuilt instead.

    What shapes a single answer still matches ``ChatParam``: the same system messages,
    the same tools for the caller's permission level, the same replies and the same error
    report. The HTTP client is shared per endpoint + key by this class itself, so repeated
    calls do not rebuild a connection pool.
    """

    allow_type = [
        'system',
        'user',
        'assistant',
        'tool'
    ]

    # one OpenAI client (and one connection pool) per endpoint + key, owned by this class
    _client_cache: dict[tuple[str, str], OpenAI] = {}
    _client_cache_lock = threading.Lock()
    _CLIENT_CACHE_MAX = 8

    def __init__(
        self,
        server: 'ServerInterface',
        *,
        model_id: str | None = None,
    ):
        self.server = server
        self.model_id: str | None = model_id
        self.ai_info: dict = plugin_config.all_ai.get(self.model_id, {})
        self.openai_client: OpenAI | None = None
        # messages staged for the next single round; emptied by response_ai()
        self.pending: list[dict] = []
        # `!!ask stop` support (same epoch scheme as BasicChatParam, kept local to this class)
        self._round_running = False
        self._stop_epoch: int = 0
        self._round_epoch: int = 0
        self._stop_lock = threading.Lock()

        self.build_openai_client()

    @property
    def get_openai_client(self) -> OpenAI | None:
        return self.openai_client

    @property
    def get_model_id(self) -> str | None:
        return self.model_id

    def request_stop(self) -> bool:
        """
        Abort the running one-shot request (nothing is retained, so there is no step to
        delete — the in-flight answer is simply discarded).

        :return: True when a request was actually running.
        """
        with self._stop_lock:
            if not self._round_running:
                return False
            self._stop_epoch += 1
            return True

    def stop_requested(self) -> bool:
        with self._stop_lock:
            return self._round_running and self._round_epoch != self._stop_epoch

    def begin_round(self) -> None:
        with self._stop_lock:
            self._round_epoch = self._stop_epoch

    def end_round(self) -> None:
        with self._stop_lock:
            self._round_running = False

    def build_openai_client(self) -> None:
        if self.model_id is None:
            raise TypeError("model_id must be string")
        api_key = self.ai_info.get("api_key")
        base_url = self.ai_info.get("base_url")
        if api_key is None or base_url is None:
            raise AttributeError("api_key and base_url missing")

        cache_key = (base_url, api_key)
        with self._client_cache_lock:
            client = self._client_cache.get(cache_key)
            if client is None:
                if len(self._client_cache) >= self._CLIENT_CACHE_MAX:
                    self._client_cache.clear()
                client = OpenAI(api_key=api_key, base_url=base_url)
                self._client_cache[cache_key] = client
        self.openai_client = client

    def build_system_message(self) -> list[dict]:
        """
        The single system message of a one-shot request, built here instead of borrowing the
        history class' version; the output matches ``ChatParam.build_system_message()``.

        Same two rules as there: one message only, because strict chat templates reject a
        second system message, and no time inside it, because the time is injected at
        request time (see :meth:`response_ai`).
        """
        prompt = str(self.ai_info.get("prompt", ""))

        default_skills = [
            {"file": "skills_management.md", "description": str(self.server.rtr("games_ai.builtin_skills.skills_management"))},
            {"file": "custom_tools_management.md", "description": str(self.server.rtr("games_ai.builtin_skills.custom_tools_management"))},
            {"file": "mineflayer_bot_guide.md", "description": str(self.server.rtr("games_ai.builtin_skills.mineflayer_bot_guide", username=plugin_config.bot_username))},
        ]
        external_skills: list[dict[str, str]] = []
        if EXTERNAL_SKILLS_LIST:
            for i in EXTERNAL_SKILLS_LIST:
                file = i.get("file")
                description = i.get("description")
                if file is None or description is None:
                    continue
                external_skills.append({"file": file, "description": description})

        skills_file_list = str(self.server.rtr(
            "games_ai.user_message.skills",
            skills=[*plugin_config.skills_description, *default_skills, *external_skills]
        ))

        parts = [part for part in (prompt, skills_file_list) if part]
        return [{"role": "system", "content": "\n\n".join(parts)}]

    def add_to_response_list(self, type: str, content: str, *, args: dict | None = None) -> None:
        """Stage one message for the next round."""
        if type not in self.allow_type:
            raise TypeError("Response type must be 'system', 'user', 'assistant', 'tool'")
        if not isinstance(type, str) or not isinstance(content, str):
            raise TypeError("type or content must be string")
        new = dict(args) if args else {}
        new["role"] = type
        new["content"] = content
        self.pending.append(new)

    def tool_call(self, source: CommandSource, tool_calls: list[ChatCompletionMessageFunctionToolCall]) -> list[dict]:
        """Run the requested tools and return their result messages for this round only."""
        ai_prefix = self.ai_info.get("ai_name", "")
        results: list[dict] = []
        for tool_call in tool_calls:
            if self.stop_requested():
                self._log(f"stop requested: skipping the remaining {len(tool_calls)} tool call(s)")
                break
            func_name = tool_call.function.name
            handler = get_tool_handler(func_name)

            if handler is None and not _runs_on_origin(handler, source, func_name):
                result = f"Unknown function: {func_name}"
                source.reply(f'{ai_prefix}{self.server.rtr("games_ai.tools.unknown_function",func_name=func_name)}')
            else:
                try:
                    func_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                    result, ok = dispatch_tool_call(handler, source, ai_prefix, func_name, func_args)
                    if ok:
                        source.reply(f'{ai_prefix}{self.server.rtr("games_ai.tools.tool_success")}')
                    else:
                        source.reply(f'{ai_prefix}{self.server.rtr("games_ai.tools.execution_error",func_name=func_name,ex=result)}')
                except Exception as e:
                    result = f"Error while executing function {func_name}: {e}"
                    source.reply(f'{ai_prefix}{self.server.rtr("games_ai.tools.execution_error",func_name=func_name,ex=e)}')

            results.append({"role": "tool", "content": result, "tool_call_id": tool_call.id})
            self._log(f"tool_call: {func_name} (result_chars={len(result)})")
        return results

    def _fit_into_window(self, messages: list[dict]) -> None:
        """
        Last-resort guard for the single-round path.

        A round without history can hardly overflow a window (a tool result can), and an
        over-window request is rejected with an error and lost, so the newest message is
        truncated to whatever room is left. The older ones were already accepted by the
        provider during this round, so they are left untouched — this is a safety net, not
        the context management of ``ChatParam``.
        """
        window = resolve_context_window(self.ai_info.get("ai_model", ""), self.ai_info.get("context_window"))
        if window <= 0:
            return
        budget = int(window * NON_HISTORY_WINDOW_RATIO)

        def size(msg) -> int:
            return estimate_text_tokens(_msg_text(msg)) + _MESSAGE_OVERHEAD

        system_tokens = 0
        others: list[int] = []
        for i, msg in enumerate(messages):
            if _msg_role(msg) == "system":
                system_tokens += size(msg)
            else:
                others.append(i)
        if not others:
            return

        total = system_tokens + sum(size(messages[i]) for i in others)
        if total <= budget:
            return

        last = others[-1]
        older = sum(size(messages[i]) for i in others[:-1])
        original = _msg_content(messages[last]) or ""
        trimmed = _shrink_text(original, max(0, budget - system_tokens - older))

        if isinstance(messages[last], dict):
            messages[last]["content"] = trimmed          # keep tool_call_id and friends
        else:
            messages[last] = {"role": _msg_role(messages[last]) or "user", "content": trimmed}
        self._log(
            f"request over window ({total} > {budget} of {window} tokens): "
            f"truncated newest message {len(original)} -> {len(trimmed)} chars"
        )

    def response_ai(self, source: CommandSource, data: list[tuple[str, str]] | None = None) -> None:
        """
        Answer once, following tool calls until the model stops requesting them.

        ``data`` is the public database dump; it is attached as an ``assistant`` message and
        skipped entirely when it is ``None`` or empty. A time reading is always injected in
        front of the question (every ``!!ask -n`` is the first round of its own conversation),
        and never as a ``system`` message. This object is thrown away after the call, so the
        reading has no baselines to measure from and says so instead of inventing a duration.

        No message is kept afterwards: the whole request is local to this call. A
        ``!!ask stop`` for this player makes the loop return without answering.
        """
        messages = self.build_system_message()
        if data:
            messages.append(_data_message(self.server, data))
        messages.extend(self.pending)
        time_message = _time_reading(round_no=1, elapsed_read=None, elapsed_message=None)
        if not _insert_before_last_user(messages, time_message):
            messages.append(time_message)
        # same rule as the history path: adjacent user messages are one turn for the model
        messages = _merge_adjacent_user_messages(messages)
        self.pending.clear()

        ai_model = self.ai_info.get("ai_model", "")
        ai_prefix = self.ai_info.get("ai_name", "")
        # same split as the history path: hub-bound tools here, the origin's own tools uploaded
        ai_tools = get_request_tool_schemas(source.get_permission_level(), _uploaded_tools(source))
        extra_body = self.ai_info.get("extra_body", {})
        self._log(f"response_ai start (no history): model={ai_model}, messages={len(messages)}, tools={len(ai_tools)}")

        with self._stop_lock:
            self._round_running = True
        self.begin_round()

        ai_reply = None
        try:
            while True:
                try:
                    if self.stop_requested():
                        self._log("response_ai aborted by stop (no history): answer discarded")
                        return
                    self._fit_into_window(messages)
                    # usage is dropped on purpose: without history there is nothing to calibrate
                    ai_reply, _usage = response_chat(
                        self.openai_client,
                        model=ai_model,
                        response_list=messages,
                        tools=ai_tools,
                        extra_body=extra_body
                    )
                    if self.stop_requested():
                        self._log("response_ai aborted by stop (no history): answer discarded")
                        return
                    messages.append(ai_reply)
                    if ai_reply.content:
                        source.reply(f"{ai_prefix}{ai_reply.content}")

                    if not ai_reply.tool_calls:
                        self._log(f"response_ai finished (no history): messages={len(messages)}")
                        return

                    messages.extend(self.tool_call(source, ai_reply.tool_calls))
                except Exception as e:
                    _log_failure(self.server, "NonHistoryChatParam",
                                 "response_ai error (no history)", e)
                    raise
        finally:
            self.end_round()

    def _log(self, msg: str) -> None:
        """Bookkeeping line: visible once ``!!gamesai debug`` is on (see logger.verbose)."""
        logger.verbose(self.server, msg, tag="NonHistoryChatParam")


# ── in-flight `!!ask -n` requests ───────────────────────────────────────────
# A stateless request lives only inside ask_ai(), so it registers itself here while it
# runs; that is the only way `!!ask stop` can reach it.

_no_history_active: dict[str, NonHistoryChatParam] = {}
_no_history_active_lock = threading.Lock()


def register_no_history(username: str, param: NonHistoryChatParam) -> None:
    """Track a running ``!!ask -n`` request of ``username``."""
    with _no_history_active_lock:
        _no_history_active[username] = param


def unregister_no_history(username: str, param: NonHistoryChatParam | None = None) -> None:
    """Stop tracking a request; with ``param`` given only when it is still the tracked one."""
    with _no_history_active_lock:
        current = _no_history_active.get(username)
        if current is not None and (param is None or current is param):
            _no_history_active.pop(username, None)


def stop_no_history(username: str) -> bool:
    """Abort the running ``!!ask -n`` request of ``username``; True when there was one."""
    with _no_history_active_lock:
        param = _no_history_active.get(username)
    return bool(param is not None and param.request_stop())
