"""Dedup on/off section in Settings (spec 2026-06-11, PR-3).

Source-text checks — no ui imports on Linux CI. The consumer gate
(extract_tasks reading config["dedup_enabled"]) is already locked by
tests/test_dialog_dedup_ui.py; these tests pin the Settings side.
"""
from pathlib import Path

BUILDER = Path("ui/dialogs/settings_builder.py").read_text(encoding="utf-8")
SETTINGS = Path("ui/dialogs/settings.py").read_text(encoding="utf-8")


def _section_block() -> str:
    start = BUILDER.index("def build_dedup_section")
    nxt = BUILDER.find("\ndef ", start + 1)
    return BUILDER[start:nxt if nxt != -1 else len(BUILDER)]


def test_builder_has_dedup_section():
    assert "def build_dedup_section" in BUILDER


def test_dedup_checkbox_bound_to_config_key_and_saves():
    block = _section_block()
    assert "CTkCheckBox" in block
    assert '"dedup_enabled"' in block
    assert "save_config" in block


def test_dedup_default_matches_consumer_gate():
    # Must mirror extract_tasks' config.get("dedup_enabled", True) — a
    # missing key means ON on both sides.
    assert 'get("dedup_enabled", True)' in _section_block()


def test_settings_wires_dedup_section_on_integrations_tab():
    assert "build_dedup_section" in SETTINGS
