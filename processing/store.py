"""Persistence for the processing queue.

queue.json (active items only) lives at ~/.audio-transcriber/queue.json, beside
config.json and directory.json. Atomic write (tmp + os.replace), mirroring
directory/store.py. No Tk, no heavy deps; safe to import headlessly. (The
disk-derived display view, build_view, is added in a later task.)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from processing.model import QueueItem

FILENAME = "queue.json"


def _default_queue_path() -> Path:
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or ".")
    return home / ".audio-transcriber" / FILENAME


def load_active(path: Path | str | None = None) -> list[QueueItem]:
    p = Path(path) if path is not None else _default_queue_path()
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [QueueItem.from_dict(d) for d in data.get("items", [])]


def save_active(items: list[QueueItem], path: Path | str | None = None) -> None:
    p = Path(path) if path is not None else _default_queue_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"items": [it.to_dict() for it in items]}
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp = p.parent / f".{p.name}.tmp"
    tmp.write_text(encoded, encoding="utf-8")
    os.replace(tmp, p)
