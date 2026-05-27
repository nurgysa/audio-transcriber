# MVP to 3 Clients — Cloud-Only Rip-Out Plan (v5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. (Subagent-driven dispatch is blocked in this environment per memory `feedback_subagent_dispatch_blocked_by_mcp_overhead`.) Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ship the existing Python `audio-transcriber` as a Windows `.zip` bundle to 3 first paying users by end of this week — cloud-only via AssemblyAI (STT + diarization) and OpenRouter (task + protocol LLM). Delete all local CUDA / Whisper / pyannote code from the codebase.

**Architecture:** Four-track work on the existing Python codebase, sequenced as: (1) **Rip-out** of `transcriber/cuda_utils.py`, `diarize_worker.py`, `enrollment_worker.py`, `voice_library.py`, `silence_remover.py`, `transcriber/segmenter.py`, `transcriber/speaker_aligner.py`, `transcriber/prompt.py`, `transcriber/progress.py`, plus heavy modifications to `transcriber/__init__.py` (drops `load_model`, `_decode_chunk_*`, hybrid path, `_launch_diarization_subprocess`); `TranscriptionCancelled` moves to `transcriber/__init__.py` top so the 6 providers' existing `from transcriber import TranscriptionCancelled` imports keep working. (2) **UI strip** removes voice-library + silence-removal + Whisper-model-size + GPU-device picker UI from `ui/dialogs/settings.py`, `ui/app/builder.py`, `ui/dialogs/voices.py`, `audio_cutter.py`; collapses provider dropdown to the 4 diarization-capable cloud STT providers (AssemblyAI / Deepgram / Gladia / Speechmatics) and deletes Groq + OpenAI Whisper provider files. (3) **PyInstaller `--onedir` bundle** trivially excludes the heavy stack (requirements.txt no longer ships it) and bundles `requests` + cloud providers + CustomTkinter + vendored ffmpeg. (4) **`tasks/protocol_generator.py`** is a new module parallel to `tasks/extractor.py`; the UI hook lives inside the existing `_run_extraction` flow in `ui/dialogs/extract_tasks/__init__.py`.

**Tech Stack:** Python 3.10+ (only Windows/cloud-friendly libs after rip-out), PyInstaller 6.x (onedir mode), AssemblyAI (default + only diarizing cloud STT in bundle UI), OpenRouter API, existing CustomTkinter UI, existing `providers/` adapter layer (minus Groq + OpenAI Whisper).

**Changes from v4 (2026-05-28 — Andas decision: «больше cuda не нужен, API буду использовать»):**

