# Google Drive Phase 7.1 — Manual Backup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Phase 7.1 of the Google Drive backup feature — a "Сделать backup сейчас" button in the Settings dialog that zips the user's `history/` directory + redacted `config.json`, builds a manifest with checksums, and uploads everything to a timestamped subfolder under `audio-transcriber-backup/` on the user's Drive. After 7.1 users have working manual backup; restore comes in 7.2, scheduling in 7.3.

**Architecture:** Two new modules in the existing `gdrive/` package: `client.py` is a thin synchronous wrapper over the Google Drive v3 API (find/create folders + upload files), and `backup.py` orchestrates the whole snapshot (redact config, zip history excluding audio, build manifest, sequential uploads via client). Settings dialog grows one button + a status label, hooked via the same daemon-thread + `self.after(0, ...)` pattern as the Войти button from 7.0. Reuses `GDriveAuth.ensure_valid_credentials()` from 7.0 so the user never gets a "please sign in again" mid-backup unless their refresh token has actually been revoked.

**Tech Stack:** Python 3.10, `google-api-python-client==2.196.0`, `google-auth==2.46.0` (both pinned in 7.0), stdlib `zipfile` + `hashlib` + `json` + `socket`, pytest, ruff. No new packages.

**Spec:** `docs/superpowers/specs/2026-04-30-gdrive-backup-design.md` (commit `bbfa10f`).

---

## Pre-flight (do once before starting)

- [ ] Confirm Phase 7.0 has shipped to `main`: `git log --oneline -1 gdrive/auth.py` should show a commit from PR #40 or later.
- [ ] Confirm baseline tests green: `pytest -q` → should report **356 passed** (per CLAUDE.md post-7.0 baseline).
- [ ] Confirm ruff clean: `python -m ruff check .` → exit 0.
- [ ] Optional (only needed for the manual smoke at C.5 Step 3): user has done the Phase 7.0 B.5 Pre-flight — i.e. real `CLIENT_ID` / `CLIENT_SECRET` are wired in `gdrive/auth.py` and a sign-in round-trip works. If they're still placeholders, the unit tests in PR-A/PR-B and the headless smoke tests in PR-C still pass; only the live "click Сделать backup, see file on Drive" check has to wait.

## File map

| PR | File | Change | Estimated LOC |
|---|---|---|---|
| A | `gdrive/client.py` | **NEW** — `DriveClient` class wrapping Drive v3 API | ~120 |
| A | `tests/test_gdrive_client.py` | **NEW** — 8 mock-based tests | ~140 |
| B | `gdrive/backup.py` | **NEW** — orchestrator: `redact_config`, `zip_history`, `build_manifest`, `run_backup` | ~180 |
| B | `tests/test_gdrive_backup.py` | **NEW** — 10 mock + filesystem tests | ~200 |
| C | `config.example.json` | Add `gdrive_root_folder_id` key | +1 |
| C | `ui/dialogs/settings.py` | Add "Сделать backup" button + `_handle_gdrive_backup_now` worker + `_on_gdrive_backup_*` callbacks | ~60 |
| C | `ui/app/settings_mixin.py` | Add `_on_gdrive_backup_succeeded` (persist `gdrive_last_backup` + `gdrive_root_folder_id`) | ~20 |
| C | `tests/test_settings_gdrive.py` | +3 source-text smoke assertions (new button + handler + mixin callback) | ~15 |
| C | `CLAUDE.md` | Update "Active work" Phase 7 bullet + bump test baseline | +12 |

**Total**: ~750 LOC across 3 PRs (~420 production + ~370 tests/docs). Spec estimated ~300 LOC + ~150 tests = ~450 LOC; we're ~50% over because the spec didn't include the API wrapper LOC explicitly and `googleapiclient` resumable-upload boilerplate inflates `client.py`. Acceptable.

## Branch strategy

Per CLAUDE.md memory `feedback_stacked_pr_squash_merge.md`: serialize via main, no stacked PRs.

```
main
 ├── feat/gdrive-phase-7.1-client         → PR-A
 │
 main (after PR-A merges)
 ├── feat/gdrive-phase-7.1-backup-orch    → PR-B
 │
 main (after PR-B merges)
 ├── feat/gdrive-phase-7.1-ui             → PR-C (includes CLAUDE.md update)
```

---

## PR-A: `gdrive/client.py` — Drive API wrapper

**Branch:** `feat/gdrive-phase-7.1-client` (from `main`).

**Goal:** Ship `gdrive.client.DriveClient` as a thin, tested wrapper over `googleapiclient.discovery.build("drive", "v3")`. Three operations: `find_folder(name, parent_id)`, `create_folder(name, parent_id)`, `upload_file(local_path, drive_name, parent_id, mime_type)`. PR-B's orchestrator composes these.

**Pre-task:**

```bash
git checkout main && git pull --ff-only origin main
git checkout -b feat/gdrive-phase-7.1-client
```

---

### Task A.1: Create `gdrive/client.py` skeleton + first failing test

**Files:**
- Create: `gdrive/client.py`
- Create: `tests/test_gdrive_client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_gdrive_client.py`:

```python
"""Tests for gdrive.client.DriveClient — Phase 7.1.

Pure module — no real Drive API, no network. Mocks
`googleapiclient.discovery.build` at its source module so the
lazily-imported symbol inside DriveClient methods resolves to a
MagicMock that returns canned Drive API responses.

Codex P1 lesson from PR #39 applies: patch the SOURCE
(`googleapiclient.discovery.build`) NOT `gdrive.client.build` —
lazy imports don't bind names as module attributes.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from gdrive.client import DriveClient


def test_constructor_takes_credentials_and_stores_them():
    """DriveClient(creds) stores the credentials object without touching
    the network. The actual `build()` call happens lazily on first API
    method call so construction stays cheap (~µs)."""
    fake_creds = MagicMock()
    client = DriveClient(fake_creds)
    assert client._credentials is fake_creds
    assert client._service is None, "Service should be lazy"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_gdrive_client.py::test_constructor_takes_credentials_and_stores_them -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gdrive.client'`.

- [ ] **Step 3: Create `gdrive/client.py` with the constructor**

Create `gdrive/client.py`:

```python
"""Drive API v3 wrapper for Phase 7.1+ — upload-only surface.

This module is intentionally tiny. It hides the
`googleapiclient.discovery.build` ceremony behind three methods that
Phase 7.1's backup orchestrator (and Phase 7.2's restore) call. Future
phases (scheduler retention cleanup, sync) will extend with `list`,
`delete`, and `download`.

The Drive API client is built lazily on first method call so that
constructing a DriveClient (e.g. at app startup) doesn't pay the
~30-50 MB import + HTTP-discovery cost — only signing-in-and-clicking-
backup does.

Codex P1 lesson from Phase 7.0 PR #39: `googleapiclient.discovery.build`
is imported INSIDE methods, NOT at module top. Tests must patch the
source (`googleapiclient.discovery.build`) — patching
`gdrive.client.build` would AttributeError because the lazy import
never binds `build` as a `gdrive.client` attribute.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# MIME types used by the backup payload. Drive folders have a magic
# MIME; arbitrary application data uses application/octet-stream
# unless we know better (JSON / ZIP get accurate types so Drive's web
# UI can preview them).
FOLDER_MIME = "application/vnd.google-apps.folder"
JSON_MIME = "application/json"
ZIP_MIME = "application/zip"


class DriveClient:
    """Synchronous wrapper over Drive API v3. One instance per backup
    operation (cheap; just holds credentials + lazy-built service)."""

    def __init__(self, credentials) -> None:
        self._credentials = credentials
        self._service = None
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_gdrive_client.py::test_constructor_takes_credentials_and_stores_them -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gdrive/client.py tests/test_gdrive_client.py
git commit -m "$(cat <<'EOF'
feat(gdrive/client): DriveClient skeleton + lazy-service constructor

First slice of the Phase 7.1 Drive API wrapper. Constructor stores the
google.oauth2.credentials.Credentials object passed by callers (Phase
7.1 backup orchestrator will get them from GDriveAuth.get_credentials)
and defers the actual googleapiclient.discovery.build() until the
first API method call — keeps DriveClient construction cheap and
keeps the ~30-50 MB Google API client import out of cold start.

Three MIME constants land here for the methods to come: FOLDER_MIME
for find/create_folder, JSON_MIME + ZIP_MIME for upload_file's
sensible defaults.

Tests patch googleapiclient.discovery.build at its SOURCE module per
the Codex P1 lesson from PR #39 — lazy imports don't bind names as
local module attrs.
EOF
)"
```

---

### Task A.2: Implement `_get_service()` + `find_folder()`

**Files:**
- Modify: `gdrive/client.py`
- Modify: `tests/test_gdrive_client.py`

- [ ] **Step 1: Write two failing tests**

Append to `tests/test_gdrive_client.py`:

```python
def test_get_service_builds_lazily_and_caches():
    """First call to _get_service() builds the discovery client; second
    call returns the cached instance without rebuilding. Important
    because discovery makes an HTTP GET to /v3/discovery (or hits the
    cached static schema) — we don't want N calls per backup."""
    fake_creds = MagicMock()
    fake_service = MagicMock()
    client = DriveClient(fake_creds)

    with patch("googleapiclient.discovery.build", return_value=fake_service) as mock_build:
        first = client._get_service()
        second = client._get_service()

    assert first is fake_service
    assert second is fake_service
    mock_build.assert_called_once_with("drive", "v3", credentials=fake_creds, cache_discovery=False)


def test_find_folder_returns_id_when_match_exists():
    """find_folder runs files().list with a name + mimeType + parent
    query. Returns the first matching folder's id, or None."""
    fake_creds = MagicMock()
    fake_service = MagicMock()
    fake_service.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "folder-id-123", "name": "audio-transcriber-backup"}]
    }
    client = DriveClient(fake_creds)

    with patch("googleapiclient.discovery.build", return_value=fake_service):
        result = client.find_folder("audio-transcriber-backup")

    assert result == "folder-id-123"
    # Verify the query was correct (escapes name, filters by folder mime + non-trashed).
    fake_service.files.return_value.list.assert_called_once()
    call_kwargs = fake_service.files.return_value.list.call_args.kwargs
    assert "name = 'audio-transcriber-backup'" in call_kwargs["q"]
    assert FOLDER_MIME in call_kwargs["q"]
    assert "trashed = false" in call_kwargs["q"]


def test_find_folder_returns_none_when_no_match():
    """No folder by that name → None, not exception. Caller decides
    whether to create one."""
    fake_creds = MagicMock()
    fake_service = MagicMock()
    fake_service.files.return_value.list.return_value.execute.return_value = {"files": []}
    client = DriveClient(fake_creds)

    with patch("googleapiclient.discovery.build", return_value=fake_service):
        assert client.find_folder("does-not-exist") is None
```

Note the import line at the top of the test file needs to include `FOLDER_MIME` — add it:

