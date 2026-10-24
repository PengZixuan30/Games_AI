"""Skill tools may only touch one flat file inside this instance's skills folder.

The tool arguments are model-generated, so a name like ``../config.json`` or an absolute path used
to let a skill edit read, overwrite or delete files outside the skills folder. Every skill tool now
validates the name first and answers the model with an error instead of touching the file system.
"""
import json
import os
import logging
from types import SimpleNamespace

import pytest

from games_ai.ai import games_ai_tool
from games_ai.core.config import plugin_config


class FakeServer:
    def __init__(self):
        self.logger = logging.getLogger("skill-path-server")

    def rtr(self, key, **kwargs):
        return key


class FakeSource:
    def __init__(self, server):
        self.server = server
        self.received = []

    def get_server(self):
        return self.server

    def get_permission_level(self):
        return 4

    def get_info(self):
        return SimpleNamespace(content="")

    @property
    def player(self):
        return "Steve"

    @property
    def is_player(self):
        return True

    @property
    def is_console(self):
        return False

    def reply(self, message, **kwargs):
        self.received.append(str(message))

    def text(self):
        return "\n".join(self.received)


@pytest.fixture
def skills(tmp_path, monkeypatch):
    folder = tmp_path / "games_ai"
    folder.mkdir()
    (folder / "skills").mkdir()
    index = folder / "skills" / "skills.json"
    index.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(plugin_config, "prefix", "[GamesAI]")
    monkeypatch.setattr(plugin_config, "skills_path", str(index))
    monkeypatch.setattr(plugin_config, "builtin_skills_dir", str(tmp_path / "builtin"))
    monkeypatch.setattr(plugin_config, "allow_permission", 3)
    # The external library is not part of this test; the path checks come after it.
    monkeypatch.setattr(games_ai_tool, "read_external_skills", lambda name: None)
    return SimpleNamespace(folder=folder, skills_dir=folder / "skills", source=FakeSource(FakeServer()))


BAD_NAMES = ("../escape", "..\\escape", "sub/dir", "sub\\dir", "..", ".", "")


@pytest.mark.parametrize("bad", BAD_NAMES)
def test_every_skill_tool_refuses_a_name_outside_the_folder(skills, bad):
    source = skills.source
    outside = skills.folder / "escape.md"
    outside.write_text("do not touch", encoding="utf-8")

    write = games_ai_tool.write_skills(source, "", bad, "summary", "owned")
    modify = games_ai_tool.modify_skills(source, "", bad, "do not touch", "owned")
    delete = games_ai_tool.delete_skills(source, "", bad)
    read = games_ai_tool.read_skills(source, "", bad)

    for result, label in ((write, "write"), (modify, "modify"), (delete, "delete"), (read, "read")):
        assert ("invalid skill file name" in result) or ("required" in result), \
            f"{label} refuses {bad!r}: {result}"
    assert outside.read_text(encoding="utf-8") == "do not touch", "the file outside was not touched"
    assert json.loads((skills.skills_dir / "skills.json").read_text(encoding="utf-8")) == [], \
        "the skills index was not rewritten"


def test_an_absolute_path_is_refused(skills, tmp_path):
    target = tmp_path / "absolute.md"
    result = games_ai_tool.write_skills(skills.source, "", str(target), "summary", "content")
    assert "invalid skill file name" in result
    assert not target.exists()


def test_a_normal_name_still_reads_writes_modifies_and_deletes(skills):
    source = skills.source
    written = games_ai_tool.write_skills(source, "", "demo", "one line", "hello world\n")
    assert written == "Skill file written successfully", written
    demo = skills.skills_dir / "demo.md"
    assert demo.read_text(encoding="utf-8") == "hello world\n"

    index = json.loads((skills.skills_dir / "skills.json").read_text(encoding="utf-8"))
    assert index == [{"file": "demo.md", "description": "one line"}], index

    read = games_ai_tool.read_skills(source, "", "demo")
    assert "hello world" in read and read.startswith("Skill file content:"), read

    modified = games_ai_tool.modify_skills(source, "", "demo", "hello", "goodbye", "two")
    assert "replaced 1 occurrence" in modified, modified
    assert "goodbye world" in demo.read_text(encoding="utf-8")
    index = json.loads((skills.skills_dir / "skills.json").read_text(encoding="utf-8"))
    assert index == [{"file": "demo.md", "description": "two"}], index

    deleted = games_ai_tool.delete_skills(source, "", "demo")
    assert deleted == "Skill file deleted successfully", deleted
    assert not demo.exists()
    assert json.loads((skills.skills_dir / "skills.json").read_text(encoding="utf-8")) == []
