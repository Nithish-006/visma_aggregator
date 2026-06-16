"""Shared singletons and mutable app state.

This module exists to break the global-state coupling in the old monolithic
``app.py``. Blueprints cannot ``from app import df_cache`` (circular import), and
the cache/legacy-frame were rebound via ``global`` — so a plain
``from extensions import df_cache`` would hand each blueprint a stale copy after
the first reload.

Fix: keep the singleton here and put the mutable values on a single ``state``
object. Everything mutates ``state`` in place (``state.df_cache[...] = ...``,
``state.df_cache.clear()``, ``state.df_global = ...``) instead of rebinding a
module global, so every importer shares one live object.
"""

from database import DatabaseManager

# Singleton DB manager (per-request connection pattern lives inside it).
# Never rebound, so importers can use it directly without going through `state`.
db_manager = DatabaseManager()


class _State:
    """Mutable shared state, swapped in for the old module-level globals."""

    def __init__(self):
        self.df_cache = {}       # bank_code -> DataFrame
        self.df_global = None    # legacy combined frame (backwards compat)
        self.db_connected = False


state = _State()
