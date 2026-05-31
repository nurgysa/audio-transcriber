# Task-Dedup PR-2 — Dedup Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline, recommended for this single cohesive module) or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add `tasks/dedup.py` — pure logic that decides whether a freshly-extracted task duplicates one already **SENT** in a past meeting, so PR-3's UI can offer "comment on the existing card" instead of creating a duplicate. **No UI wiring, no behaviour change in the running app** — this module is defined-but-not-yet-called (mirrors PR-1's posture).

**Architecture:** Loaders and the LLM client are **injected** (mirrors `tasks/extractor.py`) so the module is unit-testable with zero filesystem/network. Pipeline: `build_sent_registry()` scans meeting history (`utils.list_history_entries` + `tasks.persistence.load_tasks`) into a list of `SentTask`; `find_candidates()` fuzzy-scores a new task against same-backend+same-container registry entries via `difflib.SequenceMatcher` on normalized titles; the borderline band (`FUZZY_LOW ≤ score < FUZZY_HIGH`) is resolved by `disambiguate_via_llm()`, which reuses the OpenRouter `complete()`/json-mode-400-retry/`_strip_codefence` pattern.

**Tech Stack:** Python 3.10+, stdlib only in the body (`difflib`, `re`, `json`, `dataclasses`); `pytest` + `unittest.mock.MagicMock` for tests; `ruff`. No new deps.

**Design source:** `~/.claude/plans/foamy-wobbling-owl.md` (PR-2 section); decisions also in memory `project-task-dedup`. Verified against real code 2026-05-31: `meta["backend"]` (default `"linear"`) + `meta["team_id"]` are really written by the Extract dialog (`ui/dialogs/extract_tasks/__init__.py:894-895`); `list_history_entries()` returns `folder_path`/`folder_name`/`date_created` (`utils.py:362`); `load_tasks(folder)` returns `{**meta, "tasks": [Task]}` (`tasks/persistence.py:123`); `complete(model, messages, json_mode=...)` + module-level `_strip_codefence` exist (`tasks/extractor.py`).

