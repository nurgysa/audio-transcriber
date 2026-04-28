# Meeting Tasks Pipeline — Phase 6.0 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lay the foundation for the Meeting Tasks Pipeline by adding a `tasks/` package containing the data schema and HTTP clients for OpenRouter and Linear, plus two new sections in the Settings dialog with key validation. No main-window changes — purely infrastructure.

**Architecture:** New `tasks/` Python package contains a `Task` dataclass, `Priority`/`TaskStatus` enums (used in later phases), and two thin HTTP clients (`openrouter_client.py`, `linear_client.py`). The Settings dialog grows two sections following the existing `_build_*_section` pattern. API keys persist via existing `load_config`/`save_config`. Validate buttons make a single cheap request each (OpenRouter `/auth/key`, Linear GraphQL `viewer`) for live feedback. Tests follow the existing pure-function pytest pattern; HTTP clients are tested with `unittest.mock.patch` of `requests`.

**Spec deviation note:** The design spec mentions `httpx` for cancellation. We use **`requests`** (already in `requirements.txt` and used by `providers/assemblyai.py`) to match codebase convention. The cancellation requirement (close-from-other-thread to interrupt in-flight) is satisfied by `requests.Session.close()` plus per-request `timeout=`. No new dependencies for Phase 6.0.

**Tech Stack:** Python 3.10, `requests` (existing), CustomTkinter (existing), `pytest` + `unittest.mock` (existing).

---

## Files Created

| File | Responsibility |
|---|---|
| `tasks/__init__.py` | Empty marker. |
| `tasks/schema.py` | `Task` dataclass, `Priority` and `TaskStatus` enums, `to_dict` / `from_dict` helpers. |
| `tasks/openrouter_client.py` | Thin REST wrapper. Methods: `validate_key()`, `complete(model, messages, json_mode)`. |
| `tasks/linear_client.py` | Thin GraphQL wrapper. Methods: `validate_key()`, `bootstrap()`, `team_context(team_id)`, `create_issue(team_id, task)`. |
| `tests/test_tasks_schema.py` | Schema unit tests. |
| `tests/test_tasks_openrouter_client.py` | OpenRouter client tests with mocked `requests`. |
| `tests/test_tasks_linear_client.py` | Linear client tests with mocked `requests`. |

## Files Modified

| File | What changes |
|---|---|
| `ui/dialogs/settings.py` | Add `_build_openrouter_section` and `_build_linear_section`. Add `_validate_openrouter` and `_validate_linear` callbacks. Two new state vars on the dialog. |

## Files NOT changed in Phase 6.0

`ui/app.py`, `utils.py`, `requirements.txt`, `transcriber.py`, `recorder.py` — all untouched.

---

### Task 0: Create `tasks/` package skeleton

**Files:**
- Create: `tasks/__init__.py`

- [ ] **Step 1: Create empty package marker**

```bash
mkdir -p tasks
```

Create `tasks/__init__.py` with content:

```python
"""tasks/ — meeting-tasks pipeline.

Submodules:
- schema: Task dataclass and enums.
- openrouter_client: thin REST wrapper for OpenRouter chat completions.
- linear_client: thin GraphQL wrapper for Linear (viewer/teams/issues).
- extractor: (Phase 6.1) orchestrator that turns a transcript into Task[].
- persistence: (Phase 6.1) save/load tasks_raw.json and tasks.json.
"""
```

- [ ] **Step 2: Verify package importable**

Run from project root:

```bash
python -c "import tasks; print(tasks.__doc__[:50])"
```

Expected: prints `"tasks/ — meeting-tasks pipeline.\n\nSubmodules:"`

- [ ] **Step 3: Commit**

```bash
git add tasks/__init__.py
git commit -m "feat(tasks): create tasks/ package skeleton"
```

---

### Task 1: `Priority` IntEnum

**Files:**
- Create: `tasks/schema.py`
- Test: `tests/test_tasks_schema.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tasks_schema.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_tasks_schema.py -v
```

Expected: ImportError or `ModuleNotFoundError: No module named 'tasks.schema'`.

- [ ] **Step 3: Implement Priority + lookup helper**

Create `tasks/schema.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_tasks_schema.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tasks/schema.py tests/test_tasks_schema.py
git commit -m "feat(tasks): Priority enum with case-insensitive lookup"
```

---

### Task 2: `TaskStatus` Enum

**Files:**
- Modify: `tasks/schema.py`
- Modify: `tests/test_tasks_schema.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tasks_schema.py`:

```python
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
```

- [ ] **Step 2: Run, verify fails**

```bash
pytest tests/test_tasks_schema.py::test_task_status_string_values -v
```

Expected: `ImportError: cannot import name 'TaskStatus'`.

- [ ] **Step 3: Implement TaskStatus**

Append to `tasks/schema.py` (after `Priority` and before `priority_from_string`):

```python
from enum import Enum  # add to existing import block at top

class TaskStatus(Enum):
    """Send-to-Linear status for a Task. Used in Phase 6.3+.

    Stored in tasks.json by .value (string) so JSON stays readable.
    """
    PENDING = "pending"   # not yet attempted
    SENDING = "sending"   # in flight
    SENT    = "sent"      # successfully created in Linear
    FAILED  = "failed"    # last attempt failed (see send_error)
    SKIPPED = "skipped"   # user unchecked the task
```

Adjust the imports at the top of `tasks/schema.py`:

```python
from enum import Enum, IntEnum
```

- [ ] **Step 4: Run, verify passes**

```bash
pytest tests/test_tasks_schema.py -v
```

Expected: 5 tests pass total.

- [ ] **Step 5: Commit**

```bash
git add tasks/schema.py tests/test_tasks_schema.py
git commit -m "feat(tasks): TaskStatus enum for Linear send pipeline"
```

---

### Task 3: `Task` dataclass with defaults

**Files:**
- Modify: `tasks/schema.py`
- Modify: `tests/test_tasks_schema.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tasks_schema.py`:

```python
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
```

- [ ] **Step 2: Run, verify fails**

```bash
pytest tests/test_tasks_schema.py::test_task_minimum_creation_with_only_title -v
```

Expected: `ImportError: cannot import name 'Task'`.

- [ ] **Step 3: Implement Task dataclass**

Append to `tasks/schema.py`:

```python
import uuid
from dataclasses import dataclass, field
from typing import Optional


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
```

Adjust imports at the top of `tasks/schema.py`:

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Optional
```

- [ ] **Step 4: Run, verify passes**

```bash
pytest tests/test_tasks_schema.py -v
```

Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tasks/schema.py tests/test_tasks_schema.py
git commit -m "feat(tasks): Task dataclass with rich fields"
```

---

### Task 4: `Task.to_dict` / `Task.from_dict`

**Files:**
- Modify: `tasks/schema.py`
- Modify: `tests/test_tasks_schema.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tasks_schema.py`:

