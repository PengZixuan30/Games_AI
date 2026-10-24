# Generated from games_ai/ai/chat_param.py by tools/build_tool_stubs.py -- do not edit.
import abc
from . import context_table as context_table
from ..cluster.ws_command import WebSocketCommandSource as WebSocketCommandSource
from ..core import clock as clock, logger as logger
from ..core.config import plugin_config as plugin_config
from .context_table import resolve_context_window as resolve_context_window, resolve_max_output as resolve_max_output
from .external_skills_loader import EXTERNAL_SKILLS_LIST as EXTERNAL_SKILLS_LIST
from .games_ai_tool import get_request_tool_schemas as get_request_tool_schemas, get_tool_handler as get_tool_handler
from .openai_api import response_chat as response_chat
from _typeshed import Incomplete
from abc import ABC, abstractmethod
from collections.abc import Callable as Callable
from mcdreforged.command.command_source import CommandSource as CommandSource
from mcdreforged.plugin.si.server_interface import ServerInterface as ServerInterface
from openai import OpenAI
from openai.types.chat.chat_completion_message_function_tool_call import ChatCompletionMessageFunctionToolCall as ChatCompletionMessageFunctionToolCall

KEEP_ROUNDS: int
TRIGGER_HISTORY_RATIO: float
TRIGGER_REQUEST_RATIO: float
EMERGENCY_RATIO: float
EMERGENCY_TARGET_RATIO: float
MESSAGE_TOKEN_CAP_RATIO: float
MESSAGE_TOKEN_CAP_ABS: int
SUMMARY_INPUT_RATIO: float
SUMMARY_TIMEOUT: int
TOOLS_FIXED_OVERHEAD: int
NON_HISTORY_WINDOW_RATIO: float
TIME_INJECT_INTERVAL: int
TIME_REFRESH_SECONDS: int
CALIBRATION_ALPHA: float
CALIBRATION_MIN: float
CALIBRATION_MAX: float
_ASCII_TOKEN_DIVISOR: float
_MESSAGE_OVERHEAD: int
_CJK_RANGES: Incomplete
_calibration_store: dict[str, float]
_calibration_lock: Incomplete
_ERROR_CODE_KEYS: Incomplete

def _calibration_key(base_url: str, model: str) -> str: ...
def _is_cjk(ch: str) -> bool: ...
def estimate_text_tokens(text: str) -> int:
    """
    Rough token estimation that works across tokenizers and languages.

    latin: ~4 characters per token; CJK: ~1 token per character. The systematic
    bias of a specific provider/model is corrected by the usage calibration below.
    """
def _shrink_text(text: str, cap_tokens: int) -> str:
    """Return the longest prefix of ``text`` that estimates within ``cap_tokens``."""
def _int_at(usage: dict, section: str, key: str) -> int:
    """One nested usage counter (``prompt_tokens_details.cached_tokens`` etc.), or 0."""
def _role_counts(messages) -> dict[str, int]:
    """How many messages of each role the history holds (for ``!!ask context``)."""
def _msg_role(msg) -> str | None: ...
def _msg_tool_calls(msg):
    """The ``tool_calls`` of a message, or None (dicts and SDK objects)."""
def _msg_content(msg) -> str: ...
def _int_or_zero(value) -> int:
    """One stored counter, or 0 when it is missing or not a number."""
def _json_safe(value):
    """A JSON-primitive-only copy of a provider value.

    The raw usage dict and the compression note travel inside the stored conversation record, and
    that record is written with ``json.dumps``: one value the encoder cannot handle would lose the
    **whole** conversation, so anything that is not a plain primitive, list or dict is turned into
    a string at the leaf.
    """
def message_to_json(msg) -> dict:
    """One history message as a plain, JSON-serializable dict.

    ``response_ai`` appends the SDK's ``ChatCompletionMessage`` object to the history exactly as
    the provider returned it, so the stored list is a mix of dicts and SDK objects. This is the
    single normal form the history store writes -- and the form the provider accepts again on the
    next request. ``reasoning_content`` survives on purpose: providers that return it require it
    back in the tool-call round that produced it.
    """
def json_to_message(raw) -> dict | None:
    """The inverse of :func:`message_to_json`; None for anything unusable.

    A stored conversation is data from an earlier run (possibly of an older plugin version), so
    every message is validated here instead of being trusted: an unknown role, a message that is
    not an object or a tool result without its ``tool_call_id`` would otherwise travel straight
    into the next request.
    """
