# Phase 6.4.1 — Glide Backend (Wiring)

## Context

6.4.0 shipped `tasks/glide_client.py` + Settings UI but the `glide_*` flags
were preference-only — extract dialog still hardcoded to Linear. User
reported: "checked Glide, tasks went to Linear anyway." This phase closes
the gap: actual routing through a `TaskBackend` abstraction.

## Goal

After 6.4.1 the user can:

1. Open extract dialog → see a `Backend: [Linear / Glide]` dropdown
2. Pick Glide → container dropdown switches to Glide boards
3. Извлечь → задачи извлекаются (без assignee/labels grounding для Glide)
4. Send → задачи летят в Glide (POST /tasks), бейджи `✓ <uuid-prefix>`
5. Click on SENT row → opens task in Glide (URL constructed from board_id + task_id)
6. Settings checkbox controls visibility in dropdown

## Architecture

### `tasks/backends/` (new package)

```python
# base.py
@dataclass(frozen=True)
class Container:
    id: str
    name: str
    key: Optional[str] = None         # e.g. "NUR" for Linear, None for Glide

@dataclass(frozen=True)
class CreatedIssue:
    identifier: str                    # "NUR-24" or "467e14" (uuid prefix)
    url: str

class TaskBackend(Protocol):
    name: str                          # "linear" | "glide"
    display_name: str                  # "Linear" | "Glide"

    def bootstrap(self) -> list[Container]: ...
    def container_label(self, c: Container) -> str: ...
    def context(self, container_id: str) -> dict: ...
    # ↑ {members: [...], labels: [...]} for Linear; {} for Glide
    def create(self, container_id: str, task: Task) -> CreatedIssue: ...
    def close(self) -> None: ...
```

### `linear.py` — wraps existing `LinearClient`

