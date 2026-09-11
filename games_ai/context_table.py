"""
Context window table for GamesAI.

Window resolution order (highest priority first):
  1. per-AI config override   -> all_ai.<id>.context_window
  2. remote / cached table    -> data/context_windows.json (this repo) kept in a local cache
  3. version-bundled table    -> context_table_data.BUNDLED_TABLE (works fully offline)
  4. DEFAULT_CONTEXT_WINDOW   -> conservative fallback

The bundled table lives in its own generated module (`games_ai/context_table_data.py`),
synced from `data/context_windows.json` by `tools/build_context_table.py` in the repository.

The remote table is fetched on plugin startup and on every 24h update check,
stored at config/games_ai/cache/context_windows.json, and never blocks gameplay:
any network failure silently falls back to the cached or bundled table.
"""
import json
import os
import threading
import time
from fnmatch import fnmatch

import requests

from .config import plugin_config
from .context_table_data import BUNDLED_TABLE

TABLE_VERSION = 1

DEFAULT_CONTEXT_WINDOW = 32768
DEFAULT_MAX_OUTPUT = 4096

MIN_CONTEXT_WINDOW = 1024
MAX_CONTEXT_WINDOW = 10_000_000

CACHE_TTL = 24 * 3600          # seconds; refresh at most once per day
FETCH_TIMEOUT = 5              # seconds per source
MAX_TABLE_BYTES = 256 * 1024   # 256 KiB

# Primary source: GitHub Raw (this repository) / secondary: jsDelivr CDN
REMOTE_SOURCES = (
    "https://raw.githubusercontent.com/PengZixuan30/Games_AI/main/data/context_windows.json",
    "https://cdn.jsdelivr.net/gh/PengZixuan30/Games_AI@main/data/context_windows.json",
)

_lock = threading.Lock()
_table: dict | None = None
_cached_at: float = 0.0


def _log(server, level: str, msg: str) -> None:
    if server is None:
        return
    try:
        getattr(server.logger, level)(f"[context_table] {msg}")
    except Exception:
        pass


def _data_folder() -> str:
    """Plugin data folder (config/games_ai), derived from the skills path."""
    try:
        return os.path.dirname(os.path.dirname(os.path.abspath(plugin_config.skills_path)))
    except Exception:
        return os.path.join("config", "games_ai")


def cache_path() -> str:
    return os.path.join(_data_folder(), "cache", "context_windows.json")


# ── validation ──────────────────────────────────────────────────────────────

def _clamp_window(value) -> int | None:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    if MIN_CONTEXT_WINDOW <= value <= MAX_CONTEXT_WINDOW:
        return value
    return None


def _clamp_output(value) -> int | None:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    if 0 < value <= MAX_CONTEXT_WINDOW:
        return value
    return None


def validate_table(data) -> dict | None:
    """Return a sanitized table, or None when the payload is unusable."""
    if not isinstance(data, dict):
        return None
    models = data.get("models")
    if not isinstance(models, dict):
        return None
    clean: dict[str, dict] = {}
    for pattern, entry in models.items():
        if not isinstance(pattern, str) or not pattern:
            continue
        if not isinstance(entry, dict):
            continue
        window = _clamp_window(entry.get("context_window"))
        if window is None:
            continue
        item = {"context_window": window}
        max_output = _clamp_output(entry.get("max_output"))
        if max_output is not None:
            item["max_output"] = max_output
        note = entry.get("note")
        if isinstance(note, str) and note.strip():
            item["note"] = note.strip()[:200]
        clean[pattern] = item
    if not clean:
        return None
    return {
        "version": data.get("version", TABLE_VERSION),
        "updated": str(data.get("updated", "")),
        "models": clean,
    }


# ── table access ────────────────────────────────────────────────────────────

def _read_cache() -> tuple[dict | None, float]:
    path = cache_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return None, 0.0
    table = validate_table(payload.get("table") if isinstance(payload, dict) else payload)
    if table is None:
        return None, 0.0
    try:
        fetched_at = float(payload.get("fetched_at", 0))
    except (TypeError, ValueError):
        fetched_at = 0.0
    return table, fetched_at