```python
from gdrive.client import FOLDER_MIME, DriveClient
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_gdrive_client.py -v
```

Expected: 3 FAILs (`AttributeError: 'DriveClient' object has no attribute '_get_service'` / `'find_folder'`).

- [ ] **Step 3: Implement `_get_service` and `find_folder`**

Append to the `DriveClient` class in `gdrive/client.py`:

```python
    def _get_service(self):
        """Lazy-build (and cache) the googleapiclient discovery client.

        cache_discovery=False suppresses a noisy warning about file-based
        discovery caching — we don't need it for our small operation
        count (1 list + 1-2 creates + 3 uploads per backup).
        """
        if self._service is None:
            # Lazy import — see module docstring + Codex P1 lesson.
            from googleapiclient.discovery import build

            self._service = build(
                "drive", "v3",
                credentials=self._credentials,
                cache_discovery=False,
            )
        return self._service

    def find_folder(self, name: str, parent_id: str | None = None) -> str | None:
        """Return the Drive file ID of the first folder named ``name``
        under ``parent_id`` (root if None). None if no match.

        Folder names on Drive are NOT unique — two folders with the
        same name can coexist. We return the FIRST match (ordered by
        Drive's default — typically creation time). Backup orchestrator
        only ever creates one ``audio-transcriber-backup`` folder so
        collisions are user-induced (they manually created a duplicate)
        and we accept whichever Drive returns.
        """
        # Escape single-quote in name per Drive query syntax (rare in
        # our use case but defensive).
        safe_name = name.replace("'", "\\'")
        q_parts = [
            f"name = '{safe_name}'",
            f"mimeType = '{FOLDER_MIME}'",
            "trashed = false",
        ]
        if parent_id is not None:
            q_parts.append(f"'{parent_id}' in parents")
        query = " and ".join(q_parts)

        service = self._get_service()
        resp = service.files().list(
            q=query,
            fields="files(id, name)",
            pageSize=10,
        ).execute()
        files = resp.get("files", [])
        return files[0]["id"] if files else None
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_gdrive_client.py -v
```

Expected: 4 tests PASS (1 from A.1 + 3 from A.2).

- [ ] **Step 5: Commit**

```bash
git add gdrive/client.py tests/test_gdrive_client.py
git commit -m "$(cat <<'EOF'
feat(gdrive/client): _get_service() + find_folder()

_get_service() lazy-builds and caches the googleapiclient discovery
client. cache_discovery=False suppresses the noisy file-cache warning;
our op count per backup is small enough that the cache doesn't help.

find_folder(name, parent_id=None) does a files().list with a Drive
query that filters by name + folder MIME + non-trashed + optional
parent. Returns the first matching folder's id or None. Folder names
on Drive are not unique, but our orchestrator only creates one
top-level audio-transcriber-backup folder so collisions are
user-induced; whichever Drive returns is fine.

Single-quote escaping in the name is defensive — our hardcoded names
don't contain quotes, but future callers might pass user-provided
names.
EOF
)"
```

---

### Task A.3: Implement `create_folder()` + `find_or_create_folder()`

**Files:**
- Modify: `gdrive/client.py`
- Modify: `tests/test_gdrive_client.py`

- [ ] **Step 1: Write two failing tests**

Append to `tests/test_gdrive_client.py`:

```python
def test_create_folder_calls_files_create_with_correct_metadata():
    """create_folder(name, parent_id) calls files().create with the
    folder MIME, the name, and the parent (if given). Returns the new
    folder id from the response."""
    fake_creds = MagicMock()
    fake_service = MagicMock()
    fake_service.files.return_value.create.return_value.execute.return_value = {
        "id": "newly-created-id"
    }
    client = DriveClient(fake_creds)

    with patch("googleapiclient.discovery.build", return_value=fake_service):
        result = client.create_folder("audio-transcriber-backup")

    assert result == "newly-created-id"
    fake_service.files.return_value.create.assert_called_once()
    body = fake_service.files.return_value.create.call_args.kwargs["body"]
    assert body == {
        "name": "audio-transcriber-backup",
        "mimeType": FOLDER_MIME,
    }


def test_create_folder_with_parent_includes_parents_field():
    """When parent_id is given, the metadata body includes it under
    the `parents` list per Drive API conventions."""
    fake_creds = MagicMock()
    fake_service = MagicMock()
    fake_service.files.return_value.create.return_value.execute.return_value = {
        "id": "child-id"
    }
    client = DriveClient(fake_creds)

    with patch("googleapiclient.discovery.build", return_value=fake_service):
        client.create_folder("2026-05-23T22-00-00", parent_id="root-folder-id")

    body = fake_service.files.return_value.create.call_args.kwargs["body"]
    assert body["parents"] == ["root-folder-id"]


def test_find_or_create_folder_returns_existing_when_match():
    """If find_folder returns an id, find_or_create_folder returns it
    without calling create. Avoids creating duplicate folders on
    repeat backups."""
    fake_creds = MagicMock()
    fake_service = MagicMock()
    fake_service.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "existing-id", "name": "audio-transcriber-backup"}]
    }
    client = DriveClient(fake_creds)

    with patch("googleapiclient.discovery.build", return_value=fake_service):
        result = client.find_or_create_folder("audio-transcriber-backup")

    assert result == "existing-id"
    fake_service.files.return_value.create.assert_not_called()


def test_find_or_create_folder_creates_when_no_match():
    """If find_folder returns None, find_or_create_folder calls create
    and returns the new id."""
    fake_creds = MagicMock()
    fake_service = MagicMock()
    fake_service.files.return_value.list.return_value.execute.return_value = {"files": []}
    fake_service.files.return_value.create.return_value.execute.return_value = {
        "id": "freshly-made-id"
    }
    client = DriveClient(fake_creds)

    with patch("googleapiclient.discovery.build", return_value=fake_service):
        result = client.find_or_create_folder("audio-transcriber-backup")

    assert result == "freshly-made-id"
    fake_service.files.return_value.create.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_gdrive_client.py -v -k "create_folder or find_or_create"
```

Expected: 4 FAILs (`AttributeError: 'DriveClient' object has no attribute 'create_folder'` / `'find_or_create_folder'`).

- [ ] **Step 3: Implement `create_folder` and `find_or_create_folder`**

Append to the `DriveClient` class in `gdrive/client.py`:

```python
    def create_folder(self, name: str, parent_id: str | None = None) -> str:
        """Create a Drive folder. Returns the new folder's id.

        Drive API semantics: a "folder" is a file with mimeType
        application/vnd.google-apps.folder. The `parents` field is a
        list (Drive technically supports multiple parents but we never
        use that). Folder names are not unique — caller's job to dedup
        via find_folder first if uniqueness matters.
        """
        body: dict = {
            "name": name,
            "mimeType": FOLDER_MIME,
        }
        if parent_id is not None:
            body["parents"] = [parent_id]

        service = self._get_service()
        resp = service.files().create(body=body, fields="id").execute()
        return resp["id"]

    def find_or_create_folder(self, name: str, parent_id: str | None = None) -> str:
        """find_folder; if None, create_folder. Returns the (existing or
        new) folder id. Used by the orchestrator to ensure the
        ``audio-transcriber-backup`` top folder exists exactly once,
        then create a timestamped child for each snapshot.
        """
        existing = self.find_folder(name, parent_id=parent_id)
        if existing is not None:
            return existing
        return self.create_folder(name, parent_id=parent_id)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_gdrive_client.py -v
```

Expected: 7 tests PASS (1 + 3 + 4 = 8 ... wait 1 + 3 + 4 is actually 8, my arithmetic).

Re-count: A.1 had 1 test. A.2 had 3 tests. A.3 has 4 tests. Total = 8. Expected: 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add gdrive/client.py tests/test_gdrive_client.py
git commit -m "$(cat <<'EOF'
feat(gdrive/client): create_folder() + find_or_create_folder()

create_folder(name, parent_id=None) builds a Drive folder via
files().create with the magic application/vnd.google-apps.folder
MIME. Returns the new folder's id. parent_id is optional (falls
back to root); when given, lands in the body's `parents` list.

find_or_create_folder is the composed primitive Phase 7.1's backup
orchestrator will call: ensure the audio-transcriber-backup top
folder exists exactly once across repeat backups. Drive folder
names aren't unique — without the dedup pass we'd accumulate one
new audio-transcriber-backup folder per snapshot.

Four new tests cover: create with no parent (no `parents` key),
create with parent (parents=[id]), find_or_create when found
(no create call), find_or_create when missing (creates + returns).
EOF
)"
```

---

### Task A.4: Implement `upload_file()`

**Files:**
- Modify: `gdrive/client.py`
- Modify: `tests/test_gdrive_client.py`

`upload_file` is the heaviest method — uses `MediaFileUpload` to stream from disk to Drive in chunks. For Phase 7.1's small payloads (≤1 MB) a single-shot upload is fine; resumable upload is overkill but `MediaFileUpload` is the standard primitive and handles both.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gdrive_client.py`:

```python
def test_upload_file_calls_files_create_with_media_and_metadata(tmp_path):
    """upload_file builds the right metadata body, wraps the local
    file in a MediaFileUpload, and returns the new file id."""
    # Real file on disk so MediaFileUpload's path validation passes.
    local_file = tmp_path / "manifest.json"
    local_file.write_text('{"version": 1}')

    fake_creds = MagicMock()
    fake_service = MagicMock()
    fake_service.files.return_value.create.return_value.execute.return_value = {
        "id": "uploaded-file-id"
    }
    fake_media_cls = MagicMock()
    fake_media_instance = MagicMock()
    fake_media_cls.return_value = fake_media_instance

    client = DriveClient(fake_creds)

    with patch("googleapiclient.discovery.build", return_value=fake_service), \
         patch("googleapiclient.http.MediaFileUpload", fake_media_cls):
        result = client.upload_file(
            local_path=local_file,
            drive_name="manifest.json",
            parent_id="snapshot-folder-id",
            mime_type=JSON_MIME,
        )

    assert result == "uploaded-file-id"

    # Body has name + parent (no MIME — Drive infers from MediaFileUpload).
    body = fake_service.files.return_value.create.call_args.kwargs["body"]
    assert body == {
        "name": "manifest.json",
        "parents": ["snapshot-folder-id"],
    }
    # MediaFileUpload was constructed with the local path + mime type.
    fake_media_cls.assert_called_once()
    media_args = fake_media_cls.call_args
    assert media_args.args[0] == str(local_file) or media_args.kwargs.get("filename") == str(local_file)
    assert media_args.kwargs.get("mimetype") == JSON_MIME
    # The media kwarg got passed to create().
    assert fake_service.files.return_value.create.call_args.kwargs["media_body"] is fake_media_instance
```

Note the import at top of test file needs `JSON_MIME` — extend the existing import line:

