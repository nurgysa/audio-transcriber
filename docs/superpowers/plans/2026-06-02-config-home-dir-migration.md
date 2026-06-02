# Config Home-Dir Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Relocate the frozen app's `config.json` from inside the PyInstaller bundle (`_internal/config.json`, wiped on every update) to `~/.audio-transcriber/config.json`, so client updates stop blanking keys/settings.

**Architecture:** `utils._CONFIG_PATH` becomes frozen-aware via a new `_default_config_path()` — `~/.audio-transcriber/config.json` when frozen, repo-root `config.json` in dev (unchanged). `save_config` creates the parent dir. On frozen first-run, `load_config` seeds the config from a bundled `config.example.json` template (empty keys → first-run banner). The build bundles the template instead of seeding a live `config.json`. The single existing `C:\Apps` install is migrated once, operationally, during the deploy.

**Tech Stack:** Python 3.12 (`os`, `sys`, `shutil`, `json` — all already imported in `utils.py`), pytest, PyInstaller onedir build (`scripts/build_exe.ps1`). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-02-config-home-dir-migration-design.md`

---

## File structure

| File | Responsibility | Change |
|---|---|---|
| `utils.py` | config load/save + path resolution | + `_default_config_path()`; `_CONFIG_PATH` uses it; `save_config` makedirs; + `_seed_default_config`; `load_config` seeds on frozen first-run |
| `scripts/build_exe.ps1` | bundle packaging | step [5/6]: bundle `config.example.json` as a **template** (not a live `config.json`) |
| `tests/test_utils_config_path.py` | new tests | path resolution + save makedirs + first-run seed |

**Notes for the implementer:**
- The repo working tree has **untracked** `cli/` files and `tests/test_cli_import_guard.py` (the user's parallel work). Do NOT touch or stage them. They are collected by pytest and currently pass — leave them be.
- `gdrive/backup.py` was audited: `redact_config(config: dict)` operates on the in-memory dict passed to `run_backup`, not a path — it follows `load_config()` automatically. No change needed.
- CI constraint: do not import `ui.app` in tests (sounddevice/PortAudio loads at import on Linux CI). All tests here import only `utils` + stdlib.

---

### Task 1: Frozen-aware `_default_config_path()`

**Files:**
- Modify: `utils.py` (line 9 — the `_CONFIG_PATH` assignment)
- Test: `tests/test_utils_config_path.py` (create)

- [ ] **Step 1: Write the failing test** — create `tests/test_utils_config_path.py`:

```python
"""utils config-path resolution + first-run seed + save-dir creation.

Frozen (.exe) stores config at ~/.audio-transcriber/config.json (outside the
bundle, survives updates); dev/source uses repo-root config.json. Monkeypatch
only — never imports ui.app (sounddevice/PortAudio is absent on Linux CI).
"""
from __future__ import annotations

import json
import os

import utils


def test_default_config_path_source_mode():
    # Tests run unfrozen → repo-root config.json beside utils.py.
    assert getattr(__import__("sys"), "frozen", False) is False
    expected = os.path.join(os.path.dirname(os.path.abspath(utils.__file__)), "config.json")
    assert utils._default_config_path() == expected


def test_default_config_path_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(utils.sys, "frozen", True, raising=False)
    monkeypatch.setattr(utils.os.path, "expanduser", lambda p: str(tmp_path) if p == "~" else p)
    assert utils._default_config_path() == os.path.join(
        str(tmp_path), ".audio-transcriber", "config.json",
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_utils_config_path.py -v`
Expected: FAIL — `AttributeError: module 'utils' has no attribute '_default_config_path'`.

- [ ] **Step 3: Implement** — in `utils.py`, replace line 9:

```python
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
```

with:

```python
def _default_config_path() -> str:
    """Resolve config.json location.

    Frozen (.exe): ``~/.audio-transcriber/config.json`` — OUTSIDE the bundle so
    a build update never wipes the user's settings (same app-data home as
    gdrive-token.json / directory.json). Source (dev): repo-root config.json
    beside utils.py (unchanged).
    """
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.expanduser("~"), ".audio-transcriber", "config.json")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