```python
# ── Serialization round-trip ──────────────────────────────────────────


def test_task_round_trip_minimal():
    """Task → dict → Task preserves all fields when minimal."""
    from tasks.schema import Task
    original = Task(title="Hello")
    restored = Task.from_dict(original.to_dict())
    assert restored == original


def test_task_round_trip_full():
    """Round-trip with every field populated."""
    from tasks.schema import Task, Priority, TaskStatus
    original = Task(
        title="Починить login",
        description="Многострочное\nописание",
        priority=Priority.HIGH,
        assignee_id="user-uuid",
        assignee_name="Айдар",
        label_ids=["lbl-1", "lbl-2"],
        label_names=["bug", "mobile"],
        due_date="2026-05-15",
        local_id="custom-id",
        selected=False,
        status=TaskStatus.SENT,
        linear_issue_id="ENG-1234",
        linear_issue_url="https://linear.app/x/issue/ENG-1234",
        send_error=None,
    )
    restored = Task.from_dict(original.to_dict())
    assert restored == original


def test_task_to_dict_uses_string_values_for_enums():
    """JSON file must contain 'high' (string), not 2 (int) for priority."""
    from tasks.schema import Task, Priority, TaskStatus
    t = Task(title="X", priority=Priority.HIGH, status=TaskStatus.SENT)
    d = t.to_dict()
    assert d["priority"] == "high"
    assert d["status"] == "sent"


def test_task_from_dict_tolerates_missing_optional_keys():
    """Old tasks_raw.json (pre-Phase-6.3) won't have status/linear_*. Use defaults."""
    from tasks.schema import Task, TaskStatus
    minimal = {"title": "Old task", "local_id": "uid"}
    t = Task.from_dict(minimal)
    assert t.title == "Old task"
    assert t.local_id == "uid"
    assert t.status is TaskStatus.PENDING
    assert t.linear_issue_id is None
```

- [ ] **Step 2: Run, verify fails**

```bash
pytest tests/test_tasks_schema.py::test_task_round_trip_minimal -v
```

Expected: `AttributeError: type object 'Task' has no attribute 'from_dict'`.

- [ ] **Step 3: Implement to_dict / from_dict**

Add methods to the `Task` dataclass in `tasks/schema.py`:

```python
@dataclass
class Task:
    # ... existing fields ...

    def to_dict(self) -> dict:
        """Serialize to JSON-friendly dict. Enums become their .value (str)."""
        return {
            "local_id": self.local_id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority.name.lower(),    # 'high', not 2
            "assignee_id": self.assignee_id,
            "assignee_name": self.assignee_name,
            "label_ids": list(self.label_ids),
            "label_names": list(self.label_names),
            "due_date": self.due_date,
            "selected": self.selected,
            "status": self.status.value,
            "linear_issue_id": self.linear_issue_id,
            "linear_issue_url": self.linear_issue_url,
            "send_error": self.send_error,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        """Inverse of to_dict. Tolerant of missing optional fields.

        Older tasks.json files (pre-Phase-6.3) may lack status/linear_*;
        we apply defaults rather than raising.
        """
        return cls(
            title=d["title"],
            description=d.get("description", ""),
            priority=priority_from_string(d.get("priority")),
            assignee_id=d.get("assignee_id"),
            assignee_name=d.get("assignee_name"),
            label_ids=list(d.get("label_ids", [])),
            label_names=list(d.get("label_names", [])),
            due_date=d.get("due_date"),
            local_id=d.get("local_id") or str(uuid.uuid4()),
            selected=d.get("selected", True),
            status=TaskStatus(d.get("status", "pending")),
            linear_issue_id=d.get("linear_issue_id"),
            linear_issue_url=d.get("linear_issue_url"),
            send_error=d.get("send_error"),
        )
```

- [ ] **Step 4: Run, verify passes**

```bash
pytest tests/test_tasks_schema.py -v
```

Expected: 12 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tasks/schema.py tests/test_tasks_schema.py
git commit -m "feat(tasks): Task to_dict / from_dict with enum string round-trip"
```

---

### Task 5: OpenRouter client — module skeleton + headers

**Files:**
- Create: `tasks/openrouter_client.py`

No test in this task — pure scaffolding. Tests start in Task 6.

- [ ] **Step 1: Create the module**

Create `tasks/openrouter_client.py`:

```python
"""Thin REST wrapper around OpenRouter Chat Completions.

We deliberately keep this client dumb: no business logic, no validation
beyond HTTP status. The orchestrator (tasks/extractor.py, Phase 6.1)
builds prompts and parses responses.

Endpoints used:
- POST /chat/completions     — main extraction call
- GET  /auth/key              — Validate button in Settings (also returns balance)
- GET  /models                — Phase 6.4, full model catalog (not yet used)

Authentication: Bearer token in `Authorization` header.
Optional headers (HTTP-Referer, X-Title) help OpenRouter's leaderboard
and don't affect API behavior.
"""
from __future__ import annotations

import requests

_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_TIMEOUT_S = 60.0  # extract calls are slow; 60s covers Sonnet 4.5 on 30-min meetings


class OpenRouterError(Exception):
    """All OpenRouter HTTP/transport failures bubble up as this."""


class OpenRouterClient:
    """One client per session. Reuse it across multiple calls.

    Thread-safe enough for our use case: the underlying requests.Session
    handles concurrent calls via its connection pool.
    """

    def __init__(self, api_key: str):
        if not api_key or not api_key.strip():
            raise OpenRouterError(
                "OpenRouter API ключ не задан. "
                "Откройте Настройки → OpenRouter и вставьте ключ."
            )
        self._api_key = api_key.strip()
        self._session = requests.Session()
        self._session.headers.update(self._build_headers())

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/audio-transcriber",
            "X-Title": "Audio Transcriber",
        }

    def close(self) -> None:
        """Close the underlying connection pool. Safe to call multiple times.

        Used by the dialog's cancel handler to interrupt an in-flight request
        from another thread (closes sockets immediately).
        """
        self._session.close()