```python
from gdrive.client import FOLDER_MIME, JSON_MIME, DriveClient
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_gdrive_client.py::test_upload_file_calls_files_create_with_media_and_metadata -v
```

Expected: FAIL with `AttributeError: 'DriveClient' object has no attribute 'upload_file'`.

- [ ] **Step 3: Implement `upload_file`**

Append to the `DriveClient` class in `gdrive/client.py`:

```python
    def upload_file(
        self,
        local_path,                   # pathlib.Path or str
        drive_name: str,
        parent_id: str,
        mime_type: str = "application/octet-stream",
    ) -> str:
        """Upload ``local_path`` to Drive under ``parent_id`` with name
        ``drive_name``. Returns the new Drive file id.

        Uses MediaFileUpload (single-shot for files <5 MB, automatically
        resumable above). Phase 7.1's payloads are tiny (~1 MB total
        across manifest + config + history zip), so this is effectively
        a single-shot upload — but the same primitive will scale up
        cleanly if Phase 7.4 (audio opt-in) lands.
        """
        # Lazy import to keep cold-start light. MediaFileUpload lives in
        # googleapiclient.http, not .discovery.
        from googleapiclient.http import MediaFileUpload

        body = {
            "name": drive_name,
            "parents": [parent_id],
        }
        media = MediaFileUpload(str(local_path), mimetype=mime_type)
        service = self._get_service()
        resp = service.files().create(
            body=body,
            media_body=media,
            fields="id",
        ).execute()
        return resp["id"]
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_gdrive_client.py -v
```

Expected: 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add gdrive/client.py tests/test_gdrive_client.py
git commit -m "$(cat <<'EOF'
feat(gdrive/client): upload_file() via MediaFileUpload

upload_file(local_path, drive_name, parent_id, mime_type) wraps the
local file in googleapiclient.http.MediaFileUpload and calls
files().create with the resulting media body. Returns the new
Drive file id.

Drive API infers content type from MediaFileUpload's mimetype kwarg —
no need to set it in the metadata body (it'd just be redundant).

MediaFileUpload is single-shot for <5 MB, automatically resumable
above. Phase 7.1's payloads are tiny (~1 MB total) so this is
effectively single-shot, but the primitive scales up cleanly for
Phase 7.4 audio opt-in.

Lazy import of MediaFileUpload from googleapiclient.http (not the
.discovery module where build() lives).
EOF
)"
```

---

### Task A.5: PR-A wrap-up

- [ ] **Step 1: Final pytest + lint**

```
pytest -q
python -m ruff check .
```

Expected: 356 baseline + 8 new = 364 green; ruff clean.

- [ ] **Step 2: Push and open PR**

```bash
git push -u origin feat/gdrive-phase-7.1-client
gh pr create --title "feat(gdrive): Phase 7.1 Drive API client wrapper [PR-A]" --body "$(cat <<'EOF'
## Summary

Foundation for Phase 7.1 of the Google Drive backup feature (PR-A of 3).

- New \`gdrive/client.py\` with \`DriveClient\` class exposing 4 methods:
  - \`find_folder(name, parent_id=None)\` → folder id or None
  - \`create_folder(name, parent_id=None)\` → new folder id
  - \`find_or_create_folder(name, parent_id=None)\` → ensure-once primitive
  - \`upload_file(local_path, drive_name, parent_id, mime_type)\` → new file id
- googleapiclient.discovery built lazily on first method call (~30-50 MB import paid only when used).
- 3 MIME constants for the next PR's orchestrator: FOLDER_MIME, JSON_MIME, ZIP_MIME.
- 8 new mock-based tests; no real network.

Pure module — no UI, no orchestration. PR-B composes these into \`gdrive/backup.py\`.

## Codex P1 fix reference

Tests patch \`googleapiclient.discovery.build\` and \`googleapiclient.http.MediaFileUpload\` at their SOURCE modules per the lesson from PR #39 — lazy imports don't bind names as \`gdrive.client\` attributes.

## Test plan

- [x] \`pytest -q\` — 356 baseline + 8 new = **364** green
- [x] \`python -m ruff check .\` — clean
- [x] No UI integration yet — PR-B's orchestrator + PR-C's button come next
EOF
)"
```

- [ ] **Step 3: Wait for review + merge before starting PR-B.** Per `feedback_stacked_pr_squash_merge.md`.

---

## PR-B: `gdrive/backup.py` — orchestrator

**Branch:** `feat/gdrive-phase-7.1-backup-orch` (from `main` after PR-A merges).

**Goal:** Ship `gdrive.backup` with four pure helpers (`redact_config`, `zip_history`, `build_manifest`, `_iso_timestamp`) plus the `run_backup` orchestrator that composes them with `DriveClient`. After PR-B, calling `run_backup(auth, config, history_dir, on_status=...)` from any thread does a complete backup; PR-C wires that call into the Settings dialog button.

**Pre-task:**

```bash
git checkout main && git pull --ff-only origin main
git checkout -b feat/gdrive-phase-7.1-backup-orch
```

---

### Task B.1: Create `gdrive/backup.py` + `redact_config` + first failing test

**Files:**
- Create: `gdrive/backup.py`
- Create: `tests/test_gdrive_backup.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_gdrive_backup.py`:

```python
"""Tests for gdrive.backup — Phase 7.1 backup orchestrator.

Mostly pure stdlib testing (zipfile, tmp_path, dict redaction). The
run_backup orchestrator test mocks DriveClient — no real Drive API.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from unittest.mock import MagicMock, patch

from gdrive.backup import (
    REDACTION_PLACEHOLDER,
    REDACTED_KEYS,
    build_manifest,
    redact_config,
    zip_history,
)


def test_redact_config_replaces_listed_keys_with_placeholder():
    """All keys listed in REDACTED_KEYS must be replaced with
    REDACTION_PLACEHOLDER. Keys absent from the input config are
    silently skipped (not added as new keys)."""
    config = {
        "language": "Авто-определение",
        "openrouter_api_key": "sk-or-real-key-12345",
        "linear_api_key": "lin_api_real",
        "glide_api_key": "real-glide-key",
        "assemblyai_api_key": "asm-real",
        "hf_token": "hf_real_token",
        "cloud_api_keys": {"AssemblyAI": "real", "Deepgram": "real2"},
        "gdrive_account_email": "user@example.com",  # not redacted — it's user-visible
    }
    redacted = redact_config(config)

    # Listed keys replaced.
    assert redacted["openrouter_api_key"] == REDACTION_PLACEHOLDER
    assert redacted["linear_api_key"] == REDACTION_PLACEHOLDER
    assert redacted["glide_api_key"] == REDACTION_PLACEHOLDER
    assert redacted["assemblyai_api_key"] == REDACTION_PLACEHOLDER
    assert redacted["hf_token"] == REDACTION_PLACEHOLDER
    # cloud_api_keys (nested dict of provider→key) — values redacted, keys kept.
    assert redacted["cloud_api_keys"] == {
        "AssemblyAI": REDACTION_PLACEHOLDER,
        "Deepgram": REDACTION_PLACEHOLDER,
    }
    # Non-secret keys untouched.
    assert redacted["language"] == "Авто-определение"
    assert redacted["gdrive_account_email"] == "user@example.com"
    # Input not mutated (defensive — caller might still need it).
    assert config["openrouter_api_key"] == "sk-or-real-key-12345"


def test_redact_config_handles_missing_keys_silently():
    """A config that doesn't have any of the redacted keys returns
    intact (no KeyError, no spurious new keys)."""
    config = {"language": "Русский", "model": "large-v3"}
    redacted = redact_config(config)
    assert redacted == config
    assert redacted is not config, "redact_config must return a copy"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_gdrive_backup.py -v -k redact
```

Expected: 2 FAILs (`ModuleNotFoundError: No module named 'gdrive.backup'`).

- [ ] **Step 3: Create `gdrive/backup.py` with `redact_config`**

Create `gdrive/backup.py`:

```python
"""Backup orchestrator for Phase 7.1.

Composes `gdrive.client.DriveClient` (Drive I/O) with stdlib zipfile
+ hashlib + json (snapshot building) into a single `run_backup`
entry point that the Settings dialog's worker thread calls when the
user clicks "Сделать backup сейчас".

Four pure helpers:
  * redact_config(cfg)        — strip API keys from a config dict
  * zip_history(src_dir, out) — write history/ to a zip, excluding audio
  * build_manifest(...)       — produce the manifest dict
  * _iso_timestamp()          — folder-name-safe ISO 8601 UTC

Plus the orchestrator:
  * run_backup(auth, config, history_dir, on_status=None) → dict

Pure helpers are unit-testable without DriveClient or network. The
orchestrator is mock-tested with a fake DriveClient.

See spec docs/superpowers/specs/2026-04-30-gdrive-backup-design.md
sections "Backup payload structure (Phase 7.1)" and "API key
redaction in config.json".
"""
from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)


# String written in place of every redacted secret. Matches the spec's
# "<REDACTED>" literal so the user (or a future restore) can detect
# fields that need re-entry.
REDACTION_PLACEHOLDER = "<REDACTED>"

# Top-level config keys whose values are stripped before upload. Per
# spec line 117-121 plus cloud_api_keys (nested dict — values get
# replaced one by one, structure preserved) and hf_token (HuggingFace
# token used for pyannote diarization download — also a secret).
REDACTED_KEYS = (
    "openrouter_api_key",
    "linear_api_key",
    "glide_api_key",
    "assemblyai_api_key",
    "hf_token",
)


def redact_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy of ``config`` with all known API keys
    replaced by REDACTION_PLACEHOLDER. Input is never mutated.

    Two redaction shapes:
      * Top-level string values (REDACTED_KEYS list)
      * cloud_api_keys nested dict — keys (provider names) preserved,
        values (the actual API keys) replaced

    Keys absent from the input are silently skipped — no spurious
    new placeholder entries appear in the output.
    """
    out = copy.deepcopy(config)
    for key in REDACTED_KEYS:
        if key in out:
            out[key] = REDACTION_PLACEHOLDER
    cloud_keys = out.get("cloud_api_keys")
    if isinstance(cloud_keys, dict):
        out["cloud_api_keys"] = {k: REDACTION_PLACEHOLDER for k in cloud_keys}
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_gdrive_backup.py -v -k redact
```

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add gdrive/backup.py tests/test_gdrive_backup.py
git commit -m "$(cat <<'EOF'
feat(gdrive/backup): redact_config + module skeleton

First slice of the Phase 7.1 backup orchestrator. redact_config
returns a deep copy of the config dict with every known API key
replaced by the <REDACTED> placeholder, leaving non-secret fields
untouched. Two redaction shapes:

  * Top-level string values: openrouter_api_key, linear_api_key,
    glide_api_key, assemblyai_api_key, hf_token (HuggingFace token
    used for pyannote download — also secret).
  * cloud_api_keys nested dict: provider names preserved, per-provider
    keys replaced. Spec's redaction list (line 117-121) was top-level
    only; we add cloud_api_keys defensively because that's where each
    cloud provider's actual key lives.

