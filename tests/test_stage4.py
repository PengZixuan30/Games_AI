"""Stage-4 verification: versions, i18n keys, changelogs, README notes, docs structure."""
import io
import json
import os
import re

import pytest

from _helpers.paths import REPO_ROOT
from _helpers.pkg import package_text

LANGS = ("zh_cn", "zh_tw", "en_us")
README_NOTES = {
    "README.md": ("0.8.0", "docs/en_us/cross-server.md"),
    "README.zh-CN.md": ("0.8.0", "docs/zh_cn/cross-server.md"),
    "README.zh-TW.md": ("0.8.0", "docs/zh_tw/cross-server.md"),
}
STALE_VERSIONS = ("0.8.0", "0.8.0-SNAPSHOT-9", "0.7.3", "0.7.x", "0.7.0", "SNAPSHOT")
EXPECTED_PAGES = {"ai-request-pipeline.md", "changelog.md", "configuration.md", "cross-server.md",
                  "example.md", "hot-reload.md", "mineflayer-bot.md", "pim.md", "skills.md",
                  "testing.md", "tools.md", "troubleshooting.md"}


def _read(path, newline=""):
    with io.open(path, "r", encoding="utf-8", newline=newline) as handle:
        return handle.read()


def _lang_path(lang):
    return os.path.join(REPO_ROOT, "lang", f"{lang}.yml")


def _docs_path(lang, name):
    return os.path.join(REPO_ROOT, "docs", lang, name)


def _version_section(text, version, until):
    return text.split(f"## Version {version}", 1)[1].split(f"## Version {until}", 1)[0]


@pytest.fixture(scope="module")
def manifest():
    return json.loads(_read(os.path.join(REPO_ROOT, "mcdreforged.plugin.json")))


@pytest.fixture(scope="module")
def lang_files():
    """Each language file exactly as it sits on disk, line endings included."""
    return {lang: _read(_lang_path(lang)) for lang in LANGS}


@pytest.fixture(scope="module")
def parsed_languages(lang_files):
    """The language files parsed; only the checks that need YAML depend on this."""
    yaml = pytest.importorskip("yaml", reason="the language files are checked as YAML")
    return {lang: yaml.safe_load(text) for lang, text in lang_files.items()}


@pytest.fixture(scope="module")
def changelogs():
    return {lang: _read(_docs_path(lang, "changelog.md")) for lang in LANGS}


@pytest.fixture(scope="module")
def module_sizes():
    """The line counts the changelog's internal-structure notes quote.

    They are facts about the current tree and must not drift away from it (they did once:
    "4060 lines" survived two changes).
    """
    return {"help.py": len(_read(os.path.join(REPO_ROOT, "games_ai", "help.py")).splitlines()),
            "__init__.py": len(_read(os.path.join(REPO_ROOT, "games_ai", "__init__.py")).splitlines())}


@pytest.fixture(scope="module")
def readme_lines():
    return {name: _read(os.path.join(REPO_ROOT, name)).splitlines() for name in README_NOTES}


@pytest.fixture(scope="module")
def doc_pages():
    return {lang: sorted(name for name in os.listdir(os.path.join(REPO_ROOT, "docs", lang))
                         if name.endswith(".md"))
            for lang in LANGS}


@pytest.fixture(scope="module")
def cross_server():
    return {lang: _read(_docs_path(lang, "cross-server.md")) for lang in LANGS}


@pytest.fixture(scope="module")
def pim():
    return {lang: _read(_docs_path(lang, "pim.md")) for lang in LANGS}


def test_plugin_json_is_0_8_0(manifest):
    assert manifest["version"].startswith("0.8.0"), \
        f"plugin.json is 0.8.0 (any snapshot suffix allowed): {manifest['version']}"


def test_plugin_metadata_is_0_8_0():
    init_src = _read(os.path.join(REPO_ROOT, "games_ai", "__init__.py"))

    assert '"version": "0.8.0' in init_src, "PLUGIN_METADATA is 0.8.0"


def test_mcdr_parses_the_metadata_as_0_8_0(manifest):
    from mcdreforged.plugin.meta.metadata import Metadata

    metadata = Metadata(manifest)

    assert str(metadata.version).startswith("0.8.0"), \
        f"MCDR parses the metadata as 0.8.0: {metadata.version}"


@pytest.mark.parametrize("lang", LANGS)
def test_language_files_keep_consistent_line_endings(lang_files, lang):
    # The files are CRLF from the first byte to the last. This check used to normalise a mixed
    # file and then look at the copy it had written; that rewrite is gone with the rest of the
    # one-time migration, so a mixed file fails here instead of being quietly fixed.
    raw = lang_files[lang]
    crlf = raw.count("\r\n")
    lone_lf = raw.count("\n") - crlf

    assert lone_lf == 0, f"{lang}: line endings stay consistent: CRLF={crlf} lone-LF={lone_lf}"