```

- [ ] **Step 2: Verify importable**

```bash
python -c "from tasks.openrouter_client import OpenRouterClient, OpenRouterError; print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add tasks/openrouter_client.py
git commit -m "feat(tasks): OpenRouterClient skeleton with auth headers"
```

---

### Task 6: OpenRouter client — `validate_key()`

**Files:**
- Modify: `tasks/openrouter_client.py`
- Create: `tests/test_tasks_openrouter_client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tasks_openrouter_client.py`:

```python
"""Tests for tasks.openrouter_client. HTTP is mocked via unittest.mock."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests   # used by the ConnectionError test below

from tasks.openrouter_client import OpenRouterClient, OpenRouterError


# ── construction ──────────────────────────────────────────────────────


def test_client_rejects_empty_key():
    with pytest.raises(OpenRouterError, match="ключ не задан"):
        OpenRouterClient("")
    with pytest.raises(OpenRouterError):
        OpenRouterClient("   ")


def test_client_strips_whitespace_from_key():
    c = OpenRouterClient("  sk-or-test  ")
    assert c._api_key == "sk-or-test"
    assert c._session.headers["Authorization"] == "Bearer sk-or-test"


# ── validate_key ──────────────────────────────────────────────────────


def test_validate_key_returns_label_and_balance_on_200():
    """OpenRouter /auth/key returns {label, usage, limit} on success."""
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {
        "data": {
            "label": "personal",
            "usage": 5.40,
            "limit": 18.00,
            "is_free_tier": False,
        }
    }
    c = OpenRouterClient("sk-or-test")
    with patch.object(c._session, "get", return_value=fake) as mock_get:
        result = c.validate_key()

    mock_get.assert_called_once()
    assert "/auth/key" in mock_get.call_args[0][0]
    assert result["label"] == "personal"
    assert result["balance_remaining"] == pytest.approx(12.60)  # 18 - 5.40


def test_validate_key_returns_unlimited_when_no_limit():
    """Free tier or unlimited keys have limit=null."""
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {"data": {"label": "free", "usage": 0.10, "limit": None}}
    c = OpenRouterClient("sk-or-test")
    with patch.object(c._session, "get", return_value=fake):
        result = c.validate_key()
    assert result["balance_remaining"] is None


def test_validate_key_raises_on_401():
    fake = MagicMock()
    fake.status_code = 401
    fake.text = '{"error": "Invalid key"}'
    c = OpenRouterClient("sk-or-bad")
    with patch.object(c._session, "get", return_value=fake):
        with pytest.raises(OpenRouterError, match="401"):
            c.validate_key()


def test_validate_key_raises_on_network_failure():
    """ConnectionError from requests bubbles up as OpenRouterError."""
    c = OpenRouterClient("sk-or-test")
    with patch.object(
        c._session, "get",
        side_effect=requests.exceptions.ConnectionError("DNS fail"),
    ):
        import requests
        with pytest.raises(OpenRouterError, match="соединени"):
            c.validate_key()
```

- [ ] **Step 2: Run, verify fails**

```bash
pytest tests/test_tasks_openrouter_client.py -v
```

Expected: `AttributeError: 'OpenRouterClient' object has no attribute 'validate_key'`.

- [ ] **Step 3: Implement validate_key**

Append to `tasks/openrouter_client.py`:

```python
def validate_key(self) -> dict:
    """Cheap GET /auth/key — returns label, usage, balance_remaining.

    On success: returns dict with keys:
        - label: str (human-readable key label)
        - usage: float (USD spent so far)
        - limit: float | None (USD cap, or None for unlimited)
        - balance_remaining: float | None (limit - usage, or None)

    On any HTTP error or network failure, raises OpenRouterError.
    """
    try:
        resp = self._session.get(
            f"{_BASE_URL}/auth/key",
            timeout=10.0,
        )
    except requests.exceptions.ConnectionError as e:
        raise OpenRouterError(f"Нет соединения с OpenRouter: {e}") from e
    except requests.exceptions.Timeout as e:
        raise OpenRouterError("Таймаут подключения к OpenRouter") from e

    if resp.status_code != 200:
        raise OpenRouterError(
            f"OpenRouter вернул {resp.status_code}: {resp.text[:200]}"
        )

    data = resp.json().get("data", {})
    usage = float(data.get("usage", 0.0))
    limit = data.get("limit")  # may be None
    return {
        "label": data.get("label", ""),
        "usage": usage,
        "limit": float(limit) if limit is not None else None,
        "balance_remaining": (float(limit) - usage) if limit is not None else None,
    }
```

- [ ] **Step 4: Run, verify passes**

```bash
pytest tests/test_tasks_openrouter_client.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tasks/openrouter_client.py tests/test_tasks_openrouter_client.py
git commit -m "feat(tasks): OpenRouter validate_key with balance computation"
```

---

### Task 7: OpenRouter client — `complete()`

**Files:**
- Modify: `tasks/openrouter_client.py`
- Modify: `tests/test_tasks_openrouter_client.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tasks_openrouter_client.py`:

```python
# ── complete ──────────────────────────────────────────────────────────


def test_complete_sends_correct_body_with_json_mode():
    """response_format=json_object is set by default."""
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {
        "id": "gen-1",
        "model": "anthropic/claude-sonnet-4.5",
        "choices": [{"message": {"content": '{"tasks": []}'}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }
    c = OpenRouterClient("sk-or-test")
    with patch.object(c._session, "post", return_value=fake) as mock_post:
        result = c.complete(
            model="anthropic/claude-sonnet-4.5",
            messages=[{"role": "user", "content": "hi"}],
            json_mode=True,
        )
    args, kwargs = mock_post.call_args
    body = kwargs["json"]
    assert body["model"] == "anthropic/claude-sonnet-4.5"
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.2
    assert result["content"] == '{"tasks": []}'
    assert result["usage"]["prompt_tokens"] == 100


def test_complete_omits_response_format_when_json_mode_false():
    """For models that don't support JSON mode, allow caller to skip."""
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {
        "choices": [{"message": {"content": "free text"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    c = OpenRouterClient("sk-or-test")
    with patch.object(c._session, "post", return_value=fake) as mock_post:
        c.complete(
            model="some/no-json-model",
            messages=[{"role": "user", "content": "hi"}],
            json_mode=False,
        )
    body = mock_post.call_args.kwargs["json"]
    assert "response_format" not in body


def test_complete_raises_on_400():
    fake = MagicMock()
    fake.status_code = 400
    fake.text = '{"error":{"message":"json mode unsupported"}}'
    c = OpenRouterClient("sk-or-test")
    with patch.object(c._session, "post", return_value=fake):
        with pytest.raises(OpenRouterError, match="400"):
            c.complete(
                model="x/y",
                messages=[{"role": "user", "content": "hi"}],
                json_mode=True,
            )


def test_complete_raises_on_429_with_retry_after():
    """OpenRouterError message should expose Retry-After for caller-side retry."""
    fake = MagicMock()
    fake.status_code = 429
    fake.headers = {"Retry-After": "12"}
    fake.text = '{"error":"rate limited"}'
    c = OpenRouterClient("sk-or-test")
    with patch.object(c._session, "post", return_value=fake):
        with pytest.raises(OpenRouterError, match="429.*12"):
            c.complete(
                model="x/y",
                messages=[{"role": "user", "content": "hi"}],
            )
```

- [ ] **Step 2: Run, verify fails**

```bash
pytest tests/test_tasks_openrouter_client.py::test_complete_sends_correct_body_with_json_mode -v
```

Expected: `AttributeError: ... has no attribute 'complete'`.

- [ ] **Step 3: Implement complete**

Append to `tasks/openrouter_client.py`:

```python
def complete(
    self,
    model: str,
    messages: list[dict],
    json_mode: bool = True,
    temperature: float = 0.2,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> dict:
    """POST /chat/completions and return the parsed response.

    Args:
        model: OpenRouter model slug (e.g. 'anthropic/claude-sonnet-4.5').
        messages: standard OpenAI-style chat messages.
        json_mode: if True, request response_format=json_object. Some models
            reject this with 400; in that case caller should retry with
            json_mode=False and rely on prompt-level instruction.
        temperature: low value (0.2) keeps extraction deterministic.
        timeout: seconds before requests raises Timeout.

    Returns dict:
        - content: str (the assistant message)
        - usage: dict with prompt_tokens / completion_tokens
        - model: str (echoed model slug, useful for logging)

    Raises OpenRouterError on any HTTP or network failure. 429 errors
    include the Retry-After value in the message string for caller-side
    parsing.
    """
    body: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    try:
        resp = self._session.post(
            f"{_BASE_URL}/chat/completions",
            json=body,
            timeout=timeout,
        )
    except requests.exceptions.ConnectionError as e:
        raise OpenRouterError(f"Нет соединения с OpenRouter: {e}") from e
    except requests.exceptions.Timeout as e:
        raise OpenRouterError(f"Таймаут OpenRouter (>{timeout}s)") from e

    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After", "?")
        raise OpenRouterError(f"OpenRouter 429 rate-limit (retry after {retry_after}s)")
    if resp.status_code != 200:
        raise OpenRouterError(
            f"OpenRouter вернул {resp.status_code}: {resp.text[:200]}"
        )

    data = resp.json()
    choice = data["choices"][0]
    return {
        "content": choice["message"]["content"],
        "usage": data.get("usage", {}),
        "model": data.get("model", model),
    }
```

- [ ] **Step 4: Run, verify passes**

```bash
pytest tests/test_tasks_openrouter_client.py -v
```

Expected: 10 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tasks/openrouter_client.py tests/test_tasks_openrouter_client.py
git commit -m "feat(tasks): OpenRouter complete() with json mode + 429 surfacing"
```

---

### Task 8: Linear client — module skeleton + GraphQL helper

**Files:**
- Create: `tasks/linear_client.py`

- [ ] **Step 1: Create the module**

Create `tasks/linear_client.py`:

```python
"""Thin GraphQL wrapper around api.linear.app.

Three operations used across all phases:
- Bootstrap query (validate_key + list_teams in one round-trip)
- TeamContext query (members + labels for a given team)
- CreateIssue mutation (Phase 6.3)

Linear quirk: Authorization header is the raw API key (NO 'Bearer' prefix).
Most APIs use Bearer; this is a frequent source of 401s when copy-pasting
client code from other projects.
"""
from __future__ import annotations

import requests

_GRAPHQL_URL = "https://api.linear.app/graphql"
_DEFAULT_TIMEOUT_S = 30.0


class LinearError(Exception):
    """All Linear HTTP/GraphQL failures bubble up as this."""


class LinearClient:
    """One client per session. Reuse across calls."""

    def __init__(self, api_key: str):
        if not api_key or not api_key.strip():
            raise LinearError(
                "Linear API ключ не задан. "
                "Откройте Настройки → Linear и вставьте ключ."
            )
        self._api_key = api_key.strip()
        self._session = requests.Session()
        self._session.headers.update(self._build_headers())

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": self._api_key,   # NB: no 'Bearer' prefix
            "Content-Type": "application/json",
        }

    def close(self) -> None:
        """Close connections. Safe to call from another thread to cancel."""
        self._session.close()

    def _graphql(
        self,
        query: str,
        variables: dict | None = None,
        timeout: float = _DEFAULT_TIMEOUT_S,
    ) -> dict:
        """Send a GraphQL query/mutation. Returns the 'data' field on success.

        Raises LinearError on:
        - HTTP non-200
        - GraphQL 'errors' array present in response
        - Network failure
        """
        body = {"query": query}
        if variables:
            body["variables"] = variables

        try:
            resp = self._session.post(
                _GRAPHQL_URL, json=body, timeout=timeout,
            )
        except requests.exceptions.ConnectionError as e:
            raise LinearError(f"Нет соединения с Linear: {e}") from e
        except requests.exceptions.Timeout as e:
            raise LinearError(f"Таймаут Linear (>{timeout}s)") from e

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", "?")
            raise LinearError(f"Linear 429 rate-limit (retry after {retry_after}s)")
        if resp.status_code != 200:
            raise LinearError(
                f"Linear вернул {resp.status_code}: {resp.text[:200]}"
            )

        payload = resp.json()
        if "errors" in payload and payload["errors"]:
            msgs = "; ".join(e.get("message", "?") for e in payload["errors"])
            raise LinearError(f"Linear GraphQL: {msgs}")

        return payload.get("data", {})
```

- [ ] **Step 2: Verify importable**

```bash
python -c "from tasks.linear_client import LinearClient, LinearError; print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add tasks/linear_client.py
git commit -m "feat(tasks): LinearClient skeleton with GraphQL helper"
```

---

### Task 9: Linear client — `validate_key()` (viewer query)

**Files:**
- Modify: `tasks/linear_client.py`
- Create: `tests/test_tasks_linear_client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tasks_linear_client.py`:

```python
"""Tests for tasks.linear_client. HTTP is mocked via unittest.mock."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from tasks.linear_client import LinearClient, LinearError


# ── construction ──────────────────────────────────────────────────────


def test_client_rejects_empty_key():
    with pytest.raises(LinearError, match="ключ не задан"):
        LinearClient("")
    with pytest.raises(LinearError):
        LinearClient("   ")


def test_authorization_header_has_no_bearer_prefix():
    """Linear quirk — raw key, no 'Bearer'."""
    c = LinearClient("lin_api_test")
    assert c._session.headers["Authorization"] == "lin_api_test"


# ── validate_key ──────────────────────────────────────────────────────


def test_validate_key_returns_viewer_on_200():
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {
        "data": {"viewer": {"id": "u-1", "name": "Айдар", "email": "a@x.com"}}
    }
    c = LinearClient("lin_api_test")
    with patch.object(c._session, "post", return_value=fake) as mock_post:
        v = c.validate_key()
    mock_post.assert_called_once()
    assert v == {"id": "u-1", "name": "Айдар", "email": "a@x.com"}


def test_validate_key_raises_on_graphql_error():
    """Linear returns 200 with 'errors' array on auth failure."""
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {
        "errors": [{"message": "Authentication failed"}],
    }
    c = LinearClient("lin_api_bad")
    with patch.object(c._session, "post", return_value=fake):
        with pytest.raises(LinearError, match="Authentication"):
            c.validate_key()


def test_validate_key_raises_on_http_500():
    fake = MagicMock()
    fake.status_code = 500
    fake.text = "Internal server error"
    c = LinearClient("lin_api_test")
    with patch.object(c._session, "post", return_value=fake):
        with pytest.raises(LinearError, match="500"):
            c.validate_key()
```

- [ ] **Step 2: Run, verify fails**

```bash
pytest tests/test_tasks_linear_client.py -v
```

Expected: `AttributeError: ... has no attribute 'validate_key'`.

- [ ] **Step 3: Implement validate_key**

Append to `tasks/linear_client.py`:

```python
_VIEWER_QUERY = """
query Viewer {
  viewer { id name email }
}
"""


class LinearClient:
    # ... existing code ...

    def validate_key(self) -> dict:
        """GraphQL `viewer` query — confirms the key works.

        Returns dict with id, name, email of the authenticated user.
        Raises LinearError on any failure.
        """
        data = self._graphql(_VIEWER_QUERY)
        viewer = data.get("viewer")
        if not viewer:
            raise LinearError("Linear: viewer не найден в ответе")
        return viewer
```

Add `_VIEWER_QUERY` at module level (above the class).

- [ ] **Step 4: Run, verify passes**

```bash
pytest tests/test_tasks_linear_client.py -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tasks/linear_client.py tests/test_tasks_linear_client.py
git commit -m "feat(tasks): Linear validate_key via viewer GraphQL query"
```

---

### Task 10: Linear client — `bootstrap()` (viewer + teams in one query)

**Files:**
- Modify: `tasks/linear_client.py`
- Modify: `tests/test_tasks_linear_client.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tasks_linear_client.py`:

```python
# ── bootstrap ─────────────────────────────────────────────────────────


def test_bootstrap_returns_viewer_and_teams_in_one_query():
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {
        "data": {
            "viewer": {"id": "u-1", "name": "Айдар", "email": "a@x.com"},
            "teams": {
                "nodes": [
                    {"id": "t-1", "name": "Engineering", "key": "ENG"},
                    {"id": "t-2", "name": "Design", "key": "DES"},
                ]
            },
        }
    }
    c = LinearClient("lin_api_test")
    with patch.object(c._session, "post", return_value=fake) as mock_post:
        result = c.bootstrap()
    # One round-trip — verifies our optimization
    assert mock_post.call_count == 1
    assert result["viewer"]["name"] == "Айдар"
    assert len(result["teams"]) == 2
    assert result["teams"][0] == {"id": "t-1", "name": "Engineering", "key": "ENG"}


def test_bootstrap_returns_empty_team_list_when_user_has_no_teams():
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {
        "data": {
            "viewer": {"id": "u-1", "name": "Solo", "email": "s@x.com"},
            "teams": {"nodes": []},
        }
    }
    c = LinearClient("lin_api_test")
    with patch.object(c._session, "post", return_value=fake):
        result = c.bootstrap()
    assert result["teams"] == []
```

- [ ] **Step 2: Run, verify fails**

```bash
pytest tests/test_tasks_linear_client.py::test_bootstrap_returns_viewer_and_teams_in_one_query -v
```

Expected: `AttributeError: ... has no attribute 'bootstrap'`.

- [ ] **Step 3: Implement bootstrap**

Append to `tasks/linear_client.py` (above the class, add the query constant):

```python
_BOOTSTRAP_QUERY = """
query Bootstrap {
  viewer { id name email }
  teams { nodes { id name key } }
}
"""
```

And inside `LinearClient`:

```python
def bootstrap(self) -> dict:
    """Validate + fetch all accessible teams in a single round-trip.

    Returns dict:
        - viewer: {id, name, email}
        - teams: list[{id, name, key}]

    Cached by callers in config['linear_teams_cache'] with 24h TTL.
    """
    data = self._graphql(_BOOTSTRAP_QUERY)
    viewer = data.get("viewer")
    if not viewer:
        raise LinearError("Linear: viewer не найден в ответе bootstrap")
    teams_node = data.get("teams") or {}
    teams = teams_node.get("nodes", [])
    return {"viewer": viewer, "teams": teams}
```

- [ ] **Step 4: Run, verify passes**

```bash
pytest tests/test_tasks_linear_client.py -v
```

Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tasks/linear_client.py tests/test_tasks_linear_client.py
git commit -m "feat(tasks): Linear bootstrap query (viewer+teams in one round-trip)"
```

---

### Task 11: Linear client — `team_context()` (members + labels)

**Files:**
- Modify: `tasks/linear_client.py`
- Modify: `tests/test_tasks_linear_client.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tasks_linear_client.py`:

```python
# ── team_context ──────────────────────────────────────────────────────


def test_team_context_returns_members_and_labels():
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {
        "data": {
            "team": {
                "members": {
                    "nodes": [
                        {"id": "u-1", "name": "Айдар", "displayName": "айдар", "email": "a@x.com"},
                        {"id": "u-2", "name": "Нурғыса", "displayName": "ng", "email": "n@x.com"},
                    ]
                },
                "labels": {
                    "nodes": [
                        {"id": "l-1", "name": "bug", "color": "#ff0000"},
                        {"id": "l-2", "name": "mobile", "color": "#0000ff"},
                    ]
                },
            }
        }
    }
    c = LinearClient("lin_api_test")
    with patch.object(c._session, "post", return_value=fake) as mock_post:
        ctx = c.team_context("t-1")
    body = mock_post.call_args.kwargs["json"]
    assert body["variables"] == {"teamId": "t-1"}
    assert len(ctx["members"]) == 2
    assert ctx["members"][0]["name"] == "Айдар"
    assert len(ctx["labels"]) == 2
    assert ctx["labels"][0]["name"] == "bug"


def test_team_context_raises_when_team_id_unknown():
    """Linear returns data.team=null for invalid team IDs."""
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {"data": {"team": None}}
    c = LinearClient("lin_api_test")
    with patch.object(c._session, "post", return_value=fake):
        with pytest.raises(LinearError, match="команда"):
            c.team_context("t-bogus")
```

- [ ] **Step 2: Run, verify fails**

```bash
pytest tests/test_tasks_linear_client.py::test_team_context_returns_members_and_labels -v
```

Expected: `AttributeError: ... has no attribute 'team_context'`.

- [ ] **Step 3: Implement team_context**

Append to module-level constants:

```python
_TEAM_CONTEXT_QUERY = """
query TeamContext($teamId: String!) {
  team(id: $teamId) {
    members { nodes { id name displayName email } }
    labels  { nodes { id name color } }
  }
}
"""
```

And in `LinearClient`:

```python
def team_context(self, team_id: str) -> dict:
    """Fetch members + labels for a team in a single GraphQL query.

    Returns dict:
        - members: list[{id, name, displayName, email}]
        - labels: list[{id, name, color}]

    Used by extractor to give the LLM authoritative context for assignee
    and label resolution. NOT cached — team membership and labels change
    frequently enough that staleness costs more than the network call.
    """
    data = self._graphql(_TEAM_CONTEXT_QUERY, {"teamId": team_id})
    team = data.get("team")
    if not team:
        raise LinearError(f"Linear: команда {team_id} не найдена")
    members = (team.get("members") or {}).get("nodes", [])
    labels  = (team.get("labels")  or {}).get("nodes", [])
    return {"members": members, "labels": labels}
```

- [ ] **Step 4: Run, verify passes**

```bash
pytest tests/test_tasks_linear_client.py -v
```

Expected: 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tasks/linear_client.py tests/test_tasks_linear_client.py
git commit -m "feat(tasks): Linear team_context (members + labels in one query)"
```

---

### Task 12: Linear client — `create_issue()` mutation (defined for Phase 6.3, tested now)

**Files:**
- Modify: `tasks/linear_client.py`
- Modify: `tests/test_tasks_linear_client.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tasks_linear_client.py`:

```python
# ── create_issue ──────────────────────────────────────────────────────


def test_create_issue_sends_full_input_and_returns_issue():
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {
        "data": {
            "issueCreate": {
                "success": True,
                "issue": {
                    "id": "issue-uuid",
                    "identifier": "ENG-1234",
                    "url": "https://linear.app/x/issue/ENG-1234",
                },
            }
        }
    }
    c = LinearClient("lin_api_test")
    with patch.object(c._session, "post", return_value=fake) as mock_post:
        result = c.create_issue(
            team_id="t-1",
            title="Починить login",
            description="Длинное описание",
            priority=2,
            assignee_id="u-1",
            label_ids=["l-1", "l-2"],
            due_date="2026-05-15",
        )
    body = mock_post.call_args.kwargs["json"]
    vars_ = body["variables"]
    assert vars_["teamId"] == "t-1"
    assert vars_["title"] == "Починить login"
    assert vars_["description"] == "Длинное описание"
    assert vars_["priority"] == 2
    assert vars_["assigneeId"] == "u-1"
    assert vars_["labelIds"] == ["l-1", "l-2"]
    assert vars_["dueDate"] == "2026-05-15"
    assert result == {
        "id": "issue-uuid",
        "identifier": "ENG-1234",
        "url": "https://linear.app/x/issue/ENG-1234",
    }


def test_create_issue_omits_optional_fields_when_none():
    """Title is the only required field. None values mustn't be sent — Linear
    treats null differently from absent."""
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {
        "data": {
            "issueCreate": {
                "success": True,
                "issue": {"id": "x", "identifier": "DES-1", "url": "https://x"},
            }
        }
    }
    c = LinearClient("lin_api_test")
    with patch.object(c._session, "post", return_value=fake) as mock_post:
        c.create_issue(team_id="t-1", title="Title only")
    vars_ = mock_post.call_args.kwargs["json"]["variables"]
    assert vars_ == {"teamId": "t-1", "title": "Title only"}
    # Verify no priority/assignee/etc. keys
    assert "priority" not in vars_
    assert "assigneeId" not in vars_
    assert "labelIds" not in vars_
    assert "dueDate" not in vars_


def test_create_issue_raises_when_success_false():
    """Linear returns success=False (with errors) when input is rejected."""
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {
        "data": {
            "issueCreate": {
                "success": False,
                "issue": None,
            }
        }
    }
    c = LinearClient("lin_api_test")
    with patch.object(c._session, "post", return_value=fake):
        with pytest.raises(LinearError, match="отказ"):
            c.create_issue(team_id="t-1", title="X")
```

- [ ] **Step 2: Run, verify fails**

```bash
pytest tests/test_tasks_linear_client.py::test_create_issue_sends_full_input_and_returns_issue -v
```

Expected: `AttributeError: ... has no attribute 'create_issue'`.

- [ ] **Step 3: Implement create_issue**

Append module-level constant:

```python
_CREATE_ISSUE_MUTATION = """
mutation CreateIssue(
  $teamId: String!, $title: String!, $description: String,
  $priority: Int, $assigneeId: String, $labelIds: [String!],
  $dueDate: TimelessDate
) {
  issueCreate(input: {
    teamId: $teamId, title: $title, description: $description,
    priority: $priority, assigneeId: $assigneeId,
    labelIds: $labelIds, dueDate: $dueDate
  }) {
    success
    issue { id identifier url }
  }
}
"""
```

And in `LinearClient`:

```python
def create_issue(
    self,
    team_id: str,
    title: str,
    description: str | None = None,
    priority: int | None = None,
    assignee_id: str | None = None,
    label_ids: list[str] | None = None,
    due_date: str | None = None,
) -> dict:
    """Create a single Linear issue. Returns {id, identifier, url} on success.

    Only `team_id` and `title` are required by Linear. None values are
    *omitted* from the GraphQL variables (not sent as null) — Linear
    treats null as 'set this field to null' rather than 'leave default'.

    Raises LinearError if Linear returns success=false or any HTTP/network
    failure.
    """
    variables: dict = {"teamId": team_id, "title": title}
    if description is not None:
        variables["description"] = description
    if priority is not None:
        variables["priority"] = priority
    if assignee_id is not None:
        variables["assigneeId"] = assignee_id
    if label_ids:
        variables["labelIds"] = list(label_ids)
    if due_date is not None:
        variables["dueDate"] = due_date

    data = self._graphql(_CREATE_ISSUE_MUTATION, variables)
    result = data.get("issueCreate") or {}
    if not result.get("success"):
        raise LinearError(f"Linear отказался создать тикет: {result}")
    return result["issue"]
```

- [ ] **Step 4: Run, verify passes**

```bash
pytest tests/test_tasks_linear_client.py -v
```

Expected: 12 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tasks/linear_client.py tests/test_tasks_linear_client.py
git commit -m "feat(tasks): Linear create_issue mutation (used in Phase 6.3)"
```

---

### Task 13: Settings UI — OpenRouter section (skeleton, no Validate yet)

**Files:**
- Modify: `ui/dialogs/settings.py`

No automated test — Tk UI is impractical to unit test. Manual smoke at end.

- [ ] **Step 1: Read existing Settings file structure**

```bash
grep -n "_build_.*_section" ui/dialogs/settings.py
```

Expected: list of existing `_build_*_section` methods. Use them as template.

- [ ] **Step 2: Add the OpenRouter section method**

Append to `ui/dialogs/settings.py` (after the last `_build_*_section`, before any `_section_card` helper or the closing of class — find the right place by looking at where existing sections are added in `__init__`).

Add **method** to `SettingsDialog` class:

```python
def _build_openrouter_section(self, parent) -> None:
    """OpenRouter API key + default model.

    Layout: title, [api_key field][Вставить], [Проверить ключ][status],
    default model dropdown.
    State vars: parent app's _openrouter_key_var, _openrouter_default_model_var.
    """
    body = self._section_card(parent, "OpenRouter", row=10)

    # API key row
    label(body, "API ключ:").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))

    key_row = ctk.CTkFrame(body, fg_color="transparent")
    key_row.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))
    key_row.grid_columnconfigure(0, weight=1)

    key_entry = ctk.CTkEntry(
        key_row, textvariable=self._parent._openrouter_key_var,
        show="•", placeholder_text="sk-or-...",
    )
    key_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))

    tonal_button(
        key_row, text="📋 Вставить", width=110,
        command=self._paste_openrouter_key,
    ).grid(row=0, column=1)

    # Validate row
    val_row = ctk.CTkFrame(body, fg_color="transparent")
    val_row.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
    val_row.grid_columnconfigure(1, weight=1)

    tonal_button(
        val_row, text="Проверить ключ", width=140,
        command=self._validate_openrouter,
    ).grid(row=0, column=0)

    self._openrouter_status = label(val_row, text="", anchor="w")
    self._openrouter_status.grid(row=0, column=1, sticky="ew", padx=8)

    # Default model row
    label(body, "Модель по умолчанию:").grid(
        row=3, column=0, sticky="w", padx=8, pady=(8, 4),
    )
    option_menu(
        body, self._parent._openrouter_default_model_var,
        list(_CURATED_MODELS.keys()),
    ).grid(row=4, column=0, sticky="ew", padx=8, pady=(0, 8))


