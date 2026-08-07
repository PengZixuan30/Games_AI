EXTERNAL_SKILLS_LIST: list[dict[str, str]] = []

def register_skills(file_name: str, description: str, content: str) -> None:
    EXTERNAL_SKILLS_LIST.append({"file": file_name, "description": description, "content": content})

def read_external_skills(file_name: str) -> str | None:
    for i in EXTERNAL_SKILLS_LIST:
        if i.get("file") == file_name:
            return i.get("content")
    return None
