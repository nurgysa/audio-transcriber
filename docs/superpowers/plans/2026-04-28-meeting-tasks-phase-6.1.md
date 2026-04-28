# Meeting Tasks Pipeline — Phase 6.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the end-to-end Extract flow — main-window button → dialog with model+team dropdowns → OpenRouter call with team context → post-LLM validation → `tasks_raw.json` on disk → raw JSON shown in a textbox.

**Architecture:** Two new pure modules (`tasks/extractor.py`, `tasks/persistence.py`) implement the orchestration and disk I/O; one new dialog (`ui/dialogs/extract_tasks.py`) provides the minimal Phase-6.1 UI; `ui/app.py` gets a button and captures the active history folder. All network I/O runs in `threading.Thread(daemon=True)` and marshals UI updates via `self.after(0, …)` — same pattern as `_run_transcription` ([ui/app.py:872](ui/app.py:872)) and `_validate_openrouter` ([ui/dialogs/settings.py:478](ui/dialogs/settings.py:478)).

**Tech Stack:** Python 3.11+, `requests` for HTTP (already in `tasks/openrouter_client.py`, `tasks/linear_client.py`), `customtkinter` for UI, `pytest` + `unittest.mock` for tests, stdlib `json` / `pathlib` for persistence.

**Spec:** [docs/superpowers/specs/2026-04-28-meeting-tasks-pipeline-design.md](../specs/2026-04-28-meeting-tasks-pipeline-design.md) (Phasing → Phase 6.1).

**Carry-forwards from Phase 6.0:** Items 1, 2, 3, 5 from [docs/superpowers/handoffs/2026-04-28-phase-6.0-to-6.1-handoff.md](../handoffs/2026-04-28-phase-6.0-to-6.1-handoff.md) folded into Task 0. Item 4 (Settings `grab_set` hardening) deferred per handoff guidance.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `tasks/openrouter_client.py` | Modify | Carry-forward #1 (wrap response parsing in `try/except → OpenRouterError`) + #3 (timeout msg interpolated) |
| `tasks/schema.py` | Modify | Carry-forward #5 (one-line comment on `local_id` fallback in `from_dict`) |
| `tasks/persistence.py` | **Create** | `save_tasks_raw(folder, tasks, meta)` / `load_tasks_raw(folder)` — atomic write of `tasks_raw.json` |
| `tasks/extractor.py` | **Create** | `build_prompt`, `parse_and_validate`, `extract`, `ExtractionError`, correction counting |
| `tasks/__init__.py` | Modify | Update docstring (extractor + persistence are now wired) |
| `tests/test_tasks_schema.py` | Modify | Carry-forward #2 (test `label_names` independence) |
| `tests/test_tasks_persistence.py` | **Create** | Round-trip + edge cases |
| `tests/test_tasks_extractor.py` | **Create** | Validation + parsing + orchestration with mocked clients |
| `ui/dialogs/extract_tasks.py` | **Create** | Minimal dialog: model+team dropdowns, Извлечь button, JSON textbox, status badge |
| `ui/app.py` | Modify | Add `_btn_extract_tasks` between Copy and History; capture `_last_history_folder` in `_on_complete`; gate-check + `_open_extract_tasks_dialog` |

**Why this split:** `extractor.py` stays pure (no I/O, no Tk) — fully unit-testable with mocked clients. `persistence.py` owns disk I/O and is testable via `tmp_path`. `ExtractTasksDialog` owns Tk + threading; logic-free, so no unit tests (manual smoke checklist instead). This mirrors the Phase 6.0 pattern: `tasks/*_client.py` is pure (testable), `ui/dialogs/settings.py` is wiring (no tests).

---

## Decisions baked into this plan

These are choices made before writing the plan, listed here so reviewers can challenge before execution starts.

1. **Carry-forward #1 fixed at client level**, not extractor. Handoff says either is OK; client-level keeps the existing contract ("Raises `OpenRouterError` on any HTTP/network failure") consistent — extending it to "or malformed payload" is one small `try/except` instead of double-wrapping at every caller.
2. **Cancel-on-close**: dialog stores `self._active_client` for the in-flight worker; `_on_close` sets a `threading.Event` and calls `client.close()`. Worker's next `requests.*` raises `ConnectionError` → caught → silent exit (the dialog is already gone, `self.after` is a no-op on destroyed widgets).
3. **`priority_from_string` not refactored.** Extractor pre-checks the raw string against `{"none","low","medium","high","urgent"}` (case-insensitive) to distinguish "legitimate none" from "hallucinated 'critical'". This is a 2-line check, simpler than threading a callback through schema.
4. **Cost estimate hint** above the Извлечь button: `"~${cost:.2f}" via len(transcript)/4 ÷ 1e6 × $3` (Sonnet 4.5 pricing for input). Imprecise but useful — final usage shown in status badge after extract.
5. **JSON textbox displays `tasks_raw.json` content read from disk**, not the in-memory Task list. This makes "what you see = what's saved" trivially true and gives users a way to inspect the audit trail.
6. **Custom-typed model slugs** persisted to `config["tasks_recent_models"]` (FIFO 5) **only on successful extract**, per spec. Custom slug entered → typed-but-not-extracted slugs do NOT enter the list.
7. **`linear_teams_cache` 24h TTL**: cache entry has `{"data": [...], "fetched_at": "ISO timestamp"}`. Dialog open → if `fetched_at + 24h > now`, reuse; else call `bootstrap()` and overwrite cache. `[↻]` button forces refresh regardless.

---

## Task 0: Pre-Phase Cleanup (Phase-6.0 Carry-Forwards)

**Goal:** Ship four small fixes before opening the Phase-6.1 surface area. Lowers risk of "two unrelated diffs in the same PR" and gets the carry-forward debt off the books.

**Files:**
- Modify: `tests/test_tasks_schema.py` (add one test)
- Modify: `tasks/openrouter_client.py:81` and `:160-168`
- Modify: `tasks/schema.py:104`