def _paste_openrouter_key(self) -> None:
    """Paste-from-clipboard helper (mirrors HF Token paste pattern)."""
    try:
        text = self.clipboard_get().strip()
        self._parent._openrouter_key_var.set(text)
        if text:
            self._parent._config["openrouter_api_key"] = text
            save_config(self._parent._config)
    except Exception:
        pass


def _validate_openrouter(self) -> None:
    """Stub — wired in Task 14."""
    self._openrouter_status.configure(text="(не реализовано)", text_color=TEXT_SECONDARY)
```

Add this **module-level constant** at the top of `ui/dialogs/settings.py` (after imports):

```python
# Curated dropdown for OpenRouter default model. Slug → display label.
# Display label keeps the slug visible — power users recognize 'sonnet-4.5'
# faster than 'Anthropic Claude Sonnet 4.5 (latest)'.
_CURATED_MODELS = {
    "anthropic/claude-sonnet-4.5":   "anthropic/claude-sonnet-4.5",
    "anthropic/claude-haiku-4.5":    "anthropic/claude-haiku-4.5",
    "openai/gpt-4o":                  "openai/gpt-4o",
    "google/gemini-2.5-pro":          "google/gemini-2.5-pro",
    "deepseek/deepseek-v3":           "deepseek/deepseek-v3",
}
```

In `App.__init__` ([ui/app.py](../../../ui/app.py)) — add two new state vars near the other `*_var` declarations (around line 230):

```python
self._openrouter_key_var = ctk.StringVar(
    value=self._config.get("openrouter_api_key", ""),
)
self._openrouter_default_model_var = ctk.StringVar(
    value=self._config.get(
        "tasks_default_model", "anthropic/claude-sonnet-4.5",
    ),
)
```

Bind a write trace so changing the dropdown persists immediately (after the `*_var` block):

```python
self._openrouter_default_model_var.trace_add(
    "write", lambda *_: self._on_openrouter_default_model_changed(),
)
```

And add the callback method on `App`:

```python
def _on_openrouter_default_model_changed(self) -> None:
    self._config["tasks_default_model"] = self._openrouter_default_model_var.get()
    save_config(self._config)
