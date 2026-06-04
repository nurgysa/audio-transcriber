# Audit → Production-Readiness Remediation — Roadmap / Design

**Date:** 2026-06-04
**Status:** Draft for user review
**Author:** Claude (Opus 4.8) + 5-agent audit pass

## What this is

Output of a full codebase audit (architecture, correctness, security, tests/CI,
production-readiness) and the remediation roadmap to make `audio-transcriber`
genuinely production-ready for the 3-paying-client MVP and beyond.

This is an **umbrella roadmap**, not a single implementation spec. The work is
several independent workstreams (WS); each gets its own focused implementation
plan (via `writing-plans`) when we start it. This doc fixes: the findings, the
workstream boundaries + acceptance criteria, the execution order, and the
product decisions that only the user can make.

User-chosen strategy (2026-06-04): **"Хотфикс + спек"** — ship the P0 hotfix
immediately, write this roadmap in parallel, then proceed phase-by-phase with a
checkpoint at each PR merge.

## Scope guardrails (carried from CLAUDE.md invariants)

- **Cloud-only.** No local CUDA / torch / pyannote / faster-whisper / ctranslate2
  may be (re)introduced (invariant #2). Local CPU ONNX allowed only for the
  voice-ID initiative.
- `faulthandler.enable()` stays before any C-extension import (invariant #1).
- Don't liberalize `requirements.txt` pins without Windows smoke (invariant #3).
- Russian UI strings, English code/comments/commits.
- One concern per PR; topic branches; `## Summary` + `## Test plan` in every PR.
- TDD for every change; `pytest` green + `ruff check .` clean before every commit.

## Out of scope (explicitly NOT this effort)

- Tauri SaaS / lite-rewrite migrations (on hold).
- Voice-ID / speaker-attribution initiative (separate track).
- A hosted telemetry/error-reporting backend (we'll add at most a lightweight
  opt-in — see WS-7 decision D4).
- New product features. This is hardening, cleanup, and truth-in-docs only.

---

## Audit findings (consolidated, by severity)

Verification legend: ✅ verified personally · 🔁 corroborated by ≥2 agents ·
🧪 agent-reported (to confirm at implementation time).

### P0 — can burn a paying client / leak secrets

| # | Finding | Where | Status |
|---|---|---|---|
| P0-1 | `redact_config` skipped `trello_api_key`/`trello_token` → Drive backup uploaded them in cleartext | `gdrive/backup.py:46` | ✅🔁 **FIXED — PR #100** |
| P0-2 | README documents the deleted local CUDA/pyannote/torch/voice-library stack as the primary path | `README.md` | ✅ |
| P0-3 | Shipped `.exe` has **no markitdown** → doc-grounding (PR #99) is dead in the bundle | `dist/AudioTranscriber/_internal/`, build venv | ✅ |
| P0-4 | CI runs only on `ubuntu-latest`; product is Windows-only → Windows failure modes never tested | `.github/workflows/tests.yml:11` | ✅ |

### P1 — blockers before the next client wave

| # | Finding | Where | Status |
|---|---|---|---|
| P1-1 | MCP/CLI accept arbitrary file paths → an agent can exfiltrate `config.json`/`gdrive-token.json` via the transcribe/LLM round-trip | `cli/mcp_server.py:62`, `cli/app.py:126` | 🧪 |
| P1-2 | markitdown parses untrusted PDF/DOCX/XLSX with no size/time limits → zip-bomb / hang DoS | `tasks/doc_context.py:60` | 🧪 |
| P1-3 | Poll-loop `r.json()` unguarded → raw traceback instead of the Russian `ProviderError` | `providers/assemblyai.py:276`, `gladia.py:232`, `speechmatics.py:172` | 🧪 |
| P1-4 | `ffmpeg_trim` re-encode fallback can leave a corrupt/partial output file | `audio_io.py:416` | 🧪 |
| P1-5 | Deepgram sends `detect_language` with `nova-3` (incompatible; nova-3 lacks Kazakh) | `providers/deepgram.py:191` | 🧪 |
| P1-6 | Bundled GPL ffmpeg ships with **no license text** (redistribution compliance) | `vendor/ffmpeg/` | ✅ |
| P1-7 | `app.py` runs a 2nd unguarded `faulthandler.enable(open(...))` → re-opens the frozen-mode silent-crash risk if `_internal/logs/` is read-only | `app.py:13` | 🧪 |
| P1-8 | `load_config` has no `JSONDecodeError` recovery + `save_config` is non-atomic → a half-written config hard-crashes startup | `utils.py:145` | 🧪 |
| P1-9 | First-run banner checks only AssemblyAI, not OpenRouter → silent dead-end later | `ui/app/__init__.py:214` | 🧪 |
| P1-10 | Core untested: `Transcriber.transcribe` + cli/core wired only via whole-module stubs → contract drift passes green; `mcp` + real-ffmpeg tests skip silently in CI | `transcriber/__init__.py`, `tests/test_cli_*` | ✅ (2 mcp skips confirmed) |

### P2 — refactoring + hardening (the "refactoring" ask)

- **God-object** `ui/dialogs/extract_tasks/__init__.py` (2095 LOC / 72 methods / 37 business imports) — extraction/dedup/protocol/send orchestration + pricing math live in the UI. 🔁
- **God-object** `ui/dialogs/settings.py` (1005 LOC / 49 methods) — 9 integration sections + GDrive auth-reconciliation logic in the dialog. 🔁
- **Provider duplication ~80%** — identical `_check_cancel` / `_guess_content_type` / poll-loop / words→segments across 4 providers; ABC has no shared impl. ✅
- **Dead code from the rip-out (~1500 LOC incl. tests)** — `transcriber/cloud_chunker.py` (498) + `tests/test_cloud_chunker.py` (624), 3 `audio_io` fns, `DEVICES`, 4 dead `Transcriber.transcribe` params. ✅ (`test_providers_base.py:64` even asserts no provider sets `max_upload_bytes` → chunker unreachable)
- **Systemic doc drift** — `docs/ARCHITECTURE.md` (subprocess/CUDA topology), CLAUDE.md "Where things live" table (missing 6 subsystems), ~10 in-source docstrings. 🔁
- Atomic-write gap in `utils.save_segments`/`save_speakers`; `chmod 0o600` is a no-op on Windows; no `__version__`; ffprobe.exe ~100 MB dead weight (✅ confirmed bundled); no Tk `report_callback_exception`; no coverage measurement; HTTP clients don't retry 429; dead PyTorch `--extra-index-url` in CI.

### P3 — ~10 minor (stale `.pyc`, stale doc numbers, broad-except in cleanup paths, etc.) — batched opportunistically.

---

## Workstreams

Each WS = one PR (or a tight PR series). Acceptance = tests + ruff green, plus the
listed criteria. Detailed step plans authored per-WS at start time.

### WS-0 — P0 hotfix: secret redaction ✅ DONE (PR #100)
Deny-by-default redaction; Trello leak closed; +2 regression tests; suite 690 green.

### WS-7a — Delivery safety (P0-3, P1-6) — **do before any further client delivery**
- Rebuild `.venv-build` from current `requirements.txt` (on Python 3.12 per D2) so
  markitdown + its stack are present; re-bundle; add a post-build smoke that imports
  `tasks.doc_context.convert_documents` inside the frozen exe (D3: rebuild & keep).
- Add ffmpeg `COPYING.GPLv3` + `README`/source-offer to `vendor/ffmpeg/`, bundle
  them, and add `THIRD_PARTY_LICENSES.md` (ffmpeg, CustomTkinter, google libs,
  markitdown).
- **Acceptance:** frozen exe can convert a test PDF; bundle contains ffmpeg
  license text; `package_release.py` verifies both.

### WS-1 — Docs truth (P0-2 + doc drift)
- Rewrite `README.md` to cloud-only (drop GPU table, torch install, HF setup,
  voice-library, CUDA troubleshooting); align with `CLIENT_SETUP.md`.
- Rewrite `docs/ARCHITECTURE.md` to the cloud-only topology.
- Refresh CLAUDE.md "Where things live" table (+`audio_io`, `tasks/{trello_client,
  dedup,protocol_generator}`, `cli/`, `processing/`, `directory/`).
- Sweep CUDA-era docstrings (`app.py`, `audio_io.py`, `transcriber/__init__.py`,
  `ui/app/constants.py`, `transcript_format.py`).
- **Acceptance:** no doc references torch/pyannote/CUDA/voice-library as current;
  a fresh reader can install + run from README alone.

### WS-2 — Dead-code removal (rip-out residue) — D1: DELETE
- Delete `cloud_chunker.py` + its test + the `max_upload_bytes` ABC field +
  `needs_chunking` dispatch branch (collapse `_run_cloud_stt` to a direct
  `provider.transcribe()`); 3 dead `audio_io` fns; `DEVICES`; 4 dead
  `Transcriber.transcribe` params.
- **Acceptance:** suite green after deletion; no `grep` hit for the removed
  symbols outside history; LOC drops ~1500.

### WS-6 — CI + test safety net (P0-4, P1-10) — **before the big refactor**
- Add `windows-latest` to the pytest matrix; `apt-get install ffmpeg` on the
  Ubuntu leg so the real-ffmpeg parse test runs; declare `mcp` in
  `requirements-dev.txt` so MCP tests stop silently skipping.
- Add `pytest-cov` + a pragmatic `--cov-fail-under` (UI/audio_cutter omitted);
  drop the dead PyTorch `--extra-index-url`.
- Add `tests/test_transcriber_dispatch.py` (mixed-mode guard, missing-key error,
  diarize→formatter selection, denoise temp-file cleanup, ProviderError→RuntimeError
  re-wrap) and a real-wiring integration test per `cli/core.run_*`.
- **Acceptance:** CI green on Windows + Ubuntu; coverage reported + gated; no
  whole-suite silent skips.

### WS-3 — Correctness / robustness (P1-3,4,5,7,8,9 + P2 misc)
- Guard poll-loop `r.json()` (→ `ProviderError`); fix `ffmpeg_trim` partial-file
  cleanup; fix/verify Deepgram nova-3 language param; make `app.py` faulthandler a
  no-op when `sys.frozen` (hook owns it) or fall back to `%TEMP%`; add
  `JSONDecodeError` recovery + atomic `save_config`; first-run banner checks
  OpenRouter too; add Tk `report_callback_exception`; atomic
  `save_segments`/`save_speakers`.
- **Acceptance:** each behavior pinned by a test (TDD); no raw tracebacks reach
  the user for the covered paths.

### WS-5 — Security hardening (P1-1, P1-2 + Windows ACL, backup cleanup)
- Confine MCP/CLI file args to an allow-listed root; refuse `~/.audio-transcriber`
  paths; document the MCP server inherits FS rights.
- Enforce a markitdown input-size cap + timeout (run conversion killable);
  log+skip oversized docs.
- Windows owner-only ACL on `~/.audio-transcriber`; always clean backup
  `work_dir` in `finally`; `encoding="utf-8"` on backup `write_text`.
- **Acceptance:** path-traversal + oversized-doc tests; no secret-bearing temp
  left after a failed backup.

### WS-4 — Refactoring (the headline "refactoring") — **last, on the green net**
- Split `extract_tasks/__init__.py` into the dialog (view) + `ContainerController`
  / `ExtractionController` / `SendController` (plain-data, testable); move pricing
  tables next to `openrouter_client`.
- Slim `settings.py`: data-drive the 4 near-identical credential sections; move
  the GDrive backup worker + auth-reconciliation to a `gdrive` controller / mixin.
- Lift shared provider behavior (`_check_cancel`, `_guess_content_type`, a
  `_poll_until` helper, a `_words_to_segments` builder) into the ABC / a
  `providers/_http.py`.
- **Acceptance:** behavior-preserving (existing tests stay green; new controller
  unit tests added); dialogs ≤ ~600 LOC of view + binding; provider files shrink
  with no contract change.

---

## Execution order & rationale

```
WS-0 ✅  →  WS-7a  →  WS-1  →  WS-2  →  WS-6  →  WS-3  →  WS-5  →  WS-4
(hotfix)  (deliver  (docs)  (dead   (safety (correct (security (big
           safety)          code)   net)    -ness)   harden)   refactor)
```

**Why this order:** fix what can hurt a client *now* (secrets ✅, broken feature,
license) → tell the truth in docs (cheap, high trust, client-facing) → remove
dead code so the refactor target is smaller → **build the CI/test safety net
before touching the God-objects** (refactoring untested orchestration is the
single riskiest move; do it last, on green). Security hardening precedes the
refactor so the MCP/doc surfaces are safe while we still own that context.

---

## Decisions — RESOLVED 2026-06-04

- **D1 — `cloud_chunker`: → DELETE NOW.** Unreachable today (no provider sets
  `max_upload_bytes`; `tests/test_providers_base.py:64` enforces it). WS-2 removes
  it (−~1100 LOC); git history preserves it for a future capped (Groq-like) provider.
- **D2 — Python baseline: → 3.12.** What already ships. WS-1/WS-7a update
  `pyproject target-version`, README, CLIENT_SETUP, CLAUDE.md to match the bundle.
- **D3 — markitdown: → REBUILD & KEEP.** Refresh the build venv from
  `requirements.txt` so the doc-grounding feature is actually present in the exe;
  WS-7a adds a post-build smoke so it can't silently regress.
- **D4 — Client error visibility: → "Отправить лог" button.** WS-3 adds a Settings
  button that zips `logs/` + redacted config for a manual share. No backend, no
  telemetry. Opt-in webhook deferred.

---

## Verification strategy (all workstreams)

- TDD: failing test first, watched fail, minimal fix, green.
- Gate before every commit: full `pytest` (currently 690 passed / 2 skipped) +
  `ruff check .` clean. Run via `.venv-build` python (has runtime deps) — note it
  needs `pytest pytest-asyncio pytest-timeout` installed (dev-only; not bundled).
- WS-6 adds Windows-CI + coverage so regressions surface automatically thereafter.
- Behavior-preserving refactors (WS-4) rely on existing tests staying green +
  new controller-level unit tests; manual GUI smoke for the dialogs before merge.
