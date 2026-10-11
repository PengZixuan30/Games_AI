# Generated from games_ai/ai/context_table.py by tools/build_tool_stubs.py -- do not edit.
from ..core import logger as logger
from ..core.config import plugin_config as plugin_config
from .context_table_data import BUNDLED_TABLE as BUNDLED_TABLE
from _typeshed import Incomplete

TABLE_VERSION: int
DEFAULT_CONTEXT_WINDOW: int
DEFAULT_MAX_OUTPUT: int
MIN_CONTEXT_WINDOW: int
MAX_CONTEXT_WINDOW: int
CACHE_TTL: Incomplete
FETCH_TIMEOUT: int
MAX_TABLE_BYTES: Incomplete
REMOTE_SOURCES: Incomplete
_lock: Incomplete
_table: dict | None
_cached_at: float

def _log(server, level: str, msg: str) -> None:
    """One line tagged ``[context_table]``: the shared guard, this module's tag."""
def _data_folder() -> str:
    """Plugin data folder (config/games_ai), derived from the skills path."""
def cache_path() -> str: ...
def _clamp_window(value) -> int | None: ...
def _clamp_output(value) -> int | None: ...
def validate_table(data) -> dict | None:
    """Return a sanitized table, or None when the payload is unusable."""
def _read_cache() -> tuple[dict | None, float]: ...
def _write_cache(table: dict, source: str) -> None: ...
def get_table() -> dict:
    """Current table: memory -> cache file -> bundled fallback (never raises)."""
def _pick_model_entry(models: dict, model: str) -> dict | None:
    """
    Match a model id against the table.

    Exact match wins; otherwise the **most specific** (longest) wildcard pattern
    that matches is used, so unrelated entries never shadow a precise one.
    A vendor prefix (``openai/gpt-4o``, ``x-ai/grok-4`` …) is stripped and retried,
    which covers OpenRouter-style model ids.
    """
def resolve_context_window(model: str, override=None) -> int:
    """Effective context window for a model, honoring the per-AI config override."""
def resolve_max_output(model: str) -> int: ...
def window_source(model: str, override=None) -> str:
    '''
    Which of the three layers decides the window: ``"config"``, ``"table"`` or ``"default"``.

    Reported by ``!!ask context``: an override that silently beats the table is the usual
    reason why a displayed window looks wrong, and the three cases are indistinguishable
    from the number alone. The classification mirrors :func:`resolve_context_window`.
    '''
def _download_table(url: str) -> dict | None: ...
def refresh_table(server=None, force: bool = False) -> bool:
    """
    Refresh the table from the remote sources with a 24h TTL.

    Called from the startup / 24h update check (`update()`); the manual
    `!!gamesai check` command calls it with ``force=True`` to bypass the TTL.
    Returns True when a new table was fetched and cached.
    """
def force_reload() -> None:
    """Drop the in-memory table so the next access re-reads the cache."""