```

Finally, in `SettingsDialog.__init__`, add the new section call after the existing chain:

```python
self._build_openrouter_section(body)
```

(Find the existing `self._build_*_section(body)` calls and append it after them.)

- [ ] **Step 3: Verify dialog opens without crashing**

Run app, open Settings, scroll to bottom — should see the new OpenRouter section.

```bash
python app.py
# In app: open Settings dialog. Expect: new "OpenRouter" card visible
# with API key field, "Проверить ключ" button (still says "(не реализовано)"),
# and default model dropdown.
```

- [ ] **Step 4: Commit**

```bash
git add ui/dialogs/settings.py ui/app.py
git commit -m "feat(settings): OpenRouter section UI (Validate stubbed)"
```

---

### Task 14: Settings UI — wire OpenRouter Validate

**Files:**
- Modify: `ui/dialogs/settings.py`

- [ ] **Step 1: Replace the Validate stub with real implementation**

In `ui/dialogs/settings.py`, replace `_validate_openrouter`:

```python
def _validate_openrouter(self) -> None:
    """Make a single GET /auth/key. Show balance on success, error on fail.

    Runs in a worker thread to avoid blocking the UI on slow networks.
    """
    key = self._parent._openrouter_key_var.get().strip()
    if not key:
        self._openrouter_status.configure(
            text="Введите API ключ", text_color=RED,
        )
        return

    self._openrouter_status.configure(
        text="Проверка...", text_color=TEXT_SECONDARY,
    )

    def worker():
        try:
            from tasks.openrouter_client import OpenRouterClient, OpenRouterError
            client = OpenRouterClient(key)
            try:
                info = client.validate_key()
            finally:
                client.close()
        except Exception as e:  # OpenRouterError or anything from client
            self.after(0, self._openrouter_status.configure, {
                "text": f"✗ {e}", "text_color": RED,
            })
            return

        # Save the key — it works
        self._parent._config["openrouter_api_key"] = key
        save_config(self._parent._config)

        balance = info.get("balance_remaining")
        if balance is not None:
            msg = f"✓ Активен (баланс: ${balance:.2f})"
        else:
            msg = f"✓ Активен ({info.get('label') or 'unlimited'})"
        self.after(0, self._openrouter_status.configure, {
            "text": msg, "text_color": GREEN,
        })

    threading.Thread(target=worker, daemon=True).start()
