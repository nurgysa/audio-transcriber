# Code-switching support: Қазақша + Русский + English (Phase 2)

**Date**: 2026-05-22
**Status**: Draft — ready for implementation planning
**Phase**: 2 of 2 (Phase 1 shipped via PRs #20-#26 on 2026-05-21)

> Phase 1 (sentinel + cloud-provider multilingual + trilingual local prompt)
> shipped 2026-05-21. Phase 2 closes the local-Whisper quality gap by adding
> a VAD pre-pass and per-segment language-aware decoding. Cloud providers
> already do per-segment code-switching natively (Gladia `code_switching`,
> AssemblyAI `universal`, Speechmatics `language_identification`); Phase 2
> brings the local path to parity for the case where users transcribe
> offline.

## Context

Phase 1 introduced the `"mixed"` sentinel and the trilingual `initial_prompt`
frame. On the local Whisper path, this softens the wrong-language penalty but
does not enable true code-switching: `faster-whisper`'s internal
`detect_language()` runs once on the first ~30 seconds and applies the
result to the whole decode. Mid-utterance language switches still get
mangled — the prompt is a band-aid, not a fix.

Phase 1 documented this honestly:

> Local Phase 1 is not true code-switching. `language=None` in
> faster-whisper triggers `model.detect_language()` once on the first
> ~30 seconds and applies the result to the entire decode. The trilingual
> `initial_prompt` softens the penalty on foreign-language tokens but
> doesn't enable per-segment re-decoding.

Phase 2 replaces this behaviour for `language == "mixed"` with a VAD-based
segmentation that lets Whisper auto-detect the language per speech segment
(typically 1-30 seconds), re-decoding each segment independently. Cost:
~2× wall-clock slowdown vs Phase 1. Win: KZ inserts in RU speech are
decoded as KZ, EN tech terms stay in Latin, mid-utterance switches stop
collapsing into the dominant language.

## Scope

### In scope (Phase 2)

- New `transcriber/segmenter.py` module: thin wrapper over
  `faster_whisper.vad.get_speech_timestamps` tuned for language-detection
  (longer `min_speech_duration_ms` so each segment has enough audio for
  reliable internal language detection)
- Branch inside `Transcriber.transcribe()` per-chunk loop: when
  `language == "mixed"`, route to a new `_decode_chunk_mixed()` helper
  that runs VAD pre-pass then per-segment `model.transcribe(seg_audio,
  language=None, vad_filter=False, ...)` — each call triggers Whisper's
  internal `detect_language()` on that slice
- `last_segments[].language` — new optional field carrying Whisper's
  detected per-segment language code (`"kk"` / `"ru"` / `"en"` / other).
  Not surfaced in the .txt output; available to SRT/VTT exporters and
  future features
- Tests: ~12-14 new mock-based unit tests covering the VAD wrapper and
  the new branch
- Manual A/B validation in the PR description against 2-3 real
  trilingual meeting recordings

### Out of scope (deferred / non-goals)

- ❌ Cloud-provider changes — Phase 1 already wired native multilingual
  paths through Gladia / AssemblyAI / Speechmatics / OpenAI Whisper
- ❌ Per-segment language-specific `initial_prompt` — the trilingual frame
  established in Phase 1 is reused for all segments. Language-specific
  prompts would require a pre-pass `detect_language()` call (doubles
  encoder cost). Easy follow-up if quality demands it
- ❌ Whitelist of detected languages to {kk, ru, en} — Whisper occasionally
  returns sister languages (Uzbek, Tatar, Belarusian). Accepted risk;
  if it becomes a real problem, follow-up adds restricted language list
- ❌ Inline language tags in user-facing text output (`[ru]…`, `[kk]…`).
  Stays in `last_segments[].language` metadata only
- ❌ WER metrics / benchmark corpus — manual A/B in PR description is
  the agreed quality gate (no GPU CI, no controlled dataset)
- ❌ UI changes — `"Смешанный (KZ+RU+EN)"` label already exists from
  Phase 1; no new checkboxes, no new settings
- ❌ Real-time / streaming code-switching
- ❌ Custom-tuned KZ Whisper checkpoint

## Architecture

**Branch dispatch inside `Transcriber.transcribe()`**: a single
`if language == "mixed":` inside the per-chunk loop. Everything else
(non-mixed languages, cloud providers, ensure_wav, model loading,
chunking, diarization subprocess, speaker alignment, formatting) is
physically untouched.

```
ensure_wav → load_model → launch_diarization_subprocess(WAIT mode)
   │
   ▼
for each chunk in chunks (existing 15-min chunking unchanged):
   │
   ├─ if language == "mixed":              ──── NEW BRANCH
   │     samples, sr = load_chunk_samples(chunk_path)
   │     speech_timestamps = vad_split(samples, sr)
   │     for ts in speech_timestamps:
   │         seg_audio = samples[ts.start : ts.end]
   │         segments, info = model.transcribe(
   │             seg_audio,
   │             language=None,             # Whisper auto-detects per segment
   │             vad_filter=False,
   │             initial_prompt=trilingual_prompt,   # reused from Phase 1
   │             hotwords=...,
   │             word_timestamps=True,
   │             ...other params identical to single-language path
   │         )
   │         for s in segments:
   │             transcript_segments.append({
   │                 "start": ..., "end": ..., "text": ..., "words": [...],
   │                 "language": info.language,    # NEW FIELD
   │             })
   │
   └─ else:                                ──── EXISTING SINGLE-LANGUAGE PATH
         segments, _info = model.transcribe(chunk_path, language=..., ...)
         # ... transcriber/__init__.py:765-825 unchanged
   │
   ▼
offload_to_cpu → diarize subprocess (GO) → _assign_speakers_word_level → format
```

### Key design decisions

| Decision | Why |
|---|---|
| Per-segment `transcribe(language=None)` instead of explicit `detect_language()` + language-aware re-decode | Whisper does internal language detection inside `transcribe()` when `language=None`; one encoder pass per segment instead of two. Quality is equivalent because the same detection runs either way |
| VAD pre-pass inside each chunk, not in place of chunking | 25-min STFT-allocation safety preserved (see existing `_LONG_FILE_THRESHOLD_S` rationale at `transcriber/__init__.py:74-95`); change is localized to one loop body |
| Trilingual `initial_prompt` reused for every segment (per Phase 1) | Phase 1 already proved trilingual prompt is harmless for single-language decoding. Language-specific prompts need extra encoder pass; deferred as easy follow-up |
| `vad_filter=False` in per-segment `transcribe()` | Audio slice is already speech-only; second VAD pass risks dropping word boundaries |
| `last_segments[].language` is metadata-only, not in .txt output | Predictable output format; SRT/VTT and future features can opt in to using the field |
| Branch in `transcribe()`, not separate public method | Single entry point keeps UI integration trivial — `Transcriber.transcribe(language="mixed", ...)` does the right thing for both single-language and mixed paths |
| No language whitelist on Whisper's detection result | Trusting Whisper's per-segment detection; the alternative (restricted `detect_language()` + manual choice) requires a separate API call and adds complexity. Wrong detection (uz/tt for kk) is a follow-up if it surfaces |

## Components

Per-file change scope. All changes additive — existing single-language
paths (`kk`/`ru`/`en`/`None`) are physically untouched.

| File | Change | LOC est. |
|---|---|---|
| `transcriber/segmenter.py` | **NEW module**. `vad_split(samples, sample_rate) -> list[dict]` wrapping `faster_whisper.vad.get_speech_timestamps`. VadOptions tuned for language detection: `threshold=0.5`, `min_speech_duration_ms=500` (longer than `silence_remover.py`'s 250ms because we need enough audio per segment for Whisper's internal `detect_language()`), `min_silence_duration_ms=500`, `speech_pad_ms=100` | ~50 |
| `transcriber/__init__.py` | Branch inside per-chunk loop: `if language == "mixed":` → new private method `_decode_chunk_mixed(chunk_path, chunk_start_abs, primary_start_abs, ...)`. Existing inline logic extracted to `_decode_chunk_single(chunk_path, chunk_start_abs, primary_start_abs, effective_language, ...)`. Both return `list[transcript_segment_dict]`. `transcribe()` per-chunk body becomes a one-liner dispatch | ~120 (new ~80 + refactor ~40) |
| `transcriber/prompt.py` | No changes. `_PROMPT_FRAMES["mixed"]` (introduced in Phase 1) is reused as `initial_prompt` for every segment in the mixed branch | 0 |
| `audio_io.py` | If `load_chunk_samples(path) -> (np.ndarray, int)` helper doesn't exist, add a thin wrapper over `soundfile.read(path, dtype="float32")`. Otherwise reuse | ~10 (or 0) |
| `tests/test_segmenter.py` | **NEW**. Unit tests for the VAD wrapper (5 tests) | ~40 |
| `tests/test_transcriber_mixed.py` | **NEW**. Integration tests with mocked `WhisperModel` covering routing, prompt content, language-field population, timestamp offsets, empty-VAD path, progress monotonicity, cancellation (8 tests) | ~70 |
| `tests/test_transcriber_pure.py` | +1 regression test: `language="ru"` does NOT trigger the mixed path | ~10 |

**Files NOT touched** (YAGNI):

- `recorder.py`, `diarize_worker.py`, `voice_library.py`, `audio_cutter.py`, `silence_remover.py` — language-agnostic
- `providers/*.py` (all 5 cloud providers) — Phase 1 already added native multilingual paths
- `tasks/*` — language-agnostic post-processing
- `transcriber/speaker_aligner.py`, `transcriber/cuda_utils.py`, `transcriber/progress.py` — operate on words/turns, not text content
- `transcript_format.py` — output format unchanged; `language` field is silently ignored by formatters
- `ui/*` — `"Смешанный (KZ+RU+EN)"` label already in `LANGUAGES` from Phase 1; no new UI affordances

## Data Flow

Runtime trace for a 1-hour trilingual meeting recording with diarization ON
and `language="mixed"`:

```
1. UI / dispatch (unchanged)
   transcription_mixin reads language_var → "Смешанный (KZ+RU+EN)"
   lang_code = LANGUAGES["Смешанный (KZ+RU+EN)"] → "mixed"
   Transcriber.transcribe(audio_path, language="mixed", diarize=True, ...)

2. Pre-load (unchanged)
   ensure_wav(audio_path)                  # ffmpeg normalize → 16kHz mono WAV
   load_model()                            # Whisper large-v3 → GPU (1.5 GB)
   launch_diarization_subprocess(WAIT)     # child loads pyannote on CPU,
                                           # blocks on stdin "GO\n"

3. Chunking (unchanged)
   duration = get_duration_s(wav_path) → 3600.0
   chunks = split_wav_into_chunks(wav_path, 900, ..., overlap_s=3.0)
            → 4 chunks of ~900s each (last one shorter), 3s overlap

4. Per-chunk loop (NEW BRANCH)
   for chunk_idx, (chunk_path, chunk_start_abs, primary_start_abs) in enumerate(chunks):
       if language == "mixed":
           # ── NEW PATH ──
           samples, sr = load_chunk_samples(chunk_path)   # ~30 MB float32 per 15-min chunk
           speech_timestamps = vad_split(samples, sr)
                # → [{"start": 0,      "end": 32000},      # 0-2s (KZ greeting)
                #    {"start": 48000,  "end": 224000},     # 3-14s (RU question)
                #    {"start": 240000, "end": 416000},     # 15-26s (EN term + RU)
                #    ...]
           for ts in speech_timestamps:
               _check_cancelled(cancel_event)
               seg_audio = samples[ts["start"]:ts["end"]]
               seg_start_s = ts["start"] / sr
               segments, info = self._model.transcribe(
                   seg_audio,
                   language=None,                # Whisper auto-detects on this slice
                   beam_size=5,
                   vad_filter=False,             # already filtered
                   condition_on_previous_text=False,
                   no_speech_threshold=0.6,
                   log_prob_threshold=-1.0,
                   compression_ratio_threshold=2.4,
                   word_timestamps=True,
                   initial_prompt=initial_prompt,   # trilingual frame from Phase 1
                   hotwords=hotwords_str,
               )
               # info.language → "kk" | "ru" | "en" | other (rare)
               for segment in segments:
                   abs_start = chunk_start_abs + seg_start_s + segment.start
                   abs_end   = chunk_start_abs + seg_start_s + segment.end
                   # Boundary dedup (existing logic, same midpoint test)
                   if (abs_start + abs_end) / 2.0 < primary_start_abs:
                       continue
                   seg_words = [
                       {"start": w.start + chunk_start_abs + seg_start_s,
                        "end":   w.end   + chunk_start_abs + seg_start_s,
                        "word":  w.word}
                       for w in (segment.words or [])
                   ]
                   transcript_segments.append({
                       "start": abs_start,
                       "end":   abs_end,
                       "text":  segment.text.strip(),
                       "words": seg_words,
                       "language": info.language,    # NEW FIELD
                   })
                   if on_progress and duration > 0:
                       percent = min(abs_end / duration * 100, 100.0)
                       on_progress(percent * progress_weight)
       else:
           # ── EXISTING PATH (transcriber/__init__.py:765-825, unchanged) ──
           segments, _info = self._model.transcribe(chunk_path, language=effective_language, ...)
           ...

5. Diarization + output (unchanged)
   offload_to_cpu()                              # Whisper → CPU memory
   diarize_handle.proc.stdin.write("GO\n")       # subprocess starts GPU work
   speaker_turns = _await_diarization_subprocess(...)
   labeled = _assign_speakers_word_level(transcript_segments, speaker_turns)
        # speaker_aligner indexes by word times; "language" field passes through
        # untouched
   self.last_segments = labeled
   return format_diarized(labeled)
        # format_diarized ignores "language", emits clean text
```

### Honest limitations (surface in PR description)

1. **VAD-defined segment boundaries don't always match utterances.** Whisper
   may emit shorter sub-segments inside a VAD region. Word-level timestamps
   stay accurate; downstream `_assign_speakers_word_level` is unaffected.

2. **Detection on very short segments (<1s) is unreliable.** VAD's
   `min_speech_duration_ms=500` floor mitigates this, but a 600ms speech
   blip might mis-detect. Quality risk; not a crash risk.

3. **Sister-language false positives.** Whisper sometimes labels KZ as
   Uzbek or Tatar (sister Turkic), RU as Belarusian. The audio still
   transcribes correctly; only the metadata `language` field is wrong.
   Not surfaced to user.

4. **Per-segment processing is sequential.** No batching. ~2× slowdown
   vs Phase 1 single-pass — the trade-off the user accepted in this
   spec's brainstorming round.

## Error Handling

| Scenario | Where handled | User-facing |
|---|---|---|
| VAD found no speech in chunk | `_decode_chunk_mixed` returns `[]`, loop advances | Silent — normal flow |
| Whisper detects a language outside {kk, ru, en} (e.g., `uz`, `tt`) | `info.language` saved as-is; transcription itself still runs and produces text | Not surfaced; visible only in `last_segments[].language` for debugging |
| Very short VAD segment (<0.5s) | Filtered by VAD's `min_speech_duration_ms=500` | Silent |
| Very long single VAD segment (>5min) | Whisper's internal 30s windowing handles it | Silent |
| Cancellation mid-VAD-loop | `_check_cancelled(cancel_event)` runs before each per-segment `transcribe()` AND in the inner segment loop. Diarize subprocess cleanup in `finally` (existing) | Existing `TranscriptionCancelled` |
| OOM on per-segment transcribe (rare; segments are small) | ctranslate2 raises → bubbles up unchanged | Existing crash-log path |
| Soundfile fails to read chunk WAV | `OSError` → bubbles up | Existing crash-log path |
| Empty audio file (post-normalize) | `vad_split` returns `[]` → empty transcript | Empty result (existing behaviour for silent files) |

**Logging additions** (one line per chunk + one per segment at DEBUG):

```python
logger.info(
    "Transcribe: mixed mode, chunk=%d/%d, vad_segments=%d",
    chunk_idx + 1, len(chunks), len(speech_timestamps),
)
logger.debug(
    "vad_seg %d: %.2f-%.2fs, lang=%s, text_len=%d",
    seg_idx, seg_start_s, seg_end_s, info.language, len(text),
)
```

This makes "why is my KZ still mangled" debuggable — the log shows the
per-segment detection result.

**Logging NOT added** (avoid noise): per-word language (redundant), VAD
parameters (static config).

**Backwards compatibility**:

- `last_segments[].language` is a new optional field — existing consumers
  (`transcript_format`, any external callers) silently ignore it
- The existing single-language path is physically untouched — all 285
  current tests must stay green without any modification
- No config.json migration; no UI changes

**Rollback plan**:

- Revert the branch `if language == "mixed":` inside `transcribe()` →
  `language == "mixed"` falls back to the Phase 1 path (`_effective_whisper_language("mixed") → None` + trilingual prompt)
- `transcriber/segmenter.py` becomes dead code; can be deleted in a
  follow-up or left in place
- No data migration, no config rewrite

## Testing

### Baseline contract (per CLAUDE.md)

- Current baseline: **285 tests**, all green
- `pytest && python -m ruff check .` before every commit
- CI (`.github/workflows/tests.yml`) runs both jobs on every push

### New automated tests (~12-14 tests, ~120 LOC)

| File | New test | Asserts |
|---|---|---|
| `tests/test_segmenter.py` (NEW) | `test_vad_split_empty_audio` | empty ndarray → `[]` |
| | `test_vad_split_all_silence` | zeros → `[]` |
| | `test_vad_split_all_speech` | synthetic noise > threshold → 1 group spanning input |
| | `test_vad_split_alternating` | speech-silence-speech → 2 groups, sample-accurate boundaries |
| | `test_vad_split_micro_blips_filtered` | <250ms silence between speech does NOT fragment (via `min_silence_duration_ms`) |
| `tests/test_transcriber_mixed.py` (NEW) | `test_mixed_routes_to_per_segment_path` | mock model + `vad_split` → 3 segments; `model.transcribe` called 3 times |
| | `test_mixed_passes_language_none_to_model` | every `transcribe()` call has `language=None, vad_filter=False` |
| | `test_mixed_passes_trilingual_prompt` | `initial_prompt` contains the trilingual frame |
| | `test_mixed_output_segments_carry_language_field` | each transcript_segment has `"language"` from `info.language` |
| | `test_mixed_segment_timestamps_offset_correctly` | `chunk_start_abs + seg_start_in_chunk + whisper_local_start` sums correctly |
| | `test_mixed_empty_vad_yields_empty_transcript` | `vad_split` → `[]` returns empty list without raising |
| | `test_mixed_progress_monotonic` | progress callback never goes backward across the inner loop |
| | `test_mixed_cancel_event_breaks_inner_loop` | `cancel_event.set()` interrupts before next segment, not after entire chunk |
| `tests/test_transcriber_pure.py` (existing, +regression) | `test_single_language_skips_vad_pre_pass` | `language="ru"` → `vad_split` not called; `model.transcribe` called once per chunk |

All new tests **mock-based**. No real ASR model loaded (CI has no GPU, large-v3 is ~3GB on disk). Pattern: `unittest.mock.MagicMock` for `WhisperModel`, `Mock(language='kk', ...)` for the `info` return value from `model.transcribe()`.

### Manual QA (PR description checklist)

Real-world A/B test against Phase 1 baseline. Recordings come from real
work meetings (last 1-2 weeks) — need 2-3 files with genuine trilingual
content.

```markdown
## Manual A/B test plan

For each of 2-3 real meeting recordings (10-30 min, KZ+RU+EN mix):

1. ☐ Run Phase 1 baseline (current main): capture transcript + wall time
2. ☐ Same audio on this branch: capture transcript + wall time
3. ☐ Side-by-side diff in PR description:
   - KZ phrases: readable vs mangled?
   - EN tech terms: Latin spelling preserved vs cyrillicized?
   - RU body: regression check — quality not worse?
   - Wall time: confirm expected ~2× slowdown, no surprise blowup
4. ☐ Sanity — pure-RU file with Смешанный: quality not worse than Русский baseline
5. ☐ Diarization compatibility — multispeaker mixed file still gets correct speaker labels
6. ☐ Cancel responsiveness — отмена reacts in <1s mid-loop
```

### Not tested (explicit non-goals)

- ❌ WER metrics on a corpus (manual A/B is the agreed gate; no GPU CI, no controlled dataset)
- ❌ End-to-end with real Whisper model (mock-based — same pattern as Phase 1 tests)
- ❌ New UI tests (no UI changes)
- ❌ Real audio fixtures committed to the repo (size; license; user privacy on real meetings)

## Open questions / TBD

Implementation-time decisions, not design-blocking:

1. **VadOptions exact values**: `min_speech_duration_ms` — 500ms is the
   starting point. May need tuning if real recordings produce too many
   tiny segments (over-fragmentation) or too few (under-fragmentation
   misses language switches). Tune during manual QA.
2. **`load_chunk_samples` location**: check `audio_io.py` for existing
   helper; only add if absent. Implementation detail.
3. **`info.language` field key name**: faster-whisper exposes it as
   `info.language`. Confirmed during impl; no API surprises expected.

## Implementation phases (within Phase 2)

Recommended PR breakdown to keep each diff reviewable. Per CLAUDE.md
"one concern per PR" + memory rule "serialize multi-PR refactors via
main":

- **PR-A**: Foundation — `transcriber/segmenter.py` module + `tests/test_segmenter.py`. Pure code, no integration. Fast review.
- **PR-B**: Integration — `transcriber/__init__.py` branch + `_decode_chunk_mixed` / `_decode_chunk_single` extraction + `tests/test_transcriber_mixed.py` + regression test in `tests/test_transcriber_pure.py`. The meat of the change.
- **PR-C**: Manual A/B results — PR description with the 2-3 real-meeting comparisons + final tuning of VAD params if needed. Possibly a tiny diff if VAD defaults need adjustment after real-world signal.

Each PR ships to main independently. No stacked PRs (per the memory rule
about squash-merge orphaning).

## Future work (post-Phase 2)

Once Phase 2 is in production and we have real-world signal:

- **Language-specific `initial_prompt`** per segment (replacing the
  shared trilingual frame). Requires a pre-pass `detect_language()`
  call (~30% extra encoder cost). Worth it if KZ accuracy is still
  weak after Phase 2 ships.
- **Whitelist detected languages to {kk, ru, en}** if Whisper's
  sister-language false-positives become a real issue (current
  acceptance: rare, metadata-only impact).
- **SRT/VTT with language tags** per cue (uses the new
  `last_segments[].language` field). UX-driven, not engineering-driven.
- **Streaming code-switching for real-time mode** — Phase 2 is batch-only;
  recorder.py path stays single-language for now.

## Glossary

- **VAD pre-pass** — running Silero VAD on the chunk audio to extract
  speech-only segments before feeding them to Whisper individually.
- **Per-segment language detection** — Whisper's internal
  `detect_language()` running on each VAD segment instead of once on
  the first 30s of the chunk. Triggered by passing `language=None` to
  `model.transcribe()`.
- **`_decode_chunk_mixed`** — new private method that runs the VAD
  pre-pass + per-segment transcribe loop for one chunk.
- **`_decode_chunk_single`** — refactored extraction of the existing
  single-language per-chunk decode logic.
- **Mixed branch** — the `if language == "mixed":` arm inside the
  per-chunk loop in `Transcriber.transcribe()`.
- **Trilingual prompt** — the `_PROMPT_FRAMES["mixed"]` entry
  introduced in Phase 1, reused as `initial_prompt` for every
  segment in the mixed branch.
