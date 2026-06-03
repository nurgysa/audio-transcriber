# Processing queue + project-organized storage — design

**Date:** 2026-06-02
**Status:** approved (brainstorming)

## Problem

Two coupled gaps:

1. **The pipeline is fully manual and one-at-a-time.** The user records or picks
   a file, clicks **Транскрибировать**, then opens the **Извлечь задачи** dialog
   (which also generates the protocol via its `generate_protocol` checkbox), then
   reviews and sends tasks. Each meeting is babysat through every step; there is
   no way to drop several recordings and walk away, and no at-a-glance view of
   "what's done / what's stuck". A meeting's status today is *implicit* —
   derivable only from which files exist in its folder (`transcript.md`,
   `protocol.md`, `tasks.json`); there is no explicit *in progress* / *failed* /
   *awaiting review*.

2. **All meetings live in one flat pile.** Every meeting is a timestamped folder
   directly under `meetings_dir` (the Obsidian vault). The app already knows each
   meeting's project — the **Извлечь задачи** dialog has a project picker
   («Контекст встречи») whose choice is persisted to `<meeting>/speakers.json`
   as `project_id` — but that association is **not reflected in the folder
   layout**, so finding "all Kitng meetings" means scanning a flat list of 58+
   timestamp-named folders.

## Goal

A **processing queue** that auto-carries audio through transcription → protocol
→ task-draft with live per-stage status, leaving task *sending* as a
human-reviewed gate; **and** meeting folders **organized by project** on disk
(`meetings_dir/<project>/<meeting>/`) so the vault is browsable/searchable by
project. The two ship together because they share one surface: where a meeting
folder is created, how meetings are scanned, and how they are listed.

## Decisions (from brainstorming Q&A)

### Queue

- **Q1 — Hybrid (C).** Auto-pipeline for transcript + protocol (local files,
  safe). **Task *sending* is a reviewed gate** — the worker prepares a draft and
  stops at `awaiting_review`; the user confirms. Junk/duplicate tasks must never
  auto-land on a live board (the reason dedup exists).
- **Q2 — Entry, hybrid (C).** In-app recordings **auto-enqueue on record stop**;
  external files are added explicitly (file-picker button → **«Добавить в
  очередь»**). **No folder watcher** in v1 (would churn against the just-shipped
  `delete_recording_after_transcription` auto-delete; partial-write / non-audio
  filtering).
- **Q3 — UI (B).** The existing **«История»** dialog *becomes* the queue (stage
  columns + per-row action). Queue and meetings list are the same set, so not two
  lists. A lightweight indicator strip on the main window shows counts.
- **Q4 — Task gate (A).** The worker **auto-extracts a task draft**
  (`tasks_raw.json`) and marks `awaiting_review`. **«Отправить»** opens the
  existing dialog pre-loaded with the draft. **Dedup runs at send time** (live
  board freshest then; matches current behavior).
- **Q5 — Remove «Транскрибировать» (a).** Everything routes through the queue;
  the single-file "transcribe now" button + run-loop relocate into the worker.

### Project-organized storage

- **Q6 — Assignment timing, hybrid (3).** Project is chosen **at enqueue**
  (default = last-used project), so the folder is created in the right place
  from the start. No project → the meeting lives **flat in the `meetings_dir`
  root** (not a "Без проекта" pseudo-folder). Reassignment later **moves** the
  folder.
- **Q7 — Source of truth + layout + migration.**
  - **`speakers.json.project_id` is authoritative** for the assignment; the
    folder location is its *reflection*. The app **owns** the layout: it
    creates/moves the meeting folder and, on project rename in the directory
    dialog, renames the project folder (folder name = project name).
  - **No project → meeting folder at `meetings_dir` root** (flat, as today). So
    pre-existing meetings *without* a `project_id` need **zero migration**.
  - Existing meetings *with* a `project_id` are relocated by a **one-time
    dry-run script** (you-only; clients start fresh).
  - **Manual reorganization of project folders in Obsidian/Explorer is out of
    scope** — the app would have to infer project from folder name (fragile).
    The app manages `meetings_dir/<project>/`.

## Architecture — a third frontend over `cli.core`

The untracked `cli/` package already exposes the headless seam: pure, no-Tk
orchestration with lazy heavy imports (the "headless guarantee" enforced by
`tests/test_cli_import_guard.py`). `cli/app.py::_cmd_pipeline` already chains
transcribe → extract → protocol. The queue worker is a **third frontend** (after
GUI and CLI) over the same `cli.core` functions — it does **not** reimplement the
pipeline and does **not** import Tk.