_CONFIG_PATH = _default_config_path()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_utils_config_path.py tests/test_utils_load_config.py -v`
Expected: PASS (2 new + 3 existing BOM tests stay green — they patch `utils._CONFIG_PATH`, still a module constant).

- [ ] **Step 5: Commit**

```bash
git add utils.py tests/test_utils_config_path.py
git commit -m "feat(config): frozen-aware _default_config_path (~/.audio-transcriber when frozen)"
```

---

### Task 2: `save_config` creates the parent directory

**Files:**
- Modify: `utils.py` (the `save_config` function, ~line 131)
- Test: `tests/test_utils_config_path.py` (append)

- [ ] **Step 1: Write the failing test** — append to `tests/test_utils_config_path.py`:

```python
def test_save_config_creates_missing_parent_dir(monkeypatch, tmp_path):
    target = tmp_path / "made" / "up" / "config.json"   # parent dirs absent
    monkeypatch.setattr(utils, "_CONFIG_PATH", str(target))
    utils.save_config({"cloud_provider": "AssemblyAI"})
    assert target.is_file()
    assert json.loads(target.read_text(encoding="utf-8")) == {"cloud_provider": "AssemblyAI"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_utils_config_path.py::test_save_config_creates_missing_parent_dir -v`
Expected: FAIL — `FileNotFoundError: [Errno 2] No such file or directory: '.../made/up/config.json'` (the `open(...,"w")` can't create missing parent dirs).

- [ ] **Step 3: Implement** — in `utils.py`, replace `save_config`:

```python
def save_config(config: dict) -> None:
    parent = os.path.dirname(_CONFIG_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_utils_config_path.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add utils.py tests/test_utils_config_path.py
git commit -m "feat(config): save_config creates ~/.audio-transcriber if missing"
```

---

### Task 3: Frozen first-run seeds config from bundled template

**Files:**
- Modify: `utils.py` (add `_seed_default_config`; call it in `load_config`)
- Test: `tests/test_utils_config_path.py` (append)

- [ ] **Step 1: Write the failing test** — append to `tests/test_utils_config_path.py`:

```python
def test_load_config_seeds_template_when_frozen_and_missing(monkeypatch, tmp_path):
    # Simulate a frozen bundle whose _MEIPASS holds the config.example.json template.
    meipass = tmp_path / "bundle"
    meipass.mkdir()
    (meipass / "config.example.json").write_text(
        json.dumps({"cloud_provider": "AssemblyAI", "cloud_api_keys": {}}),
        encoding="utf-8",
    )
    target = tmp_path / "home" / ".audio-transcriber" / "config.json"   # absent
    monkeypatch.setattr(utils.sys, "frozen", True, raising=False)
    monkeypatch.setattr(utils.sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(utils, "_CONFIG_PATH", str(target))

    result = utils.load_config()

    assert target.is_file()                       # seeded the template to ~
    assert result["cloud_provider"] == "AssemblyAI"
    assert result["cloud_api_keys"] == {}         # empty keys → first-run banner fires


def test_load_config_does_not_seed_in_source_mode(monkeypatch, tmp_path):
    target = tmp_path / "config.json"             # absent; not frozen
    monkeypatch.setattr(utils, "_CONFIG_PATH", str(target))
    assert utils.load_config() == {}              # unchanged dev behavior
    assert not target.exists()                    # no seeding when unfrozen
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_utils_config_path.py::test_load_config_seeds_template_when_frozen_and_missing -v`
Expected: FAIL — the target is not created and `result` is `{}` (no seed logic yet) → `KeyError`/`assert target.is_file()` fails.

- [ ] **Step 3: Implement** — in `utils.py`, add `_seed_default_config` directly above `load_config`:

```python
def _seed_default_config(path: str) -> None:
    """Frozen first-run: copy the bundled config.example.json template to
    ``path`` when it is missing, so the live config is fully populated (empty
    keys → first-run banner). No-op in source mode (no sys.frozen / _MEIPASS)."""
    if not getattr(sys, "frozen", False):
        return
    template = os.path.join(getattr(sys, "_MEIPASS", ""), "config.example.json")
    if not os.path.isfile(template):
        return
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    shutil.copyfile(template, path)
```

and change `load_config` to seed before reading (keep the existing `utf-8-sig` BOM comment + read intact):

```python
def load_config() -> dict:
    # utf-8-sig (not "utf-8") so a leading UTF-8 BOM is silently stripped on
    # read. Defensive: third-party tooling that touches config.json — Windows
    # Notepad on save, PowerShell 5.1 `Set-Content -Encoding UTF8`, some
    # ZIP-extract pipelines — adds `EF BB BF` at the file start, and the
    # default "utf-8" codec then raises json.JSONDecodeError "Unexpected UTF-8
    # BOM" → silent app-start crash. Verified live on 2026-05-28 when a merge
    # helper script wrote config.json with BOM and the bundle failed to launch.
    if not os.path.isfile(_CONFIG_PATH):
        _seed_default_config(_CONFIG_PATH)  # frozen first-run: populate from template
    if os.path.isfile(_CONFIG_PATH):
        with open(_CONFIG_PATH, encoding="utf-8-sig") as f:
            return json.load(f)
    return {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_utils_config_path.py tests/test_utils_load_config.py -v`
Expected: PASS (5 in config_path + 3 existing BOM tests — note the existing `test_load_config_missing_file_returns_empty_dict` still returns `{}` because the seed is a no-op when unfrozen).

- [ ] **Step 5: Commit**

```bash
git add utils.py tests/test_utils_config_path.py
git commit -m "feat(config): seed config from bundled template on frozen first-run"
```

---

### Task 4: Build bundles the template instead of a live config

**Files:**
- Modify: `scripts/build_exe.ps1` (step [5/6], ~lines 39-51)

- [ ] **Step 1: Edit the build script**

Replace the step [5/6] block (the `Write-Host "[5/6] Seeding ..."` line, the comment paragraph above the `Copy-Item`, and the `Copy-Item` line) with:

```powershell
Write-Host "[5/6] Bundling config.example.json template into _internal/..." -ForegroundColor Cyan
# The live config now lives OUTSIDE the bundle at ~/.audio-transcriber/config.json
# (utils._default_config_path when frozen), so a build update never wipes the
# user's keys/settings. We bundle config.example.json as a read-only TEMPLATE;
# on first run utils._seed_default_config copies it to ~ (empty keys -> the
# first-run banner fires). sys._MEIPASS resolves to _internal in the
# PyInstaller 6.x onedir layout, so the template is found there at runtime.
$internalDir = "$bundleDir/_internal"
if (-not (Test-Path $internalDir)) {
    # Older PyInstaller layouts put modules at bundle root — detect + adapt.
    $internalDir = $bundleDir
    Write-Host "  Note: _internal/ not found; placing template at bundle root instead." -ForegroundColor Yellow
}
Copy-Item "config.example.json" "$internalDir/config.example.json" -Force
```

(Net change: the destination filename goes from `config.json` → `config.example.json`, and the comment is updated. The `$internalDir` detection logic is unchanged.)

- [ ] **Step 2: Verify the edit is internally consistent**

Run: `Select-String -Path scripts/build_exe.ps1 -Pattern "config.example.json|config.json"`
Expected: the only `config.json` references are inside the new comment; the `Copy-Item` targets `config.example.json`. (Full bundle verification happens in Task 6's rebuild.)

- [ ] **Step 3: Commit**

```bash
git add scripts/build_exe.ps1
git commit -m "build(config): bundle config.example.json as template, drop live _internal config seed"
```

---

### Task 5: Full gate — pytest + ruff

**Files:** none (verification)

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q -p no:cacheprovider`
Expected: exit code 0 (the summary line may not surface through the pipe — use `; echo "EXIT=$?"`). ~6 new config-path tests added on top of the prior green suite. The untracked `tests/test_cli_import_guard.py` is collected too and must stay green — do not modify it.

- [ ] **Step 2: Run ruff**

Run: `python -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 3: Fix any failures, then commit fixups (only if needed)**

```bash
git add utils.py tests/test_utils_config_path.py
git commit -m "chore(config): lint/test fixups for config relocation"
```

(If both are already green, skip this commit.)

---

### Task 6: Rebuild + one-time transition deploy + manual verification (the gate)

**Files:** none (manual operational step on the real Windows install)

This is the production gate. The unit tests prove the path logic; only a real
rebuild+deploy proves the transition preserves the user's keys and that a fresh
install shows the first-run banner.

- [ ] **Step 1: Migrate the existing install's keys to the new home FIRST**

Before rebuilding, lift the current keys to `~/.audio-transcriber/` (PowerShell):
```powershell
$src = "C:\Apps\AudioTranscriber\_internal\config.json"
$dst = Join-Path $env:USERPROFILE ".audio-transcriber\config.json"
New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
if (-not (Test-Path $dst)) { Copy-Item $src $dst }   # don't clobber an existing ~ config
# verify keys present (no secrets printed):
$j = Get-Content $dst -Raw | ConvertFrom-Json
"AssemblyAI key set: " + (-not [string]::IsNullOrEmpty($j.cloud_api_keys.AssemblyAI))
"meetings_dir set:   " + (-not [string]::IsNullOrEmpty($j.meetings_dir))
```
Expected: both `True`.

- [ ] **Step 2: Rebuild from this branch**

Run (venv-build active): `.\scripts\build_exe.ps1`
Then confirm the bundle has the TEMPLATE and no live config:
```powershell
Test-Path "dist\AudioTranscriber\_internal\config.example.json"   # True
Test-Path "dist\AudioTranscriber\_internal\config.json"           # False
```

- [ ] **Step 3: Deploy over C:\Apps**

Rename the current install to a `.old-<ts>` rollback, copy `dist\AudioTranscriber` into place (the live config is already safe at `~`, so no `_internal` config restore is needed this time).

- [ ] **Step 4: Verify the deployed app uses the ~ config**

Launch `C:\Apps\AudioTranscriber\AudioTranscriber.exe`. Expected: it opens with your AssemblyAI key + `meetings_dir` intact and **no first-run banner** (it read `~/.audio-transcriber/config.json`). Change a setting (e.g. appearance) → confirm it persists to `~/.audio-transcriber/config.json` (not `_internal`).

- [ ] **Step 5: Verify fresh-install behavior (first-run banner)**

Temporarily rename `~/.audio-transcriber/config.json` aside, launch the app → expect the **yellow first-run banner** (seeded template, empty keys). Close, restore your real config back.

- [ ] **Step 6: Record outcome**

If all green: the update-wipe class of bug is fixed; future client updates won't touch config. Note results in the session. If any step fails: roll back by swapping the `.old-<ts>` folder back, and return to systematic-debugging.

---

## Self-Review

**Spec coverage:**
- Frozen-aware path (`~/.audio-transcriber/config.json`) → Task 1. ✓
- Dev unchanged (repo-root) → Task 1 (source branch). ✓
- First-run seeds defaults from bundled template → Task 3. ✓
- `save_config` makedirs → Task 2. ✓
- Build bundles template, stops seeding live config → Task 4. ✓
- One-time operational transition for existing install → Task 6 (Steps 1-4). ✓
- Fresh-install first-run banner → Task 6 (Step 5). ✓
- Tests are monkeypatch-only, no `ui.app` import → all tasks. ✓
- Audit gdrive/backup.py → done in planning (operates on dict, no change). ✓
- `load_config` BOM tolerance preserved → Task 3 (read block unchanged). ✓

**Placeholder scan:** none — every step has concrete code/commands.

**Type/signature consistency:** `_default_config_path() -> str` (Task 1) used by `_CONFIG_PATH`. `_seed_default_config(path: str) -> None` (Task 3) called as `_seed_default_config(_CONFIG_PATH)` in `load_config`. `save_config(config: dict)` signature unchanged (Task 2). Existing tests patch `utils._CONFIG_PATH` (kept a module constant in Task 1) — compatible. ✓

**Out of scope (per spec):** first-run auto-migration code (operational seed is the mechanism); atomic writes; dev/frozen unification. Untracked `cli/` is the user's parallel work — not touched.