**Branch:** `feat/task-dedup-engine` (off updated `origin/main` = `9d32235`, which carries PR-1's foundation via the #88 squash). Per [[feedback-stacked-pr-squash-merge]] this is branched from main AFTER #88 merged — NOT stacked on the old `feat/task-dedup-foundation`. Working tree is clean; the user's separate `cli/` WIP is untracked/empty — do NOT stage it.

**Design decisions locked here (decisive defaults; PR-3 can override via config):**
- **Title normalization** = lowercase → replace punctuation with space → collapse whitespace. `\w` is **Unicode-aware** (`re.UNICODE`) so Cyrillic / Kazakh letters survive; only punctuation/separators are stripped. Rationale: meeting-task titles are RU/KZ; ASCII-only normalization would mangle them.
- **Thresholds** `FUZZY_HIGH = 0.82`, `FUZZY_LOW = 0.55`. `SequenceMatcher.ratio()` on short normalized titles: ≥0.82 = same task with at most a word reorder; <0.55 = unrelated. The 0.55–0.82 band is genuinely ambiguous → spend one cheap LLM call. PR-3 wires `dedup_fuzzy_high`/`dedup_fuzzy_low` config keys to these module constants.
- **LLM fail-safe direction** = a malformed/unparseable disambiguation reply returns `None` (= "no match" = create a new task), NOT a guessed match. Rationale: a duplicate task is trivially recoverable (user merges), but commenting on the **wrong** card is a confusing, hard-to-undo false positive. Fail toward create-new.

**Tech reuse (do NOT reinvent):**
- `from tasks.extractor import _strip_codefence` — intentional reuse of the shared codefence stripper (the master plan endorses it; keeps the json-parse identical to extraction).
- `from tasks.openrouter_client import OpenRouterError` — retry-on-`"вернул 400:"` mirrors `extractor.extract()`.
- `from tasks.persistence import PersistenceError` — narrow `except` for meetings with no/broken `tasks.json` (CLAUDE.md: narrow excepts).
- `from tasks.schema import Task, TaskStatus` — `TaskStatus.SENT` filter; `Task.backend_ref`/`linear_issue_id`/`linear_issue_url` read for the registry.

---

## File Structure

| File | Change |
|------|--------|
| `docs/superpowers/plans/2026-05-31-task-dedup-pr2-engine.md` | **(this file)** committed first |
| `tasks/dedup.py` | **Create** — `SentTask`, `normalize_title`, `FUZZY_HIGH/LOW`, `build_sent_registry`, `find_candidates`, `disambiguate_via_llm` |
| `tests/test_tasks_dedup.py` | **Create** — registry build (injected loader), normalization, scope filter, threshold boundaries, LLM disambig (stub client) |

**Baseline:** run `python -m pytest` once at the start to record the green baseline (origin/main = 546 tests per PR-1's final count); `python -m ruff check .` clean. Both must pass before every commit.

**Naming note:** the master plan said `tests/test_dedup.py`, but the established convention is `tests/test_tasks_<module>.py` (10 existing files). This plan uses `tests/test_tasks_dedup.py` for consistency.

---

## Task 0: Commit this plan

**Files:** Create `docs/superpowers/plans/2026-05-31-task-dedup-pr2-engine.md` (this document).

- [ ] **Step 1: Record baseline**

Run: `python -m pytest -q` → record the green count. Run: `python -m ruff check .` → clean.

- [ ] **Step 2: Commit the plan**

```bash
git add docs/superpowers/plans/2026-05-31-task-dedup-pr2-engine.md
git commit -m "docs(dedup): PR-2 engine bite-sized plan"  # + Co-Authored-By trailer
```
(Do NOT `git add -A` — the user's `cli/` WIP must stay untracked.)

---

## Task 1: `SentTask` + `normalize_title` + thresholds

**Files:** Create `tasks/dedup.py`; Create `tests/test_tasks_dedup.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tasks_dedup.py`:

```python
"""Tests for the task-dedup engine (PR-2). Pure logic — no FS/network."""
from __future__ import annotations

import pytest

from tasks.dedup import (
    FUZZY_HIGH,
    FUZZY_LOW,
    SentTask,
    normalize_title,
)


def test_thresholds_are_sane():
    assert 0.0 < FUZZY_LOW < FUZZY_HIGH < 1.0


def test_sent_task_is_frozen_value_object():
    s = SentTask(
        title="Починить логин",
        backend="linear",
        container_id="team-1",
        ref="node-uuid-1",
        identifier="ENG-1",
        url="http://x/ENG-1",
        meeting_name="2026-05-20_10-00-00_standup",
        meeting_date="2026-05-20_10-00-00",
    )
    assert s.title == "Починить логин"
    assert s.ref == "node-uuid-1"
    with pytest.raises(Exception):  # frozen dataclass -> FrozenInstanceError
        s.title = "x"  # type: ignore[misc]


def test_normalize_lowercases_and_collapses_punct_and_space():
    assert normalize_title("  Починить   ЛОГИН!! ") == "починить логин"
    assert normalize_title("Fix: the   bug.") == "fix the bug"


def test_normalize_preserves_cyrillic_and_kazakh_letters():
    # Unicode-aware \w must keep RU/KZ letters; only punctuation goes.
    assert normalize_title("Әзірлеу: есеп —  v2") == "әзірлеу есеп v2"


def test_normalize_empty_and_none_safe():
    assert normalize_title("") == ""
    assert normalize_title("!!!") == ""
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_tasks_dedup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tasks.dedup'`.

- [ ] **Step 3: Create the module scaffold**

Create `tasks/dedup.py`:

```python
"""Task-dedup engine — decide if a new task duplicates a past SENT one.

Pure logic with no I/O in the body: the history loader and the LLM client
are injected (mirrors ``tasks/extractor.py``) so the whole module is
unit-testable without the filesystem or the network. PR-2 defines this;
PR-3 wires it into the Extract dialog. Nothing here is called by the
running app yet.

Pipeline (PR-3 caller shape):
    reg = build_sent_registry(list_history_entries(), load_tasks,
                              exclude_folder=current_folder)
    cands = find_candidates(new_task, reg, backend=b, container_id=c)
    if cands and cands[0][1] >= FUZZY_HIGH:
        match = cands[0][0]                      # confident, no LLM
    elif cands:                                  # borderline band
        match = disambiguate_via_llm(
            new_task, [c for c, _ in cands], openrouter_client, model)
    else:
        match = None                             # nothing close enough

Public API:
    SentTask                 — value type for a previously-sent task
    normalize_title(str)     — shared title normalization (exposed for tests)
    FUZZY_HIGH / FUZZY_LOW   — score thresholds (config-overridable in PR-3)
    build_sent_registry(...) — scan meeting history -> list[SentTask]
    find_candidates(...)     — fuzzy match within backend+container scope
    disambiguate_via_llm(...)— LLM resolves the borderline band
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable

# Reuse the extractor's codefence stripper so dedup parses LLM JSON exactly
# like extraction does (intentional cross-module reuse of a shared helper).
from tasks.extractor import _strip_codefence
from tasks.openrouter_client import OpenRouterError
from tasks.persistence import PersistenceError
from tasks.schema import Task, TaskStatus

logger = logging.getLogger(__name__)

# Fuzzy-match score band (difflib.SequenceMatcher.ratio() on normalized
# titles). >=HIGH: confident duplicate, no LLM. LOW..HIGH: borderline ->
# ask the LLM. <LOW: not a match. PR-3 overrides these from config keys
# dedup_fuzzy_high / dedup_fuzzy_low.
FUZZY_HIGH = 0.82
FUZZY_LOW = 0.55

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+", re.UNICODE)


@dataclass(frozen=True)
class SentTask:
    """A task already created in a tracker on a past meeting.

    ``ref`` is the comment-addressable backend id (Linear node UUID /
    Trello full card id) copied from ``Task.backend_ref``; ``identifier``
    + ``url`` are the human badge/link for the UI. ``backend`` +
    ``container_id`` scope the match — a comment must land on the same
    team/board the new task would be created in.
    """
    title: str
    backend: str
    container_id: str
    ref: str
    identifier: str
    url: str
    meeting_name: str
    meeting_date: str


def normalize_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace for fuzzy compare.

    ``\\w`` is Unicode-aware (``re.UNICODE``) so Cyrillic / Kazakh letters
    survive — only punctuation and separators are removed. Empty/None-ish
    input returns "".
    """
    if not title:
        return ""
    lowered = title.lower()
    no_punct = _PUNCT_RE.sub(" ", lowered)
    return _WS_RE.sub(" ", no_punct).strip()
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_tasks_dedup.py -v` → Expected: PASS (5 tests).
Run: `python -m ruff check tasks/dedup.py tests/test_tasks_dedup.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add tasks/dedup.py tests/test_tasks_dedup.py
git commit -m "feat(dedup): SentTask value type + Unicode-aware normalize_title"  # + trailer
```

---

## Task 2: `build_sent_registry`

**Files:** Modify `tasks/dedup.py`; Modify `tests/test_tasks_dedup.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tasks_dedup.py` (add `from tasks.dedup import build_sent_registry` to the imports, and `from tasks.schema import Task, TaskStatus`, `from tasks.persistence import PersistenceError`):

```python
from tasks.dedup import build_sent_registry  # noqa: E402  (grouped for readability)
from tasks.persistence import PersistenceError  # noqa: E402
from tasks.schema import Task, TaskStatus  # noqa: E402


def _sent(title, ref, **kw):
    """A Task in SENT state with a backend_ref (eligible for the registry)."""
    return Task(
        title=title,
        status=TaskStatus.SENT,
        backend_ref=ref,
        linear_issue_id=kw.get("identifier", "ENG-1"),
        linear_issue_url=kw.get("url", "http://x/ENG-1"),
    )


def _entries(*folders):
    # Non-trivial, varied folder names + dates (no all-zero fixtures).
    return [
        {"folder_path": f, "folder_name": f.split("/")[-1],
         "date_created": f.split("/")[-1][:19]}
        for f in folders
    ]


def _loader(mapping):
    def load(folder):
        if folder not in mapping:
            raise PersistenceError(f"no tasks.json in {folder}")
        return mapping[folder]
    return load


def test_registry_keeps_only_sent_with_backend_ref():
    mapping = {
        "/h/2026-05-20_10-00-00_standup": {
            "backend": "linear", "team_id": "team-A",
            "tasks": [
                _sent("Починить логин", "uuid-1"),
                Task(title="draft idea", status=TaskStatus.PENDING),  # excluded: not SENT
                Task(title="old sent no ref", status=TaskStatus.SENT, backend_ref=None),  # excluded
            ],
        },
    }
    reg = build_sent_registry(
        _entries("/h/2026-05-20_10-00-00_standup"), _loader(mapping),
    )
    assert len(reg) == 1
    s = reg[0]
    assert (s.title, s.ref, s.backend, s.container_id) == (
        "Починить логин", "uuid-1", "linear", "team-A")
    assert s.meeting_name == "2026-05-20_10-00-00_standup"
    assert s.identifier == "ENG-1"


def test_registry_excludes_current_meeting_folder():
    mapping = {
        "/h/A": {"backend": "linear", "team_id": "t", "tasks": [_sent("a", "r1")]},
        "/h/B": {"backend": "linear", "team_id": "t", "tasks": [_sent("b", "r2")]},
    }
    reg = build_sent_registry(
        _entries("/h/A", "/h/B"), _loader(mapping), exclude_folder="/h/B",
    )
    assert [s.ref for s in reg] == ["r1"]


def test_registry_defaults_backend_to_linear_and_skips_missing_tasks_json():
    mapping = {
        "/h/has": {"team_id": "t-9", "tasks": [_sent("x", "r9")]},  # no "backend" key
        # "/h/none" intentionally absent -> loader raises PersistenceError
    }
    reg = build_sent_registry(
        _entries("/h/has", "/h/none"), _loader(mapping),
    )
    assert len(reg) == 1
    assert reg[0].backend == "linear"  # defaulted
    assert reg[0].container_id == "t-9"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_tasks_dedup.py -k registry -v`
Expected: FAIL — `ImportError: cannot import name 'build_sent_registry'`.

- [ ] **Step 3: Implement**

Append to `tasks/dedup.py`:

```python
def build_sent_registry(
    entries: list[dict],
    load_tasks: Callable[[str], dict],
    *,
    exclude_folder: str | None = None,
) -> list[SentTask]:
    """Build the registry of previously-sent tasks from meeting history.

    ``entries`` come from ``utils.list_history_entries()`` (folder_path /
    folder_name / date_created). ``load_tasks`` is
    ``tasks.persistence.load_tasks`` injected so tests pass a fixture
    loader. A meeting contributes one ``SentTask`` per task with
    ``status == SENT`` and a non-empty ``backend_ref`` — older sent tasks
    predate ``backend_ref`` and have no comment-addressable id, so they
    cannot be commented on and are skipped. ``exclude_folder`` (the current
    meeting's ``folder_path``) never dedups against itself. Meetings with
    no/broken ``tasks.json`` (PersistenceError) are silently skipped — most
    meetings have no extracted tasks at all.
    """
    registry: list[SentTask] = []
    for entry in entries:
        folder = entry.get("folder_path")
        if not folder or folder == exclude_folder:
            continue
        try:
            loaded = load_tasks(folder)
        except PersistenceError:
            continue
        backend = loaded.get("backend") or "linear"
        container_id = loaded.get("team_id") or ""
        meeting_name = entry.get("folder_name") or ""
        meeting_date = entry.get("date_created") or ""
        for task in loaded.get("tasks", []):
            if task.status != TaskStatus.SENT or not task.backend_ref:
                continue
            registry.append(SentTask(
                title=task.title,
                backend=backend,
                container_id=container_id,
                ref=task.backend_ref,
                identifier=task.linear_issue_id or "",
                url=task.linear_issue_url or "",
                meeting_name=meeting_name,
                meeting_date=meeting_date,
            ))
    return registry
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_tasks_dedup.py -v` → Expected: PASS (all).
Run: `python -m ruff check tasks/dedup.py tests/test_tasks_dedup.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add tasks/dedup.py tests/test_tasks_dedup.py
git commit -m "feat(dedup): build_sent_registry from meeting history"  # + trailer
```

---

## Task 3: `find_candidates`

**Files:** Modify `tasks/dedup.py`; Modify `tests/test_tasks_dedup.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tasks_dedup.py` (add `from tasks.dedup import find_candidates`):

```python
from tasks.dedup import find_candidates  # noqa: E402


def _reg_entry(title, ref, backend="linear", container="team-A"):
    return SentTask(
        title=title, backend=backend, container_id=container, ref=ref,
        identifier="ENG-X", url="http://x", meeting_name="m", meeting_date="d",
    )


def test_find_candidates_scope_filters_backend_and_container():
    registry = [
        _reg_entry("Починить логин", "r-match"),                       # same scope
        _reg_entry("Починить логин", "r-other-backend", backend="trello"),
        _reg_entry("Починить логин", "r-other-team", container="team-B"),
    ]
    new = Task(title="починить логин")
    out = find_candidates(new, registry, backend="linear", container_id="team-A")
    assert [s.ref for s, _ in out] == ["r-match"]


def test_find_candidates_sorted_by_score_desc_and_thresholded():
    registry = [
        _reg_entry("Купить кофе для офиса", "r-low"),       # unrelated -> below LOW
        _reg_entry("Подготовить отчёт по продажам", "r-hi"),  # near-identical
        _reg_entry("Подготовить отчет о продажах", "r-mid"),  # close variant
    ]
    new = Task(title="Подготовить отчёт по продажам за май")
    out = find_candidates(new, registry, backend="linear", container_id="team-A")
    refs = [s.ref for s, _ in out]
    assert "r-low" not in refs                 # filtered: score < FUZZY_LOW
    assert refs[0] == "r-hi"                    # best match first
    scores = [score for _, score in out]
    assert scores == sorted(scores, reverse=True)
    assert all(sc >= FUZZY_LOW for sc in scores)


def test_find_candidates_empty_new_title_returns_nothing():
    registry = [_reg_entry("anything", "r")]
    assert find_candidates(Task(title="!!!"), registry,
                           backend="linear", container_id="team-A") == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_tasks_dedup.py -k find_candidates -v`
Expected: FAIL — `ImportError: cannot import name 'find_candidates'`.

- [ ] **Step 3: Implement**

Append to `tasks/dedup.py`:

```python
def find_candidates(
    new_task: Task,
    registry: list[SentTask],
    *,
    backend: str,
    container_id: str,
) -> list[tuple[SentTask, float]]:
    """Score ``new_task`` against same-scope registry entries, best first.

    Scope filter: only registry tasks with the SAME ``backend`` AND
    ``container_id`` are eligible — a dedup comment must land on the same
    team/board the new task would otherwise be created in. Score =
    ``difflib.SequenceMatcher.ratio()`` on normalized titles, in [0, 1].
    Returns ``(SentTask, score)`` pairs with ``score >= FUZZY_LOW``, sorted
    by score descending (Python's stable sort keeps registry order on
    ties). The caller distinguishes confident (``>= FUZZY_HIGH``) from
    borderline (``FUZZY_LOW..FUZZY_HIGH``) and only LLM-checks the latter.
    """
    new_norm = normalize_title(new_task.title)
    if not new_norm:
        return []
    scored: list[tuple[SentTask, float]] = []
    for sent in registry:
        if sent.backend != backend or sent.container_id != container_id:
            continue
        score = SequenceMatcher(None, new_norm, normalize_title(sent.title)).ratio()
        if score >= FUZZY_LOW:
            scored.append((sent, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_tasks_dedup.py -v` → Expected: PASS (all).
Run: `python -m ruff check tasks/dedup.py tests/test_tasks_dedup.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add tasks/dedup.py tests/test_tasks_dedup.py
git commit -m "feat(dedup): find_candidates with scope filter + fuzzy scoring"  # + trailer
```

---

## Task 4: `disambiguate_via_llm`

**Files:** Modify `tasks/dedup.py`; Modify `tests/test_tasks_dedup.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tasks_dedup.py` (add `from unittest.mock import MagicMock` and `from tasks.dedup import disambiguate_via_llm`):

```python
from unittest.mock import MagicMock  # noqa: E402

from tasks.dedup import disambiguate_via_llm  # noqa: E402


def _cands():
    return [
        _reg_entry("Подготовить отчёт по продажам", "r-1"),
        _reg_entry("Обновить документацию API", "r-2"),
    ]


def test_disambiguate_returns_matched_candidate_by_id():
    llm = MagicMock()
    llm.complete.return_value = {"content": '{"match_id": "r-1"}'}
    out = disambiguate_via_llm(
        Task(title="Сделать отчёт продаж"), _cands(), llm, "anthropic/x")
    assert out is not None and out.ref == "r-1"
    # json_mode requested on first attempt
    assert llm.complete.call_args.kwargs.get("json_mode") is True


def test_disambiguate_returns_none_on_explicit_no_match():
    llm = MagicMock()
    llm.complete.return_value = {"content": '{"match_id": null}'}
    assert disambiguate_via_llm(
        Task(title="Нечто иное"), _cands(), llm, "m") is None


def test_disambiguate_unknown_id_returns_none():
    llm = MagicMock()
    llm.complete.return_value = {"content": '{"match_id": "r-999"}'}  # not in cands
    assert disambiguate_via_llm(
        Task(title="x"), _cands(), llm, "m") is None


def test_disambiguate_malformed_json_fails_safe_to_none():
    llm = MagicMock()
    llm.complete.return_value = {"content": "sorry, no JSON here"}
    assert disambiguate_via_llm(
        Task(title="x"), _cands(), llm, "m") is None


def test_disambiguate_retries_without_json_mode_on_400():
    llm = MagicMock()
    llm.complete.side_effect = [
        OpenRouterError("OpenRouter вернул 400: response_format unsupported"),
        {"content": '{"match_id": "r-2"}'},
    ]
    out = disambiguate_via_llm(Task(title="docs"), _cands(), llm, "m")
    assert out is not None and out.ref == "r-2"
    assert llm.complete.call_count == 2
    assert llm.complete.call_args_list[1].kwargs.get("json_mode") is False


def test_disambiguate_propagates_non_400_errors():
    llm = MagicMock()
    llm.complete.side_effect = OpenRouterError("OpenRouter 429 rate-limit")
    with pytest.raises(OpenRouterError, match="429"):
        disambiguate_via_llm(Task(title="x"), _cands(), llm, "m")


def test_disambiguate_empty_candidates_short_circuits_without_llm():
    llm = MagicMock()
    assert disambiguate_via_llm(Task(title="x"), [], llm, "m") is None
    llm.complete.assert_not_called()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_tasks_dedup.py -k disambiguate -v`
Expected: FAIL — `ImportError: cannot import name 'disambiguate_via_llm'`.

- [ ] **Step 3: Implement**

Append to `tasks/dedup.py`:

```python
def disambiguate_via_llm(
    new_task: Task,
    candidates: list[SentTask],
    openrouter_client,
    model: str,
) -> SentTask | None:
    """Ask the LLM which candidate (if any) is the same task as ``new_task``.

    Called only for the borderline fuzzy band, where string similarity is
    ambiguous. Reuses the extractor's OpenRouter call shape: json_mode
    first, retry once without it on a 400, ``_strip_codefence`` + json
    parse. Returns the matched ``SentTask`` (by ``ref``), or ``None`` when
    the LLM says "no match", names an unknown id, or returns unparseable
    output. A malformed reply fails SAFE to ``None`` (-> create a new task)
    rather than risk commenting on the wrong card. Network/HTTP errors
    other than the 400-json_mode case propagate as ``OpenRouterError``.
    """
    if not candidates:
        return None
    by_ref = {c.ref: c for c in candidates}
    cand_lines = "\n".join(f'- id={c.ref} | "{c.title}"' for c in candidates)
    system = (
        "Ты дедупликатор задач. Дано НОВОЕ название задачи и список РАНЕЕ "
        "созданных задач с их id. Верни строго JSON "
        '{"match_id": "<id одной совпадающей задачи>"} или '
        '{"match_id": null}, если ни одна не совпадает по смыслу. Совпадение '
        "= та же по сути работа, даже если формулировки разные. Без markdown, "
        "без пояснений."
    )
    user = (
        f'НОВАЯ задача: "{new_task.title}"\n\n'
        f"РАНЕЕ созданные:\n{cand_lines}\n\n"
        "Верни только JSON-объект."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        response = openrouter_client.complete(
            model=model, messages=messages, json_mode=True,
        )
    except OpenRouterError as e:
        if "вернул 400:" in str(e):
            logger.info("dedup model %s rejected json_mode, retrying without", model)
            response = openrouter_client.complete(
                model=model, messages=messages, json_mode=False,
            )
        else:
            raise

    raw = response["content"]
    try:
        data = json.loads(_strip_codefence(raw))
    except (json.JSONDecodeError, TypeError):
        logger.warning("dedup LLM returned non-JSON, treating as no-match: %r", (raw or "")[:200])
        return None
    match_id = data.get("match_id") if isinstance(data, dict) else None
    if not match_id:
        return None
    return by_ref.get(match_id)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_tasks_dedup.py -v` → Expected: PASS (all).
Run: `python -m ruff check tasks/dedup.py tests/test_tasks_dedup.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add tasks/dedup.py tests/test_tasks_dedup.py
git commit -m "feat(dedup): disambiguate_via_llm for the borderline fuzzy band"  # + trailer
```

---

## Task 5: Full-suite gate + finish

**Files:** none (verification + handoff).

- [ ] **Step 1:** `python -m pytest` → all green (baseline + ~18 new dedup tests). Investigate any failure before proceeding.
- [ ] **Step 2:** `python -m ruff check .` → clean.
- [ ] **Step 3:** `git status` → confirm only the intended commits; the user's `cli/` WIP remains untracked/unstaged.
- [ ] **Step 4:** Finish via `superpowers:finishing-a-development-branch` → push `feat/task-dedup-engine`, open PR against `main`. PR body: Summary + Test plan; note this is **PR-2 of 3** (dedup engine — pure logic, NOT yet wired to UI; `tasks/dedup.py` is defined-but-not-called). PR-3 (Extract-dialog badge/toggle + sender `add_comment` branch + `COMMENTED` status + config keys) follows per `~/.claude/plans/foamy-wobbling-owl.md`. No GUI smoke needed (no UI in this PR).

---

## Self-Review

**Spec coverage (vs foamy-wobbling-owl PR-2):**
- `SentTask` dataclass (title, backend, container_id, ref, identifier, url, meeting_name, meeting_date) — ✓ Task 1.
- `build_sent_registry(entries, load_tasks, *, exclude_folder)` reusing `list_history_entries` shape + injected `load_tasks`, SENT + non-empty `backend_ref`, backend=`meta["backend"]`(fallback linear), container=`meta["team_id"]`, exclude current folder — ✓ Task 2.
- `find_candidates(new_task, registry, *, backend, container_id)` scope filter same backend+container, `SequenceMatcher.ratio()` on normalized title — ✓ Task 3.
- `FUZZY_HIGH`/`FUZZY_LOW` thresholds, ≥HIGH confident / LOW..HIGH borderline / <LOW no-match — ✓ Task 1 (constants) + Task 3 (LOW filter) + caller contract documented in module docstring (HIGH split is the PR-3 caller's job; documented).
- `disambiguate_via_llm(new_task, candidates, openrouter_client, model)` mini-prompt, reuse `complete()`+`_strip_codefence`+json-parse+retry-without-json_mode — ✓ Task 4.
- Tests: registry build (injected loader), normalization, threshold boundaries, scope filter, LLM disambig with stub — ✓; fixtures use non-zero/varied titles+dates per [[feedback-boundary-test-data-must-have-nonzero-start]] — ✓.

**Placeholder scan:** none — every step has code-complete content and exact commands.

**Type/name consistency:** `SentTask.ref` ← `Task.backend_ref` ← `CreatedIssue.ref` (PR-1 chain) consistent. `find_candidates` returns `list[tuple[SentTask, float]]`; the caller in the module docstring unpacks `cands[0][1]` (score) / `cands[0][0]` (SentTask) and passes `[c for c, _ in cands]` to `disambiguate_via_llm(candidates: list[SentTask])` — shapes line up. `normalize_title` used by both `find_candidates` and tests. `by_ref` keyed on `SentTask.ref`, matched against LLM `match_id`.

**Out of scope (do NOT touch in PR-2):** the Extract dialog / `task_row.py` badge+toggle, `tasks/sender.py` `add_comment` branch, `TaskStatus.COMMENTED`, `dedup_enabled`/`dedup_fuzzy_*` config keys, `backend_from_name` re-construction for commenting — all PR-3. `tasks/dedup.py` stays **uncalled** by the running app in this PR.
