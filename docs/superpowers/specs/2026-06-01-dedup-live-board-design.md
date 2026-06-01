# Dedup against the live backend board — production design

**Date:** 2026-06-01
**Status:** design (awaiting review → writing-plans)
**Scope:** Linear + Trello (Glide excluded — `supports_comments = False`)

## Problem

Task-dedup (#88–#90) shipped, but on the first real run it created a
duplicate (`NUR-40` "Изучить систему СУП для последующей интеграции")
instead of commenting on the existing `NUR-37` "Изучить систему СУП".

**Root cause (verified, not theory):** the dedup registry is built
*only* from the app's own local meeting history
(`build_sent_registry()` over `list_history_entries()` + each meeting's
`tasks.json`), and it includes a sent task only if it has a non-empty
`backend_ref`. `backend_ref` persistence shipped *today* with #88, so
every one of the user's 56 historical `tasks.json` files has
`backend_ref = None`. A live run of `build_sent_registry` over the real
history returns **0 entries** (confirmed; no exception). Therefore the
new task had nothing to match against and was created fresh.

Two consequences the design must fix:
1. Dedup never sees issues already on the Linear/Trello board (it only
   knew what the app itself sent with a `backend_ref`).
2. Cold-start: a fresh install / pre-#88 history has an empty registry,
   so dedup is a silent no-op until enough new tasks accumulate.

## Goal

Match each newly-extracted task against the **existing open items on the
live backend board** (Linear team / Trello board) and, on a confirmed
match, comment on the existing item instead of creating a duplicate.
Production-grade: **complete, idempotent, observable, resilient**, and
gated on a **real-API acceptance smoke** (not only mocked tests).

## Approach

**A1 — live-board registry (paginated full active fetch) + the existing
fuzzy/LLM matching engine.** The matching engine (`find_candidates`,
`select_match`, `disambiguate_via_llm`), the dup badge, the
comment/create toggle, and the `COMMENTED` status are **already built
and tested** — the only missing piece is the registry source. We swap
the source from local history to a live-board fetch.

Rejected alternatives:
- **B — merge live-board + local history.** Adds complexity and
  re-opens "suppress a recurring task whose prior instance is closed"
  with no correctness gain (the live board is a superset of app-sent
  items that are still open). YAGNI.
- **C — backfill `backend_ref` into old `tasks.json`.** Fragile, partial
  (per-issue node-id lookups), and still blind to items created outside
  the app.
- **A2 — backend server-side search** (`issueSearch` / Trello `/search`)
  for candidate retrieval. More scalable for very large boards, but
  trades *completeness* (search relevance is opaque and can miss the
  true duplicate) for scale we don't need at current board sizes
  (NUR ≈ 33 issues). Kept as the documented path-to-scale, triggered
  when a board exceeds the pagination safety cap (below).

## Design

### Data flow

```
_run_dedup(tasks, backend, container_id, ...)
  └─ build_board_registry(backend, container_id)        # NEW source
       └─ backend.list_existing(container_id)            # NEW per-backend
            → list[ExistingItem]                          # paginated, active-only
  └─ select_match(task, registry, ...)                   # UNCHANGED engine
       → task.dup_match (SentTask)
  └─ (send) comment-or-create toggle → COMMENTED         # UNCHANGED UI/send
       └─ idempotent guard before posting comment        # NEW
```

### 1. New backend capability (`tasks/backends/base.py`)

```python
@dataclass(frozen=True)
class ExistingItem:
    title: str
    ref: str          # comment-addressable id (Linear node UUID / Trello card id)
    identifier: str    # human badge (NUR-37 / #42)
    url: str
    description: str = ""   # used by LLM disambiguation (borderline band)
```

Add to the `TaskBackend` Protocol:

```python
def list_existing(self, container_id: str) -> list[ExistingItem]:
    """Open items in the container's board, for dedup. Active only
    (no completed/canceled/archived). Raises the backend's error class
    on HTTP/network failure (caller swallows best-effort)."""
    ...
```

Backends without comments (Glide) are never asked — `_run_dedup` gates
on `supports_comments` first.

### 2. Linear (`tasks/linear_client.py` + `tasks/backends/linear.py`)

`LinearClient.list_issues(team_id)`:
- GraphQL `team(id).issues(first: 250, after: <cursor>, filter: {
  state: { type: { nin: ["completed", "canceled"] } } }, orderBy: updatedAt)`
  with `nodes { id identifier title url description }` and
  `pageInfo { hasNextPage endCursor }`.
- **Paginate** until `hasNextPage == false` OR a **safety cap of 2000**
  issues (8 pages). If the cap is hit, log a WARNING (signal to adopt
  A2 search-based retrieval) and use what was fetched.
- Partial failure mid-pagination → return what was collected + log
  (best-effort; a partial registry beats none).

`LinearBackend.list_existing(container_id)` → maps issues to
`ExistingItem(title, ref=id, identifier, url, description)`.

### 3. Trello (`tasks/trello_client.py` + `tasks/backends/trello.py`)

`TrelloClient.list_open_cards(list_id)`:
- Resolve `list_id → board_id` (reuse the list→board step already used
  by `board_context` since the #80 fix).
- `GET /1/boards/{board_id}/cards?filter=open&fields=name,desc,url,
  idShort,shortLink,id` — **board-level** (not just the target list) so a
  duplicate that was moved to another list on the same board is still
  caught. Trello returns up to 1000 open cards per board by default;
  paginate via `before` if a board exceeds that (same 2000 safety cap +
  WARNING).

`TrelloBackend.list_existing(container_id)` → `ExistingItem(title,
ref=card id, identifier="#"+idShort (or shortLink), url, description=desc)`.

### 4. Registry builder (`tasks/dedup.py`)

```python
def build_board_registry(backend, container_id: str) -> list[SentTask]:
    """Live-board registry: map backend.list_existing() to SentTask.
    meeting_name/meeting_date are "" (the dup badge uses identifier/url,
    not meeting provenance — verified in task_row.py)."""
```

All entries carry `backend=backend.name` and the **passed
`container_id`** so the existing `find_candidates` scope filter
(`sent.container_id != container_id`) passes unchanged. (For Trello,
board-level cards are tagged with the dedup-scope = the passed list id —
the scope is "this board", keyed by the container the task enters.)

`build_sent_registry` (local history) is retained in the module and its
tests, but **no longer wired** into `_run_dedup`.

### 5. Matching engine (mostly unchanged)

`find_candidates` / `select_match` / thresholds (0.82 / 0.55):
unchanged. The СУП case scores ≈ 0.585 (borderline) → LLM.

`disambiguate_via_llm` **enhanced**: the prompt includes the new task's
description and each candidate's description (now available on
`ExistingItem`), not just titles. Titles still drive the cheap fuzzy
pre-filter; the LLM judges on fuller context for the borderline band.
Malformed/`null` reply still fails SAFE to "no match" → create new.

### 6. Idempotent commenting (new hard requirement)

A re-extraction of the same meeting must not post the same dedup comment
twice.

- The dedup comment body carries a stable hidden marker:
  `\n\n<!-- audiotx-dedup:{sig} -->` where
  `sig = sha1(normalize_title(new_task.title))[:12]`.
- Before posting, fetch the target item's existing comments
  (`LinearClient.list_comments(issue_id)` via `issue.comments.nodes.body`;
  `TrelloClient.list_card_comments(card_id)` via
  `GET /1/cards/{id}/actions?filter=commentCard`) and **skip the post**
  if a comment already contains `audiotx-dedup:{sig}`. Skipped =
  treated as already-commented (still resolves to `COMMENTED` in the UI;
  no duplicate comment).
- Cost: one comments fetch per *matched* item at send time. Matches are
  rare, so this is negligible.

### 7. Error handling / resilience

- `list_existing` failure (network / 4xx / 5xx / auth) → caught in
  `_run_dedup` (`except (OSError, LinearError, TrelloError, ...)`) →
  log WARNING, skip dedup for this run. Extraction is unaffected (badges
  simply don't appear) — the existing best-effort contract is preserved.
- 429 (rate limit): clients honor `Retry-After` with one bounded retry;
  on repeated 429 the call fails and dedup is skipped (logged), never
  crashing the extraction.
- Partial pagination failure: use the partial registry + log.

### 8. Observability (new)

INFO logs at each boundary so a future "dedup не работает" is
diagnosable instead of silent:
- registry build: `backend`, `container_id`, pages fetched, items
  fetched, cap-hit flag.
- per task: candidate count + top score; match decision (confident /
  llm-confirmed / no-match).
- send: comment posted vs skipped-idempotent (with target identifier).

### 9. `_run_dedup` wiring (`ui/dialogs/extract_tasks/__init__.py`)

- Registry source: `build_board_registry(backend, container_id)`
  (replaces the `build_sent_registry(list_history_entries(), …)` call).
- `except` clause widened to the backend error classes
  (`LinearError`, `TrelloError`) alongside `OSError`; best-effort
  swallow + WARNING log kept.
- Send path: `COMMENTED` status + comment/create toggle already wired;
  insert the idempotency guard (§6) at comment time.

## Testing

**Unit (mock HTTP) — must be green:**
- `list_issues`: single page, multi-page cursor pagination, empty board,
  state filter excludes completed/canceled, mid-page error → partial +
  no raise to caller-of-builder, cap-hit WARNING.
- `list_open_cards`: board-level fetch, parsing (idShort vs shortLink),
  empty board, error.
- `build_board_registry`: `ExistingItem → SentTask` mapping; backend
  error propagates to `_run_dedup` and is swallowed.
- `disambiguate_via_llm` with descriptions present.
- idempotency: marker present → skip post; absent → post; signature
  derivation stable.
- `select_match` over a board registry — the СУП case (borderline → LLM
  → match).
- Existing dedup-engine tests remain green (engine untouched).

**Mandatory real-API acceptance smoke (the gate — mocked tests gave a
false-green on Trello before, #79):**
1. Linear: re-extract the "3rd part kitng in the corridor" meeting
   against the real NUR board → must **comment on NUR-37**, NOT create a
   new NUR-4x. Open NUR-37 → the dedup comment is present.
2. Re-run #1 again → must **NOT** post a second comment (idempotency).
3. Trello: one board with a known duplicate → comments on the existing
   card, board-level (even if the card is in a different list).

## Files touched

| File | Change |
|---|---|
| `tasks/backends/base.py` | `ExistingItem` + `list_existing` in Protocol |
| `tasks/linear_client.py` | `list_issues` (paginated, active-only) + `list_comments` |
| `tasks/backends/linear.py` | `list_existing` |
| `tasks/trello_client.py` | `list_open_cards` (board-level) + `list_card_comments` |
| `tasks/backends/trello.py` | `list_existing` |
| `tasks/dedup.py` | `build_board_registry` + LLM prompt uses descriptions |
| `ui/dialogs/extract_tasks/__init__.py` | `_run_dedup` source swap + idempotency guard at comment time + logging |
| `tests/…` | new unit suites above |

## Out of scope (path-to-scale)

- **A2** backend server-side search for candidate retrieval — adopt only
  when a board exceeds the 2000-item pagination safety cap (the WARNING
  is the trigger).
- Caching the board snapshot across extractions — rejected: fresh fetch
  per extraction is more correct (no staleness) and costs one paginated
  fetch.
- Cross-backend dedup (a Linear task duplicating a Trello card) — out of
  scope; a comment must land in the same backend + container.
