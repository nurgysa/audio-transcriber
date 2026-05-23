"""Silence removal using Silero VAD (via faster-whisper).

Pure logic, no UI — can be tested standalone.

Typical flow:
    result = remove_silences(samples, sample_rate)
    soundfile.write(out_path, result.speech_samples, sample_rate, subtype="PCM_16")
"""

from dataclasses import dataclass, field

import numpy as np

from audio_io import SAMPLE_RATE


@dataclass
class SilenceRemovalResult:
    """Result of a silence-removal pass."""

    # Concatenated speech-only audio (float32 mono, same sample rate as input).
    speech_samples: np.ndarray

    # Time ranges (in seconds, relative to input) that were detected as SILENCE.
    # Used by the UI to draw red overlays on the waveform.
    silence_ranges_sec: list[tuple[float, float]] = field(default_factory=list)

    # Time ranges (in seconds) that were detected as SPEECH — complement of silence_ranges_sec.
    speech_ranges_sec: list[tuple[float, float]] = field(default_factory=list)

    # Total duration removed (sum of silence_ranges_sec).
    removed_sec: float = 0.0

    # Total duration kept (len(speech_samples) / sample_rate).
    kept_sec: float = 0.0

    # Number of silence intervals found.
    num_silences: int = 0


# ── VAD defaults ────────────────────────────────────────────────
# Tuned for spoken-word recordings. These come from several iterations of
# manual testing with Silero VAD (the same model that faster-whisper uses
# for `vad_filter=True` in transcriber.py). Changing these without testing
# is not recommended — Silero is sensitive to the combination.
_VAD_THRESHOLD = 0.5               # 0-1, higher = stricter ("is this speech?")
_MIN_SPEECH_MS = 250               # ignore blips shorter than this
_MIN_SILENCE_MS = 500              # merge speech across silences shorter than this
_SPEECH_PAD_MS = 200               # keep this much padding around each speech region


def remove_silences(samples: np.ndarray, sample_rate: int) -> SilenceRemovalResult:
    """Detect speech in `samples` and return a speech-only copy + metadata.

    Args:
        samples: 1-D float32 mono audio, values in [-1, 1]. Must be the format
            produced by `AudioCutter._load_file` (audio_cutter.py:258).
        sample_rate: Sample rate of `samples`, typically 16_000.

    Returns:
        SilenceRemovalResult — see class docstring. If no speech is detected,
        `speech_samples` is an empty array and `silence_ranges_sec` covers
        the whole input.
    """
    # Handle empty input up front.
    if samples is None or len(samples) == 0:
        return SilenceRemovalResult(speech_samples=np.array([], dtype=np.float32))

    # Silero VAD's neural model is 16-kHz-only and faster-whisper does NOT
    # resample non-16k input before feeding the model. Without resampling
    # here, non-16k WAVs (44.1 / 48 kHz files coming from audio_cutter via
    # load_mono_float32) would land at wrong formant frequencies for
    # Silero — detection collapses. resample_to_16khz_mono short-circuits
    # when sample_rate already equals SAMPLE_RATE so the 16k fast path
    # pays nothing. See PR #34's discussion for the partial-fix history;
    # this is the proper fix and supersedes the sampling_rate kwarg
    # workaround.
    #
    # IMPORTANT: we resample for VAD ONLY. The output ``speech_samples``
    # is trimmed from the ORIGINAL samples (at the caller's native rate)
    # using TIME-BASED indexing — audio_cutter writes the result with
    # ``self._sample_rate`` (the caller's rate), and producing a 16 kHz
    # array would silently change playback speed of the saved file.
    total_duration_sec = len(samples) / sample_rate
    if sample_rate != SAMPLE_RATE:
        from audio_io import resample_to_16khz_mono
        vad_samples = resample_to_16khz_mono(samples, sample_rate)
        vad_sample_rate = SAMPLE_RATE
    else:
        vad_samples = samples
        vad_sample_rate = sample_rate

    # Lazy import: keeps module import cheap for callers that only need the dataclass.
    # faster-whisper exposes the same Silero VAD that it uses internally for
    # `vad_filter=True` — so we get accurate speech detection with ZERO new deps.
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    vad_options = VadOptions(
        threshold=_VAD_THRESHOLD,
        min_speech_duration_ms=_MIN_SPEECH_MS,
        min_silence_duration_ms=_MIN_SILENCE_MS,
        speech_pad_ms=_SPEECH_PAD_MS,
    )

    # Returns a list of dicts like [{"start": int, "end": int}, ...] where
    # start/end are sample indices into ``vad_samples`` (always 16 kHz).
    # sampling_rate matches that array — explicit even though it equals
    # the faster-whisper default, so a future refactor that touches the
    # rate elsewhere still gets the kwarg right.
    speech_timestamps = get_speech_timestamps(
        vad_samples,
        vad_options,
        sampling_rate=vad_sample_rate,
    )

    # Convert VAD sample-ranges to seconds (wall time, rate-independent).
    # We clamp to the ORIGINAL duration so any tiny ffmpeg-resample length
    # drift doesn't push speech indices past the end of `samples`.
    speech_ranges_sec = [
        (
            min(ts["start"] / vad_sample_rate, total_duration_sec),
            min(ts["end"] / vad_sample_rate, total_duration_sec),
        )
        for ts in speech_timestamps
    ]

    # Invert the speech ranges to get silence ranges. This is the interesting
    # piece — edge cases around leading/trailing silence, no speech at all,
    # and speech touching the file boundaries.
    silence_ranges_sec = _compute_silence_ranges(
        speech_ranges_sec,
        total_duration_sec=total_duration_sec,
    )

    # Concatenate the speech portions FROM THE ORIGINAL samples (at the
    # caller's native rate) using time-based indexing. This preserves the
    # caller's sample rate end-to-end; audio_cutter's WAV-write step uses
    # ``self._sample_rate`` and would playback at the wrong speed if we
    # returned the 16 kHz ``vad_samples`` chunks instead.
    if speech_ranges_sec:
        chunks = [
            samples[int(start * sample_rate):int(end * sample_rate)]
            for start, end in speech_ranges_sec
        ]
        speech_samples = np.concatenate(chunks)
    else:
        speech_samples = np.array([], dtype=np.float32)

    kept_sec = len(speech_samples) / sample_rate
    removed_sec = sum(e - s for s, e in silence_ranges_sec)

    return SilenceRemovalResult(
        speech_samples=speech_samples.astype(np.float32, copy=False),
        silence_ranges_sec=silence_ranges_sec,
        speech_ranges_sec=speech_ranges_sec,
        removed_sec=removed_sec,
        kept_sec=kept_sec,
        num_silences=len(silence_ranges_sec),
    )