```

Add imports if missing at top of `ui/dialogs/settings.py`:

```python
import threading
from theme import GREEN, RED   # add these to existing theme imports
```

Verify `from utils import save_config` is also imported.

- [ ] **Step 2: Manual smoke**

1. Open the app, open Settings.
2. Paste a valid OpenRouter key.
3. Click "Проверить ключ". Expected: green "✓ Активен (баланс: $X.YZ)".
4. Replace with a known-bad key (e.g., add an extra char).
5. Click "Проверить ключ". Expected: red "✗ OpenRouter вернул 401: ...".

If the user has no OpenRouter key, skip this manual smoke — just verify the code path doesn't crash by typing a fake key (it'll show 401, which is correct behavior).

- [ ] **Step 3: Commit**

```bash
git add ui/dialogs/settings.py
git commit -m "feat(settings): wire OpenRouter Validate (live API call + balance)"
```

---

### Task 15: Settings UI — Linear section (skeleton)

**Files:**
- Modify: `ui/dialogs/settings.py`
- Modify: `ui/app.py`

- [ ] **Step 1: Add `_build_linear_section`**

In `ui/dialogs/settings.py`, append:

```python
def _build_linear_section(self, parent) -> None:
    """Linear API key + connection status.

    No team picker here — that's per-extract in the ExtractTasksDialog
    (Phase 6.1). Settings only persists the key.
    """
    body = self._section_card(parent, "Linear", row=11)

    label(body, "API ключ:").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))

    key_row = ctk.CTkFrame(body, fg_color="transparent")
    key_row.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))
    key_row.grid_columnconfigure(0, weight=1)

    key_entry = ctk.CTkEntry(
        key_row, textvariable=self._parent._linear_key_var,
        show="•", placeholder_text="lin_api_...",
    )
    key_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))

    tonal_button(
        key_row, text="📋 Вставить", width=110,
        command=self._paste_linear_key,
    ).grid(row=0, column=1)

    val_row = ctk.CTkFrame(body, fg_color="transparent")
    val_row.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
    val_row.grid_columnconfigure(1, weight=1)

    tonal_button(
        val_row, text="Проверить ключ", width=140,
        command=self._validate_linear,
    ).grid(row=0, column=0)

    self._linear_status = label(val_row, text="", anchor="w")
    self._linear_status.grid(row=0, column=1, sticky="ew", padx=8)


