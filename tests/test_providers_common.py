"""Direct units for providers._common — shared transport machinery.

HTTP is patched at the ONE canonical target: ``providers._common.requests``.
The per-provider test files keep their behavioral assertions and act as
integration coverage on top of these units.
"""
from __future__ import annotations

import logging
import threading
from unittest.mock import MagicMock, patch

import pytest
import requests

from providers._common import (
    cancel_remote,
    check_cancel,
    guess_content_type,
    require_key,
)
from providers.base import ProviderError

# ── check_cancel ──────────────────────────────────────────────────────


def test_check_cancel_none_event_is_noop():
    check_cancel(None)  # must not raise


def test_check_cancel_unset_event_is_noop():
    check_cancel(threading.Event())


def test_check_cancel_set_event_raises_transcription_cancelled():
    from transcriber import TranscriptionCancelled

    ev = threading.Event()
    ev.set()
    with pytest.raises(TranscriptionCancelled):
        check_cancel(ev)


# ── guess_content_type ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("ext", "mime"),
    [
        (".mp3", "audio/mpeg"),
        (".wav", "audio/wav"),
        (".m4a", "audio/mp4"),
        (".flac", "audio/flac"),
        (".ogg", "audio/ogg"),
        (".webm", "audio/webm"),
        (".xyz", "application/octet-stream"),
    ],
)
def test_guess_content_type(ext, mime):
    assert guess_content_type(f"C:/audio/file{ext}") == mime


def test_guess_content_type_is_case_insensitive():
    assert guess_content_type("C:/audio/FILE.MP3") == "audio/mpeg"


# ── require_key ───────────────────────────────────────────────────────


def test_require_key_strips_and_returns():
    assert require_key("  abc  ", "AssemblyAI") == "abc"


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_require_key_empty_raises_with_provider_name(bad):
    with pytest.raises(ProviderError, match="API-ключ Gladia не задан"):
        require_key(bad, "Gladia")


# ── cancel_remote ─────────────────────────────────────────────────────


def test_cancel_remote_network_error_logged_not_raised(caplog):
    with patch(
        "providers._common.requests.delete",
        side_effect=requests.ConnectionError("boom"),
    ), caplog.at_level(logging.WARNING, logger="providers._common"):
        cancel_remote("https://api.example/jobs/42", {"h": "1"}, provider="X")
    assert any("cancel-DELETE failed" in r.message for r in caplog.records)
    assert any("jobs/42" in r.message for r in caplog.records)


def test_cancel_remote_success_no_log(caplog):
    with patch(
        "providers._common.requests.delete",
        return_value=MagicMock(ok=True, status_code=200),
    ):
        with caplog.at_level("WARNING", logger="providers._common"):
            cancel_remote("https://api.example/jobs/42", {}, provider="X")
    assert caplog.records == []
