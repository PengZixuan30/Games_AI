import logging
from openai import OpenAI
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.chat.chat_completion import ChatCompletion


class _MCDRBridgeHandler(logging.Handler):

    def __init__(self, mcdr_logger: logging.Logger):
        super().__init__()
        self._mcdr = mcdr_logger

    def emit(self, record: logging.LogRecord):
        msg = self.format(record)
        lvl = record.levelno
        if lvl >= logging.ERROR:
            self._mcdr.error(msg)
        elif lvl >= logging.WARNING:
            self._mcdr.warning(msg)
        elif lvl >= logging.INFO:
            self._mcdr.info(msg)
        else:
            self._mcdr.debug(msg)


_openai_bridge_setup_done = False


def http_logger_names() -> list[str]:
    """Every logger the OpenAI SDK may write its HTTP traffic to.

    The SDK's HTTP dependency gets renamed from time to time -- ``httpx`` in the 1.x SDKs,
    ``httpx2`` in the 2.x/3.x ones -- and a hardcoded list is exactly how
    ``INFO:httpx2:HTTP Request: ...`` ended up printed by the root logger instead of the
    MCDR console. The names are therefore read from the installed SDK's own metadata, with
    the known ones kept as a fallback for the import-shadowing case.
    """
    names = {"openai", "httpx", "httpx2", "httpcore", "httpcore2"}
    try:
        from importlib.metadata import requires
        for requirement in requires("openai") or []:
            dependency = requirement.split(";")[0].split()[0].strip().lower()
            if dependency.startswith(("httpx", "httpcore")):
                names.add(dependency)
    except Exception:
        pass
    return sorted(names)


def setup_openai_logging(mcdr_logger: logging.Logger, level=logging.INFO):
    global _openai_bridge_setup_done
    if _openai_bridge_setup_done:
        return
    _openai_bridge_setup_done = True

    fmt = logging.Formatter("[OpenAI] %(message)s")
    handler = _MCDRBridgeHandler(mcdr_logger)
    handler.setFormatter(fmt)
    handler.setLevel(level)

    bridged = []
    for name in http_logger_names():
        lg = logging.getLogger(name)
        lg.setLevel(level)
        lg.handlers.clear()
        # propagate=False is what keeps the record from reaching the root logger, where it
        # would be printed a second time in a plain "LEVEL:name:message" format.
        lg.propagate = False
        lg.addHandler(handler)
        bridged.append(name)

    mcdr_logger.info("[OpenAI] Logging bridge enabled (level=%s, loggers=%s)",
                     logging.getLevelName(level), ", ".join(bridged))


def response_chat(
    client: OpenAI,
    model: str,
    response_list: list,
    *,
    tools = None,
    extra_body = None,
    timeout: float | None = None,
) -> tuple[ChatCompletionMessage, dict | None]:
    """
    Send one chat completion request.

    :return: ``(message, usage)`` — ``usage`` is the raw provider usage dict
             (``prompt_tokens`` / ``completion_tokens`` / ``total_tokens`` / cache fields)
             or ``None`` when the provider did not report it. The usage is used for
             context management (calibration and window triggers).
    """
    if not isinstance(client, OpenAI):
        raise TypeError("Must pass in OpenAI object")
    if not isinstance(model, str):
        raise TypeError("Model must be string")

    kwargs = dict(
        model=model,
        messages=response_list,
        tools=tools,
        extra_body=extra_body,
        stream=False,
    )
    if timeout is not None:
        kwargs["timeout"] = timeout

    response: ChatCompletion = client.chat.completions.create(**kwargs)

    if not isinstance(response, ChatCompletion):
        raise TypeError("Response type was error")

    usage: dict | None = None
    if response.usage is not None:
        try:
            usage = response.usage.model_dump()
        except AttributeError:
            usage = dict(response.usage)
    return response.choices[0].message, usage