def _paste_linear_key(self) -> None:
    try:
        text = self.clipboard_get().strip()
        self._parent._linear_key_var.set(text)
        if text:
            self._parent._config["linear_api_key"] = text
            save_config(self._parent._config)
    except Exception:
        pass


def _validate_linear(self) -> None:
    """Stub — wired in Task 16."""
    self._linear_status.configure(text="(не реализовано)", text_color=TEXT_SECONDARY)
```

In `ui/app.py`, add the `_linear_key_var`:

```python
self._linear_key_var = ctk.StringVar(
    value=self._config.get("linear_api_key", ""),
)
```

In `SettingsDialog.__init__`, add the section call:

```python
self._build_linear_section(body)
```

- [ ] **Step 2: Manual check**

```bash
python app.py
```

Open Settings, scroll. Both OpenRouter and Linear sections should be visible.

- [ ] **Step 3: Commit**

```bash
git add ui/dialogs/settings.py ui/app.py
git commit -m "feat(settings): Linear section UI (Validate stubbed)"
```

---

### Task 16: Settings UI — wire Linear Validate

**Files:**
- Modify: `ui/dialogs/settings.py`

- [ ] **Step 1: Replace the Validate stub**

In `ui/dialogs/settings.py`, replace `_validate_linear`:

```python
def _validate_linear(self) -> None:
    """Make a single viewer query. Show display name on success."""
    key = self._parent._linear_key_var.get().strip()
    if not key:
        self._linear_status.configure(text="Введите API ключ", text_color=RED)
        return

    self._linear_status.configure(text="Проверка...", text_color=TEXT_SECONDARY)

    def worker():
        try:
            from tasks.linear_client import LinearClient, LinearError
            client = LinearClient(key)
            try:
                viewer = client.validate_key()
            finally:
                client.close()
        except Exception as e:
            self.after(0, self._linear_status.configure, {
                "text": f"✗ {e}", "text_color": RED,
            })
            return

        self._parent._config["linear_api_key"] = key
        save_config(self._parent._config)

        name = viewer.get("name") or viewer.get("email") or "(unknown)"
        self.after(0, self._linear_status.configure, {
            "text": f"✓ Подключено: {name}", "text_color": GREEN,
        })

    threading.Thread(target=worker, daemon=True).start()