| Stage | Worker calls | Artifact(s) written |
|---|---|---|
| transcribe | `run_transcribe` → `create_history_entry` (at root) + `save_segments`, then `layout.assign_project` (writes `speakers.json`, moves under `<project>/`) | meeting folder under `<project>/` (or root), `transcript.md`, `description.md`, `segments.json`, `speakers.json`, audio copy |
| protocol | `cli.core.run_protocol(...)` | `protocol.md` |
| task-draft | `cli.core.run_extract_tasks(...)` | `tasks_raw.json` |
| send (on user action) | existing dialog → `cli.core.run_send(...)` | `tasks.json` |

Config/keys resolve through `cli.config` (`merged_config()` / `resolve()`) — same
as `_cmd_pipeline` — so the worker reads *persisted* settings, not mutable UI vars.

## Approach

### 1. State model — `processing/model.py`

`StageStatus` enum: `PENDING · RUNNING · DONE · ERROR · AWAITING_REVIEW`
(`AWAITING_REVIEW` only for tasks).

`QueueItem` dataclass (`to_dict`/`from_dict`):

- `id: str` — stable id (timestamp + audio basename; before a folder exists).
- `audio_path: str` — source audio (may be deleted post-transcription).
- `meeting_folder: str | None` — set once the folder is created.
- `title: str` — display label.
- `created_at: str` — ISO timestamp.
- `options: dict` — **enqueue-time snapshot** of `{language, provider, diarize,
  hotwords, denoise, project_id}`. Captures per-meeting intent (incl. the chosen
  project) so later UI changes don't alter in-flight items and the worker is
  deterministic.
- `auto: bool` — **whether the worker drives this item**. Freshly enqueued =
  `True`; pre-existing meetings discovered on disk = `False` (display-only).
  Guards against a first-launch flood (without it, every old meeting's missing
  protocol/tasks would be `PENDING` and the worker would auto-generate drafts for
  all ~58 — a surprise burst of LLM cost).
- `project_id: str | None` — the resolved assignment for display/grouping (read
  from `speakers.json` for reconciled items; from `options` for active ones).
- `transcript / protocol / tasks: StageStatus`.
- `error_stage: str | None`, `error_message: str | None` (humanized).

Package named **`processing/`**, not `queue/` (would shadow the stdlib `queue`).

### 2. Persistence + view — `processing/store.py`

Truths are layered: the meeting folder's **files** are the truth for *stage
status*; `speakers.json.project_id` is the truth for *project assignment*;
`queue.json` is a rebuildable overlay holding **only active (`auto=True`) items**.
The displayed list is derived fresh from disk each time, overlaid with active
items.

- Atomic load/save of `~/.audio-transcriber/queue.json` (home-dir per the shipped
  migration; atomic-write pattern from `directory/store.py`). Active items only.
- **Stage status from file presence:** `transcript.md` → transcript `DONE`;
  `protocol.md` → protocol `DONE`; `tasks.json` → tasks `DONE`; only
  `tasks_raw.json` → tasks `AWAITING_REVIEW`; else `PENDING`.
- **`build_view(meetings_dir, active) -> list[QueueItem]`** — a **two-level**
  scan: for each entry in `meetings_dir`, **skip `recordings/`** (the raw-audio
  pool) and other non-meeting dirs; a meeting folder (has `transcript.md` / the
  timestamp-name shape) at the root is a no-project meeting; any other directory
  is treated as a **project folder** and recursed one level for its meetings.
  **Project is read from each meeting's `speakers.json.project_id`** (resolved to
  a name via the directory store), *not* inferred from the parent folder name —
  so a rename or a transient layout drift never breaks the link. A folder already
  represented by an active item yields to that item; others become `auto=False`
  rows. Effects: existing meetings appear immediately with correct flags and
  project grouping, without being auto-processed; a `RUNNING` active item left by
  a crash re-derives completed stages from disk and the worker resumes the rest.

### 3. Project placement — `processing/layout.py`

The single seam that maps a `project_id` to a folder and keeps the layout in sync:

- `project_dirname(project) -> str` — filesystem-safe folder name from
  `project.name` (strip/replace Windows-illegal `<>:"/\|?*`; Cyrillic/spaces are
  fine; collision of two names → append a short `project.id` suffix).
- `target_dir(meetings_dir, project_id) -> str` — `meetings_dir/<dirname>/` for a
  known project, else `meetings_dir` (root) for `None`/unknown.
- `assign_project(meeting_folder, project_id) -> str` — update **only the
  `project_id`** in `speakers.json` (load-merge-save, preserving existing
  `participants`/`speakers`) **and** move the folder to `target_dir(...)`
  (collision-safe), returning the new path. The one entry point for
  reassignment, used by both the queue UI and the extract dialog.
- `rename_project_folder(old_name, new_name)` — on project rename in the
  directory dialog, rename the matching project folder once.

