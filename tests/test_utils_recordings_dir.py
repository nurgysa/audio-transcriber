"""utils.get_recordings_dir — recordings live under the active meetings dir.

Monkeypatch-only; never imports ui.app/recorder (native deps absent on CI).
"""
from __future__ import annotations

import os

import utils


def test_recordings_dir_is_subfolder_of_meetings_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "get_meetings_dir", lambda: str(tmp_path / "vault"))
    assert utils.get_recordings_dir() == os.path.join(str(tmp_path / "vault"), "recordings")
