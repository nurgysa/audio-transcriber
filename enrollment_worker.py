"""Isolated worker for extracting one speaker embedding from a voice sample.

Mirrors the architecture of diarize_worker.py — a fresh subprocess so that
pyannote/torch CUDA state never collides with ctranslate2's. Runs on GPU if
available, CPU otherwise (embedding extraction is cheap, ~hundreds of ms
for a 10-second clip on CPU).

Usage:
    python enrollment_worker.py <audio_path>

Env:
    HF_TOKEN — Hugging Face token for pyannote/embedding model weights.

Exit codes:
    0 — success; stdout contains one JSON object:
        {"dim": <int>, "embedding_b64": "<base64 float32>"}
    non-zero — failure; stderr contains the traceback.

All human-readable output (warnings, errors) goes to stderr. stdout is
reserved for the single JSON line that the parent process parses.
"""

import base64
import inspect
import json
import os
import sys
from contextlib import contextmanager

# Force UTF-8 for stdout so non-ASCII names in potential error lines don't
# mojibake on Windows' default cp1251 pipe encoding.
sys.stdout.reconfigure(encoding="utf-8")

import soundfile as sf  # noqa: E402
import torch  # noqa: E402
import numpy as np  # noqa: E402

# cuDNN on GTX 1650 Ti crashes pyannote with HOST_ALLOCATION_FAILED —
# same issue as the diarization worker. Native CUDA kernels complete
# cleanly. See memory/diarization_gpu_tricks.md.
torch.backends.cudnn.enabled = False


@contextmanager
def _suppress_inspect_stack():
    """
    Work around speechbrain 1.1 + lightning LazyModule crash (same as in
    diarize_worker — lightning's _restricted_classmethod wrapper walks
    sys.modules via inspect.stack on every classmethod call, triggering
    LazyModule resolution for speechbrain modules with missing deps).
    """
    original = inspect.stack
    inspect.stack = lambda *a, **kw: []
    try:
        yield
    finally:
        inspect.stack = original


def _load_audio(audio_path: str) -> tuple[torch.Tensor, int]:
    """
    Chunked pre-allocated load — same strategy as diarize_worker._load_audio.

    For enrollment the clips are small (typically 10-30 s), so the Windows
    fragmented-heap concern is weaker here than for hour-long diarization
    inputs. Sharing the pattern keeps the two workers' audio pipelines
    consistent — if a regression hits one, we fix it the same way in the
    other.
    """
    with sf.SoundFile(audio_path) as f:
        total_frames = len(f)
        sample_rate = f.samplerate
        channels = f.channels
        waveform = torch.empty((1, total_frames), dtype=torch.float32)
        chunk_frames = 65_536
        pos = 0
        while pos < total_frames:
            n = min(chunk_frames, total_frames - pos)
            block = f.read(frames=n, dtype="float32", always_2d=False)
            if channels > 1 and block.ndim > 1:
                block = block.mean(axis=1)
            waveform[0, pos:pos + len(block)] = torch.from_numpy(block)
            pos += len(block)
    return waveform, sample_rate


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: enrollment_worker.py <audio_path>", file=sys.stderr)
        return 2

    audio_path = sys.argv[1]
    if not os.path.isfile(audio_path):
        print(f"audio file not found: {audio_path}", file=sys.stderr)
        return 2

    hf_token = os.environ.get("HF_TOKEN") or None

    # Lazy imports — only paid inside the subprocess, not at module import.
    from pyannote.audio import Inference, Model

    with _suppress_inspect_stack():
        # pyannote/embedding: classic ECAPA-TDNN-style x-vectors, 512-dim.
        # Widely available, non-gated in typical HF accounts that already
        # accepted pyannote/speaker-diarization-3.1 conditions. Matching
        # uses the same model inside diarize_worker so dims stay consistent.
        model = Model.from_pretrained("pyannote/embedding", token=hf_token)
        # window="whole" yields a single embedding from the entire clip.
        inference = Inference(model, window="whole")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    inference.to(device)
    print(f"enrollment on {device}", file=sys.stderr, flush=True)

    waveform, sample_rate = _load_audio(audio_path)
    # pyannote expects dict form (same as diarize_worker) because torchcodec
    # is broken on this Windows setup — see pyannote.audio.core.io warning.
    emb = inference({"waveform": waveform, "sample_rate": sample_rate})

    if isinstance(emb, torch.Tensor):
        emb = emb.detach().cpu().numpy()
    emb = np.asarray(emb, dtype=np.float32).reshape(-1)

    # L2-normalize so downstream cosine similarity is a plain dot product.
    norm = float(np.linalg.norm(emb)) + 1e-10
    emb = (emb / norm).astype(np.float32)

    out = {
        "dim": int(emb.shape[0]),
        "embedding_b64": base64.b64encode(emb.tobytes()).decode("ascii"),
    }
    sys.stdout.write(json.dumps(out))
    sys.stdout.flush()
    sys.stderr.flush()
    # Fast-exit to skip ~8 s of torch/pyannote CUDA teardown at interpreter
    # shutdown. Same pattern as diarize_worker.py.
    os._exit(0)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
