# Meeting Tasks Pipeline — Phase 6.3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Close the loop. Add a "Отправить выбранные в Linear" button to the editor. For each selected task, POST to Linear via `LinearClient.create_issue()`. Show per-task status: pending → sending → sent (✓) / failed (⚠). Retry button for failed. Successful tasks open in browser on click.

**Architecture:** New send worker thread that iterates selected tasks one at a time, calling `linear_client.create_issue()` per task. Status updates marshalled via `self.after(0, ...)` to update each row's UI badge. Per-task `Task.status` field (already in schema as `TaskStatus` enum from Phase 6.0) is the source of truth. After every status change, save `tasks.json` so a crash mid-send leaves accurate state on disk.

**Tech Stack:** Same as 6.2. Plus stdlib `webbrowser` for opening Linear issue URLs on click.

**Spec:** [docs/superpowers/specs/2026-04-28-meeting-tasks-pipeline-design.md](../specs/2026-04-28-meeting-tasks-pipeline-design.md) (Phasing → Phase 6.3; UI Design → Phase 6.3 send + statuses; Error handling matrix; Cancellation).

**Baseline (after Phase 6.2):**
- 127 tests passing
- `LinearClient.create_issue()` already shipped in Phase 6.0 — used as-is
- `Task.status: TaskStatus` field + `TaskStatus.{PENDING, SENDING, SENT, FAILED, SKIPPED}` enum already in schema
- `Task.linear_issue_id`, `linear_issue_url`, `send_error` fields already in schema
- `tasks.json` mutable persistence already wired

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `ui/dialogs/extract_tasks.py` | Modify | Add Send button + status badges + retry button + send worker (~200 lines) |
| `tests/test_tasks_send.py` | **Create** | Unit tests for the send orchestrator helper (10 tests) |
| `tasks/sender.py` | **Create** | Pure orchestrator helper (`send_tasks_iter`) for unit-testability |

**Why split sender out:** The send loop has nontrivial logic (which tasks to send, status-transition rules, retry semantics, Linear-issue-id tracking). Keeping it pure and Tk-free lets us unit-test it. The dialog wraps it in a thread + UI updates.

---

## Decisions baked in