- **Scope flip:** v4 wrapped local CUDA imports behind `_LOCAL_AVAILABLE` gate to keep source-mode devs working. v5 deletes the local stack entirely from the codebase. Source mode for the dev is now also cloud-only.
- **Task 2 fully rewritten:** «Rip out local CUDA stack» — pure deletion + simplification, no `LocalEngineUnavailable`, no `_require_local()`, no try/except gate. ~70% of `transcriber/__init__.py` deleted.
- **Task 3 fully rewritten:** «Strip local-only UI affordances» — pure UI deletions (voice library section, silence-removal button, Whisper-model-size dropdown, GPU device pickers, "Голоса" dialog). Provider dropdown auto-shrinks because Groq + OpenAI Whisper provider files are deleted in Task 2.
- **Task 4 simplified:** PyInstaller spec needs no `excludes=[...]` for torch/ctranslate2/faster_whisper/pyannote/speechbrain — they're not installed anymore. No hidden-import dance for Groq + OpenAI Whisper. Smaller bundle (~150-300 MB target instead of 200-500 MB).
- **Task 7 simplified:** No `_LOCAL_AVAILABLE` first-run banner check; banner triggers solely on empty AssemblyAI key. No `cloud_enabled: true` flip in `config.example.json` (key obsolete — there's no local engine to opt out of).
- **Tasks 1, 5, 6, 8, 9 unchanged** from v4 plan with two minor wording amendments (Task 8: drop voice-library + silence-removal verifications; Task 9: drop "voice library" from feature list in client onboarding doc). Reference v4 file `docs/superpowers/plans/2026-05-27-mvp-3-clients-this-week.md` for the verbatim content.
- **`requirements.txt`** drops 8 heavy deps (`faster-whisper`, `ctranslate2`, `torch`, `torchaudio`, `pyannote.audio`, `speechbrain`, `pytorch-lightning`, `nvidia-ml-py`). Install size drops from ~6-8 GB to ~150 MB.
- **CLAUDE.md** invariants #2 (ctranslate2 before torch), #3 (unload_model), #4 (cuDNN disable), #5 (GO protocol), #7 (numpy 16kHz → Whisper), #8 (numpy 16kHz → Silero VAD) — all become obsolete because their code paths are deleted. Section rewritten to keep only #1 (faulthandler) and #6 (no liberal version pins), plus a new #2 about cloud-only architecture.
- **Test count delta:** baseline 462 → expected ~290-330 after rip-out (lose ~130-170 local-path tests) + ~13 new tests (protocol generator + UI checkbox + ffmpeg helper) = final ~305-345. Exact count emerges during execution — the plan does NOT pre-commit to a number.

---

## Context

**Why this plan exists:** 2026-05-28 follow-up to the 2026-05-27 cloud-only-MVP pivot. The user discovered that the v4 lazy-gate strategy is unnecessary complexity for their target: they will use the cloud API for personal transcription too (no longer maintaining a local-CUDA dev path). Deleting the local stack collapses maintenance burden ~50% and removes 4-6 GB of install footprint from any future contributor's setup.

**Scope decisions (locked-in 2026-05-28):**

- **Distribution:** PyInstaller `--onedir` `.exe` bundle. Final delivery = `.zip` of `dist/AudioTranscriber/`. Client extracts to `C:\Apps\AudioTranscriber\` (user-writable). Bundle target **150-300 MB**.
- **STT + diarization:** AssemblyAI only in the bundle UI (Universal model, KZ+RU+EN code-switching + built-in diarization, ~$0.17/h combined). Deepgram / Gladia / Speechmatics also retained as provider options. Groq + OpenAI Whisper provider files deleted (they lack diarization, and there is no local pyannote to fall back to).
- **Diarization default = ON** (`app._diar_var = True` at `ui/app/builder.py:134`).
- **Protocol format:** Full 5-block MoM from Tauri spec §7.9. Generated as a NEW LLM pass via existing `OpenRouterClient`.
- **Trade-off:** Quality > scope. **Trello backend dropped.** Linear + Glide sufficient.

**Out of scope (same as v4 plus expanded):**

- Any local STT or local diarize anywhere — including the `_LOCAL_AVAILABLE` gate from v4
- Voice library / speaker enrollment in any form (cloud providers expose raw "Speaker A / B / C" labels — that's the MVP behavior)
- Silence removal (Silero VAD was a local dependency)
- Whisper-model-size dropdown, GPU device picker, hf_token field (all local-only concepts)
- Phase 2 code-switching per-segment VAD (`transcriber/segmenter.py`) — AssemblyAI Universal handles code-switching natively
- Hybrid cloud-STT + local-pyannote path (`_transcribe_via_cloud_with_local_diarize`)
- Trello / macOS / Linux / MSI installer / in-app onboarding wizard
- All Tauri-spec items (vault, cross-device sync, RAG chat, MCP server)
- Maintaining v4's lazy-gate work (commit `c0426a5` was discarded — see memory `project_mvp_3_clients_this_week`)

**Daily milestone budget (5 working days, starting Wed 2026-05-28):**

| Day | Goal |
|---|---|
| Wed | Task 1 (verify clients) + Task 2 (rip-out — full day) |
| Thu | Task 3 (UI strip) + Task 4 (PyInstaller spike — much smoother than v4) |
| Fri | Task 5 (`protocol_generator` module) + Task 6 (UI integration) |
| Sat | Task 7 (bundle integration with bundled `config.json` + ffmpeg helper + banner) |
| Sun | Task 8 (clean-machine smoke at `C:\Apps\AudioTranscriber\`) + Task 9 (delivery) |

Hard gate: if Task 4 (PyInstaller) fails by EOD-Thu even after rip-out → fall back to "ship Python source + handhold install" via Skype screenshare.

---

## File Structure

### Files to DELETE entirely

| Path | Reason |
|---|---|
| `transcriber/cuda_utils.py` | `_cuda_is_available` + `_check_cancelled` + `TranscriptionCancelled` move to `transcriber/__init__.py`; `import ctranslate2` is gone |
| `transcriber/segmenter.py` | Phase 2 per-segment language-detection VAD; AssemblyAI Universal handles code-switching natively |
| `transcriber/speaker_aligner.py` | Pure-Python aligner used only by local + hybrid paths; both deleted |
| `transcriber/prompt.py` | `_build_initial_prompt` + `_effective_whisper_language` — only the local Whisper path consumed these |
| `transcriber/progress.py` | `_parse_progress_line` parsed faster-whisper subprocess output; the call site is deleted |
| `diarize_worker.py` | pyannote subprocess — no pyannote in bundle, no callers in cloud path |
| `enrollment_worker.py` | pyannote embedding subprocess — voice library is gone |
| `voice_library.py` | Speaker enrollment — feature dropped for MVP |
| `silence_remover.py` | Silero VAD wrapper — depends on `faster_whisper.vad` which is gone |
| `ui/dialogs/voices.py` | Voice library dialog — feature dropped |
| `providers/groq.py` | No diarization support; without local pyannote fallback it's unusable for MVP |
| `providers/openai_whisper.py` | Same — no diarization, no fallback |
| `tests/test_diarize_worker*.py` (if any) | Tests for deleted modules |
| `tests/test_enrollment_worker*.py` (if any) | Same |
| `tests/test_voice_library*.py` | Same |
| `tests/test_silence_remover*.py` (if any) | Same |
| `tests/test_segmenter*.py` (if any) | Same |
| `tests/test_speaker_aligner*.py` (if any) | Same |
| `tests/test_transcriber_hybrid.py` | Hybrid cloud-STT + local-pyannote path is gone |
| `tests/test_transcriber_mixed.py` | Phase 2 mixed-mode path is gone |
| `tests/test_transcriber_pure.py` | Local-only Whisper transcribe path tests — most gone (keep cloud helpers if any) |
| `tests/test_transcriber_paths.py` | `_DIARIZE_WORKER_PATH` constant deleted |
| `tests/test_providers_groq.py` | Groq provider deleted |
| `tests/test_providers_openai_whisper.py` | OpenAI Whisper provider deleted |
| `tests/test_local_engine_gate.py` | Was created by v4 Task 2 (commit `c0426a5`, discarded) — never landed on main, so no deletion needed; confirm with `git ls-files tests/test_local_engine_gate.py` returning empty |

(Run `pytest --collect-only -q | findstr /R "test_diariz test_enrollment test_voice test_silence test_segment test_speaker test_transcriber_hybrid test_transcriber_mixed test_transcriber_paths test_providers_groq test_providers_openai_whisper"` BEFORE deleting to get the actual file list and avoid missing a test file.)

### Files to MAJORLY MODIFY

| Path | Change summary |
|---|---|
| `transcriber/__init__.py` | Strip ~70% of contents. Keep: `Transcriber` class (cloud-only, simpler `__init__` without `model_size` / `device` / `compute_type` / `beam_size`); `transcribe()` dispatches to cloud only; `_transcribe_via_cloud` + `_run_cloud_stt` retained verbatim. Move `TranscriptionCancelled` and `_check_cancelled` here (they were in `cuda_utils.py`). Drop: `load_model`, `offload_to_cpu`, `_get_device`, `_get_compute_type`, `_cuda_is_available`, `_DIARIZE_WORKER_PATH`, `_LONG_FILE_THRESHOLD_S`, `_CHUNK_DURATION_S`, `_CHUNK_OVERLAP_S`, `_write_crash_log`, `_launch_diarization_subprocess`, `_await_diarization_subprocess`, `_transcribe_via_cloud_with_local_diarize`, `_decode_chunk_single`, `_decode_chunk_mixed`, plus their helper imports (`from .segmenter`, `from .speaker_aligner`, `from .prompt`, `from .progress`, `from faster_whisper import WhisperModel`). Update `__all__`. |
| `transcriber/cloud_chunker.py` | Single line change: `from .cuda_utils import TranscriptionCancelled` → `from . import TranscriptionCancelled` (one level up to the package). |
| `ui/app/transcription_mixin.py` | Strip ~50%. Delete: voice library temp-file path (lines ~127-149), hybrid-path special-case (lines ~181-220), `hf_token` resolution, `_tr_device_var` / `_di_device_var` / `_model_var` reads, `_transcriber.load_model()` call (line ~317), local device-label logic (line ~318), `voice_lib_path` parameter plumbing (lines 267, 302, 333, 371-374). Result: a simple cloud-only `_run_transcription_thread` that constructs `Transcriber(...)` with no args, calls `transcribe(audio_path, language=..., diarize=..., cloud_provider=..., cloud_api_key=..., hotwords=..., denoise_audio=...)`. |
| `ui/app/builder.py` | Delete: `app._model_var` (line 131), `app._tr_device_var` (line 151), `app._di_device_var` (line 155), their associated CTkOptionMenu widgets, plus the "Голоса" button + voice-library status label. Flip `app._diar_var = ctk.BooleanVar(value=True)` (line 134; was False). Keep banner-row scaffolding for Task 7. |
| `ui/dialogs/settings.py` | Delete: "Голоса" button + voice library section (~lines 427-432); "Whisper модель" dropdown; "Транскрипция: устройство" dropdown; "Диаризация: устройство" dropdown; "HuggingFace токен" field; "Удаление тишины" controls (if any). Keep: cloud-provider dropdown (filter list to `["AssemblyAI", "Deepgram", "Gladia", "Speechmatics"]` — the registry already won't have Groq / OpenAI Whisper after their files are deleted); per-provider API-key fields; OpenRouter section; Linear / Glide sections; Google Drive section. |
| `audio_cutter.py` | Find silence-removal button(s) (`Grep -n "silence\|тишин"`). Delete the button widgets + their command handlers. Delete `from silence_remover import …` if present. Keep all other manual-trim / preview / export features. |
| `requirements.txt` | Delete lines: `faster-whisper`, `ctranslate2`, `torch`, `torchaudio`, `pyannote.audio`, `speechbrain`, `pytorch-lightning`, `nvidia-ml-py`. Keep: `customtkinter`, `psutil`, `requests`, `soundfile`, `sounddevice`, `scipy`, `numpy`, `google-auth*`. |
| `CLAUDE.md` | Rewrite the **Hard invariants** section to remove obsolete entries (#2 ctranslate2-before-torch, #3 unload_model, #4 cuDNN, #5 GO-protocol, #7 16k-mono-to-Whisper, #8 16k-mono-to-VAD). Renumber and keep #1 (faulthandler) + #6 (no liberal pins). Add new #2: «No local CUDA / pyannote / faster-whisper code may be reintroduced — codebase is cloud-only since 2026-05-28 rip-out». Drop the "Diarization subprocess" section, the "Where things live" rows for `diarize_worker.py` / `enrollment_worker.py` / `voice_library.py` / `silence_remover.py`. Update the test-baseline parenthetical to whatever the actual post-rip-out number is. |

### Files to LIGHTLY MODIFY

| Path | Change |
|---|---|
| `audio_io.py` | Only if `Grep -n "ensure_16khz_mono\|load_mono_float32"` shows ALL callers are in deleted files: delete those two functions. Otherwise keep verbatim — cloud chunker and audio cutter both use ffmpeg helpers from here. |
| `providers/__init__.py` | Remove `"Groq"` and `"OpenAI Whisper"` (or whatever the display-name keys are — verify by reading) from the `PROVIDERS` dict. |
| `pytest.ini` / `pyproject.toml` | No change unless ruff/pytest collects deleted dirs differently. Re-run after deletions to confirm. |
| `README.md` | Drop GPU / HuggingFace / voice-library / silence-removal language. Add: "cloud-only, requires AssemblyAI + OpenRouter API keys; no GPU needed". |
| `.github/workflows/tests.yml` | Confirm CI installs the trimmed `requirements.txt` (no torch on the runner means faster CI). No code change unless the workflow explicitly mentions torch. |

### Files to LEAVE UNTOUCHED

`tasks/*` (extractor, sender, schema, persistence, linear_client, glide_client, openrouter_client, errors, backends/*); `gdrive/*` (auth, client, backup); `providers/{assemblyai,deepgram,gladia,speechmatics}.py`; `providers/base.py`; `recorder.py`; `transcript_format.py`; `logging_setup.py`; `utils.py`; `ui/dialogs/{extract_tasks,history,terms,system_monitor}*`; `ui/app/{__init__,recorder_mixin,save_mixin,settings_mixin,dialogs_mixin}.py` (Task 3 only touches `builder.py` + `transcription_mixin.py`); `ui/widgets/*`; `transcriber/cloud_chunker.py` (one-line import change only); `app.py`; `config.example.json` (Task 7 will adjust); CI / pre-commit configs.

---

## Task Inventory

| # | Task | Status | Reference |
|---|---|---|---|
| 1 | Verify clients | Unchanged from v4 | `docs/superpowers/plans/2026-05-27-mvp-3-clients-this-week.md` §128-146 |
| 2 | **Rip out local CUDA stack** | **Rewritten v5** | this document |
| 3 | **Strip local-only UI affordances** | **Rewritten v5** | this document |
| 4 | **PyInstaller spike (simplified)** | **Rewritten v5** | this document |
| 5 | Protocol generator module | Unchanged from v4 | v4 §972-1007 |
| 6 | UI integration for protocol checkbox | Unchanged from v4 | v4 §1011-1167 |
| 7 | **Bundle integration (simplified)** | **Rewritten v5** | this document |
| 8 | Clean-machine smoke | Mostly unchanged | v4 §1387-1471 (Step 3 checklist: drop the voice-library + silence-removal items) |
| 9 | Delivery | Mostly unchanged | v4 §1475-1593 (CLIENT_SETUP.md: drop "voice library" from feature list) |

---

## Task 2: Rip out local CUDA stack

**Files to delete:** `transcriber/cuda_utils.py`, `transcriber/segmenter.py`, `transcriber/speaker_aligner.py`, `transcriber/prompt.py`, `transcriber/progress.py`, `diarize_worker.py`, `enrollment_worker.py`, `voice_library.py`, `silence_remover.py`, `providers/groq.py`, `providers/openai_whisper.py`, plus their test files (see Step 2 below for enumeration).

**Files to modify:** `transcriber/__init__.py`, `transcriber/cloud_chunker.py`, `providers/__init__.py`, `requirements.txt`, `CLAUDE.md`, `audio_io.py` (conditional), `pyproject.toml` (conditional ruff exclusions check).

**Files to create:** None.

### Subtask 2a: Baseline + inventory

- [ ] **Step 1: Baseline**

```powershell
git status         # must be clean
git branch --show-current   # confirm on the rip-out branch (e.g. refactor/cloud-only-rip-out)
python -m pytest --tb=no -q  # record the exact pre-change passing count
python -m ruff check .       # must say "All checks passed!"
```

Record the baseline count (expected ~462). Use it later to sanity-check the post-rip-out delta.

- [ ] **Step 2: Enumerate test files that import deleted modules**

```powershell
# Find every test file that imports any of the modules being deleted.
# This list is the deletion target for Step 9 below.
python -c "import subprocess; subprocess.run(['python','-m','pytest','--collect-only','-q'], check=False)" | findstr /R "test_diariz test_enrollment test_voice test_silence test_segment test_speaker test_transcriber_hybrid test_transcriber_mixed test_transcriber_paths test_providers_groq test_providers_openai_whisper"
```

(If the `findstr` produces nothing, fall back to a manual `Grep -l "cuda_utils\|diarize_worker\|enrollment_worker\|voice_library\|silence_remover\|segmenter\|speaker_aligner\|faster_whisper\|pyannote\|ctranslate2" tests/`.)

Note the exact file list. This is the test-deletion manifest.

### Subtask 2b: Delete provider files

- [ ] **Step 3: Delete `providers/groq.py` + `providers/openai_whisper.py`**

```powershell
Remove-Item providers/groq.py
Remove-Item providers/openai_whisper.py
```

- [ ] **Step 4: Update `providers/__init__.py`**

Read it first (small file). Find the `PROVIDERS` registry dict. Remove the `"Groq"` and `"OpenAI Whisper"` entries (or whatever the display-name keys are — verify by reading first; per memory `feedback_read_actual_code_before_writing_plan_pseudocode` do NOT invent the key names). Remove the corresponding `from .groq import GroqProvider` + `from .openai_whisper import OpenAIWhisperProvider` import lines.

- [ ] **Step 5: Delete provider test files**

```powershell
Remove-Item tests/test_providers_groq.py
Remove-Item tests/test_providers_openai_whisper.py
```

- [ ] **Step 6: Spot-check provider tests still pass**

```powershell
python -m pytest tests/test_providers_assemblyai.py tests/test_providers_deepgram.py tests/test_providers_gladia.py tests/test_providers_speechmatics.py tests/test_providers_base.py -v
```

Expected: all green. If `test_providers_base.py` references Groq / OpenAI Whisper, edit those references out (likely a `pytest.mark.parametrize` of provider names). Do not invent — read first.

### Subtask 2c: Rewrite `transcriber/__init__.py` to cloud-only

- [ ] **Step 7: Move `TranscriptionCancelled` + `_check_cancelled` into `transcriber/__init__.py`**

Read the current `transcriber/cuda_utils.py` (small file, ~50 lines on main). Copy the `TranscriptionCancelled` class + `_check_cancelled` function definitions into `transcriber/__init__.py`, placed near the top of the file just below the imports + just above the existing `logger = …` line. Keep the same docstrings.

- [ ] **Step 8: Strip `transcriber/__init__.py`**

This is the largest single edit in the rip-out. Read the current file end-to-end first (it's ~1300 lines after Phase 2). Identify and DELETE these blocks (function and class boundaries — verify by reading, don't rely on the line numbers below if they've drifted):

| What | Approximate line range (verify on read) |
|---|---|
| `# isort: off` header through the cuda_utils import block | 1-12 |
| `from faster_whisper import WhisperModel` line | 22 |
| `from .progress import _parse_progress_line` | 34 |
| `from .prompt import _build_initial_prompt, _effective_whisper_language` | 35 |
| `from .segmenter import vad_split` | 36 |
| `from .speaker_aligner import (...)` block | 37-42 |
| `_DIARIZE_WORKER_PATH` constant + comment | 47-58 |
| `_LONG_FILE_THRESHOLD_S` / `_CHUNK_DURATION_S` / `_CHUNK_OVERLAP_S` constants + comments | 81-109 |
| `Transcriber.__init__` `model_size`, `device`, `compute_type`, `beam_size` params + their state fields | 115-127 |
| `Transcriber.model_size` property | 134 |
| `Transcriber._get_device` method | 137-154 |
| `Transcriber._get_compute_type` method | 156-178 |
| `Transcriber.device` property | 180-185 |
| `Transcriber.load_model` method | 187-207 |
| `Transcriber.offload_to_cpu` method | 209-235 |
| `Transcriber._write_crash_log` method | 237-265 |
| `Transcriber._launch_diarization_subprocess` method | 267-405 |
| `Transcriber._await_diarization_subprocess` method | 408-497 |
| `Transcriber._transcribe_via_cloud_with_local_diarize` method | 661-815 (post `_run_cloud_stt`) |
| `Transcriber._decode_chunk_single` method | 818-925 |
| `Transcriber._decode_chunk_mixed` method | 927-1058 |
| Local branch inside `Transcriber.transcribe()` | inside ~lines 1060-1300; identify by `if not cloud_provider:` / `else:` structure |

Keep:
- `Transcriber._transcribe_via_cloud` (~line 499)
- `Transcriber._run_cloud_stt` (~line 584)
- The cloud-dispatch portion of `Transcriber.transcribe()` (cloud_provider short-circuit)
- `logger = get_logger(__name__)`
- The `crash_log_path` import IF cloud paths use it (verify; likely safe to drop)

Add at the top of the file:

```python
"""Cloud-only audio transcription dispatcher.

Wraps the providers/ ABC for the UI layer. Local CUDA / Whisper / pyannote
code was removed in the 2026-05-28 rip-out — see
docs/superpowers/plans/2026-05-28-cloud-only-mvp-v5.md Task 2. The
TranscriptionCancelled exception (cancel-button → worker thread) lives in
this module because the 6 cloud providers import it as
`from transcriber import TranscriptionCancelled` (see providers/assemblyai.py:315
and 5 siblings).
"""
from __future__ import annotations

from logging_setup import get_logger
from transcript_format import format_diarized, format_timed

logger = get_logger(__name__)


class TranscriptionCancelled(Exception):
    """Raised inside :meth:`Transcriber.transcribe` when the cancel event fires.

    Caught in ``ui.app._run_transcription`` and routed to a "cancelled" UI
    state distinct from the "error" path — the user asked to stop, so
    we don't show a scary error dialog.
    """


def _check_cancelled(cancel_event) -> None:
    """Raise :class:`TranscriptionCancelled` if the event is set."""
    if cancel_event is not None and cancel_event.is_set():
        raise TranscriptionCancelled()


__all__ = [
    "Transcriber",
    "TranscriptionCancelled",
    "_check_cancelled",
]
```

Then the trimmed `Transcriber` class (cloud-only):

```python
class Transcriber:
    """Cloud-only transcription dispatcher.

    Constructor takes no model/device/compute_type — those were local-Whisper
    knobs that have no meaning in the cloud-only build. `transcribe()` accepts
    a `cloud_provider` + `cloud_api_key` pair and routes through the
    providers/ ABC.
    """

    def __init__(self) -> None:
        # No state. Kept as a class so the UI's existing
        # `self._transcriber = Transcriber(...)` calls don't need refactoring
        # beyond dropping the constructor args.
        self.last_segments: list[dict] | None = None

    # _transcribe_via_cloud + _run_cloud_stt + the cloud dispatch in
    # transcribe() carry over verbatim from main — paste them in unchanged.
```

(The actual `_transcribe_via_cloud`, `_run_cloud_stt`, and `transcribe()` cloud-branch code is dozens of lines. The execution agent must COPY them verbatim from the current `transcriber/__init__.py` rather than retyping. Use `git show HEAD:transcriber/__init__.py` to grab them if the working copy is mid-edit.)

- [ ] **Step 9: Run pytest, expect MANY failures from tests of deleted code**

```powershell
python -m pytest --tb=line -q 2>&1 | findstr /R "FAILED ERROR"
```

The failures should be confined to: tests in the deletion manifest from Step 2, plus any test that does `from transcriber import _build_initial_prompt` / `_assign_speakers_word_level` / `_LONG_FILE_THRESHOLD_S` / etc. (helpers re-exported via the old `__all__`).

Do NOT try to fix these failures individually — they're going away in Step 10.

### Subtask 2d: Delete dependent files + tests

- [ ] **Step 10: Bulk-delete the local stack**

```powershell
Remove-Item transcriber/cuda_utils.py
Remove-Item transcriber/segmenter.py
Remove-Item transcriber/speaker_aligner.py
Remove-Item transcriber/prompt.py
Remove-Item transcriber/progress.py
Remove-Item diarize_worker.py
Remove-Item enrollment_worker.py
Remove-Item voice_library.py
Remove-Item silence_remover.py
```

Then bulk-delete the test files from the deletion manifest (Step 2):

```powershell
# Substitute the file list from your Step 2 inventory; example:
Remove-Item tests/test_transcriber_hybrid.py
Remove-Item tests/test_transcriber_mixed.py
Remove-Item tests/test_transcriber_paths.py
# tests/test_transcriber_pure.py: read first — if some tests cover cloud
# helpers that survived, KEEP those tests and delete only the local ones.
# Otherwise delete entirely.
```

- [ ] **Step 11: Fix `transcriber/cloud_chunker.py` import**

Read the file. Find the line `from .cuda_utils import TranscriptionCancelled` (around line 1-20). Replace with:

```python
from . import TranscriptionCancelled
```

(One level up — `transcriber/__init__.py` now exports it.)

- [ ] **Step 12: Run pytest, sweep the remaining import errors**

```powershell
python -m pytest --tb=short -q 2>&1 | findstr /R "ImportError ModuleNotFoundError"
```

Each surviving error points at a callsite I missed — either a test that imports a deleted name, or production code that still references one. Fix each:

- If it's a **test** file: most likely should be deleted (covered deleted code). Add it to the manifest and delete.
- If it's a **production** file (in `ui/`, `tasks/`, `providers/`, etc.): the import is reachable from cloud code — that means I missed a callsite during the strip. Trace it: who calls this function from the cloud path? If genuinely cloud, restore the function or move it to a new home. If only the local path called it, delete the call site.

Common surviving callsites to verify:
- `ui/app/transcription_mixin.py` — Task 3 will clean this up; for now, comment out the line and add a `# TODO Task 3` marker if removing it breaks the file's syntax.
- `audio_cutter.py` — Task 3 will clean up silence removal; same comment-out-with-marker tactic if needed mid-Task-2.
- `ui/dialogs/voices.py` — gets deleted in Task 3; but it might be imported eagerly by `ui/app/dialogs_mixin.py` or similar. If so, leave the file in place until Task 3 deletes it AND its callers together.

The goal of Step 12 is to get pytest collection back to a clean state — every remaining test must either pass or fail-with-actual-assertion (not import-error).

- [ ] **Step 13: Update `audio_io.py` if applicable**

```powershell
# Find callers of ensure_16khz_mono + load_mono_float32 across the codebase.
```

Use Grep with pattern `ensure_16khz_mono|load_mono_float32` across the repo. If ALL surviving callers are in deleted files (and thus the call sites no longer exist), delete these two functions from `audio_io.py`. If anything in `ui/`, `tasks/`, `providers/`, `recorder.py`, `audio_cutter.py`, or `transcriber/cloud_chunker.py` still calls them, keep them.

(Most likely: `ensure_16khz_mono` was used by the local Whisper path AND has no cloud callers → delete. `load_mono_float32` was used by `_decode_chunk_mixed` only → delete.)

- [ ] **Step 14: Update `requirements.txt`**

Delete these lines:

```text
faster-whisper==1.2.1
ctranslate2==4.7.1
torch==2.11.0+cu126
torchaudio==2.11.0+cu126
pyannote.audio==4.0.4
speechbrain==1.1.0
pytorch-lightning==2.6.1
nvidia-ml-py==12.560.30
```

Keep everything else. Result: ~10 lines instead of ~18.

- [ ] **Step 15: Run pytest + ruff for the FIRST clean post-rip-out signal**

```powershell
python -m pytest --tb=no -q
python -m ruff check .
```

Expected: pytest passes (count is whatever it shaped up to be — record it). Ruff is clean (may flag unused imports if the strip left orphans — `python -m ruff check . --fix` will mop those up).

If pytest count is suspiciously high (>400), Step 10 may have under-deleted — go through each deleted module and confirm its test file is also gone. If <250, possibly over-deleted — restore the cloud test files (`test_providers_assemblyai.py` + 4 siblings, `test_cloud_chunker.py`, etc.).

### Subtask 2e: Update CLAUDE.md + commit

- [ ] **Step 16: Rewrite CLAUDE.md invariants**

Read the current `CLAUDE.md`. Find the **Hard invariants — DO NOT BREAK** section. Replace it with:

```markdown
## Hard invariants — DO NOT BREAK

1. **Faulthandler must initialize before any C-extension import.** See
   `app.py:13-16`. ctranslate2/torch are gone after the 2026-05-28 rip-out,
   but other native deps (soundfile, sounddevice) can still SIGSEGV during
   shutdown; faulthandler buys diagnostics.
2. **No local CUDA / pyannote / faster-whisper / ctranslate2 / torch code
   may be reintroduced.** Codebase is cloud-only since the 2026-05-28
   rip-out (commit `<RIPOUT_COMMIT_SHA>`). Adding any of those imports
   anywhere — `transcriber/`, `tasks/`, `ui/`, `providers/`, tests,
   anywhere — is a regression. If a feature truly needs local inference,
   open a discussion before coding.
3. **Do not "liberalize" version pins in `requirements.txt`.** Even after
   the cloud-only trim, the remaining pins (CustomTkinter / soundfile /
   sounddevice / google-auth versions) are load-bearing on Windows.
```

Delete the now-obsolete sections:
- The "Diarization subprocess" + GO-protocol invariants (old #5)
- The 16k-mono-to-Whisper / 16k-mono-to-VAD invariants (old #7 / #8)
- The "Unload Whisper" invariant (old #3)
- The cuDNN invariant (old #4)

Also update the **Where things live** table to remove the rows for: `diarize_worker.py`, `enrollment_worker.py`, `voice_library.py`, `silence_remover.py`, `audio_cutter.py` silence-removal description, voice-library description, and the `transcriber/segmenter`, `speaker_aligner`, `prompt`, `progress`, `cuda_utils` submodule mentions in the transcriber row.

Update the **Test + lint contract** section's test-count parenthetical to the actual post-rip-out number from Step 15. Add a one-line note: «2026-05-28: ~135 local-path tests deleted in the cloud-only rip-out; baseline reset.»

- [ ] **Step 17: Commit the rip-out**

```powershell
git add -A
git status     # eyeball before committing — should show ~12 deletions + ~6 modifications
git commit -m "refactor: rip out local CUDA / pyannote / faster-whisper stack — cloud-only

Removes the local-inference code path (Whisper, pyannote, voice library,
silence removal, Phase 2 mixed-language VAD) and the hybrid cloud-STT +
local-diarize route. The MVP ships cloud-only via AssemblyAI; maintaining
two transcription pipelines was a velocity tax.

Deleted modules: transcriber/cuda_utils.py, transcriber/segmenter.py,
transcriber/speaker_aligner.py, transcriber/prompt.py, transcriber/progress.py,
diarize_worker.py, enrollment_worker.py, voice_library.py, silence_remover.py,
providers/groq.py, providers/openai_whisper.py.

TranscriptionCancelled relocated from transcriber/cuda_utils to
transcriber/__init__.py so the 6 providers' existing
'from transcriber import TranscriptionCancelled' imports keep working
unchanged. transcriber/cloud_chunker.py import updated to match.

requirements.txt drops 8 heavy deps (torch / torchaudio / ctranslate2 /
faster-whisper / pyannote.audio / speechbrain / pytorch-lightning /
nvidia-ml-py). Install footprint drops from ~6-8 GB to ~150 MB.

CLAUDE.md hard-invariants section rewritten — invariants #2/#3/#4/#5/#7/#8
are obsolete (their code paths are gone). New invariant #2 documents the
cloud-only constraint going forward.

Test count: 462 → <ACTUAL_POST_RIPOUT_COUNT> (lost ~135 local-path tests;
Tasks 5-7 will add back ~13 protocol + UI + ffmpeg tests for a final
~310-330).

Plan: docs/superpowers/plans/2026-05-28-cloud-only-mvp-v5.md Task 2."
```

(Substitute `<ACTUAL_POST_RIPOUT_COUNT>` with the real number from Step 15.)

---

## Task 3: Strip local-only UI affordances

**Files to modify:** `ui/app/builder.py`, `ui/app/transcription_mixin.py`, `ui/dialogs/settings.py`, `audio_cutter.py`.
**Files to delete:** `ui/dialogs/voices.py` (plus any `tests/test_*voices*.py` not already caught in Task 2 Step 10).
**Files to create:** `tests/test_bundle_ui_only.py` — source-text smoke checks that the deleted affordances actually stay deleted.

- [ ] **Step 1: Write failing source-text tests**

Create `tests/test_bundle_ui_only.py`:

```python
"""Source-text checks that local-only UI affordances are deleted.

Linux CI doesn't import ui/ (per memory feedback_ui_app_import_breaks_linux_ci),
so we verify deletion by reading file content rather than instantiating widgets.
"""
from pathlib import Path


def test_voices_dialog_deleted():
    assert not Path("ui/dialogs/voices.py").exists(), \
        "ui/dialogs/voices.py must be deleted in the cloud-only build"


def test_settings_has_no_voice_library_section():
    src = Path("ui/dialogs/settings.py").read_text(encoding="utf-8")
    assert "Голоса" not in src, "voice library button must be removed from Settings"
    assert "_open_voices_dialog" not in src, "voices dialog launcher must be removed"


def test_settings_has_no_model_size_picker():
    src = Path("ui/dialogs/settings.py").read_text(encoding="utf-8")
    # Whisper model size dropdown is local-only — verify removal
    for marker in ["Whisper", "whisper_model", "model_size"]:
        assert marker not in src, f"Settings still mentions {marker!r}"


def test_settings_has_no_device_picker():
    src = Path("ui/dialogs/settings.py").read_text(encoding="utf-8")
    # Both transcription + diarization device pickers are local-only
    assert "tr_device" not in src and "di_device" not in src, \
        "device pickers must be removed from Settings"


def test_settings_has_no_hf_token_field():
    src = Path("ui/dialogs/settings.py").read_text(encoding="utf-8")
    assert "hf_token" not in src.lower() and "huggingface" not in src.lower(), \
        "HuggingFace token field must be removed (pyannote is gone)"


def test_builder_has_no_local_state_vars():
    src = Path("ui/app/builder.py").read_text(encoding="utf-8")
    for marker in ["_model_var", "_tr_device_var", "_di_device_var"]:
        assert marker not in src, f"builder.py still declares {marker!r}"


def test_builder_diarize_default_is_true():
    src = Path("ui/app/builder.py").read_text(encoding="utf-8")
    # Diarization default ON for AssemblyAI MVP — clients shouldn't have to
    # toggle a checkbox to get speaker labels.
    import re
    m = re.search(r"_diar_var\s*=\s*ctk\.BooleanVar\([^)]*value\s*=\s*True", src)
    assert m, "_diar_var must default to True for AssemblyAI diarization to engage"


def test_audio_cutter_has_no_silence_remove_button():
    src = Path("audio_cutter.py").read_text(encoding="utf-8")
    # Both Russian + English markers; one of them must have been in the original
    for marker in ["remove_silences", "silence_remov", "Удаление тишины", "Убрать тишину"]:
        assert marker not in src, f"audio_cutter.py still references {marker!r}"


def test_transcription_mixin_has_no_load_model_call():
    src = Path("ui/app/transcription_mixin.py").read_text(encoding="utf-8")
    assert "load_model" not in src, "load_model() is gone — cloud-only Transcriber"
    assert "_transcriber.load_model" not in src
    assert "hf_token" not in src.lower(), "hf_token plumbing must be removed"
    assert "voice_lib_path" not in src, "voice_lib_path plumbing must be removed"


def test_provider_registry_drops_local_dependent():
    src = Path("providers/__init__.py").read_text(encoding="utf-8")
    # Groq + OpenAI Whisper lacked diarization and depended on the
    # (now-deleted) hybrid path. Both provider files are gone.
    assert "Groq" not in src and "OpenAIWhisper" not in src, \
        "Groq + OpenAI Whisper must be removed from the PROVIDERS registry"
```

- [ ] **Step 2: Run, watch fail**

```powershell
python -m pytest tests/test_bundle_ui_only.py -v
```

Expected: all 9 tests fail (UI not stripped yet).

- [ ] **Step 3: Delete the voices dialog**

```powershell
Remove-Item ui/dialogs/voices.py
```

- [ ] **Step 4: Strip `ui/dialogs/settings.py`**

Read the file end-to-end. Identify and remove:
- The "Голоса" button + voice-library status label (around line 427)
- Any "Whisper модель" / model_size dropdown
- Any "Транскрипция: устройство" / `_tr_device_var` widget
- Any "Диаризация: устройство" / `_di_device_var` widget
- Any "HuggingFace токен" / `hf_token` field + its label
- Any silence-removal toggle (if Settings had one — most likely it didn't; audio_cutter.py has the actual button)

Keep:
- The cloud-provider dropdown — but check what list it pulls from. If it iterates `PROVIDERS.keys()`, no change needed (the registry already lost Groq + OpenAI Whisper in Task 2). If it has a hardcoded list, trim it to `["AssemblyAI", "Deepgram", "Gladia", "Speechmatics"]`.
- The per-provider API-key fields (loop over `PROVIDERS.keys()`)
- OpenRouter, Linear, Glide, Google Drive sections
- The `_apply_settings()` save handler (verify it no longer touches deleted config keys)

After each removal, also remove the corresponding lines from `_apply_settings()` (the save handler that writes to `self._config[...]`).

- [ ] **Step 5: Strip `ui/app/builder.py`**

Read the file. Find these state declarations + their widget construction:

| State var | Widget | Action |
|---|---|---|
| `app._model_var` (line ~131) + the CTkOptionMenu wired to it | "Whisper модель" picker | Delete both lines |
| `app._tr_device_var` (line ~151) + its CTkOptionMenu | "Транскрипция: устройство" picker | Delete |
| `app._di_device_var` (line ~155) + its CTkOptionMenu | "Диаризация: устройство" picker | Delete |
| `app._diar_var = ctk.BooleanVar(value=False)` (line ~134) | Diarize checkbox | CHANGE value to `True` (keep var + checkbox — AssemblyAI uses it) |

If deleting these widgets leaves empty `padx` / `pady` / `row=N` grid holes, re-flow the surrounding `grid(...)` calls to be contiguous. Don't leave dead rows that shift the layout's perceived alignment.

- [ ] **Step 6: Strip `ui/app/transcription_mixin.py`**

Read the file end-to-end. Identify and DELETE these blocks (verify via grep):

| Concern | Approximate location (verify on read) |
|---|---|
| Voice library temp-file creation | Lines ~127-149 (`voice_lib_path = None; if voices_from_config(...): tmp.write(...)`) |
| Hybrid-path special-case + Russian error about Groq/OpenAI Whisper not diarizing | Lines ~181-220 (`if cloud_enabled and diarize:`) — the entire branch can go, plus its diagnostic + error messages, because Groq + OpenAI Whisper are no longer in the registry |
| `hf_token` resolution + the `if diarize and not hf_token and not cloud_enabled:` error | Lines ~222-230 |
| `_tr_device_var` / `_di_device_var` reads + the resulting `tr_device` / `di_device` variables | Lines ~234-250 |
| `if not cloud_enabled: self._transcriber.load_model()` + `device_label = ...` | Lines ~317-318 — entire local branch of the dispatch |
| `voice_lib_path` parameter in `_run_transcription_thread` + its cleanup | Lines 267 (call), 302 (signature), 333 (pass-through), 371-374 (cleanup) |

Result: a much shorter `_run_transcription_thread` that:
1. Reads `cloud_provider_name = self._cloud_provider_var.get()`, `cloud_api_key = self._cloud_api_keys.get(cloud_provider_name, "").strip()`
2. Raises a Russian error if `cloud_api_key` is empty (existing logic, keep)
3. Constructs `Transcriber()` (no args after Task 2)
4. Calls `transcriber.transcribe(audio_path, language=..., diarize=..., cloud_provider=..., cloud_api_key=..., hotwords=..., denoise_audio=...)` — let the providers do their thing
5. Catches `TranscriptionCancelled` for the cancel path, `ProviderError` for clean errors, generic `Exception` for unknowns

If `cloud_enabled` / `self._cloud_enabled_var` is now redundant (everything is cloud), keep the var for backward-compat with `config.json` parsing but skip the conditional — always cloud.

- [ ] **Step 7: Strip silence removal from `audio_cutter.py`**

Read the file. Use `Grep -n "silence\|тишин\|remove_silences"` to find:
- The "Убрать тишину" / "Remove silences" button + its grid call
- The button's `command=` handler method
- The handler method body itself (often calls `silence_remover.remove_silences(...)`)
- The `from silence_remover import …` import line

Delete all of the above. Keep the rest of `audio_cutter.py` (manual trim, preview, export — all useful cloud-side).

- [ ] **Step 8: Run pytest + ruff**

```powershell
python -m pytest tests/test_bundle_ui_only.py -v
python -m pytest --tb=short -q
python -m ruff check .
```

Expected: all 9 new UI-strip tests pass; full suite green; ruff clean (auto-fix orphaned imports with `--fix` if needed).

- [ ] **Step 9: Manual source-mode smoke**

```powershell
python app.py
```

Manual checks:
- Main window opens normally
- Settings dialog: no Whisper model picker, no device pickers, no HF token, no voice library section
- Provider dropdown shows AssemblyAI / Deepgram / Gladia / Speechmatics ONLY
- Diarize checkbox is checked by default
- Audio Cutter (if opened): no "Убрать тишину" button; manual trim still works
- Drop a short audio file → click Транскрибировать (assumes valid AssemblyAI key in `config.json`) → transcript with speaker labels appears

If something is missing or broken, the smoke is the truth — fix the code, not the smoke. Per memory `feedback_run_app_from_main_not_worktree`, run from the actual project directory.

- [ ] **Step 10: Commit Task 3**

```powershell
git add -A
git status
git commit -m "feat(ui): strip local-only affordances for cloud-only build

Removes UI surfaces that the post-rip-out backend can no longer service:
- Settings 'Голоса' voice-library section
- Settings Whisper model size dropdown
- Settings transcription + diarization device pickers (GPU/CPU/Auto)
- Settings HuggingFace token field
- Audio Cutter silence-removal button + handler
- ui/dialogs/voices.py (entire file)
- _model_var / _tr_device_var / _di_device_var state in ui/app/builder.py

Flipped: ui/app/builder.py _diar_var default False → True. Without this,
AssemblyAI returns transcripts with no speaker labels — contradicts the
'качественная диаризация' goal that motivates AssemblyAI Universal.

Stripped ~50% of ui/app/transcription_mixin.py (voice-library plumbing,
hybrid-path dispatch, HF-token + device resolution, load_model() call).
Result: a cloud-only _run_transcription_thread that just constructs
Transcriber() and calls transcribe() with the provider params.

9 new source-text tests in tests/test_bundle_ui_only.py pin the deletions
in place (delete + verify-it-stayed-deleted)."
```

---

## Task 4: PyInstaller spike (simplified — no torch excludes)

**Why this is simpler than v4:** the rip-out + `requirements.txt` trim already excludes torch / ctranslate2 / faster_whisper / pyannote / speechbrain — they're not installed in the build venv, so PyInstaller never sees them. The spec needs `hiddenimports=[requests, urllib3, customtkinter, providers.assemblyai, providers.deepgram, providers.gladia, providers.speechmatics]` and no `excludes=[]` block at all (other than the standard test-dep excludes).

**Files to create:** `audio_transcriber.spec`, `runtime_hook_imports.py`, `requirements-build.txt`, `scripts/build_exe.ps1`, `vendor/ffmpeg/.gitkeep`, `.gitignore` additions.

- [ ] **Step 1: Build venv + vendor ffmpeg**

```powershell
python -m venv .venv-build
.\.venv-build\Scripts\Activate.ps1
pip install -r requirements.txt
echo "pyinstaller==6.10.0" > requirements-build.txt
pip install -r requirements-build.txt
```

Download ffmpeg + ffprobe Windows builds from https://www.gyan.dev/ffmpeg/builds/ ("essentials" release-build). Extract `ffmpeg.exe` + `ffprobe.exe` into `vendor/ffmpeg/`. Verify:

```powershell
.\vendor\ffmpeg\ffmpeg.exe -version
```

- [ ] **Step 2: Runtime hook for faulthandler (invariant #1)**

`runtime_hook_imports.py`:

```python
"""PyInstaller runtime hook — CLAUDE.md invariant #1 (faulthandler) in frozen mode.

The cloud-only rip-out removed the ctranslate2/torch DLL-ordering concern
(old invariant #2), so this hook only needs to enable faulthandler.
"""
import faulthandler
faulthandler.enable()
```

- [ ] **Step 3: PyInstaller spec**

`audio_transcriber.spec`:

```python
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the cloud-only Audio Transcriber Windows bundle.

Build: pyinstaller audio_transcriber.spec --noconfirm
Output: dist/AudioTranscriber/  (onedir bundle, ~150-300 MB)

Cloud-only: no torch / ctranslate2 / faster_whisper / pyannote in the
build venv, so no PyInstaller `excludes=[]` is needed for them.
"""
from pathlib import Path

block_cipher = None
PROJECT_ROOT = Path(SPECPATH)

a = Analysis(
    ['app.py'],
    pathex=[str(PROJECT_ROOT)],
    binaries=[
        (str(PROJECT_ROOT / 'vendor' / 'ffmpeg' / 'ffmpeg.exe'), 'vendor/ffmpeg'),
        (str(PROJECT_ROOT / 'vendor' / 'ffmpeg' / 'ffprobe.exe'), 'vendor/ffmpeg'),
    ],
    datas=[
        ('config.example.json', '.'),
    ],
    hiddenimports=[
        'requests',
        'urllib3',
        'customtkinter',
        'providers.assemblyai',
        'providers.deepgram',
        'providers.gladia',
        'providers.speechmatics',
    ],
    hookspath=[],
    runtime_hooks=[str(PROJECT_ROOT / 'runtime_hook_imports.py')],
    excludes=[
        'matplotlib',
        'tkinter.test',
        'unittest',
        'pytest',
        'IPython',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='AudioTranscriber',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='AudioTranscriber',
)
```

- [ ] **Step 4: Build script**

`scripts/build_exe.ps1`:

```powershell
# Bundle the Audio Transcriber as a Windows .exe (cloud-only, onedir).
$ErrorActionPreference = 'Stop'

Write-Host "1. Cleaning previous build outputs..."
if (Test-Path 'build') { Remove-Item -Recurse -Force 'build' }
if (Test-Path 'dist')  { Remove-Item -Recurse -Force 'dist'  }

Write-Host "2. Verifying vendor binaries..."
foreach ($name in @('ffmpeg.exe','ffprobe.exe')) {
    $path = "vendor/ffmpeg/$name"
    if (-not (Test-Path $path)) {
        throw "Missing $path — download from https://www.gyan.dev/ffmpeg/builds/"
    }
}

Write-Host "3. Running PyInstaller..."
pyinstaller audio_transcriber.spec --noconfirm

Write-Host "4. Verifying output..."
$bundleDir = 'dist/AudioTranscriber'
$exePath = "$bundleDir/AudioTranscriber.exe"
if (-not (Test-Path $exePath)) {
    throw "Build failed — $exePath not found"
}

Write-Host "5. Seeding starter config.json into _internal/..."
$internalDir = "$bundleDir/_internal"
if (-not (Test-Path $internalDir)) {
    $internalDir = $bundleDir
}
Copy-Item 'config.example.json' "$internalDir/config.json" -Force

Write-Host "6. Verifying bundle size..."
$bundleSize = (Get-ChildItem -Recurse $bundleDir | Measure-Object -Sum Length).Sum / 1MB
Write-Host ("   Bundle size: {0:N0} MB" -f $bundleSize)
if ($bundleSize -gt 500) {
    Write-Warning "Bundle larger than expected — local CUDA libs may have slipped back in via a transitive dep. Inspect Analysis warnings."
}

Write-Host "Done. Run dist/AudioTranscriber/AudioTranscriber.exe to test."
```

- [ ] **Step 5: .gitignore additions**

```text
build/
dist/
*.zip
vendor/ffmpeg/*.exe
.venv-build/
```

Create `vendor/ffmpeg/.gitkeep` (empty file).

- [ ] **Step 6: First bundle attempt**

```powershell
.\scripts\build_exe.ps1
```

Expected: build in 2-4 min (no torch to bundle = much faster than v4 would have been), output `dist/AudioTranscriber/` 150-300 MB.

Failure modes:
- `Module 'X' not found` → add to `hiddenimports` (likely `googleapiclient` sub-modules; the gdrive package may need explicit hidden imports)
- Bundle launches then closes immediately → set `console=True` in EXE block, rebuild, run from cmd.exe for traceback
- CustomTkinter themes missing → add `(<venv site-packages>/customtkinter/assets, customtkinter/assets)` to `datas`

- [ ] **Step 7: Smoke test the bundle**

```powershell
.\dist\AudioTranscriber\AudioTranscriber.exe
```

Verify:
- UI opens within 5 sec
- Settings → cloud_provider dropdown shows ONLY AssemblyAI / Deepgram / Gladia / Speechmatics
- Settings has no voice library section, no silence removal toggle, no model picker, no device picker
- Settings → enter a real AssemblyAI key → save → transcribe a 30-sec audio file → transcript appears with Speaker labels

If the smoke fails, fix in source (not in `dist/`), rebuild, retest.

- [ ] **Step 8: Commit Task 4**

```powershell
git add audio_transcriber.spec runtime_hook_imports.py requirements-build.txt scripts/build_exe.ps1 vendor/ffmpeg/.gitkeep .gitignore
git commit -m "build: PyInstaller onedir spec for cloud-only bundle

Bundles requests + cloud providers + CustomTkinter + vendored ffmpeg.
No torch / ctranslate2 / faster_whisper / pyannote excludes needed —
the cloud-only rip-out (Task 2) removed those deps entirely from
requirements.txt, so PyInstaller never sees them in the build venv.
Target bundle size: 150-300 MB.

build_exe.ps1 copies config.example.json -> _internal/config.json so the
bundle's first launch sees a starter config (cloud_provider=AssemblyAI,
empty API keys). First-run banner (Task 7) prompts the user toward
Settings to enter keys.

Spike outcome: \$OUTCOME (record one-liner — PASS or FAIL + why)."
```

---

## Task 5: Protocol generator module (TDD)

**Unchanged from v4 plan.** See `docs/superpowers/plans/2026-05-27-mvp-3-clients-this-week.md` §972-1007 for the full content. Recap:

- Subtask 5a: `tasks/protocol_template.py` + 4 tests (template substitution helper)
- Subtask 5b: `tasks/protocol_generator.py` + 5 tests (LLM-driven 5-block MoM via OpenRouter)
- Documents the template in `docs/PROTOCOL_TEMPLATE.md`

Test count after Task 5: post-rip-out count + 9 protocol tests.

---

## Task 6: UI integration — protocol checkbox in extract-tasks dialog

**Unchanged from v4 plan.** See v4 §1011-1167. Adds the `generate_protocol` BooleanVar (default ON), the CTkCheckBox, and the post-extract conditional call to `protocol_generator.generate(...)` using the dialog's real instance state.

Test count after Task 6: previous + 4 dialog source-text tests.

---

## Task 7: Bundle integration — ffmpeg helper + first-run banner

**What changed from v4:** no `_LOCAL_AVAILABLE` first-run-banner conditional check (the flag is gone). Banner triggers solely on `cloud_api_keys.get("AssemblyAI", "").strip() == ""`. No `cloud_enabled` flip in `config.example.json` (key is obsolete).

**Files:** Same as v4 — `utils.py` (add `get_ffmpeg_path()` + `get_ffprobe_path()`), `audio_io.py`, `transcriber/cloud_chunker.py`, `ui/app/builder.py` (first-run banner row insertion), `tests/test_ffmpeg_path_resolution.py`.

(`providers/groq.py` ffmpeg site is no longer applicable — the provider was deleted in Task 2. The site count drops from 9 to 8.)

- [ ] **Steps 1-4: ffmpeg helper + 8 callsite updates**

Same as v4 §1181-1300 EXCEPT:
- Drop `providers/groq.py` from the callsite list (file deleted).
- `tests/test_providers_groq.py` does not exist (deleted in Task 2). Skip the test-update step for it.
- Site count: 6 in `audio_io.py` + 2 in `transcriber/cloud_chunker.py` = **8 sites total**.

- [ ] **Step 5: First-run banner in `ui/app/builder.py`**

Same as v4 §1303-1350 EXCEPT the first-run detection in `ui/app/__init__.py` becomes simpler:

```python
# In App.__init__, after config load:
cloud_keys = self._config.get("cloud_api_keys", {}) or {}
self._first_run = not cloud_keys.get("AssemblyAI", "").strip()
```

(No `cloud_enabled` check — the flag is obsolete. Cloud is always on.)

- [ ] **Step 6: Run tests + smoke**

```powershell
python -m pytest
python -m ruff check .
python app.py    # banner DOESN'T show because dev config has a real key
```

To test the banner manually, temporarily blank out `cloud_api_keys.AssemblyAI` in `config.json`, restart, verify banner shows + button opens Settings.

- [ ] **Step 7: Commit Task 7**

```powershell
git add utils.py audio_io.py transcriber/cloud_chunker.py ui/app/builder.py ui/app/__init__.py tests/test_ffmpeg_path_resolution.py
git commit -m "feat(bundle): vendored ffmpeg resolution + first-run banner

utils.get_ffmpeg_path() + get_ffprobe_path() resolve to vendor/ffmpeg/ in
frozen mode, fall back to shutil.which() in source mode. check_ffmpeg()
rewritten to use the helper. Updated bare 'ffmpeg' subprocess sites in
audio_io.py (6 sites) and transcriber/cloud_chunker.py (lines 415 + 463).

First-run banner in ui/app/builder.py at row=0, shown when AssemblyAI key
is empty after config load (no _LOCAL_AVAILABLE check — the flag is gone
post-rip-out). Calls _open_settings_dialog. Grid rows shifted by +1;
rowconfigure expand target moved row=6 → row=7.

4 new ffmpeg-resolution tests."
```

---

## Task 8: Clean-machine smoke test

**Mostly unchanged from v4 plan §1387-1471.** Use the same clean-Windows-VM-or-spare-laptop discipline, the same `C:\Apps\Audio Transcriber Test` path-with-space tactic, the same E2E sequence (transcribe → extract → protocol).

**Adjustments to the v4 Step 3 first-run UX checklist** (delete these lines, which referenced gated features that are simply gone in v5):

- ❌ `Settings dialog: NO "Голоса" section` → unnecessary (the section can't exist; the file is deleted)
- ❌ `Settings dialog: NO silence-removal toggle` → unnecessary
- ❌ `Settings dialog: cloud_provider dropdown ONLY shows AssemblyAI/Deepgram/Gladia/Speechmatics` → still verify, but it's now guaranteed by the deleted provider files
- ✅ Add: `Settings dialog: NO Whisper model picker, NO device pickers, NO HF token field`

**Adjusted Step 6 pre-ship checklist:**

- `pytest` on dev = **whatever the actual post-Task-7 number is** (record from Task 7 commit). The «490» from v4 is wrong for v5.
- All other items unchanged.

---

## Task 9: Client onboarding doc + delivery

**Mostly unchanged from v4 plan §1475-1593.** The `docs/CLIENT_SETUP.md` template carries over with three small wording changes:

1. Drop the "Локальный движок недоступен" troubleshooting line — that error is gone in v5.
2. Section 1 ("Что вам понадобится"): change «Не нужно: NVIDIA GPU, HuggingFace аккаунт, Python.» → «Не нужно: NVIDIA GPU, HuggingFace аккаунт, Python, локальная установка моделей.»
3. Drop any reference to voice library / speaker enrollment from the user-facing text (the feature isn't shipping).

Tag the release `v0.1.0-mvp-cloud-only` to distinguish from any hypothetical future hybrid build.

All other Task 9 steps (build + zip + tag + 3-client delivery + tester checklist + memory update) carry over verbatim.

---

## Self-review (v5)

**0. v5 scope-shift sanity check:**

| Concern | Addressed by | Resolved? |
|---|---|---|
| Maintaining local + cloud doubles surface area | Task 2 deletes local stack entirely | ✓ |
| Source-mode dev needs torch installed | requirements.txt no longer ships torch — dev can be cloud-only too | ✓ |
| `TranscriptionCancelled` import contract with 6 providers | Class moves to `transcriber/__init__.py` top, providers' existing `from transcriber import` imports keep working | ✓ |
| UI affordances pointing at deleted backend | Task 3 deletes voice library section, model picker, device pickers, HF token, silence-removal button | ✓ |
| Groq + OpenAI Whisper would crash without local pyannote fallback | Provider files + tests deleted in Task 2 Subtask 2b | ✓ |
| CLAUDE.md invariants about local stack become wrong | Rewritten in Task 2 Step 16 | ✓ |
| PyInstaller spec needed elaborate excludes in v4 | Simplified — torch / ctranslate2 / etc. not installed → not bundled | ✓ |
| Voice library data loss for current users (if any) | N/A — no production users yet; MVP is for first 3 clients | ✓ |

**1. Coverage of user-stated requirements (post-2026-05-28 pivot):**

| Requirement | Task | Verified? |
|---|---|---|
| Качественная транскрибация | AssemblyAI Universal model | ✓ |
| Качественная диаризация | AssemblyAI built-in (cloud only — local pyannote deleted) | ✓ |
| Протокол | Task 5 + Task 6 | ✓ |
| Задачи в Linear / Glide | Existing, no change | ✓ |
| Cloud-only (no local CUDA code in codebase) | Task 2 + Task 3 | ✓ |
| Trello | DROPPED | ⚠ deferred |

**2. Placeholder scan:** Two intentional "discover live state" instructions remain — Task 2 Step 2 (enumerate test files via collect-only), Task 3 Steps 4 + 6 + 7 (read the actual file to find exact widget names). Per writing-plans rule «No Placeholders», these are explicitly named as "read-then-do" rather than "TBD" / "implement later" — they instruct the engineer to look at the live state because pre-computed line numbers will drift between v5 and execution time. NOT placeholders.

**3. Type consistency:**
- `TranscriptionCancelled(Exception)` — class signature identical to its previous home in `cuda_utils.py`; providers' `raise TranscriptionCancelled()` keeps working ✓
- `_check_cancelled(cancel_event)` — signature identical ✓
- `Transcriber.__init__()` (no args) is a CHANGE from prior `Transcriber(model_size, device, compute_type, beam_size)` — see Task 3 Step 6 for the callsite update in `ui/app/transcription_mixin.py` ✓
- `Transcriber.transcribe(audio_path, *, language, diarize, cloud_provider, cloud_api_key, hotwords, denoise_audio, ...)` — cloud-path signature preserved verbatim from current main ✓

**4. Dependency order:**

- Task 1 — non-blocking, parallel with Task 2
- Task 2 (rip-out) — HARD GATE for Tasks 3, 4, 7
- Task 3 (UI strip) — depends on Task 2 (deleted providers + Transcriber surface); GATE for Task 7's first-run banner
- Task 4 (PyInstaller) — depends on Tasks 2 + 3 (clean codebase, no orphaned UI calling deleted backend); GATE for Tasks 7, 8, 9
- Task 5 (protocol generator) — independent, can run parallel with 2/3/4
- Task 6 (UI checkbox) — depends on Task 5
- Task 7 (bundle integration) — depends on Tasks 2 + 3 + 4
- Task 8 (clean-machine smoke) — depends on Tasks 4 + 6 + 7
- Task 9 (deliver) — depends on Task 8

**5. Boundary test data audit:** N/A — no new interval-bucket arithmetic introduced. Protocol generator tests use diverse-shape input.

**6. Pre-check safety-net audit:** Task 2 Step 13 (audio_io.py grep) explicitly checks whether `ensure_16khz_mono` / `load_mono_float32` have surviving callers before deletion — avoids silent breakage of cloud code paths.

**7. ffmpeg-mock-blindness audit:** Task 8 path-with-space discipline carries over from v4 (per memory `feedback_mock_tests_dont_catch_ffmpeg_parse_errors`).

**8. Codex-contract-drift audit:** Provider import contract (`from transcriber import TranscriptionCancelled`) verified via Grep before plan-writing — all 6 providers use the `from transcriber import` form, NOT `from transcriber.cuda_utils import`, so the relocation is invisible to them. Per memory `feedback_read_actual_code_before_writing_plan_pseudocode` — read first, do not invent.

---

## Glossary

- **Cloud-only build** — no local Whisper, no local pyannote, no torch / ctranslate2 / faster_whisper in the codebase. Distinct from v4's "lazy-gate" build which kept them as optional source-mode deps.
- **Rip-out** — the 2026-05-28 commit that deletes the local CUDA stack files entirely (vs gating them).
- **PyInstaller `--onedir`** — folder-mode bundle (vs `--onefile`); faster startup, easier debugging.
- **Frozen mode** — `sys.frozen = True` + `sys._MEIPASS` populated (PyInstaller runtime).
- **MoM** — Minutes of Meeting; 5-block structured protocol per Tauri spec §7.9.
- **v4 plan** — `docs/superpowers/plans/2026-05-27-mvp-3-clients-this-week.md`. Superseded by this v5 doc but retained as reference for unchanged tasks (1, 5, 6, 8, 9).
