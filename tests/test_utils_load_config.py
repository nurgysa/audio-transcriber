"""utils.load_config regression tests.

Focus: BOM tolerance. Real Windows tooling (Notepad save-as, PS 5.1
`Set-Content -Encoding UTF8`, some ZIP-extract pipelines) prepends UTF-8
BOM bytes (EF BB BF) to text files. The default `encoding="utf-8"` reader
then raises `json.JSONDecodeError: Unexpected UTF-8 BOM` and the app
fails to start. utf-8-sig silently strips the BOM.

Discovered live on 2026-05-28 when a PowerShell merge helper script
re-seeded config.json with BOM and the freshly-built bundle crashed at
startup with the exact error this test now guards against.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch


def _write_config(path: Path, payload: dict, with_bom: bool) -> None:
    """Helper: write a config.json with or without leading UTF-8 BOM."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if with_bom:
        body = b"\xef\xbb\xbf" + body
    path.write_bytes(body)


def test_load_config_accepts_bom_prefixed_file(tmp_path: Path) -> None:
    """A BOM'd config.json must load without raising; payload must be intact."""
    config_path = tmp_path / "config.json"
    payload = {"language": "Смешанный (KZ+RU+EN)", "cloud_enabled": True}
    _write_config(config_path, payload, with_bom=True)

    # Sanity: verify the file actually has the BOM (otherwise the test
    # doesn't prove anything — it would pass even on the pre-fix utf-8 reader).
    assert config_path.read_bytes()[:3] == b"\xef\xbb\xbf"

    with patch("utils._CONFIG_PATH", str(config_path)):
        from utils import load_config
        result = load_config()

    assert result == payload
    assert result["language"] == "Смешанный (KZ+RU+EN)"


def test_load_config_still_accepts_plain_utf8_file(tmp_path: Path) -> None:
    """Regression guard: plain utf-8 (no BOM) keeps working — utf-8-sig
    handles both. The previous reader only handled plain — defensive fix
    must not break the common case."""
    config_path = tmp_path / "config.json"
    payload = {"language": "Русский", "cloud_provider": "AssemblyAI"}
    _write_config(config_path, payload, with_bom=False)

    assert config_path.read_bytes()[:3] != b"\xef\xbb\xbf"

    with patch("utils._CONFIG_PATH", str(config_path)):
        from utils import load_config
        result = load_config()

    assert result == payload


def test_load_config_missing_file_returns_empty_dict(tmp_path: Path) -> None:
    """First-run / wiped install path: no config.json yet — return {} not raise.
    Regression guard for the existing contract — utf-8-sig fix must not
    accidentally change the missing-file behaviour."""
    missing_path = tmp_path / "nope.json"
    assert not missing_path.exists()

    with patch("utils._CONFIG_PATH", str(missing_path)):
        from utils import load_config
        result = load_config()

    assert result == {}
