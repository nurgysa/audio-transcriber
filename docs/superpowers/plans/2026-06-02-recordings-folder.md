# Recordings Folder Relocation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the recorder dumping `.wav` files into the `~/Documents` root — write them to `<meetings_dir>/recordings/`, with an opt-in config toggle to delete a recording after a successful transcription, plus a one-time script to move the ~103 existing root files.

**Architecture:** New `utils.get_recordings_dir()` (builds on `get_meetings_dir()`) is the single source of truth for the recordings location. `recorder.start()` takes the resolved dir per-recording and `makedirs` it. `recorder_mixin` passes the resolved dir. A pure `utils.should_delete_after_transcription(config, audio_path)` (toggle + path-containment) gates an optional delete in `transcription_mixin._on_complete`, placed after the history-folder audio copy so deletion never loses the only copy. A standalone `scripts/move_recordings.py` relocates existing root files.

**Tech Stack:** Python 3.12 (`os`, `glob`, `shutil`, `argparse` — stdlib), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-02-recordings-folder-design.md`

---

## File structure

| File | Responsibility | Change |
|---|---|---|
| `utils.py` | path resolution + delete decision | + `get_recordings_dir()`, + `should_delete_after_transcription(config, audio_path)` |
| `recorder.py` | audio capture | `start(output_dir=None)` + `makedirs`; `__init__` fallback default → recordings subfolder |
| `ui/app/recorder_mixin.py` | record button handler | `_start_recording` passes the resolved dir |
| `ui/app/transcription_mixin.py` | post-transcription | `_on_complete` deletes `.wav` when the helper says so |
| `config.example.json` | template | + `delete_recording_after_transcription: false` |
| `scripts/move_recordings.py` | one-time migration | new (dry-run default) |
| `tests/` | tests | resolver + delete-decision + recorder + move-script + 2 source-text wiring checks |

**Notes for the implementer:**
- CI constraint: tests must NOT import `ui.app` or `recorder` *directly* (sounddevice/soundfile load native libs absent on Linux CI). The recorder test injects `MagicMock`s into `sys.modules` for `sounddevice` + `soundfile` BEFORE importing `recorder`. The two mixin tests use **source-text assertions** (read the `.py` as text), the established pattern (`tests/test_dialog_dedup_*`). `utils` and `scripts/move_recordings.py` are CI-safe to import (no native deps).
- Untracked `cli/` files + `tests/test_cli_import_guard.py` are the user's parallel work — do not touch/stage; they're collected by pytest and currently pass.

---

### Task 1: `utils.get_recordings_dir()`

**Files:**
- Modify: `utils.py` (add after `get_meetings_dir`)
- Test: `tests/test_utils_recordings_dir.py` (create)

- [ ] **Step 1: Write the failing test** — create `tests/test_utils_recordings_dir.py`:

```python
"""utils.get_recordings_dir — recordings live under the active meetings dir.

Monkeypatch-only; never imports ui.app/recorder (native deps absent on CI).
"""
from __future__ import annotations

import os

import utils


def test_recordings_dir_is_subfolder_of_meetings_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "get_meetings_dir", lambda: str(tmp_path / "vault"))
    assert utils.get_recordings_dir() == os.path.join(str(tmp_path / "vault"), "recordings")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_utils_recordings_dir.py -v`
Expected: FAIL — `AttributeError: module 'utils' has no attribute 'get_recordings_dir'`.

- [ ] **Step 3: Implement** — in `utils.py`, add after the `get_meetings_dir` function:

```python
def get_recordings_dir() -> str:
    """Directory for raw recordings: ``<meetings_dir>/recordings/``.

    Builds on get_meetings_dir() so it inherits the same 3-level fallback,
    ~/%VAR% expansion, and writability checks — recordings always land as a
    subfolder of whatever meetings dir is actually in use. The subfolder
    itself is created by the write sites (recorder.start, move script), not
    here, so this stays a pure resolver.
    """
    return os.path.join(get_meetings_dir(), "recordings")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_utils_recordings_dir.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add utils.py tests/test_utils_recordings_dir.py
