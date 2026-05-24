"""Drive API v3 wrapper for Phase 7.1+ — upload-only surface.

This module is intentionally tiny. It hides the
`googleapiclient.discovery.build` ceremony behind three methods that
Phase 7.1's backup orchestrator (and Phase 7.2's restore) call. Future
phases (scheduler retention cleanup, sync) will extend with `list`,
`delete`, and `download`.

The Drive API client is built lazily on first method call so that
constructing a DriveClient (e.g. at app startup) doesn't pay the
~30-50 MB import + HTTP-discovery cost — only signing-in-and-clicking-
backup does.

Codex P1 lesson from Phase 7.0 PR #39: `googleapiclient.discovery.build`
is imported INSIDE methods, NOT at module top. Tests must patch the
source (`googleapiclient.discovery.build`) — patching
`gdrive.client.build` would AttributeError because the lazy import
never binds `build` as a `gdrive.client` attribute.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# MIME types used by the backup payload. Drive folders have a magic
# MIME; arbitrary application data uses application/octet-stream
# unless we know better (JSON / ZIP get accurate types so Drive's web
# UI can preview them).
FOLDER_MIME = "application/vnd.google-apps.folder"
JSON_MIME = "application/json"
ZIP_MIME = "application/zip"


class DriveClient:
    """Synchronous wrapper over Drive API v3. One instance per backup
    operation (cheap; just holds credentials + lazy-built service)."""

    def __init__(self, credentials) -> None:
        self._credentials = credentials
        self._service = None
