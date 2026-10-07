"""Precise README parity check: real '\n' line counts + per-section content counts (read-only)."""
import os
import re

import pytest

from _helpers.paths import REPO_ROOT

FILES = ("README.md", "README.zh-CN.md", "README.zh-TW.md")
EXOTIC = {"\u2028": "U+2028", "\u2029": "U+2029", "\u0085": "U+0085", "\u000b": "U+000B",
          "\u000c": "U+000C", "\r": "CR"}


def _load(name):
    """One README as (text, exotic separator labels), decoded exactly as the old script did."""
    with open(os.path.join(REPO_ROOT, name), "rb") as handle:
        text = handle.read().decode("utf-8")
    return text, sorted({label for char, label in EXOTIC.items() if char in text})


def _shape(text):
    """The per-section (text, code, bullet, row) counts the three READMEs must share."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    shape = []
    body = []
    in_code = False
    for line in lines:
        if line.startswith("```"):
            in_code = not in_code
            body.append("code")
            continue
        if in_code:
            continue
        if line.startswith("#"):
            shape.append(tuple(body.count(kind) for kind in ("text", "code", "bullet", "row")))
            body = []
            continue
        if re.match(r"^\s*[-*] ", line):
            body.append("bullet")
        elif line.startswith("|") and not re.match(r"^\|[\s:|-]+\|$", line):
            body.append("row")
        elif line.strip():
            body.append("text")
    shape.append(tuple(body.count(kind) for kind in ("text", "code", "bullet", "row")))
    return shape


@pytest.fixture(scope="module")
def readmes():
    return {name: _load(name) for name in FILES}


@pytest.mark.parametrize("name", FILES)
def test_every_readme_uses_only_real_line_breaks(readmes, name):
    exotic = readmes[name][1]

    assert not exotic, f"{name}: exotic line separators {exotic}"


@pytest.mark.parametrize("name", FILES[1:])
def test_the_readmes_have_identical_section_shapes(readmes, name):
    reference = _shape(readmes[FILES[0]][0])
    shape = _shape(readmes[name][0])
    problems = []
    for index in range(max(len(reference), len(shape))):
        left = reference[index] if index < len(reference) else None
        right = shape[index] if index < len(shape) else None
        if left != right:
            problems.append(f"{name} section {index}: {right} != en {left}")

    assert not problems, (
        "the three READMEs have identical section shapes "
        f"(text/paragraphs, code blocks, bullets, table rows): {problems}")