Input dict is NEVER mutated — defensive deep-copy. Caller (run_backup
in Task B.5) still needs the live config for the in-memory app.

Two tests: full redaction roundtrip + missing-keys silent skip.
EOF
)"
```

---

### Task B.2: Implement `zip_history()` with audio exclusion

**Files:**
- Modify: `gdrive/backup.py`
- Modify: `tests/test_gdrive_backup.py`

- [ ] **Step 1: Write three failing tests**

Append to `tests/test_gdrive_backup.py`:

```python
# Audio file extensions excluded from the history.zip per spec
# (text-only backup; audio is opt-in for Phase 7.4 which we haven't shipped).
_AUDIO_EXTS = (".wav", ".mp3", ".m4a")


def test_zip_history_includes_text_files(tmp_path):
    """Plain .txt and .json files in history/ must end up in the zip."""
    src = tmp_path / "history"
    src.mkdir()
    (src / "2026-05-23_meeting").mkdir()
    (src / "2026-05-23_meeting" / "transcript.txt").write_text("Привет мир")
    (src / "2026-05-23_meeting" / "diarized.json").write_text('{"speakers": []}')

    out_zip = tmp_path / "history.zip"
    zip_history(src, out_zip)

    with zipfile.ZipFile(out_zip) as zf:
        names = sorted(zf.namelist())
    assert "2026-05-23_meeting/transcript.txt" in names
    assert "2026-05-23_meeting/diarized.json" in names


def test_zip_history_excludes_audio_files(tmp_path):
    """*.wav, *.mp3, *.m4a are stripped (spec — text-only backup).
    Verified by creating fake binary files with audio extensions
    alongside transcripts."""
    src = tmp_path / "history"
    src.mkdir()
    folder = src / "2026-05-23_meeting"
    folder.mkdir()
    (folder / "transcript.txt").write_text("text content")
    (folder / "original.wav").write_bytes(b"fake-wav-binary")
    (folder / "original.mp3").write_bytes(b"fake-mp3-binary")
    (folder / "alt.m4a").write_bytes(b"fake-m4a-binary")

    out_zip = tmp_path / "history.zip"
    zip_history(src, out_zip)

    with zipfile.ZipFile(out_zip) as zf:
        names = zf.namelist()
    assert "2026-05-23_meeting/transcript.txt" in names
    assert not any(name.endswith(_AUDIO_EXTS) for name in names), (
        f"Audio files leaked: {[n for n in names if n.endswith(_AUDIO_EXTS)]}"
    )


def test_zip_history_empty_directory_produces_empty_archive(tmp_path):
    """An empty history/ folder must produce a valid (but empty) zip,
    not crash. Edge case: first-run user clicks Сделать backup before
    transcribing anything."""
    src = tmp_path / "history"
    src.mkdir()

    out_zip = tmp_path / "history.zip"
    zip_history(src, out_zip)

    assert out_zip.exists()
    with zipfile.ZipFile(out_zip) as zf:
        assert zf.namelist() == []
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_gdrive_backup.py -v -k zip_history
```

Expected: 3 FAILs (`ImportError: cannot import name 'zip_history' from 'gdrive.backup'`).

- [ ] **Step 3: Implement `zip_history`**

Add to `gdrive/backup.py` (after `redact_config`):

```python
# Audio file extensions excluded from the history.zip — text-only
# backup is the spec's default; audio opt-in is a Phase 7.4 follow-up.
AUDIO_EXTS = (".wav", ".mp3", ".m4a")


def zip_history(src_dir, out_zip) -> None:
    """Zip the contents of ``src_dir`` into ``out_zip``, with two rules:

      * Audio files (AUDIO_EXTS) are SKIPPED — they're typically 50-100
        MB per meeting and the Free Drive tier is 15 GB. Text-only is
        the spec's chosen scope.
      * Relative paths inside the zip are rooted at ``src_dir`` (so a
        file at ``history/2026-05-23_meeting/transcript.txt`` lands in
        the zip as ``2026-05-23_meeting/transcript.txt``).

    Empty source directory produces a valid empty zip (not an error).
    Existing out_zip is overwritten.

    src_dir and out_zip accept str or pathlib.Path.
    """
    # Import zipfile/pathlib lazily — both are stdlib and cheap, but
    # keeping the module-top imports minimal helps grep-ability.
    import zipfile
    from pathlib import Path

    src = Path(src_dir)
    out = Path(out_zip)

    # ZIP_DEFLATED gives ~70% compression on transcript JSON/TXT; small
    # enough payloads that compresslevel default (6) is the right pick
    # — going to 9 saves <1% and costs noticeable CPU.
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src.rglob("*")):
            if path.is_dir():
                continue
            if path.suffix.lower() in AUDIO_EXTS:
                continue
            arcname = path.relative_to(src).as_posix()
            zf.write(path, arcname=arcname)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_gdrive_backup.py -v -k zip_history
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add gdrive/backup.py tests/test_gdrive_backup.py
git commit -m "$(cat <<'EOF'
feat(gdrive/backup): zip_history with audio exclusion

zip_history(src_dir, out_zip) recursively walks src_dir and writes
every non-audio file to a ZIP_DEFLATED archive. Relative paths inside
the zip are rooted at src_dir so the layout mirrors history/'s
structure.

Audio files (.wav/.mp3/.m4a) are dropped — spec scope is text-only
backup. A typical meeting's original audio is 50-100 MB; including
them would blow through the Free Drive tier in days. Phase 7.4 will
add an opt-in audio toggle.

Empty source dir → valid empty zip (first-run UX: user clicks
Сделать backup before transcribing anything → no crash).

Three tests cover: text files included, audio files excluded,
empty source directory.

ZIP_DEFLATED default compresslevel (6) chosen over 9 — ~70%
compression on JSON/TXT transcripts, going to 9 saves <1% for
noticeable CPU cost.
EOF
)"
```

---

### Task B.3: Implement `build_manifest()` + `_iso_timestamp()`

**Files:**
- Modify: `gdrive/backup.py`
- Modify: `tests/test_gdrive_backup.py`

- [ ] **Step 1: Write three failing tests**

Append to `tests/test_gdrive_backup.py`:

```python
def test_iso_timestamp_format_matches_spec(monkeypatch):
    """_iso_timestamp returns the folder-name-safe ISO 8601 used in
    the spec's example (`2026-04-30T12-30-00`). The two : separators
    between hours/minutes/seconds are replaced with `-` because Drive
    folder names tolerate them but Windows paths don't (matters for
    restore flow's local extraction in Phase 7.2)."""
    from gdrive.backup import _iso_timestamp
    import datetime as dt

    class _FakeDateTime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 5, 23, 22, 30, 45, tzinfo=tz)

    monkeypatch.setattr("gdrive.backup.datetime", _FakeDateTime)
    assert _iso_timestamp() == "2026-05-23T22-30-45"


def test_build_manifest_computes_sha256_and_size_for_each_file(tmp_path):
    """build_manifest computes SHA-256 + byte-size for each file in
    the files dict, plus carries through the structural fields
    (version, created_at, app_version, host, transcripts_count,
    audio_included)."""
    config_file = tmp_path / "config.json"
    config_file.write_bytes(b'{"language": "ru"}')   # 18 bytes
    history_zip = tmp_path / "history.zip"
    history_zip.write_bytes(b"PK\x03\x04" + b"\x00" * 100)  # 104 bytes

    expected_config_sha = hashlib.sha256(b'{"language": "ru"}').hexdigest()
    expected_zip_sha = hashlib.sha256(b"PK\x03\x04" + b"\x00" * 100).hexdigest()

    manifest = build_manifest(
        files={"config.json": config_file, "history.zip": history_zip},
        transcripts_count=42,
        app_version="phase-7.1",
        host="TEST-HOST",
        created_at="2026-05-23T22-30-45",
    )

    assert manifest["version"] == 1
    assert manifest["created_at"] == "2026-05-23T22-30-45"
    assert manifest["app_version"] == "phase-7.1"
    assert manifest["host"] == "TEST-HOST"
    assert manifest["transcripts_count"] == 42
    assert manifest["audio_included"] is False
    assert manifest["files"] == {
        "config.json": {"size": 18, "sha256": expected_config_sha},
        "history.zip": {"size": 104, "sha256": expected_zip_sha},
    }


def test_build_manifest_serializable_to_json(tmp_path):
    """The returned dict must round-trip through json.dumps/loads with
    no special encoders. Smoke for "did I use a Path object where I
    should have str'd it" kinds of bugs."""
    config_file = tmp_path / "config.json"
    config_file.write_text("{}")
    history_zip = tmp_path / "history.zip"
    history_zip.write_bytes(b"PK")

    manifest = build_manifest(
        files={"config.json": config_file, "history.zip": history_zip},
        transcripts_count=0,
        app_version="phase-7.1",
        host="HOST",
        created_at="2026-05-23T22-30-45",
    )

    serialised = json.dumps(manifest)
    assert json.loads(serialised) == manifest
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_gdrive_backup.py -v -k "iso_timestamp or build_manifest"
```

Expected: 3 FAILs (`ImportError: cannot import name '_iso_timestamp'` / `'build_manifest'`).

- [ ] **Step 3: Implement `_iso_timestamp` and `build_manifest`**

Add to `gdrive/backup.py` (after `zip_history`):

```python
# stdlib `datetime` is monkeypatched by test_iso_timestamp_format_matches_spec
# via `gdrive.backup.datetime` — import the module (not just the class) so
# the patch surface is the binding the tests target.
from datetime import datetime, timezone


MANIFEST_VERSION = 1


def _iso_timestamp() -> str:
    """Current UTC time formatted as the spec's folder-name (line 86):
    ``2026-04-30T12-30-00``. The two ``:`` separators inside the time
    portion are replaced with ``-`` for Windows-filename safety (the
    folder is created in Drive but the same string appears in local
    paths during Phase 7.2 restore extraction).
    """
    now = datetime.now(timezone.utc)
    # isoformat() with timespec='seconds' → '2026-04-30T12:30:00+00:00'
    # We want '2026-04-30T12-30-00' — strip tz, replace colons.
    raw = now.strftime("%Y-%m-%dT%H:%M:%S")
    return raw.replace(":", "-")


