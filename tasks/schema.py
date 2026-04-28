"""Data model for the meeting-tasks pipeline.

Defines:
- Priority enum (maps to Linear API int 0-4)
- TaskStatus enum (send-status to Linear, used in Phase 6.3)
- Task dataclass
- Serialization helpers (to_dict / from_dict / priority_from_string)

Pure stdlib — no third-party deps, no I/O.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Optional


class Priority(IntEnum):
    """Linear-compatible task priority. Maps directly to Linear's int field.

    Counter-intuitive: 1 = Urgent, 4 = Low. Lower = higher priority.
    """
    NONE   = 0
    URGENT = 1
    HIGH   = 2
    MEDIUM = 3
    LOW    = 4


class TaskStatus(Enum):
    """Send-to-Linear status for a Task. Used in Phase 6.3+.

    Stored in tasks.json by .value (string) so JSON stays readable.
    """
    PENDING = "pending"   # not yet attempted
    SENDING = "sending"   # in flight
    SENT    = "sent"      # successfully created in Linear
    FAILED  = "failed"    # last attempt failed (see send_error)
    SKIPPED = "skipped"   # user unchecked the task


@dataclass
class Task:
    """A single meeting-extracted task. Edited in UI, sent to Linear.

    Fields divided into LLM-extracted (top half) and local-only (bottom half).
    Local fields support the editor and Linear send lifecycle, never go to
    the LLM, and never come back from Linear.
    """
    # ── LLM-extracted fields ──
    title: str
    description: str = ""
    priority: Priority = Priority.NONE
    assignee_id: Optional[str] = None     # Linear member UUID
    assignee_name: Optional[str] = None   # cached display name for UI
    label_ids: list[str] = field(default_factory=list)
    label_names: list[str] = field(default_factory=list)
    due_date: Optional[str] = None        # ISO "YYYY-MM-DD"

    # ── Local-only fields ──
    local_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    selected: bool = True
    status: TaskStatus = TaskStatus.PENDING
    linear_issue_id: Optional[str] = None
    linear_issue_url: Optional[str] = None
    send_error: Optional[str] = None


def priority_from_string(name: str | None) -> Priority:
    """Map LLM-returned priority strings to Priority enum.

    Case-insensitive. Unknown strings (including None and empty) → NONE.
    Caller is responsible for logging warnings on fallback.
    """
    if not name:
        return Priority.NONE
    try:
        return Priority[name.strip().upper()]
    except KeyError:
        return Priority.NONE
