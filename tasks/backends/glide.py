"""Glide adapter — wraps tasks.glide_client.GlideClient.

Translates between Phase 6.0 schema and Glide's REST + columns model.

Phase 6.4.1 notes:
- No LLM grounding (`context()` returns empty members/labels). Schemas
  vary too much between Glide boards for the LLM to reliably guess
  assignees / status options. User fills these manually in the editor.
- assignee_id and label_ids on the Task are IGNORED for Glide (they are
  Linear-shaped UUIDs). Future polish: map Task.assignee_name → Glide's
  Person column via integration's field_mapping.
- Identifier shown in row badge is the first 6 chars of the task UUID
  (Glide has no ENG-1234-style human ID).
"""
from __future__ import annotations

from tasks.backends.base import Container, CreatedIssue
from tasks.glide_client import GlideClient
from tasks.schema import Priority, Task

# Glide priority is a 4-string set; Linear has 5 (NONE is silently NULL).
_PRIORITY_MAP: dict[Priority, str] = {
    Priority.URGENT: "critical",
    Priority.HIGH:   "high",
    Priority.MEDIUM: "medium",
    Priority.LOW:    "low",
    # Priority.NONE deliberately omitted — sender passes None to create_task,
    # which omits the field from the payload entirely.
}


def _glide_task_url(board_id: str, task_id: str) -> str:
    """Construct the web-UI URL for a created task.

    Format inferred from user's notes (`https://os.tensor-ai.tech/boards/<board_id>`).
    First smoke will reveal whether the task page is at /boards/<bid>/tasks/<tid>
    or different — TBD until live test.
    """
    return f"https://os.tensor-ai.tech/boards/{board_id}/tasks/{task_id}"


class GlideBackend:
    """Adapter: dialog/sender ←→ GlideClient."""

    name = "glide"
    display_name = "Glide"

    def __init__(self, client: GlideClient):
        self._client = client

    def bootstrap(self) -> list[Container]:
        boards = self._client.list_boards()
        return [
            Container(id=b["id"], name=b.get("name", "?"), key=None)
            for b in boards
        ]

    def container_label(self, c: Container) -> str:
        # Glide boards have no key — name only.
        return c.name

    def context(self, container_id: str) -> dict:
        # Empty grounding — see module docstring.
        return {"members": [], "labels": []}

    def create(self, container_id: str, task: Task) -> CreatedIssue:
        priority = _PRIORITY_MAP.get(task.priority)   # None for Priority.NONE

        # Idempotency-Key: stable per local task. Retry uses the same key —
        # Glide caches the response (success OR failure) for 24h, which means
        # network-drop retry is safe but a Glide-side error replays from cache.
        # Phase 6.4.2: add attempt suffix on Retry-button paths.
        idem_key = f"task-{task.local_id}" if task.local_id else None

        result = self._client.create_task(
            title=task.title,
            description=task.description or None,
            priority=priority,
            board_id=container_id,
            idempotency_key=idem_key,
        )

        task_uuid = result.get("id") or ""
        # Short identifier — first 6 chars of UUID. Glide has no
        # human-readable ENG-1234 equivalent.
        identifier = task_uuid[:6] if task_uuid else "?"

        # Use board_id from response if present (defends against integration
        # default-board redirects); fall back to caller's container_id.
        actual_board = result.get("board_id") or container_id
        url = _glide_task_url(actual_board, task_uuid) if task_uuid else ""

        return CreatedIssue(identifier=identifier, url=url)

    def close(self) -> None:
        self._client.close()