def build_manifest(
    *,
    files: dict[str, "Path | str"],   # forward-ref string; Path imported in zip_history
    transcripts_count: int,
    app_version: str,
    host: str,
    created_at: str,
    audio_included: bool = False,
) -> dict[str, Any]:
    """Build the manifest dict that ships alongside the payload files.

    Schema per spec line 94-108. SHA-256 + byte-size are computed
    per file by streaming (chunked reads — works for arbitrarily
    large payloads, though Phase 7.1's are tiny).

    audio_included defaults to False (text-only is Phase 7.1's scope);
    Phase 7.4's audio opt-in passes True.
    """
    import hashlib
    from pathlib import Path

    files_meta = {}
    for arcname, local in files.items():
        path = Path(local)
        sha = hashlib.sha256()
        size = 0
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(64 * 1024), b""):
                sha.update(chunk)
                size += len(chunk)
        files_meta[arcname] = {"size": size, "sha256": sha.hexdigest()}

    return {
        "version": MANIFEST_VERSION,
        "created_at": created_at,
        "app_version": app_version,
        "host": host,
        "files": files_meta,
        "transcripts_count": transcripts_count,
        "audio_included": audio_included,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_gdrive_backup.py -v -k "iso_timestamp or build_manifest"
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add gdrive/backup.py tests/test_gdrive_backup.py
git commit -m "$(cat <<'EOF'
feat(gdrive/backup): _iso_timestamp() + build_manifest()

_iso_timestamp() returns UTC time as YYYY-MM-DDTHH-MM-SS — matches
the spec example folder name (line 86). Colons in the time portion
are replaced with hyphens because Windows filename validation rejects
them, and the same string lands in local paths during Phase 7.2's
restore extraction.

build_manifest(files, transcripts_count, app_version, host,
created_at) returns the manifest dict per the schema at spec line
94-108. Per-file size + SHA-256 are computed by chunked-streaming
the file (64 KiB chunks) so the implementation scales when Phase 7.4
adds large audio.zip payloads.

audio_included defaults to False — text-only is Phase 7.1's scope.

datetime is imported at module top so test_iso_timestamp_format_
matches_spec can monkeypatch `gdrive.backup.datetime` and freeze the
clock. hashlib + pathlib are lazy inside build_manifest — only paid
when an actual backup runs.

Three tests: timestamp format pinning, full manifest round-trip with
size/sha verification, JSON-serialisability smoke (catches accidental
non-stringified Path objects).
EOF
)"
```

---

### Task B.4: Implement `run_backup()` orchestrator

**Files:**
- Modify: `gdrive/backup.py`
- Modify: `tests/test_gdrive_backup.py`

The orchestrator composes everything. Its signature is the one
PR-C's Settings dialog worker will call.

- [ ] **Step 1: Write two failing tests**

Append to `tests/test_gdrive_backup.py`:

```python
def test_run_backup_calls_client_in_correct_order(tmp_path):
    """run_backup must call DriveClient in this order:
      1. find_or_create_folder("audio-transcriber-backup")  → root_id
      2. create_folder(<iso-timestamp>, parent_id=root_id)  → snap_id
      3. upload_file(manifest.json, ..., parent_id=snap_id) → manifest_id
      4. upload_file(config.json,   ..., parent_id=snap_id) → config_id
      5. upload_file(history.zip,   ..., parent_id=snap_id) → zip_id

    Returns a dict with root_id + snapshot_id + uploaded file ids."""
    from gdrive.backup import run_backup

    # Set up a real on-disk history dir + config so zip_history and
    # build_manifest do real work (lighter-weight than mocking them).
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "meeting").mkdir()
    (history_dir / "meeting" / "transcript.txt").write_text("hello")

    config = {"language": "ru", "openrouter_api_key": "secret"}

    # Mock the auth + client.
    fake_auth = MagicMock()
    fake_auth.ensure_valid_credentials.return_value = None
    fake_auth.get_credentials.return_value = MagicMock()

    fake_client = MagicMock()
    fake_client.find_or_create_folder.return_value = "root-folder-id"
    fake_client.create_folder.return_value = "snapshot-folder-id"
    fake_client.upload_file.side_effect = ["manifest-id", "config-id", "zip-id"]

    with patch("gdrive.backup.DriveClient", return_value=fake_client), \
         patch("gdrive.backup._iso_timestamp", return_value="2026-05-23T22-30-45"):
        result = run_backup(
            auth=fake_auth,
            config=config,
            history_dir=history_dir,
            work_dir=tmp_path / "work",
        )

    # ensure_valid_credentials was called before any Drive op.
    fake_auth.ensure_valid_credentials.assert_called_once()
    fake_auth.get_credentials.assert_called_once()

    # Folder creation in the right order.
    fake_client.find_or_create_folder.assert_called_once_with("audio-transcriber-backup")
    fake_client.create_folder.assert_called_once_with(
        "2026-05-23T22-30-45", parent_id="root-folder-id",
    )

    # 3 uploads to the snapshot folder.
    assert fake_client.upload_file.call_count == 3
    upload_names = [c.kwargs["drive_name"] for c in fake_client.upload_file.call_args_list]
    assert upload_names == ["manifest.json", "config.json", "history.zip"]
    for call in fake_client.upload_file.call_args_list:
        assert call.kwargs["parent_id"] == "snapshot-folder-id"

    # Result dict shape.
    assert result == {
        "root_folder_id": "root-folder-id",
        "snapshot_folder_id": "snapshot-folder-id",
        "snapshot_name": "2026-05-23T22-30-45",
        "uploaded": {
            "manifest.json": "manifest-id",
            "config.json": "config-id",
            "history.zip": "zip-id",
        },
    }


def test_run_backup_redacts_uploaded_config_not_local(tmp_path):
    """The config.json uploaded to Drive has API keys REDACTED, but
    the in-memory `config` dict passed to run_backup is unchanged
    (the app keeps using its real keys for normal operation)."""
    from gdrive.backup import run_backup

    history_dir = tmp_path / "history"
    history_dir.mkdir()

    config = {
        "language": "ru",
        "openrouter_api_key": "real-secret",
        "cloud_api_keys": {"AssemblyAI": "real-asm-key"},
    }
    # Snapshot the dict BEFORE call to compare after.
    config_before = copy.deepcopy(config)

    fake_auth = MagicMock()
    fake_auth.get_credentials.return_value = MagicMock()
    fake_client = MagicMock()
    fake_client.find_or_create_folder.return_value = "root"
    fake_client.create_folder.return_value = "snap"

    uploaded_paths = []
    def capture_upload(*, local_path, **_):
        uploaded_paths.append(str(local_path))
        return "fake-id"
    fake_client.upload_file.side_effect = capture_upload

    work_dir = tmp_path / "work"
    with patch("gdrive.backup.DriveClient", return_value=fake_client), \
         patch("gdrive.backup._iso_timestamp", return_value="2026-05-23T22-30-45"):
        run_backup(auth=fake_auth, config=config, history_dir=history_dir, work_dir=work_dir)

    # Local config unmodified.
    assert config == config_before

    # Find the uploaded config.json on disk and verify keys are <REDACTED>.
    uploaded_config_path = next(p for p in uploaded_paths if p.endswith("config.json"))
    on_disk = json.loads(open(uploaded_config_path, encoding="utf-8").read())
    assert on_disk["openrouter_api_key"] == REDACTION_PLACEHOLDER
    assert on_disk["cloud_api_keys"] == {"AssemblyAI": REDACTION_PLACEHOLDER}
    assert on_disk["language"] == "ru"


import copy   # used in the test above; safe to add at top of test file too
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_gdrive_backup.py -v -k run_backup
```

Expected: 2 FAILs (`ImportError: cannot import name 'run_backup'`).

- [ ] **Step 3: Implement `run_backup`**

Add to `gdrive/backup.py` (after `build_manifest`):

```python
# DriveClient is imported lazily inside run_backup so importing
# `gdrive.backup` from anywhere (e.g. Settings dialog at import time)
# doesn't drag in googleapiclient. The test fixture patches
# `gdrive.backup.DriveClient` — that name binding is created by the
# `from .client import DriveClient` line INSIDE run_backup, which
# happens at first call. To make the patch work, we declare the
# binding at module scope via the lazy-loader trick: `DriveClient`
# is a sentinel module-level None; run_backup overwrites it on first
# entry. Tests `patch("gdrive.backup.DriveClient", ...)` after the
# first import-time pass — they intercept the SAME module attribute.
DriveClient = None   # populated lazily on first run_backup() call


def run_backup(
    *,
    auth,
    config: dict[str, Any],
    history_dir,
    work_dir,
    app_version: str = "phase-7.1",
    on_status: "callable | None" = None,
) -> dict[str, Any]:
    """Run a complete backup: zip history, redact config, upload all
    three payload files to a fresh timestamped folder on Drive.

    Args:
        auth: `gdrive.auth.GDriveAuth` instance (signed in).
        config: in-memory app config dict — NOT mutated.
        history_dir: pathlib.Path or str — the local history/ folder.
        work_dir: temp scratch dir for staging files. Created if
            missing. Caller is responsible for cleanup (tempfile.
            mkdtemp + shutil.rmtree on success, leave on failure for
            debug).
        app_version: free-form version string written to manifest.
        on_status: optional callable(str) for progress updates. Called
            with Russian-language phase strings like
            "Создаю архив истории...", "Загружаю manifest.json...",
            etc. Settings dialog's worker uses this to update the
            status badge.

    Returns:
        Dict with root_folder_id, snapshot_folder_id, snapshot_name,
        and uploaded (mapping arcname → Drive file id). Caller
        persists root_folder_id to config so subsequent backups
        skip the find/create-top-folder dance.

    Raises:
        Any googleapiclient error (network, auth, quota) propagates
        unchanged. RefreshError specifically: ensure_valid_credentials
        re-raises it after sign_out, so the caller's status badge
        can prompt re-login.
    """
    import shutil
    import socket
    from pathlib import Path

    # Lazy import — see module-scope DriveClient sentinel comment.
    global DriveClient
    if DriveClient is None:
        from .client import DriveClient as _DriveClient
        DriveClient = _DriveClient

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    history_path = Path(history_dir)

    def _say(msg: str) -> None:
        logger.info("backup: %s", msg)
        if on_status is not None:
            try:
                on_status(msg)
            except Exception:
                # on_status is a UI callback; we never let it crash
                # the backup. The status label not updating is a
                # cosmetic issue, not a data-integrity one.
                logger.exception("on_status callback failed (ignored)")

    # 1. Validate auth — surfaces RefreshError early so we don't waste
    #    time zipping if the user has revoked access in Google account
    #    settings.
    _say("Проверяю авторизацию Google Drive...")
    auth.ensure_valid_credentials()
    credentials = auth.get_credentials()

    # 2. Stage history.zip
    _say("Создаю архив истории...")
    history_zip = work / "history.zip"
    zip_history(history_path, history_zip)

    # 3. Stage redacted config.json
    _say("Готовлю конфиг (API ключи удалены)...")
    import json
    redacted_cfg = redact_config(config)
    config_path = work / "config.json"
    config_path.write_text(json.dumps(redacted_cfg, indent=2, ensure_ascii=False))

    # 4. Build + stage manifest.json
    _say("Считаю контрольные суммы...")
    snapshot_name = _iso_timestamp()
    manifest = build_manifest(
        files={
            "config.json": config_path,
            "history.zip": history_zip,
        },
        transcripts_count=_count_history_subdirs(history_path),
        app_version=app_version,
        host=socket.gethostname(),
        created_at=snapshot_name,
        audio_included=False,
    )
    manifest_path = work / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    # 5. Drive: find/create root + create snapshot folder
    client = DriveClient(credentials)
    _say("Подключаюсь к Google Drive...")
    root_id = client.find_or_create_folder("audio-transcriber-backup")
    _say(f"Создаю snapshot {snapshot_name}...")
    snapshot_id = client.create_folder(snapshot_name, parent_id=root_id)

    # 6. Upload three files in deterministic order. Manifest first so
    #    a partial-failure observer can see what should have been
    #    uploaded (Phase 7.2 restore reads manifest.json first).
    uploaded = {}
    # Imports local to keep module-top minimal.
    from .client import JSON_MIME, ZIP_MIME

    for arcname, local, mime in (
        ("manifest.json", manifest_path, JSON_MIME),
        ("config.json", config_path, JSON_MIME),
        ("history.zip", history_zip, ZIP_MIME),
    ):
        _say(f"Загружаю {arcname}...")
        file_id = client.upload_file(
            local_path=local,
            drive_name=arcname,
            parent_id=snapshot_id,
            mime_type=mime,
        )
        uploaded[arcname] = file_id

    _say("✓ Backup готов")

    # 7. Cleanup work dir on success (failure path leaves it for debug).
    try:
        shutil.rmtree(work)
    except OSError as e:
        logger.warning("Could not clean up work dir %s: %s", work, e)

    return {
        "root_folder_id": root_id,
        "snapshot_folder_id": snapshot_id,
        "snapshot_name": snapshot_name,
        "uploaded": uploaded,
    }


