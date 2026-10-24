"""``!!ask context --all`` groups by the configured AI entry, not by the upstream model.

Two ``all_ai`` entries may point at the same upstream ``ai_model`` while being different
assistants (different ``ai_name``/prompt/key). The server-wide view used to group on the upstream
model, so those two configurations collapsed into one row, named after whichever conversation was
read first -- the command claimed "1 model" although players were spread over two configured AIs.
The row is now the configured entry (its ``all_ai`` id, shown by ``ai_name``) and the hover names
the id and the upstream model; conversations whose numbers cannot be read are logged instead of
silently disappearing from the totals.
"""
import logging
import threading

import pytest

import games_ai


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def warnings(self):
        return [str(record.getMessage()) for record in self.records
                if record.levelno == logging.WARNING]


class FakeServer:
    """Enough MCDR for the command: the three translated templates and a logger."""

    def __init__(self):
        self.logger = logging.getLogger("context-all-server")
        self.logger.propagate = False

    def rtr(self, key, **kwargs):
        templates = {
            "games_ai.context_all.header": "SERVER({players} players, {models} models)",
            "games_ai.context_all.empty": "EMPTY",
            "games_ai.context_all.line": "{model} · {players} player(s) · {estimate}/{window}",
            "games_ai.context_all.hover": "AI {model_id} upstream {model} · total {total}",
            "games_ai.context_all.total": "TOTAL {estimate}",
            "games_ai.context_all.hover_hint": "HINT",
        }
        template = templates.get(key, key)
        return template.format(**kwargs) if kwargs else template


class FakeSource:
    def __init__(self, server):
        self.server = server
        self.replies = []

    def get_server(self):
        return self.server

    def reply(self, message, **kwargs):
        self.replies.append(message)

    def text(self):
        parts = []
        for reply in self.replies:
            plain = getattr(reply, "to_plain_text", None)
            parts.append(plain() if callable(plain) else str(reply))
        return "\n".join(parts)

    def hovers(self):
        """Every hover text carried by the replies (RText keeps it outside the plain text)."""
        found = []

        def flatten(node, parts):
            if isinstance(node, str):
                parts.append(node)
            elif isinstance(node, dict):
                if isinstance(node.get("text"), str):
                    parts.append(node["text"])
                for key, value in node.items():
                    if key != "hoverEvent":
                        flatten(value, parts)
            elif isinstance(node, list):
                for value in node:
                    flatten(value, parts)

        def walk(node):
            if isinstance(node, dict):
                hover = node.get("hoverEvent")
                if isinstance(hover, dict):
                    parts = []
                    flatten(hover.get("contents", hover.get("value")), parts)
                    found.append("".join(parts))
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        for reply in self.replies:
            to_json = getattr(reply, "to_json_object", None)
            if callable(to_json):
                walk(to_json())
        return found


class FakeParam:
    def __init__(self, *, model_id="penguin", model="upstream-1", label="<Penguin>",
                 window=1_048_576, estimate=100, round_prompt=10, round_max_total=20,
                 total_prompt=1_000, total_completion=100, total_cached=500,
                 total_reasoning=50, broken=False):
        self._usage = {
            "model_id": model_id, "model": model, "label": label, "window": window,
            "estimate": estimate, "round_prompt": round_prompt,
            "round_max_total": round_max_total, "total_prompt": total_prompt,
            "total_completion": total_completion, "total_cached": total_cached,
            "total_reasoning": total_reasoning,
        }
        self.broken = broken

    def context_usage(self):
        if self.broken:
            raise RuntimeError("this conversation cannot be read")
        return dict(self._usage)


@pytest.fixture
def conversations(monkeypatch):
    params = {}
    monkeypatch.setattr(games_ai, "all_chat_param", params, raising=False)
    return params


@pytest.fixture
def capture():
    server = FakeServer()
    capture = LogCapture()
    server.logger.addHandler(capture)
    server.logger.setLevel(logging.DEBUG)
    try:
        yield server, capture
    finally:
        server.logger.removeHandler(capture)
        server.logger.setLevel(logging.NOTSET)


def test_two_configurations_sharing_one_upstream_model_are_two_rows(conversations):
    conversations["penguin-a"] = FakeParam(model_id="penguin", label="<Penguin>", estimate=100)
    conversations["penguin-b"] = FakeParam(model_id="penguin", label="<Penguin>", estimate=200)
    conversations["coco"] = FakeParam(model_id="coco", label="<Coco>", estimate=50,
                                      model="upstream-1")

    models, totals, broken = games_ai.aggregate_context_usage()

    assert broken == []
    assert len(models) == 2, f"two configured AIs are two rows: {[(g['model_id'], g['label']) for g in models]}"
    assert totals["models"] == 2, "the header counts configured AIs"
    assert totals["players"] == 3
    by_id = {group["model_id"]: group for group in models}
    assert set(by_id) == {"penguin", "coco"}, f"groups by all_ai id: {set(by_id)}"
    assert by_id["penguin"]["players"] == 2 and by_id["penguin"]["estimate"] == 300, \
        "players of one configured AI stay together"
    assert by_id["coco"]["players"] == 1
    assert by_id["coco"]["models"] == {"upstream-1"}, "the upstream model travels for the hover"


