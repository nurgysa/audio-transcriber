"""SettingsDialog uses the unified api_key_row helper for each API key section.

Source-text check — we cannot import ui.dialogs.settings (sounddevice
PortAudio issue on Linux CI). See feedback_ui_app_import_breaks_linux_ci.

This assertion is BUMPED across Tasks 2-5 of the plan as each section is
migrated. Final target after Task 5: 4 calls (Cloud STT + OpenRouter +
Linear + Glide).
"""
from __future__ import annotations

from pathlib import Path

SETTINGS_PATH = (
    Path(__file__).resolve().parent.parent / "ui" / "dialogs" / "settings.py"
)


def test_settings_imports_api_key_row():
    source = SETTINGS_PATH.read_text(encoding="utf-8")
    assert "api_key_row" in source, (
        "ui/dialogs/settings.py must import api_key_row from ui.widgets"
    )


def test_settings_calls_api_key_row_at_least_four_times():
    """Cloud STT + OpenRouter + Linear + Glide = 4 call sites. Counted
    via 'api_key_row(' rather than 'api_key_row,' to skip import lines."""
    source = SETTINGS_PATH.read_text(encoding="utf-8")
    n_calls = source.count("api_key_row(")
    assert n_calls >= 1, (
        f"Expected ≥ 1 api_key_row(...) call after Task 2, got {n_calls}"
    )
