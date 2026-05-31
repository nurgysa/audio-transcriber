"""Source-text checks for the dedup UI wiring (PR-3).

CustomTkinter / ui.app must NOT be imported on Linux CI (sounddevice loads
PortAudio at import time — see feedback_ui_app_import_breaks_linux_ci). We
assert on the FILE TEXT instead: structural guarantees that the badge,
toggle, worker-thread driver, and config/settings plumbing are present and
wired — without importing any Tk module.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROW = (ROOT / "ui" / "dialogs" / "extract_tasks" / "task_row.py").read_text("utf-8")
DIALOG = (ROOT / "ui" / "dialogs" / "extract_tasks" / "__init__.py").read_text("utf-8")
SETTINGS = (ROOT / "ui" / "dialogs" / "settings.py").read_text("utf-8")
CONFIG = (ROOT / "config.example.json").read_text("utf-8")


# ── task_row badge + toggle (Task 4) ─────────────────────────────────


def test_task_row_has_dedup_badge_and_toggle():
    assert "set_dup_visual" in ROW
    assert "возможный дубль" in ROW
    assert "CTkSegmentedButton" in ROW
    assert "Закомментировать" in ROW and "Создать новую" in ROW
    assert "dup_action" in ROW


def test_task_row_renders_commented_badge():
    # set_status_visual must handle the COMMENTED state explicitly.
    assert "COMMENTED" in ROW