- [ ] **Step 0.1: Write the new failing test** (carry-forward #2 — `label_names` mutable-default isolation)

In `tests/test_tasks_schema.py`, after line 100 (after `test_task_label_ids_default_is_independent_per_instance`), add:

```python
def test_task_label_names_default_is_independent_per_instance():
    """Mirror of label_ids isolation — guards against future
    accidental switch from field(default_factory=list) to =[]."""
    from tasks.schema import Task
    a = Task(title="A")
    b = Task(title="B")
    a.label_names.append("bug")
    assert b.label_names == []
```

- [ ] **Step 0.2: Run the new test alone — confirm it passes against current schema**

Run: `pytest tests/test_tasks_schema.py::test_task_label_names_default_is_independent_per_instance -v`
Expected: PASS (current schema already uses `field(default_factory=list)` for `label_names`; this test is a regression guard, not a fix).

- [ ] **Step 0.3: Update `validate_key()` timeout message** (carry-forward #3)

In `tasks/openrouter_client.py:80`, change:

```python
        except requests.exceptions.Timeout as e:
            raise OpenRouterError("Таймаут подключения к OpenRouter") from e
```

to:

```python
        except requests.exceptions.Timeout as e:
            raise OpenRouterError("Таймаут подключения к OpenRouter (>10s)") from e
```

- [ ] **Step 0.4: Wrap response-payload extraction in `complete()`** (carry-forward #1)

In `tasks/openrouter_client.py:160-168`, change:

```python
        try:
            data = resp.json()
        except ValueError as e:
            raise OpenRouterError(f"OpenRouter вернул не-JSON ответ: {resp.text[:200]}") from e
        choice = data["choices"][0]
        return {
            "content": choice["message"]["content"],
            "usage": data.get("usage", {}),
            "model": data.get("model", model),
        }
```

to:

```python
        try:
            data = resp.json()
        except ValueError as e:
            raise OpenRouterError(f"OpenRouter вернул не-JSON ответ: {resp.text[:200]}") from e
        # Provider-routing failures occasionally return 200 with {"error": {...}}
        # instead of {"choices": [...]}. Surface that as OpenRouterError so
        # callers don't see a raw KeyError/IndexError.
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            err = data.get("error", {}).get("message") if isinstance(data, dict) else None
            detail = err or f"unexpected response shape: {str(data)[:200]}"
            raise OpenRouterError(f"OpenRouter: {detail}") from e
        return {
            "content": content,
            "usage": data.get("usage", {}),
            "model": data.get("model", model),
        }
```

- [ ] **Step 0.5: Add a test for the new error path**

In `tests/test_tasks_openrouter_client.py`, after the existing `complete()` tests, add:

```python
def test_complete_raises_on_provider_error_in_200_body():
    """OpenRouter sometimes returns 200 with {'error': {...}} instead of
    a normal completion. We surface that as OpenRouterError, not KeyError."""
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {
        "error": {"message": "Provider returned no choices", "code": 502}
    }
    c = OpenRouterClient("sk-or-test")
    with patch.object(c._session, "post", return_value=fake):
        with pytest.raises(OpenRouterError, match="Provider returned no choices"):
            c.complete("anthropic/claude-sonnet-4.5", [{"role": "user", "content": "hi"}])


def test_complete_raises_on_empty_choices():
    """Empty choices array (rare but possible) → OpenRouterError, not IndexError."""
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {"choices": []}
    c = OpenRouterClient("sk-or-test")
    with patch.object(c._session, "post", return_value=fake):
        with pytest.raises(OpenRouterError, match="unexpected response shape"):
            c.complete("anthropic/claude-sonnet-4.5", [{"role": "user", "content": "hi"}])
```

- [ ] **Step 0.6: Add `local_id` comment in `from_dict`** (carry-forward #5)

In `tasks/schema.py:104`, change:

```python
            local_id=d.get("local_id") or str(uuid.uuid4()),
```

to:

```python
            local_id=d.get("local_id") or str(uuid.uuid4()),  # generate fresh id if absent or empty
```

- [ ] **Step 0.7: Run the full test suite**

Run: `pytest tests/ -v`
Expected: 93 passed (90 baseline + 3 new: 1 label_names isolation + 2 OpenRouter response-shape tests).

- [ ] **Step 0.8: Commit**

```bash
git add tasks/openrouter_client.py tasks/schema.py tests/test_tasks_schema.py tests/test_tasks_openrouter_client.py
git commit -m "fix(tasks): Phase-6.0 carry-forwards (KeyError, label_names test, timeout msg, local_id comment)"
```

---

## Task 1: Persistence module (`tasks/persistence.py`)

**Goal:** Atomic save/load of `tasks_raw.json` in a history entry folder. Pure stdlib, fully unit-tested.

**Files:**
- Create: `tasks/persistence.py`
- Create: `tests/test_tasks_persistence.py`
- Modify: `tasks/__init__.py` (drop one stale "(Phase 6.1)" marker on persistence)

- [ ] **Step 1.1: Write failing tests for `save_tasks_raw` / `load_tasks_raw`**

Create `tests/test_tasks_persistence.py`:

```python
"""Tests for tasks.persistence — disk I/O via pytest tmp_path, no real history."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tasks.persistence import (
    PersistenceError, load_tasks_raw, save_tasks_raw, RAW_FILENAME,
)
from tasks.schema import Priority, Task


def _sample_tasks() -> list[Task]:
    return [
        Task(title="A", priority=Priority.HIGH, assignee_id="u1", assignee_name="Айдар"),
        Task(title="B", description="Multi\nline", label_ids=["l1"], label_names=["bug"]),
    ]


def _sample_meta() -> dict:
    return {
        "extracted_at": "2026-04-28T15:30:00",
        "model": "anthropic/claude-sonnet-4.5",
        "team_id": "team-uuid",
        "team_name": "Engineering",
        "transcript_lang": "ru",
    }


# ── save_tasks_raw ─────────────────────────────────────────────────────


def test_save_writes_tasks_raw_json_to_folder(tmp_path: Path):
    save_tasks_raw(str(tmp_path), _sample_tasks(), _sample_meta())
    raw = tmp_path / RAW_FILENAME
    assert raw.is_file()
    data = json.loads(raw.read_text(encoding="utf-8"))
    assert data["model"] == "anthropic/claude-sonnet-4.5"
    assert data["team_id"] == "team-uuid"
    assert data["transcript_lang"] == "ru"
    assert isinstance(data["tasks"], list)
    assert len(data["tasks"]) == 2
    assert data["tasks"][0]["title"] == "A"
    assert data["tasks"][0]["priority"] == "high"   # enum-as-string


def test_save_does_not_include_local_send_state_in_raw(tmp_path: Path):
    """tasks_raw.json is the LLM's output as-extracted — no selected/status/linear_*.

    Those are user/local-only and belong in tasks.json (Phase 6.2)."""
    save_tasks_raw(str(tmp_path), _sample_tasks(), _sample_meta())
    data = json.loads((tmp_path / RAW_FILENAME).read_text(encoding="utf-8"))
    sample = data["tasks"][0]
    assert "selected" not in sample
    assert "status" not in sample
    assert "linear_issue_id" not in sample
    assert "linear_issue_url" not in sample
    assert "send_error" not in sample
    # local_id IS preserved — it's the durable handle the editor uses.
    assert "local_id" in sample


def test_save_creates_folder_if_missing(tmp_path: Path):
    target = tmp_path / "new-history-entry"
    assert not target.exists()
    save_tasks_raw(str(target), _sample_tasks(), _sample_meta())
    assert (target / RAW_FILENAME).is_file()


def test_save_is_atomic_via_temp_file_rename(tmp_path: Path, monkeypatch):
    """If json.dumps somehow fails midway, no partial tasks_raw.json is left."""
    # Pre-populate so we can verify atomicity:
    save_tasks_raw(str(tmp_path), _sample_tasks(), _sample_meta())
    original = (tmp_path / RAW_FILENAME).read_text(encoding="utf-8")

    # Now poison json.dumps and try a "second save" — original file must be intact.
    import tasks.persistence as P
    original_dumps = P.json.dumps

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure mid-encode")

    monkeypatch.setattr(P.json, "dumps", boom)
    with pytest.raises(RuntimeError):
        save_tasks_raw(str(tmp_path), [Task(title="C")], _sample_meta())

    monkeypatch.setattr(P.json, "dumps", original_dumps)
    # Original file untouched:
    assert (tmp_path / RAW_FILENAME).read_text(encoding="utf-8") == original


# ── load_tasks_raw ─────────────────────────────────────────────────────


def test_load_round_trips_save(tmp_path: Path):
    tasks_in = _sample_tasks()
    save_tasks_raw(str(tmp_path), tasks_in, _sample_meta())
    loaded = load_tasks_raw(str(tmp_path))
    assert loaded["model"] == "anthropic/claude-sonnet-4.5"
    out = loaded["tasks"]
    assert len(out) == 2
    assert out[0].title == "A"
    assert out[0].priority is Priority.HIGH
    assert out[0].assignee_name == "Айдар"
    assert out[1].label_names == ["bug"]


def test_load_raises_persistence_error_on_missing_file(tmp_path: Path):
    with pytest.raises(PersistenceError, match="not found"):
        load_tasks_raw(str(tmp_path))


def test_load_raises_persistence_error_on_malformed_json(tmp_path: Path):
    (tmp_path / RAW_FILENAME).write_text("not json at all", encoding="utf-8")
    with pytest.raises(PersistenceError, match="malformed"):
        load_tasks_raw(str(tmp_path))
```

- [ ] **Step 1.2: Run tests to confirm they fail with ImportError**

Run: `pytest tests/test_tasks_persistence.py -v`
Expected: All FAIL — `ModuleNotFoundError: No module named 'tasks.persistence'`.

- [ ] **Step 1.3: Implement `tasks/persistence.py`**

Create `tasks/persistence.py`:

```python
"""On-disk persistence for the tasks pipeline.

Phase 6.1 writes ``tasks_raw.json`` — the immutable LLM-extraction snapshot —
into the active history-entry folder. Phase 6.2 will add ``tasks.json`` for
the editable, user-state-bearing version.

Atomic write: dump JSON to ``<folder>/.tasks_raw.json.tmp`` then ``os.replace``
into place. Prevents a partial file on disk if the process dies mid-write.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from tasks.schema import Task

RAW_FILENAME = "tasks_raw.json"

# Subset of Task.to_dict() keys persisted to tasks_raw.json. We deliberately
# omit the local-only send-state fields — that's the audit-trail discipline
# from the spec ("tasks_raw.json is immutable").
_RAW_FIELDS = (
    "local_id", "title", "description", "priority",
    "assignee_id", "assignee_name", "label_ids", "label_names", "due_date",
)


class PersistenceError(Exception):
    """Disk read/write failures bubble up as this."""


def _task_to_raw_dict(task: Task) -> dict:
    full = task.to_dict()
    return {k: full[k] for k in _RAW_FIELDS}


def save_tasks_raw(folder: str, tasks: list[Task], meta: dict) -> None:
    """Atomically write ``<folder>/tasks_raw.json``.

    ``meta`` keys: extracted_at, model, team_id, team_name, transcript_lang.
    Folder is created if missing.

    Raises PersistenceError on OS-level failure. Re-raises whatever
    json.dumps raises (callers in tests poison json.dumps to verify atomicity).
    """
    target_dir = Path(folder)
    target_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        **meta,
        "tasks": [_task_to_raw_dict(t) for t in tasks],
    }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)

    final = target_dir / RAW_FILENAME
    tmp = target_dir / f".{RAW_FILENAME}.tmp"
    try:
        tmp.write_text(encoded, encoding="utf-8")
        os.replace(tmp, final)
    except OSError as e:
        # Best-effort cleanup of the temp file before re-raising.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise PersistenceError(f"Не удалось записать {RAW_FILENAME}: {e}") from e


def load_tasks_raw(folder: str) -> dict:
    """Read ``<folder>/tasks_raw.json`` and return ``{**meta, 'tasks': [Task, ...]}``.

    Raises PersistenceError if the file is missing or malformed.
    """
    path = Path(folder) / RAW_FILENAME
    if not path.is_file():
        raise PersistenceError(f"{RAW_FILENAME} not found in {folder}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise PersistenceError(f"{RAW_FILENAME} malformed in {folder}: {e}") from e

    raw_tasks = data.pop("tasks", [])
    return {**data, "tasks": [Task.from_dict(t) for t in raw_tasks]}
```

- [ ] **Step 1.4: Update `tasks/__init__.py` docstring**

In `tasks/__init__.py`, change:

```python
- persistence: (Phase 6.1) save/load tasks_raw.json and tasks.json.
```

to:

```python
- persistence: save/load tasks_raw.json (Phase 6.1) and tasks.json (Phase 6.2).
```

- [ ] **Step 1.5: Run tests to verify they pass**

Run: `pytest tests/test_tasks_persistence.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 1.6: Run the full suite**

Run: `pytest tests/ -v`
Expected: 100 passed (93 + 7).

- [ ] **Step 1.7: Commit**

```bash
git add tasks/persistence.py tasks/__init__.py tests/test_tasks_persistence.py
git commit -m "feat(tasks): persistence module (save/load tasks_raw.json) + 7 tests"
```

---

## Task 2: Extractor module (`tasks/extractor.py`)

**Goal:** Pure orchestration — given a transcript and the team-context provider, returns a validated `list[Task]` plus a corrections counter. No I/O, no Tk. Testable with mocked clients.

**Files:**
- Create: `tasks/extractor.py`
- Create: `tests/test_tasks_extractor.py`

- [ ] **Step 2.1: Write failing tests for `parse_and_validate`**

Create `tests/test_tasks_extractor.py`:

```python
"""Tests for tasks.extractor — pure logic with mocked clients, no real network."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tasks.extractor import (
    ExtractionError, build_prompt, extract, parse_and_validate,
)
from tasks.schema import Priority


# ── Fixtures ──────────────────────────────────────────────────────────


def _members():
    return [
        {"id": "u-aidar", "name": "Aidar", "displayName": "Айдар"},
        {"id": "u-nur",   "name": "Nurgysa", "displayName": "Нурғыса"},
    ]


def _labels():
    return [
        {"id": "l-bug",     "name": "bug",     "color": "#f00"},
        {"id": "l-mobile",  "name": "mobile",  "color": "#0f0"},
    ]


def _llm_response(tasks: list[dict]) -> str:
    """Helper: format the JSON payload an LLM would return."""
    import json
    return json.dumps({"tasks": tasks}, ensure_ascii=False)


# ── parse_and_validate ───────────────────────────────────────────────


def test_parse_extracts_well_formed_task():
    raw = _llm_response([{
        "title": "Починить login",
        "description": "Айдар сообщил жалобы.",
        "priority": "high",
        "assignee_id": "u-aidar",
        "label_ids": ["l-bug"],
        "due_date": "2026-05-15",
    }])
    tasks, corrections = parse_and_validate(raw, _members(), _labels())
    assert len(tasks) == 1
    assert corrections == 0
    t = tasks[0]
    assert t.title == "Починить login"
    assert t.priority is Priority.HIGH
    assert t.assignee_id == "u-aidar"
    assert t.assignee_name == "Айдар"   # filled from team context
    assert t.label_ids == ["l-bug"]
    assert t.label_names == ["bug"]
    assert t.due_date == "2026-05-15"


def test_parse_strips_json_codefences():
    """Some models return ```json\\n{...}\\n``` despite explicit instructions."""
    raw = "```json\n" + _llm_response([{"title": "X"}]) + "\n```"
    tasks, _ = parse_and_validate(raw, _members(), _labels())
    assert len(tasks) == 1
    assert tasks[0].title == "X"


def test_parse_strips_plain_codefences():
    """Same again with the language-less ``` variant."""
    raw = "```\n" + _llm_response([{"title": "Y"}]) + "\n```"
    tasks, _ = parse_and_validate(raw, _members(), _labels())
    assert len(tasks) == 1


def test_parse_drops_task_with_empty_title():
    raw = _llm_response([
        {"title": "", "priority": "high"},
        {"title": "Valid one", "priority": "low"},
    ])
    tasks, corrections = parse_and_validate(raw, _members(), _labels())
    assert len(tasks) == 1
    assert tasks[0].title == "Valid one"
    assert corrections >= 1   # at least one task dropped


def test_parse_filters_hallucinated_assignee():
    raw = _llm_response([{"title": "T", "assignee_id": "u-ghost"}])
    tasks, corrections = parse_and_validate(raw, _members(), _labels())
    assert len(tasks) == 1
    assert tasks[0].assignee_id is None
    assert tasks[0].assignee_name is None
    assert corrections == 1


def test_parse_filters_hallucinated_labels_keeps_valid():
    raw = _llm_response([{"title": "T", "label_ids": ["l-bug", "l-ghost", "l-mobile"]}])
    tasks, corrections = parse_and_validate(raw, _members(), _labels())
    assert tasks[0].label_ids == ["l-bug", "l-mobile"]
    assert tasks[0].label_names == ["bug", "mobile"]
    assert corrections == 1   # one label dropped


def test_parse_unknown_priority_falls_back_to_none_with_correction():
    raw = _llm_response([{"title": "T", "priority": "supercritical"}])
    tasks, corrections = parse_and_validate(raw, _members(), _labels())
    assert tasks[0].priority is Priority.NONE
    assert corrections == 1


def test_parse_legitimate_none_priority_does_not_count_as_correction():
    """LLM legitimately returning 'none' is not a hallucination."""
    raw = _llm_response([{"title": "T", "priority": "none"}])
    tasks, corrections = parse_and_validate(raw, _members(), _labels())
    assert tasks[0].priority is Priority.NONE
    assert corrections == 0


def test_parse_due_date_more_than_30_days_in_past_is_cleared():
    """Spec: due_date >30 days in past → cleared, log warning."""
    raw = _llm_response([{"title": "T", "due_date": "2024-01-01"}])
    tasks, corrections = parse_and_validate(raw, _members(), _labels())
    assert tasks[0].due_date is None
    assert corrections == 1


def test_parse_due_date_recent_past_is_kept():
    """Within-30-days-past dates are kept (meeting on Friday, due Monday-of-last-week)."""
    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    raw = _llm_response([{"title": "T", "due_date": yesterday}])
    tasks, _ = parse_and_validate(raw, _members(), _labels())
    assert tasks[0].due_date == yesterday


def test_parse_invalid_due_date_format_is_cleared():
    raw = _llm_response([{"title": "T", "due_date": "tomorrow"}])
    tasks, corrections = parse_and_validate(raw, _members(), _labels())
    assert tasks[0].due_date is None
    assert corrections == 1


def test_parse_malformed_json_raises_extraction_error():
    with pytest.raises(ExtractionError, match="JSON"):
        parse_and_validate("not json at all", _members(), _labels())


def test_parse_no_tasks_key_raises_extraction_error():
    """LLM returned valid JSON but without the 'tasks' key."""
    with pytest.raises(ExtractionError, match="tasks"):
        parse_and_validate('{"other": []}', _members(), _labels())


def test_parse_all_invalid_tasks_raises_extraction_error():
    """If every task has empty/missing title, raise so the dialog can offer
    "Show raw response" — per spec edge case."""
    raw = _llm_response([{"title": ""}, {}, {"title": None}])
    with pytest.raises(ExtractionError, match="валидных"):
        parse_and_validate(raw, _members(), _labels())


# ── build_prompt ─────────────────────────────────────────────────────


def test_build_prompt_returns_system_user_message_pair():
    msgs = build_prompt("Hello world", _members(), _labels(), lang="ru")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    # System prompt contains team context:
    assert "u-aidar" in msgs[0]["content"]
    assert "Айдар"   in msgs[0]["content"]
    assert "l-bug"   in msgs[0]["content"]
    # User message contains transcript:
    assert "Hello world" in msgs[1]["content"]


def test_build_prompt_handles_unknown_language():
    msgs = build_prompt("X", _members(), _labels(), lang=None)
    # Doesn't crash, says "auto-detected" or similar:
    assert "auto" in msgs[1]["content"].lower() or msgs[1]["content"]


# ── extract (orchestrator) ───────────────────────────────────────────


def test_extract_calls_clients_and_returns_validated_tasks():
    """End-to-end with mocked clients."""
    linear = MagicMock()
    linear.team_context.return_value = {"members": _members(), "labels": _labels()}

    openrouter = MagicMock()
    openrouter.complete.return_value = {
        "content": _llm_response([
            {"title": "T1", "priority": "high", "assignee_id": "u-aidar"},
            {"title": "T2", "priority": "low"},
        ]),
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        "model": "anthropic/claude-sonnet-4.5",
    }

    result = extract(
        transcript="Some transcript text",
        team_id="team-uuid",
        model="anthropic/claude-sonnet-4.5",
        lang="ru",
        linear_client=linear,
        openrouter_client=openrouter,
    )

    linear.team_context.assert_called_once_with("team-uuid")
    openrouter.complete.assert_called_once()
    assert len(result["tasks"]) == 2
    assert result["corrections"] == 0
    assert result["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}
    assert result["model"] == "anthropic/claude-sonnet-4.5"
    # Raw response text preserved for "Show raw response" UI fallback:
    assert "T1" in result["raw_response"]


def test_extract_retries_without_json_mode_on_400():
    """If the model rejects response_format=json_object, fall back to
    prompt-instruction-only mode."""
    from tasks.openrouter_client import OpenRouterError

    linear = MagicMock()
    linear.team_context.return_value = {"members": _members(), "labels": _labels()}

    openrouter = MagicMock()
    # First call (json_mode=True) raises; second (json_mode=False) succeeds.
    openrouter.complete.side_effect = [
        OpenRouterError("OpenRouter вернул 400: response_format unsupported"),
        {
            "content": _llm_response([{"title": "T", "priority": "low"}]),
            "usage": {},
            "model": "deepseek/deepseek-v3",
        },
    ]

    result = extract(
        transcript="t", team_id="tid", model="deepseek/deepseek-v3", lang=None,
        linear_client=linear, openrouter_client=openrouter,
    )

    assert openrouter.complete.call_count == 2
    # First attempt with json_mode=True, second without:
    assert openrouter.complete.call_args_list[0].kwargs.get("json_mode") is True
    assert openrouter.complete.call_args_list[1].kwargs.get("json_mode") is False
    assert len(result["tasks"]) == 1


def test_extract_does_not_retry_on_non_400_error():
    """401, 429, network errors: surface immediately, no retry."""
    from tasks.openrouter_client import OpenRouterError

    linear = MagicMock()
    linear.team_context.return_value = {"members": _members(), "labels": _labels()}

    openrouter = MagicMock()
    openrouter.complete.side_effect = OpenRouterError("OpenRouter вернул 401: ...")

    with pytest.raises(OpenRouterError, match="401"):
        extract(transcript="t", team_id="tid", model="m", lang=None,
                linear_client=linear, openrouter_client=openrouter)
    assert openrouter.complete.call_count == 1


def test_extract_attaches_raw_response_to_extraction_error():
    """ExtractionError raised after a successful LLM call must carry the
    raw response so the dialog can display it to the user."""
    linear = MagicMock()
    linear.team_context.return_value = {"members": _members(), "labels": _labels()}

    bad_payload = "this is not JSON at all, sorry"
    openrouter = MagicMock()
    openrouter.complete.return_value = {
        "content": bad_payload, "usage": {}, "model": "x",
    }

    with pytest.raises(ExtractionError) as excinfo:
        extract(transcript="t", team_id="tid", model="m", lang=None,
                linear_client=linear, openrouter_client=openrouter)
    assert excinfo.value.raw_response == bad_payload
```

- [ ] **Step 2.2: Run tests to confirm they fail with ImportError**

Run: `pytest tests/test_tasks_extractor.py -v`
Expected: All FAIL — `ModuleNotFoundError: No module named 'tasks.extractor'`.

- [ ] **Step 2.3: Implement `tasks/extractor.py`**

Create `tasks/extractor.py`:

```python
"""Orchestrator for the tasks pipeline.

Pure logic with no I/O — receives `linear_client` and `openrouter_client`
as parameters so tests can inject mocks. The dialog is responsible for
constructing real clients and threading.

Public API:
    extract(transcript, team_id, model, lang, linear_client, openrouter_client)
        → {"tasks": list[Task], "corrections": int, "usage": dict,
           "model": str, "raw_response": str}

    build_prompt(transcript, members, labels, lang) → list[dict]   # exposed for tests
    parse_and_validate(raw_text, members, labels) → (list[Task], int)
    ExtractionError                                # raised on unrecoverable LLM-output issues
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Optional, Protocol

from tasks.openrouter_client import OpenRouterError
from tasks.schema import Priority, Task, priority_from_string

logger = logging.getLogger(__name__)

# Set of all priority strings that are "legitimate". Used to distinguish
# "the LLM said 'critical'" (corrections += 1) from "the LLM said 'none'"
# (no correction needed — that's the literal default).
_KNOWN_PRIORITIES = {"none", "low", "medium", "high", "urgent"}

# How far in the past a due_date may be before we treat it as a hallucination.
# Picks up "due tomorrow" said in a meeting last month — that's still useful.
_DUE_DATE_PAST_TOLERANCE = timedelta(days=30)

_CODEFENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


class ExtractionError(Exception):
    """LLM returned content that we cannot turn into any valid Task list.

    `raw_response` carries the offending LLM output so callers can show it
    to the user / log it for prompt tuning. Set by `extract()` after a
    successful network round-trip; None when raised before we have one.
    """
    def __init__(self, msg: str, raw_response: str | None = None):
        super().__init__(msg)
        self.raw_response = raw_response


class _LLMClient(Protocol):
    """Duck-typed shape we need from openrouter_client."""
    def complete(self, model: str, messages: list[dict],
                 json_mode: bool = ..., temperature: float = ...,
                 timeout: float = ...) -> dict: ...


class _LinearClient(Protocol):
    """Duck-typed shape we need from linear_client."""
    def team_context(self, team_id: str) -> dict: ...


# ── Public functions ─────────────────────────────────────────────────


def build_prompt(
    transcript: str,
    members: list[dict],
    labels: list[dict],
    lang: Optional[str],
) -> list[dict]:
    """Construct the system+user message pair fed to OpenRouter."""
    member_lines = "\n".join(
        f"- id={m['id']} | name={m.get('displayName') or m.get('name', '?')}"
        for m in members
    )
    label_lines = "\n".join(
        f"- id={lbl['id']} | name={lbl['name']}" for lbl in labels
    )
    system = (
        "You are a meeting-task extraction assistant. Output strictly valid JSON.\n"
        "No prose, no markdown fences. Required schema:\n"
        '{"tasks": [{\n'
        '  "title": "string, required",\n'
        '  "description": "string",\n'
        '  "priority": "none|low|medium|high|urgent",\n'
        '  "assignee_id": "id from team_members below, or null",\n'
        '  "label_ids": ["ids from team_labels below"],\n'
        '  "due_date": "YYYY-MM-DD or null"\n'
        "}]}\n\n"
        "Rules:\n"
        "- Only assign people whose IDs are in team_members below.\n"
        "- Only use label IDs from team_labels below.\n"
        "- If unsure, leave assignee_id null and label_ids empty.\n"
        "- Use the meeting's dominant language for title and description.\n\n"
        f"team_members:\n{member_lines or '(none)'}\n\n"
        f"team_labels:\n{label_lines or '(none)'}\n"
    )
    lang_hint = f"language: {lang}" if lang else "language: auto-detected"
    user = (
        f"Meeting transcript ({lang_hint}):\n\n"
        f"{transcript}\n\n"
        "Return only the JSON object."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]


def parse_and_validate(
    raw_text: str,
    members: list[dict],
    labels: list[dict],
) -> tuple[list[Task], int]:
    """Parse the LLM response, validate every field, return (tasks, corrections).

    Strips markdown codefences if present. Filters out hallucinated assignee
    and label IDs against the supplied team context. Drops tasks with empty
    titles. Raises ExtractionError on unrecoverable issues:
      - Malformed JSON
      - Missing top-level 'tasks' key
      - Every task fails the title rule
    """
    cleaned = _strip_codefence(raw_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ExtractionError(f"LLM вернул некорректный JSON: {e}") from e

    if not isinstance(data, dict) or "tasks" not in data:
        raise ExtractionError(
            "LLM ответ не содержит ключ 'tasks'. Попробуйте другую модель."
        )

    member_ids = {m["id"] for m in members}
    member_name_by_id = {
        m["id"]: m.get("displayName") or m.get("name") or m["id"]
        for m in members
    }
    label_ids_set = {l["id"] for l in labels}
    label_name_by_id = {l["id"]: l["name"] for l in labels}

    tasks: list[Task] = []
    corrections = 0

    for raw_item in data.get("tasks", []):
        if not isinstance(raw_item, dict):
            corrections += 1
            logger.warning("LLM task item is not a dict: %r", raw_item)
            continue

        title = (raw_item.get("title") or "").strip()
        if not title:
            corrections += 1
            logger.warning("dropping task with empty title: %r", raw_item)
            continue

        # Priority
        raw_priority = raw_item.get("priority")
        priority = priority_from_string(raw_priority)
        if (
            raw_priority is not None
            and isinstance(raw_priority, str)
            and raw_priority.strip().lower() not in _KNOWN_PRIORITIES
            and raw_priority.strip() != ""   # empty string → legitimate fallback
        ):
            corrections += 1
            logger.warning(
                "unknown priority %r → fallback NONE (task=%r)", raw_priority, title,
            )

        # Assignee
        raw_assignee = raw_item.get("assignee_id")
        assignee_id: Optional[str] = None
        assignee_name: Optional[str] = None
        if raw_assignee:
            if raw_assignee in member_ids:
                assignee_id = raw_assignee
                assignee_name = member_name_by_id.get(raw_assignee)
            else:
                corrections += 1
                logger.warning(
                    "hallucinated assignee_id %r dropped (task=%r)",
                    raw_assignee, title,
                )

        # Labels
        raw_labels = raw_item.get("label_ids") or []
        clean_label_ids: list[str] = []
        for lid in raw_labels:
            if lid in label_ids_set:
                clean_label_ids.append(lid)
            else:
                corrections += 1
                logger.warning(
                    "hallucinated label_id %r dropped (task=%r)", lid, title,
                )
        clean_label_names = [label_name_by_id[lid] for lid in clean_label_ids]

        # Due date
        raw_due = raw_item.get("due_date")
        due_date = _validate_due_date(raw_due)
        if raw_due and due_date is None:
            corrections += 1
            logger.warning(
                "invalid/stale due_date %r cleared (task=%r)", raw_due, title,
            )

        description = raw_item.get("description") or ""
        if not isinstance(description, str):
            corrections += 1
            logger.warning("non-string description coerced to empty (task=%r)", title)
            description = ""

        tasks.append(Task(
            title=title,
            description=description,
            priority=priority,
            assignee_id=assignee_id,
            assignee_name=assignee_name,
            label_ids=clean_label_ids,
            label_names=clean_label_names,
            due_date=due_date,
        ))

    if not tasks:
        raise ExtractionError(
            "LLM не вернул валидных задач. Попробуйте другую модель."
        )

    return tasks, corrections


def extract(
    *,
    transcript: str,
    team_id: str,
    model: str,
    lang: Optional[str],
    linear_client: _LinearClient,
    openrouter_client: _LLMClient,
) -> dict:
    """Run the full extraction. Returns dict with tasks, corrections, usage,
    model echo, raw_response (for debugging / 'Show raw response' UI).

    Raises:
        OpenRouterError, LinearError — for network/HTTP/auth issues
        ExtractionError              — for unrecoverable LLM-output issues
    """
    ctx = linear_client.team_context(team_id)
    members = ctx.get("members") or []
    labels  = ctx.get("labels")  or []

    messages = build_prompt(transcript, members, labels, lang)

    # First attempt: JSON mode. Some models reject response_format with 400;
    # we detect via "400" in the error message and retry once without.
    try:
        response = openrouter_client.complete(
            model=model, messages=messages, json_mode=True,
        )
    except OpenRouterError as e:
        if "400" in str(e):
            logger.info(
                "model %s rejected json_mode, retrying without response_format",
                model,
            )
            response = openrouter_client.complete(
                model=model, messages=messages, json_mode=False,
            )
        else:
            raise

    raw_content = response["content"]
    try:
        tasks, corrections = parse_and_validate(raw_content, members, labels)
    except ExtractionError as e:
        # We have the raw LLM output here; attach it to the exception so
        # the dialog can show "Show raw response" affordance and so log
        # readers can debug prompt issues directly.
        logger.warning(
            "ExtractionError; raw LLM response logged for review:\n%s",
            raw_content[:2000],
        )
        raise ExtractionError(str(e), raw_response=raw_content) from e

    return {
        "tasks": tasks,
        "corrections": corrections,
        "usage": response.get("usage", {}),
        "model": response.get("model", model),
        "raw_response": raw_content,
    }


# ── Helpers ──────────────────────────────────────────────────────────


def _strip_codefence(text: str) -> str:
    """Remove ``` or ```json fences if the response is wrapped in them."""
    m = _CODEFENCE_RE.match(text or "")
    return m.group(1) if m else (text or "")


def _validate_due_date(raw: object) -> Optional[str]:
    """Accept ISO YYYY-MM-DD strings within tolerance window. Else None."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        d = datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None
    if date.today() - d > _DUE_DATE_PAST_TOLERANCE:
        return None
    return d.isoformat()
```

- [ ] **Step 2.4: Run extractor tests to verify they pass**

Run: `pytest tests/test_tasks_extractor.py -v`
Expected: All 20 tests PASS.

- [ ] **Step 2.5: Run the full suite**

Run: `pytest tests/ -v`
Expected: 120 passed (100 from Tasks 0–1 + 20 new in Task 2).

- [ ] **Step 2.6: Commit**

```bash
git add tasks/extractor.py tests/test_tasks_extractor.py
git commit -m "feat(tasks): extractor module with JSON-mode fallback + post-LLM validation"
```

---

## Task 3: App-side wiring (button + history-folder capture + gate-check)

**Goal:** Wire the main window: capture the active history folder when transcription completes, add the "Извлечь задачи" button, gate-check API keys before launching the dialog. Logic-only — the dialog itself is Task 4.

**Files:**
- Modify: `ui/app.py` (5 small edits)

- [ ] **Step 3.1: Add `_last_history_folder` field on the App**

In `ui/app.py`, find the `__init__` method and locate where instance variables like `self._cancel_event`, `self._monitor_dialog`, `self._settings_dialog` are initialized. After those lines, add:

```python
        # Path to the most recent successful transcription's history folder.
        # Populated in _on_complete; consumed by _open_extract_tasks_dialog.
        self._last_history_folder: str | None = None
```

(If you can't find the exact insertion point, use `Grep` for `self._settings_dialog =` in `ui/app.py` and add the new line right after.)

- [ ] **Step 3.2: Capture the history folder return value in `_on_complete`**

In `ui/app.py:954-970`, change the existing block:

```python
    def _on_complete(self, text: str):
        self._textbox.delete("1.0", "end")
        self._textbox.insert("1.0", text)
        self._progress.set(1.0)
        self._progress.configure(progress_color=GREEN)
        self._lbl_status.configure(text="Готово!", text_color=GREEN)
        self._btn_save.configure(state="normal")
        self._btn_copy.configure(state="normal")
        self._set_running(False)

        if self._audio_path:
            create_history_entry(
                audio_file_path=self._audio_path,
                transcript_text=text,
                language=LANGUAGES.get(self._lang_var.get()),
                model=MODELS.get(self._model_var.get(), ""),
            )
```

to (capture return value, enable extract button):

```python
    def _on_complete(self, text: str):
        self._textbox.delete("1.0", "end")
        self._textbox.insert("1.0", text)
        self._progress.set(1.0)
        self._progress.configure(progress_color=GREEN)
        self._lbl_status.configure(text="Готово!", text_color=GREEN)
        self._btn_save.configure(state="normal")
        self._btn_copy.configure(state="normal")
        self._btn_extract_tasks.configure(state="normal")
        self._set_running(False)

        if self._audio_path:
            self._last_history_folder = create_history_entry(
                audio_file_path=self._audio_path,
                transcript_text=text,
                language=LANGUAGES.get(self._lang_var.get()),
                model=MODELS.get(self._model_var.get(), ""),
            )
```

- [ ] **Step 3.3: Add the "Извлечь задачи" button to the bottom row**

In `ui/app.py:360-376`, change the button-row block:

```python
        self._btn_copy = tonal_button(
            btn_frame, text="Копировать", command=self._copy_text,
            width=150, state="disabled",
        )
        self._btn_copy.grid(row=0, column=1, padx=8, pady=4)

        self._btn_history = tonal_button(
            btn_frame, text="История", command=self._open_history_dialog,
            width=130,
        )
        self._btn_history.grid(row=0, column=2, padx=8, pady=4)

        self._btn_cutter = tonal_button(
            btn_frame, text="Audio Cutter", command=self._open_cutter,
            width=140,
        )
        self._btn_cutter.grid(row=0, column=3, padx=8, pady=4)
```

to (insert Извлечь at column=2, push others right):

```python
        self._btn_copy = tonal_button(
            btn_frame, text="Копировать", command=self._copy_text,
            width=150, state="disabled",
        )
        self._btn_copy.grid(row=0, column=1, padx=8, pady=4)

        self._btn_extract_tasks = tonal_button(
            btn_frame, text="Извлечь задачи",
            command=self._open_extract_tasks_dialog,
            width=160, state="disabled",
        )
        self._btn_extract_tasks.grid(row=0, column=2, padx=8, pady=4)

        self._btn_history = tonal_button(
            btn_frame, text="История", command=self._open_history_dialog,
            width=130,
        )
        self._btn_history.grid(row=0, column=3, padx=8, pady=4)

        self._btn_cutter = tonal_button(
            btn_frame, text="Audio Cutter", command=self._open_cutter,
            width=140,
        )
        self._btn_cutter.grid(row=0, column=4, padx=8, pady=4)
```

- [ ] **Step 3.4: Enable the button when history is loaded into main**

In `ui/app.py:444-463` (`_load_history_into_main`), find:

```python
        self._btn_save.configure(state="normal")
        self._btn_copy.configure(state="normal")
```

and change to:

```python
        self._btn_save.configure(state="normal")
        self._btn_copy.configure(state="normal")
        # The history entry's folder IS the target for any future extract.
        self._last_history_folder = os.path.dirname(audio_path) if audio_path else None
        self._btn_extract_tasks.configure(
            state="normal" if self._last_history_folder else "disabled",
        )
```

(`audio_path` here points to a file inside the history folder, so `dirname` gives the folder. If there's no audio path, the user only has free-floating text — extract still works but won't have anywhere to save tasks_raw.json, so we keep the button disabled.)

- [ ] **Step 3.5: Add `_open_extract_tasks_dialog` method**

In `ui/app.py`, find `_open_history_dialog` ([ui/app.py:441](ui/app.py:441)). Add this method directly after it:

```python
    def _open_extract_tasks_dialog(self):
        """Validate API keys are set, then open the Extract dialog."""
        # Gate-check: both keys must be present in config. Mirrors the
        # cloud-mode key check at line 790-797.
        openrouter_key = (self._config.get("openrouter_api_key") or "").strip()
        linear_key     = (self._config.get("linear_api_key") or "").strip()
        if not openrouter_key or not linear_key:
            messagebox.showwarning(
                "Нет API-ключей",
                "Извлечение задач требует двух ключей:\n"
                "  • OpenRouter — чтобы вызвать LLM\n"
                "  • Linear — чтобы получить список команд и участников\n\n"
                "Откройте Настройки и введите ключи.",
            )
            return

        transcript = self._textbox.get("1.0", "end").strip()
        if not transcript:
            messagebox.showwarning(
                "Нет транскрипции",
                "Сначала запустите транскрипцию или загрузите её из Истории.",
            )
            return

        if not self._last_history_folder:
            messagebox.showwarning(
                "Нет папки истории",
                "Извлечение пишет результат в папку из Истории. "
                "Запустите транскрипцию или откройте запись из Истории, "
                "затем повторите.",
            )
            return

        # Lazy import — pulls in tasks/extractor and (transitively) requests.
        # Same pattern as Settings dialog's lazy validate-button imports.
        from ui.dialogs.extract_tasks import ExtractTasksDialog
        ExtractTasksDialog(
            self,
            transcript=transcript,
            history_folder=self._last_history_folder,
            transcript_lang=LANGUAGES.get(self._lang_var.get()),
            config=self._config,
        )
```

- [ ] **Step 3.6: Run app, smoke-check that the button appears and is greyed out**

Run: `python main.py` (or whatever the app entry point is — verify with `Glob` for `main.py`).

Manual checks:
- App launches without errors.
- Bottom row reads: `[Сохранить (TXT/SRT/VTT)] [Копировать] [Извлечь задачи] [История] [Audio Cutter]`.
- "Извлечь задачи" is **disabled** (grey).
- Click Settings → existing OpenRouter and Linear sections still work.
- Close the app cleanly.

If layout is broken (e.g. button row wraps), increase `btn_frame` width or shorten button labels — adjust `width=` values until the row fits.

- [ ] **Step 3.7: Commit**

```bash
git add ui/app.py
git commit -m "feat(app): add 'Извлечь задачи' button + history-folder capture (disabled, no dialog yet)"
```

---

## Task 4: ExtractTasksDialog (minimal Phase-6.1 form)

**Goal:** The dialog the button opens. Model + team dropdowns, [↻] team-refresh, [Извлечь] button, JSON textbox for the result, status badge. Cancel-on-close.

**Files:**
- Create: `ui/dialogs/extract_tasks.py` (~330 lines including comments)

This is a UI-heavy task with no unit tests. Each step is self-contained — implement, run the app, verify visually, then move on.

- [ ] **Step 4.1: Create the dialog skeleton**

Create `ui/dialogs/extract_tasks.py`:

```python
"""Extract Tasks dialog — Phase 6.1 minimal version.

Layout (~640×520):
    [Модель ▾] [Команда ▾] [↻]   [Извлечь]    ← header row
    ─────────────────────────────────────────
    Стоимость ≈ $0.09                          ← cost hint (above textbox)
    ✓ Извлечено 12 задач (3 поля скорректированы)
    ┌─────────────────────────────────────────┐
    │ {                                        │
    │   "tasks": [...]                        │   ← raw JSON, read-only
    │ }                                        │
    └─────────────────────────────────────────┘
    Сохранено: history/.../tasks_raw.json    [Закрыть]

Phase 6.2 will replace the JSON textbox with a master-detail editor;
this dialog deliberately keeps the JSON view minimal so the swap is
isolated.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta
from tkinter import messagebox
from typing import Optional

import customtkinter as ctk

from theme import (
    BG, BORDER, FONT, GREEN, INPUT_BG, RED, SURFACE,
    TEXT_PRIMARY, TEXT_SECONDARY,
)
from ui.widgets import label, option_menu, primary_button, tonal_button
from utils import save_config


# Same curated list as Settings → OpenRouter section, kept in sync manually.
# (Phase 6.4 may replace both with a live /models browser.)
_CURATED_MODELS = [
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-haiku-4.5",
    "openai/gpt-4o",
    "google/gemini-2.5-pro",
    "deepseek/deepseek-v3",
]

_TEAMS_CACHE_KEY = "linear_teams_cache"
_TEAMS_CACHE_TTL = timedelta(hours=24)
_RECENT_MODELS_KEY = "tasks_recent_models"
_RECENT_MODELS_LIMIT = 5

# Sonnet-4.5 input price per 1M tokens. Used for the cost-estimate hint.
# Imprecise (we don't know the actual model's price) but useful as a sanity-check.
_COST_PER_1M_INPUT_TOKENS_USD = 3.0


class ExtractTasksDialog(ctk.CTkToplevel):
    """Phase-6.1 dialog. Master-detail editor lands in Phase 6.2."""

    def __init__(
        self,
        parent,
        *,
        transcript: str,
        history_folder: str,
        transcript_lang: Optional[str],
        config: dict,
    ):
        super().__init__(parent)
        self._parent = parent
        self._transcript = transcript
        self._history_folder = history_folder
        self._transcript_lang = transcript_lang
        self._config = config

        # Worker-thread plumbing: cancel_event flips on close;
        # active_client is the in-flight client we close to interrupt sockets.
        self._cancel_event = threading.Event()
        self._active_clients: list = []   # OpenRouter + Linear clients in flight
        self._teams: list[dict] = []      # populated by bootstrap

        self.title("Извлечение задач")
        self.geometry("640x520")
        self.configure(fg_color=BG)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.grab_set()

        self._build_ui()
        self._load_teams_async()
```

- [ ] **Step 4.2: Implement `_build_ui`**

Append to `ui/dialogs/extract_tasks.py`:

```python
    # ── UI construction ──────────────────────────────────────────

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)   # textbox row stretches

        # --- Header row: model + team + refresh + extract ---
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=16, pady=(14, 6), sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        header.grid_columnconfigure(3, weight=1)

        label(header, "Модель").grid(row=0, column=0, padx=(0, 6), sticky="w")
        default_model = self._config.get(
            "tasks_default_model", _CURATED_MODELS[0],
        )
        recent = self._config.get(_RECENT_MODELS_KEY, []) or []
        all_models = list(_CURATED_MODELS)
        for slug in recent:
            if slug not in all_models:
                all_models.append(slug)
        self._model_var = ctk.StringVar(value=default_model)
        # CTkComboBox lets the user type custom slugs that aren't in the list.
        self._model_combo = ctk.CTkComboBox(
            header, variable=self._model_var, values=all_models,
            width=280, height=32,
            font=ctk.CTkFont(family=FONT, size=12),
            border_color=BORDER, button_color=BORDER,
            fg_color=INPUT_BG, text_color=TEXT_PRIMARY,
        )
        self._model_combo.grid(row=0, column=1, padx=(0, 12), sticky="ew")

        label(header, "Команда").grid(row=0, column=2, padx=(0, 6), sticky="w")
        self._team_var = ctk.StringVar(value="(загрузка...)")
        self._team_menu = ctk.CTkComboBox(
            header, variable=self._team_var, values=["(загрузка...)"],
            width=200, height=32, state="readonly",
            font=ctk.CTkFont(family=FONT, size=12),
            border_color=BORDER, button_color=BORDER,
            fg_color=INPUT_BG, text_color=TEXT_PRIMARY,
        )
        self._team_menu.grid(row=0, column=3, padx=(0, 4), sticky="ew")

        self._btn_refresh = tonal_button(
            header, text="↻", command=self._refresh_teams, width=36,
        )
        self._btn_refresh.grid(row=0, column=4, padx=(0, 8))

        self._btn_extract = primary_button(
            header, text="Извлечь", command=self._on_extract, width=120,
        )
        self._btn_extract.grid(row=0, column=5)

        # --- Status / cost hint row ---
        self._status_label = label(self, "", anchor="w")
        self._status_label.grid(row=1, column=0, padx=18, pady=(2, 4), sticky="ew")
        self._update_cost_hint()

        # --- JSON textbox (read-only after extract) ---
        self._json_box = ctk.CTkTextbox(
            self, wrap="word", corner_radius=10,
            fg_color=SURFACE, text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self._json_box.grid(row=2, column=0, padx=16, pady=(2, 4), sticky="nsew")
        self._json_box.configure(state="disabled")  # nothing to show yet

        # --- Footer: saved-path + close ---
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, padx=16, pady=(2, 14), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        self._saved_label = label(footer, "", anchor="w")
        self._saved_label.grid(row=0, column=0, sticky="ew")
        tonal_button(
            footer, text="Закрыть", command=self._on_close, width=110,
        ).grid(row=0, column=1, sticky="e")

    def _update_cost_hint(self) -> None:
        """Heuristic: ~chars/4 input tokens × Sonnet pricing × 1.3 (output)."""
        chars = len(self._transcript or "")
        approx_tokens = max(chars // 4, 1)
        cost = approx_tokens / 1_000_000 * _COST_PER_1M_INPUT_TOKENS_USD * 1.3
        self._status_label.configure(
            text=f"Стоимость ≈ ${cost:.2f} (≈ {approx_tokens:,} токенов)",
            text_color=TEXT_SECONDARY,
        )
```

- [ ] **Step 4.3: Implement `_load_teams_async` + `_refresh_teams`**

Append to `ui/dialogs/extract_tasks.py`:

```python
    # ── Team bootstrap (cached 24h) ──────────────────────────────

    def _load_teams_async(self) -> None:
        """Use cache if fresh; else fetch from Linear in a worker."""
        cache = self._config.get(_TEAMS_CACHE_KEY) or {}
        fetched_at = cache.get("fetched_at")
        if fetched_at:
            try:
                age = datetime.now() - datetime.fromisoformat(fetched_at)
            except ValueError:
                age = _TEAMS_CACHE_TTL + timedelta(seconds=1)
            if age <= _TEAMS_CACHE_TTL and cache.get("data"):
                self._teams = list(cache["data"])
                self._populate_team_dropdown()
                return

        self._fetch_teams_in_worker()

    def _refresh_teams(self) -> None:
        """[↻] forces a fetch regardless of cache age."""
        self._team_var.set("(обновление...)")
        self._team_menu.configure(values=["(обновление...)"])
        self._fetch_teams_in_worker()

    def _fetch_teams_in_worker(self) -> None:
        api_key = (self._config.get("linear_api_key") or "").strip()
        if not api_key:
            self._team_var.set("(нет ключа Linear)")
            return

        def worker():
            try:
                from tasks.linear_client import LinearClient, LinearError
                client = LinearClient(api_key)
                self._active_clients.append(client)
                try:
                    result = client.bootstrap()
                finally:
                    self._active_clients.remove(client)
                    client.close()
            except Exception as e:
                if self._cancel_event.is_set():
                    return  # dialog already closing; ignore
                self.after(0, self._on_teams_error, str(e))
                return

            if self._cancel_event.is_set():
                return
            teams = result.get("teams", [])
            self._config[_TEAMS_CACHE_KEY] = {
                "data": teams,
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
            }
            save_config(self._config)
            self.after(0, self._on_teams_loaded, teams)

        threading.Thread(target=worker, daemon=True).start()

    def _on_teams_loaded(self, teams: list[dict]) -> None:
        self._teams = teams
        self._populate_team_dropdown()

    def _on_teams_error(self, msg: str) -> None:
        self._team_var.set("(ошибка)")
        self._team_menu.configure(values=["(ошибка)"])
        self._status_label.configure(text=f"✗ {msg}", text_color=RED)

    def _populate_team_dropdown(self) -> None:
        if not self._teams:
            self._team_var.set("(нет команд)")
            self._team_menu.configure(values=["(нет команд)"])
            return
        labels = [f"{t['name']} ({t['key']})" for t in self._teams]
        self._team_menu.configure(values=labels)
        self._team_var.set(labels[0])
```

- [ ] **Step 4.4: Implement `_on_extract` and `_run_extraction` worker**

Append to `ui/dialogs/extract_tasks.py`:

```python
    # ── Извлечение ───────────────────────────────────────────────

    def _on_extract(self) -> None:
        team = self._selected_team()
        if not team:
            messagebox.showwarning(
                "Нет команды",
                "Выберите команду или нажмите [↻] для загрузки списка.",
            )
            return

        model = self._model_var.get().strip()
        if not model:
            messagebox.showwarning("Нет модели", "Введите slug модели OpenRouter.")
            return

        self._set_busy(True)
        self._status_label.configure(
            text="Запрос к Linear (team_context)...", text_color=TEXT_SECONDARY,
        )
        self._json_box.configure(state="normal")
        self._json_box.delete("1.0", "end")
        self._json_box.configure(state="disabled")
        self._saved_label.configure(text="")

        threading.Thread(
            target=self._run_extraction,
            args=(team, model),
            daemon=True,
        ).start()

    def _selected_team(self) -> Optional[dict]:
        label_value = self._team_var.get()
        for t in self._teams:
            if f"{t['name']} ({t['key']})" == label_value:
                return t
        return None

    def _run_extraction(self, team: dict, model: str) -> None:
        from tasks.extractor import extract, ExtractionError
        from tasks.linear_client import LinearClient, LinearError
        from tasks.openrouter_client import OpenRouterClient, OpenRouterError
        from tasks.persistence import save_tasks_raw

        linear = openrouter = None
        try:
            linear     = LinearClient(self._config["linear_api_key"])
            openrouter = OpenRouterClient(self._config["openrouter_api_key"])
            self._active_clients.extend([linear, openrouter])

            if self._cancel_event.is_set():
                return

            self.after(0, self._status_label.configure, {
                "text": f"Запрос к OpenRouter ({model})...",
                "text_color": TEXT_SECONDARY,
            })

            result = extract(
                transcript=self._transcript,
                team_id=team["id"],
                model=model,
                lang=self._transcript_lang,
                linear_client=linear,
                openrouter_client=openrouter,
            )

            if self._cancel_event.is_set():
                return

            meta = {
                "extracted_at": datetime.now().isoformat(timespec="seconds"),
                "model": result["model"],
                "team_id": team["id"],
                "team_name": team["name"],
                "transcript_lang": self._transcript_lang or "auto",
            }
            save_tasks_raw(self._history_folder, result["tasks"], meta)

            self._remember_recent_model(model)

            self.after(0, self._on_extract_success, result, meta)

        except ExtractionError as e:
            # ExtractionError carries `raw_response` when extract() got a
            # successful network round-trip but the payload was unusable.
            if not self._cancel_event.is_set():
                self.after(
                    0, self._on_extract_error, str(e), e.raw_response,
                )
        except (OpenRouterError, LinearError) as e:
            if not self._cancel_event.is_set():
                self.after(0, self._on_extract_error, str(e), None)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("extract failed")
            if not self._cancel_event.is_set():
                self.after(0, self._on_extract_error, f"{type(e).__name__}: {e}", None)
        finally:
            for c in (linear, openrouter):
                if c is not None:
                    try:
                        c.close()
                    except Exception:
                        pass
                    if c in self._active_clients:
                        self._active_clients.remove(c)
            self.after(0, self._set_busy, False)
```

- [ ] **Step 4.5: Implement success/error/busy handlers + remember-model + close**

Append to `ui/dialogs/extract_tasks.py`:

```python
    # ── UI updates marshalled from worker thread ─────────────────

    def _on_extract_success(self, result: dict, meta: dict) -> None:
        n = len(result["tasks"])
        corr = result["corrections"]
        if corr:
            self._status_label.configure(
                text=f"✓ Извлечено {n} задач ({corr} полей скорректированы)",
                text_color=GREEN,
            )
        else:
            self._status_label.configure(
                text=f"✓ Извлечено {n} задач",
                text_color=GREEN,
            )

        # Show what's actually on disk — guarantees "shown == saved".
        from pathlib import Path
        from tasks.persistence import RAW_FILENAME
        try:
            raw_path = Path(self._history_folder) / RAW_FILENAME
            content = raw_path.read_text(encoding="utf-8")
        except OSError:
            # Fallback: serialize the in-memory result if the file vanished.
            content = json.dumps(
                {**meta, "tasks": [t.to_dict() for t in result["tasks"]]},
                ensure_ascii=False, indent=2,
            )

        self._json_box.configure(state="normal")
        self._json_box.delete("1.0", "end")
        self._json_box.insert("1.0", content)
        self._json_box.configure(state="disabled")

        rel = os.path.relpath(
            os.path.join(self._history_folder, "tasks_raw.json"),
        )
        self._saved_label.configure(
            text=f"Сохранено: {rel}", text_color=TEXT_SECONDARY,
        )

    def _on_extract_error(self, msg: str, raw_response: Optional[str]) -> None:
        self._status_label.configure(text=f"✗ {msg}", text_color=RED)
        if raw_response:
            self._json_box.configure(state="normal")
            self._json_box.delete("1.0", "end")
            self._json_box.insert("1.0", raw_response)
            self._json_box.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self._btn_extract.configure(state=state)
        self._btn_refresh.configure(state=state)

    def _remember_recent_model(self, slug: str) -> None:
        """If `slug` is custom (not in curated list), prepend to FIFO-5 list."""
        if slug in _CURATED_MODELS:
            return
        recent = list(self._config.get(_RECENT_MODELS_KEY, []) or [])
        if slug in recent:
            recent.remove(slug)
        recent.insert(0, slug)
        recent = recent[:_RECENT_MODELS_LIMIT]
        self._config[_RECENT_MODELS_KEY] = recent
        save_config(self._config)

    def _on_close(self) -> None:
        """Cancel any in-flight worker, release the grab, destroy the toplevel."""
        self._cancel_event.set()
        # Closing the requests.Session sockets interrupts any blocked .post()
        # in the worker; it raises ConnectionError, which the worker catches
        # and exits silently because cancel_event is set.
        for c in list(self._active_clients):
            try:
                c.close()
            except Exception:
                pass
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
```

- [ ] **Step 4.6: Smoke-test the dialog (no API call)**

Run: `python main.py`

Manual checks:
- Transcribe a short audio file (or load one from History) — Извлечь задачи becomes enabled.
- Click Извлечь задачи → dialog opens.
- Header reads: `Модель: [<combobox>] Команда: [<combobox>] [↻] [Извлечь]`.
- Cost hint shows "Стоимость ≈ $X.XX".
- If keys are valid, team dropdown populates with team names.
- Click [Закрыть] — dialog closes cleanly, app remains responsive.
- Click [↻] — dropdown shows "(обновление...)" then re-populates.

Visually-not-required for this step:
- Извлечь happy path (Step 4.7).
- Mid-extract close (Step 4.8).

If layout looks broken, adjust widths/padx.

- [ ] **Step 4.7: Smoke-test extract happy path against real APIs**

Prerequisites:
- Real OpenRouter key with at least $0.20 balance.
- Real Linear key with access to a test team.
- A 1-2 minute Russian-language audio file already transcribed.

Steps:
1. Ensure the transcript is loaded in the main window.
2. Click Извлечь задачи.
3. Pick a team from the dropdown.
4. Click Извлечь.
5. Wait ~5-15s (status badge cycles: Запрос к Linear → Запрос к OpenRouter → ✓ Извлечено N задач).
6. JSON textbox populates with valid JSON.
7. Footer reads `Сохранено: history/<…>/tasks_raw.json`.
8. Open the file on disk — content matches the textbox.
9. Open `config.json` — `tasks_recent_models` list reflects the model used (if it was custom-typed).

Acceptance: at least 1 task in `tasks_raw.json` with title in Russian.

If the model returns invalid JSON or 0 valid tasks, the badge should read in red `✗ ...` and no `tasks_raw.json` is written. Verify by checking the folder.

- [ ] **Step 4.8: Smoke-test cancel-on-close**

1. Click Извлечь задачи on a long transcript.
2. Click Извлечь.
3. While the badge reads "Запрос к OpenRouter...", click [Закрыть].
4. Dialog closes immediately.
5. App is responsive (open Settings, History — no freeze).
6. Check `logs/app.log` — no traceback (the worker should have exited silently because `cancel_event` was set).

If the dialog hangs on close, the cancel mechanism didn't fire — investigate before merging.

- [ ] **Step 4.9: Commit**

```bash
git add ui/dialogs/extract_tasks.py
git commit -m "feat(extract): minimal Phase-6.1 dialog (model/team/extract → tasks_raw.json)"
```

---

## Task 5: Final integration smoke + tag

**Goal:** Make sure nothing regressed, then tag `phase-6.1`.

- [ ] **Step 5.1: Run the full test suite one more time**

Run: `pytest tests/ -v`
Expected: 120 passed (90 baseline + 30 new across Tasks 0–2). Zero failures.

- [ ] **Step 5.2: Manual end-to-end smoke (full pipeline)**

1. Fresh app launch.
2. Pick a 1-2 min audio file.
3. Transcribe (local or cloud — either path works).
4. Wait for transcript.
5. Click Извлечь задачи.
6. Pick a team, click Извлечь.
7. Verify badge: `✓ Извлечено N задач`.
8. Verify file: `history/<…>/tasks_raw.json` contains valid JSON with N tasks.
9. Re-open the dialog (Извлечь задачи again) — re-extract overwrites the file (current behavior, by design until Phase 6.4 adds re-open from History).
10. Close the app.

- [ ] **Step 5.3: Manual edge cases**

For each, check that the app surfaces a clean error (red status, no traceback, no freeze):

- a) Wrong OpenRouter key (mangle it in Settings, save, retry).
- b) Wrong Linear key (mangle it, retry — bootstrap should fail with clean error).
- c) No internet (kill Wi-Fi mid-extract — both client classes raise ConnectionError, badge turns red).
- d) Custom model slug that doesn't exist (`anthropic/totally-fake-model`) — OpenRouter returns 400, badge shows the message.
- e) Empty transcript (paste empty text, click Извлечь задачи) — gate-check fires.