git commit -m "feat(recorder): get_recordings_dir() under the meetings dir"
```

---

### Task 2: `utils.should_delete_after_transcription()` + config key

**Files:**
- Modify: `utils.py` (add after `get_recordings_dir`)
- Modify: `config.example.json`
- Test: `tests/test_utils_recordings_dir.py` (append)

- [ ] **Step 1: Write the failing test** — append to `tests/test_utils_recordings_dir.py`:

```python
def test_should_delete_off_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "get_recordings_dir", lambda: str(tmp_path / "rec"))
    inside = str(tmp_path / "rec" / "recording_x.wav")
    assert utils.should_delete_after_transcription({}, inside) is False


def test_should_delete_when_on_and_inside(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "get_recordings_dir", lambda: str(tmp_path / "rec"))
    inside = str(tmp_path / "rec" / "recording_x.wav")
    cfg = {"delete_recording_after_transcription": True}
    assert utils.should_delete_after_transcription(cfg, inside) is True


def test_should_not_delete_when_on_but_outside(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "get_recordings_dir", lambda: str(tmp_path / "rec"))
    outside = str(tmp_path / "downloads" / "user_clip.wav")
    cfg = {"delete_recording_after_transcription": True}
    assert utils.should_delete_after_transcription(cfg, outside) is False


def test_should_not_delete_when_path_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "get_recordings_dir", lambda: str(tmp_path / "rec"))
    cfg = {"delete_recording_after_transcription": True}
    assert utils.should_delete_after_transcription(cfg, "") is False
    assert utils.should_delete_after_transcription(cfg, None) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_utils_recordings_dir.py -v`
Expected: FAIL — `AttributeError: ... 'should_delete_after_transcription'`.

- [ ] **Step 3: Implement** — in `utils.py`, add after `get_recordings_dir`:

```python
def should_delete_after_transcription(config: dict, audio_path: str | None) -> bool:
    """True only when the user opted in AND ``audio_path`` lives inside the
    recordings dir. The path-containment check (not a flag) guarantees a
    user-loaded file from elsewhere is never deleted. Drive-mismatch / bad
    paths fail safe to False (don't delete)."""
    if not config.get("delete_recording_after_transcription", False):
        return False
    if not audio_path:
        return False
    try:
        ap = os.path.normcase(os.path.abspath(audio_path))
        rd = os.path.normcase(os.path.abspath(get_recordings_dir()))
        return os.path.commonpath([ap, rd]) == rd
    except (ValueError, OSError):
        return False  # different drives (Windows) / malformed path → don't delete