1. **Send only `selected=True && status=PENDING` tasks.** Already-`SENT` tasks are skipped (don't double-create). `FAILED` tasks are skipped (use Retry button). `SKIPPED` (`selected=False`) are skipped.

2. **Retry sends only `FAILED` tasks** (not pending). This is intentional: if the initial send had a partial failure, sent tasks shouldn't be retouched.

3. **Status badges replace the checkbox** after send starts (per spec mockup). For each row: `_TaskRow` gets a new mode that renders one of: `☑/☐` (pending), `⏳` (sending), `✓` + Linear-id (sent), `⚠` + error code (failed), `—` (skipped).

4. **Click on sent row opens Linear issue in browser** via `webbrowser.open(task.linear_issue_url)`. Other clicks (pending/failed) still select the task in the editor as in 6.2.

5. **Per-task save after every status change.** This is N saves for N tasks vs one bulk save at end. Slightly higher I/O but crash-safe (mid-send crash leaves accurate state). Atomic write means each save is fast.

6. **Cancel-on-close still works mid-send.** When user clicks Закрыть during send: cancel_event fires → worker detects between issues → exits. Already-sent issues stay sent (Linear can't be undone safely).

7. **`Task.send_error` carries a short HTTP-style code.** From the error message (`"401"`, `"429"`, `"500"`, `"network"`, `"timeout"`, etc.) — NOT the full message (which would overflow the badge). Full message goes to `logs/app.log` via `logger.exception`.

8. **Linear-issue-id format on row**: short identifier like `ENG-1234` (from `issue["identifier"]`), not the URL.

9. **No throttling between issues.** Linear's rate limit is 1500/hour per personal API key. A 30-task send is well under. If we ever see 429 in the wild, that triggers FAILED state which the user can retry — sufficient for now. (Carry-forward to 6.4 if needed.)

10. **The send button label updates dynamically**: shows count of pending+selected tasks. E.g. `Отправить выбранные (3)`. After sending, becomes `Отправить выбранные (0)` and disables. After failures, the Retry button becomes enabled.

---

## Task 1: Sender module (pure orchestrator + tests)

**Goal:** A `send_tasks_iter(tasks, *, linear_client, on_status_change, cancel_check)` generator function that orchestrates the send loop with status callbacks. Pure, no I/O outside the LinearClient calls. Fully unit-testable with mocked clients.

**Files:**
- Create: `tasks/sender.py` (~80 lines)
- Create: `tests/test_tasks_send.py` (~150 lines)

- [ ] **Step 1.1: Write failing tests for `send_tasks_iter`**

Create `tests/test_tasks_send.py`:

```python
"""Tests for tasks.sender — pure orchestrator with mocked LinearClient."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tasks.schema import Priority, Task, TaskStatus
from tasks.sender import send_tasks_iter


def _pending_task(title="T", **kw) -> Task:
    return Task(title=title, selected=True, status=TaskStatus.PENDING, **kw)


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
    cancel_after = [False]
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
    assert "priority" not in kwargs or kwargs["priority"] is None


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
```

- [ ] **Step 1.2: Run tests — confirm ImportError**

Run: `pytest tests/test_tasks_send.py -v`
Expected: All FAIL — `ModuleNotFoundError: No module named 'tasks.sender'`.

- [ ] **Step 1.3: Implement `tasks/sender.py`**

Create `tasks/sender.py`:

```python
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
from typing import Callable, Iterator

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
            task.send_error = _short_error_code(str(e))
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
    # HTTP status codes
    import re
    m = re.search(r"\b(4\d\d|5\d\d)\b", msg)
    if m:
        return m.group(1)
    if "соединен" in msg_lower or "connection" in msg_lower:
        return "network"
    if "таймаут" in msg_lower or "timeout" in msg_lower:
        return "timeout"
    return ""
```

- [ ] **Step 1.4: Run tests — verify pass**

Run: `pytest tests/test_tasks_send.py -v`
Expected: All 10 tests PASS.

- [ ] **Step 1.5: Run full suite**

Run: `pytest tests/ -v`
Expected: 137 passed (127 + 10).

- [ ] **Step 1.6: Commit**

```bash
git add tasks/sender.py tests/test_tasks_send.py
git commit -m "feat(sender): pure send orchestrator + 10 tests"
```

---

## Task 2: Wire Send + Retry buttons into the dialog

**Goal:** Add `Отправить выбранные (N)` button + `Повторить упавшие` button + worker thread that drives `send_tasks_iter` + per-row status badges that replace checkboxes during/after send.

**Files:**
- Modify: `ui/dialogs/extract_tasks.py` (~150 line delta)

- [ ] **Step 2.1: Extend `_TaskRow` to render status badges**

Find the `_TaskRow` class. Add a `set_status_visual(status, *, identifier=None, error_code=None)` method that swaps the checkbox display for a status badge:

```python
    def set_status_visual(
        self, status, *, identifier: str | None = None,
        error_code: str | None = None,
    ) -> None:
        """Replace checkbox with a status badge after send begins.

        Status icons:
            PENDING — keep checkbox (no change)
            SENDING — ⏳ blue
            SENT    — ✓ green + identifier
            FAILED  — ⚠ red + error_code
            SKIPPED — — gray
        """
        from tasks.schema import TaskStatus
        # PENDING reverts to checkbox.
        if status is TaskStatus.PENDING:
            self._check.grid()  # show
            if hasattr(self, "_status_badge"):
                self._status_badge.grid_remove()
            return

        # Lazy-create badge label.
        if not hasattr(self, "_status_badge"):
            self._status_badge = ctk.CTkLabel(
                self, text="", width=28,
                font=ctk.CTkFont(family=FONT, size=14, weight="bold"),
                anchor="center",
            )
            self._status_badge.grid(row=0, column=0, padx=(8, 6), pady=4, sticky="w")

        # Hide the checkbox; show the badge.
        self._check.grid_remove()
        self._status_badge.grid()

        if status is TaskStatus.SENDING:
            self._status_badge.configure(text="⏳", text_color=BLUE_DIM)
        elif status is TaskStatus.SENT:
            self._status_badge.configure(text="✓", text_color=GREEN)
            # Append identifier to summary so user sees ENG-1234 next to title.
            if identifier:
                self._lbl_summary.configure(
                    text=f"{self._summary_text()}  ·  {identifier}",
                )
        elif status is TaskStatus.FAILED:
            code = error_code or "?"
            self._status_badge.configure(text=f"⚠{code}", text_color=RED)
        elif status is TaskStatus.SKIPPED:
            self._status_badge.configure(text="—", text_color=TEXT_SECONDARY)
```

(`BLUE_DIM` is already imported. `GREEN`, `RED`, `TEXT_SECONDARY` should be there too — verify the imports.)

Also bind the row's click for SENT-state opening of Linear URL. Modify `_handle_click` to:
```python
    def _handle_click(self, _event=None):
        # If already sent, click opens the Linear issue in browser.
        from tasks.schema import TaskStatus
        if self._task.status is TaskStatus.SENT and self._task.linear_issue_url:
            import webbrowser
            webbrowser.open(self._task.linear_issue_url)
            return
        self._on_select(self._task)
```

- [ ] **Step 2.2: Add Send + Retry buttons to the dialog footer**

Currently the dialog footer has just `[Закрыть]`. Add a left-aligned area for send-state + the two new buttons. Find the footer block in `_build_ui`:

```python
        # --- Footer: saved-path + close ---
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, padx=16, pady=(2, 14), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        self._saved_label = label(footer, "", anchor="w")
        self._saved_label.grid(row=0, column=0, sticky="ew")
        tonal_button(
            footer, text="Закрыть", command=self._on_close, width=110,
        ).grid(row=0, column=1, sticky="e")
```

Replace with:

```python
        # --- Footer: saved-path + send buttons + close ---
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, padx=16, pady=(2, 14), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        self._saved_label = label(footer, "", anchor="w")
        self._saved_label.grid(row=0, column=0, sticky="ew")

        self._btn_send = primary_button(
            footer, text="Отправить выбранные (0)",
            command=self._on_send_clicked, width=220, state="disabled",
        )
        self._btn_send.grid(row=0, column=1, padx=(8, 4), sticky="e")

        self._btn_retry = tonal_button(
            footer, text="Повторить упавшие", command=self._on_retry_clicked,
            width=170, state="disabled",
        )
        self._btn_retry.grid(row=0, column=2, padx=(0, 4), sticky="e")

        tonal_button(
            footer, text="Закрыть", command=self._on_close, width=110,
        ).grid(row=0, column=3, sticky="e")
```

- [ ] **Step 2.3: Add a helper `_refresh_send_button_label`**

Append to the dialog:

```python
    def _refresh_send_button_label(self) -> None:
        """Update Send button label to reflect count of pending+selected,
        and Retry button enable state to reflect failed count."""
        from tasks.schema import TaskStatus
        pending_count = sum(
            1 for t in self._tasks
            if t.selected and t.status is TaskStatus.PENDING
        )
        failed_count = sum(
            1 for t in self._tasks if t.status is TaskStatus.FAILED
        )
        self._btn_send.configure(
            text=f"Отправить выбранные ({pending_count})",
            state="normal" if pending_count > 0 else "disabled",
        )
        self._btn_retry.configure(
            state="normal" if failed_count > 0 else "disabled",
        )
```

Call it from:
- End of `_render_task_list` (so initial state is right after extract or load)
- End of `_persist_current_task` (so checkbox toggles update the count)
- End of every status transition callback (so during send the count decreases live)
- End of `_on_select_all` / `_on_select_none` / `_on_add_task` / `_on_delete_task` / `_undo`

(That's a lot of call sites. Easier: call it from `_save_tasks_to_disk` since that's already the central post-mutation hook. Inspect — yes, every mutation goes through there. Add the call as the last line of `_save_tasks_to_disk`.)

- [ ] **Step 2.4: Implement `_on_send_clicked` and `_on_retry_clicked`**

Append:

```python
    def _on_send_clicked(self) -> None:
        self._start_send(retry_failed=False)

    def _on_retry_clicked(self) -> None:
        self._start_send(retry_failed=True)

    def _start_send(self, *, retry_failed: bool) -> None:
        """Spin up the send worker thread."""
        if not self._meta.get("team_id"):
            messagebox.showwarning(
                "Нет команды",
                "Не могу отправить — потерян контекст команды. Перезапустите извлечение.",
            )
            return

        # Persist any pending form edits before sending so saved-state matches.
        self._persist_current_task()

        self._set_busy(True)
        # Disable send/retry buttons during work — also handled by _set_busy
        # if you've added them to its list.
        self._btn_send.configure(state="disabled")
        self._btn_retry.configure(state="disabled")

        threading.Thread(
            target=self._run_send_worker,
            args=(retry_failed,),
            daemon=True,
        ).start()
```

- [ ] **Step 2.5: Implement `_run_send_worker`**

Append:

```python
    def _run_send_worker(self, retry_failed: bool) -> None:
        """Worker thread: iterate selected tasks and POST each to Linear."""
        from tasks.linear_client import LinearClient
        from tasks.sender import send_tasks_iter

        api_key = (self._config.get("linear_api_key") or "").strip()
        if not api_key:
            if not self._cancel_event.is_set():
                self.after(0, self._on_send_finished, "Нет ключа Linear.")
            return

        linear = LinearClient(api_key)
        self._active_clients.append(linear)
        team_id = self._meta["team_id"]

        try:
            for _ in send_tasks_iter(
                self._tasks,
                team_id=team_id,
                linear_client=linear,
                on_status_change=self._on_send_status_change,
                cancel_check=self._cancel_event.is_set,
                retry_failed=retry_failed,
            ):
                pass  # generator drives the work; we don't need the values
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("send worker crashed")
            if not self._cancel_event.is_set():
                self.after(0, self._on_send_finished, str(e))
        finally:
            try:
                linear.close()
            except Exception:
                pass
            if linear in self._active_clients:
                self._active_clients.remove(linear)

        if not self._cancel_event.is_set():
            self.after(0, self._on_send_finished, None)

    def _on_send_status_change(self, task, new_status, **kw) -> None:
        """Called from worker thread for every status transition.

        Marshal UI update back to main thread; persist tasks.json after each
        transition so a crash leaves accurate state.
        """
        if self._cancel_event.is_set():
            return
        # Save first (atomic disk write — safe from any thread).
        try:
            from tasks.persistence import save_tasks
            save_tasks(self._history_folder, self._tasks, self._meta)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("save_tasks during send failed")

        # Then UI update on main thread.
        if not self._cancel_event.is_set():
            self.after(0, self._update_row_status, task)

    def _update_row_status(self, task) -> None:
        """Main-thread UI update for one row."""
        from tasks.schema import TaskStatus
        # Find the row by identity.
        for row in getattr(self, "_task_rows", []):
            if row._task is task:
                row.set_status_visual(
                    task.status,
                    identifier=task.linear_issue_id,
                    error_code=task.send_error,
                )
                break
        # Refresh send/retry button labels live.
        self._refresh_send_button_label()

    def _on_send_finished(self, error_msg: str | None) -> None:
        """Main-thread completion callback."""
        self._set_busy(False)
        self._refresh_send_button_label()
        if error_msg:
            self._status_label.configure(
                text=f"✗ Отправка прервана: {error_msg}", text_color=RED,
            )
        else:
            from tasks.schema import TaskStatus
            sent = sum(1 for t in self._tasks if t.status is TaskStatus.SENT)
            failed = sum(1 for t in self._tasks if t.status is TaskStatus.FAILED)
            self._status_label.configure(
                text=f"✓ Отправлено: {sent} · ✗ Ошибок: {failed}",
                text_color=GREEN if failed == 0 else RED,
            )
```

- [ ] **Step 2.6: Update `_set_busy` to disable Send/Retry too**

Find `_set_busy`. Add `_btn_send` and `_btn_retry` to the buttons list. Note: send/retry button states are also dynamically managed by `_refresh_send_button_label`, but during busy the wholesale disable is correct.

After `_set_busy(False)`, `_refresh_send_button_label()` will be called from `_on_send_finished` and will re-enable Send if pending tasks remain.

- [ ] **Step 2.7: Static checks**

```
python -m py_compile ui/dialogs/extract_tasks.py
python -c "from ui.dialogs.extract_tasks import ExtractTasksDialog"
pytest tests/ -v 2>&1 | tail -3
```

Must report 137 passed.

- [ ] **Step 2.8: Commit**

```bash
git add ui/dialogs/extract_tasks.py
git commit -m "feat(extract): Send/Retry buttons + per-task status badges + send worker"
```

---

## Task 3: Final smoke + handoff for Phase 6.2 + 6.3 combined

**Goal:** Final pytest + write a unified handoff that covers both 6.2 and 6.3 (since they ship together).

- [ ] **Step 3.1: Run full pytest**

```
pytest tests/ -v 2>&1 | tail -3
```

Expected: 137 passed.

- [ ] **Step 3.2: Visual smoke checklist (HUMAN — deferred to user before tag)**

After all subagent commits land, the human runs:

**Editor smoke (Phase 6.2):**
1. `python app.py` → transcribe a short Russian audio file → click Извлечь задачи → click Извлечь.
2. Wait for ✓ Извлечено N задач.
3. Editor visible: split layout, left list with row widgets, right form populated with first task's fields.
4. Click a different task → form switches to its values.
5. Edit title, watch left list summary update.
6. Change priority dropdown.
7. Click + Добавить → empty new task appears, auto-selected.
8. Click 🗑 Удалить → task removed.
9. Press Ctrl+Z → deleted task returns.
10. Click ✗ Снять → all checkboxes clear.
11. Close dialog (X / Закрыть).
12. Re-open Извлечь задачи → editor loads existing tasks.json without re-extract.
13. Inspect `history/<entry>/tasks.json` — content matches editor state.

**Send smoke (Phase 6.3):**
14. With a task list of 2-3 selected tasks, click "Отправить выбранные (N)".
15. Status badges replace checkboxes:
    - During send: ⏳ blue badge appears
    - On success: ✓ green + ENG-XXXX identifier appended to summary line
    - On failure: ⚠ red + short error code (e.g. "401")
16. Status label at bottom: "✓ Отправлено: N · ✗ Ошибок: M".
17. Click on a SENT row → opens the Linear issue in browser.
18. Open Linear web app → confirm 2-3 new issues exist with correct title/priority/assignee/labels.
19. If any failed: click "Повторить упавшие" → retries only failed.
20. Cancel test: click Извлечь, get tasks, click Send, then [Закрыть] mid-send. App closes cleanly. Already-sent tasks stay sent in tasks.json on disk.

Acceptance: end-to-end transcript→Linear issues works; statuses are correct; cancel-mid-send doesn't crash.

- [ ] **Step 3.3: Write combined handoff doc**

Create `docs/superpowers/handoffs/2026-04-29-phase-6.3-to-6.4-handoff.md` (covers 6.2 + 6.3 ship-together state). Mirror structure of 6.0→6.1 and 6.1→6.2 handoffs.

- [ ] **Step 3.4: Commit handoff**

```bash
git add docs/superpowers/handoffs/2026-04-29-phase-6.3-to-6.4-handoff.md
git commit -m "docs: Phase 6.3 → 6.4 handoff (carry-forwards from 6.2 + 6.3 reviews)"
```

- [ ] **Step 3.5: Tag both phases (after smoke passes)**

After human visual smoke passes:

```bash
git tag -a phase-6.2 -m "Phase 6.2: master-detail editor + tasks.json"
git tag -a phase-6.3 -m "Phase 6.3: send to Linear + per-task statuses + retry"
git checkout main
git merge phase-6.2-edit --ff-only
```

(One ff-merge brings both phase-6.2 and phase-6.3 onto main, since 6.3 was committed on the same branch as 6.2.)

---

## Spec coverage map (Phase 6.3)

| Spec requirement | Implemented in | Verified by |
|---|---|---|
| "Отправить выбранные в Linear" button | Task 2.2 (`_btn_send`) | Smoke 3.2.14 |
| Per-task statuses (✓ ⚠ ⏳ ☑ —) | Task 2.1 (`_TaskRow.set_status_visual`) | Smoke 3.2.15 |
| "Повторить упавшие" button | Task 2.2 (`_btn_retry`) | Smoke 3.2.19 |
| Successful tasks open in browser on click | Task 2.1 (`_handle_click` SENT branch) | Smoke 3.2.17 |
| Linear issue identifier shown on row | Task 2.1 (summary append) | Smoke 3.2.15 |
| Already-sent tasks NOT retouched on retry | Task 1 (`_should_send`) | Test `test_send_iter_skips_already_sent_tasks` |
| Cancel-on-close mid-send | Task 2.5 (`cancel_check=self._cancel_event.is_set`) | Smoke 3.2.20 |
| Per-task save after every status change | Task 2.5 (`_on_send_status_change`) | Smoke 3.2.13 (after partial send) |
| Status label at bottom shows N/M | Task 2.5 (`_on_send_finished`) | Smoke 3.2.16 |
| Send button label dynamic count | Task 2.3 (`_refresh_send_button_label`) | Smoke 3.2.14 |
| Short error code in badge | Task 1 (`_short_error_code`) | Test `test_send_iter_extracts_short_error_code_from_linear_message` |

## Out-of-scope (Phase 6.4)

- Throttling / rate-limit handling beyond surfacing errors as FAILED
- Bulk model A/B comparison
- Re-open from History dialog
- Custom prompts per team
- AssemblyAI Validate parity
