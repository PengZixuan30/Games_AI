"""Structural parity/validity checks for the doc set (read-only, separate from doc_invariants).

1. Markdown tables must have a consistent number of cells in every row of a table.
2. Bullet and table-row counts per heading must match across en_us / zh_cn / zh_tw.
3. No list item number may repeat inside one ordered list (catches the duplicated "6." steps).
4. Every heading anchor referenced from anywhere in docs/ + READMEs must exist.
"""
import os
import re

import pytest

from _helpers.paths import REPO_ROOT

LANGS = ("en_us", "zh_cn", "zh_tw")
README = {"en_us": "README.md", "zh_cn": "README.zh-CN.md", "zh_tw": "README.zh-TW.md"}


def _read(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def _sections(text):
    """Split into (heading, body) pairs; the preamble is under the '' heading."""
    out = []
    heading = ""
    body = []
    for line in text.splitlines():
        if line.startswith("#"):
            out.append((heading, body))
            heading = line
            body = []
        else:
            body.append(line)
    out.append((heading, body))
    return [(h, b) for h, b in out if h or any(x.strip() for x in b)]


def _counts(body):
    bullets = sum(1 for l in body if re.match(r"^\s*[-*] ", l))
    rows = sum(1 for l in body if l.startswith("|") and not re.match(r"^\|[\s:|-]+\|$", l))
    return bullets, rows


def _slugs(text):
    out = set()
    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if match:
            title = match.group(2).strip().lower()
            title = re.sub(r"[^\w\u4e00-\u9fff\- ]", "", title)
            out.add(title.replace(" ", "-"))
    return out


@pytest.fixture(scope="module")
def docs():
    """Every docs/<lang>/*.md page as text, keyed by language and page."""
    pages = {lang: {} for lang in LANGS}
    for lang in LANGS:
        folder = os.path.join(REPO_ROOT, "docs", lang)
        for name in sorted(os.listdir(folder)):
            if name.endswith(".md"):
                pages[lang][name] = _read(os.path.join(folder, name))
    return pages


@pytest.fixture(scope="module")
def anchor_index(docs):
    """The heading slugs every page and README offers: {(lang, file): slugs}."""
    index = {}
    for lang in LANGS:
        for name, text in docs[lang].items():
            index[(lang, name)] = _slugs(text)
        index[(lang, README[lang])] = _slugs(_read(os.path.join(REPO_ROOT, README[lang])))
    return index


def test_every_table_row_has_a_consistent_cell_count(docs):
    problems = []
    for lang in LANGS:
        for name, text in docs[lang].items():
            lines = text.splitlines()
            i = 0
            while i < len(lines):
                if lines[i].startswith("|"):
                    block = []
                    while i < len(lines) and lines[i].startswith("|"):
                        block.append((i + 1, lines[i]))
                        i += 1
                    widths = {}
                    for number, line in block:
                        if re.match(r"^\|[\s:|-]+\|$", line):
                            continue
                        widths.setdefault(line.count("|"), []).append(number)
                    if len(widths) > 1:
                        problems.append(f"docs/{lang}/{name}: table lines {sorted(widths)} "
                                        f"have different cell counts {sorted(widths)}")
                else:
                    i += 1

    assert not problems, f"every table row has a consistent number of cells: {problems}"


def test_bullet_and_table_row_counts_match_across_languages(docs):
    problems = []
    for name in sorted(docs["en_us"]):
        shapes = {}
        for lang in LANGS:
            text = docs[lang].get(name)
            if text is None:
                continue
            shapes[lang] = [_counts(body) for _, body in _sections(text)]
        reference = shapes.get("en_us")
        for lang in LANGS:
            if lang == "en_us" or lang not in shapes:
                continue
            if shapes[lang] != reference:
                diff = [(i, reference[i] if i < len(reference) else None, shapes[lang][i])
                        for i in range(max(len(reference), len(shapes[lang])))
                        if i >= len(reference) or i >= len(shapes[lang]) or reference[i] != shapes[lang][i]]
                problems.append(f"{name}: bullet/row counts differ in {lang}: {diff}")

    assert not problems, f"bullet and table-row counts per heading match across languages: {problems}"


def test_no_ordered_list_marker_repeats_inside_one_list(docs):
    problems = []
    for lang in LANGS:
        for name, text in docs[lang].items():
            last = None
            for number, line in enumerate(text.splitlines(), 1):
                match = re.match(r"^(\d+)\.\s", line)
                if match:
                    marker = int(match.group(1))
                    if last is not None and marker == last:
                        problems.append(f"docs/{lang}/{name}:{number}: list marker {marker} repeats")
                    last = marker
                elif line.strip():
                    last = None

    assert not problems, f"no ordered list repeats a number inside one list: {problems}"


def test_every_referenced_heading_anchor_exists(docs, anchor_index):
    problems = []
    for lang in LANGS:
        files = dict(docs[lang])
        files[README[lang]] = _read(os.path.join(REPO_ROOT, README[lang]))
        for name, text in files.items():
            for target in re.findall(r"\]\((?!https?:)([^)]+)\)", text):
                if "#" not in target:
                    continue
                path, anchor = target.split("#", 1)
                path = path or name
                if path.startswith("/"):
                    continue
                key = (lang, os.path.basename(path))
                if key not in anchor_index:
                    continue
                if anchor.lower() not in anchor_index[key]:
                    problems.append(f"docs/{lang}/{name}: anchor #{anchor} not found in {path}")

    assert not problems, f"every referenced heading anchor exists: {problems}"
