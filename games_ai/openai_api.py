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


def setup_openai_logging(mcdr_logger: logging.Logger, level=logging.INFO):
    global _openai_bridge_setup_done
    if _openai_bridge_setup_done:
        return
    _openai_bridge_setup_done = True

    fmt = logging.Formatter("[OpenAI] %(message)s")
    handler = _MCDRBridgeHandler(mcdr_logger)
    handler.setFormatter(fmt)
    handler.setLevel(level)

    for name in ("openai", "httpx"):
        lg = logging.getLogger(name)
        lg.setLevel(level)
        lg.handlers.clear()
        lg.propagate = False
        lg.addHandler(handler)

    mcdr_logger.info("[OpenAI] Logging bridge enabled (level=%s)", logging.getLevelName(level))


def response_chat(
    client: OpenAI,
    model: str,
    response_list,
    *,
    tools = None,
    extra_body = None,
) -> ChatCompletionMessage:

    if not isinstance(client, OpenAI):
        raise TypeError("Must pass in OpenAI object")
    if not isinstance(model, str):
        raise TypeError("Model must be string")

    response: ChatCompletion = client.chat.completions.create(
        model=model,
        messages=response_list,
        tools=tools,
        extra_body=extra_body,
        stream=False,
    )

    if not isinstance(response, ChatCompletion):
        raise TypeError("Response type was error")

    return response.choices[0].message
