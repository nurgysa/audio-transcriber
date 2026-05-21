"""Tests for ui/app/constants.py — small dict-level invariants.

Kept separate from UI tests because LANGUAGES, MODELS, SPEAKER_COUNTS etc.
are pure data structures imported by both UI and non-UI code paths
(Settings dialog + Transcriber's language hint plumbing).

We load ``constants.py`` directly via ``importlib.util`` rather than
``from ui.app.constants import LANGUAGES``. The dotted import would force
Python to execute ``ui/app/__init__.py`` first, which eagerly imports
``recorder`` → ``sounddevice`` → requires the PortAudio system library
at import time. That library is bundled with the ``sounddevice`` wheel on
Windows but absent on the Linux CI runner, so the dotted import errors
out during pytest collection. The dict-level invariants we verify here
don't need any of that machinery — bypassing the package init keeps the
test pure and CI-portable.
"""
import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_CONSTANTS_PATH = os.path.join(
    os.path.dirname(_HERE), "ui", "app", "constants.py"
)
_spec = importlib.util.spec_from_file_location(
    "_ui_app_constants_isolated", _CONSTANTS_PATH
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

LANGUAGES = _module.LANGUAGES


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
