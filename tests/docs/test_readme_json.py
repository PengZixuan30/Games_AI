"""Validate every ```json block in the three READMEs (read-only)."""
import json
import os
import re

import pytest

from _helpers.paths import REPO_ROOT

FILES = ("README.md", "README.zh-CN.md", "README.zh-TW.md")


def _read(name):
    with open(os.path.join(REPO_ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def _json_blocks(name):
    return re.findall(r"```json\r?\n(.*?)```", _read(name), re.S)


@pytest.mark.parametrize("name", FILES)
def test_every_readme_has_a_json_block(name):
    blocks = _json_blocks(name)

    assert blocks, f"{name}: no json block found"


@pytest.mark.parametrize("name", FILES)
def test_every_readme_json_block_parses(name):
    problems = []
    for index, block in enumerate(_json_blocks(name), 1):
        try:
            json.loads(block)
        except Exception as error:
            problems.append(f"{name} block {index}: {error}")

    assert not problems, f"{name}: json blocks do not parse: {problems}"
