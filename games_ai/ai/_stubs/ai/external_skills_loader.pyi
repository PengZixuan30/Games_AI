# Generated from games_ai/ai/external_skills_loader.py by tools/build_tool_stubs.py -- do not edit.
EXTERNAL_SKILLS_LIST: list[dict[str, str]]

def register_skills(file_name: str, description: str, content: str) -> None:
    """Inject one skill at load time, without writing anything to disk.

    ``description`` is what the AI reads to decide when to load the skill, ``content`` is what it
    gets back. A skill registered this way is served before a file of the same name and is not
    listed in ``skills.json``.
    """
def read_external_skills(file_name: str) -> str | None: ...