@pytest.mark.parametrize("lang", LANGS)
def test_cross_server_unavailable_key_exists(parsed_languages, lang):
    node = parsed_languages[lang].get("games_ai", {}).get("cross_server", {})

    assert node.get("unavailable"), f"{lang}: games_ai.cross_server.unavailable exists: {node}"


@pytest.mark.parametrize("lang", LANGS)
def test_no_permission_key_is_still_there(parsed_languages, lang):
    assert "no_permission" in parsed_languages[lang]["games_ai"], \
        f"{lang}: no_permission is still there"


def test_the_three_languages_expose_the_same_top_level_keys(parsed_languages):
    keys = {lang: set(parsed_languages[lang]["games_ai"]) for lang in LANGS}
    common = set.intersection(*keys.values())

    assert all(key == common for key in keys.values()), \
        ("the three languages expose the same top-level keys: "
         + str({lang: sorted(keys[lang] - common) for lang in LANGS}))


def test_the_new_key_is_a_translated_string(parsed_languages):
    values = [parsed_languages[lang]["games_ai"]["cross_server"]["unavailable"] for lang in LANGS]

    assert len(set(values)) == 3, \
        f"the new key is a translated string, not English everywhere: {values}"


def test_the_code_uses_the_translated_key():
    source = package_text()
    problems = []
    if "games_ai.cross_server.unavailable" not in source:
        problems.append("the translated key is not referenced")
    if "Cross-server link is not available" in source:
        problems.append("the hard-coded English message is still in the package")

    assert not problems, f"_forward_command goes through rtr: {problems}"


@pytest.mark.parametrize("lang", LANGS)
def test_the_0_8_0_changelog_section_comes_first(changelogs, lang):
    versions = re.findall(r"^## Version ([\d.]+)", changelogs[lang], re.M)

    assert versions and versions[0] == "0.8.0", f"{lang}: 0.8.0 section is first: {versions[:3]}"


@pytest.mark.parametrize("lang", LANGS)
def test_the_changelog_keeps_its_history(changelogs, lang):
    versions = re.findall(r"^## Version ([\d.]+)", changelogs[lang], re.M)

    assert "0.7.3" in versions and "0.7.0" in versions, f"{lang}: history kept: {versions}"


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("topic", ("cross-server", "websocket"))
def test_the_0_8_0_section_mentions_each_topic(changelogs, lang, topic):
    section = _version_section(changelogs[lang], "0.8.0", "0.7.3")

    assert topic in section.lower(), f"{lang}: the 0.8.0 section mentions {topic}"


@pytest.mark.parametrize("lang", LANGS)
def test_the_0_8_0_section_links_the_new_doc(changelogs, lang):
    section = _version_section(changelogs[lang], "0.8.0", "0.7.3")

    assert f"{lang}/cross-server.md" in section, f"{lang}: the 0.8.0 section links the new doc"


@pytest.mark.parametrize("lang", LANGS)
def test_the_internal_structure_notes_quote_the_help_module(changelogs, module_sizes, lang):
    unit = "lines" if lang == "en_us" else "行"
    section = changelogs[lang].split("## Version 0.8.0", 1)[1]
    quoted = f"{module_sizes['help.py']} {unit}"

    assert quoted in section, f"{lang}: the internal-structure notes quote help.py as {quoted}"


@pytest.mark.parametrize("lang", LANGS)
def test_the_internal_structure_notes_quote_the_entry_module(changelogs, module_sizes, lang):
    unit = "lines" if lang == "en_us" else "行"
    section = changelogs[lang].split("## Version 0.8.0", 1)[1]
    quoted = f"{module_sizes['__init__.py']} {unit}"

    assert quoted in section, f"{lang}: ...and the entry module as {quoted}"


@pytest.mark.parametrize("name", list(README_NOTES))
def test_readme_line_17_mentions_the_release(readme_lines, name):
    line = readme_lines[name][16]

    assert README_NOTES[name][0] in line, f"{name} line 17 mentions 0.8.0: {line[:60]}"


@pytest.mark.parametrize("name", list(README_NOTES))
def test_readme_line_17_links_its_own_language_doc(readme_lines, name):
    line = readme_lines[name][16]

    assert README_NOTES[name][1] in line, f"{name} line 17 links its own language doc: {line[:80]}"


@pytest.mark.parametrize("name", list(README_NOTES))
def test_the_release_version_stays_in_the_readme_welcome_note(readme_lines, name):
    # The welcome note on line 17 is the only place a release version may appear: the rest of
    # the README describes whatever the current code does.
    lines = readme_lines[name]
    rest = "\n".join(lines[:16] + lines[17:])
    stale = [needle for needle in STALE_VERSIONS if needle in rest]

    assert not stale, f"{name}: the release version stays in the welcome note: {stale}"


