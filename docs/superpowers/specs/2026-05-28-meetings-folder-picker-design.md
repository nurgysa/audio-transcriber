# Meetings folder picker + migration

**Date**: 2026-05-28
**Status**: Draft — ready for implementation planning
**Scope**: User-configurable meetings folder + sane default + auto-migration of legacy `history/` + UI rename «История» → «Митинги»
**Target effort**: ~2 days (multi-PR if needed)

> Brings the meetings folder out from inside the PyInstaller bundle's
> `_internal/` (where it gets wiped on every rebuild+replace) and lets
> users pick a custom location. First-launch detects legacy entries and
> offers to migrate them. Settings dialog gets a new section to change
> the location later. The "История" terminology is also renamed to
> "Митинги" across UI for clarity.

## Context

The current implementation hardcodes the meetings folder ([utils.py:134](../../../utils.py)):

```python
_HISTORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history")
```

In dev source-mode this resolves to `<repo>/history/`. In the PyInstaller
onedir bundle it resolves to `_internal/history/` because `utils.py` lives
under `_internal/`. Two consequences:

1. **Bundle rebuild loses meetings.** Every replace of `C:\Apps\AudioTranscriber\`
   wipes `_internal/history/`. Verified during the 2026-05-28 build sessions
   — `config.json` got backed up explicitly because we knew about it; meetings
   were quietly inside the wipe zone.
2. **User can't pick where to store work product.** Clients have a strong
   preference to keep meeting recordings in Documents / OneDrive / Google
   Drive Backup sync folder / a NAS share — currently all impossible.

The spec adds a user-configurable path, a saner default
(`%USERPROFILE%\Documents\AudioTranscriber\meetings\`), one-time
auto-migration of legacy `_internal/history/` entries on first launch, an
explicit migration prompt when the user changes the path, and renames the
UI surface from «История» → «Митинги».

## Architecture

### File-level changes

| Path | Action | Responsibility |
|---|---|---|
| `utils.py` | Modify | Replace `_HISTORY_DIR` constant with `get_meetings_dir()` function. Add `_DEFAULT_MEETINGS_DIR` + `_LEGACY_HISTORY_LOCATIONS` constants. All existing callers (create_history_entry, list_history_entries, delete_history_entry) call the resolver at-call-time. |
| `meetings_migration.py` | **Create** | Pure-Python migration logic: `detect_old_locations(probe_paths=None) -> list[(str, int)]`, `count_meetings(path) -> int`, `migrate_meetings(src, dst, on_progress, cancel_event) -> dict`. No Tk imports — fully unit-testable on Linux CI. |
| `ui/dialogs/meetings.py` | **Rename + tweak** | `git mv ui/dialogs/history.py ui/dialogs/meetings.py`. Class `HistoryDialog` → `MeetingsDialog`. Class `HistoryViewerDialog` → `MeetingViewerDialog`. Window title «История транскрипций» → «Митинги». Label «Записей: N» → «Митингов: N». |
| `ui/dialogs/migration.py` | **Create** | `MigrationPromptDialog` (Перенести / Оставить / Спросить позже) + `MigrationProgressDialog` (progress bar, cancel). UI shell — calls into `meetings_migration` for actual work. Reused for both first-launch and Settings-trigger flows. |
| `ui/dialogs/settings.py` | Modify | New section card «Митинги» in Tab 1 «Транскрипция» (row=4 — between «Облачное распознавание» and «Словари»; existing rows 4-5 shift to 5-6). Path entry (readonly) + «📁 Выбрать» button + «↻ Default» button + stats string. Path change → triggers `MigrationPromptDialog` if current folder has entries. |
| `ui/app/dialogs_mixin.py` | Modify | Method `_open_history_dialog` → `_open_meetings_dialog`. Import `MeetingsDialog` instead of `HistoryDialog`. |
| `ui/app/builder.py` | Modify | Main-window button text «История» → «Митинги». Callback name follows the mixin rename. |
| `ui/app/__init__.py` | Modify | After `load_config()`, if `config["meetings_dir"]` is empty AND `detect_old_locations()` returns non-empty → schedule `self.after(500, lambda: MigrationPromptDialog(self, found=...))`. |
| `config.example.json` | Modify | New key `"meetings_dir": ""` with inline comment explaining empty = use default. |
| `gdrive/backup.py` | Modify | Callers of `run_backup(history_dir=...)` pass `get_meetings_dir()` explicitly. The `history_dir` kwarg name on `run_backup` stays — only the call sites change. |

### Design principles

1. **`meetings_migration.py` — pure logic, no Tk.** Lets us write real
   unit tests using `tempfile.TemporaryDirectory` and the existing
   `test_*` files convention.
2. **`ui/dialogs/migration.py` — UI shell.** Spawns daemon thread that
   calls migration logic, marshals updates via `parent.after(0, ...)`.
   Used by both first-launch flow and Settings-trigger flow.
3. **`get_meetings_dir()` is a function, not a module-level constant.**
   The current constant freezes at import time; changing the config
   in-flight from Settings would need an app restart. A function reads
   config at-call-time → live updates.
4. **Path resolution has 3 fallback levels** — `config` → default → legacy.
   The app must never crash because a configured path went away.

### Component: `get_meetings_dir()` resolver

```python
def get_meetings_dir() -> str:
    """Return absolute path to the active meetings folder. Creates it if missing.

    Resolution order:
      1. config["meetings_dir"] — if non-empty AND the parent directory
         exists AND it's writable.
      2. %USERPROFILE%\\Documents\\AudioTranscriber\\meetings\\ (default).
      3. <bundle_root>/_internal/history/ — last-resort legacy fallback
         in case Documents itself is unavailable (corporate locked-down
         Windows profiles).

    Each fallback logs a warning when triggered. Callers can rely on
    the returned path existing as a directory after this call returns.
    """