Depends on `directory/store` to resolve ids → names. No Tk.

### 4. Worker — `processing/worker.py` (`ProcessingQueue`)

- Owns the item list, a `threading.Lock`, and a single **daemon worker thread**.
  **Serial** (one item end-to-end, then the next) — cloud rate limits;
  transcription is the bottleneck; reuses the existing single-worker pattern.
- API: `start()`, `enqueue(audio_path, options)`, `retry(item_id)`,
  `snapshot() -> list[QueueItem]` (deep copy), `on_change` callback.
- Loop: pick the next **`auto=True`** item with a `PENDING` stage → per auto-stage
  set `RUNNING`, call the `cli.core` function, write the artifact, persist, set
  `DONE` (or `ERROR` and **halt this item**). The transcribe stage creates the
  meeting folder via `create_history_entry` (at root) + `save_segments`, then
  `layout.assign_project(folder, options.project_id)` writes `speakers.json` and
  moves it under the project dir (a no-op move when `project_id` is `None`) — the
  same placement seam reassignment uses. After task-draft, set tasks
  `AWAITING_REVIEW` and stop (no auto-send). `auto=False` items are never picked.
- The thread **never touches widgets** — mutates state under the lock and
  persists; the UI reads via `snapshot()`.
- The transcription run-loop currently in `ui/app/transcription_mixin.py`
  (history-entry creation, `save_segments`, `should_delete_after_transcription`)
  **relocates into the worker's transcribe stage**.

### 5. Entry integration — `ui/app/recorder_mixin.py`, `builder.py`

- Record stop → `enqueue(path, options=<current settings + project_id>)`.
- File-picker button → **«Добавить в очередь»** → same `enqueue`.
- A **project selector** on the main bar (combobox of directory projects, default
  = last-used, persisted in config as `last_project_id`) supplies the enqueue
  `project_id`. Low-friction: back-to-back meetings of one project keep the
  default.
- The **«Транскрибировать»** button and `_start_transcription` are removed (Q5);
  `transcription_mixin` shrinks to enqueue + status reflection.

### 6. UI — «История» becomes the queue + main-window indicator

- Extend `ui/dialogs/history.py`: rows **grouped by project** (project header →
  its meetings; a "Без проекта" group for root meetings), each row with four
  stage glyphs (`🎤 · 📝 · 📋 · ✅`) and a per-row action keyed off status:
  `AWAITING_REVIEW → [Отправить]`, `ERROR → [Повтор]`, all-`DONE → [Открыть]`,
  plus a **project reassign** control (dropdown → `layout.assign_project`, which
  moves the folder).
- Glyph legend: `✓ done · ⟳ running · ⏸ awaiting review · ✗! error · — pending`.
- Main window (`builder.py`): indicator strip
  `● Очередь: N в работе · M ждёт ревью · K ошибок`; click opens the dialog.
- App-side poller (`after(...)`, ~1 s) reads `snapshot()` + refreshes the strip
  and the open dialog. Mirrors the existing status-callback pattern; respects CTk
  single-threadedness.

### 7. Task-send gate — draft-review mode in the extract dialog

`ui/dialogs/extract_tasks/` gains a **draft-review mode**: opened from the queue
via `[Отправить]`, it loads tasks from `tasks_raw.json`, **skips LLM extraction**
(the worker already ran it), force-hides the `generate_protocol` checkbox
(protocol exists), pre-selects the meeting's project, then runs the existing
review/edit → dedup(live board) → send UI unchanged. A project change here routes
through `layout.assign_project` (same folder-move seam as the queue UI). On
successful send it writes `tasks.json`; the tasks stage flips to `DONE`.

### 8. One-time migration — `scripts/organize_by_project.py`

Dry-run by default; `--apply` to execute. For each meeting folder under
`meetings_dir` (root-level only — skips `recordings/` and existing project dirs),
read `speakers.json`; if it has a `project_id` that resolves to a project, move
the folder under that project's dir (collision-safe, never overwrite). Meetings
without a `project_id` stay in the root. Prints planned/done moves. You-only; not
bundled.

## Failure handling

- A stage exception (typed: `ProviderError`, `OpenRouterError`,
  `ProtocolGenerationError`, `TranscriptionCancelled`, backend errors) is caught
  per stage; `error_stage`/`error_message` set (via `tasks/errors.humanize()`),
  stage shows `✗!`, the item **halts** (no later stages). The worker moves on.
- **No auto-retry** — avoids burning API/$ on deterministic failures (bad key,
  unsupported language). Retry is manual via `[Повтор]`, re-running from the
  failed stage.
- Folder-move failures (`assign_project`, migration) are best-effort and reported,
  never corrupting `speakers.json` — write the metadata first, then move; a failed
  move leaves a consistent (if mislocated) state recoverable on next assign.