def _count_history_subdirs(history_dir) -> int:
    """Count immediate subdirectories of history/ — each one is a
    transcribed meeting. Used for the manifest's transcripts_count
    field (informational; restore UI shows it before downloading)."""
    from pathlib import Path
    p = Path(history_dir)
    if not p.exists():
        return 0
    return sum(1 for child in p.iterdir() if child.is_dir())
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_gdrive_backup.py -v
```

Expected: 10 tests PASS (2 redact + 3 zip + 3 manifest + 2 run_backup = 10).

If the run_backup tests fail with `AttributeError: module 'gdrive.backup' has no attribute 'DriveClient'`, the lazy-loader sentinel didn't get assigned at module-import time. Verify the line `DriveClient = None` is at module scope (not inside a function).

- [ ] **Step 5: Commit**

```bash
git add gdrive/backup.py tests/test_gdrive_backup.py
git commit -m "$(cat <<'EOF'
feat(gdrive/backup): run_backup() orchestrator + helpers

run_backup is the single entry point Phase 7.1's Settings dialog
worker will call. Composes:
  1. auth.ensure_valid_credentials() — surfaces RefreshError early
  2. zip_history(history_dir, work/history.zip) — text-only archive
  3. redact_config(config) + write to work/config.json — keys stripped
  4. build_manifest(...) — size + sha256 + transcripts_count + host
  5. DriveClient.find_or_create_folder("audio-transcriber-backup")
  6. DriveClient.create_folder(<iso-ts>, parent_id=root)
  7. upload_file × 3 in order: manifest.json, config.json, history.zip
  8. shutil.rmtree(work_dir) on success — leave on failure for debug

DriveClient is imported lazily via a module-scope sentinel pattern
(DriveClient = None at module top; populated on first run_backup
call). This makes `from gdrive.backup import run_backup` cheap (no
googleapiclient drag) AND keeps `patch("gdrive.backup.DriveClient",
...)` as a clean test surface — the patch overrides the sentinel
that run_backup's `global DriveClient` declaration references.

on_status callback: optional callable(str) for Russian-language
progress updates ("Создаю архив истории...", "Загружаю manifest.
json...", etc). Failures inside on_status are caught and logged —
UI callback breaking the backup is never the right trade-off.

_count_history_subdirs sets manifest.transcripts_count; helper
because Phase 7.2 restore UI displays the value alongside snapshot
metadata.

Two new orchestrator tests: call-order verification (find_or_create
+ create + 3 uploads with the right names/parent), and a redaction
roundtrip (uploaded config.json on disk has <REDACTED> placeholders;
in-memory config dict untouched).
EOF
)"
```

---

### Task B.5: PR-B wrap-up

- [ ] **Step 1: Final pytest + lint**

```
pytest -q
python -m ruff check .
```

Expected: 364 (from PR-A) + 10 new = 374 green; ruff clean.

- [ ] **Step 2: Push and open PR**

```bash
git push -u origin feat/gdrive-phase-7.1-backup-orch
gh pr create --title "feat(gdrive): Phase 7.1 backup orchestrator [PR-B]" --body "$(cat <<'EOF'
## Summary

Orchestrator step for Phase 7.1 (PR-B of 3).

- New \`gdrive/backup.py\` with four pure helpers + one orchestrator:
  - \`redact_config(cfg)\` — strip API keys (top-level list + cloud_api_keys nested values), input never mutated
  - \`zip_history(src, out)\` — ZIP_DEFLATED archive excluding *.wav/*.mp3/*.m4a
  - \`build_manifest(files, ...)\` — schema per spec line 94-108 with chunked SHA-256
  - \`_iso_timestamp()\` — UTC, colons replaced with hyphens (Windows path safety)
  - \`run_backup(auth, config, history_dir, work_dir, on_status=None)\` — composes everything
- 10 new tests (2 redaction + 3 zip + 3 manifest + 2 orchestrator).
- \`DriveClient\` is module-lazy-loaded via a sentinel pattern so \`from gdrive.backup import run_backup\` stays cheap and \`patch("gdrive.backup.DriveClient", ...)\` remains a clean test surface.

Pure module + tests — no UI integration. PR-C wires the Settings dialog button to \`run_backup()\`.

## Test plan

- [x] \`pytest -q\` — 364 (PR-A) + 10 new = **374** green
- [x] \`python -m ruff check .\` — clean
- [x] redact_config never mutates input (verified by deep-copy roundtrip in test_run_backup_redacts_uploaded_config_not_local)
- [x] Manual smoke deferred to PR-C (no button to click yet)
EOF
)"
```

- [ ] **Step 3: Wait for review + merge before starting PR-C.**

---

## PR-C: Settings UI integration + config key + CLAUDE.md update

**Branch:** `feat/gdrive-phase-7.1-ui` (from `main` after PR-B merges).

**Goal:** Add "Сделать backup сейчас" button to the existing Settings → Google Drive section, wire it to `gdrive.backup.run_backup` via a worker thread with status feedback. Persist `gdrive_root_folder_id` + `gdrive_last_backup` on success. Update CLAUDE.md to mark Phase 7.1 shipped.

**Pre-task:**

```bash
git checkout main && git pull --ff-only origin main
git checkout -b feat/gdrive-phase-7.1-ui
```

---

### Task C.1: Add `gdrive_root_folder_id` to config.example.json

**Files:**
- Modify: `config.example.json`

`gdrive_last_backup` already landed in 7.0 PR-B. We just need the new `gdrive_root_folder_id` (cached after the first successful backup so subsequent backups skip the find_or_create-top-folder Drive round-trip).

- [ ] **Step 1: Add the new key**

Open `config.example.json`. Find the line `"gdrive_backup_frequency": "off",` (added in 7.0 PR-B). Add a new line immediately after it:

```json
"gdrive_root_folder_id": "",
```

The full GDrive group should now read:

```json
"gdrive_enabled": false,
"gdrive_account_email": "",
"gdrive_last_backup": "",
"gdrive_backup_frequency": "off",
"gdrive_root_folder_id": "",
```

- [ ] **Step 2: Verify JSON parses**

```
python -c "import json; json.load(open('config.example.json')); print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add config.example.json
git commit -m "$(cat <<'EOF'
feat(config): add gdrive_root_folder_id for Phase 7.1

New key cached after the first successful backup — stores the Drive
file id of the audio-transcriber-backup top folder. Lets subsequent
backups skip the find_or_create_folder round-trip (one less API call
per backup). Empty default; populated by gdrive.backup.run_backup's
return value, persisted by SettingsMixin._on_gdrive_backup_succeeded
in C.3.
EOF
)"
```

---

### Task C.2: Add `_on_gdrive_backup_succeeded` to SettingsMixin

**Files:**
- Modify: `ui/app/settings_mixin.py`

The mixin already owns `_on_gdrive_signed_in` / `_on_gdrive_signed_out` (Phase 7.0). Adding the parallel success callback here keeps persistence concerns out of the dialog.

- [ ] **Step 1: Add the method**

In `ui/app/settings_mixin.py`, find the existing `_on_gdrive_signed_out` method (added in Phase 7.0). Add this method immediately after it:

```python
    def _on_gdrive_backup_succeeded(
        self,
        *,
        root_folder_id: str,
        snapshot_name: str,
    ) -> None:
        """Called from the Settings dialog after a successful backup.

        Persists two config keys:
          * gdrive_root_folder_id — cached so the NEXT backup skips
            the find_or_create_folder round-trip
          * gdrive_last_backup — ISO snapshot name, used by the
            Phase 7.3 scheduler's "is overdue?" check
        """
        self._config["gdrive_root_folder_id"] = root_folder_id
        self._config["gdrive_last_backup"] = snapshot_name
        save_config(self._config)
```

- [ ] **Step 2: Smoke import**

```
python -c "from ui.app.settings_mixin import SettingsMixin; assert hasattr(SettingsMixin, '_on_gdrive_backup_succeeded'); print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add ui/app/settings_mixin.py
git commit -m "$(cat <<'EOF'
feat(ui/app/settings_mixin): _on_gdrive_backup_succeeded callback

Parallel to the existing _on_gdrive_signed_in/out from Phase 7.0.
Persists two config keys after a successful backup:

  * gdrive_root_folder_id — cached top-folder Drive id; next backup
    skips the find_or_create_folder round-trip
  * gdrive_last_backup — ISO snapshot name; Phase 7.3 scheduler
    reads it to decide if a backup is overdue

Kwargs-only signature so the Settings dialog's worker callback
can't accidentally pass them in the wrong order.
EOF
)"
```

---

### Task C.3: Add "Сделать backup" button + handler in settings.py

**Files:**
- Modify: `ui/dialogs/settings.py`

Extends the existing `_build_gdrive_section` from Phase 7.0 with one more row, plus three new methods (`_handle_gdrive_backup_now`, `_on_gdrive_backup_success`, `_on_gdrive_backup_failure`). Worker-thread pattern mirrors `_handle_gdrive_signin`.

- [ ] **Step 1: Locate the existing GDrive section**

```
grep -n "_build_gdrive_section\|_handle_gdrive_signin\|_handle_gdrive_signout" ui/dialogs/settings.py
```

