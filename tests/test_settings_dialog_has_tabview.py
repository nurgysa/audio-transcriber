"""SettingsDialog uses a CTkTabview with the three expected tabs.

Source-text checks only — see feedback_ui_app_import_breaks_linux_ci.
"""
from __future__ import annotations

import re
from pathlib import Path

SETTINGS_PATH = (
    Path(__file__).resolve().parent.parent / "ui" / "dialogs" / "settings.py"
)


def test_imports_ctk_tabview_or_references_it():
    source = SETTINGS_PATH.read_text(encoding="utf-8")
    assert "CTkTabview" in source, (
        "ui/dialogs/settings.py must reference CTkTabview"
    )


def test_three_tabs_added_with_expected_names():
    """Three tabs: Транскрипция, Интеграции, Резервная копия. We grep
    for `.add("<name>")` calls — flexible to either chained-call
    construction or post-construction tab adding."""
    source = SETTINGS_PATH.read_text(encoding="utf-8")

    expected = ["Транскрипция", "Интеграции", "Резервная копия"]
    for name in expected:
        pattern = rf'\.add\(\s*[\'"]{re.escape(name)}[\'"]\s*\)'
        assert re.search(pattern, source), (
            f'Expected `.add("{name}")` call in settings.py'
        )
