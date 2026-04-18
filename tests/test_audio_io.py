"""Tests for the torch-free audio I/O helpers.

Avoids the ffmpeg-dependent code paths (ensure_wav with conversion,
split chunking) — those are integration tests that need a real ffmpeg
binary. The branches we cover here exercise pure logic + soundfile.
"""
import numpy as np
import pytest
import soundfile as sf

from audio_io import (
    SAMPLE_RATE, _ffmpeg_time, ensure_wav, get_duration_s,
    load_mono_float32, split_wav_into_chunks,
)


# ── _ffmpeg_time ───────────────────────────────────────────────────


@pytest.mark.parametrize("seconds,expected", [
    (0.0,       "00:00:00.000"),
    (1.5,       "00:00:01.500"),
    (61.0,      "00:01:01.000"),
    (3725.999,  "01:02:05.999"),
])
def test_ffmpeg_time(seconds, expected):
    assert _ffmpeg_time(seconds) == expected


# ── get_duration_s ─────────────────────────────────────────────────


def _write_silent_wav(path, seconds: float, channels: int = 1) -> None:
    """Generate a silent WAV at the project's standard 16 kHz sample rate."""
    n = int(seconds * SAMPLE_RATE)
    data = np.zeros((n, channels), dtype=np.float32) if channels > 1 else np.zeros(n, dtype=np.float32)
    sf.write(str(path), data, SAMPLE_RATE, subtype="PCM_16")


def test_get_duration_matches_source(tmp_path):
    wav = tmp_path / "synthetic.wav"
    _write_silent_wav(wav, 2.5)
    # Sample-quantization rounding can shift duration by a fraction of a
    # frame (1/16000s); a 5 ms tolerance is well below any audible threshold.
    assert get_duration_s(str(wav)) == pytest.approx(2.5, abs=0.005)


# ── ensure_wav short-circuit ───────────────────────────────────────


def test_ensure_wav_returns_input_for_wav_when_not_normalizing(tmp_path):
    """No ffmpeg invocation when input is already WAV and normalize=False."""
    wav = tmp_path / "raw.wav"
    _write_silent_wav(wav, 0.5)
    out_path, is_temp = ensure_wav(str(wav), normalize=False)
    # Same file, no temp copy made.
    assert out_path == str(wav)
    assert is_temp is False


# ── load_mono_float32 ──────────────────────────────────────────────


def test_load_mono_float32_downmixes_stereo(tmp_path):
    wav = tmp_path / "stereo.wav"
    # Distinct per-channel signal so the channel-average is observable.
    n = SAMPLE_RATE  # 1 second
    left = np.full(n, 0.5, dtype=np.float32)
    right = np.full(n, -0.5, dtype=np.float32)
    stereo = np.stack([left, right], axis=1)
    sf.write(str(wav), stereo, SAMPLE_RATE, subtype="PCM_16")

    samples, sr = load_mono_float32(str(wav))
    assert sr == SAMPLE_RATE
    assert samples.ndim == 1
    # Downmix is the per-frame mean: (0.5 + -0.5) / 2 = 0.0 across the file.
    np.testing.assert_allclose(samples, np.zeros(n, dtype=np.float32), atol=1e-3)


# ── split_wav_into_chunks (no-chunk fast path) ─────────────────────


def test_split_returns_single_chunk_when_under_threshold(tmp_path):
    """Files shorter than the chunk size return [(path, 0.0, 0.0)] without copying."""
    wav = tmp_path / "short.wav"
    _write_silent_wav(wav, 1.0)
    out_dir = tmp_path / "chunks"
    chunks = split_wav_into_chunks(str(wav), chunk_duration_s=60, out_dir=str(out_dir))
    assert chunks == [(str(wav), 0.0, 0.0)]
    # No ffmpeg call → no chunks dir created.
    assert not out_dir.exists()