Confirm `_build_gdrive_section` exists (added in 7.0 PR-B). We'll modify it + append new methods at the file's end (where the sign-in handlers already live).

- [ ] **Step 2: Add the backup button to `_build_gdrive_section`**

Find the section method. After the existing Войти/Выйти row (uses `row=1`), append a third row (`row=2`) for the backup button + status:

Replace the end of `_build_gdrive_section` (the part starting with `# Initial button enabled-state...`) with:

```python
        self._gdrive_signout_btn.grid(row=1, column=2, padx=(4, 4), pady=6, sticky="e")

        # Backup-now row (Phase 7.1) — button + status label. Status is
        # local (not bound to a parent Var) because backup status is a
        # transient dialog-only concern; persistence of
        # gdrive_last_backup happens on success via the mixin callback.
        self._gdrive_backup_btn = tonal_button(
            section, text="Сделать backup сейчас",
            command=self._handle_gdrive_backup_now, width=200,
        )
        self._gdrive_backup_btn.grid(
            row=2, column=0, columnspan=2, padx=4, pady=6, sticky="w",
        )
        self._gdrive_backup_status = label(section, "", anchor="w")
        self._gdrive_backup_status.grid(
            row=2, column=2, padx=(8, 4), pady=6, sticky="ew",
        )

        # Initial button enabled-state reflects current sign-in state.
        self._refresh_gdrive_button_state()
```

Then extend `_refresh_gdrive_button_state` (also already exists from 7.0) to also gate the backup button on sign-in state. Find the existing method and replace its body:

```python
    def _refresh_gdrive_button_state(self) -> None:
        """Войти is enabled iff not signed in; Выйти + Сделать backup
        iff signed in. Called after every state change so the UI
        matches the GDriveAuth state."""
        if self._parent._gdrive_auth.is_signed_in():
            self._gdrive_signin_btn.configure(state="disabled")
            self._gdrive_signout_btn.configure(state="normal")
            self._gdrive_backup_btn.configure(state="normal")
        else:
            self._gdrive_signin_btn.configure(state="normal")
            self._gdrive_signout_btn.configure(state="disabled")
            self._gdrive_backup_btn.configure(state="disabled")
```

- [ ] **Step 3: Add the three backup handler methods at end of file**

Find the end of the `SettingsDialog` class (after `_handle_gdrive_signout` from 7.0). Append:

```python
    # ── Phase 7.1: Сделать backup сейчас ──────────────────────────────

    def _handle_gdrive_backup_now(self) -> None:
        """Сделать backup clicked — spawn a worker that runs
        gdrive.backup.run_backup. Disable button immediately so a
        double-click can't trigger two parallel backups (Drive's
        find_or_create_folder isn't atomic — concurrent runs could
        create duplicate top folders)."""
        self._gdrive_backup_btn.configure(
            state="disabled", text="Backup в процессе...",
        )
        self._gdrive_backup_status.configure(
            text="Запускаю...", text_color=TEXT_SECONDARY,
        )

        def worker():
            try:
                # Lazy imports — keep dialog construction independent
                # of gdrive.backup's googleapiclient import chain.
                import tempfile
                from gdrive.backup import run_backup

                # Status callback marshals each status string back to
                # the Tk main thread (CTk widgets are not thread-safe).
                def _status(msg: str) -> None:
                    self.after(0, self._gdrive_backup_status.configure, {
                        "text": msg, "text_color": TEXT_SECONDARY,
                    })

                work_dir = tempfile.mkdtemp(prefix="gdrive-backup-")
                result = run_backup(
                    auth=self._parent._gdrive_auth,
                    config=self._parent._config,
                    history_dir="history",
                    work_dir=work_dir,
                    on_status=_status,
                )
                self.after(0, lambda: self._on_gdrive_backup_success(result))
            except Exception as e:   # network, quota, RefreshError, disk full — all surface here
                _logger.exception("GDrive backup failed: %s", e)
                error_msg = str(e)   # hoist before lambda (Python except-scope rule)
                self.after(0, lambda: self._on_gdrive_backup_failure(error_msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_gdrive_backup_success(self, result: dict) -> None:
        """Worker → main thread: persist new config keys + show ✓ message
        + re-enable button."""
        self._parent._on_gdrive_backup_succeeded(
            root_folder_id=result["root_folder_id"],
            snapshot_name=result["snapshot_name"],
        )
        n_files = len(result.get("uploaded", {}))
        self._gdrive_backup_status.configure(
            text=f"✓ Готово ({n_files} файла, snapshot {result['snapshot_name']})",
            text_color=GREEN,
        )
        self._gdrive_backup_btn.configure(
            state="normal", text="Сделать backup сейчас",
        )

    def _on_gdrive_backup_failure(self, error_msg: str) -> None:
        """Worker → main thread: surface error in status + re-enable
        button. Truncate to 100 chars so a long Drive error message
        doesn't break dialog layout."""
        self._gdrive_backup_status.configure(
            text=f"✗ {error_msg[:100]}", text_color=RED,
        )
        self._gdrive_backup_btn.configure(
            state="normal", text="Сделать backup сейчас",
        )
        # Refresh sign-in state — RefreshError inside run_backup
        # triggers ensure_valid_credentials → sign_out, so the button
        # states need to flip back to "not signed in".
        self._refresh_gdrive_button_state()
```

- [ ] **Step 4: Sanity-check imports + syntax**

```
python -c "import ui.app; from ui.dialogs.settings import SettingsDialog; assert hasattr(SettingsDialog, '_handle_gdrive_backup_now'); print('ok')"
```

Expected: `ok`. If `NameError: name 'TEXT_SECONDARY' is not defined` — it's already imported in 7.0's settings.py (used by _validate_openrouter). If `NameError: name 'GREEN'` — same, used by existing validate methods. If `NameError: name 'RED'` — same. All three should already be in the import block at the top of settings.py.

- [ ] **Step 5: Commit**

```bash
git add ui/dialogs/settings.py
git commit -m "$(cat <<'EOF'
feat(ui/settings): "Сделать backup сейчас" button (Phase 7.1)

Extends the existing Google Drive section (Phase 7.0) with a third
row: a tonal button + status label. Button is enabled iff signed in
(_refresh_gdrive_button_state extended to gate it). Click spawns a
daemon thread that calls gdrive.backup.run_backup with a status
callback that marshals each Russian progress string back to the Tk
main thread via self.after(0, ...).

On success: SettingsMixin._on_gdrive_backup_succeeded persists
gdrive_root_folder_id + gdrive_last_backup; status shows "✓ Готово
(N файла, snapshot <iso>)" in GREEN.

On failure: status shows "✗ <truncated error>" in RED; button
re-enabled; _refresh_gdrive_button_state runs because a RefreshError
inside the backup will have signed the user out via
ensure_valid_credentials.

Worker exception scoping: str(e) hoisted to a plain local
`error_msg` BEFORE the lambda captures it — Python's del-on-
except-exit rule would NameError otherwise (same pattern as
_handle_gdrive_signin in 7.0).

Threading: tempfile.mkdtemp(prefix="gdrive-backup-") for the scratch
work dir; run_backup's shutil.rmtree cleans up on success, leaves
on failure for debug per the orchestrator's contract.
EOF
)"
```

---

### Task C.4: Extend `test_settings_gdrive.py` with backup-button assertions

**Files:**
- Modify: `tests/test_settings_gdrive.py`

Same pure-source-text pattern from 7.0 PR-B (avoids `ui.app` import on Linux CI per `test_ui_constants.py` docstring lesson).

- [ ] **Step 1: Add three new assertions**

Open `tests/test_settings_gdrive.py`. Find `test_settings_dialog_has_gdrive_handlers` and `test_settings_mixin_has_gdrive_callbacks`. Append the following two new tests at the end of the file:

```python
def test_settings_dialog_has_backup_now_button_and_handlers():
    """Phase 7.1: 'Сделать backup сейчас' button + 3 handlers must
    exist in SettingsDialog source."""
    src = _read(os.path.join("ui", "dialogs", "settings.py"))
    assert "Сделать backup сейчас" in src, (
        "Button label literal missing — Russian UX string check"
    )
    for method in (
        "_handle_gdrive_backup_now",
        "_on_gdrive_backup_success",
        "_on_gdrive_backup_failure",
    ):
        assert f"def {method}(self" in src, f"Missing handler: {method}"


def test_settings_mixin_has_backup_success_callback():
    """Phase 7.1: _on_gdrive_backup_succeeded must exist on
    SettingsMixin (called by the dialog's success worker)."""
    src = _read(os.path.join("ui", "app", "settings_mixin.py"))
    assert "def _on_gdrive_backup_succeeded(" in src
    # Sanity: it must persist both keys.
    assert '"gdrive_root_folder_id"' in src
    assert '"gdrive_last_backup"' in src
```

- [ ] **Step 2: Run the smoke tests**

```
pytest tests/test_settings_gdrive.py -v
```

Expected: 6 PASS (4 existing from 7.0 + 2 new).

- [ ] **Step 3: Run the full suite + lint**

```
pytest -q
python -m ruff check .
```

Expected: 374 (post-PR-B) + 2 new = 376 green; ruff clean.

- [ ] **Step 4: Commit**

```bash
git add tests/test_settings_gdrive.py
git commit -m "$(cat <<'EOF'
test(settings/gdrive): Phase 7.1 backup-button smoke assertions

Two new source-text smoke tests verify the surface added in C.3:
  - SettingsDialog source contains the "Сделать backup сейчас" button
    label literal + all three new handler method definitions
  - SettingsMixin source contains _on_gdrive_backup_succeeded
    + persists both gdrive_root_folder_id and gdrive_last_backup keys

Same pure-source-text pattern as the existing 7.0 tests — no ui.app
import (Ubuntu CI has no PortAudio; see test_ui_constants.py docstring
for the established workaround).
EOF
)"
```

---

### Task C.5: CLAUDE.md update + PR-C wrap-up

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update test baseline + add Phase 7.1 to Active work**

Open `CLAUDE.md`. Find the test baseline line:

```
pytest                       # must show green; baseline = 356 tests
```

Replace the breakdown comment to add the Phase 7.1 contribution:

```
pytest                       # must show green; baseline = 376 tests
                             # (was 285 pre-code-switching; +30 from Phase 1
                             # cloud/UI tests, +4 segmenter, +15 mixed-mode,
                             # +8 from sampling-rate / VAD-resample fixes,
                             # +10 from GDrive auth (Phase 7.0 PR-A #40/#41),
                             # +4 from Settings-section smoke (Phase 7.0 PR-B #42),
                             # +8 from Drive client wrapper (Phase 7.1 PR-A),
                             # +10 from backup orchestrator (Phase 7.1 PR-B),
                             # +2 from backup-button smoke (Phase 7.1 PR-C))
```

