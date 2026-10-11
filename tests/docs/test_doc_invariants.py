"""Doc invariants: encoding/line endings + trilingual structural parity + probe tokens + the
plugin imports the pages hand out.

Read-only: one test per invariant, and a failure names the offending file (and line).
"""
import ast
import importlib
import os
import re

import pytest

from _helpers.paths import REPO_ROOT
from _helpers.pkg import module_file

LANGS = ("en_us", "zh_cn", "zh_tw")
README = {"en_us": "README.md", "zh_cn": "README.zh-CN.md", "zh_tw": "README.zh-TW.md"}

# Tokens the probe suite greps for.
TOKENS = {
    "cross-server.md": ("hello", "hello_ack", "message", "reply", "event", "4000", "4001",
                        "4002", "4003", "4004", "4005", "min(", "permission.yml"),
    "pim.md": ("sha256", "ghfast.top", "requirements.txt", "[deps]", "reload_plugin"),
}


def _rel(path):
    return os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")


def _read(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def _hygiene(path):
    """BOM, CRLF, missing final newline, trailing whitespace, unbalanced fences -- as before."""
    with open(path, "rb") as handle:
        raw = handle.read()
    problems = []
    if raw.startswith(b"\xef\xbb\xbf"):
        problems.append(f"{_rel(path)}: BOM")
    if b"\r\n" in raw:
        problems.append(f"{_rel(path)}: CRLF")
    text = raw.decode("utf-8")
    if not text.endswith("\n"):
        problems.append(f"{_rel(path)}: no final newline")
    for i, line in enumerate(text.splitlines(), 1):
        if line != line.rstrip():
            problems.append(f"{_rel(path)}:{i}: trailing whitespace")
    if text.count("```") % 2:
        problems.append(f"{_rel(path)}: unbalanced code fences")
    return problems


def _headings(text):
    return [line for line in text.splitlines() if line.startswith("#")]


def _docs_paths():
    for lang in LANGS:
        folder = os.path.join(REPO_ROOT, "docs", lang)
        for name in sorted(os.listdir(folder)):
            if name.endswith(".md"):
                yield os.path.join(folder, name)


@pytest.fixture(scope="module")
def docs():
    """Every docs/<lang>/*.md page as text, keyed by language."""
    pages = {}
    for lang in LANGS:
        folder = os.path.join(REPO_ROOT, "docs", lang)
        pages[lang] = {name: _read(os.path.join(folder, name))
                       for name in sorted(os.listdir(folder)) if name.endswith(".md")}
    return pages


@pytest.fixture(scope="module")
def readmes():
    """The three READMEs as text, keyed by language."""
    return {lang: _read(os.path.join(REPO_ROOT, README[lang])) for lang in LANGS}


def test_docs_pages_are_well_formed():
    problems = [problem for path in _docs_paths() for problem in _hygiene(path)]

    assert not problems, f"docs pages keep encoding, line endings and fences: {problems}"


def test_readmes_are_well_formed():
    problems = [problem for lang in LANGS
                for problem in _hygiene(os.path.join(REPO_ROOT, README[lang]))]

    assert not problems, f"READMEs keep encoding, line endings and fences: {problems}"


def test_the_three_languages_document_the_same_pages(docs):
    sets = {lang: set(docs[lang]) for lang in LANGS}

    assert len({frozenset(s) for s in sets.values()}) == 1, \
        f"page sets differ: {[sorted(s) for s in sets.values()]}"


def test_heading_shapes_match_per_page(docs):
    problems = []
    for page in sorted(docs["en_us"]):
        reference = None
        for lang in LANGS:
            text = docs[lang].get(page)
            if text is None:
                continue
            shape = [len(h) - len(h.lstrip("#")) for h in _headings(text)]
            if reference is None:
                reference = (lang, shape)
            elif shape != reference[1]:
                problems.append(f"{page}: heading shape {lang}={shape} != {reference[0]}={reference[1]}")

    assert not problems, f"heading structure parity per page: {problems}"


def test_docs_links_resolve(docs):
    problems = []
    for lang in LANGS:
        for page, text in docs[lang].items():
            for target in re.findall(r"\]\((?!https?:|#)([^)]+)\)", text):
                path = target.split("#")[0]
                if not path:
                    continue
                resolved = os.path.normpath(os.path.join(REPO_ROOT, "docs", lang, path))
                if not os.path.exists(resolved):
                    problems.append(f"docs/{lang}/{page}: broken link {target}")

    assert not problems, f"every relative link inside docs/ resolves: {problems}"


def test_readme_links_resolve(readmes):
    problems = []
    for lang in LANGS:
        for target in re.findall(r"\]\((?!https?:|#)([^)]+)\)", readmes[lang]):
            path = target.split("#")[0]
            if not path or path.startswith("/"):     # site-root links are for GitHub's UI
                continue
            if not os.path.exists(os.path.normpath(os.path.join(REPO_ROOT, path))):
                problems.append(f"{README[lang]}: broken link {target}")

    assert not problems, f"every relative link in the READMEs resolves: {problems}"


@pytest.mark.parametrize("lang", LANGS)
def test_the_welcome_note_keeps_its_version_and_link(readmes, lang):
    lines = readmes[lang].splitlines()
    note = lines[16] if len(lines) > 16 else ""
    problems = []
    if "0.8.0" not in note:
        problems.append(f"{README[lang]}: line 17 lost its version note")
    if f"docs/{lang}/cross-server.md" not in note:
        problems.append(f"{README[lang]}: line 17 lost its cross-server link")

    assert not problems, f"the welcome note names the release and its own doc: {problems}"


@pytest.mark.parametrize("lang", LANGS)
def test_the_release_version_stays_in_the_welcome_note(readmes, lang):
    # The welcome note is the only place a release version may appear; the rest of the README
    # describes the current code without naming a version (dependency versions stay allowed).
    lines = readmes[lang].splitlines()
    body = "\n".join(lines[:16] + lines[17:])
    stale = [needle for needle in ("0.8.0", "0.8.0-SNAPSHOT-9", "0.7.3", "0.7.x", "0.7.0", "SNAPSHOT")
             if needle in body]

    assert not stale, f"{README[lang]}: release version outside the welcome note: {stale}"


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("page", sorted(TOKENS))
def test_the_probe_tokens_are_all_present(docs, lang, page):
    missing = [needle for needle in TOKENS[page] if needle not in docs[lang].get(page, "")]

    assert not missing, f"docs/{lang}/{page}: missing probe tokens {missing}"


# --------------------------------------------------------------- the plugin imports the pages show

# A page that is not history is read as instructions: a line copied out of it has to work. The
# changelog is the one page that may quote a path that was right when it was written.
HISTORY_PAGE = "changelog.md"

FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
SPAN = re.compile(r"`([^`\n]+)`")
IMPORT_TEXT = re.compile(r"\b(?:from|import)\s+(games_ai(?:\.[A-Za-z_][A-Za-z0-9_]*)*)")


def _module_paths(text):
    """Every ``games_ai`` module path the page names after ``from`` or ``import``, with its line.

    This reads the page as text, so it also covers a snippet that does not parse -- an example
    with a ``...`` placeholder still shows plainly which module it imports, and that is the part
    a reader copies.
    """
    found = {}
    for match in IMPORT_TEXT.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        found.setdefault(match.group(1), line)
    return found


def _parsed_imports(text):
    """The ``games_ai`` imports of every snippet that is really Python, as ``(module, names)``.

    Fenced blocks and inline code spans are parsed; a snippet the parser rejects (a shell line,
    prose that happens to sit in a fence, an example with placeholders) is left to the text pass.
    """
    out = []
    for snippet in FENCE.findall(text) + SPAN.findall(text):
        try:
            tree = ast.parse(snippet)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and not node.level \
                    and (node.module or "").startswith("games_ai"):
                out.append((node.module, [alias.name for alias in node.names]))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("games_ai"):
                        out.append((alias.name, []))
    return out


def test_every_plugin_import_the_pages_show_resolves(docs, readmes):
    """The guides have to name modules and names that exist -- module *and* symbol.

    The modules moved from ``games_ai/`` into the subpackages, and the guides kept the flat
    imports for a while: ``from games_ai.games_ai_tool import register_tool`` raises
    ModuleNotFoundError, and for a custom ``tools.py`` that means the whole file fails to load
    and **no** tool of it registers. Checking the symbol as well catches a rename the same way.
    """
    sources = [(f"docs/{lang}/{page}", docs[lang][page])
               for lang in LANGS for page in sorted(docs[lang]) if page != HISTORY_PAGE]
    skills = os.path.join(REPO_ROOT, "skills")
    sources += [(f"skills/{name}", _read(os.path.join(skills, name)))
                for name in sorted(os.listdir(skills)) if name.endswith(".md")]
    sources += [(README[lang], readmes[lang]) for lang in LANGS]

    problems = []
    for label, text in sources:
        lines = _module_paths(text)
        wanted = {module: set() for module in lines}
        for module, names in _parsed_imports(text):
            wanted.setdefault(module, set()).update(names)
        for module, names in sorted(wanted.items()):
            where = f"{label}:{lines[module]}" if module in lines else label
            if module_file(module) is None:
                problems.append(f"{where}: {module} is not a module of the package")
                continue
            try:
                package = importlib.import_module(module)
            except ImportError as error:
                problems.append(f"{where}: {module} cannot be imported ({error})")
                continue
            missing = sorted(name for name in names if name != "*" and not hasattr(package, name))
            if missing:
                problems.append(f"{where}: {module} has no {', '.join(missing)}")

    assert not problems, f"every games_ai import the pages show resolves: {problems}"
