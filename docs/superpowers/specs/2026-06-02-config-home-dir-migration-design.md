# Config relocation to `~/.audio-transcriber/` (frozen-only) — design

**Date:** 2026-06-02
**Status:** approved (brainstorming)

## Problem

The frozen app reads/writes its config from `_internal/config.json` — *inside*
the PyInstaller bundle. `utils._CONFIG_PATH = dirname(utils.py)/config.json`,
which resolves to `_internal/config.json` when frozen. Because a build replaces
the whole bundle, **every client update wipes the user's settings** (AssemblyAI
key, `meetings_dir`, all backend keys, dedup tuning). We just lived this during
the live-board rebuild: the deploy had to manually back up and restore
`_internal/config.json`. For the 3 paying clients about to go on an update
cadence, the first update would silently blank their key — a support ticket on
every release.

The build even re-seeds `config.example.json` → `_internal/config.json` on every
build (so a clean first-run shows the "enter your key" banner), which guarantees
the wipe.

## Goal

Make the frozen app store config **outside** the bundle, at
`~/.audio-transcriber/config.json` — the established app-data home already used
for `gdrive-token.json`, `directory.json`, and the rnnoise model cache. After a
one-time transition, bundle updates never touch config again.

**Scope decision (Q1): frozen-only.** Dev/source mode keeps reading the
repo-root `config.json`. Rationale: the wipe problem only exists in the frozen
build; unifying dev + frozen onto `~` would make dev experiments mutate the same
config the deployed `C:\Apps` install uses (same Windows user) — a dev/prod
collision. The cost is a single `frozen`-vs-`source` branch in the path resolver.

## Approach

### 1. Frozen-aware config path (`utils.py`)

`_CONFIG_PATH` resolves by mode:

- **Frozen** (`getattr(sys, "frozen", False)`): `~/.audio-transcriber/config.json`.
  Resolve the home dir the same way the rest of the app does (`os.path.expanduser("~")`
  / `Path.home()`, which honors `USERPROFILE` on Windows — see `gdrive/auth.py`).
- **Source** (dev): unchanged — `dirname(utils.py)/config.json` (repo root).

`load_config()` keeps its `utf-8-sig` BOM-tolerant read verbatim (a past
start-crash fix — do not regress). It still returns `{}` when the file is absent.

### 2. First-run init seeds defaults from a bundled template

The app currently *always* runs with a populated config (the build seeds it), so
switching cold to a bare `{}` is a behavior change with latent-`KeyError` risk
for any reader that indexes `config["x"]` directly. To preserve current behavior:

- Bundle `config.example.json` into the frozen app as a **read-only template**
  (e.g. at `_internal/config.example.json` via `sys._MEIPASS`), not as the live
  config.
- On frozen startup, if `~/.audio-transcriber/config.json` does not exist, create
  the directory and copy the template there. The first-run banner still fires
  because the seeded template has empty keys (`cloud_api_keys: {}`,
  `linear_api_key: ""`, …).

`save_config()` gains `os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)`
before writing, so the first save can never fail on a missing `~/.audio-transcriber/`.

### 3. Build change (`scripts/build_exe.ps1`)

Stop copying `config.example.json` → `_internal/config.json` (it would be a dead,
misleading file now that the live config lives in `~`). Instead place
`config.example.json` in the bundle as the template that step 2 reads. The
bundle therefore ships **no live `config.json`** — a fresh install creates one in
`~` on first run.

### 4. One-time transition for the existing `C:\Apps` install (operational)

This is a deploy procedure, not code. On the deploy that ships this version:

1. Copy the current `C:\Apps\AudioTranscriber\_internal\config.json` →
   `~/.audio-transcriber/config.json` (if the latter doesn't already exist).
2. Then swap in the new bundle.

The new code finds the real keys at `~` and uses them; thereafter updates are
seamless. The 3 new clients need no transition — they install the new version
fresh and first-run-init creates their `~` config.

### 5. Tests

Monkeypatch/source-text style (no `ui.app` import on CI — sounddevice/PortAudio):

- `_CONFIG_PATH` (or its resolver) → `~/.audio-transcriber/config.json` when
  `sys.frozen` is patched truthy; repo-root path otherwise.
- `save_config()` creates the parent directory when missing, then writes valid
  UTF-8 JSON readable by `load_config()`.
- First-run init: when frozen and `~` config is absent, the template is copied to
  `~` and the result has empty keys (banner-triggering).
- `load_config()` still strips a UTF-8 BOM (`utf-8-sig`) — keep the existing test.

## Out of scope (deliberate)

- **First-run auto-migration code** that reads the old `_internal/config.json`:
  our deploy replaces the whole bundle, so `_internal` is empty/seed at first run
  of the new version — reading it is unreliable. The operational seed (§4) is the
  reliable mechanism, and there is exactly one existing install.
- **Atomic config writes** — a separate robustness concern; the current
  non-atomic `save_config` has been fine. Can be a later follow-up.
- **Dev/frozen config unification** — rejected in Q1.

## Implementation audit note

Before finishing, grep for any reader of `config.json` that bypasses
`utils.load_config()` / `_CONFIG_PATH` (candidate: `gdrive/backup.py`'s
`redact_config`, which reads the config to redact keys for backup) and ensure it
follows the new path / goes through the resolver.

## Affected files

| File | Change |
|---|---|
| `utils.py` | frozen-aware `_CONFIG_PATH` (or a resolver fn); `save_config` makedirs; first-run template seed |
| `scripts/build_exe.ps1` | bundle `config.example.json` as template; stop seeding `_internal/config.json` |
| `audio_transcriber.spec` | ensure `config.example.json` is included as a data file (template) |
| `tests/` | new tests for path resolution + makedirs + first-run seed |
| `gdrive/backup.py` | audit: config read must follow the new path (if it bypasses `load_config`) |