def test_the_group_window_is_the_smallest_of_its_players(conversations):
    conversations["one"] = FakeParam(model_id="penguin", window=1_048_576)
    conversations["two"] = FakeParam(model_id="penguin", window=131_072)

    models, _totals, _broken = games_ai.aggregate_context_usage()

    assert len(models) == 1 and models[0]["window"] == 131_072, \
        f"the honest denominator is the smallest window in the group: {models}"


def test_a_zero_usage_configuration_is_not_a_row(conversations):
    conversations["active"] = FakeParam(model_id="penguin")
    conversations["idle"] = FakeParam(model_id="coco", estimate=0, round_prompt=0,
                                      round_max_total=0, total_prompt=0,
                                      total_completion=0)

    models, totals, _broken = games_ai.aggregate_context_usage()

    assert [group["model_id"] for group in models] == ["penguin"]
    assert totals["models"] == 1, "an unused configured AI is hidden"


def test_an_unreadable_conversation_is_reported_and_does_not_hide_the_rest(conversations, capture):
    conversations["good"] = FakeParam(model_id="penguin")
    conversations["bad"] = FakeParam(model_id="coco", broken=True)
    server, capture = capture
    source = FakeSource(server)

    games_ai.ask_context_server(source)

    assert any("could not be read" in line and "bad" in line for line in capture.warnings()), \
        f"the unreadable conversation is named in the log: {capture.warnings()}"
    text = source.text()
    assert "SERVER(1 players, 1 models)" in text, f"the readable conversation is still counted: {text}"
    assert "<Penguin>" in text and "<Coco>" not in text, \
        f"only the configured AI that could be read is shown: {text}"


def test_the_upstream_model_is_only_in_the_hover(conversations, capture):
    conversations["a"] = FakeParam(model_id="penguin", label="<Penguin>", model="upstream-x")
    server, _capture = capture
    source = FakeSource(server)

    games_ai.ask_context_server(source)

    text = source.text()
    line = next(part for part in text.splitlines() if "<Penguin>" in part)
    assert "upstream-x" not in line, f"the row is the configured AI, not the upstream model: {line}"
    hovers = source.hovers()
    assert any("AI penguin upstream upstream-x" in hover for hover in hovers), \
        f"the hover carries the configured id and the upstream model: {hovers}"


def test_context_usage_reports_the_configured_entry_and_the_upstream_model():
    from games_ai.ai.chat_param import ChatParam

    param = ChatParam.__new__(ChatParam)
    param._ctx_lock = threading.RLock()
    param.model_id = "coco"
    param.ai_info = {"ai_model": "upstream-model", "ai_name": "<Coco>"}
    param.response_list = []
    param._last_estimate = 42
    param._round_prompt_tokens = 1
    param._round_max_total_tokens = 2
    param._total_prompt_tokens = 3
    param._total_completion_tokens = 4
    param._total_cached_tokens = 5
    param._total_reasoning_tokens = 6
    param.context_window = lambda: 1000
    param._split_rounds_locked = lambda: ([], [])

    usage = param.context_usage()

    assert usage["model_id"] == "coco", "the configured AI entry is reported"
    assert usage["model"] == "upstream-model", "the upstream model is reported separately"
    assert usage["label"] == "<Coco>"


def _row_plain_texts(source):
    rows = []
    for reply in source.replies:
        to_plain = getattr(reply, "to_plain_text", None)
        if callable(to_plain):
            rows.append(to_plain())
    return rows


def test_a_colored_ai_name_keeps_its_color_but_does_not_bleed_into_the_row(conversations, capture):
    """``ai_name`` may contain § codes; they used to leave everything after the name white."""
    conversations["penguin"] = FakeParam(model_id="penguin", label="<§bPenguin§r>")
    server, _capture = capture
    source = FakeSource(server)

    games_ai.ask_context_server(source)

    plain = next(text for text in _row_plain_texts(source) if "Penguin" in text)
    assert "<§bPenguin§r>§r§7" in plain, \
        f"the configured name keeps its codes and the row color is re-asserted after it: {plain!r}"
    assert "§r§7 · 1 player" in plain, \
        f"the rest of the row is gray again, not default white: {plain!r}"


def test_a_plain_ai_name_row_is_not_touched(conversations, capture):
    conversations["penguin"] = FakeParam(model_id="penguin", label="<Penguin>")
    server, _capture = capture
    source = FakeSource(server)

    games_ai.ask_context_server(source)

    plain = next(text for text in _row_plain_texts(source) if "<Penguin>" in text)
    assert "§" not in plain, \
        f"a name without formatting codes gets no injected codes: {plain!r}"
