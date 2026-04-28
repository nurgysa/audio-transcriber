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
