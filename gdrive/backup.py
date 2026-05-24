"""Backup orchestrator for Phase 7.1.

Composes `gdrive.client.DriveClient` (Drive I/O) with stdlib zipfile
+ hashlib + json (snapshot building) into a single `run_backup`
entry point that the Settings dialog's worker thread calls when the
user clicks "Сделать backup сейчас".

Four pure helpers:
  * redact_config(cfg)        — strip API keys from a config dict
  * zip_history(src_dir, out) — write history/ to a zip, excluding audio
  * build_manifest(...)       — produce the manifest dict
  * _iso_timestamp()          — folder-name-safe ISO 8601 UTC

Plus the orchestrator:
  * run_backup(auth, config, history_dir, on_status=None) → dict

Pure helpers are unit-testable without DriveClient or network. The
orchestrator is mock-tested with a fake DriveClient.

See spec docs/superpowers/specs/2026-04-30-gdrive-backup-design.md
sections "Backup payload structure (Phase 7.1)" and "API key
redaction in config.json".
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


MANIFEST_VERSION = 1


# String written in place of every redacted secret. Matches the spec's
# "<REDACTED>" literal so the user (or a future restore) can detect
# fields that need re-entry.
REDACTION_PLACEHOLDER = "<REDACTED>"

# Top-level config keys whose values are stripped before upload. Per
# spec line 117-121 plus cloud_api_keys (nested dict — values get
# replaced one by one, structure preserved) and hf_token (HuggingFace
# token used for pyannote diarization download — also a secret).
REDACTED_KEYS = (
    "openrouter_api_key",
    "linear_api_key",
    "glide_api_key",
    "assemblyai_api_key",
    "hf_token",
)


def redact_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy of ``config`` with all known API keys
    replaced by REDACTION_PLACEHOLDER. Input is never mutated.

    Two redaction shapes:
      * Top-level string values (REDACTED_KEYS list)
      * cloud_api_keys nested dict — keys (provider names) preserved,
        values (the actual API keys) replaced

    Keys absent from the input are silently skipped — no spurious
    new placeholder entries appear in the output.
    """
    out = copy.deepcopy(config)
    for key in REDACTED_KEYS:
        if key in out:
            out[key] = REDACTION_PLACEHOLDER
    cloud_keys = out.get("cloud_api_keys")
    if isinstance(cloud_keys, dict):
        out["cloud_api_keys"] = {k: REDACTION_PLACEHOLDER for k in cloud_keys}
    return out


# Audio file extensions excluded from the history.zip — text-only
# backup is the spec's default; audio opt-in is a Phase 7.4 follow-up.
AUDIO_EXTS = (".wav", ".mp3", ".m4a")


def zip_history(src_dir, out_zip) -> None:
    """Zip the contents of ``src_dir`` into ``out_zip``, with two rules:

      * Audio files (AUDIO_EXTS) are SKIPPED — they're typically 50-100
        MB per meeting and the Free Drive tier is 15 GB. Text-only is
        the spec's chosen scope.
      * Relative paths inside the zip are rooted at ``src_dir`` (so a
        file at ``history/2026-05-23_meeting/transcript.txt`` lands in
        the zip as ``2026-05-23_meeting/transcript.txt``).

    Empty source directory produces a valid empty zip (not an error).
    Existing out_zip is overwritten.

    src_dir and out_zip accept str or pathlib.Path.
    """
    # Import zipfile/pathlib lazily — both are stdlib and cheap, but
    # keeping the module-top imports minimal helps grep-ability.
    import zipfile
    from pathlib import Path

    src = Path(src_dir)
    out = Path(out_zip)

    # ZIP_DEFLATED gives ~70% compression on transcript JSON/TXT; small
    # enough payloads that compresslevel default (6) is the right pick
    # — going to 9 saves <1% and costs noticeable CPU.
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src.rglob("*")):
            if path.is_dir():
                continue
            if path.suffix.lower() in AUDIO_EXTS:
                continue
            arcname = path.relative_to(src).as_posix()
            zf.write(path, arcname=arcname)


def _iso_timestamp() -> str:
    """Current UTC time formatted as the spec's folder-name (line 86):
    ``2026-04-30T12-30-00``. The two ``:`` separators inside the time
    portion are replaced with ``-`` for Windows-filename safety (the
    folder is created in Drive but the same string appears in local
    paths during Phase 7.2 restore extraction).
    """
    now = datetime.now(timezone.utc)
    # isoformat() with timespec='seconds' → '2026-04-30T12:30:00+00:00'
    # We want '2026-04-30T12-30-00' — strip tz, replace colons.
    raw = now.strftime("%Y-%m-%dT%H:%M:%S")
    return raw.replace(":", "-")


def build_manifest(
    *,
    files: dict[str, Any],
    transcripts_count: int,
    app_version: str,
    host: str,
    created_at: str,
    audio_included: bool = False,
) -> dict[str, Any]:
    """Build the manifest dict that ships alongside the payload files.

    Schema per spec line 94-108. SHA-256 + byte-size are computed
    per file by streaming (chunked reads — works for arbitrarily
    large payloads, though Phase 7.1's are tiny).

    audio_included defaults to False (text-only is Phase 7.1's scope);
    Phase 7.4's audio opt-in passes True.
    """
    import hashlib
    from pathlib import Path

    files_meta = {}
    for arcname, local in files.items():
        path = Path(local)
        sha = hashlib.sha256()
        size = 0
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(64 * 1024), b""):
                sha.update(chunk)
                size += len(chunk)
        files_meta[arcname] = {"size": size, "sha256": sha.hexdigest()}

    return {
        "version": MANIFEST_VERSION,
        "created_at": created_at,
        "app_version": app_version,
        "host": host,
        "files": files_meta,
        "transcripts_count": transcripts_count,
        "audio_included": audio_included,
    }