```

`expanduser` + `expandvars` applied to the config value before validation,
so `~/Meetings` and `%USERPROFILE%\Meetings` both work.

### Component: `meetings_migration.migrate_meetings`

```python
def migrate_meetings(
    src: str,
    dst: str,
    on_progress: Callable[[int, int, str], None],   # (done, total, current_name)
    cancel_event: threading.Event,
) -> dict:
    """Move all meeting subfolders from src to dst.

    Each subfolder is moved atomically via shutil.move (which uses
    os.rename for same-volume and copy2+delete for cross-volume).
    Per-folder progress only — no per-byte tracking (would require
    full pre-scan; gain is illusory).

    On collision (dst already has a folder by the same name), the new
    one gets an `_imported_<HHMMSS>` suffix. Timestamp gives uniqueness
    even across multiple migration runs.

    On error (locked file, disk full, permission denied) for a single
    folder, the error is recorded and the next folder is attempted —
    partial migration beats total failure. Caller surfaces error count
    in the UI.

    Cancellation: checked between folders only. The in-progress folder
    completes its move (we don't kill shutil mid-call).

    Returns: {"moved": [name, ...], "skipped": [...], "errors": [(name, msg)...], "cancelled": bool}
    """
```

### First-run migration flow

```
App.__init__
  ↓ load_config()
  ↓ if config.get("meetings_dir", "").strip() == "":
  ↓    old = detect_old_locations()
  ↓    if old:
  ↓       self.after(500, lambda: MigrationPromptDialog(self, found=old))
  ↓ ...continue normal startup
```

The 500ms delay lets the main window finish drawing before the modal
appears — without it the dialog can flash above an unrendered parent.

### Settings-trigger migration flow

```
SettingsDialog.<meetings_section>
  ↓ user clicks «📁 Выбрать»
  ↓ filedialog.askdirectory()
  ↓ if chosen and chosen != current_meetings_dir:
  ↓    if count_meetings(current_meetings_dir) > 0:
  ↓       MigrationPromptDialog(parent=self, src=current, dst=chosen, mode="settings")
  ↓    else:
  ↓       config["meetings_dir"] = chosen; save_config(...)
