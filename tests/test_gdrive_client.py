"""Tests for gdrive.client.DriveClient — Phase 7.1.

Pure module — no real Drive API, no network. Mocks
`googleapiclient.discovery.build` at its source module so the
lazily-imported symbol inside DriveClient methods resolves to a
MagicMock that returns canned Drive API responses.

Codex P1 lesson from PR #39 applies: patch the SOURCE
(`googleapiclient.discovery.build`) NOT `gdrive.client.build` —
lazy imports don't bind names as module attributes.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from gdrive.client import DriveClient


def test_constructor_takes_credentials_and_stores_them():
    """DriveClient(creds) stores the credentials object without touching
    the network. The actual `build()` call happens lazily on first API
    method call so construction stays cheap (~µs)."""
    fake_creds = MagicMock()
    client = DriveClient(fake_creds)
    assert client._credentials is fake_creds
    assert client._service is None, "Service should be lazy"
