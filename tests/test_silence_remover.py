"""Tests for ``silence_remover._compute_silence_ranges``.

The function inverts a sorted list of speech-time ranges into the gaps
between them — sounds simple, but the docstring promises specific
behavior at file boundaries (leading/trailing silence) and around the
1e-6 second floating-point noise floor. These tests pin those promises
down so a future refactor that "simplifies" the eps logic can't quietly
introduce a phantom silence region the UI would render as a red bar.

The wrapper ``remove_silences`` itself isn't tested here — it's a thin
adapter around faster_whisper's Silero VAD, which is too heavy for unit
tests. The interesting logic is the inversion in ``_compute_silence_ranges``.
"""
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from silence_remover import _compute_silence_ranges, remove_silences

# ── Cases lifted straight from the docstring ────────────────────────


def test_docstring_example_three_silences_around_two_speech_blocks():
    # total=10.0, speech=[(2.0, 5.0), (7.0, 9.0)] → silence=[(0.0, 2.0), (5.0, 7.0), (9.0, 10.0)]
    silences = _compute_silence_ranges(
        speech_ranges_sec=[(2.0, 5.0), (7.0, 9.0)],
        total_duration_sec=10.0,
    )
    assert silences == [(0.0, 2.0), (5.0, 7.0), (9.0, 10.0)]


def test_docstring_example_no_speech_means_whole_file_is_silence():
    # total=10.0, speech=[] → silence=[(0.0, 10.0)]
    silences = _compute_silence_ranges(
        speech_ranges_sec=[],
        total_duration_sec=10.0,
    )
    assert silences == [(0.0, 10.0)]


def test_docstring_example_full_speech_means_no_silence():
    # total=10.0, speech=[(0.0, 10.0)] → silence=[]
    silences = _compute_silence_ranges(
        speech_ranges_sec=[(0.0, 10.0)],
        total_duration_sec=10.0,
    )
    assert silences == []


def test_docstring_example_no_leading_or_trailing_silence():
    # total=10.0, speech=[(0.0, 4.0), (6.0, 10.0)] → silence=[(4.0, 6.0)]
    silences = _compute_silence_ranges(
        speech_ranges_sec=[(0.0, 4.0), (6.0, 10.0)],
        total_duration_sec=10.0,
    )
    assert silences == [(4.0, 6.0)]


# ── Boundary cases the docstring doesn't cover ──────────────────────


def test_zero_duration_with_no_speech_returns_empty():
    """A degenerate input (no audio at all) must not produce a silence
    range — that would render as a zero-width red bar in the UI."""
    silences = _compute_silence_ranges(
        speech_ranges_sec=[],
        total_duration_sec=0.0,
    )
    assert silences == []


def test_speech_starting_exactly_at_zero_no_leading_silence():
    silences = _compute_silence_ranges(
        speech_ranges_sec=[(0.0, 5.0)],
        total_duration_sec=10.0,
    )
    assert silences == [(5.0, 10.0)]  # only trailing silence


def test_speech_ending_exactly_at_total_no_trailing_silence():
    silences = _compute_silence_ranges(
        speech_ranges_sec=[(3.0, 10.0)],
        total_duration_sec=10.0,
    )
    assert silences == [(0.0, 3.0)]  # only leading silence


# ── The eps (1e-6) noise-floor invariant ───────────────────────────


def test_sub_eps_gap_does_not_produce_phantom_silence():
    """Floating-point noise floor: a gap < 1e-6 between consecutive
    speech ranges must be treated as 'no gap' — NOT a tiny silence range.

    This is the runtime invariant that's easiest to break by 'simplifying'
    the eps comparison (e.g. someone changes `> eps` to `>= 0` and now
    every numerically-touching pair leaves a 0.0-second silence behind).

    Build inputs where:
      - There are two speech ranges almost touching (gap ~5e-7 sec)
      - There IS a real leading silence to keep (so the result isn't empty)
    Then assert the silence list contains ONLY the leading region — the
    sub-eps gap between the two speech ranges should be invisible.
    """
    silences = _compute_silence_ranges(
        speech_ranges_sec=[(0.5, 4.0), (4.0 + 5e-7, 9.0)],
        total_duration_sec=10.0,
    )
    # Expect ONLY the real leading + trailing silence — sub-eps gap dropped.
    assert silences == [(0.0, 0.5), (9.0, 10.0)]


def test_multiple_consecutive_sub_eps_gaps_all_dropped():
    """Stronger version: three speech ranges almost touching → no internal
    silences at all, even though there are two sub-eps gaps."""
    silences = _compute_silence_ranges(
        speech_ranges_sec=[(0.0, 4.0), (4.0 + 5e-7, 6.0), (6.0 + 5e-7, 10.0)],
        total_duration_sec=10.0,
    )
    assert silences == []


# ── 16 kHz enforcement (full fix for the latent VAD bug) ────────────
#
# History: PR #34 forwarded sample_rate to get_speech_timestamps as a
# partial fix. That made faster-whisper's ms→sample arithmetic correct
# but didn't help Silero's neural model, which is 16-kHz-only. This file
# now tests the full fix: silence_remover resamples non-16k input to
# 16 kHz upstream (via audio_io.resample_to_16khz_mono), then hands the
# 16k array to VAD.


def test_remove_silences_resamples_non_16k_input_before_vad():
    """44.1 kHz input must be resampled to 16 kHz before VAD runs.

    The resample helper is patched as a tripwire that asserts the call
    shape (numpy array + original sample_rate kwarg). Returns synthetic
    16k samples so the downstream code path executes normally.
    """
    samples = np.zeros(44_100, dtype=np.float32)  # 1 second @ 44.1k
    resampled = np.zeros(16_000, dtype=np.float32)  # what the helper would return

    resample_mock = MagicMock(return_value=resampled)
    captured_vad_kwargs: dict = {}

    def fake_get_speech_timestamps(audio, vad_options=None, **kwargs):
        captured_vad_kwargs.update(kwargs)
        return []

    with patch("audio_io.resample_to_16khz_mono", resample_mock), \
         patch(
             "faster_whisper.vad.get_speech_timestamps",
             side_effect=fake_get_speech_timestamps,
         ):
        remove_silences(samples, sample_rate=44_100)

    # The resample helper was called once with the original (numpy, 44100) pair.
    assert resample_mock.call_count == 1, (
        f"Expected exactly 1 resample call, got {resample_mock.call_count}"
    )
    call_args = resample_mock.call_args
    assert call_args.args[1] == 44_100, (
        f"resample called with wrong sample_rate: {call_args.args[1]}"
    )
    # VAD then ran at 16 kHz (post-resample), not at 44.1.
    assert captured_vad_kwargs.get("sampling_rate") == 16_000, (
        f"VAD didn't receive 16k sampling_rate: {captured_vad_kwargs}"
    )


def test_remove_silences_skips_resample_for_16k_input():
    """16 kHz input must NOT trigger the resample helper. This is the
    fast path — the dominant case in production where ensure_wav or a
    16k WAV upstream has already produced the right rate.

    Tripwire pattern: patch resample helper as MagicMock; if it's called,
    the assertion at the end fails.
    """
    samples = np.zeros(16_000, dtype=np.float32)  # 1 second @ 16k
    resample_tripwire = MagicMock()

    with patch("audio_io.resample_to_16khz_mono", resample_tripwire), \
         patch(
             "faster_whisper.vad.get_speech_timestamps",
             return_value=[],
         ):
        remove_silences(samples, sample_rate=16_000)

    resample_tripwire.assert_not_called()