- [ ] **Step 5.4: Commit any tweaks from smoke testing**

If any smoke-test surfaced a bug, fix it inline and commit:

```bash
git add <fixed files>
git commit -m "fix(extract): <description>"
```

If everything is green, skip this step.

- [ ] **Step 5.5: Tag the release**

```bash
git tag -a phase-6.1 -m "Phase 6.1: Extract dialog + extractor + persistence"
```

Don't push tag yet — wait for user's go-ahead.

- [ ] **Step 5.6: Write Phase 6.1 → 6.2 handoff**

Create `docs/superpowers/handoffs/2026-04-29-phase-6.1-to-6.2-handoff.md`:

```markdown
# Handoff: Phase 6.1 → Phase 6.2

**Status:** Phase 6.1 (Extract dialog + extractor + persistence) shipped to
`main` (tag `phase-6.1`). Phase 6.2 (master-detail editor) plan not yet
written.

## What's on `main` after Phase 6.1

(Auto-fill: paste `git diff phase-6.0..phase-6.1 --stat` here.)

## Carry-forward recommendations from Phase 6.1 reviews

(Fill after code-review pass — likely candidates: prompt-template hardening,
recent-models eviction edge cases, [↻]-while-extract-running guard.)

## Spec & plan locations

- Spec: `docs/superpowers/specs/2026-04-28-meeting-tasks-pipeline-design.md`
  (Phasing → Phase 6.2)
- Phase 6.1 plan: `docs/superpowers/plans/2026-04-28-meeting-tasks-phase-6.1.md`
- Phase 6.2 plan: not yet written

## Suggested first prompt for the next chat

(Same template as 6.0 → 6.1 handoff, swap phase numbers.)
```

