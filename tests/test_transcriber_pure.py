"""Tests for transcriber.py's pure helpers.

Importing transcriber pulls in ctranslate2 + faster-whisper, which is
slow but acceptable once per pytest session. The functions we exercise
here are themselves model-free and run in microseconds.
"""
import threading

import pytest

from transcriber import (
    TranscriptionCancelled,
    _assign_speakers_word_level,
    _build_initial_prompt,
    _check_cancelled,
    _find_speaker_by_overlap,
    _parse_progress_line,
    _speaker_at_time,
)

# ── _build_initial_prompt ──────────────────────────────────────────


def test_initial_prompt_is_none_when_no_signal():
    assert _build_initial_prompt(language=None, hotwords_str=None) is None
    assert _build_initial_prompt(language="auto", hotwords_str="  ") is None


def test_initial_prompt_uses_language_frame_when_only_language():
    out = _build_initial_prompt(language="ru", hotwords_str=None)
    assert out is not None
    assert "русском" in out
    assert "Терм" not in out and "Term" not in out


def test_initial_prompt_includes_terms_when_provided():
    out = _build_initial_prompt(language="ru", hotwords_str="Kubernetes, Docker")
    assert out is not None
    assert "Упомянутые термины: Kubernetes, Docker" in out
    assert "русском" in out


def test_initial_prompt_unknown_language_falls_back_to_terms_only():
    out = _build_initial_prompt(language="zz", hotwords_str="alpha, beta")
    assert out == "Terms: alpha, beta."


def test_initial_prompt_truncates_at_last_comma():
    # Build enough terms that the joined string blows past the 400-char cap.
    long_terms = ", ".join([f"term{i:03d}" for i in range(120)])
    out = _build_initial_prompt(language="en", hotwords_str=long_terms)
    assert out is not None
    assert len(out) <= 400
    # Should truncate on a clean comma boundary, ending with a period.
    assert out.endswith(".")


# ── _parse_progress_line ───────────────────────────────────────────


def test_parse_progress_valid_line_maps_to_70_90_band():
    # segmentation: range (0.10, 0.25). At 50% completion of segmentation,
    # sub_percent = 0.10 + 0.5 * 0.15 = 0.175; final = 70 + 20 * 0.175 = 73.5.
    assert _parse_progress_line("PROGRESS\tsegmentation\t1\t2\n") == pytest.approx(73.5)


def test_parse_progress_unknown_step_returns_none():
    # Unknown step intentionally returns None so the GUI bar doesn't jump
    # if a future pyannote version adds new stages.
    assert _parse_progress_line("PROGRESS\twho_knows\t1\t2\n") is None


def test_parse_progress_malformed_lines_return_none():
    assert _parse_progress_line("not progress at all") is None
    assert _parse_progress_line("PROGRESS\tsegmentation\tNaN\t2\n") is None
    assert _parse_progress_line("PROGRESS\tonly\tthree\n") is None


def test_parse_progress_zero_total_does_not_divide():
    # Defensive: a 0/0 step shouldn't blow up; ratio falls back to 0.
    assert _parse_progress_line("PROGRESS\tsegmentation\t0\t0\n") == pytest.approx(72.0)


# ── _check_cancelled ───────────────────────────────────────────────


def test_check_cancelled_passes_through_when_unset():
    ev = threading.Event()
    _check_cancelled(ev)  # should not raise
    _check_cancelled(None)  # None is the "no cancel signal" caller


def test_check_cancelled_raises_when_set():
    ev = threading.Event()
    ev.set()
    with pytest.raises(TranscriptionCancelled):
        _check_cancelled(ev)


# ── _speaker_at_time / _find_speaker_by_overlap ────────────────────


def test_speaker_at_time_inside_turn():
    turns = [(0.0, 5.0, "SPEAKER_00"), (5.0, 10.0, "SPEAKER_01")]
    assert _speaker_at_time(2.5, turns) == "SPEAKER_00"
    assert _speaker_at_time(7.5, turns) == "SPEAKER_01"


def test_speaker_at_time_falls_back_to_nearest_in_gap():
    # No turn covers t=4.6; the gap between SPEAKER_00 (ends 4.0) and
    # SPEAKER_01 (starts 5.0) makes 4.6 closer to SPEAKER_01's start.
    turns = [(0.0, 4.0, "SPEAKER_00"), (5.0, 10.0, "SPEAKER_01")]
    assert _speaker_at_time(4.6, turns) == "SPEAKER_01"


def test_find_speaker_by_overlap_picks_max_overlap():
    turns = [(0.0, 3.0, "A"), (3.0, 10.0, "B")]
    # Segment [2.0, 5.0]: 1.0s overlap with A, 2.0s with B → B wins.
    assert _find_speaker_by_overlap(2.0, 5.0, turns) == "B"


# ── _assign_speakers_word_level ────────────────────────────────────


def test_assign_speakers_word_level_splits_segment_at_speaker_change():
    """Two words on different speakers must produce two output sub-segments."""
    segments = [{
        "start": 0.0, "end": 4.0, "text": "Да Согласен",
        "words": [
            {"start": 0.0, "end": 1.0, "word": "Да"},
            {"start": 3.0, "end": 4.0, "word": " Согласен"},
        ],
    }]
    speaker_turns = [(0.0, 2.0, "A"), (2.0, 5.0, "B")]
    out = _assign_speakers_word_level(segments, speaker_turns)
    assert [(s["text"], s["speaker"]) for s in out] == [("Да", "A"), ("Согласен", "B")]


def test_assign_speakers_word_level_falls_back_when_words_missing():
    """Segments without word-level timestamps use whole-segment overlap."""
    segments = [{"start": 0.0, "end": 5.0, "text": "Текст", "words": []}]
    speaker_turns = [(0.0, 5.0, "A")]
    out = _assign_speakers_word_level(segments, speaker_turns)
    assert out == [{"start": 0.0, "end": 5.0, "text": "Текст", "speaker": "A"}]
