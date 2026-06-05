"""Unit tests for the extracted container-cache helper.

ui.dialogs.extract_tasks.cache_helpers is a pure leaf module (stdlib at
import; Container lazily imported inside the function), so it tests on
Linux CI without the dialog's Tk/sounddevice chain. Behaviour is locked
against the pre-extraction `_load_containers_async` cache branch so the
WS-4 move stays behaviour-preserving.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from tasks.backends.base import Container
from ui.dialogs.extract_tasks.cache_helpers import load_cached_containers

_TTL = timedelta(hours=24)
_KEY = "linear_teams_cache"


def _fresh_stamp() -> str:
    return datetime.now().isoformat()


def _stale_stamp() -> str:
    return (datetime.now() - timedelta(hours=48)).isoformat()


def test_fresh_cache_rebuilds_containers():
    config = {
        _KEY: {
            "fetched_at": _fresh_stamp(),
            "data": [
                {"id": "t1", "name": "Engineering", "key": "ENG"},
                {"id": "t2"},  # missing name + key → defaults "?" / None
            ],
        }
    }
    result = load_cached_containers(config, _KEY, _TTL)
    assert result == [
        Container(id="t1", name="Engineering", key="ENG"),
        Container(id="t2", name="?", key=None),
    ]


def test_stale_cache_returns_none():
    config = {_KEY: {"fetched_at": _stale_stamp(), "data": [{"id": "t1"}]}}
    assert load_cached_containers(config, _KEY, _TTL) is None


def test_corrupt_timestamp_returns_none():
    # Unparseable fetched_at → ValueError → age forced past TTL → None.
    config = {_KEY: {"fetched_at": "not-a-date", "data": [{"id": "t1"}]}}
    assert load_cached_containers(config, _KEY, _TTL) is None


def test_missing_cache_key_returns_none():
    assert load_cached_containers({}, _KEY, _TTL) is None


def test_fresh_but_empty_data_returns_none():
    # Fresh stamp but no data payload → nothing to rebuild → None (fetch).
    config = {_KEY: {"fetched_at": _fresh_stamp(), "data": []}}
    assert load_cached_containers(config, _KEY, _TTL) is None