Find the "Where things live" table row added in 7.0 for `gdrive/auth.py`. Add two more rows immediately after it:

```markdown
| Google Drive API wrapper (Phase 7.1) | `gdrive/client.py` (`DriveClient` — thin wrapper over `googleapiclient.discovery.build`; find/create folder + upload file) |
| Google Drive backup orchestrator (Phase 7.1) | `gdrive/backup.py` (`run_backup` — composes `redact_config` + `zip_history` + `build_manifest` + `DriveClient`) |
```

Find the Phase 7.0 bullet in "Active work / context". Append (NOT replace) a new bullet immediately after it:

```markdown
- **Phase 7.1** (May 2026, shipped): Google Drive manual backup.
  Shipped via PR-A (`gdrive/client.py` Drive API v3 wrapper),
  PR-B (`gdrive/backup.py` orchestrator), PR-C (Settings UI
  button + config key). New "Сделать backup сейчас" button under
  the Google Drive section of Settings; click triggers a worker
  thread that ensures auth is valid, zips `history/` (excluding
  `*.wav/*.mp3/*.m4a` per text-only scope), redacts API keys
  from `config.json`, builds a SHA-256 + size manifest, and
  uploads all three files to `audio-transcriber-backup/<ISO-ts>/`
  on Drive. New config keys: `gdrive_root_folder_id` (cached
  after first backup to skip find_or_create round-trip),
  `gdrive_last_backup` (ISO snapshot name; Phase 7.3 scheduler
  reads it). Spec at
  `docs/superpowers/specs/2026-04-30-gdrive-backup-design.md`,
  plan at `docs/superpowers/plans/2026-05-23-gdrive-phase-7.1-backup.md`.
  Phase 7.2 (restore), 7.3 (auto-schedule), 7.4 (audio opt-in)
  remain unstarted.
```

- [ ] **Step 2: Verify nothing broke**

```
pytest -q
python -m ruff check .
```

Expected: 376 green, ruff clean.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: update CLAUDE.md after Phase 7.1 ships

Three changes:

* Test baseline 356 → 376 (+8 from PR-A's client wrapper, +10 from
  PR-B's orchestrator, +2 from PR-C's smoke). Per-PR breakdown in
  the comment so a future drop is git-blameable to the right PR.

* "Where things live" table: two new rows for gdrive/client.py and
  gdrive/backup.py, sitting alongside the existing gdrive/auth.py
  row from Phase 7.0.

* New "Active work" bullet for Phase 7.1 (additive — Phase 7.0
  bullet stays as the precedent for the auth + UI surface). Notes
  the new config keys, the spec/plan paths, and what remains
  unstarted (7.2/7.3/7.4).
EOF
)"
```

- [ ] **Step 4: Push + open PR**

```bash
git push -u origin feat/gdrive-phase-7.1-ui
gh pr create --title "feat(gdrive): Phase 7.1 Settings UI integration + docs [PR-C]" --body "$(cat <<'EOF'
## Summary

Phase 7.1 closeout: Settings dialog gets a "Сделать backup сейчас" button under the existing Google Drive section. Click triggers a worker that runs \`gdrive.backup.run_backup\` (from PR-B) with a status callback feeding Russian-language progress strings back into the dialog. After this PR users have working manual backup; restore is Phase 7.2.

### Changes

| File | What |
|---|---|
| \`config.example.json\` | +1 key: \`gdrive_root_folder_id\` (cached after first backup) |
| \`ui/app/settings_mixin.py\` | \`_on_gdrive_backup_succeeded(root_folder_id, snapshot_name)\` — persists both new keys |
| \`ui/dialogs/settings.py\` | New "Сделать backup сейчас" button (row=2 in GDrive section) + 3 handlers (\`_handle_gdrive_backup_now\` worker, \`_on_gdrive_backup_success\`, \`_on_gdrive_backup_failure\`) |
| \`tests/test_settings_gdrive.py\` | +2 pure-source-text smoke tests |
| \`CLAUDE.md\` | Active-work Phase 7.1 bullet, two "Where things live" rows for \`gdrive/client.py\` + \`gdrive/backup.py\`, test baseline 356 → 376 |

### Notable choices

- **Backup button gated on sign-in state**: \`_refresh_gdrive_button_state\` extended to also disable Сделать backup when not signed in. Trying to backup without auth would fail at the first \`ensure_valid_credentials\` call anyway, but the disabled state is the friendlier UX.
- **Lambda scoping fix applied preemptively**: \`error_msg = str(e)\` hoisted before \`lambda\` (same Python except-scope rule that bit Phase 7.0 PR-B; caught by ruff F821 there).
- **Pure-source-text smoke tests**: same pattern as 7.0 PR-B per \`test_ui_constants.py\` docstring — avoids \`ui.app\` import on Ubuntu CI without PortAudio.

### Deferred: manual smoke

Real "click Сделать backup, see snapshot folder on Drive" verification needs the Phase 7.0 B.5 Pre-flight (real GCP \`CLIENT_ID\` / \`CLIENT_SECRET\`) done. If still using placeholders, the unit + smoke tests all pass but the live round-trip waits for that tiny follow-up commit.

## Test plan

- [x] \`pytest -q\` — 364 (post-PR-A) + 10 (PR-B) + 2 (PR-C) = **376** green
- [x] \`python -m ruff check .\` — clean
- [x] \`python -c "import ui.app; from ui.dialogs.settings import SettingsDialog; assert hasattr(SettingsDialog, '_handle_gdrive_backup_now'); print('ok')"\` → ok
- [ ] Manual smoke (real OAuth + click button + verify Drive contents) — deferred to follow-up alongside the Phase 7.0 B.5 manual smoke

## Closes

Phase 7.1 of the Google Drive backup feature per [spec](docs/superpowers/specs/2026-04-30-gdrive-backup-design.md).
EOF
)"
```

- [ ] **Step 5: After merge, no separate docs PR needed** — CLAUDE.md was updated in this same PR (different from Phase 7.0's pattern; Phase 7.0 had a separate docs PR because its closure came after PR-B; here PR-C IS the closure).

---

## Plan self-review

**Spec coverage** — every Phase 7.1 spec section has a corresponding task:

- Backup payload structure (spec lines 78-108): Task B.4 (`run_backup` composes everything), B.3 (manifest schema match), B.2 (zip), B.1 (redacted config)
- API key redaction list (spec lines 117-121): B.1 (`REDACTED_KEYS` constant + `redact_config`)
- Timestamped folders (spec line 84-92): B.3 (`_iso_timestamp`), B.4 (orchestrator creates `<iso-ts>` subfolder under `audio-transcriber-backup`)
- Drive folder creation idempotency (spec implicit — "Drive folder created on first backup"): A.3 (`find_or_create_folder`), C.1 (cached root id in config)
- Status feedback during backup (spec implicit — "manual backup button"): C.3 (`on_status` callback + Russian-language phase strings)
- Configuration keys (spec lines 173-181): `gdrive_root_folder_id` added in C.1; `gdrive_last_backup` from 7.0 reused and persisted in C.2; rest belong to 7.3/7.4

**Spec scope NOT in this plan** — explicitly deferred per phasing:

- Restore (spec section "Restore (Phase 7.2)") — Phase 7.2 plan, separate
- Auto-schedule (spec section "Auto-schedule (Phase 7.3)") — Phase 7.3 plan
- Audio opt-in (spec section "Audio opt-in (Phase 7.4)") — Phase 7.4 plan
- Retention policy (spec line 115) — Phase 7.3
- Eventual two-way sync (spec section "Eventual two-way sync (Phase 7.5)") — far future

**Placeholder scan** — no TBD / TODO / "implement later" in code steps. The only conditional is C.5 Step 5 ("no separate docs PR needed") which is a documented divergence from Phase 7.0's pattern with rationale.

**Type consistency** —
- `run_backup(*, auth, config, history_dir, work_dir, app_version, on_status)` — kwargs-only signature consistent in B.4 test definitions, B.4 implementation, C.3 dialog call site.
- Return-dict shape `{"root_folder_id", "snapshot_folder_id", "snapshot_name", "uploaded"}` — same keys read in B.4 test, C.2 `_on_gdrive_backup_succeeded`, C.3 `_on_gdrive_backup_success`.
- `DriveClient.upload_file(*, local_path, drive_name, parent_id, mime_type)` — kwargs-only, consistent in A.4 test + impl + B.4 orchestrator caller.
- `REDACTION_PLACEHOLDER = "<REDACTED>"` — string literal consistent in B.1 constant + B.1 test assertion + B.4 test verification.
- `MANIFEST_VERSION = 1` — written in B.3 impl, asserted in B.3 test.
- `AUDIO_EXTS = (".wav", ".mp3", ".m4a")` — defined in B.2 impl; the test uses its own local tuple constant `_AUDIO_EXTS` for the same set (deliberately decoupled so a future change to the production tuple doesn't silently mask a test bug).

---

## Glossary

- **`DriveClient`** — `gdrive.client.DriveClient`. Thin sync wrapper over `googleapiclient.discovery.build("drive", "v3")`. Methods: `find_folder`, `create_folder`, `find_or_create_folder`, `upload_file`.
- **`run_backup`** — `gdrive.backup.run_backup`. The single orchestrator entry point. Settings dialog's worker thread calls it; returns a result dict that drives `_on_gdrive_backup_succeeded`'s config persistence.
- **`audio-transcriber-backup`** — fixed top-folder name on the user's Drive. Cached in `config.json["gdrive_root_folder_id"]` after first backup so subsequent backups skip the `find_or_create_folder` round-trip.
- **Snapshot folder** — timestamped subfolder created under `audio-transcriber-backup` per backup, e.g. `2026-05-23T22-30-45/`. Contains `manifest.json`, `config.json` (redacted), `history.zip`.
- **Manifest** — `manifest.json` per spec schema (line 94-108): version, created_at, app_version, host, files{size, sha256}, transcripts_count, audio_included. Phase 7.2 restore reads this first to verify integrity before downloading the payload.
- **Redaction** — top-level secret keys (per `REDACTED_KEYS`) plus all values in the nested `cloud_api_keys` dict replaced with `<REDACTED>` before upload. Input config dict is never mutated.
- **`on_status` callback** — optional `callable(str)` passed to `run_backup`. Receives Russian-language phase strings ("Создаю архив истории...", "Загружаю manifest.json...", "✓ Backup готов"). The Settings dialog uses it to live-update the status badge; CLI / scheduler callers can pass `None`.
- **PR-A** — Foundation: the `gdrive/client.py` module + 8 unit tests. Nothing imports it on this branch.
- **PR-B** — Composition: the `gdrive/backup.py` orchestrator + 10 unit tests. Imports `DriveClient` lazily via a sentinel pattern so it stays mock-friendly.
- **PR-C** — Integration: Settings dialog button + config key + CLAUDE.md update. End of PR-C = Phase 7.1 shipped.