## Phasing (rough; writing-plans finalizes)

Vertical-slice bias to avoid a dead intermediate state:

- **PR-1** — `processing/model.py` + `store.py` (`build_view`, project-aware
  two-level scan) + `layout.py` (`project_dirname`, `target_dir`). Pure logic,
  fully unit-testable, **no behavior change**. Migration script can ride along.
- **PR-2** — `processing/worker.py` + entry integration (record/file → enqueue
  with project, main-bar project selector, remove «Транскрибировать», relocate
  run-loop, folder placement under project) **+** the «История» project-grouped
  queue view + main-window indicator. Shipped together (always
  visible/controllable). Until PR-3, tasks stop at `awaiting_review` and the user
  sends via the existing (re-extracting) dialog.
- **PR-3** — draft-review mode + reassignment-moves-folder (`layout.assign_project`
  in queue UI + extract dialog) + project rename → folder rename.

## Tests

Monkeypatch / source-text only where `ui.app` import is involved (sounddevice /
PortAudio absent on Linux CI):

- **model**: `QueueItem` round-trips `to_dict`/`from_dict`; enum values stable;
  `project_id` carried.
- **store**: atomic save/load; `build_view` over a tmp meetings dir → correct
  per-stage status (incl. `tasks_raw.json`-only → `AWAITING_REVIEW`); **two-level
  scan** finds root meetings *and* meetings inside project dirs; **`recordings/`
  is skipped**; project read from `speakers.json` (not the folder name); active
  item overrides its disk row; stale `RUNNING` re-derives from disk.
- **layout**: `project_dirname` sanitizes illegal chars + collision suffix;
  `target_dir` → project dir vs root for `None`; `assign_project` writes
  `speakers.json` then moves the folder and returns the new path (collision-safe).
- **worker**: with `cli.core.run_*` patched, an `auto=True` item walks
  transcript→protocol→task-draft→`awaiting_review`; the folder is created under
  the project dir; a stage raising sets `ERROR` and halts; `retry` resumes; serial
  ordering; **`auto=False` items never processed** (cost-flood guard).
- **entry wiring** (source-text): record-stop + file-picker call `enqueue` with
  `project_id`; project selector reads/writes `last_project_id`;
  «Транскрибировать» removed.
- **draft-review** (source-text): draft-load path reads `tasks_raw.json`, does
  not call the extractor, `generate_protocol` off, project pre-selected.
- **migration**: selects only root meetings with a resolvable `project_id`; moves
  under the project dir; no-project meetings untouched; dry-run moves nothing;
  collision skipped.

## Out of scope (deliberate)

- Folder watcher / drop-zone auto-ingest (Q2).
- Parallel / concurrent item processing (serial v1).
- Auto-sending tasks to a live board (reviewed gate — Q1).
- Auto-retry of failed stages (manual «Повтор»).
- A separate Queue window (reuse «История» — Q3).
- Backfilling pre-existing meetings — old meetings missing a protocol/task-draft
  are shown (`auto=False`) but not auto-generated.
- **Inferring project from manual folder moves** in Obsidian/Explorer — the app
  owns the `meetings_dir/<project>/` layout (Q7); manual reorg is unsupported.
- A Settings UI for queue/project behavior (none needed in v1).

## Affected files

| File | Change |
|---|---|
| `processing/model.py` | new — `StageStatus`, `QueueItem` (incl. `project_id`) |
| `processing/store.py` | new — atomic `queue.json` I/O + project-aware two-level `build_view` |
| `processing/layout.py` | new — `project_dirname` / `target_dir` / `assign_project` / `rename_project_folder` |
| `processing/worker.py` | new — `ProcessingQueue` serial worker; places folders under the project dir |
| `ui/app/recorder_mixin.py` | record stop → `enqueue` with `project_id` |
| `ui/app/transcription_mixin.py` | run-loop + delete-after-success relocate to worker; shrinks to enqueue/reflect |
| `ui/app/builder.py` | file-picker → «Добавить в очередь»; main-bar project selector; remove «Транскрибировать»; indicator strip |
| `ui/app/__init__.py` | construct/start `ProcessingQueue`; `after()` poller |
| `ui/dialogs/history.py` | project-grouped rows + stage glyphs + action/reassign controls |
| `ui/dialogs/extract_tasks/__init__.py` | draft-review mode; project change routes via `layout.assign_project` |
| `ui/dialogs/directory.py` | project rename → `layout.rename_project_folder` |
| `scripts/organize_by_project.py` | new one-time dry-run migration (you-only) |
| `tests/` | model + store/scan + layout + worker + entry-wiring + draft-review + migration |
