from pathlib import Path


def test_launcher_defined_in_mixin():
    src = Path("ui/app/dialogs_mixin.py").read_text(encoding="utf-8")
    assert "from ui.dialogs.directory import DirectoryDialog" in src
    assert "def _open_directory_dialog" in src
    assert "DirectoryDialog(self)" in src


def test_toolbar_button_wired_in_builder():
    src = Path("ui/app/builder.py").read_text(encoding="utf-8")
    assert "Справочники" in src
    assert "_open_directory_dialog" in src
