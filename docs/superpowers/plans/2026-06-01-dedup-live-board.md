# Live-board Dedup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make task-dedup match newly-extracted tasks against the EXISTING open items on the live backend board (Linear team / Trello board) and comment on a confirmed match instead of creating a duplicate.

**Architecture:** Swap the dedup registry source from local meeting-history (`build_sent_registry`, which was empty because pre-#88 history has no `backend_ref`) to a live-board fetch via a new `backend.list_existing(container_id)`. The matching engine, dup badge, comment/create toggle, and `COMMENTED` status are already built and stay untouched. Add idempotent commenting (signature marker + pre-post check) and observability logging.

**Tech Stack:** Python 3.12, `requests` (Linear GraphQL / Trello REST), `difflib` (fuzzy), OpenRouter (LLM disambiguation), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-01-dedup-live-board-design.md`

---

## File structure

| File | Responsibility | Change |
|---|---|---|
| `tasks/backends/base.py` | backend contract + value types | + `ExistingItem`; + `list_existing`, `comment_exists` in Protocol |
| `tasks/dedup.py` | matching engine (pure) | + `dedup_signature`, `dedup_marker`, `build_board_registry`; `SentTask.description`; LLM prompt uses descriptions |
| `tasks/linear_client.py` | Linear GraphQL wrapper | + `list_issues` (paginated, active-only), `list_comments` |
| `tasks/backends/linear.py` | Linear adapter | + `list_existing`, `comment_exists` |
| `tasks/trello_client.py` | Trello REST wrapper | + `list_open_cards` (board-level), `list_card_comments` |
| `tasks/backends/trello.py` | Trello adapter | + `list_existing`, `comment_exists` |
| `tasks/sender.py` | send orchestrator | idempotency guard + marker in `_dup_comment_body` |
| `ui/dialogs/extract_tasks/__init__.py` | dialog `_run_dedup` | registry source swap + widen `except` + logging |

CI note: do NOT import `ui.app` / the dialog module in tests on Linux CI (sounddevice/PortAudio load at import — see existing `tests/test_dialog_dedup_ui.py`). Task 10 uses **source-text assertions**, the established pattern.

---

### Task 1: `ExistingItem` + dedup signature/marker + `SentTask.description`

**Files:**
- Modify: `tasks/backends/base.py`
- Modify: `tasks/dedup.py`
- Test: `tests/test_dedup_signature.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_dedup_signature.py
from tasks.backends.base import ExistingItem
from tasks.dedup import SentTask, dedup_marker, dedup_signature


def test_signature_stable_and_normalized():
    # Same title (modulo case/punct/space) → same signature.
    a = dedup_signature("Изучить систему СУП")
    b = dedup_signature("  изучить  систему,  суп ")
    assert a == b
    assert len(a) == 12


def test_signature_differs_for_different_titles():
    assert dedup_signature("Задача А") != dedup_signature("Задача Б")


def test_marker_wraps_signature():
    m = dedup_marker("Изучить систему СУП")
    assert m == f"<!-- audiotx-dedup:{dedup_signature('Изучить систему СУП')} -->"


def test_existing_item_defaults_description_empty():
    it = ExistingItem(title="t", ref="r", identifier="NUR-1", url="u")
    assert it.description == ""


def test_sent_task_accepts_description():
    s = SentTask(
        title="t", backend="linear", container_id="c", ref="r",
        identifier="NUR-1", url="u", meeting_name="", meeting_date="",
        description="d",
    )
    assert s.description == "d"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dedup_signature.py -v`
Expected: FAIL — `ImportError: cannot import name 'ExistingItem'` / `dedup_marker`.

- [ ] **Step 3: Implement**

In `tasks/backends/base.py`, add after the `CreatedIssue` dataclass:

```python
@dataclass(frozen=True)
class ExistingItem:
    """An open item already on a backend board, for dedup matching.

    `ref` is the comment-addressable id (Linear node UUID / Trello card id).
    `identifier`/`url` are the human badge + link. `description` feeds the
    LLM disambiguation of the borderline fuzzy band.
    """
    title: str
    ref: str
    identifier: str
    url: str
    description: str = ""
```

In the `TaskBackend` Protocol (after `add_comment`), add:

```python
    def list_existing(self, container_id: str) -> list["ExistingItem"]:
        """Open items on the container's board (active only — no
        completed/canceled/archived). For task-dedup. Only called for
        backends with supports_comments = True. Raises the backend's own
        error class on HTTP/network failure (the dedup driver swallows it
        best-effort)."""
        ...

    def comment_exists(self, ref: str, marker: str) -> bool:
        """True if the item already has a comment containing `marker`
        (idempotency for dedup re-runs). Raises the backend's error class
        on HTTP/network failure."""
        ...
```

In `tasks/dedup.py`, add `import hashlib` to the imports, add `description: str = ""` as the LAST field of `SentTask`:

```python
@dataclass(frozen=True)
class SentTask:
    # ... existing fields ...
    meeting_name: str
    meeting_date: str
    description: str = ""
```

and add the two helpers (after `normalize_title`):

```python
def dedup_signature(title: str) -> str:
    """Stable 12-hex signature of a title's normalized form. Used to mark
    dedup comments so a re-run does not post a duplicate comment."""
    return hashlib.sha1(normalize_title(title).encode("utf-8")).hexdigest()[:12]


def dedup_marker(title: str) -> str:
    """Hidden HTML-comment marker embedded in a dedup comment body."""
    return f"<!-- audiotx-dedup:{dedup_signature(title)} -->"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dedup_signature.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add tasks/backends/base.py tasks/dedup.py tests/test_dedup_signature.py
git commit -m "feat(dedup): ExistingItem + signature/marker helpers + SentTask.description"
```

---

### Task 2: `build_board_registry` in `tasks/dedup.py`

**Files:**
- Modify: `tasks/dedup.py`
- Test: `tests/test_dedup_board_registry.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_dedup_board_registry.py
import pytest

from tasks.backends.base import ExistingItem
from tasks.dedup import build_board_registry


class _FakeBackend:
    name = "linear"

    def __init__(self, items, *, raises=None):
        self._items = items
        self._raises = raises

    def list_existing(self, container_id):
        if self._raises:
            raise self._raises
        return self._items


def test_maps_existing_items_to_sent_tasks():
    backend = _FakeBackend([
        ExistingItem(title="Изучить систему СУП", ref="uuid-37",
                     identifier="NUR-37", url="http://x/37", description="desc"),
    ])
    reg = build_board_registry(backend, "team-1")
    assert len(reg) == 1
    s = reg[0]
    assert s.title == "Изучить систему СУП"
    assert s.backend == "linear"
    assert s.container_id == "team-1"
    assert s.ref == "uuid-37"
    assert s.identifier == "NUR-37"
    assert s.description == "desc"
    assert s.meeting_name == "" and s.meeting_date == ""


def test_skips_items_without_title_or_ref():
    backend = _FakeBackend([
        ExistingItem(title="", ref="r", identifier="x", url=""),
        ExistingItem(title="ok", ref="", identifier="x", url=""),
        ExistingItem(title="keep", ref="r2", identifier="NUR-2", url=""),
    ])
    reg = build_board_registry(backend, "team-1")
    assert [s.title for s in reg] == ["keep"]


def test_backend_error_propagates():
    backend = _FakeBackend([], raises=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        build_board_registry(backend, "team-1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dedup_board_registry.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_board_registry'`.

- [ ] **Step 3: Implement**

In `tasks/dedup.py`, add (after `build_sent_registry`):

```python
def build_board_registry(backend, container_id: str) -> list[SentTask]:
    """Build the dedup registry from the LIVE backend board.

    Calls ``backend.list_existing(container_id)`` and maps each open item to
    a ``SentTask`` scoped to this backend + container so the existing
    ``find_candidates`` scope filter passes. Items missing a title or a
    comment-addressable ``ref`` are skipped (cannot be matched/commented).
    Backend errors propagate — the dialog driver swallows them best-effort.
    """
    name = getattr(backend, "name", "") or ""
    registry: list[SentTask] = []
    for item in backend.list_existing(container_id):
        if not item.title or not item.ref:
            continue
        registry.append(SentTask(
            title=item.title,
            backend=name,
            container_id=container_id,
            ref=item.ref,
            identifier=item.identifier,
            url=item.url,
            meeting_name="",
            meeting_date="",
            description=item.description,
        ))
    return registry
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dedup_board_registry.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add tasks/dedup.py tests/test_dedup_board_registry.py
git commit -m "feat(dedup): build_board_registry from live backend board"
```

---

### Task 3: `disambiguate_via_llm` uses descriptions

**Files:**
- Modify: `tasks/dedup.py:216-278` (the `disambiguate_via_llm` function)
- Test: `tests/test_dedup_llm_descriptions.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_dedup_llm_descriptions.py
import json

from tasks.dedup import SentTask, disambiguate_via_llm
from tasks.schema import Priority, Task, TaskStatus


class _FakeOR:
    def __init__(self):
        self.last_messages = None

    def complete(self, *, model, messages, json_mode):
        self.last_messages = messages
        return {"content": json.dumps({"match_id": None})}


def _task(title, desc=""):
    return Task(
        local_id="l1", title=title, description=desc, priority=Priority.MEDIUM,
        status=TaskStatus.PENDING,
    )


def test_llm_prompt_includes_descriptions():
    cand = SentTask(
        title="Изучить систему СУП", backend="linear", container_id="t",
        ref="r", identifier="NUR-37", url="", meeting_name="", meeting_date="",
        description="Погрузиться в систему СУП для интеграции",
    )
    orc = _FakeOR()
    disambiguate_via_llm(
        _task("Изучить СУП", "Разобрать интерфейс СУП"), [cand], orc, "model-x",
    )
    user_msg = orc.last_messages[1]["content"]
    assert "Разобрать интерфейс СУП" in user_msg          # new task desc
    assert "Погрузиться в систему СУП для интеграции" in user_msg  # candidate desc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dedup_llm_descriptions.py -v`
Expected: FAIL — descriptions not in the prompt (assertion error).

- [ ] **Step 3: Implement**

In `tasks/dedup.py`, replace the `cand_lines` / `user` construction inside `disambiguate_via_llm` with:

```python
    cand_lines = "\n".join(
        f'- id={c.ref} | "{c.title}"'
        + (f" | {c.description[:200]}" if c.description else "")
        for c in candidates
    )
    user = (
        f'НОВАЯ задача: "{new_task.title}"'
        + (f"\nОписание: {new_task.description[:200]}" if new_task.description else "")
        + f"\n\nРАНЕЕ созданные:\n{cand_lines}\n\n"
        "Верни только JSON-объект."
    )
```

(Leave the `system` prompt, the OpenRouter call, the 400-retry, and the JSON parsing exactly as they are.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dedup_llm_descriptions.py tests/test_tasks_dedup.py -v`
Expected: PASS (new test + existing dedup tests stay green).

- [ ] **Step 5: Commit**

```bash
git add tasks/dedup.py tests/test_dedup_llm_descriptions.py
git commit -m "feat(dedup): include descriptions in LLM disambiguation prompt"
```

---

### Task 4: `LinearClient.list_issues` (paginated, active-only)

**Files:**
- Modify: `tasks/linear_client.py`
- Test: `tests/test_linear_client_list_issues.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_linear_client_list_issues.py
from tasks.linear_client import LinearClient


def _client():
    return LinearClient(api_key="k")


def test_single_page(monkeypatch):
    c = _client()
    monkeypatch.setattr(c, "_graphql", lambda q, v=None: {
        "team": {"issues": {
            "nodes": [{"id": "i1", "identifier": "NUR-1", "title": "T1",
                       "url": "u1", "description": "d1"}],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        }}
    })
    issues = c.list_issues("team-1")
    assert [i["identifier"] for i in issues] == ["NUR-1"]


def test_multi_page_follows_cursor(monkeypatch):
    c = _client()
    pages = [
        {"team": {"issues": {
            "nodes": [{"id": "i1", "identifier": "NUR-1", "title": "T1", "url": "", "description": ""}],
            "pageInfo": {"hasNextPage": True, "endCursor": "CUR"}}}},
        {"team": {"issues": {
            "nodes": [{"id": "i2", "identifier": "NUR-2", "title": "T2", "url": "", "description": ""}],
            "pageInfo": {"hasNextPage": False, "endCursor": None}}}},
    ]
    seen_cursors = []

    def fake_graphql(q, v=None):
        seen_cursors.append((v or {}).get("after"))
        return pages.pop(0)

    monkeypatch.setattr(c, "_graphql", fake_graphql)
    issues = c.list_issues("team-1")
    assert [i["identifier"] for i in issues] == ["NUR-1", "NUR-2"]
    assert seen_cursors == [None, "CUR"]


def test_empty_team(monkeypatch):
    c = _client()
    monkeypatch.setattr(c, "_graphql", lambda q, v=None: {"team": {"issues": {
        "nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}})
    assert c.list_issues("team-1") == []


def test_query_excludes_completed_and_canceled():
    from tasks.linear_client import _TEAM_ISSUES_QUERY
    assert '"completed"' in _TEAM_ISSUES_QUERY
    assert '"canceled"' in _TEAM_ISSUES_QUERY
    assert "nin" in _TEAM_ISSUES_QUERY
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_linear_client_list_issues.py -v`
Expected: FAIL — `AttributeError: 'LinearClient' object has no attribute 'list_issues'` / import error on `_TEAM_ISSUES_QUERY`.

- [ ] **Step 3: Implement**

In `tasks/linear_client.py`, add at the top (after `import requests`):

```python
import logging

logger = logging.getLogger(__name__)
```

Add the query constant + cap near the other query constants:

```python
_MAX_ISSUES = 2000

_TEAM_ISSUES_QUERY = """
query TeamIssues($teamId: String!, $after: String) {
  team(id: $teamId) {
    issues(
      first: 250, after: $after,
      filter: { state: { type: { nin: ["completed", "canceled"] } } },
      orderBy: updatedAt
    ) {
      nodes { id identifier title url description }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""
```

Add the method (after `team_context`):

```python
    def list_issues(self, team_id: str) -> list[dict]:
        """All ACTIVE issues in a team (not completed/canceled), for dedup.

        Cursor-paginates 250/page until exhausted or the _MAX_ISSUES safety
        cap (logs a WARNING and returns the partial set if hit — that's the
        signal to adopt server-side search). Each issue: {id, identifier,
        title, url, description}. Raises LinearError on HTTP/network failure.
        """
        issues: list[dict] = []
        cursor: str | None = None
        while True:
            data = self._graphql(
                _TEAM_ISSUES_QUERY, {"teamId": team_id, "after": cursor},
            )
            conn = (data.get("team") or {}).get("issues") or {}
            issues.extend(conn.get("nodes") or [])
            page = conn.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                break
            if len(issues) >= _MAX_ISSUES:
                logger.warning(
                    "Linear team %s has >%d active issues; dedup registry "
                    "capped (consider server-side search retrieval)",
                    team_id, _MAX_ISSUES,
                )
                break
            cursor = page.get("endCursor")
        logger.info("linear list_issues team=%s fetched=%d", team_id, len(issues))
        return issues
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_linear_client_list_issues.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add tasks/linear_client.py tests/test_linear_client_list_issues.py
git commit -m "feat(linear): list_issues (paginated, active-only) for dedup"
```

---

### Task 5: `LinearClient.list_comments`

**Files:**
- Modify: `tasks/linear_client.py`
- Test: `tests/test_linear_client_list_comments.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_linear_client_list_comments.py
from tasks.linear_client import LinearClient


def test_list_comments_returns_bodies(monkeypatch):
    c = LinearClient(api_key="k")
    monkeypatch.setattr(c, "_graphql", lambda q, v=None: {
        "issue": {"comments": {"nodes": [{"body": "hello"}, {"body": "world"}]}}
    })
    assert c.list_comments("uuid-1") == ["hello", "world"]


def test_list_comments_empty(monkeypatch):
    c = LinearClient(api_key="k")
    monkeypatch.setattr(c, "_graphql", lambda q, v=None: {"issue": {"comments": {"nodes": []}}})
    assert c.list_comments("uuid-1") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_linear_client_list_comments.py -v`
Expected: FAIL — no attribute `list_comments`.

- [ ] **Step 3: Implement**

In `tasks/linear_client.py`, add a query constant:

```python
_ISSUE_COMMENTS_QUERY = """
query IssueComments($issueId: String!) {
  issue(id: $issueId) { comments { nodes { body } } }
}
"""
```

and the method (after `add_comment`):

```python
    def list_comments(self, issue_id: str) -> list[str]:
        """Comment bodies on an issue (dedup idempotency check).

        Raises LinearError on HTTP/network failure.
        """
        data = self._graphql(_ISSUE_COMMENTS_QUERY, {"issueId": issue_id})
        nodes = ((data.get("issue") or {}).get("comments") or {}).get("nodes") or []
        return [n.get("body") or "" for n in nodes]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_linear_client_list_comments.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add tasks/linear_client.py tests/test_linear_client_list_comments.py
git commit -m "feat(linear): list_comments for dedup idempotency"
```

---

### Task 6: `LinearBackend.list_existing` + `comment_exists`

**Files:**
- Modify: `tasks/backends/linear.py`
- Test: `tests/test_linear_backend_dedup.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_linear_backend_dedup.py
from tasks.backends.base import ExistingItem
from tasks.backends.linear import LinearBackend


class _FakeClient:
    def __init__(self):
        self.issues = [
            {"id": "u37", "identifier": "NUR-37", "title": "Изучить систему СУП",
             "url": "http://x/37", "description": "desc37"},
        ]
        self.comments = ["nope", "yes <!-- audiotx-dedup:abc123def456 -->"]

    def list_issues(self, team_id):
        return self.issues

    def list_comments(self, issue_id):
        return self.comments


def test_list_existing_maps_to_existing_item():
    b = LinearBackend(_FakeClient())
    items = b.list_existing("team-1")
    assert items == [ExistingItem(
        title="Изучить систему СУП", ref="u37", identifier="NUR-37",
        url="http://x/37", description="desc37",
    )]


def test_comment_exists_substring_match():
    b = LinearBackend(_FakeClient())
    assert b.comment_exists("u37", "<!-- audiotx-dedup:abc123def456 -->") is True
    assert b.comment_exists("u37", "<!-- audiotx-dedup:zzz -->") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_linear_backend_dedup.py -v`
Expected: FAIL — `LinearBackend` has no `list_existing`.

- [ ] **Step 3: Implement**

In `tasks/backends/linear.py`, update the import line to add `ExistingItem`:

```python
from tasks.backends.base import Container, CreatedIssue, ExistingItem
```

and add the two methods (after `add_comment`):

```python
    def list_existing(self, container_id: str) -> list[ExistingItem]:
        return [
            ExistingItem(
                title=i.get("title") or "",
                ref=i.get("id") or "",
                identifier=i.get("identifier") or "",
                url=i.get("url") or "",
                description=i.get("description") or "",
            )
            for i in self._client.list_issues(container_id)
        ]

    def comment_exists(self, ref: str, marker: str) -> bool:
        return any(marker in body for body in self._client.list_comments(ref))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_linear_backend_dedup.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add tasks/backends/linear.py tests/test_linear_backend_dedup.py
git commit -m "feat(linear): backend list_existing + comment_exists"
```

---

### Task 7: `TrelloClient.list_open_cards` (board-level)

**Files:**
- Modify: `tasks/trello_client.py`
- Test: `tests/test_trello_client_list_cards.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_trello_client_list_cards.py
import pytest

from tasks.trello_client import TrelloClient, TrelloError


def _client():
    return TrelloClient(api_key="k", token="t")


def test_resolves_list_to_board_then_lists_open_cards(monkeypatch):
    c = _client()
    calls = []

    def fake_request(method, path, *, params=None, timeout=30.0):
        calls.append((method, path, params))
        if path == "/lists/list-1":
            return {"idBoard": "board-9"}
        if path == "/boards/board-9/cards":
            return [{"id": "card-1", "name": "Изучить СУП", "desc": "d",
                     "url": "http://c/1", "idShort": 5, "shortLink": "abc"}]
        raise AssertionError(path)

    monkeypatch.setattr(c, "_request", fake_request)
    cards = c.list_open_cards("list-1")
    assert [x["id"] for x in cards] == ["card-1"]
    # board-level fetch, open filter
    board_call = [x for x in calls if x[1] == "/boards/board-9/cards"][0]
    assert board_call[2]["filter"] == "open"


def test_raises_when_board_unresolvable(monkeypatch):
    c = _client()
    monkeypatch.setattr(c, "_request", lambda m, p, *, params=None, timeout=30.0: {})
    with pytest.raises(TrelloError):
        c.list_open_cards("list-1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_trello_client_list_cards.py -v`
Expected: FAIL — no attribute `list_open_cards`.

- [ ] **Step 3: Implement**

In `tasks/trello_client.py`, add the method (after `board_context`):

```python
    def list_open_cards(self, list_id: str) -> list[dict]:
        """Open cards on the BOARD that owns ``list_id`` (board-level so a
        duplicate moved to another list is still caught), for dedup.

        Resolves list→board (same as board_context), then GET
        /boards/{id}/cards?filter=open. Returns card dicts (id, name, desc,
        url, idShort, shortLink). Raises TrelloError on failure. A full
        board returns up to 1000 open cards; if exactly 1000 come back the
        board may be truncated — logged as a WARNING (path-to-scale: switch
        to server-side /search).
        """
        if not list_id:
            raise TrelloError("list_id обязателен для list_open_cards")
        lst = self._request("GET", f"/lists/{list_id}", params={"fields": "idBoard"})
        board_id = lst.get("idBoard") if isinstance(lst, dict) else None
        if not board_id:
            raise TrelloError(
                f"Trello: не удалось определить доску для списка {list_id}",
            )
        cards = self._request(
            "GET", f"/boards/{board_id}/cards",
            params={"filter": "open", "fields": "name,desc,url,idShort,shortLink"},
        )
        if not isinstance(cards, list):
            raise TrelloError(
                f"Trello /boards/{board_id}/cards вернул неожиданный формат: "
                f"{type(cards).__name__}",
            )
        if len(cards) >= 1000:
            logger.warning(
                "Trello board %s returned %d open cards; dedup may be "
                "truncated (consider server-side search)", board_id, len(cards),
            )
        return cards
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_trello_client_list_cards.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add tasks/trello_client.py tests/test_trello_client_list_cards.py
git commit -m "feat(trello): list_open_cards (board-level) for dedup"
```

---

### Task 8: `TrelloClient.list_card_comments`

**Files:**
- Modify: `tasks/trello_client.py`
- Test: `tests/test_trello_client_card_comments.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_trello_client_card_comments.py
from tasks.trello_client import TrelloClient


def test_list_card_comments_extracts_text(monkeypatch):
    c = TrelloClient(api_key="k", token="t")

    def fake_request(method, path, *, params=None, timeout=30.0):
        assert path == "/cards/card-1/actions"
        assert params["filter"] == "commentCard"
        return [
            {"data": {"text": "first"}},
            {"data": {"text": "second"}},
        ]

    monkeypatch.setattr(c, "_request", fake_request)
    assert c.list_card_comments("card-1") == ["first", "second"]


def test_list_card_comments_handles_nonlist(monkeypatch):
    c = TrelloClient(api_key="k", token="t")
    monkeypatch.setattr(c, "_request", lambda m, p, *, params=None, timeout=30.0: {})
    assert c.list_card_comments("card-1") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_trello_client_card_comments.py -v`
Expected: FAIL — no attribute `list_card_comments`.

- [ ] **Step 3: Implement**

In `tasks/trello_client.py`, add (after `add_comment`):

```python
    def list_card_comments(self, card_id: str) -> list[str]:
        """Comment texts on a card (dedup idempotency check).

        GET /cards/{id}/actions?filter=commentCard → each action's
        data.text. Raises TrelloError on HTTP/network failure.
        """
        if not card_id:
            raise TrelloError("card_id обязателен для list_card_comments")
        actions = self._request(
            "GET", f"/cards/{card_id}/actions", params={"filter": "commentCard"},
        )
        if not isinstance(actions, list):
            return []
        return [(a.get("data") or {}).get("text") or "" for a in actions]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_trello_client_card_comments.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add tasks/trello_client.py tests/test_trello_client_card_comments.py
git commit -m "feat(trello): list_card_comments for dedup idempotency"
```

---

### Task 9: `TrelloBackend.list_existing` + `comment_exists`

**Files:**
- Modify: `tasks/backends/trello.py`
- Test: `tests/test_trello_backend_dedup.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_trello_backend_dedup.py
from tasks.backends.base import ExistingItem
from tasks.backends.trello import TrelloBackend


class _FakeClient:
    def list_open_cards(self, list_id):
        return [
            {"id": "card-1", "name": "Изучить СУП", "desc": "d1",
             "url": "http://c/1", "idShort": 5, "shortLink": "abc"},
            {"id": "card-2", "name": "Без idShort", "desc": "",
             "url": "", "idShort": None, "shortLink": "shortX"},
        ]

    def list_card_comments(self, card_id):
        return ["x <!-- audiotx-dedup:sig1 -->"]


def test_list_existing_maps_cards():
    b = TrelloBackend(_FakeClient())
    items = b.list_existing("list-1")
    assert items[0] == ExistingItem(
        title="Изучить СУП", ref="card-1", identifier="#5",
        url="http://c/1", description="d1",
    )
    # idShort missing → fall back to shortLink
    assert items[1].identifier == "shortX"


def test_comment_exists():
    b = TrelloBackend(_FakeClient())
    assert b.comment_exists("card-1", "<!-- audiotx-dedup:sig1 -->") is True
    assert b.comment_exists("card-1", "<!-- audiotx-dedup:other -->") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_trello_backend_dedup.py -v`
Expected: FAIL — `TrelloBackend` has no `list_existing`.

- [ ] **Step 3: Implement**

In `tasks/backends/trello.py`, update the import:

```python
from tasks.backends.base import Container, CreatedIssue, ExistingItem
```

and add the two methods (after `add_comment`):

```python
    def list_existing(self, container_id: str) -> list[ExistingItem]:
        out: list[ExistingItem] = []
        for c in self._client.list_open_cards(container_id):
            id_short = c.get("idShort")
            if id_short is not None:
                identifier = f"#{id_short}"
            else:
                identifier = c.get("shortLink") or "?"
            out.append(ExistingItem(
                title=c.get("name") or "",
                ref=c.get("id") or "",
                identifier=identifier,
                url=c.get("url") or "",
                description=c.get("desc") or "",
            ))
        return out

    def comment_exists(self, ref: str, marker: str) -> bool:
        return any(marker in t for t in self._client.list_card_comments(ref))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_trello_backend_dedup.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add tasks/backends/trello.py tests/test_trello_backend_dedup.py
git commit -m "feat(trello): backend list_existing + comment_exists"
```

---

### Task 10: Wire `_run_dedup` to the live-board registry

**Files:**
- Modify: `ui/dialogs/extract_tasks/__init__.py:1024-1044` (the imports + registry build inside `_run_dedup`)
- Test: `tests/test_dialog_dedup_board_source.py` (create — source-text checks, NOT an import of the dialog)

- [ ] **Step 1: Write failing test**

```python
# tests/test_dialog_dedup_board_source.py
import pathlib

_SRC = pathlib.Path("ui/dialogs/extract_tasks/__init__.py").read_text(encoding="utf-8")


def test_run_dedup_uses_board_registry_not_local_history():
    # Slice the _run_dedup method so we only assert on its body.
    start = _SRC.index("def _run_dedup(")
    end = _SRC.index("def _on_extract_success(")
    body = _SRC[start:end]
    assert "build_board_registry(backend, container_id)" in body
    assert "build_sent_registry(" not in body          # old source retired
    assert "list_history_entries" not in body          # no history scan
    # backend errors widen the swallow
    assert "LinearError" in body and "TrelloError" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dialog_dedup_board_source.py -v`
Expected: FAIL — body still references `build_sent_registry` / `list_history_entries`.

- [ ] **Step 3: Implement**

In `ui/dialogs/extract_tasks/__init__.py`, inside `_run_dedup`, replace the import block + registry build (current lines ~1024-1044) with:

```python
        from tasks.dedup import (
            build_board_registry,
            resolve_thresholds,
            select_match,
        )
        from tasks.linear_client import LinearError
        from tasks.openrouter_client import OpenRouterError
        from tasks.trello_client import TrelloError

        high, low = resolve_thresholds(self._config)
        try:
            registry = build_board_registry(backend, container_id)
        except (OSError, LinearError, TrelloError, ValueError, KeyError) as e:
            # Best-effort: a board-listing failure must never block showing
            # the freshly-extracted tasks (badges simply won't appear).
            _logging.getLogger(__name__).warning("dedup board registry failed: %s", e)
            return
        _logging.getLogger(__name__).info(
            "dedup registry: backend=%s container=%s size=%d",
            backend_name, container_id, len(registry),
        )
```

(Leave the `if not getattr(backend, "supports_comments", False): return` and
`if not bool(self._config.get("dedup_enabled", True)): return` gates and the
per-task `select_match` loop below exactly as they are. The
`from tasks.persistence import PersistenceError, load_tasks` and
`from utils import list_history_entries` imports are removed.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dialog_dedup_board_source.py tests/test_dialog_dedup_ui.py -v`
Expected: PASS (new source check + existing dedup-UI source checks).

- [ ] **Step 5: Commit**

```bash
git add ui/dialogs/extract_tasks/__init__.py tests/test_dialog_dedup_board_source.py
git commit -m "feat(dedup): _run_dedup builds registry from live board"
```

---

### Task 11: Idempotent commenting in `tasks/sender.py`

**Files:**
- Modify: `tasks/sender.py:84-94` (use_comment branch) and `_dup_comment_body` (line 175)
- Test: `tests/test_sender_dedup_idempotent.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_sender_dedup_idempotent.py
from tasks.dedup import SentTask, dedup_marker
from tasks.schema import Priority, Task, TaskStatus
from tasks.sender import _dup_comment_body, send_tasks_iter


class _Backend:
    supports_comments = True

    def __init__(self, existing_marker=None):
        self._existing = existing_marker
        self.commented = []

    def comment_exists(self, ref, marker):
        return self._existing == marker

    def add_comment(self, ref, body):
        self.commented.append((ref, body))

    def create(self, container_id, task):
        raise AssertionError("must not create when commenting")

    def close(self):
        pass


def _dup_task(title="Изучить систему СУП"):
    t = Task(local_id="l1", title=title, description="", priority=Priority.MEDIUM,
             status=TaskStatus.PENDING, selected=True)
    t.dup_match = SentTask(title=title, backend="linear", container_id="c",
                           ref="ref-1", identifier="NUR-37", url="u",
                           meeting_name="", meeting_date="")
    t.dup_action = "comment"
    return t


def test_comment_body_carries_marker():
    body = _dup_comment_body(_dup_task(), "Встреча", dedup_marker("Изучить систему СУП"))
    assert dedup_marker("Изучить систему СУП") in body


def test_posts_when_no_existing_marker():
    b = _Backend(existing_marker=None)
    t = _dup_task()
    list(send_tasks_iter([t], container_id="c", backend=b,
                         on_status_change=lambda *a: None, cancel_check=lambda: False))
    assert len(b.commented) == 1
    assert t.status is TaskStatus.COMMENTED


def test_skips_post_when_marker_already_present():
    marker = dedup_marker("Изучить систему СУП")
    b = _Backend(existing_marker=marker)
    t = _dup_task()
    list(send_tasks_iter([t], container_id="c", backend=b,
                         on_status_change=lambda *a: None, cancel_check=lambda: False))
    assert b.commented == []                 # idempotent: no second comment
    assert t.status is TaskStatus.COMMENTED   # still resolves as commented
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sender_dedup_idempotent.py -v`
Expected: FAIL — `_dup_comment_body` takes 2 args (no `marker`); no idempotency skip.

- [ ] **Step 3: Implement**

In `tasks/sender.py`, add to the imports (near the other `tasks.*` imports):

```python
from tasks.dedup import dedup_marker
```

Replace the `use_comment` branch inside the `try` (currently lines ~91-94):

```python
        try:
            if use_comment:
                _marker = dedup_marker(task.title)
                if backend.comment_exists(task.dup_match.ref, _marker):
                    logger.info(
                        "dedup idempotent: marker already on %s, skipping comment",
                        task.dup_match.ref,
                    )
                else:
                    backend.add_comment(
                        task.dup_match.ref,
                        _dup_comment_body(task, meeting_label, _marker),
                    )
            else:
                issue = backend.create(container_id, task)
```

Update `_dup_comment_body` to accept and append the marker:

```python
def _dup_comment_body(task: Task, meeting_label: str, marker: str = "") -> str:
    """RU comment posted to the existing card when a task recurs (dedup)."""
    where = f' "{meeting_label}"' if meeting_label else ""
    body = (
        f"🔁 Эта задача снова обсуждалась на встрече{where} "
        f"({date.today().isoformat()})."
    )
    if task.description:
        body += f"\n\n{task.description}"
    if marker:
        body += f"\n\n{marker}"
    return body
```

(The `comment_exists` call can raise LinearError/TrelloError — it is inside
the existing `except (LinearError, GlideError, TrelloError)` block, so a
listing failure marks the task FAILED, consistent with other backend errors.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_sender_dedup_idempotent.py tests/test_tasks_send.py -v`
Expected: PASS (new tests + existing sender tests stay green).

- [ ] **Step 5: Commit**

```bash
git add tasks/sender.py tests/test_sender_dedup_idempotent.py
git commit -m "feat(dedup): idempotent commenting (signature marker + pre-post check)"
```

---

### Task 12: Full gate — pytest + ruff

**Files:** none (verification)

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS, count = 586 (baseline) + ~22 new tests from Tasks 1–11.

- [ ] **Step 2: Run ruff**

Run: `python -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 3: Fix any failures**

If a pre-existing test imports `build_sent_registry` expecting it wired into
the dialog, it still passes (the function is retained). If ruff flags an
unused import in `extract_tasks/__init__.py` (the removed `load_tasks` /
`list_history_entries` / `PersistenceError`), delete those import lines.
Re-run both until green.

- [ ] **Step 4: Commit any fixups**

```bash
git add -p
git commit -m "chore(dedup): lint + test fixups for live-board registry"
```

---

### Task 13: Real-API acceptance smoke (the gate — manual)

**Files:** none (manual verification on the deployed build, with real keys)

This is the production acceptance gate. Mocked tests gave a false-green on
Trello before (#79), so the feature is NOT "done" until this passes.

- [ ] **Step 1: Rebuild + deploy**

Run (from repo root, `.venv-build` on PATH):
```
.\scripts\build_exe.ps1
```
Then deploy `dist\AudioTranscriber` over `C:\Apps\AudioTranscriber`,
preserving `_internal\config.json` (merge as in the prior session).

- [ ] **Step 2: Linear dedup smoke**

Launch the app → open a meeting that overlaps NUR-37 ("3rd part kitng in
the corridor") → Извлечь задачи → backend Linear, team NUR → extract.
Expected: the row for "Изучить систему СУП…" shows
`🔁 возможный дубль → NUR-37` with the comment/create toggle on
«Закомментировать». Send. Open NUR-37 → a dedup comment is present.
**No new NUR-4x issue is created for that task.**

- [ ] **Step 3: Idempotency smoke**

Re-extract the same meeting and send again with «Закомментировать».
Expected: NUR-37 gets **NO second** dedup comment (idempotent). Logs show
"dedup idempotent: marker already on …" (check `_internal\logs\app.log`).

- [ ] **Step 4: Trello dedup smoke**

Switch backend to Trello, pick a list whose board has a known duplicate
card → extract → confirm `🔁 возможный дубль → #N` → send → the existing
card got the comment (board-level: even if the card sits in a different
list than the target). Re-run → no double comment.

- [ ] **Step 5: Record outcome + ship**

Note results in the session. If all green: repackage
`dist\AudioTranscriber-v0.1.0.zip` (Python `zipfile`, forward slashes — see
[[feedback_ps51_zip_backslash_use_python_zipfile]]) and resume client
delivery. If any fail: return to systematic-debugging with the app.log
evidence.

---

## Self-Review

**Spec coverage:**
- Live-board registry source → Tasks 2, 10. ✓
- `list_existing` Linear + Trello → Tasks 4/6, 7/9. ✓
- Active-only filter → Task 4 (Linear `nin` completed/canceled), Task 7 (Trello `filter=open`). ✓
- Pagination + safety cap → Task 4 (Linear cursor + `_MAX_ISSUES`), Task 7 (Trello 1000-warn). ✓
- Idempotent commenting (marker + pre-post check) → Tasks 1 (helpers), 5/6 + 8/9 (comment listing), 11 (guard). ✓
- LLM uses descriptions → Tasks 1 (`SentTask.description`), 3. ✓
- Observability logging → Task 4 (fetched count), Task 10 (registry size), Task 11 (idempotent skip). ✓
- Best-effort error swallow preserved → Task 10 (`except` widened). ✓
- Real-API acceptance gate → Task 13. ✓
- Board-level Trello scope → Task 7. ✓

**Placeholder scan:** none — every step has concrete code/commands.

**Type consistency:** `ExistingItem(title, ref, identifier, url, description="")` used identically in Tasks 1/2/6/9. `build_board_registry(backend, container_id)` matches the Task 10 call site. `comment_exists(ref, marker)` / `list_existing(container_id)` signatures consistent across base/linear/trello. `_dup_comment_body(task, meeting_label, marker="")` matches the Task 11 call. `dedup_marker(title)` used in Tasks 1/11. ✓

**Out of scope (per spec):** server-side search (A2) — triggered by the cap WARNINGs; Glide (no comments, gated out); cross-backend dedup.