```

Also add the key to `config.example.json` — insert after the `"trello_enabled": false,` line (next to the other feature flags):

```json
  "delete_recording_after_transcription": false,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_utils_recordings_dir.py -v && python -c "import json; json.load(open('config.example.json'))"`
Expected: PASS (5 tests) and the config.example.json still parses as valid JSON.

- [ ] **Step 5: Commit**

```bash
git add utils.py config.example.json tests/test_utils_recordings_dir.py
git commit -m "feat(recorder): should_delete_after_transcription + config key"
```

---

### Task 3: `recorder.start(output_dir)` + makedirs + safe default

**Files:**
- Modify: `recorder.py` (`__init__` line 26-27, `start` line 69-101)
- Test: `tests/test_recorder_output_dir.py` (create)

- [ ] **Step 1: Write the failing test** — create `tests/test_recorder_output_dir.py`:

```python
"""recorder.start writes to the given output_dir (creating it).

recorder.py imports sounddevice, and audio_io imports soundfile — both load
native libs absent on Linux CI. Inject MagicMocks BEFORE importing recorder
so the test runs headless. We assert on the directory + path logic only (the
mocked SoundFile writes no real file).
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("sounddevice", MagicMock())
sys.modules.setdefault("soundfile", MagicMock())

from recorder import Recorder  # noqa: E402


def test_start_creates_and_uses_output_dir(tmp_path):
    target = tmp_path / "vault" / "recordings"   # parent dirs do NOT exist yet
    r = Recorder()
    path = r.start(output_dir=str(target))
    try:
        assert os.path.isdir(str(target))                  # makedirs created it
        assert path.startswith(str(target))
        assert os.path.basename(path).startswith("recording_")
        assert path.endswith(".wav")
    finally:
        r.stop()


def test_default_output_dir_is_not_documents_root():
    r = Recorder()
    expected = os.path.join(
        os.path.expanduser("~"), "Documents", "AudioTranscriber", "recordings",
    )
    assert r._output_dir == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_recorder_output_dir.py -v`
Expected: FAIL — `test_start_creates_and_uses_output_dir` raises `TypeError: start() got an unexpected keyword argument 'output_dir'`; `test_default_output_dir_is_not_documents_root` fails because the default is `~/Documents` (root).

- [ ] **Step 3: Implement** — in `recorder.py`:

Change `__init__` (line 26-27):

```python
    def __init__(self, output_dir: str | None = None):
        self._output_dir = output_dir or os.path.join(
            os.path.expanduser("~"), "Documents", "AudioTranscriber", "recordings",
        )
```

Change the `start` signature + add makedirs + use the per-call dir (replace the head of `start`, lines 69-75):

```python
    def start(self, output_dir: str | None = None) -> str:
        """Start recording. Returns the output file path.

        ``output_dir`` overrides the instance default for this recording
        (the caller passes the freshly-resolved recordings dir so a
        mid-session meetings_dir change is honored). The dir is created if
        missing.
        """
        if self._is_recording:
            raise RuntimeError("Already recording")

        target_dir = output_dir or self._output_dir
        os.makedirs(target_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._current_path = os.path.join(target_dir, f"recording_{timestamp}.wav")
```

(Leave the rest of `start` — the `sf.SoundFile(...)`, `sd.InputStream(...)`, state flags, `self._stream.start()`, `return self._current_path` — unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_recorder_output_dir.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add recorder.py tests/test_recorder_output_dir.py
git commit -m "feat(recorder): start(output_dir) + makedirs; default off the Documents root"
```

---

### Task 4: Wire `recorder_mixin` to the resolved dir

**Files:**
- Modify: `ui/app/recorder_mixin.py` (`_start_recording`, line 28-30; imports)
- Test: `tests/test_recorder_mixin_dir_source.py` (create — source-text, no import)

- [ ] **Step 1: Write the failing test** — create `tests/test_recorder_mixin_dir_source.py`:

```python
import pathlib

_SRC = pathlib.Path("ui/app/recorder_mixin.py").read_text(encoding="utf-8")


def test_start_recording_passes_resolved_recordings_dir():
    start = _SRC.index("def _start_recording(")
    nxt = _SRC.index("def ", start + 1)
    body = _SRC[start:nxt]
    assert "get_recordings_dir()" in body
    assert "output_dir=get_recordings_dir()" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_recorder_mixin_dir_source.py -v`
Expected: FAIL — body still calls `self._recorder.start()` with no dir.

- [ ] **Step 3: Implement** — read `ui/app/recorder_mixin.py`. At the top of the file add the import (with the other imports):

```python
from utils import get_recordings_dir
```

In `_start_recording`, change the `self._recorder.start()` call to:

```python
            self._recorder.start(output_dir=get_recordings_dir())
```

(Keep the surrounding try/except and UI-state lines exactly as they are. If `_start_recording` references `get_recordings_dir` only here, the import is the only other change.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_recorder_mixin_dir_source.py -v && python -m ruff check ui/app/recorder_mixin.py`
Expected: PASS + ruff clean (no unused import).

- [ ] **Step 5: Commit**

```bash
git add ui/app/recorder_mixin.py tests/test_recorder_mixin_dir_source.py
git commit -m "feat(recorder): record into the resolved recordings dir"
```

---

### Task 5: Optional delete in `transcription_mixin._on_complete`

**Files:**
- Modify: `ui/app/transcription_mixin.py` (`_on_complete`, inside the `if self._audio_path:` block; imports)
- Test: `tests/test_transcription_mixin_delete_source.py` (create — source-text, no import)

- [ ] **Step 1: Write the failing test** — create `tests/test_transcription_mixin_delete_source.py`:

```python
import pathlib

_SRC = pathlib.Path("ui/app/transcription_mixin.py").read_text(encoding="utf-8")


def test_on_complete_deletes_recording_when_helper_says_so():
    start = _SRC.index("def _on_complete(")
    nxt = _SRC.index("def _on_error(")
    body = _SRC[start:nxt]
    assert "should_delete_after_transcription(self._config, self._audio_path)" in body
    assert "os.unlink(" in body or "os.remove(" in body
    # guarded so a delete failure never crashes the success flow
    assert "except OSError" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_transcription_mixin_delete_source.py -v`
Expected: FAIL — no delete logic in `_on_complete` yet.

- [ ] **Step 3: Implement** — in `ui/app/transcription_mixin.py`:

Ensure `os` is imported at the top (it is — used by the crash-dump path). Add to the utils import (find the existing `from utils import ...` line and add the name, or add a new import):

```python
from utils import should_delete_after_transcription
```

In `_on_complete`, inside the existing `if self._audio_path:` block, AFTER the `create_history_entry(...)` call and the `save_segments(...)` block (so the history-folder audio copy already exists), add:

```python
            # Opt-in: drop the source recording now that the transcript is
            # saved and the audio is copied into the history folder. Guarded by
            # path-containment so only files inside the recordings dir are
            # touched. Best-effort — a delete failure must not break success.
            if should_delete_after_transcription(self._config, self._audio_path):
                try:
                    os.unlink(self._audio_path)
                    logger.info("deleted recording after transcription: %s", self._audio_path)
                except OSError as e:
                    logger.warning("could not delete recording %s: %s", self._audio_path, e)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_transcription_mixin_delete_source.py -v && python -m ruff check ui/app/transcription_mixin.py`
Expected: PASS + ruff clean.

- [ ] **Step 5: Commit**

```bash
git add ui/app/transcription_mixin.py tests/test_transcription_mixin_delete_source.py
git commit -m "feat(recorder): optional delete-after-transcription (path-guarded)"
```

---

### Task 6: One-time move script `scripts/move_recordings.py`

**Files:**
- Create: `scripts/move_recordings.py`
- Test: `tests/test_move_recordings_script.py` (create)

- [ ] **Step 1: Write the failing test** — create `tests/test_move_recordings_script.py`:

```python
"""Selection logic for the one-time recordings move script.