def _write_cache(table: dict, source: str) -> None:
    path = cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {
            "fetched_at": time.time(),
            "source": source,
            "table": table,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def get_table() -> dict:
    """Current table: memory -> cache file -> bundled fallback (never raises)."""
    global _table, _cached_at
    if _table is not None:
        return _table
    with _lock:
        if _table is not None:
            return _table
        cached, fetched_at = _read_cache()
        if cached is not None:
            _table = cached
            _cached_at = fetched_at
        else:
            _table = validate_table(BUNDLED_TABLE) or {"version": TABLE_VERSION, "models": {}}
            _cached_at = 0.0
        return _table


def _pick_model_entry(models: dict, model: str) -> dict | None:
    """
    Match a model id against the table.

    Exact match wins; otherwise the **most specific** (longest) wildcard pattern
    that matches is used, so unrelated entries never shadow a precise one.
    A vendor prefix (``openai/gpt-4o``, ``x-ai/grok-4`` …) is stripped and retried,
    which covers OpenRouter-style model ids.
    """
    if not models or not model:
        return None
    entry = models.get(model)
    if isinstance(entry, dict):
        return entry
    model_lower = model.lower()

    def wildcard_match(candidate: str) -> dict | None:
        best_pattern = ""
        best: dict | None = None
        for pattern, value in models.items():
            if pattern == "*" or not isinstance(value, dict):
                continue
            try:
                if fnmatch(candidate, pattern.lower()) and len(pattern) > len(best_pattern):
                    best_pattern = pattern
                    best = value
            except Exception:
                continue
        return best

    found = wildcard_match(model_lower)
    if found is not None:
        return found
    if "/" in model_lower:                      # OpenRouter / gateway style id
        bare = model_lower.split("/", 1)[1]
        entry = models.get(bare)
        if isinstance(entry, dict):
            return entry
        found = wildcard_match(bare)
        if found is not None:
            return found
    fallback = models.get("*")
    return fallback if isinstance(fallback, dict) else None


def resolve_context_window(model: str, override=None) -> int:
    """Effective context window for a model, honoring the per-AI config override."""
    window = _clamp_window(override)
    if window is not None:
        return window
    entry = _pick_model_entry(get_table().get("models", {}), str(model or ""))
    if entry:
        window = _clamp_window(entry.get("context_window"))
        if window is not None:
            return window
    return DEFAULT_CONTEXT_WINDOW


def resolve_max_output(model: str) -> int:
    entry = _pick_model_entry(get_table().get("models", {}), str(model or ""))
    if entry:
        value = _clamp_output(entry.get("max_output"))
        if value is not None:
            return value
    return DEFAULT_MAX_OUTPUT


# ── remote refresh ──────────────────────────────────────────────────────────

def _download_table(url: str) -> dict | None:
    try:
        response = requests.get(url, timeout=FETCH_TIMEOUT)
    except Exception:
        return None
    if response.status_code != 200:
        return None
    content = response.content
    if not content or len(content) > MAX_TABLE_BYTES:
        return None
    try:
        data = json.loads(content.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return validate_table(data)


def refresh_table(server=None, force: bool = False) -> bool:
    """
    Refresh the table from the remote sources with a 24h TTL.

    Called from the startup / 24h update check (`update()`); the manual
    `!!gamesai check` command calls it with ``force=True`` to bypass the TTL.
    Returns True when a new table was fetched and cached.
    """
    global _table, _cached_at

    _, fetched_at = (0.0, 0.0)
    if not force:
        get_table()                      # make sure cache/bundled table is loaded
        with _lock:
            fetched_at = _cached_at
        if fetched_at and (time.time() - fetched_at) < CACHE_TTL:
            _log(server, "debug", "cache is fresh, skip remote refresh")
            return False

    with _lock:
        # Re-check under the lock: a concurrent caller may have refreshed while
        # we were waiting, so at most one download runs per TTL window.
        if not force and _cached_at and (time.time() - _cached_at) < CACHE_TTL:
            _log(server, "debug", "cache was refreshed by another caller, skip remote refresh")
            return False
        for url in REMOTE_SOURCES:
            table = _download_table(url)
            if table is None:
                _log(server, "debug", f"source failed: {url}")
                continue
            _table = table
            _cached_at = time.time()
            _write_cache(table, url)
            _log(server, "info", f"context window table updated from {url} ({len(table['models'])} entries)")
            return True
    _log(server, "debug", "all sources failed, keeping current table")
    return False


def force_reload() -> None:
    """Drop the in-memory table so the next access re-reads the cache."""
    global _table, _cached_at
    with _lock:
        _table = None
        _cached_at = 0.0
