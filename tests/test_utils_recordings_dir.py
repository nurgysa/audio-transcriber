"""utils.get_recordings_dir — recordings live under the active meetings dir.

Monkeypatch-only; never imports ui.app/recorder (native deps absent on CI).
"""
from __future__ import annotations

import os

import utils


def test_recordings_dir_is_subfolder_of_meetings_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "get_meetings_dir", lambda: str(tmp_path / "vault"))
    assert utils.get_recordings_dir() == os.path.join(str(tmp_path / "vault"), "recordings")


def test_should_delete_off_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "get_recordings_dir", lambda: str(tmp_path / "rec"))
    inside = str(tmp_path / "rec" / "recording_x.wav")
    assert utils.should_delete_after_transcription({}, inside) is False


def test_should_delete_when_on_and_inside(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "get_recordings_dir", lambda: str(tmp_path / "rec"))
    inside = str(tmp_path / "rec" / "recording_x.wav")
    cfg = {"delete_recording_after_transcription": True}
    assert utils.should_delete_after_transcription(cfg, inside) is True


def test_should_not_delete_when_on_but_outside(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "get_recordings_dir", lambda: str(tmp_path / "rec"))
    outside = str(tmp_path / "downloads" / "user_clip.wav")
    cfg = {"delete_recording_after_transcription": True}
    assert utils.should_delete_after_transcription(cfg, outside) is False


def test_should_not_delete_when_path_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "get_recordings_dir", lambda: str(tmp_path / "rec"))
    cfg = {"delete_recording_after_transcription": True}
    assert utils.should_delete_after_transcription(cfg, "") is False
    assert utils.should_delete_after_transcription(cfg, None) is False