Loads the script by path (it lives in scripts/, not a package). The script
imports utils (CI-safe — no native deps), so this import is safe on CI.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib

_PATH = pathlib.Path("scripts/move_recordings.py")
_spec = importlib.util.spec_from_file_location("move_recordings", _PATH)
move_recordings = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(move_recordings)


def test_selects_only_root_recording_wavs(tmp_path):
    docs = tmp_path / "Documents"
    (docs / "sub").mkdir(parents=True)
    (docs / "recording_2026-01-01_10-00-00.wav").write_bytes(b"x")
    (docs / "recording_2026-01-02_11-00-00.wav").write_bytes(b"x")
    (docs / "notes.wav").write_bytes(b"x")               # not a recording
    (docs / "report.docx").write_bytes(b"x")             # not a wav
    (docs / "sub" / "recording_nested.wav").write_bytes(b"x")  # nested → skip

    found = move_recordings._select_root_recordings(str(docs))
    names = sorted(os.path.basename(p) for p in found)
    assert names == [
        "recording_2026-01-01_10-00-00.wav",
        "recording_2026-01-02_11-00-00.wav",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_move_recordings_script.py -v`
Expected: FAIL — `FileNotFoundError`/`spec is None` (script doesn't exist yet).

- [ ] **Step 3: Implement** — create `scripts/move_recordings.py`:

```python
#!/usr/bin/env python3
"""One-time move of legacy recordings out of the ~/Documents root.

Old builds wrote recording_<ts>.wav straight into ~/Documents. This moves
those root files into the current recordings dir (<meetings_dir>/recordings/).
Dry-run by default; pass --apply to actually move. Non-recursive, exact glob —
it only touches recording_*.wav directly in ~/Documents, never subfolders or
other files. You-only; not bundled with the app.

Usage (from repo root):
    python scripts/move_recordings.py            # dry run
    python scripts/move_recordings.py --apply
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from utils import get_recordings_dir  # noqa: E402


def _select_root_recordings(documents_dir: str) -> list[str]:
    """recording_*.wav directly in documents_dir (non-recursive)."""
    pattern = os.path.join(documents_dir, "recording_*.wav")
    return sorted(p for p in glob.glob(pattern) if os.path.isfile(p))


def main() -> int:
    ap = argparse.ArgumentParser(description="Move legacy ~/Documents recordings into the recordings dir.")
    ap.add_argument("--apply", action="store_true", help="actually move (default: dry run)")
    args = ap.parse_args()

    docs = os.path.join(os.path.expanduser("~"), "Documents")
    dest = get_recordings_dir()
    files = _select_root_recordings(docs)
    print(f"source: {docs}")
    print(f"dest:   {dest}")
    print(f"found:  {len(files)} recording_*.wav in the Documents root")

    if not args.apply:
        for f in files:
            print(f"  would move: {os.path.basename(f)}")
        print("DRY RUN — nothing moved. Re-run with --apply.")
        return 0

    os.makedirs(dest, exist_ok=True)
    moved = skipped = 0
    for f in files:
        target = os.path.join(dest, os.path.basename(f))
        if os.path.exists(target):
            print(f"  skip (exists): {os.path.basename(f)}")
            skipped += 1
            continue
        shutil.move(f, target)
        moved += 1
        print(f"  moved: {os.path.basename(f)}")
    print(f"done: moved={moved} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_move_recordings_script.py -v && python -m ruff check scripts/move_recordings.py`
Expected: PASS + ruff clean.

- [ ] **Step 5: Commit**

```bash
git add scripts/move_recordings.py tests/test_move_recordings_script.py
git commit -m "chore(recorder): one-time move script for legacy ~/Documents recordings"
```

---

### Task 7: Full gate — pytest + ruff

**Files:** none (verification)

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q -p no:cacheprovider > out.txt 2>&1; echo "EXIT=$?"; tail -3 out.txt; rm -f out.txt`
Expected: `EXIT=0` (the summary line may not surface through the pipe — the exit code is authoritative). ~10 new tests on top of the prior green suite.

- [ ] **Step 2: Run ruff**

Run: `python -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 3: Fix any failures, then commit fixups (only if needed)**

```bash
git add -p
git commit -m "chore(recorder): lint/test fixups"
```

(Skip if both already green. Do NOT use `git add -A` — untracked `cli/` is the user's.)

---

### Task 8: Manual smoke (the gate)

**Files:** none (manual verification — recording needs the GUI + a mic)

- [ ] **Step 1: Run the app from the repo (dev mode)**

Run: `python app.py` (dev/source mode uses repo-root config; `meetings_dir` from that config). Record a short clip (⏺), stop.

- [ ] **Step 2: Verify location**

Confirm the new `.wav` is at `<meetings_dir>/recordings/recording_<ts>.wav` (NOT the Documents root). If `meetings_dir` is unset in the dev config, confirm it landed at `~/Documents/AudioTranscriber/meetings/recordings/`.

- [ ] **Step 3: Verify transcription + (optional) delete toggle**

Transcribe the clip → confirm the transcript saves and a copy of the audio is in the history folder. Then set `"delete_recording_after_transcription": true` in the config, record + transcribe again, and confirm the new `<meetings_dir>/recordings/` `.wav` is removed after success (history copy remains). Set it back to `false`.

- [ ] **Step 4: Move the legacy files**

Run `python scripts/move_recordings.py` (dry run) → review the list of ~103 root files. Then `python scripts/move_recordings.py --apply` → confirm the Documents root is clean and the files now sit in the recordings dir.

- [ ] **Step 5: Record outcome**

Note results in the session. If green: the Documents root no longer accumulates recordings. If any step fails: return to systematic-debugging.

---

## Self-Review

**Spec coverage:**
- `get_recordings_dir()` under meetings dir → Task 1. ✓
- Recorder writes there + makedirs + safe default → Task 3. ✓
- Caller passes resolved dir → Task 4. ✓
- Optional delete (toggle + path-containment, after history copy) → Tasks 2 + 5. ✓
- Config key in template → Task 2. ✓
- One-time move script (dry-run, root-only, collision-skip) → Task 6. ✓
- Tests monkeypatch/source-text/sys.modules-mock, no ui.app/recorder import on CI → all tasks. ✓
- Manual smoke (location + delete + move) → Task 8. ✓

**Placeholder scan:** none — every step has concrete code/commands.

**Type/signature consistency:** `get_recordings_dir() -> str` (Task 1) used by `should_delete_after_transcription` (Task 2), `recorder_mixin` (Task 4), and the move script (Task 6). `should_delete_after_transcription(config, audio_path) -> bool` (Task 2) called identically in Task 5's source-text check. `recorder.start(output_dir=None)` (Task 3) matches the Task 4 call `start(output_dir=get_recordings_dir())`. `_select_root_recordings(documents_dir) -> list[str]` (Task 6) matches its test. ✓

**Out of scope (per spec):** Settings UI checkbox; per-meeting co-location; in-app auto-migration; configurable recordings path. Untracked `cli/` not touched.