def _elapsed_line(label: str, seconds: float | None) -> str:
    '''One elapsed line: the duration when a baseline exists, "unavailable" when it does not.'''
def _time_reading(*, round_no: int, elapsed_read: float | None, elapsed_message: float | None, moment: float | None = None) -> dict:
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
def _epoch_or_none(value) -> float | None:
    """A stored epoch, or None when it is missing, not a number, or in the future.

    The stored record can come from an older build (no such key), from a damaged file, or from a
    machine whose clock was wrong when it was written. A timestamp the plugin has not reached yet
    is treated as unknown rather than trusted: the elapsed lines are measured against it.
    """
def _insert_before_last_user(messages: list, message: dict) -> bool:
    """
    Put ``message`` immediately in front of the newest ``user`` message — the question it
    belongs to. Returns False when the list holds no user message at all.
    """
def _data_message(server: ServerInterface, data: list[tuple[str, str]]) -> dict:
    """The public database dump as an ``assistant`` message (reference material, not an order)."""
def _merge_adjacent_user_messages(messages: list) -> list:
    '''
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
    '''
def _msg_text(msg) -> str:
    """All token-relevant text of a message (content + tool calls + reasoning + ids)."""

_remote_tool_router: Callable[[CommandSource, str, dict, str], str] | None

def set_remote_tool_router(router: Callable[[CommandSource, str, dict, str], str] | None) -> None:
    """Install the function that runs a tool call on the instance the request came from."""
def describe_http_status(server: ServerInterface, status) -> str:
    '''The localized meaning of one provider HTTP status, or "" when this build has none.

    The table lives here because this module owns the status codes, and both readers share it so
    the operator\'s log line and the player\'s reply can never describe the same code differently:
    :func:`_ai_error_detail` (which falls back to ``error_unknown``) and
    ``__init__._ask_error_reply`` (which simply omits the parenthesis when there is nothing to
    add).
    '''
def _log_failure(server: ServerInterface, tag: str, prefix_text: str, error: Exception) -> None:
    """One failed AI request, at a level the operator sees without ``!!gamesai debug``.

    The detail line (status code, its localized meaning, the provider's request id) used to go
    through ``ChatParam._log``, i.e. to DEBUG unless debug mode was on -- which hid exactly the
    part that says what to change. A failure is not a normal flow, so it is a WARNING and always
    visible. ``tag`` keeps the class name in front of the line, as the per-class loggers did.
    """
def _ai_error_detail(prefix_text: str, error: Exception, server: ServerInterface) -> str:
    """One log line about a failed AI request: status code, localized text, provider request id.

    The player-facing sentence is not written here: ``ask_ai`` owns it (``_ask_error_reply``),
    because only the caller can tell a bad key from a rate limit. What stays here is the detail
    an operator needs, and its status description comes from :func:`describe_http_status` -- the
    very text the player's reply now carries as well.
    """
def _uploaded_tools(source: CommandSource) -> list[dict] | None:
    """The schemas the asking instance uploaded, or None for a request made on this instance."""
def _uploaded_tool_names(source: CommandSource) -> set[str]:
    """The tool names the asking instance said it can run on its own side."""
def _runs_on_origin(handler, source: CommandSource, func_name: str) -> bool:
    '''True when this call has to be handed to the instance the request came from.

    A tool that is not hub-bound acts on the asking player\'s own server, so on a request that
    crossed the link it belongs there. A name this instance does not know at all goes over as
    well when the origin uploaded it: only that side can run it, and it answers with its own
    "this server does not provide tool X" when it cannot either.
    '''
def dispatch_tool_call(handler, source: CommandSource, ai_prefix: str, func_name: str, func_args: dict) -> tuple[str, bool]:
    """Run one tool call, here or on the instance it belongs to.

    The single place a tool is invoked, for every caller. Returns ``(result_text, ok)`` and
    never lets a routed failure escape: the model gets an honest string instead, and the AI
    round keeps going. A *local* tool that raises still propagates to the caller, which turns
    it into the usual ``Error while executing function ...`` result.

    Routing blocks until the origin answers. That is safe here and only here: this runs on the
    AI loop thread, which may wait -- a link thread must never do it (see
    ``__init__._on_cross_message``).
    """

