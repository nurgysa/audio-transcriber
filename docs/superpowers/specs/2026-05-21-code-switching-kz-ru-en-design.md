# Code-switching support: Қазақша + Русский + English (Phase 1)

**Date**: 2026-05-21
**Status**: Draft — ready for implementation planning
**Phase**: 1 of 2

> Phase 2 (per-segment language detection for local Whisper) will be a
> separate spec, written after Phase 1 ships and we have real-world signal
> on what the prompt-only approach achieves.

## Context

Kazakhstan workplaces routinely mix Қазақша, Русский, and English in the
same utterance ("Стендапке кеттік — деплой Slack-та обсудим"). The current
language selector forces a single dominant language and degrades all three
sub-cases:

1. **KZ inserts in RU speech get mangled** — `language=ru` forces Whisper /
   provider to interpret a Kazakh phrase as phonetically-similar Russian
   text.
2. **EN technical terms in RU/KZ get cyrillicized** — "Kubernetes" → "куберэнетес",
   "deadline" → "дедлайн", even when the speaker used the Latin word.
3. **Auto-detect picks one language per file** — switching mid-conversation
   is invisible; whichever language wins the first ~30 seconds wins all.
4. **Pure KZ accuracy is weak** — `large-v3` is poorly resourced for KZ
   compared to RU/EN. (Phase 1 does not fix this; flagged as Phase 2 target.)

The fix is **one cross-cutting `"mixed"` sentinel** that propagates from
UI → `TranscriptionOptions` → local Whisper config / cloud provider
configs. No new packages, no new dependencies — Phase 1 uses existing
extension points.

## Scope

### In scope (Phase 1)

- New `"Смешанный (KZ+RU+EN)"` entry in the UI language selector
  (`ui/app/constants.py::LANGUAGES`)
- Trilingual `initial_prompt` for local Whisper (existing
  `_PROMPT_FRAMES` dict in `transcriber/prompt.py`)
- Mixed-aware request bodies for 4 of 5 cloud providers (Gladia,
  AssemblyAI, Speechmatics, OpenAI Whisper)
