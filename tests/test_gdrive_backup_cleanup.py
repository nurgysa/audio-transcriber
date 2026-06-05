"""WS-5: gdrive.backup.run_backup must clean its staging dir on FAILURE too.

The staging work_dir holds history.zip (ALL meeting transcripts) + the config +
manifest. The original code only removed it on success, so a failed backup left
transcripts/PII accumulating in %TEMP% across retries (audit P2). The fix moves
cleanup into a finally so it always runs.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from gdrive.backup import run_backup


def _history(tmp_path):
    h = tmp_path / "history"
    h.mkdir()
    (h / "meeting").mkdir()
    (h / "meeting" / "transcript.txt").write_text("привет", encoding="utf-8")
    return h


def test_run_backup_cleans_work_dir_on_failure(tmp_path):
    """A failure mid-upload must NOT leave the staging dir behind."""
    work_dir = tmp_path / "work"
    fake_auth = MagicMock()
    fake_client = MagicMock()
    fake_client.find_or_create_folder.return_value = "root"
    fake_client.create_folder.return_value = "snap"
    fake_client.upload_file.side_effect = RuntimeError("network down")

    with patch("gdrive.backup.DriveClient", return_value=fake_client), \
         patch("gdrive.backup._iso_timestamp", return_value="2026-06-04T00-00-00"):
        with pytest.raises(RuntimeError, match="network down"):
            run_backup(
                auth=fake_auth,
                config={"language": "ru", "openrouter_api_key": "secret"},
                history_dir=_history(tmp_path),
                work_dir=work_dir,
            )

    assert not work_dir.exists(), "staging dir must be cleaned even on failure"


def test_run_backup_cleans_work_dir_on_success(tmp_path):
    """Regression: the success path still cleans the staging dir."""
    work_dir = tmp_path / "work"
    fake_auth = MagicMock()
    fake_client = MagicMock()
    fake_client.find_or_create_folder.return_value = "root"
    fake_client.create_folder.return_value = "snap"
    fake_client.upload_file.side_effect = ["m-id", "c-id", "z-id"]

    with patch("gdrive.backup.DriveClient", return_value=fake_client), \
         patch("gdrive.backup._iso_timestamp", return_value="2026-06-04T00-00-00"):
        result = run_backup(
            auth=fake_auth,
            config={"language": "ru"},
            history_dir=_history(tmp_path),
            work_dir=work_dir,
        )

    assert result["snapshot_name"] == "2026-06-04T00-00-00"
    assert not work_dir.exists(), "staging dir must be cleaned on success"
