"""Send-to-Linear orchestrator.

Pure logic — no Tk, no I/O outside the injected LinearClient. The dialog
wraps this in a worker thread and marshals status updates back to the UI
via ``self.after(0, ...)``.

Public API:
    send_tasks_iter(tasks, *, team_id, linear_client, on_status_change,
                    cancel_check, retry_failed=False)
        → generator yielding Task objects after each status transition

The on_status_change callback is invoked with (task, new_status) signature
on EVERY transition. It also receives kwargs for context — currently
unused by callers but reserved for richer status reporting.

Filtering rules:
- Initial send (retry_failed=False): send tasks where selected=True AND
  status=PENDING. Skip already-SENT, already-FAILED, and unselected tasks.
- Retry send (retry_failed=True): send tasks where status=FAILED. Already-
  SENT tasks are NEVER touched (avoids duplicate Linear issues).

Status transitions:
  PENDING → SENDING → SENT  (success)
  PENDING → SENDING → FAILED  (LinearError)
  FAILED → SENDING → SENT  (retry success)
  FAILED → SENDING → FAILED  (retry failure)
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator

from tasks.linear_client import LinearError
from tasks.schema import Priority, Task, TaskStatus

logger = logging.getLogger(__name__)


def send_tasks_iter(
    tasks: list[Task],
    *,
    team_id: str,
    linear_client,
    on_status_change: Callable,
    cancel_check: Callable[[], bool],
    retry_failed: bool = False,
) -> Iterator[Task]:
    """Iterate selected tasks and POST each to Linear.

    Yields each task after its terminal status (SENT / FAILED) is set.
    Caller iterates the generator to drive the send (the generator does
    the work; the yielded values are mostly for testing).

    `cancel_check()` is called BEFORE each Linear request. If it returns
    True, the iteration stops; tasks not yet sent retain their PENDING/
    FAILED status.

    `on_status_change(task, new_status)` is invoked on every transition.
    """
    for task in tasks:
        # Cancel check at the top of the loop — before any work.
        if cancel_check():
            logger.info("send cancelled before task %r", task.local_id)
            return

        if not _should_send(task, retry_failed=retry_failed):
            continue

        # PENDING (or FAILED if retry) → SENDING
        task.status = TaskStatus.SENDING
        task.send_error = None
        on_status_change(task, TaskStatus.SENDING)

        try:
            issue = _create_one(linear_client, team_id, task)
        except LinearError as e:
            task.status = TaskStatus.FAILED
            task.send_error = _short_error_code(str(e)) or "error"
            logger.warning(
                "send failed for task %r (%s): %s",
                task.local_id, task.title, e,
            )
            on_status_change(task, TaskStatus.FAILED)
            yield task
            continue
        except Exception as e:
            # Belt-and-braces: any unexpected exception → FAILED.
            task.status = TaskStatus.FAILED
            task.send_error = _short_error_code(str(e)) or "error"
            logger.exception(
                "unexpected error sending task %r (%s)",
                task.local_id, task.title,
            )
            on_status_change(task, TaskStatus.FAILED)
            yield task
            continue

        task.status = TaskStatus.SENT
        task.linear_issue_id = issue.get("identifier")
        task.linear_issue_url = issue.get("url")
        task.send_error = None
        on_status_change(task, TaskStatus.SENT)
        yield task


# ── Helpers ─────────────────────────────────────────────────────────


def _should_send(task: Task, *, retry_failed: bool) -> bool:
    if not task.selected:
        return False
    if retry_failed:
        return task.status is TaskStatus.FAILED
    return task.status is TaskStatus.PENDING


def _create_one(linear_client, team_id: str, task: Task) -> dict:
    """Build the create_issue kwargs from a Task and call the client."""
    kwargs = {
        "team_id": team_id,
        "title": task.title,
    }
    # Description: only pass if non-empty (Linear treats null as 'set null').
    if task.description:
        kwargs["description"] = task.description
    if task.priority is not Priority.NONE:
        kwargs["priority"] = int(task.priority.value)
    if task.assignee_id:
        kwargs["assignee_id"] = task.assignee_id
    if task.label_ids:
        kwargs["label_ids"] = list(task.label_ids)
    if task.due_date:
        kwargs["due_date"] = task.due_date
    return linear_client.create_issue(**kwargs)


def _short_error_code(msg: str) -> str:
    """Extract a short tag from a Linear/network error message.

    Examples:
        "Linear вернул 401: ..." → "401"
        "Linear 429 rate-limit"  → "429"
        "Нет соединения с..."   → "network"
        "Таймаут Linear..."     → "timeout"
        anything else            → ""
    """
    msg_lower = msg.lower()
    # HTTP status codes. \b ensures "1400" doesn't match "400" — between two
    # digits there's no word boundary, so "1400" is treated as one token.
    m = re.search(r"\b(4\d\d|5\d\d)\b", msg)
    if m:
        return m.group(1)
    if "соединен" in msg_lower or "connection" in msg_lower:
        return "network"
    if "таймаут" in msg_lower or "timeout" in msg_lower:
        return "timeout"
    return ""