```

- [ ] **Step 2: Manual smoke** (only if user has a Linear key)

1. Open Settings → Linear.
2. Paste key. Click "Проверить ключ".
3. Expected: green "✓ Подключено: <your display name>".

If no key — skip. The code path is identical to the OpenRouter case which we already smoke-tested.

- [ ] **Step 3: Commit**

```bash
git add ui/dialogs/settings.py
git commit -m "feat(settings): wire Linear Validate (live viewer query)"
```

---

### Task 17: Manual smoke checklist + final test sweep

**Files:**
- None (verification only).

- [ ] **Step 1: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: existing tests pass, plus all new tests:
- `tests/test_tasks_schema.py` — 12 tests
- `tests/test_tasks_openrouter_client.py` — 10 tests
- `tests/test_tasks_linear_client.py` — 12 tests

Total new: 34 tests.

- [ ] **Step 2: Smoke checklist**

Run through this list once with real keys (or as much of it as you can with what you have):

| # | Action | Expected |
|---|---|---|
| 1 | Open Settings, scroll to OpenRouter | Section visible, key field empty (if first run) |
| 2 | Paste OpenRouter key, click Проверить | "✓ Активен (баланс: $X.YZ)" green |
| 3 | Edit key (corrupt 1 char), Проверить | "✗ OpenRouter вернул 401:..." red |
| 4 | Restore key, switch dropdown to a different curated model, close Settings, reopen | Selected model persisted |
| 5 | Same flow for Linear (`✓ Подключено: <name>`) | Same |
| 6 | Disconnect Wi-Fi, click Проверить on either section | "✗ Нет соединения с..." red within ~10 s |

- [ ] **Step 3: No final commit needed** (Tasks 0–16 already committed everything). Just confirm git is clean:

```bash
git status
```

Expected: only the unrelated pre-existing modifications remain (`README.md`, `audio_cutter.py`, etc., as listed in initial `git status`). Nothing new from Phase 6.0 should be uncommitted.

---

## Phase 6.0 — Done. Next steps.

After all 17 tasks ✅:
- `tasks/` package skeleton in place with `schema`, `openrouter_client`, `linear_client`.
- 34 unit tests covering schema and both HTTP clients.
- Settings dialog has working OpenRouter and Linear sections with live key validation.
- Both API keys persist in `config.json`.
- Default model selectable.
- No main-window changes — user sees nothing new on the main window yet.

**Phase 6.1 (next plan)** will use the foundation to build:
- New `tasks/extractor.py` — orchestrator (transcript + context → Task[]).
- New `tasks/persistence.py` — save/load `tasks_raw.json` and `tasks.json`.
- New `ui/dialogs/extract_tasks.py` — the Extract Tasks dialog (minimal: model + team dropdowns, JSON textbox for results).
- New "Извлечь задачи" button in main window's bottom row.
