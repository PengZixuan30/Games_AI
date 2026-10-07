"""Reproduce the production leak: where does the OpenAI SDK's `HTTP Request:` line go?

Prod symptom:
    [MCDR] [09:25:11] [games_ai@ask_ai/INFO]: [小墨]正在思考...
    INFO:httpx2:HTTP Request: POST https://open.cherryin.ai/v1/chat/completions "HTTP/1.1 400 Bad Request"
The second line is printed by the root logger in BASIC_FORMAT, outside MCDR's formatting.
"""
import http.server
import importlib.metadata
import logging
import re
import socketserver
import threading
import time
import types

import pytest

from games_ai import openai_api


class Sink(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))


@pytest.fixture
def bridge():
    """A fake MCDR logger, the real bridge, and the root logger that must stay silent.

    The bridge is global state: it clears the handlers of every SDK logger and remembers that it
    was installed. The fixture snapshots all of it -- the levels, the handler lists, the
    propagate flags and the module's "installed" flag -- and puts it back when the test ends, so
    one test's bridge (bound to one test's sink) can never satisfy the next test's ``setup``
    call and leave its sink empty.
    """
    mcdr_sink = Sink()
    mcdr_sink.setFormatter(logging.Formatter("%(levelname)s/%(name)s: %(message)s"))
    mcdr_log = logging.Logger("games_ai@ask_ai", level=logging.INFO)
    mcdr_log.addHandler(mcdr_sink)

    root_sink = Sink()
    root_sink.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))   # BASIC_FORMAT
    root_level = logging.root.level
    logging.root.addHandler(root_sink)
    logging.root.setLevel(logging.INFO)

    saved = {}
    for name in openai_api.http_logger_names():
        logger = logging.getLogger(name)
        saved[name] = (logger.level, list(logger.handlers), logger.propagate)

    installed = openai_api._openai_bridge_setup_done
    openai_api._openai_bridge_setup_done = False
    openai_api.setup_openai_logging(mcdr_log, logging.INFO)

    yield types.SimpleNamespace(log=mcdr_log, sink=mcdr_sink, root=root_sink)

    openai_api._openai_bridge_setup_done = installed
    for name, (level, handlers, propagate) in saved.items():
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.handlers[:] = handlers
        logger.propagate = propagate
    logging.root.removeHandler(root_sink)
    logging.root.setLevel(root_level)


@pytest.fixture
def bad_request_server(free_port):
    """A local HTTP server that answers every POST with the provider's real 400 body."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = b'{"error":{"message":"boom","type":"bad_response_status_code"}}'
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = socketserver.TCPServer(("127.0.0.1", free_port()), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:{}/v1".format(server.server_address[1])
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_the_sdk_http_loggers_are_discovered():
    names = openai_api.http_logger_names()

    assert "httpx2" in names, f"httpx2 is bridged (the SDK's real HTTP dependency): {names}"
    assert "httpx" in names, f"httpx is still covered (older SDKs): {names}"
    assert "httpcore2" in names, f"httpcore2 is covered: {names}"

    deps = [re.split(r"[<>=!~\[;\s]", d)[0] for d in (importlib.metadata.requires("openai") or [])]
    assert "httpx2" in deps, \
        f"the installed SDK really requires httpx2: {[d for d in deps if 'httpx' in d]}"


def test_a_real_400_request_lands_in_the_mcdr_logger(bridge, bad_request_server):
    from openai import OpenAI

    client = OpenAI(api_key="sk-test", base_url=bad_request_server, max_retries=0)
    try:
        client.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}])
    except Exception:
        pass                       # the request failing is what this suite wants
    time.sleep(0.2)

    request_lines = [l for l in bridge.sink.lines if "HTTP Request" in l]
    escaped = [l for l in bridge.root.lines if "HTTP Request" in l]

    assert bool(request_lines), \
        f"the HTTP request line reached the MCDR logger: {bridge.sink.lines[-5:]}"
    assert request_lines and "[OpenAI]" in request_lines[0], \
        f"it is prefixed like every other bridged line: {request_lines[:2]}"
    assert request_lines and "400" in request_lines[0], \
        f"it mentions the 400 from the provider: {request_lines[:2]}"
    assert not escaped, f"it did NOT escape to the root logger: {escaped[:3]}"


def test_the_bridge_holds_for_child_loggers_and_is_not_installed_twice(bridge):
    def bridge_handlers():
        """The bridge's own handlers on httpx2.

        pytest's logging plugin attaches a capture handler of its own while a test runs, so the
        check counts the bridge's handlers rather than every handler on the logger.
        """
        return [h for h in logging.getLogger("httpx2").handlers
                if isinstance(h, openai_api._MCDRBridgeHandler)]

    assert logging.getLogger("httpx2").propagate is False, "httpx2.propagate is False"
    assert len(bridge_handlers()) == 1, \
        f"httpx2 has exactly the bridge handler: {logging.getLogger('httpx2').handlers}"

    logging.getLogger("httpx2._client").warning("a child logger record")
    assert any("a child logger record" in l for l in bridge.sink.lines), \
        f"a child logger is bridged too: {bridge.sink.lines[-3:]}"
    assert not any("a child logger record" in l for l in bridge.root.lines), \
        "and does not escape to root"

    before = len(bridge_handlers())
    openai_api.setup_openai_logging(bridge.log, logging.DEBUG)
    assert len(bridge_handlers()) == before, "no duplicate handler is installed"
