"""Phase 7.0 smoke tests for the Settings dialog GDrive section.

Headless — no Tk root spun up. Verifies imports + class surface so
ImportError or AttributeError regressions surface in CI without
needing a display.

Imports `ui.app` BEFORE `ui.dialogs.settings` to avoid the pre-existing
circular-import topology between settings.py (which imports
`ui.app.constants.LANGUAGES`) and `ui.app.dialogs_mixin` (which imports
SettingsDialog at module level).
"""
from __future__ import annotations

import inspect

import ui.app  # noqa: F401 — load the package first, then settings can resolve


def test_settings_dialog_has_gdrive_section_builder():
    """SettingsDialog must expose _build_gdrive_section as a method."""
    from ui.dialogs.settings import SettingsDialog
    assert hasattr(SettingsDialog, "_build_gdrive_section")
    assert callable(SettingsDialog._build_gdrive_section)


def test_settings_dialog_has_gdrive_handlers():
    """Sign-in/out handlers must exist on SettingsDialog (referenced by
    button commands in _build_gdrive_section)."""
    from ui.dialogs.settings import SettingsDialog
    for method in (
        "_handle_gdrive_signin",
        "_handle_gdrive_signout",
        "_on_gdrive_signin_success",
        "_on_gdrive_signin_failure",
        "_refresh_gdrive_button_state",
    ):
        assert hasattr(SettingsDialog, method), f"Missing {method}"


def test_settings_mixin_has_gdrive_callbacks():
    """App (via SettingsMixin) must expose the change callbacks the
    Settings dialog button handlers call back into."""
    from ui.app.settings_mixin import SettingsMixin
    for method in (
        "_compute_gdrive_status_text",
        "_on_gdrive_signed_in",
        "_on_gdrive_signed_out",
    ):
        assert hasattr(SettingsMixin, method), f"Missing {method}"
        assert callable(getattr(SettingsMixin, method))


def test_builder_creates_gdrive_vars():
    """ui.app.builder source must mention the three GDrive Vars +
    GDriveAuth instance so they're created during App init. Source
    inspection is the safest check without a real Tk root."""
    from ui.app import builder
    src = inspect.getsource(builder)
    for marker in (
        "_gdrive_auth",
        "_gdrive_status_var",
        "_gdrive_account_email_var",
        "_gdrive_enabled_var",
        "from gdrive.auth import GDriveAuth",
    ):
        assert marker in src, f"builder.py source missing {marker!r}"
