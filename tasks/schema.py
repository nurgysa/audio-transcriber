"""Data model for the meeting-tasks pipeline.

Defines:
- Priority enum (maps to Linear API int 0-4)
- TaskStatus enum (send-status to Linear, used in Phase 6.3)
- Task dataclass
- Serialization helpers (to_dict / from_dict / priority_from_string)

Pure stdlib — no third-party deps, no I/O.
"""
from __future__ import annotations

from enum import IntEnum


class Priority(IntEnum):
    """Linear-compatible task priority. Maps directly to Linear's int field.

    Counter-intuitive: 1 = Urgent, 4 = Low. Lower = higher priority.
    """
    NONE   = 0
    URGENT = 1
    HIGH   = 2
    MEDIUM = 3
    LOW    = 4


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
