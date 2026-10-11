# Generated from games_ai/ai/openai_api.py by tools/build_tool_stubs.py -- do not edit.
import logging
from _typeshed import Incomplete
from openai import OpenAI
from openai.types.chat.chat_completion_message import ChatCompletionMessage as ChatCompletionMessage

class _MCDRBridgeHandler(logging.Handler):
    _mcdr: Incomplete
    def __init__(self, mcdr_logger: logging.Logger) -> None: ...
    def emit(self, record: logging.LogRecord): ...

_openai_bridge_setup_done: bool

def http_logger_names() -> list[str]:
    """Every logger the OpenAI SDK may write its HTTP traffic to.

    The SDK's HTTP dependency gets renamed from time to time -- ``httpx`` in the 1.x SDKs,
    ``httpx2`` in the 2.x/3.x ones -- and a hardcoded list is exactly how
    ``INFO:httpx2:HTTP Request: ...`` ended up printed by the root logger instead of the
    MCDR console. The names are therefore read from the installed SDK's own metadata, with
    the known ones kept as a fallback for the import-shadowing case.
    """
def setup_openai_logging(mcdr_logger: logging.Logger, level=...): ...
def response_chat(client: OpenAI, model: str, response_list: list, *, tools=None, extra_body=None, timeout: float | None = None) -> tuple[ChatCompletionMessage, dict | None]:
    """
    Send one chat completion request.

    :return: ``(message, usage)`` — ``usage`` is the raw provider usage dict
             (``prompt_tokens`` / ``completion_tokens`` / ``total_tokens`` / cache fields)
             or ``None`` when the provider did not report it. The usage is used for
             context management (calibration and window triggers).
    """
