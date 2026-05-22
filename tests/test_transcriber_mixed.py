"""Tests for the language='mixed' path in Transcriber.transcribe().

Mock-based — no real Whisper model, no GPU. Stubs:
  - WhisperModel via MagicMock on the Transcriber._model attribute
  - faster_whisper.vad's get_speech_timestamps via patching segmenter.vad_split
  - audio loading via patching audio_io.load_mono_float32
  - ensure_wav / diarize subprocess via patching at the import site
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from transcriber import Transcriber


def _make_fake_model(per_call_results):
    """Build a MagicMock that mimics faster_whisper.WhisperModel.

    ``per_call_results`` is a list of (segments_iter, info) tuples; each
    successive ``model.transcribe()`` invocation pops one and returns it.
    """
    model = MagicMock()
    model.model = MagicMock()  # for unload_model() / load_model() during offload
    calls = iter(per_call_results)

    def fake_transcribe(audio, **kwargs):
        return next(calls)

    model.transcribe.side_effect = fake_transcribe
    return model


def _make_segment(start, end, text, words=None):
    """Build a faster_whisper segment stand-in (duck-typed)."""
    seg = MagicMock()
    seg.start = start
    seg.end = end
    seg.text = text
    seg.words = words
    return seg


def _make_info(language="ru"):
    info = MagicMock()
    info.language = language
    return info


def test_mixed_routes_to_per_segment_path():
    """When language='mixed', the chunk-loop dispatches to the VAD-pre-pass
    branch and model.transcribe() is called once PER VAD segment, not
    once per chunk."""
    t = Transcriber(model_size="tiny")  # size irrelevant — model is mocked
    # Three VAD segments → three transcribe() calls.
    t._model = _make_fake_model([
        (iter([_make_segment(0.0, 1.0, "Сәлеметсіз бе")]), _make_info("kk")),
        (iter([_make_segment(0.0, 2.0, "Окей, давайте")]), _make_info("ru")),
        (iter([_make_segment(0.0, 1.5, "Slack deployment")]), _make_info("en")),
    ])

    fake_samples = np.zeros(16_000 * 30, dtype=np.float32)  # 30s of "audio"
    vad_segments = [
        {"start": 0, "end": 16_000 * 5},
        {"start": 16_000 * 10, "end": 16_000 * 20},
        {"start": 16_000 * 22, "end": 16_000 * 28},
    ]

    with patch("transcriber.load_mono_float32", return_value=(fake_samples, 16_000)), \
         patch("transcriber.vad_split", return_value=vad_segments):
        out = t._decode_chunk_mixed(
            chunk_path="fake.wav",
            chunk_start_abs=0.0,
            primary_start_abs=0.0,
            initial_prompt="trilingual frame",
            hotwords_str=None,
            cancel_event=None,
        )

    # One model.transcribe call per VAD segment.
    assert t._model.transcribe.call_count == 3
    # Three transcript segments out (one per call's single Whisper segment).
    assert len(out) == 3
    # Texts preserved.
    assert [s["text"] for s in out] == [
        "Сәлеметсіз бе", "Окей, давайте", "Slack deployment",
    ]
