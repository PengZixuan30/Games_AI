"""
Context-window table builder / verifier.

The repository keeps the table twice:

  * ``data/context_windows.json``      - source of truth, also the file the plugin
                                         fetches at runtime (GitHub Raw / jsDelivr)
  * ``games_ai/context_table_data.py`` - generated Python module bundled into the
                                         release, used as the offline fallback

Modes:

  python tools/build_context_table.py
      Maintenance mode (default): read data/context_windows.json, regenerate
      games_ai/context_table_data.py from it and verify that both agree.

  python tools/build_context_table.py --merge
      Research mode: merge the .tmp_part_*.json research batches into
      data/context_windows.json, then do the same as maintenance mode.

  python tools/build_context_table.py --check
      Verify only; writes nothing.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_TABLE = os.path.join(ROOT, "data", "context_windows.json")
DATA_MODULE = os.path.join(ROOT, "games_ai", "context_table_data.py")

# research staging files (only used with --merge)
PARTS = [
    ".tmp_part_deepseek_kimi_glm.json",
    ".tmp_part_openai_xai.json",
    ".tmp_part_china.json",
    ".tmp_part_west_extra.json",
    ".tmp_part_claude_gemini.json",
]

FALLBACK = {"context_window": 32768, "max_output": 4096}

HEADER = '''"""
Version-bundled context-window table (generated file - do not edit by hand).

Source of truth: ``data/context_windows.json`` in the repository, which is also the
remote table the plugin fetches at runtime. Regenerate after editing that file::

    python tools/build_context_table.py

Loaded by ``games_ai/context_table.py`` as the offline fallback (priority 3).
"""
'''


def merge_parts() -> dict:
    models: dict[str, dict] = {}
    conflicts: list[str] = []
    for name in PARTS:
        path = os.path.join(ROOT, name)
        if not os.path.exists(path):
            continue
        data = json.load(open(path, encoding="utf-8"))
        for pattern, entry in data.get("models", {}).items():
            if pattern in models and models[pattern] != entry:
                conflicts.append(pattern)
            models[pattern] = entry
        print(f"[merge] {name}: {len(data.get('models', {}))} entries")
    if conflicts:
        print(f"[warn] conflicting keys overwritten: {conflicts}")
    return models


def normalise(models: dict, updated: str) -> dict:
    ordered = {k: v for k, v in models.items() if k != "*"}
    ordered["*"] = models.get("*", FALLBACK)
    return {"version": 1, "updated": updated, "models": ordered}


def write_repo(table: dict) -> None:
    os.makedirs(os.path.dirname(REPO_TABLE), exist_ok=True)
    with open(REPO_TABLE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(table, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"[write] {REPO_TABLE} ({len(table['models'])} entries)")


def render_bundled(table: dict) -> str:
    """
    Render the generated data module.

    One model per line keeps the file diff-friendly. Values are emitted with `repr`
    (not `json.dumps`) so that JSON-only literals such as `null` become valid Python
    (`None`); `write_bundled()` still executes the result and compares it back to the
    input, so a future schema change cannot produce a broken module silently.
    """
    lines = [HEADER, "BUNDLED_TABLE: dict = {"]
    lines.append(f'    "version": {table.get("version", 1)!r},')
    lines.append(f'    "updated": {str(table.get("updated", ""))!r},')
    lines.append('    "models": {')
    for pattern, entry in table["models"].items():
        lines.append(f"        {pattern!r}: {entry!r},")
    lines.append("    },")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def write_bundled(table: dict) -> bool:
    source = render_bundled(table)
    namespace: dict = {}
    try:
        exec(compile(source, DATA_MODULE, "exec"), namespace)
    except Exception as e:
        print(f"[error] generated module does not execute: {type(e).__name__}: {e}")
        return False
    if namespace.get("BUNDLED_TABLE") != table:
        print("[error] generated module does not round-trip to the same table")
        return False
    with open(DATA_MODULE, "w", encoding="utf-8", newline="\n") as f:
        f.write(source)
    print(f"[write] {DATA_MODULE} ({len(table['models'])} entries)")
    return True


def verify() -> bool:
    sys.path.insert(0, ROOT)
    import importlib
    import games_ai.context_table as ct
    import games_ai.context_table_data as ctd
    importlib.reload(ctd)
    importlib.reload(ct)

    repo = json.load(open(REPO_TABLE, encoding="utf-8"))
    results: list[tuple[str, bool, str]] = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), "" if cond else str(detail)))

    ct_source = open(os.path.join(ROOT, "games_ai", "context_table.py"), encoding="utf-8").read()
    check("bundled == repo", ct.BUNDLED_TABLE["models"] == repo["models"])
    check("schema valid", ct.validate_table(repo) is not None)
    check("has * fallback", "*" in repo["models"])
    check("data module is the bundle", ctd.BUNDLED_TABLE is ct.BUNDLED_TABLE)
    check("no inlined table", "BEGIN BUNDLED TABLE" not in ct_source and "_BUNDLED_TABLE_JSON" not in ct_source)
    bad_range = {k: v for k, v in repo["models"].items()
                 if not isinstance(v.get("context_window"), int)
                 or not (1024 <= v["context_window"] <= 10_000_000)}
    check("window range ok", not bad_range, bad_range)
    bad_out = {k: v for k, v in repo["models"].items()
               if v.get("max_output") is not None and not (0 < v["max_output"] <= 10_000_000)}
    check("max_output range ok", not bad_out, bad_out)
    unknown = ct.resolve_context_window("definitely-not-a-model-xyz")
    check("unknown model -> default", unknown == ct.DEFAULT_CONTEXT_WINDOW, unknown)

    print("== verify ==")
    ok = True
    for name, cond, detail in results:
        print(("  [PASS] " if cond else "  [FAIL] ") + name + ("" if cond else f" {detail}"))
        ok = ok and cond
    notes = sum(1 for v in repo["models"].values() if v.get("note"))
    print(f"  [info] entries={len(repo['models'])}, with note={notes}, updated={repo.get('updated')}")
    return ok


def main() -> int:
    args = set(sys.argv[1:])
    check_only = "--check" in args
    do_merge = "--merge" in args

    if do_merge:
        models = merge_parts()
        updated = os.environ.get("TABLE_DATE") or json.load(
            open(REPO_TABLE, encoding="utf-8")).get("updated", "")
        table = normalise(models, updated)
    else:
        table = json.load(open(REPO_TABLE, encoding="utf-8"))
        table = normalise(table["models"], table.get("updated", ""))

    if not check_only:
        write_repo(table)
        if not write_bundled(table):
            return 2

    return 0 if verify() else 1


if __name__ == "__main__":
    sys.exit(main())
