import logging
from openai import OpenAI


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


def response_chat(model,url,message,api_key,tools=[],extra_body={}):

    client = OpenAI(
        api_key=api_key,
        base_url=url
    )
    
    response = client.chat.completions.create(
        model=model,
        messages=message,
        tools=tools,
        stream=False,
        extra_body=extra_body,
    )

    return response.choices[0].message
