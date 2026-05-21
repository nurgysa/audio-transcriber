"""Speaker enrollment library — persist voice embeddings in config.json.

One entry per known speaker. The embedding is a float32 vector (dim depends
on the enrollment model — 256 for WeSpeaker, 512 for pyannote/embedding),
L2-normalized at enrollment time so downstream cosine similarity is a
simple dot product.

Storage format in config.json:

    "voices": [
        {
            "name": "Нургиса",
            "dim": 256,
            "embedding_b64": "<base64 of float32 bytes>",
            "created_at": "2026-04-15T21:30:00"
        },
        ...
    ]

This module is deliberately dependency-light (stdlib + numpy) so app.py
and the Voices dialog can use it without importing torch/pyannote. Actual
embedding extraction lives in enrollment_worker.py.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime

import numpy as np

_logger = logging.getLogger(__name__)


def encode_embedding(embedding: np.ndarray) -> str:
    """Serialize a float32 1-D vector as base64 for JSON storage.

    Base64 (not a JSON list of floats) keeps config.json small and parseable
    even for 256+ dim vectors without 20× overhead of text-encoded floats.
    """
    arr = np.asarray(embedding, dtype=np.float32).reshape(-1)
    return base64.b64encode(arr.tobytes()).decode("ascii")


def decode_embedding(encoded: str) -> np.ndarray:
    """Inverse of ``encode_embedding``. Returns a float32 1-D vector."""
    return np.frombuffer(base64.b64decode(encoded), dtype=np.float32).copy()


def l2_normalize(embedding: np.ndarray) -> np.ndarray:
    """Unit-norm an embedding so cosine similarity reduces to a dot product.

    Adds a tiny epsilon to avoid divide-by-zero on degenerate inputs (which
    should never happen for real speech, but defensive math costs nothing).
    """
    vec = np.asarray(embedding, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vec)) + 1e-10
    return (vec / norm).astype(np.float32)


def voices_from_config(config: dict) -> list[dict]:
    """Parse config['voices'] into [{name, embedding (np.ndarray), dim}, ...].

    Skips malformed entries silently (missing name or embedding_b64) —
    config.json is user-editable and we don't want to crash the whole app
    over a stray manual edit.
    """
    out: list[dict] = []
    for entry in config.get("voices", []) or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        enc = entry.get("embedding_b64")
        if not name or not enc:
            continue
        try:
            emb = decode_embedding(enc)
        except (ValueError, TypeError) as e:
            # Corrupted base64, wrong dtype, or truncated payload — skip the
            # entry but warn so the user knows their voice library has a
            # bad entry that needs re-enrollment.
            _logger.warning("Skipping voice %r: bad embedding (%s)", name, e)
            continue
        out.append({
            "name": str(name),
            "embedding": emb,
            "dim": int(entry.get("dim") or emb.shape[0]),
            "created_at": entry.get("created_at"),
        })
    return out


def save_voice_to_config(
    config: dict,
    name: str,
    embedding: np.ndarray,
) -> None:
    """Insert or replace a voice by name. Mutates config in place.

    Embedding is L2-normalized here so callers don't have to remember to
    normalize before saving. Cosine similarity downstream assumes unit norm.
    """
    vec = l2_normalize(embedding)
    voices: list = config.setdefault("voices", [])
    # Replace-by-name: remove any prior entry with the same name, then append.
    voices[:] = [v for v in voices if v.get("name") != name]
    voices.append({
        "name": name,
        "dim": int(vec.shape[0]),
        "embedding_b64": encode_embedding(vec),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })


def remove_voice_from_config(config: dict, name: str) -> bool:
    """Remove a voice by name. Returns True if something was removed."""
    voices: list = config.setdefault("voices", [])
    before = len(voices)
    voices[:] = [v for v in voices if v.get("name") != name]
    return len(voices) < before


def voice_names(config: dict) -> list[str]:
    """Just the names — handy for the GUI list without decoding embeddings."""
    return [
        str(v.get("name"))
        for v in (config.get("voices") or [])
        if isinstance(v, dict) and v.get("name")
    ]
