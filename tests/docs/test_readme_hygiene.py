"""Markdown hygiene: tables and code fences must not be glued to neighbouring text (read-only).

Opening/closing fences are checked from outside the block: the line before an opening fence and
the line after a closing fence must be blank (or the file boundary).
"""
import os

import pytest

from _helpers.paths import REPO_ROOT

FILES = ("README.md", "README.zh-CN.md", "README.zh-TW.md")
FENCE = "`" * 3


def _read(name):
    with open(os.path.join(REPO_ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def _scan(lines):
    """Every problem the old script reported, tagged with the class it belongs to.

    ``fence``: a fence glued to the line before it (opening) or after it (closing).
    ``table``: a table row glued to the line before or after it.
    ``fences``: the file ends inside a code block.
    """
    problems = []
    in_code = False
    for index, line in enumerate(lines):
        previous = lines[index - 1] if index else ""
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if line.startswith(FENCE):
            if not in_code:
                if previous.strip():
                    problems.append(("fence", f"{index + 1}: opening fence glued to previous line"))
            elif following.strip():
                problems.append(("fence", f"{index + 1}: closing fence glued to next line"))
            in_code = not in_code
            continue
        if in_code:
            continue
        if line.startswith("|"):
            if previous.strip() and not previous.startswith("|"):
                problems.append(("table", f"{index + 1}: table glued to previous line"))
            if following.strip() and not following.startswith("|"):
                problems.append(("table", f"{index + 1}: table glued to next line"))
    if in_code:
        problems.append(("fences", "unbalanced fences"))
    return problems


@pytest.fixture(scope="module")
def scanned():
    """{name: [(class, problem)]} for the three READMEs, scanned once for the module."""
    return {name: _scan(_read(name).split("\n")) for name in FILES}


def _problems(scanned, name, kind):
    return [f"{name}: {problem}" for problem_kind, problem in scanned[name] if problem_kind == kind]


@pytest.mark.parametrize("name", FILES)
def test_no_fence_is_glued_to_the_text_around_it(scanned, name):
    problems = _problems(scanned, name, "fence")

    assert not problems, f"no code fence is glued to the text around it: {problems}"


@pytest.mark.parametrize("name", FILES)
def test_no_table_is_glued_to_the_text_around_it(scanned, name):
    problems = _problems(scanned, name, "table")

    assert not problems, f"no table is glued to the text around it: {problems}"


@pytest.mark.parametrize("name", FILES)
def test_every_readme_has_balanced_code_fences(scanned, name):
    problems = _problems(scanned, name, "fences")

    assert not problems, f"every README has balanced code fences: {problems}"