def _compute_silence_ranges(
    speech_ranges_sec: list[tuple[float, float]],
    total_duration_sec: float,
) -> list[tuple[float, float]]:
    """Invert a sorted list of speech ranges into a list of silence ranges.

    Given the speech regions and the total duration of the audio, return the
    complementary list of silence regions in the same (start, end) format.

    Examples:
        total=10.0, speech=[(2.0, 5.0), (7.0, 9.0)]
            → silence=[(0.0, 2.0), (5.0, 7.0), (9.0, 10.0)]

        total=10.0, speech=[]
            → silence=[(0.0, 10.0)]          # whole file is silence

        total=10.0, speech=[(0.0, 10.0)]
            → silence=[]                     # whole file is speech

        total=10.0, speech=[(0.0, 4.0), (6.0, 10.0)]
            → silence=[(4.0, 6.0)]           # no leading/trailing silence

    Notes:
        - `speech_ranges_sec` is guaranteed to be sorted and non-overlapping
          (this is how Silero VAD returns them, and we don't reorder them).
        - Treat any gap with length < ~1e-6 seconds as "no gap" — that's
          floating-point noise from the sample→sec conversion, not a real
          silence region.
        - The caller relies on this list for the red canvas overlays, so
          correctness on the edges (0.0 and total_duration_sec) matters.

    """
    # Floating-point noise floor: gaps smaller than this are artifacts of
    # the sample-index → seconds conversion, not real silence.
    eps = 1e-6

    # Corner case: no speech at all → the entire file is one silence block.
    if not speech_ranges_sec:
        if total_duration_sec > eps:
            return [(0.0, total_duration_sec)]
        return []

    result: list[tuple[float, float]] = []

    # 1. Leading silence (before the first speech region).
    first_start = speech_ranges_sec[0][0]
    if first_start > eps:
        result.append((0.0, first_start))

    # 2. Gaps between consecutive speech regions.
    for i in range(len(speech_ranges_sec) - 1):
        prev_end = speech_ranges_sec[i][1]
        next_start = speech_ranges_sec[i + 1][0]
        if next_start - prev_end > eps:
            result.append((prev_end, next_start))

    # 3. Trailing silence (after the last speech region).
    last_end = speech_ranges_sec[-1][1]
    if total_duration_sec - last_end > eps:
        result.append((last_end, total_duration_sec))

    return result
