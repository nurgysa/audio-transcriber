"""Backend Protocol + value types — the contract every adapter satisfies.

A `TaskBackend` exposes four operations:
    bootstrap()        → list[Container]      (containers visible to the token)
    container_label(c) → str                  (UI label for the dropdown)
    context(cid)       → dict                 (members + labels, or empty)
    create(cid, task)  → CreatedIssue         (POST/mutation per task)
plus a `close()` method to release HTTP sessions.

Container/CreatedIssue are intentionally minimal — backends differ in what
metadata they track, but the dialog and sender only need the listed fields.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from tasks.schema import Task


@dataclass(frozen=True)
class Container:
    """A backend "container" where tasks live.

    For Linear: a Team (id is a UUID, key is the short prefix like "NUR").
    For Glide: a Board (id is a UUID, key is None — Glide has no short codes).
    """
    id: str
    name: str
    key: Optional[str] = None


@dataclass(frozen=True)
class CreatedIssue:
    """Result of a successful create() call.

    `identifier` is what the UI shows in the row badge after send:
    - Linear: human-readable ENG-1234 from the API response
    - Glide: first 6 chars of the task UUID (Glide has no human ID)

    `url` opens the task in the backend's web UI when the user clicks
    the SENT row.
    """
    identifier: str
    url: str


class TaskBackend(Protocol):
    """Every backend (Linear, Glide, future) implements this."""

    name: str             # stable id for config / persistence ("linear", "glide")
    display_name: str     # human-facing dropdown label ("Linear", "Glide")

    def bootstrap(self) -> list[Container]:
        """Validate the API key + return all containers visible to it.

        Single round-trip where possible. Used to populate the dropdown
        on dialog open and for the [↻] refresh button.
        """
        ...

    def container_label(self, c: Container) -> str:
        """How to render a container in the dropdown.

        Linear: "Engineering (ENG)". Glide: just "Inbox" (no key).
        """
        ...

    def context(self, container_id: str) -> dict:
        """Return member + label lists for LLM grounding.

        Linear: {"members": [...], "labels": [...]} from team_context.
        Glide: {"members": [], "labels": []} (no grounding — schema is
        too heterogeneous across boards for reliable LLM matching;
        assignee/labels stay manual in the editor).
        """
        ...

    def create(self, container_id: str, task: Task) -> CreatedIssue:
        """Send a single task to the backend. Returns identifier + URL.

        Raises whatever the underlying client raises (LinearError /
        GlideError) — sender catches those and marks the task FAILED.
        """
        ...

    def close(self) -> None:
        """Release HTTP session. Safe to call from another thread to
        cancel an in-flight request (raises ConnectionError in the
        worker, which sender catches as a generic Exception)."""
        ...
