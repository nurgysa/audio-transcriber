"""Tests for ui/app/constants.py — small dict-level invariants.

Kept separate from UI tests because LANGUAGES, MODELS, SPEAKER_COUNTS etc.
are pure data structures imported by both UI and non-UI code paths
(Settings dialog + Transcriber's language hint plumbing).
"""
from __future__ import annotations

from ui.app.constants import LANGUAGES


def test_languages_contains_mixed_sentinel():
    """The `Смешанный (KZ+RU+EN)` entry must map to the `mixed` sentinel —
    the same string the rest of the codebase branches on
    (transcriber/__init__.py, transcriber/prompt.py, providers/*.py).
    """
    assert "Смешанный (KZ+RU+EN)" in LANGUAGES
    assert LANGUAGES["Смешанный (KZ+RU+EN)"] == "mixed"


def test_languages_preserves_single_lang_entries():
    """Regression: existing single-language entries unchanged."""
    assert LANGUAGES["Авто-определение"] is None
    assert LANGUAGES["Казахский"] == "kk"
    assert LANGUAGES["Русский"] == "ru"
    assert LANGUAGES["English"] == "en"
