"""The docs' house-format layout conventions, verified (read-only).

This module used to *finish* the house-format pass as well: it rewrote the stale
troubleshooting row and the changelog claim in place. That migration has landed -- the pages
below are what it produced -- so only the verification half is left, and it never writes.
"""
import os
import re

import pytest

from _helpers.paths import REPO_ROOT

LANGS = {
    "zh_cn": ("# 跨服连接", "[返回 README](../../README.zh-CN.md)", "简体中文"),
    "en_us": ("# Cross-server Linking", "[Back to README](../../README.md)", "English"),
    "zh_tw": ("# 跨服連線", "[返回 README](../../README.zh-TW.md)", "繁體中文"),
}


def _docs_path(lang, name):
    return os.path.join(REPO_ROOT, "docs", lang, name)


def _read(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


@pytest.fixture(scope="module")
def cross_server_lines():
    return {lang: _read(_docs_path(lang, "cross-server.md")).splitlines() for lang in LANGS}


@pytest.fixture(scope="module")
def configuration():
    return {lang: _read(_docs_path(lang, "configuration.md")) for lang in LANGS}


@pytest.fixture(scope="module")
def mineflayer_bot():
    return {lang: _read(_docs_path(lang, "mineflayer-bot.md")) for lang in LANGS}


@pytest.fixture(scope="module")
def troubleshooting():
    return {lang: _read(_docs_path(lang, "troubleshooting.md")) for lang in LANGS}


@pytest.mark.parametrize("lang", list(LANGS))
def test_cross_server_opens_with_the_centred_div(cross_server_lines, lang):
    lines = cross_server_lines[lang]

    assert lines[0] == '<div align="center">', f"{lang}: opens with the centred div: {lines[0]}"


@pytest.mark.parametrize("lang", list(LANGS))
def test_cross_server_title_sits_on_line_three(cross_server_lines, lang):
    lines = cross_server_lines[lang]

    assert lines[2] == LANGS[lang][0], f"{lang}: title on line 3: {lines[2]}"


@pytest.mark.parametrize("lang", list(LANGS))
def test_cross_server_switcher_links_both_other_languages(cross_server_lines, lang):
    switcher = cross_server_lines[lang][4]
    others = [other for other in LANGS if other != lang]

    assert all(f"../{other}/cross-server.md" in switcher for other in others), \
        f"{lang}: language switcher links both other languages: {switcher}"


@pytest.mark.parametrize("lang", list(LANGS))
def test_cross_server_switcher_keeps_the_current_language_as_plain_text(cross_server_lines, lang):
    switcher = cross_server_lines[lang][4]

    assert switcher.count("](") == 2, \
        f"{lang}: the current language is plain text in the switcher: {switcher}"


@pytest.mark.parametrize("lang", list(LANGS))
def test_cross_server_has_a_back_to_readme_line(cross_server_lines, lang):
    lines = cross_server_lines[lang]

    assert lines[6] == LANGS[lang][1], f"{lang}: back-to-README line: {lines[6]}"


@pytest.mark.parametrize("lang", list(LANGS))
def test_cross_server_closes_the_centred_div(cross_server_lines, lang):
    lines = cross_server_lines[lang]

    assert lines[8] == "</div>", f"{lang}: the div closes: {lines[8]}"


@pytest.mark.parametrize("lang", list(LANGS))
def test_cross_server_intro_paragraph_follows_the_header(cross_server_lines, lang):
    lines = cross_server_lines[lang]

    assert lines[9] == "" and lines[10].strip() != "" and not lines[10].startswith("#"), \
        f"{lang}: intro paragraph follows the header: {lines[10][:40]}"


@pytest.mark.parametrize("lang", list(LANGS))
def test_cross_server_has_no_horizontal_rules(cross_server_lines, lang):
    lines = cross_server_lines[lang]

    assert not any(line.strip() == "---" for line in lines), f"{lang}: no horizontal rules"


@pytest.mark.parametrize("lang", list(LANGS))
def test_cross_server_headings_are_unnumbered(cross_server_lines, lang):
    headings = [line for line in cross_server_lines[lang] if line.startswith("## ")]

    assert all(not re.match(r"^## \d", heading) for heading in headings), \
        f"{lang}: headings are unnumbered: {headings[:3]}"


@pytest.mark.parametrize("lang", list(LANGS))
def test_cross_server_table_cells_are_unpadded(cross_server_lines, lang):
    lines = cross_server_lines[lang]
    tables = [line for line in lines
              if line.startswith("|") and not re.match(r"^\|[\s:|-]+\|\s*$", line)]

    assert all(line == "|" + "|".join(cell.strip() for cell in line.strip().strip("|").split("|")) + "|"
               for line in tables), f"{lang}: table cells are unpadded: {tables[:2]}"


@pytest.mark.parametrize("lang", list(LANGS))
def test_cross_server_notes_use_the_github_callout(cross_server_lines, lang):
    lines = cross_server_lines[lang]

    assert (any(line.strip() == "> [!NOTE]" for line in lines)
            and not any(line.startswith("> 注意：") for line in lines)), \
        f"{lang}: notes use the GitHub callout"


@pytest.mark.parametrize("lang", list(LANGS))
def test_configuration_documents_the_websocket_section(configuration, lang):
    cfg = configuration[lang]

    assert "## 6.websocket" in cfg and "websocket.uri" in cfg, \
        f"{lang}: configuration.md documents websocket"


@pytest.mark.parametrize("lang", list(LANGS))
def test_mineflayer_bot_drops_the_removed_block(mineflayer_bot, lang):
    bot = mineflayer_bot[lang]

    assert "mineflayer_bot.websocket`" not in bot, \
        f"{lang}: mineflayer-bot.md no longer documents the removed block"


@pytest.mark.parametrize("lang", list(LANGS))
def test_mineflayer_bot_points_at_the_cluster_address(mineflayer_bot, lang):
    bot = mineflayer_bot[lang]

    assert "websocket.uri" in bot, f"{lang}: mineflayer-bot.md points at the cluster address"


@pytest.mark.parametrize("lang", list(LANGS))
def test_troubleshooting_drops_the_dead_port_message(troubleshooting, lang):
    trouble = troubleshooting[lang]

    assert "is already in use" not in trouble, \
        f"{lang}: troubleshooting.md drops the dead port message"


@pytest.mark.parametrize("lang", list(LANGS))
def test_troubleshooting_points_at_the_hub(troubleshooting, lang):
    trouble = troubleshooting[lang]

    assert "Registered on hub" in trouble, f"{lang}: troubleshooting.md points at the hub"
