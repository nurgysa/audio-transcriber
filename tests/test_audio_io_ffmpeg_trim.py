"""WS-3: ffmpeg_trim must not leave a corrupt/partial output on failure.

The trim does a fast stream-copy, falling back to a re-encode if that fails.
The audit found that when BOTH passes fail, whatever the copy pass wrote is
left on disk as ``dst`` — and audio_cutter reports success on no-exception, so
a caller could treat a half-written file as a valid trim. The fix removes the
partial ``dst`` before the re-encode and again on a final failure.
"""
from __future__ import annotations

import subprocess

import pytest

from audio_io import ffmpeg_trim


def test_ffmpeg_trim_stream_copy_success_is_single_call(tmp_path, monkeypatch):
    """Fast path: stream-copy succeeds → no re-encode fallback is invoked."""
    calls = []
    monkeypatch.setattr("audio_io.subprocess.run", lambda cmd, **kw: calls.append(cmd))
    ffmpeg_trim("src.wav", 0.0, 1.0, str(tmp_path / "out.wav"))
    assert len(calls) == 1


def test_ffmpeg_trim_falls_back_to_reencode(tmp_path, monkeypatch):
    """Stream-copy failure (non-keyframe cut / incompatible container) falls
    back to a re-encode pass; success there means no exception."""
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if len(calls) == 1:
            raise subprocess.CalledProcessError(1, cmd, stderr=b"copy failed")

    monkeypatch.setattr("audio_io.subprocess.run", fake_run)
    ffmpeg_trim("src.wav", 0.0, 1.0, str(tmp_path / "out.wav"))  # must not raise
    assert len(calls) == 2


def test_ffmpeg_trim_cleans_partial_output_on_double_failure(tmp_path, monkeypatch):
    """When BOTH the copy and re-encode fail, the partial dst the copy pass
    wrote must be removed before re-raising — a caller must never find a
    half-written file it would treat as a successful trim."""
    dst = tmp_path / "out.wav"
    dst.write_bytes(b"partial output from the copy pass")

    def fake_run(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd, stderr=b"boom")

    monkeypatch.setattr("audio_io.subprocess.run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        ffmpeg_trim("src.wav", 0.0, 1.0, str(dst))
    assert not dst.exists(), "partial dst must be cleaned on double failure"
