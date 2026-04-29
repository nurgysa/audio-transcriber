"""Tests for tasks.sender — pure orchestrator with mocked LinearClient."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tasks.schema import Priority, Task, TaskStatus
from tasks.sender import send_tasks_iter


def _pending_task(title="T", **kw) -> Task:
    kw.setdefault("selected", True)
    kw.setdefault("status", TaskStatus.PENDING)
    return Task(title=title, **kw)


def _make_linear(issues_iter=None, raise_on=None):
    """Helper: construct a MagicMock LinearClient.

    `issues_iter` — list of dicts to return on successive create_issue calls
    `raise_on` — list of (call_index, exception) pairs to raise instead
    """
    from tasks.linear_client import LinearError
    client = MagicMock()
    issues_iter = list(issues_iter or [])
    raise_on = dict(raise_on or {})

    call_count = [0]

    def _create(**kwargs):
        idx = call_count[0]
        call_count[0] += 1
        if idx in raise_on:
            raise raise_on[idx]
        if idx < len(issues_iter):
            return issues_iter[idx]
        return {"id": f"id-{idx}", "identifier": f"ENG-{100 + idx}", "url": f"https://linear.app/x/ENG-{100 + idx}"}

    client.create_issue.side_effect = _create
    return client


# ── Filtering ────────────────────────────────────────────────────────


def test_send_iter_skips_unselected_tasks():
    tasks = [
        _pending_task("A", local_id="a"),
        _pending_task("B", selected=False, local_id="b"),  # unselected
        _pending_task("C", local_id="c"),
    ]
    linear = _make_linear()
    statuses = []
    list(send_tasks_iter(
        tasks, team_id="team-id", linear_client=linear,
        on_status_change=lambda t, s, **kw: statuses.append((t.local_id, s)),
        cancel_check=lambda: False,
    ))
    # Only A and C went through SENDING/SENT cycles. B never got touched.
    a_seen = any(local_id == "a" for local_id, _ in statuses)
    c_seen = any(local_id == "c" for local_id, _ in statuses)
    b_seen = any(local_id == "b" for local_id, _ in statuses)
    assert a_seen and c_seen and not b_seen
    assert linear.create_issue.call_count == 2


def test_send_iter_skips_already_sent_tasks():
    tasks = [
        _pending_task("A", local_id="a"),
        Task(title="B", selected=True, status=TaskStatus.SENT, local_id="b"),  # already sent
    ]
    linear = _make_linear()
    list(send_tasks_iter(
        tasks, team_id="team-id", linear_client=linear,
        on_status_change=lambda t, s, **kw: None,
        cancel_check=lambda: False,
    ))
    assert linear.create_issue.call_count == 1   # only A sent


def test_send_iter_skips_failed_tasks_unless_retry_mode():
    """In default (initial-send) mode, skip FAILED. In retry mode, SEND only FAILED."""
    tasks = [
        _pending_task("A", local_id="a"),
        Task(title="B", selected=True, status=TaskStatus.FAILED,
             local_id="b", send_error="500"),
    ]
    linear = _make_linear()

    # Initial send: only A.
    list(send_tasks_iter(
        tasks, team_id="t", linear_client=linear,
        on_status_change=lambda *a, **kw: None,
        cancel_check=lambda: False, retry_failed=False,
    ))
    assert linear.create_issue.call_count == 1

    # Retry mode: only B (now FAILED is the target, A is now SENT from above).
    linear.create_issue.reset_mock()
    list(send_tasks_iter(
        tasks, team_id="t", linear_client=linear,
        on_status_change=lambda *a, **kw: None,
        cancel_check=lambda: False, retry_failed=True,
    ))
    assert linear.create_issue.call_count == 1


# ── Status transitions ──────────────────────────────────────────────


def test_send_iter_transitions_through_sending_then_sent_on_success():
    task = _pending_task("A", local_id="a", priority=Priority.HIGH)
    linear = _make_linear([{
        "id": "uuid-1", "identifier": "ENG-101",
        "url": "https://linear.app/x/ENG-101",
    }])
    seen = []
    list(send_tasks_iter(
        [task], team_id="t", linear_client=linear,
        on_status_change=lambda t, s, **kw: seen.append(s),
        cancel_check=lambda: False,
    ))
    # Transitioned PENDING → SENDING → SENT
    assert seen == [TaskStatus.SENDING, TaskStatus.SENT]
    assert task.status is TaskStatus.SENT
    assert task.linear_issue_id == "ENG-101"
    assert task.linear_issue_url == "https://linear.app/x/ENG-101"
    assert task.send_error is None


def test_send_iter_transitions_to_failed_on_linear_error():
    from tasks.linear_client import LinearError

    task = _pending_task("A", local_id="a")
    linear = _make_linear(raise_on={0: LinearError("Linear вернул 401: unauth")})
    seen = []
    list(send_tasks_iter(
        [task], team_id="t", linear_client=linear,
        on_status_change=lambda t, s, **kw: seen.append(s),
        cancel_check=lambda: False,
    ))
    assert seen == [TaskStatus.SENDING, TaskStatus.FAILED]
    assert task.status is TaskStatus.FAILED
    assert task.send_error  # short code extracted
    assert "401" in task.send_error


def test_send_iter_extracts_short_error_code_from_linear_message():
    """Linear's full message is logged; status badge just needs a short code."""
    from tasks.linear_client import LinearError
    task = _pending_task("A", local_id="a")

    cases = [
        (LinearError("Linear вернул 429 rate-limit"), "429"),
        (LinearError("Linear вернул 500: ..."), "500"),
        (LinearError("Нет соединения с Linear: ..."), "network"),
        (LinearError("Таймаут Linear (>30s)"), "timeout"),
        (LinearError("Linear GraphQL: ошибка запроса"), "error"),
    ]
    for err, expected_code in cases:
        task.status = TaskStatus.PENDING
        task.send_error = None
        linear = _make_linear(raise_on={0: err})
        list(send_tasks_iter(
            [task], team_id="t", linear_client=linear,
            on_status_change=lambda *a, **kw: None,
            cancel_check=lambda: False,
        ))
        assert expected_code in (task.send_error or ""), \
            f"expected {expected_code} in {task.send_error!r} for {err}"


