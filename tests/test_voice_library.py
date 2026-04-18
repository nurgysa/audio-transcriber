"""Tests for the speaker enrollment library (pure stdlib + numpy)."""
import numpy as np
import pytest

from voice_library import (
    decode_embedding, encode_embedding, l2_normalize,
    remove_voice_from_config, save_voice_to_config,
    voice_names, voices_from_config,
)


def test_encode_decode_round_trip():
    original = np.array([0.1, -0.2, 0.3, 0.4], dtype=np.float32)
    encoded = encode_embedding(original)
    assert isinstance(encoded, str)
    decoded = decode_embedding(encoded)
    np.testing.assert_array_equal(decoded, original)


def test_l2_normalize_produces_unit_vector():
    raw = np.array([3.0, 4.0], dtype=np.float32)  # 3-4-5 triangle → norm 5
    out = l2_normalize(raw)
    assert pytest.approx(np.linalg.norm(out), rel=1e-6) == 1.0
    np.testing.assert_allclose(out, [0.6, 0.8], rtol=1e-6)


def test_l2_normalize_handles_zero_vector():
    # Real speech embeddings are never all-zero, but the helper must not
    # divide by zero — the +1e-10 guard keeps it returning a finite vector.
    out = l2_normalize(np.zeros(4, dtype=np.float32))
    assert np.all(np.isfinite(out))


def test_save_then_remove_round_trip():
    config: dict = {}
    emb = np.array([1.0, 2.0, 2.0], dtype=np.float32)
    save_voice_to_config(config, "Анна", emb)
    assert voice_names(config) == ["Анна"]

    voices = voices_from_config(config)
    assert len(voices) == 1
    assert voices[0]["name"] == "Анна"
    # save_voice_to_config L2-normalizes before storing — round-trip should
    # match the normalized form, not the raw embedding.
    expected = emb / np.linalg.norm(emb)
    np.testing.assert_allclose(voices[0]["embedding"], expected, rtol=1e-6)

    assert remove_voice_from_config(config, "Анна") is True
    assert voice_names(config) == []
    assert remove_voice_from_config(config, "Анна") is False  # idempotent


def test_save_replaces_voice_with_same_name():
    config: dict = {}
    save_voice_to_config(config, "Иван", np.array([1.0, 0.0], dtype=np.float32))
    save_voice_to_config(config, "Иван", np.array([0.0, 1.0], dtype=np.float32))
    voices = voices_from_config(config)
    assert len(voices) == 1
    np.testing.assert_allclose(voices[0]["embedding"], [0.0, 1.0], rtol=1e-6)


def test_voices_from_config_skips_malformed_entries():
    config = {"voices": [
        {"name": "Good", "embedding_b64": encode_embedding(np.ones(4, dtype=np.float32))},
        {"name": "NoEmbedding"},                # missing embedding_b64 → skip
        {"embedding_b64": "abc"},               # missing name → skip
        {"name": "BadB64", "embedding_b64": "!!!not-base64!!!"},  # decode fail → skip
        "not even a dict",                      # wrong type → skip
    ]}
    out = voices_from_config(config)
    assert [v["name"] for v in out] == ["Good"]