- `bootstrap()` → `[Container(id, name, key) for t in linear.bootstrap()["teams"]]`
- `context(team_id)` → returns `linear.team_context(team_id)` as-is (matches extractor's existing dict shape)
- `create(team_id, task)` → translates `Task.priority` Linear-int + assignee/labels → calls `linear.create_issue` → wraps response into `CreatedIssue("ENG-1234", url)`

### `glide.py` — wraps `GlideClient`

- `bootstrap()` → `[Container(id, name, key=None) for b in glide.list_boards()]`
- `container_label(c)` → just `c.name` (no key suffix)
- `context(board_id)` → returns `{"members": [], "labels": []}` (no LLM grounding)
- `create(board_id, task)` → translates `Task.priority` enum → Glide string; ignores `assignee_id`/`label_ids` for now (manual editor in 6.4.2 polish); calls `glide.create_task(board_id=..., title=task.title, ...)` → wraps response: `CreatedIssue(uuid[:6], url=_glide_task_url(board_id, task_id))`
- Idempotency key: `f"task-{task.local_id}"` for first send; in retry (Phase 6.4.2 if needed) add suffix.
- URL construction: `f"https://os.tensor-ai.tech/boards/{board_id}/tasks/{task_id}"` (TBD — verify with real Glide; first smoke will reveal correct format)

### `tasks/sender.py` refactor

Rename `linear_client` parameter → `backend`. Rename `team_id` → `container_id`. Internally call `backend.create(container_id, task)` instead of building Linear-shaped kwargs. The 10 existing tests rewrite their `linear` mock as a `backend` mock.

`_create_one()` helper goes away — the backend now handles per-task payload construction.

`_short_error_code` stays — it operates on exception `str(e)` regardless of source.

### `tasks/extractor.py` minor change

Currently calls `linear_client.team_context(team_id)` for prompt grounding. After this phase, accept pre-fetched `members` / `labels` lists (or empty for Glide). Caller decides what to fetch.

Signature change:
```python
# Before
def extract(transcript, team_id, model, lang, linear_client, openrouter_client) -> dict
# After
def extract(transcript, members, labels, model, lang, openrouter_client) -> dict
```

The dialog now does:
```python
if backend.name == "linear":
    ctx = backend.context(container_id)
    members, labels = ctx["members"], ctx["labels"]
else:
    members, labels = [], []  # Glide skips grounding
result = extract(transcript=..., members=members, labels=labels, ...)
```

This is a real API change to extractor — its 21 existing tests need adjustment.

### `ui/dialogs/extract_tasks.py` updates

1. **Header row** gets a third dropdown: `[Backend: Linear ▾]` between Model and Container. Values come from `_get_enabled_backends()` which filters by `linear_enabled` / `glide_enabled` config flags.

2. **Backend change → container dropdown swaps**: `_on_backend_changed()` re-runs `_load_containers_async()` against the new backend, repopulating dropdown.

3. `_load_containers_async()` is the renamed `_load_teams_async()` — works generically through `backend.bootstrap()`.

4. **Cache key per backend**: `linear_teams_cache` stays for Linear; Glide uses `glide_boards_cache`. Same 24h TTL discipline.

5. **Empty backend list**: if user disabled both Linear and Glide in Settings, dropdown is `(нет включённых backend'ов)` and Извлечь is disabled.

6. **Extract path**: after selecting backend + container, build `members`/`labels` (empty for Glide), call `extractor.extract`, save with `meta["backend"] = backend.name`.

7. **Send path**: pass selected backend instance to `send_tasks_iter` instead of `LinearClient`.

8. **Default selection**: on dialog open, default to whatever backend was last used in this `tasks.json` (read from `meta["backend"]`). If new extract or unknown — first enabled backend.

### `tasks/persistence.py` — meta carries `backend`

`save_tasks_raw` and `save_tasks` already accept arbitrary meta dict. No code change. Just need callers to include `meta["backend"]`. Old files without `backend` key default to "linear" (back-compat).

### `_TaskRow` identifier display

Currently `set_status_visual(SENT)` appends `· ENG-1234`. For Glide identifiers (UUID prefix) this looks weird because they're 6-char hex. Either:
- (a) Show as-is — `· 467e14` is fine, just shorter
- (b) Add backend hint — `· glide:467e14`

(a) is cleaner. The click already opens `linear_issue_url` (poorly named field but holds Glide URL too).

### Renames worth considering (deferred)

- `Task.linear_issue_id` → `Task.issue_id` (backend-agnostic name)
- `Task.linear_issue_url` → `Task.issue_url`
- `meta["team_id"]` → `meta["container_id"]`

Leaves stale field names in tasks.json. Defer to 6.4.2 cleanup or do a one-shot migration. For now: keep names, just put Glide values into them.

## Files touched

| File | Type | Lines (delta est) |
|---|---|---|
| `tasks/backends/__init__.py` | New | 5 |
| `tasks/backends/base.py` | New | 60 |
| `tasks/backends/linear.py` | New | 80 |
| `tasks/backends/glide.py` | New | 100 |
| `tasks/sender.py` | Modify | -30 / +30 |
| `tasks/extractor.py` | Modify | -15 / +10 |
| `ui/dialogs/extract_tasks.py` | Modify | -50 / +120 |
| `tasks/persistence.py` | (no change) | 0 |
| `tests/test_tasks_send.py` | Modify | -30 / +40 (10 tests rewritten) |
| `tests/test_tasks_extractor.py` | Modify | -30 / +30 (signature change) |
| `tests/test_tasks_backends.py` | New | 100 (8 tests) |

## Tests target

After 6.4.1: ~170 passed (162 baseline − some shifted, + new backend tests).

## Verification

Smoke for the user (after I finish):

1. Settings → ☐ Linear (off), ☑ Glide (on)
2. Транскрибировать любую history-запись
3. Извлечь задачи → диалог открыт
4. Header: dropdown «Backend: Glide» (Linear скрыт)
5. dropdown «Доска» с вашими Glide boards
6. Извлечь → задачи появятся (без assignee/labels — те поля пустые)
7. Отправить выбранные → бейджи `⏳` → `✓ <6-hex>` (UUID prefix)
8. Click на SENT строку → открывается Glide в браузере
9. Открыть `tasks.json` → `meta.backend: "glide"`, `linear_issue_id: "467e14"`, `linear_issue_url: "https://os.tensor-ai.tech/..."`

Then turn Linear back on and verify it still works (regression check).

## Open questions / 6.4.2 follow-ups

- Glide assignee/labels grounding (currently skipped) — Phase 6.4.2 polish
- `Task.linear_issue_*` rename — defer
- `fields_warnings` UX — currently logged only; surface to row badge?
- Glide retry uses same idempotency key → cached error replays. Need new-key-on-retry strategy.
- Glide URL format unverified — first smoke will tell us
