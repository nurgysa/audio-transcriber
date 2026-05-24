"""Tests for gdrive.backup — Phase 7.1 backup orchestrator.

Mostly pure stdlib testing (zipfile, tmp_path, dict redaction). The
run_backup orchestrator test mocks DriveClient — no real Drive API.
"""
from __future__ import annotations

import copy
import hashlib
import json
import zipfile
from unittest.mock import MagicMock, patch

from gdrive.backup import REDACTED_KEYS, REDACTION_PLACEHOLDER, redact_config

# build_manifest and zip_history get imported INSIDE their tests below —
# during the B.2/B.3 TDD slices they don't exist yet, so a top-level
# import would break test collection for the B.1 (redact) tests.


def test_redact_config_replaces_listed_keys_with_placeholder():
    """All keys listed in REDACTED_KEYS must be replaced with
    REDACTION_PLACEHOLDER. Keys absent from the input config are
    silently skipped (not added as new keys)."""
    config = {
        "language": "Авто-определение",
        "openrouter_api_key": "sk-or-real-key-12345",
        "linear_api_key": "lin_api_real",
        "glide_api_key": "real-glide-key",
        "assemblyai_api_key": "asm-real",
        "hf_token": "hf_real_token",
        "cloud_api_keys": {"AssemblyAI": "real", "Deepgram": "real2"},
        "gdrive_account_email": "user@example.com",  # not redacted — it's user-visible
    }
    redacted = redact_config(config)

    # Listed keys replaced.
    assert redacted["openrouter_api_key"] == REDACTION_PLACEHOLDER
    assert redacted["linear_api_key"] == REDACTION_PLACEHOLDER
    assert redacted["glide_api_key"] == REDACTION_PLACEHOLDER
    assert redacted["assemblyai_api_key"] == REDACTION_PLACEHOLDER
    assert redacted["hf_token"] == REDACTION_PLACEHOLDER
    # cloud_api_keys (nested dict of provider→key) — values redacted, keys kept.
    assert redacted["cloud_api_keys"] == {
        "AssemblyAI": REDACTION_PLACEHOLDER,
        "Deepgram": REDACTION_PLACEHOLDER,
    }
    # Non-secret keys untouched.
    assert redacted["language"] == "Авто-определение"
    assert redacted["gdrive_account_email"] == "user@example.com"
    # Input not mutated (defensive — caller might still need it).
    assert config["openrouter_api_key"] == "sk-or-real-key-12345"


def test_redact_config_handles_missing_keys_silently():
    """A config that doesn't have any of the redacted keys returns
    intact (no KeyError, no spurious new keys)."""
    config = {"language": "Русский", "model": "large-v3"}
    redacted = redact_config(config)
    assert redacted == config
    assert redacted is not config, "redact_config must return a copy"