def test_docs_and_skills_name_no_release_version():
    # Dependency declarations and API version floors are allowed; the plugin's own release
    # numbers are not (the changelog is the one place that keeps them).
    allowed = (">=0.6.1", ">= 0.6.0")
    release_version = re.compile(r"0\.(?:6\.[0-9]+|7\.[0-9x]+|8\.[0-9]+)|SNAPSHOT")
    targets = [os.path.join("docs", lang, name)
               for lang in LANGS
               for name in sorted(os.listdir(os.path.join(REPO_ROOT, "docs", lang)))
               if name.endswith(".md") and name != "changelog.md"]
    targets += [os.path.join("skills", name)
                for name in sorted(os.listdir(os.path.join(REPO_ROOT, "skills")))
                if name.endswith(".md")]
    offenders = []
    for path in targets:
        for number, line in enumerate(_read(os.path.join(REPO_ROOT, path)).splitlines(), 1):
            if release_version.search(line) and not any(ok in line for ok in allowed):
                offenders.append(f"{path}:{number}")

    assert not offenders, \
        f"docs (changelog aside) and skills name no release version: {offenders[:8]}"


@pytest.mark.parametrize("lang", LANGS)
def test_cross_server_page_was_added(doc_pages, lang):
    assert "cross-server.md" in doc_pages[lang], f"{lang}: cross-server.md added: {doc_pages[lang]}"


@pytest.mark.parametrize("lang", LANGS)
def test_every_language_has_the_same_pages(doc_pages, lang):
    assert set(doc_pages[lang]) == EXPECTED_PAGES, \
        f"{lang}: every language has the same pages: {sorted(set(doc_pages[lang]) ^ EXPECTED_PAGES)}"


@pytest.mark.parametrize("lang", LANGS)
def test_cross_server_is_well_formed(cross_server, lang):
    text = cross_server[lang]
    problems = []
    if not text.endswith("\n"):
        problems.append("no final newline")
    if "\r" in text:
        problems.append("CR found")
    if [i for i, line in enumerate(text.splitlines(), 1) if line != line.rstrip()]:
        problems.append("trailing whitespace")
    if text.count("```") % 2:
        problems.append("unbalanced code fences")
    for target in re.findall(r"\]\((?!https?:)([^)]+)\)", text):
        if not os.path.exists(os.path.join(REPO_ROOT, "docs", lang, target)):
            problems.append("broken link " + target)

    assert not problems, f"{lang}: cross-server.md is well formed: {problems}"


@pytest.mark.parametrize("lang", LANGS)
def test_cross_server_documents_the_protocol_frames(cross_server, lang):
    missing = [frame for frame in ("hello", "hello_ack", "message", "reply", "event")
               if frame not in cross_server[lang]]

    assert not missing, f"{lang}: documents the protocol frames: missing {missing}"


@pytest.mark.parametrize("lang", LANGS)
def test_cross_server_documents_every_close_code(cross_server, lang):
    missing = [code for code in ("4000", "4001", "4002", "4003", "4004", "4005")
               if code not in cross_server[lang]]

    assert not missing, f"{lang}: documents every close code: missing {missing}"


@pytest.mark.parametrize("lang", LANGS)
def test_cross_server_documents_the_three_command_classes(cross_server, lang):
    missing = [class_ for class_ in ("A", "B", "C") if class_ not in cross_server[lang]]

    assert not missing, f"{lang}: documents the three command classes: missing {missing}"


@pytest.mark.parametrize("lang", LANGS)
def test_cross_server_documents_the_permission_rule(cross_server, lang):
    text = cross_server[lang]
    problems = []
    if "min(" not in text:
        problems.append("the min( permission rule is not spelled out")
    if "permission.yml" not in text:
        problems.append("permission.yml is not named")

    assert not problems, f"{lang}: documents the permission rule: {problems}"


@pytest.mark.parametrize("lang", LANGS)
def test_pim_is_well_formed(pim, lang):
    text = pim[lang]
    problems = []
    if not text.endswith("\n"):
        problems.append("no final newline")
    if "\r" in text:
        problems.append("CR found")
    if [i for i, line in enumerate(text.splitlines(), 1) if line != line.rstrip()]:
        problems.append("trailing whitespace")
    if text.count("```") % 2:
        problems.append("unbalanced code fences")
    for target in re.findall(r"\]\((?!https?:)([^)]+)\)", text):
        if not os.path.exists(os.path.join(REPO_ROOT, "docs", lang, target.split("#")[0])):
            problems.append("broken link " + target)

    assert not problems, f"{lang}: pim.md is well formed: {problems}"


@pytest.mark.parametrize("lang", LANGS)
def test_pim_covers_both_mechanisms(pim, lang):
    missing = [token for token in ("sha256", "ghfast.top", "requirements.txt", "[deps]",
                                   "reload_plugin") if token not in pim[lang]]

    assert not missing, f"{lang}: pim.md covers both mechanisms: missing {missing}"