class BasicChatParam(ABC, metaclass=abc.ABCMeta):
    """
    A abstract basic class about ChatParam Object.
    """
    allow_type: Incomplete
    _ctx_version: int
    server: Incomplete
    model_id: str | None
    ai_info: dict
    openai_client: OpenAI | None
    response_list: list[dict]
    system_message: list[dict]
    response_queue: list[dict]
    tool_count: int
    is_stopped: Incomplete
    _last_prompt_tokens: int
    _round_max_total_tokens: int
    _last_base_estimate: int
    _last_estimate: int
    _last_usage: dict | None
    _last_compress: dict | None
    _round_prompt_tokens: int
    _round_cached_tokens: int
    _round_reasoning_tokens: int
    _total_prompt_tokens: int
    _total_completion_tokens: int
    _total_cached_tokens: int
    _total_reasoning_tokens: int
    _ctx_lock: Incomplete
    _stop_epoch: int
    _round_epoch: int
    _stop_lock: Incomplete
    _pending_hand_off: dict | None
    _pending_compaction: bool
    _rounds_since_time: int
    _last_time_read: float | None
    _last_message_at: float | None
    def __init__(self, server: ServerInterface, *, model_id: str | None = None) -> None: ...
    def _apply_pending_hand_off(self, source: CommandSource | None = None) -> None:
        """
        Summarize a conversation that was switched away, before the next request.

        This is the deferred half of the ``!!ask switch`` hand-off (option B1): like the
        normal context compression, the extra summarizing request is sent from the round
        that needs it instead of inside the command, so the switch itself never blocks.
        The previous model writes the summary; the old history was already cleared, so the
        result is injected as the first system message of the new conversation.
        """
    def _has_switch_summary(self) -> bool:
        """True when the history currently carries a model-switch hand-off summary."""
    def _describe_history(self, preamble_count: int) -> str:
        """Compact description of the request that is about to be sent (debug logging)."""
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
    def begin_round(self) -> None:
        """Take the epoch snapshot a round compares against (see :meth:`stop_requested`)."""
    def stop_requested(self) -> bool:
        """True when :meth:`request_stop` was called after the current round started."""
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
    def _abort_interrupted_round(self) -> None:
        """Finish a round that ``!!ask stop`` interrupted (keep the history, validate, release).

        The round is not marked stopped here any more: this conversation owns its round through
        :meth:`ChatParam.try_claim_round` / :meth:`ChatParam.release_round`, and the queued
        questions of a merged conversation are sent afterwards (see ``ask_ai``).
        """
    @property
    def get_response_list(self) -> list[dict]: ...
    @property
    def get_response_queue(self) -> list[dict]: ...
    @property
    def get_openai_client(self) -> OpenAI | None: ...
    @property
    def get_model_id(self) -> str | None: ...
    @property
    def get_is_stopped(self) -> bool: ...
    @abstractmethod
    def build_openai_client(self) -> None:
        """
        Build a OpenAI client object
        """
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
    @abstractmethod
    def add_to_response_list(self, type: str, content: str, *, args: dict | None = None) -> None:
        """
        Add a message to response queue
        """
    @abstractmethod
    def forced_add_to_response_list(self, type: str, content: str) -> None:
        """
        Forced add a message to response queue
        """
    @abstractmethod
    def tool_call(self, source: CommandSource, tool_calls: list[ChatCompletionMessageFunctionToolCall]) -> None:
        """
        Auto run tools.
        """
    @abstractmethod
    def response_ai(self, source: CommandSource, data: list[tuple[str, str]] | None = None) -> None:
        """
        Response AI loop

        ``data`` is the public database content to attach to the request; ``None`` (or an
        empty list) means the database holds nothing and no data message is sent.
        """
    @abstractmethod
    def change_model(self, source: CommandSource, model_id: str) -> None:
        """
        Change the model and re-build a OpenAI client object and re-build system message
        """
    def context_window(self) -> int:
        """Effective context window: config override -> table -> conservative default."""
    def context_window_source(self) -> str:
        """Where the effective window comes from: ``config``, ``table`` or ``default``."""
    def _window_for(self, ai_info: dict) -> int:
        """Same resolution for an arbitrary AI entry (the switch hand-off uses the old one)."""
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
    def context_stats(self) -> dict: ...
    def _calibration_factor(self) -> float: ...
    def _update_calibration(self, base_estimate: int, real_prompt_tokens: int) -> None:
        """EMA-adjust the calibration factor so that base_estimate * factor ~= real."""
    def _record_usage(self, usage: dict | None) -> None:
        """
        Remember what the provider charged for one request.

        The raw dict is kept as well (not just the three ints), because it carries the cache
        and reasoning counters that ``!!ask context`` shows, and because a provider that
        answers without usage must not leave the previous request's numbers on display.
        """
    def _estimate_request_tokens(self, system: list[dict], tools: list[dict] | None) -> int: ...
    def _split_rounds(self) -> tuple[list, list[list]]:
        """
        Split the history into rounds (one user message plus its assistant/tool follow-ups)
        and a preamble of leading system messages.

        Runs under :attr:`_ctx_lock`: a command thread takes its snapshot through this, while
        the round thread may be appending to or replacing the very same list.
        """
    def _split_rounds_locked(self) -> tuple[list, list[list]]: ...
    def _drop_oldest_round(self) -> bool:
        """Drop the oldest round (split + edit + replace must be atomic against a snapshot)."""
    def _drop_oldest_round_locked(self) -> bool: ...
    def _truncate_long_messages(self, cap_tokens: int) -> bool:
        """Shrink oversized messages (split + edit + replace, atomic against a snapshot)."""
    def _truncate_long_messages_locked(self, cap_tokens: int) -> bool: ...
    def _emergency_reduce(self, system: list[dict], tools: list[dict] | None, target_ratio: float) -> None:
        """Guarantee the next request fits: truncate huge messages, then drop rounds."""
    @staticmethod
    def _transcript_lines(messages) -> list[str]:
        """``Role: text`` lines of a message collection; tool results are skipped as bulky."""
    def _summary_request(self, parts: list[str], *, client: OpenAI | None = None, ai_info: dict | None = None) -> str | None:
        """
        One neutral factual summary request (no tools).

        ``client``/``ai_info`` default to the current model; the model-switch hand-off
        passes the *previous* ones so that the old model writes its own summary.
        """
    def _summarize(self, rounds: list[list], existing_summaries: list) -> str | None:
        """Compress old rounds into a neutral factual summary (no tools, content only)."""
    def _limit_summary_input(self, parts: list[str], window: int) -> list[str]:
        """Keep the newest part of the summarization input within its own budget."""
    def _compress_old_rounds(self) -> bool:
        '''
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
        '''
    def _compress_old_rounds_locked(self) -> bool:
        """Compatibility name: the compression no longer runs under the lock (see above)."""
    def _validate_sequence(self) -> None:
        """Drop orphan tool messages / broken tool-call groups before sending."""
    def manage_context(self, system: list[dict], tools: list[dict] | None, *, preflight: bool = False, source: CommandSource | None = None) -> None:
        """
        Keep the request within the model window.

        Called before every request (``preflight=True``) and after every request
        (post-round). Compression keeps the newest KEEP_ROUNDS rounds verbatim and
        replaces older rounds with a neutral summary; if that is not enough, giant
        messages are truncated and the oldest rounds are dropped. A pending model-switch
        hand-off is applied here as well, i.e. right before the next request.
        """
    def wait_until_stop(self) -> None:
        """
        Wait this round stop
        """
    def _log(self, msg: str) -> None:
        """Bookkeeping line: visible once ``!!gamesai debug`` is on (see logger.verbose)."""
    def context_view(self) -> list[tuple[str, str]]:
        """
        Render :meth:`context_snapshot` as ``(line, hover)`` pairs for ``!!ask context``.

        Kept next to the state it describes (and not in the command layer) so the thresholds
        shown here are the very constants the window management uses; the text comes from
        ``self.server.rtr``, like everywhere else in this class.

        The produced text is deliberately short — the chat box only gets a few lines — while
        the hover carries the details that would not fit, such as the per-round sizes.
        """
    def reload_ai_info(self) -> bool:
        """Re-read this conversation's model from the config (hot reload).

        A model the config no longer has (removed or renamed while the conversation is live)
        must not abort the reload: the warning is logged and the previous client/info are kept,
        so the conversation keeps answering until the player switches or the config gains the
        model again. The reload itself continues (see ``_reload_body``).

        :return: True when the conversation now uses a configured model, False when the
                 previous one was kept.
        """
    def is_running(self) -> bool:
        """True while a round of this conversation is in flight (for messages/commands)."""
    _round_active: bool
    def try_claim_round(self) -> bool:
        """Atomically take this conversation's round ownership.

        :return: True when the caller now owns the round and must call :meth:`release_round`
                 (or :meth:`finish_round_or_take_next` when it runs a merged sequence).
        """
    def queue_pending_ask(self, source: CommandSource, message: str) -> None:
        """Queue one question asked while another round owns this conversation.

        The owner thread drains the queue when its round ends and sends the questions in
        arrival order as one merged round (see ``ask_ai``).
        """
    _pending_asks: Incomplete
    def finish_round_or_take_next(self) -> tuple[list[tuple[CommandSource, str]], bool] | None:
        """Finish the current round of an owned sequence, or start its next merged round.

        :return: ``(batch, True)`` while the owner must run another round; ``None`` when the
                 sequence is finished and the round ownership has been released.
        """
    def release_round(self) -> None:
        """Release this conversation's round ownership (idempotent safety net)."""
    def is_round_active(self) -> bool:
        """True while some thread owns this conversation's round (or merged sequence)."""
    _round_lock: Incomplete
    def _ensure_round_state(self) -> None:
        """Create the ownership/stop state on objects built without ``__init__`` (test doubles)."""
    def compact_history(self) -> str:
        '''
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
        '''
    def _apply_pending_compaction(self) -> None:
        """
        Run a manual compaction that was requested earlier (deferred half of
        :meth:`compact_history`). Called from the preflight, so the forced compression is
        then handled by the ordinary flow of that same preflight.
        """

