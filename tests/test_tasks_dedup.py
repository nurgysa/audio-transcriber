"""Tests for the task-dedup engine (PR-2). Pure logic — no FS/network."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from tasks.dedup import (
    FUZZY_HIGH,
    FUZZY_LOW,
    SentTask,
    build_sent_registry,
    normalize_title,
)
from tasks.persistence import PersistenceError
from tasks.schema import Task, TaskStatus


def test_thresholds_are_sane():
    assert 0.0 < FUZZY_LOW < FUZZY_HIGH < 1.0


def test_sent_task_is_frozen_value_object():
    s = SentTask(
        title="Починить логин",
        backend="linear",
        container_id="team-1",
        ref="node-uuid-1",
        identifier="ENG-1",
        url="http://x/ENG-1",
        meeting_name="2026-05-20_10-00-00_standup",
        meeting_date="2026-05-20_10-00-00",
    )
    assert s.title == "Починить логин"
    assert s.ref == "node-uuid-1"
    with pytest.raises(FrozenInstanceError):
        s.title = "x"  # type: ignore[misc]


def test_normalize_lowercases_and_collapses_punct_and_space():
    assert normalize_title("  Починить   ЛОГИН!! ") == "починить логин"
    assert normalize_title("Fix: the   bug.") == "fix the bug"


def test_normalize_preserves_cyrillic_and_kazakh_letters():
    # Unicode-aware \w must keep RU/KZ letters; only punctuation goes.
    assert normalize_title("Әзірлеу: есеп —  v2") == "әзірлеу есеп v2"


def test_normalize_empty_and_none_safe():
    assert normalize_title("") == ""
    assert normalize_title("!!!") == ""


# ── build_sent_registry ──────────────────────────────────────────────


def _sent(title, ref, **kw):
    """A Task in SENT state with a backend_ref (eligible for the registry)."""
    return Task(
        title=title,
        status=TaskStatus.SENT,
        backend_ref=ref,
        linear_issue_id=kw.get("identifier", "ENG-1"),
        linear_issue_url=kw.get("url", "http://x/ENG-1"),
    )


def _entries(*folders):
    # Non-trivial, varied folder names + dates (no all-zero fixtures).
    return [
        {"folder_path": f, "folder_name": f.split("/")[-1],
         "date_created": f.split("/")[-1][:19]}
        for f in folders
    ]


def _loader(mapping):
    def load(folder):
        if folder not in mapping:
            raise PersistenceError(f"no tasks.json in {folder}")
        return mapping[folder]
    return load


def test_registry_keeps_only_sent_with_backend_ref():
    mapping = {
        "/h/2026-05-20_10-00-00_standup": {
            "backend": "linear", "team_id": "team-A",
            "tasks": [
                _sent("Починить логин", "uuid-1"),
                Task(title="draft idea", status=TaskStatus.PENDING),  # excluded: not SENT
                Task(title="old sent no ref", status=TaskStatus.SENT, backend_ref=None),  # excluded
            ],
        },
    }
    reg = build_sent_registry(
        _entries("/h/2026-05-20_10-00-00_standup"), _loader(mapping),
    )
    assert len(reg) == 1
    s = reg[0]
    assert (s.title, s.ref, s.backend, s.container_id) == (
        "Починить логин", "uuid-1", "linear", "team-A")
    assert s.meeting_name == "2026-05-20_10-00-00_standup"
    assert s.identifier == "ENG-1"


def test_registry_excludes_current_meeting_folder():
    mapping = {
        "/h/A": {"backend": "linear", "team_id": "t", "tasks": [_sent("a", "r1")]},
        "/h/B": {"backend": "linear", "team_id": "t", "tasks": [_sent("b", "r2")]},
    }
    reg = build_sent_registry(
        _entries("/h/A", "/h/B"), _loader(mapping), exclude_folder="/h/B",
    )
    assert [s.ref for s in reg] == ["r1"]


def test_registry_defaults_backend_to_linear_and_skips_missing_tasks_json():
    mapping = {
        "/h/has": {"team_id": "t-9", "tasks": [_sent("x", "r9")]},  # no "backend" key
        # "/h/none" intentionally absent -> loader raises PersistenceError
    }
    reg = build_sent_registry(
        _entries("/h/has", "/h/none"), _loader(mapping),
    )
    assert len(reg) == 1
    assert reg[0].backend == "linear"  # defaulted
    assert reg[0].container_id == "t-9"