- Hard `ProviderError` for Deepgram + `mixed` (nova-3 doesn't ship KZ)
- New `supports_mixed() -> bool` capability on `providers/base.py` ABC
- Settings UI: inline warning when current provider doesn't support `mixed`

### Out of scope (deferred / non-goals)

- ❌ Per-segment language detection for local Whisper — **Phase 2 spec**
- ❌ Auto-routing to "best" provider for mixed content (paternalism)
- ❌ Migration of existing `config.json` (additive sentinel — old labels keep working)
- ❌ Real audio benchmarking / WER metrics (no corpus, no GPU CI)
- ❌ Custom-tuned KZ Whisper checkpoint
- ❌ Real-time / streaming code-switching

### Phase 2 preview (separate spec, after Phase 1 ships)

- Pre-pass: VAD-segmented audio → `faster-whisper.detect_language()`
  per ~5-10s window → language map
- Re-decode each segment in its detected language; merge timeline
- Expected ~2× slowdown vs single-pass; gates needed for VRAM budget
  (1650 Ti can't hold large-v3 + diarize in parallel)

## Architecture

**Sentinel-based dispatch**: one new string `"mixed"` flows through three
layers unchanged.

```
UI (LANGUAGES dict)              ──► "Смешанный (KZ+RU+EN)" = "mixed"
   │
   ▼
TranscriptionOptions             ──► .language = "mixed" | "kk" | "ru" | "en" | None
   │
   ▼
   ├─► Local: transcribe(language="mixed")
   │       └─► Whisper config: language=None  (internal auto-detect)
   │           initial_prompt: trilingual KZ+RU+EN frame
   │
   └─► Cloud: provider.transcribe(options)
           ├─► Gladia: language_config={"languages":[kk,ru,en], "code_switching":true}
           ├─► AssemblyAI: language_detection=true + speech_model="universal"
           ├─► Speechmatics: language_identification config (exact field TBD)
           ├─► OpenAI Whisper: omit language param (best-effort auto-detect)
           └─► Deepgram: ProviderError("Қазақша не поддерживается")
```

### Key design decisions

| Decision | Why |
|---|---|
| Sentinel `"mixed"` instead of a separate `code_switching: bool` flag | Single source of truth; bool + language would allow contradictory states |
| `supports_mixed()` on ABC, not a centralized blocklist | Provider knows its own constraints; adding new providers stays a one-file change |
| Inline UI warning, not auto-disable / auto-switch provider | Predictability over magic — user may consciously pick a single-language provider for a specific recording |
| Local: prompt engineering, **not** per-segment ASR | Phase 1 ships in 1-2 PRs; per-segment is research-grade and gets its own spec |
| `initial_prompt` builder receives `"mixed"` (not translated `None`) | Builder uses the key as dict-lookup in `_PROMPT_FRAMES`; translation to Whisper's `None` happens at the API call site |

## Components

Per-file change scope. All changes additive — existing single-language
paths (`kk`/`ru`/`en`/`None`) are physically untouched.

| File | Change | LOC |
|---|---|---|
| `ui/app/constants.py` | Add `"Смешанный (KZ+RU+EN)": "mixed"` to `LANGUAGES` | 1 |
| `transcriber/prompt.py` | Add `"mixed"` key to `_PROMPT_FRAMES` (prefix + terms_label) | ~5 |
| `transcriber/__init__.py` | `effective_language = None if language == "mixed" else language`; pass `effective_language` to Whisper but **original** `language` to `_build_initial_prompt` | ~3 |
| `providers/base.py` | New method `supports_mixed(self) -> bool` with default `return True` | ~6 |
| `providers/gladia.py` | When `options.language == "mixed"`: `body["language_config"] = {"languages": ["kk","ru","en"], "code_switching": True}` (replaces existing single-language branch) | ~5 |
| `providers/assemblyai.py` | When `mixed`: `body["language_detection"] = True` + `body["speech_model"] = "universal"` | ~4 |
| `providers/speechmatics.py` | When `mixed`: enable language identification config (exact field name TBD — verify against current Speechmatics docs during impl) | ~4 |
| `providers/openai_whisper.py` | When `mixed`: skip `language` form field (whisper-1 falls back to auto-detect) | ~3 |
| `providers/deepgram.py` | Override `supports_mixed() -> False`; raise `ProviderError("Deepgram nova-3 не поддерживает Қазақша. Выбери Gladia или AssemblyAI.")` early in `_submit()` | ~6 |
| `ui/dialogs/settings.py` | When `language == "Смешанный (KZ+RU+EN)"` AND `not provider.supports_mixed()`: show inline warning under provider dropdown | ~30 |
| `tests/test_transcriber_pure.py` | +3-4 tests for `_build_initial_prompt("mixed", ...)` | ~10 |
| `tests/test_providers_*.py` (×5) | +1-2 tests per provider — see Testing section | ~50 |

**Files NOT touched** (YAGNI): `recorder.py`, `diarize_worker.py`,
`voice_library.py`, `audio_cutter.py`, `silence_remover.py`,
`tasks/*`, `transcriber/speaker_aligner.py`, `transcriber/cuda_utils.py`,
`transcriber/progress.py` — all language-agnostic.

## Data Flow

Runtime trace for "user clicks Транскрибировать with `Смешанный` selected":

```
1. UI event
   user clicks Транскрибировать
   ↓
   ui/app/transcription_mixin.py
   reads self.language_var.get() → "Смешанный (KZ+RU+EN)"
   ↓
   lang_code = LANGUAGES["Смешанный (KZ+RU+EN)"]  → "mixed"

2. Dispatch
   if self.cloud_enabled:                          ┐
       options = TranscriptionOptions(             │
           language="mixed", ...,                  │  ── cloud branch
       )                                           │
       provider.transcribe(audio, options, prog)   ┘
   else:
       transcribe(audio, language="mixed", ...)    ── local branch

3a. LOCAL branch (transcriber/__init__.py)
    effective_language = None if language == "mixed" else language
    initial_prompt = _build_initial_prompt(language="mixed", hotwords_str=...)
    # → "Расшифровка трилингвальной (қазақша, русский, English) речи.
    #    Terms / Терминдер / Терминов: Slack, Kubernetes, Нургиса"
    model.transcribe(
        audio,
        language=effective_language,    # None → Whisper auto-detect
        initial_prompt=initial_prompt,  # trilingual frame
        hotwords=hotwords_list,         # CTC bias for EN/proper-noun spelling
        ...
    )

3b. CLOUD branch (providers/*.py — _submit())
    Each provider sees options.language == "mixed" and emits its native
    multilingual config:

    Gladia:        body["language_config"] = {
                       "languages": ["kk","ru","en"],
                       "code_switching": True,
                   }
    AssemblyAI:    body["language_detection"] = True
                   body["speech_model"] = "universal"
    Speechmatics:  config["language_identification_config"] = {...}  # TBD
    OpenAI:        # whisper-1 auto-detect; no "language" key in form
    Deepgram:      raise ProviderError(...)  # before any HTTP call

4. Result
   All three paths return identical `TranscriptionResult` shape.
   Diarization (pyannote) and speaker_aligner are language-agnostic;
   they run unchanged downstream.
```

### Honest limitations (will be surfaced in the PR description, too)

1. **Local Phase 1 is not true code-switching.** `language=None` in
   faster-whisper triggers `model.detect_language()` once on the first
   ~30 seconds and applies the result to the entire decode. The trilingual
   `initial_prompt` softens the penalty on foreign-language tokens but
   doesn't enable per-segment re-decoding. Cloud (Gladia in particular)
   will give qualitatively better results for true mid-utterance
   code-switching on Phase 1.
2. **AssemblyAI / Speechmatics specifics need doc verification.** The
   exact field names for "multilingual mode" / "universal model" must be
   checked against current vendor documentation during implementation.
   Marked as TBD throughout this spec.

## Error Handling

| Scenario | Where handled | User-facing message (Russian) |
|---|---|---|
| Deepgram + `mixed` | `providers/deepgram.py::_submit()` — early `ProviderError` before HTTP | `"Deepgram nova-3 не поддерживает Қазақша. Выбери Gladia или AssemblyAI."` |
| Gladia rejects `code_switching` field (API change) | Existing `if not r.ok: raise ProviderError(f"...{r.status_code}: {r.text[:300]}")` | Stock provider-error path with vendor text |
| AssemblyAI rejects `speech_model: "universal"` | Same | Same |
| Speechmatics rejects unknown config | Same | Same |
| Local prompt > 400 chars (trilingual frame + 3-language hotwords) | Existing `_build_initial_prompt` truncation: last-comma cut, frame preserved | Not surfaced — graceful degradation, hotwords still bias via CTC |
| Config has `Смешанный` saved but current provider is Deepgram | UI inline warning in Settings + hard `ProviderError` on transcribe click | See row 1 |

**Logging**:
- `logger.info("Transcribe: language=%s, provider=%s, mixed=%s", lang, provider_name, lang == "mixed")` at dispatch points (one for local, one for cloud)
- Helps debug "why is my KZ still mangled" — log makes the actual path visible
- No new `print()` (per CLAUDE.md convention; `diarize_worker.py` exception unchanged)

**Backward compatibility**:
- All changes are additive. Existing `LANGUAGES` keys (`kk`, `ru`, `en`, `None`) physically unchanged.
- Existing `config.json` files with `"language": "Русский"` etc. work without migration.
- New saves use the new label `"Смешанный (KZ+RU+EN)"`.

**Rollback plan**:
- Remove `"Смешанный (KZ+RU+EN)"` entry from `LANGUAGES` (one line)
- Other `if language == "mixed":` branches become dead code — harmless; can be cleaned in follow-up
- No data migration, no config rewrite

## Testing

### Baseline contract (per CLAUDE.md)

- Current baseline: 285 tests, all green
- `pytest` + `ruff check .` must pass before every commit
- CI (`.github/workflows/tests.yml`) runs both jobs

### New automated tests (~12-14, ~80 LOC)

| File | New test | Asserts |
|---|---|---|
| `tests/test_transcriber_pure.py` | `test_build_prompt_mixed_with_terms` | trilingual frame + `Terms / Терминдер / Терминов:` label present |
| | `test_build_prompt_mixed_no_terms` | frame-only output, no terms label |
| | `test_build_prompt_mixed_truncation` | long hotwords → last-comma cut, frame preserved |
| | `test_effective_whisper_language` | `"mixed" → None`, others pass-through (if helper extracted) |
| `tests/test_providers_gladia.py` | `test_mixed_enables_code_switching` | `body["language_config"] == {"languages": ["kk","ru","en"], "code_switching": True}` |
| | `test_single_lang_unchanged` | regression: `language="ru"` produces same body shape as today (no `code_switching` key) |
| `tests/test_providers_assemblyai.py` | `test_mixed_uses_universal_model` | `body["speech_model"] == "universal"` AND `body["language_detection"] == True` |
| `tests/test_providers_speechmatics.py` | `test_mixed_enables_language_identification` | Speechmatics multilingual config field is present (exact name verified at impl time) |
| `tests/test_providers_openai_whisper.py` | `test_mixed_omits_language_field` | no `"language"` key in multipart form payload |
| `tests/test_providers_deepgram.py` | `test_mixed_raises_provider_error` | `ProviderError` raised with Russian message; `requests.post` mock asserts **zero** calls (proves early-fail) |
| `tests/test_providers_base.py` (new file if absent) | `test_supports_mixed_default_true` + `test_deepgram_supports_mixed_false` | ABC capability contract |

### Manual QA checklist (to be included in PR description)

Automated tests cannot judge ASR quality. The PR must include a manual
test plan covering:

1. ☐ **Regression — pure RU + `Русский`**: transcript identical to baseline (sanity)
2. ☐ **Regression — pure RU + `Смешанный`**: quality no worse than baseline (worst case: small WER bump from prompt overhead)
3. ☐ **Win — trilingual audio (KZ greeting + RU body + EN tech terms) + `Смешанный` + Gladia**: measurably better than same audio + `Русский` + Gladia (KZ readable, EN terms in Latin)
4. ☐ **Local — same trilingual + `Смешанный` + Whisper**: modest improvement vs `Русский` (prompt-effect only; Phase 2 for real gain)
5. ☐ **Error — `Смешанный` + Deepgram**: friendly error message, no crash
6. ☐ **UI — Settings warning**: with `Смешанный` selected, switching provider to Deepgram surfaces inline warning; switching back removes it
7. ☐ **Persistence — restart**: `config.json` with `"language": "Смешанный (KZ+RU+EN)"` loads correctly on next launch

### Not tested (explicit non-goals)

- ❌ End-to-end integration with real trilingual audio (no fixtures, no CI GPU)
- ❌ WER metrics on an ad-hoc corpus (impractical without controlled dataset)
- ❌ Real HTTP calls to providers (existing tests are mock-based — same pattern)
- ❌ New UI tests for the Settings warning (codebase has minimal UI test infra; manual QA #6 covers it)

## Open questions / TBD

These need verification during implementation, not during spec:

1. **AssemblyAI `speech_model: "universal"`**: exact field value and
   whether it auto-detects per-segment or requires extra config. Confirm
   against current AssemblyAI docs.
2. **Speechmatics `language_identification_config`**: exact field name
   (could be `language_id_config`, `language_identification`, or part of
   `transcription_config`). Confirm against current Speechmatics docs.
3. **Gladia `code_switching` payload shape**: is it `{"code_switching": true}`
   nested inside `language_config`, or a top-level body field? Confirm
   against current Gladia v2 docs.
4. **OpenAI Whisper code-switching**: confirm that omitting the
   `language` form field is the documented way to enable auto-detect
   (vs. passing `language: ""` or `language: "auto"`).

## Implementation phases (within Phase 1)

Recommended PR breakdown to keep each diff reviewable (per CLAUDE.md
"one concern per PR" + memory note "Serialize multi-PR refactors via main"):

- **PR-A**: Foundation — `LANGUAGES["Смешанный"]`, `_PROMPT_FRAMES["mixed"]`,
  `effective_language` translator, `supports_mixed()` ABC method,
  `transcriber_pure` tests
- **PR-B**: Cloud providers (Gladia + Deepgram first, as both have
  concrete known APIs) + provider tests
- **PR-C**: Cloud providers part 2 (AssemblyAI + Speechmatics +
  OpenAI Whisper after doc verification) + remaining provider tests
- **PR-D**: Settings UI inline warning + manual QA results

Each PR ships to main independently; no stacked PRs.

## Future work (Phase 2 — separate spec)

After Phase 1 ships and we have real-world feedback:

- Pre-pass VAD segmentation → `faster-whisper.detect_language()` per
  ~5-10s window → language map for the recording
- Re-decode each segment in its detected language
- VRAM management: 1650 Ti can't hold large-v3 + diarize together, so
  per-segment re-decode needs its own GPU/CPU strategy (likely chunked
  on GPU, model not unloaded mid-recording)
- Benchmarking: build a small (~5min) trilingual test clip; track WER
  trajectory across Phase 1 → 2

## Glossary

- **Code-switching** — mixing two or more languages within a single
  conversation or utterance (linguistics term; common in trilingual
  Kazakhstan workplaces).
- **`mixed` sentinel** — the string `"mixed"` flowing through
  `LANGUAGES`, `TranscriptionOptions.language`, `_PROMPT_FRAMES`, and
  provider `_submit()` branches.
- **`supports_mixed()`** — capability method on the
  `TranscriptionProvider` ABC; default `True`, overridden to `False` on
  providers that can't handle one or more of {KZ, RU, EN}.
- **Mixed-aware path** — the branch inside a provider's `_submit()`
  that runs when `options.language == "mixed"`.