class ChatParam(BasicChatParam):
    """
    Chat parameter handler for managing chat interactions with the AI.

    This class extends :class:`BasicChatParam` and provides additional functionality for
    building an OpenAI client, adding messages to the response list, and handling forced
    additions to the response queue.
    """
    _round_lock: Incomplete
    _round_active: bool
    _pending_asks: list[tuple[CommandSource, str]]
    def __init__(self, server: ServerInterface, *, model_id: str | None = None) -> None: ...
    openai_client: Incomplete
    def build_openai_client(self) -> None: ...
    def add_to_response_list(self, type: str, content: str, *, args: dict | None = None) -> None: ...
    def forced_add_to_response_list(self, type: str, content: str) -> None: ...
    def _merge_response_queue_locked(self) -> int:
        """Move every queued message into the history; returns how many were merged.

        The queue is filled from other threads -- ``!!ask -f`` and a message relayed by another
        user -- so the drain must be one atomic step: ``extend`` followed by ``clear`` could
        drop a message appended in between, and the sender would never know.
        """
    def has_history(self) -> bool:
        """True when this conversation holds anything worth storing."""
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
    response_list: Incomplete
    response_queue: Incomplete
    _total_prompt_tokens: Incomplete
    _total_completion_tokens: Incomplete
    _total_cached_tokens: Incomplete
    _total_reasoning_tokens: Incomplete
    _last_usage: Incomplete
    _last_prompt_tokens: Incomplete
    _round_max_total_tokens: Incomplete
    _round_prompt_tokens: Incomplete
    _round_cached_tokens: Incomplete
    _round_reasoning_tokens: Incomplete
    _last_compress: Incomplete
    _rounds_since_time: Incomplete
    _last_time_read: Incomplete
    _last_message_at: Incomplete
    def restore(self, record: dict) -> int:
        """Fill this conversation from a stored record; returns how many messages were kept.

        Never raises on bad data: unusable messages are dropped one by one (see
        :func:`json_to_message`) and the survivors pass the same orphan-tool guard a round uses,
        because the stored conversation may come from an older build. The ``usage`` and
        ``last_compress`` keys are optional, so a record written before they existed restores the
        same way -- with zeroed counters instead of a skipped row.
        """
    def add_external_message(self, sender: str, text: str, origin: str = '') -> str:
        '''Put one message from another user into this conversation.

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
        user\'s words.

        :return: ``"history"`` or ``"queued"`` -- where the message landed.
        '''
    def tool_call(self, source: CommandSource, tool_calls: list[ChatCompletionMessageFunctionToolCall]) -> None: ...
    def _time_is_due(self, moment: float) -> bool:
        """Whether this round gets a reading: the first one, every N rounds, or a stale one.

        The round rule alone cannot keep the model's clock honest -- twenty rounds can be twenty
        seconds or twenty hours -- so a reading older than :data:`TIME_REFRESH_SECONDS` is
        refreshed whatever the counter says. A missing baseline (a record written before these
        fields existed) counts as stale.
        """
    def _note_message_time(self, moment: float | None = None) -> None:
        """Remember when a real message entered this conversation (the reading's second baseline).

        Only real messages count. The time reading is placed by :meth:`_inject_time` and must not
        touch this: it says how long ago the previous message was, and it is not one itself.
        """
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
    def _preamble(self, data: list[tuple[str, str]] | None) -> list[dict]:
        '''
        The leading block of the request: the single system message, plus the public data
        list when the database actually holds something.

        The data is a separate ``assistant`` message on purpose (reference material rather
        than an instruction) and it is skipped entirely when there is nothing to send — an
        empty "public data" message would only spend tokens and confuse the model. ``data``
        may therefore be ``None``.
        '''
    def response_ai(self, source: CommandSource, data: list[tuple[str, str]] | None = None) -> None: ...
    _pending_hand_off: Incomplete
    model_id: Incomplete
    ai_info: dict
    tool_count: int
    _last_base_estimate: int
    _last_estimate: int
    def change_model(self, source: CommandSource, model_id: str) -> str:
        '''
        Switch the model with a summary hand-off (v0.7.1, option B1 of issue #20).

        The current conversation is compressed by the **old** model into one neutral,
        factual system message (topic, settled conclusions, open items) and the raw history
        is cleared, so the new model\'s persona is not shaped by the old model\'s replies.

        The summarizing request is **deferred**: like the normal context compression it is
        sent right before the next request (see :meth:`_apply_pending_hand_off`), so the
        switch command returns immediately. If it fails then, the history simply stays
        cleared and the player is told.

        :return: ``"same"`` (already on that model), ``"scheduled"`` (hand-off pending),
                 or ``"empty"`` (nothing to hand over)
        '''

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
    allow_type: Incomplete
    _client_cache: dict[tuple[str, str], OpenAI]
    _client_cache_lock: Incomplete
    _CLIENT_CACHE_MAX: int
    server: Incomplete
    model_id: str | None
    ai_info: dict
    openai_client: OpenAI | None
    pending: list[dict]
    _round_running: bool
    _stop_epoch: int
    _round_epoch: int
    _stop_lock: Incomplete
    def __init__(self, server: ServerInterface, *, model_id: str | None = None) -> None: ...
    @property
    def get_openai_client(self) -> OpenAI | None: ...
    @property
    def get_model_id(self) -> str | None: ...
    def request_stop(self) -> bool:
        """
        Abort the running one-shot request (nothing is retained, so there is no step to
        delete — the in-flight answer is simply discarded).

        :return: True when a request was actually running.
        """
    def stop_requested(self) -> bool: ...
    def begin_round(self) -> None: ...
    def end_round(self) -> None: ...
    def build_openai_client(self) -> None: ...
    def build_system_message(self) -> list[dict]:
        """
        The single system message of a one-shot request, built here instead of borrowing the
        history class' version; the output matches ``ChatParam.build_system_message()``.

        Same two rules as there: one message only, because strict chat templates reject a
        second system message, and no time inside it, because the time is injected at
        request time (see :meth:`response_ai`).
        """
    def add_to_response_list(self, type: str, content: str, *, args: dict | None = None) -> None:
        """Stage one message for the next round."""
    def tool_call(self, source: CommandSource, tool_calls: list[ChatCompletionMessageFunctionToolCall]) -> list[dict]:
        """Run the requested tools and return their result messages for this round only."""
    def _fit_into_window(self, messages: list[dict]) -> None:
        """
        Last-resort guard for the single-round path.

        A round without history can hardly overflow a window (a tool result can), and an
        over-window request is rejected with an error and lost, so the newest message is
        truncated to whatever room is left. The older ones were already accepted by the
        provider during this round, so they are left untouched — this is a safety net, not
        the context management of ``ChatParam``.
        """
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
    def _log(self, msg: str) -> None:
        """Bookkeeping line: visible once ``!!gamesai debug`` is on (see logger.verbose)."""

_no_history_active: dict[str, NonHistoryChatParam]
_no_history_active_lock: Incomplete

def register_no_history(username: str, param: NonHistoryChatParam) -> None:
    """Track a running ``!!ask -n`` request of ``username``."""
def unregister_no_history(username: str, param: NonHistoryChatParam | None = None) -> None:
    """Stop tracking a request; with ``param`` given only when it is still the tracked one."""
def stop_no_history(username: str) -> bool:
    """Abort the running ``!!ask -n`` request of ``username``; True when there was one."""