```

The `mode="settings"` differs from first-launch in that the «Спросить
позже» button is hidden — user explicitly opened Settings to change
this, deferring isn't a coherent action.

## UI changes

### Main window

Button «История» → **«Митинги»**. Same position, same style.

### Meetings dialog (former History dialog)

| Element | Before | After |
|---|---|---|
| Window title | «История транскрипций» | «Митинги» |
| Class | `HistoryDialog` | `MeetingsDialog` |
| Viewer class | `HistoryViewerDialog` | `MeetingViewerDialog` |
| Footer label | «Записей: N» | «Митингов: N» |
| Search placeholder | «🔍 Поиск по имени файла или содержимому...» | (unchanged — still accurate) |
| Empty-state text | «Нет транскрипций» | «Нет митингов» |

### Settings — new section in Tab 1

```
┌─ Митинги ─────────────────────────────────────────┐
│  Папка хранения:                                  │
│  ┌────────────────────────────────────┐ ┌──────┐ │
│  │ C:\Users\Nurgisa\Documents\…       │ │📁    │ │
│  └────────────────────────────────────┘ └──────┘ │
│                                          [↻ Default] │
│                                                   │
│  В этой папке: 24 митинга • 1.2 GB                │
└───────────────────────────────────────────────────┘
```

- Entry is readonly (CTkEntry with `state="readonly"`), shows resolved path
- «📁 Выбрать» opens `filedialog.askdirectory()` Win32 native picker
- «↻ Default» resets `config["meetings_dir"]` to `""` → resolver falls back to default
- Stats string is computed on dialog open AND after path change (refreshes after migration)

### MigrationPromptDialog

**First-launch mode** (`mode="first_launch"`):

```
┌─ Перенос митингов ─────────────────────────────────┐
│                                                    │
│  Найдено 24 митинга в старой папке:               │
│  C:\Apps\AudioTranscriber\_internal\history\       │
│                                                    │
│  Новая папка по умолчанию:                        │
│  C:\Users\Nurgisa\Documents\AudioTranscriber\…    │
│                                                    │
│  [Перенести (24 файла, ~1.2 GB)]                  │
│  [Оставить в старой папке]                        │
│  [Спросить позже]                                  │
└────────────────────────────────────────────────────┘
```

**Settings-trigger mode** (`mode="settings"`):

Same shell minus the «Спросить позже» button. Header says «Перенести
существующие митинги?» instead of «Перенос митингов».

### MigrationProgressDialog

```
┌─ Перенос митингов ─────────────────────────────────┐
│                                                    │
│  Переношу митинг 12 / 24:                         │
│  2026-04-15_14-30-00_quarterly-review              │
│                                                    │
│  [█████████░░░░░░░░░░░░░░░░░░] 47%                │
│                                                    │
│  [Отмена]                                          │
└────────────────────────────────────────────────────┘
```

- Cannot close via WM X (`WM_DELETE_WINDOW → cancel_event.set()`)
- Cancel triggers `cancel_event.set()` and waits for current folder to finish
- On completion: auto-close + main-window status toast

## Data flow / persistence

### Config key

```json
{
  "meetings_dir": ""
}
```

- `""` (empty string) or key absent → resolver uses default
- Any other string → resolver normalizes (`expandvars` + `expanduser` + `abspath`) and uses if parent exists and writable

### Path normalization

```python
def _normalize_meetings_path(raw: str) -> str:
    """Expand %VARS% / ~, normalize separators, return absolute path."""
    return os.path.abspath(os.path.expandvars(os.path.expanduser(raw.strip())))
