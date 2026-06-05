"""Container-cache helper for the Extract Tasks dialog.

Pure leaf logic (config dict in, Container list out) so the TTL-freshness
check + dict→Container rebuild is unit-testable on Linux CI without the
dialog's Tk/sounddevice import chain. Container is imported lazily inside
the function (mirrors the original _load_containers_async inline import) so
this module stays stdlib-only at import time.
"""
from __future__ import annotations

from datetime import datetime, timedelta


def load_cached_containers(config: dict, cache_key: str, ttl: timedelta) -> list | None:
    """Return cached Container objects if the cache entry is fresh, else None.

    The dialog persists fetched backend containers (Linear teams / Glide
    boards / Trello lists) as plain dicts under ``cache_key`` with an ISO
    ``fetched_at`` stamp. This rebuilds them into Container objects when the
    stamp is within ``ttl``. A missing/empty cache, a missing or unparseable
    ``fetched_at``, an aged-out stamp, or an empty ``data`` payload all return
    None — the caller then fetches fresh in a worker.
    """
    cache = config.get(cache_key) or {}
    fetched_at = cache.get("fetched_at")
    if not fetched_at:
        return None
    try:
        age = datetime.now() - datetime.fromisoformat(fetched_at)
    except ValueError:
        age = ttl + timedelta(seconds=1)
    if age <= ttl and cache.get("data"):
        # Cache stores plain dicts; rebuild Container objects.
        from tasks.backends.base import Container
        return [
            Container(id=d["id"], name=d.get("name", "?"), key=d.get("key"))
            for d in cache["data"]
        ]
    return None
