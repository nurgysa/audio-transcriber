"""Tests for tasks.schema — pure stdlib, no I/O."""
from __future__ import annotations

import pytest

from tasks.schema import Priority


# ── Priority ──────────────────────────────────────────────────────────


def test_priority_int_values_match_linear_api():
    """Linear priority is int 0-4: 0=None, 1=Urgent, 2=High, 3=Med, 4=Low.

    Verified against Linear API docs. Lower number = higher priority.
    """
    assert Priority.NONE.value == 0
    assert Priority.URGENT.value == 1
    assert Priority.HIGH.value == 2
    assert Priority.MEDIUM.value == 3
    assert Priority.LOW.value == 4


def test_priority_lookup_by_name_case_insensitive():
    """LLM may return 'High', 'high', 'HIGH' — all should map to HIGH."""
    from tasks.schema import priority_from_string
    assert priority_from_string("high") is Priority.HIGH
    assert priority_from_string("High") is Priority.HIGH
    assert priority_from_string("HIGH") is Priority.HIGH
    assert priority_from_string("urgent") is Priority.URGENT


def test_priority_lookup_unknown_falls_back_to_none():
    """LLM hallucinations like 'critical' or '' fall back to NONE."""
    from tasks.schema import priority_from_string
    assert priority_from_string("critical") is Priority.NONE
    assert priority_from_string("") is Priority.NONE
    assert priority_from_string(None) is Priority.NONE  # type: ignore[arg-type]


# ── TaskStatus ────────────────────────────────────────────────────────


def test_task_status_string_values():
    """TaskStatus values are strings (used as JSON-friendly tags)."""
    from tasks.schema import TaskStatus
    assert TaskStatus.PENDING.value == "pending"
    assert TaskStatus.SENDING.value == "sending"
    assert TaskStatus.SENT.value    == "sent"
    assert TaskStatus.FAILED.value  == "failed"
    assert TaskStatus.SKIPPED.value == "skipped"


def test_task_status_round_trip_via_value():
    """TaskStatus(value) → enum, used when loading tasks.json."""
    from tasks.schema import TaskStatus
    assert TaskStatus("sent") is TaskStatus.SENT
    assert TaskStatus("failed") is TaskStatus.FAILED


# ── Task dataclass ────────────────────────────────────────────────────


def test_task_minimum_creation_with_only_title():
    """Title is the only required field; everything else has defaults."""
    from tasks.schema import Task, Priority, TaskStatus
    t = Task(title="Починить login bug")
    assert t.title == "Починить login bug"
    assert t.description == ""
    assert t.priority is Priority.NONE
    assert t.assignee_id is None
    assert t.assignee_name is None
    assert t.label_ids == []
    assert t.label_names == []
    assert t.due_date is None
    assert t.selected is True
    assert t.status is TaskStatus.PENDING
    assert t.linear_issue_id is None
    assert t.linear_issue_url is None
    assert t.send_error is None
    # local_id is auto-generated
    assert isinstance(t.local_id, str)
    assert len(t.local_id) == 36  # UUID4 format


def test_task_local_ids_are_unique():
    """Two Tasks created back-to-back must have different local_ids."""
    from tasks.schema import Task
    a = Task(title="A")
    b = Task(title="B")
    assert a.local_id != b.local_id


def test_task_label_ids_default_is_independent_per_instance():
    """Mutable defaults must use field(default_factory=list), not =[]."""
    from tasks.schema import Task
    a = Task(title="A")
    b = Task(title="B")
    a.label_ids.append("label-1")
    assert b.label_ids == []   # if default leaked, this would also have label-1