# ── Cancellation ────────────────────────────────────────────────────


def test_send_iter_stops_on_cancel_between_tasks():
    """Cancel checked BEFORE each create_issue. Already-sent stays sent."""
    tasks = [_pending_task(f"T{i}", local_id=str(i)) for i in range(5)]
    linear = _make_linear()
    cancel_count = [0]

    def cancel_check():
        cancel_count[0] += 1
        # Trigger cancel after the 2nd send completes (3rd cancel_check).
        if cancel_count[0] >= 3:
            return True
        return False

    list(send_tasks_iter(
        tasks, team_id="t", linear_client=linear,
        on_status_change=lambda *a, **kw: None,
        cancel_check=cancel_check,
    ))
    # Should have sent 2 tasks then bailed.
    assert linear.create_issue.call_count == 2
    assert tasks[0].status is TaskStatus.SENT
    assert tasks[1].status is TaskStatus.SENT
    assert tasks[2].status is TaskStatus.PENDING   # not started
    assert tasks[3].status is TaskStatus.PENDING
    assert tasks[4].status is TaskStatus.PENDING


# ── Linear API kwargs construction ──────────────────────────────────


def test_send_iter_passes_priority_as_int_to_linear():
    """Linear's priority is int 0-4; Task.priority is the IntEnum."""
    task = _pending_task("A", priority=Priority.URGENT)
    linear = _make_linear()
    list(send_tasks_iter(
        [task], team_id="t", linear_client=linear,
        on_status_change=lambda *a, **kw: None,
        cancel_check=lambda: False,
    ))
    kwargs = linear.create_issue.call_args.kwargs
    assert kwargs["priority"] == 1   # URGENT.value == 1
    assert kwargs["team_id"] == "t"
    assert kwargs["title"] == "A"


def test_send_iter_omits_priority_when_none():
    """Linear treats missing priority as 'leave default'. Don't pass 0."""
    task = _pending_task("A", priority=Priority.NONE)
    linear = _make_linear()
    list(send_tasks_iter(
        [task], team_id="t", linear_client=linear,
        on_status_change=lambda *a, **kw: None,
        cancel_check=lambda: False,
    ))
    kwargs = linear.create_issue.call_args.kwargs
    assert "priority" not in kwargs


def test_send_iter_passes_assignee_label_due_date():
    task = _pending_task(
        "A", assignee_id="u-1", label_ids=["l-1"], due_date="2026-05-15",
    )
    linear = _make_linear()
    list(send_tasks_iter(
        [task], team_id="t", linear_client=linear,
        on_status_change=lambda *a, **kw: None,
        cancel_check=lambda: False,
    ))
    kwargs = linear.create_issue.call_args.kwargs
    assert kwargs["assignee_id"] == "u-1"
    assert kwargs["label_ids"] == ["l-1"]
    assert kwargs["due_date"] == "2026-05-15"