```

Applied at:
- Settings before save (so `~/Meetings` becomes absolute before persisting)
- `get_meetings_dir()` when reading from config (defensive — handle hand-edited config.json)

### Legacy probe paths

```python
_LEGACY_HISTORY_LOCATIONS = [
    # Sibling of utils.py — in dev source mode this is <repo>/history/,
    # in PyInstaller bundle it's <bundle>/_internal/history/. The same
    # expression yields different real paths depending on whether the
    # app runs from source or frozen, so a single entry covers both.
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "history"),
    # PyInstaller bundle "root" (parent of _internal/) — covers the
    # edge case where a future build script puts history at bundle root.
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "history"),
]
```

`detect_old_locations()` deduplicates + filters paths that don't exist
or have zero subfolders. Returns `[(path, count), ...]` sorted by count
descending.

## Testing strategy

### Unit tests (real I/O on tempdirs)

`tests/test_meetings_migration.py` — 9 tests covering:

1. `migrate_empty_src` → no-op result
2. `migrate_single_meeting` → folder moved, files intact, src cleared
3. `migrate_multiple_meetings` → all moved
4. `migrate_collision_appends_timestamp` → dst original untouched, new gets suffix
5. `migrate_progress_called` → on_progress fires (start + done) per folder
6. `migrate_cancel_mid_flight` → cancelled=True, src+dst total count preserved
7. `detect_old_locations_empty_returns_nothing` → empty list
8. `detect_old_locations_finds_populated` → returns `[(path, count)]`
9. `count_meetings_excludes_non_meeting_dirs` → loose files ignored

### Source-text tests

- `tests/test_meetings_rename.py` — no «История транскрипций» in `ui/dialogs/meetings.py`; «Митинги» in `ui/app/builder.py`; `_open_meetings_dialog` defined in `dialogs_mixin`; class `MeetingsDialog` exists.
- `tests/test_settings_dialog_meetings_section.py` — `_section_card(... "Митинги" ...)` in settings.py; `filedialog.askdirectory` referenced.
- `tests/test_utils_meetings_resolver.py` — `get_meetings_dir` function defined; reads `config["meetings_dir"]`; references `expanduser` + `expandvars`.

### Manual smoke (Windows)

- [ ] First launch with pre-existing `_internal/history/`: prompt appears
- [ ] Migration progress bar shows real progress (1/N, 2/N, ...)
- [ ] Cancel mid-migration: partial state preserved, no data loss
- [ ] Settings folder change: prompt appears, choosing «Переключить» does NOT move files
- [ ] Default reset: ↻ button clears config, resolver returns default
- [ ] Removable drive disconnected: fallback to default, warning in log
- [ ] gdrive backup: ZIP includes meetings from NEW directory only

### Pre-merge contract

- `pytest` green (baseline 388 + ~12 new ≈ 400)
- `python -m ruff check .` clean
- Manual smoke checklist all ticked
- PyInstaller bundle from `dist/` opens, shows meetings list correctly

## Out of scope

Explicitly NOT in this spec:

- **Merged-view (both old + new folder shown simultaneously)** — that's Approach B from brainstorming; we picked Approach A.
- **Auto-migration without user prompt** — privacy concern (user may not want files moved without consent).
- **Multi-folder support** (history of histories) — over-scope for MVP.
- **Cloud-folder integration** (auto-sync to Google Drive) — Phase 7's Drive-backup feature already handles this; meetings folder is local-only.
- **Per-meeting custom paths** — current model is one root folder containing all meeting subfolders; no per-meeting overrides.
- **Migration rollback / undo** — partial state on cancel is accepted as final; user can run another migration to consolidate.
- **Disk-space pre-check** — we don't probe free space before migrating. shutil.move will fail loudly on disk-full, error is reported per-folder; user can clean up + retry.

## Open questions

None — all resolved during brainstorming on 2026-05-28.

## References

- Brainstorming session: 2026-05-28 (this spec is the direct output)
- Current implementation: [utils.py:134](../../../utils.py), [ui/dialogs/history.py](../../../ui/dialogs/history.py)
- gdrive backup integration: [gdrive/backup.py](../../../gdrive/backup.py)
- Test discipline: `feedback_ui_app_import_breaks_linux_ci.md` (drives the
  `meetings_migration.py` pure-logic separation)