This file is filled out post-merge — leave the auto-fill blocks empty for now.

- [ ] **Step 5.7: Final commit**

```bash
git add docs/superpowers/handoffs/2026-04-29-phase-6.1-to-6.2-handoff.md
git commit -m "docs: Phase 6.1 → 6.2 handoff stub"
```

---

## Spec Coverage Map

| Spec requirement | Implemented in | Verified by |
|---|---|---|
| "Извлечь задачи" button between Copy and History | Task 3.3 | Smoke 3.6, 5.2 |
| Button disabled without transcript | Task 3.3, 3.4 | Smoke 3.6 |
| Gate-check both API keys before opening dialog | Task 3.5 | Smoke 5.3 |
| Extract dialog with model+team dropdowns | Task 4.1, 4.2 | Smoke 4.6 |
| `linear_client.bootstrap()` with 24h cache | Task 4.3 | Smoke 4.6 |
| `[↻]` button forces refresh | Task 4.3 | Smoke 4.6 |
| Извлечь runs in worker thread | Task 4.4 | Smoke 4.7 |
| `team_context` per extract (not cached) | Task 4.4 (via `extractor.extract`) | Smoke 4.7 |
| OpenRouter call with team-context-augmented prompt | Task 2 (`build_prompt`) | Tests `test_build_prompt_*` |
| JSON-mode fallback to prompt-instruction | Task 2 (`extract`) | Test `test_extract_retries_without_json_mode_on_400` |
| Strip ```json fences | Task 2 (`_strip_codefence`) | Tests `test_parse_strips_*` |
| Post-LLM validation (assignee, label, priority, due-date) | Task 2 (`parse_and_validate`) | 7 dedicated tests |
| Empty-title task dropped | Task 2 | Test `test_parse_drops_task_with_empty_title` |
| All-tasks-invalid → ExtractionError | Task 2 | Test `test_parse_all_invalid_tasks_raises_extraction_error` |
| Show raw response on parse failure (in JSON box) | Task 2 (`ExtractionError.raw_response`) + Task 4.4/4.5 | Test `test_extract_attaches_raw_response_to_extraction_error` + Smoke 5.3(d) |
| Save `tasks_raw.json` to history folder | Task 1 + Task 4.4 | Smoke 4.7, 5.2 |
| Atomic write (no partial files) | Task 1 (`os.replace` from `.tmp`) | Test `test_save_is_atomic_via_temp_file_rename` |
| Status badge "✓ Извлечено N задач (M полей скорректированы)" | Task 4.5 | Smoke 4.7 |
| Cost estimate hint above Извлечь | Task 4.2 | Smoke 4.6 |
| `tasks_recent_models` FIFO-5 only on success | Task 4.5 (`_remember_recent_model`) | Smoke 4.7 step 9 |
| Cancellation by closing client sessions | Task 4.5 (`_on_close`) | Smoke 4.8 |
| Carry-forward #1 (KeyError client-level) | Task 0.4 | Tests `test_complete_raises_on_*` |
| Carry-forward #2 (label_names test) | Task 0.1 | Test added |
| Carry-forward #3 (timeout msg) | Task 0.3 | Inspection |
| Carry-forward #5 (local_id comment) | Task 0.6 | Inspection |
| Carry-forward #4 (settings grab_set) | **Deferred** | Per handoff guidance |

## Out-of-Scope (Defer to 6.2 / 6.3 / 6.4)

These appear in the spec but are NOT part of Phase 6.1:

- Master-detail editor (Phase 6.2)
- `tasks.json` (mutable user-state file) — Phase 6.2
- "+ Добавить задачу", "🗑 Удалить", undo stack — Phase 6.2
- "Отправить выбранные в Linear" + per-task statuses — Phase 6.3
- Re-open from History — Phase 6.4
- Retry/auto-retry on 429 — covered by client-level error messages; UI doesn't auto-retry
- AssemblyAI Validate parity — Phase 6.4
