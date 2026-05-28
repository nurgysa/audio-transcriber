"""Naming consistency in the Settings dialog.

Use 'Транскрипция' / 'Облачное распознавание' instead of 'Транскрибация'.
"""
from __future__ import annotations

from pathlib import Path

SETTINGS_PATH = (
    Path(__file__).resolve().parent.parent / "ui" / "dialogs" / "settings.py"
)


def test_no_transkribatsia_form():
    source = SETTINGS_PATH.read_text(encoding="utf-8")
    assert "Транскрибация" not in source, (
        "Use 'Транскрипция' or 'Облачное распознавание' — not 'Транскрибация'"
    )


def test_oblachnoe_raspoznavanie_present():
    """The Cloud STT section title was renamed to 'Облачное распознавание'."""
    source = SETTINGS_PATH.read_text(encoding="utf-8")
    assert "Облачное распознавание" in source, (
        "Cloud STT section title must be 'Облачное распознавание' per spec"
    )
