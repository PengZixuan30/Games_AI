from abc import ABC, abstractmethod
from openai import OpenAI
import json, datetime, re, threading

from .openai_api import response_chat
from .config import plugin_config
from .context_table import resolve_context_window, resolve_max_output
from .games_ai_tool import get_tool_handler, get_tool_schemas_for_perm
from .external_skills_loader import EXTERNAL_SKILLS_LIST

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

        # `!!ask stop` support: a running round compares its epoch snapshot with this
        # counter, so a stop request is never lost even if another round starts later.
        self._stop_epoch: int = 0
        self._round_epoch: int = 0
        self._stop_lock = threading.Lock()

        # pending model-switch hand-off (see change_model / _apply_pending_hand_off)
        self._pending_hand_off: dict | None = None

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
            self.response_list.insert(0, {"role": "system", "content": f"{prefix}\n{summary}"})
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

    def _describe_history(self, system_count: int) -> str:
        """Compact description of the request that is about to be sent (debug logging)."""
        counts: dict[str, int] = {}
        for msg in self.response_list:
            role = _msg_role(msg) or "?"
            counts[role] = counts.get(role, 0) + 1
        return (
            f"system={system_count}, history={len(self.response_list)} {counts}, "
            f"hand-off summary={'yes' if self._has_switch_summary() else 'no'}"
        )

    def request_stop(self) -> bool:
        """
        Ask the running round of this conversation to abort (used by ``!!ask stop``).

        An in-flight HTTP request cannot be cancelled, so the round stops at its next
        checkpoint: before the next request, right after a response arrives, or between
        two tool calls of a batch. The interrupted step is then dropped from the history.
        Queued ``!!ask -f`` messages are discarded as well.

        :return: True when a round was actually running (and will abort).
        """
        with self._stop_lock:
            self.response_queue.clear()
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

    def _truncate_interrupted_step(self) -> int:
        """
        Drop the step that ``!!ask stop`` interrupted.

        * a trailing tool-call group (assistant message with ``tool_calls`` plus its tool
          results) is removed as a whole, so no orphan tool message is left behind;
        * otherwise everything the interrupted round appended is removed — the trailing
          message, messages merged from ``!!ask -f`` and injected system notes — stopping
          at the last completed assistant turn, so an interrupted ask never happened;
        * when that round had already appended a final answer, that answer is removed too.
        """
        messages = self.response_list
        if not messages:
            return 0

        tail = len(messages)
        while tail > 0 and _msg_role(messages[tail - 1]) == "tool":
            tail -= 1
        if tail > 0 and _msg_role(messages[tail - 1]) == "assistant" and _msg_tool_calls(messages[tail - 1]):
            removed = len(messages) - tail + 1
            del messages[tail - 1:]
            self._log(f"stop: dropped the interrupted tool-call group ({removed} message(s))")
            return removed

        removed = 0
        while messages and _msg_role(messages[-1]) != "assistant":
            del messages[-1:]
            removed += 1
        if removed == 0 and messages:
            # the round already produced its final answer: it was interrupted, so drop it
            del messages[-1:]
            removed = 1
        self._log(f"stop: dropped the interrupted step ({removed} message(s))")
        return removed

    def _abort_interrupted_round(self) -> None:
        """Finish a round that ``!!ask stop`` interrupted (truncate, validate, release)."""
        removed = self._truncate_interrupted_step()
        self._validate_sequence()
        self._log(
            f"response_ai aborted by stop: dropped {removed} message(s), "
            f"history={len(self.response_list)}, queue={len(self.response_queue)}"
        )
        self.is_stopped.set()

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
        Time + prompt + the list of skills the model may load.

        Stored in ``self.system_message`` and returned; every history-based parameter
        object starts its request with exactly these messages.
        """
        prompt = str(self.ai_info.get("prompt", ""))
        now_time = str(self.server.rtr("games_ai.user_message.time", time=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

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

        self.system_message.clear()
        self.system_message.append({
            "role": "system",
            "content": now_time,
        })
        self.system_message.append({
            "role": "system",
            "content": prompt,
        })
        self.system_message.append({
            "role": "system",
            "content": skills_file_list
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
    def response_ai(self, source: CommandSource, data: list[tuple[str, str]]) -> None:
        """
        Response AI loop
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

    def _window_for(self, ai_info: dict) -> int:
        """Same resolution for an arbitrary AI entry (the switch hand-off uses the old one)."""
        return resolve_context_window(
            str(ai_info.get("ai_model", "")),
            ai_info.get("context_window"),
        )

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
        if not usage:
            return
        try:
            prompt = int(usage.get("prompt_tokens") or 0)
            completion = int(usage.get("completion_tokens") or 0)
            total = int(usage.get("total_tokens") or (prompt + completion))
        except (TypeError, ValueError):
            return
        if prompt > 0:
            self._last_prompt_tokens = prompt
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
        """
        pending: list = []
        rounds: list[list] = []
        for msg in self.response_list:
            role = _msg_role(msg)
            if role == "system":
                pending.append(msg)
                continue
            if role == "user":
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
        preamble, rounds = self._split_rounds()
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
        """Replace all but the newest KEEP_ROUNDS rounds with one summary system message."""
        preamble, rounds = self._split_rounds()
        if len(rounds) <= KEEP_ROUNDS:
            self._log(f"compress skipped: {len(rounds)} round(s) <= KEEP_ROUNDS({KEEP_ROUNDS})")
            return False
        old_rounds = rounds[:-KEEP_ROUNDS]
        keep_rounds = rounds[-KEEP_ROUNDS:]
        existing_summaries = [m for group in old_rounds for m in group if _msg_role(m) == "system"]
        summary = self._summarize(old_rounds, existing_summaries)

        new_list: list = list(preamble)
        if summary:
            prefix = str(self.server.rtr("games_ai.context.summary_prefix"))
            new_list.append({"role": "system", "content": f"{prefix}\n{summary}"})
        for group in keep_rounds:
            new_list.extend(group)

        before, after = len(self.response_list), len(new_list)
        self.response_list = new_list
        self._log(
            f"compressed {len(old_rounds)} old round(s): messages {before} -> {after}, "
            f"summary={'ok' if summary else 'failed(dropped)'}, est={self._last_estimate}, "
            f"window={self.context_window()}"
        )
        return True

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
                self.response_list = cleaned
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
        """Debug-mode logging: INFO level when !!gamesai debug is on, DEBUG otherwise."""
        try:
            if plugin_config.debug_mode:
                self.server.logger.info(f"[ChatParam]{msg}")
            else:
                self.server.logger.debug(f"[ChatParam]{msg}")
        except Exception:
            pass

    def reload_ai_info(self) -> None:
        self.ai_info: dict = plugin_config.all_ai.get(self.model_id, {})
        self.build_openai_client()
        self.build_system_message()


class ChatParam(BasicChatParam):

    def __init__(
        self,
        server: 'ServerInterface',
        *,
        model_id: str | None = None,
    ):
        super().__init__(server, model_id=model_id)
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
        self.response_list.append(new)

    def forced_add_to_response_list(self, type: str, content: str) -> None:
        if type not in ['system', 'user']:
            raise TypeError("Forced add to response queue by type must be 'system' or 'user'")
        if not isinstance(type, str) or not isinstance(content, str):
            raise TypeError("type or content must be string")
        new = {}
        new["role"] = type
        new["content"] = content
        self.response_queue.append(new)

    def tool_call(self, source: CommandSource, tool_calls: list[ChatCompletionMessageFunctionToolCall]) -> None:
        ai_prefix = self.ai_info.get("ai_name", "")
        for tool_call in tool_calls:
            if self.stop_requested():
                self._log(f"stop requested: skipping the remaining {len(tool_calls)} tool call(s)")
                break
            func_name = tool_call.function.name
            handler = get_tool_handler(func_name)
            self.tool_count += 1

            if handler is None:
                result = f"Unknown function: {func_name}"
                source.reply(f'{ai_prefix}{self.server.rtr("games_ai.tools.unknown_function",func_name=func_name)}')
            else:
                try:
                    func_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                    result = str(handler.func(source, ai_prefix, **func_args))
                    source.reply(f'{ai_prefix}{self.server.rtr("games_ai.tools.tool_success")}')
                except Exception as e:
                    result = f"Error while executing function {func_name}: {e}"
                    source.reply(f'{ai_prefix}{self.server.rtr("games_ai.tools.execution_error",func_name=func_name,ex=e)}')

            self.add_to_response_list("tool", result, args={"tool_call_id": tool_call.id})
            self._log(f"tool_call: {func_name} (tool_count={self.tool_count}, result_chars={len(result)})")

    def response_ai(self, source: CommandSource, data: list[tuple[str, str]]) -> None:
        self.is_stopped.clear()
        self.begin_round()
        self._round_max_total_tokens = 0

        merged_leftover = len(self.response_queue)
        self.response_list.extend(self.response_queue)
        self.response_queue.clear()
        if merged_leftover:
            self._log(f"response_ai start: merged {merged_leftover} leftover queued message(s) into history")

        system = self.build_system_message()
        system.append({"role": "system","content": f'{str(self.server.rtr("games_ai.user_message.data_list"))}{data}'})

        ai_model = self.ai_info.get("ai_model", "")
        ai_prefix = self.ai_info.get("ai_name", "")
        ai_tools = get_tool_schemas_for_perm(source.get_permission_level())
        extra_body = self.ai_info.get("extra_body", {})
        self._log(
            f"response_ai start: model={ai_model}, history={len(self.response_list)}, "
            f"queue={len(self.response_queue)}, stats={self.context_stats()}"
        )
        while True:
            try:
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
                    response_list=system + self.response_list,
                    tools=ai_tools,
                    extra_body= extra_body
                )
                # the round may have been stopped while this request was in flight:
                # drop the step instead of using the answer
                if self.stop_requested():
                    self._abort_interrupted_round()
                    return
                self._record_usage(usage)
                self.response_list.append(ai_reply)
                if ai_reply.content:
                    source.reply(f"{ai_prefix}{ai_reply.content}")

                if ai_reply.tool_calls:
                    self.tool_call(source, ai_reply.tool_calls)

                has_queue = bool(self.response_queue)

                if has_queue:
                    n = len(self.response_queue)
                    self.response_list.extend(self.response_queue)
                    self.response_queue.clear()
                    self._log(f"merged {n} queued message(s) into running round (continue)")

                # evaluate the window triggers after every request of this round
                self.manage_context(system, ai_tools)

                if ai_reply.tool_calls or has_queue:
                    continue
                self._validate_sequence()
                self._log(f"response_ai finished: history={len(self.response_list)}, stats={self.context_stats()}")
                break
            except Exception as e:
                error_code_map = {
                    400: self.server.rtr("games_ai.error_code_map.error400"),
                    401: self.server.rtr("games_ai.error_code_map.error401"),
                    402: self.server.rtr("games_ai.error_code_map.error402"),
                    403: self.server.rtr("games_ai.error_code_map.error403"),
                    404: self.server.rtr("games_ai.error_code_map.error404"),
                    408: self.server.rtr("games_ai.error_code_map.error408"),
                    422: self.server.rtr("games_ai.error_code_map.error422"),
                    429: self.server.rtr("games_ai.error_code_map.error429"),
                    500: self.server.rtr("games_ai.error_code_map.error500"),
                    502: self.server.rtr("games_ai.error_code_map.error502"),
                    503: self.server.rtr("games_ai.error_code_map.error503"),
                }
    
                error_code = getattr(e, 'status_code', None)
                request_id = None
    
                resp = getattr(e, 'response', None)
                if resp is not None:
                    request_id = getattr(resp, '_request_id', None)
    
                if request_id is None:
                    try:
                        request_id = ai_reply._request_id
                    except (NameError, AttributeError):
                        request_id = None
    
                if error_code is not None:
                    error_desc = error_code_map.get(error_code)
                    if error_desc is None:
                        error_desc = str(self.server.rtr("games_ai.error_code_map.error_unknown", code=error_code))
                    rid_str = f" [Request ID: {request_id}]" if request_id else ""
                    source.reply(f'{ai_prefix}ERROR! [Code: {error_code}] {error_desc}{rid_str}\n{ai_prefix}{e}')
                else:
                    source.reply(f'{ai_prefix}ERROR!\n{ai_prefix}{e}')
                self._log(f"response_ai error: {e}")
                self.is_stopped.set()
                raise e
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

        self.wait_until_stop()          # never rewrite the history of a running round
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

        self.response_list.clear()
        self.response_queue.clear()
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

    # error code -> i18n key; this class formats its own error replies
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
        System messages for this round, built here instead of borrowing the history
        class' version; the output is identical to ``ChatParam.build_system_message()``.
        """
        prompt = str(self.ai_info.get("prompt", ""))
        now_time = str(self.server.rtr("games_ai.user_message.time", time=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

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

        return [
            {"role": "system", "content": now_time},
            {"role": "system", "content": prompt},
            {"role": "system", "content": skills_file_list},
        ]

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

            if handler is None:
                result = f"Unknown function: {func_name}"
                source.reply(f'{ai_prefix}{self.server.rtr("games_ai.tools.unknown_function",func_name=func_name)}')
            else:
                try:
                    func_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                    result = str(handler.func(source, ai_prefix, **func_args))
                    source.reply(f'{ai_prefix}{self.server.rtr("games_ai.tools.tool_success")}')
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

    def response_ai(self, source: CommandSource, data: list[tuple[str, str]]) -> None:
        """
        Answer once, following tool calls until the model stops requesting them.

        No message is kept afterwards: the whole request is local to this call. A
        ``!!ask stop`` for this player makes the loop return without answering.
        """
        messages = self.build_system_message()
        messages.append({"role": "system", "content": f'{str(self.server.rtr("games_ai.user_message.data_list"))}{data}'})
        messages.extend(self.pending)
        self.pending.clear()

        ai_model = self.ai_info.get("ai_model", "")
        ai_prefix = self.ai_info.get("ai_name", "")
        ai_tools = get_tool_schemas_for_perm(source.get_permission_level())
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
                    error_code = getattr(e, 'status_code', None)
                    request_id = None

                    response = getattr(e, 'response', None)
                    if response is not None:
                        request_id = getattr(response, '_request_id', None)

                    if request_id is None and ai_reply is not None:
                        request_id = getattr(ai_reply, '_request_id', None)

                    if error_code is not None:
                        rtr_key = self._ERROR_CODE_KEYS.get(error_code) or "games_ai.error_code_map.error_unknown"
                        error_desc = str(self.server.rtr(rtr_key, code=error_code))
                        rid_str = f" [Request ID: {request_id}]" if request_id else ""
                        source.reply(f'{ai_prefix}ERROR! [Code: {error_code}] {error_desc}{rid_str}\n{ai_prefix}{e}')
                    else:
                        source.reply(f'{ai_prefix}ERROR!\n{ai_prefix}{e}')
                    self._log(f"response_ai error (no history): {e}")
                    raise e
        finally:
            self.end_round()

    def _log(self, msg: str) -> None:
        """Debug-mode logging: INFO level when !!gamesai debug is on, DEBUG otherwise."""
        try:
            if plugin_config.debug_mode:
                self.server.logger.info(f"[NonHistoryChatParam]{msg}")
            else:
                self.server.logger.debug(f"[NonHistoryChatParam]{msg}")
        except Exception:
            pass


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
