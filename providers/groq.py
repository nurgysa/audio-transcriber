"""Groq Whisper API transcription provider.

Groq hosts Whisper Large v3 on their LPU inference stack, exposing an
OpenAI-compatible HTTP surface. Same multipart upload, same
``verbose_json`` response shape — the only meaningful differences from
:mod:`providers.openai_whisper` are the base URL, the model id, and the
fact that we explicitly request both segment- AND word-level timestamp
granularities so that the hybrid PR-B path can hand the words[] off to
the local pyannote aligner.

API workflow (single synchronous call):

    POST /openai/v1/audio/transcriptions   multipart {file, model, language,
                                                       timestamp_granularities[]}
        → verbose JSON with segment-level fields PLUS a top-level words[]
          array (when granularities[]=word is requested).

Groq's hosted Whisper has no built-in diarization. The provider
declares ``supports_diarization = False``; the cloud-only path leaves
speaker labels empty, while the upcoming hybrid path (PR-B) runs
local pyannote on the same audio and merges the two outputs via
:mod:`transcriber.speaker_aligner`.

Pricing (May 2026 — verified at https://console.groq.com/docs/speech-to-text):
  whisper-large-v3:        $0.111/h
  whisper-large-v3-turbo:  $0.04/h   (cost-optimized; identical model
                                       family, smaller compute footprint)

File limits (per Groq docs):
  Free tier:  25 MB hard upload cap
  Dev tier:   100 MB hard upload cap
We pre-check at 25 MB to give the broadest base of users an actionable
Russian error instead of letting Groq's gateway return a generic 413.

Languages: 99+, including ``ru``, ``kk``, and ``en`` — the trilingual
mix the codebase's "mixed" sentinel exists to serve. When
``options.language == "mixed"`` we omit the ``language`` form field so
whisper-large-v3's native per-segment language detection kicks in.
"""

from __future__ import annotations

import os

import requests

from .base import (
    ProviderError,
    TranscriptionOptions,
    TranscriptionProvider,
    TranscriptionResult,
)

_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_DEFAULT_MODEL = "whisper-large-v3"
# Free-tier hard cap. Dev tier raises this to 100 MB; we keep the lower
# bound here because the user-actionable error message is more valuable
# than serving the rarer dev-tier case (which can still send <25 MB chunks).
_MAX_FILE_BYTES = 25 * 1024 * 1024


class GroqProvider(TranscriptionProvider):
    """Cloud transcription via api.groq.com (whisper-large-v3 family)."""

    display_name = "Groq"
    supports_diarization = False
    # whisper-large-v3 is natively multilingual — when no language is forced
    # the model detects per segment, which is exactly what the "mixed" sentinel
    # means at our UI layer. No code_switching flag is required by Groq;
    # omitting the form field is the documented path.
    supports_mixed = True

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL):
        if not api_key or not api_key.strip():
            raise ProviderError(
                "API-ключ Groq не задан. Открой Настройки → Облако и "
                "вставь ключ."
            )
        self._api_key = api_key.strip()
        self._model = model
        self._headers = {"Authorization": f"Bearer {self._api_key}"}

    # --------------------------- public API ----------------------------

    def transcribe(
        self,
        audio_path: str,
        options: TranscriptionOptions,
        on_status=None,
        on_progress=None,
        cancel_event=None,
    ) -> TranscriptionResult:
        if not os.path.isfile(audio_path):
            raise ProviderError(f"Файл не найден: {audio_path}")

        size = os.path.getsize(audio_path)
        if size > _MAX_FILE_BYTES:
            mb = size / (1024 * 1024)
            raise ProviderError(
                f"Файл {mb:.1f} МБ — Groq принимает не более 25 МБ на "
                f"free-tier. Подними тариф до dev (100 МБ), порежь файл "
                f"или используй локальный пайплайн."
            )

        self._check_cancel(cancel_event)
        if on_status:
            on_status("Загрузка аудио в Groq...")
        if on_progress:
            on_progress(5.0)

        # Build the multipart form. We always request both segment AND word
        # granularities — segment-level for the cloud-only path's text
        # formatting, word-level for the hybrid PR-B path's speaker-aligner
        # (which needs word midpoints to assign each word to a pyannote turn).
        # Requesting both is cheap on Groq's side: the response gets a
        # top-level words[] array alongside segments[] — no extra round-trip,
        # no extra billing.
        data: list[tuple[str, str]] = [
            ("model", self._model),
            ("response_format", "verbose_json"),
            ("timestamp_granularities[]", "segment"),
            ("timestamp_granularities[]", "word"),
        ]
        # "mixed" sentinel → omit the language field so whisper-large-v3
        # auto-detects per segment. Forcing a single ISO code here would
        # collapse trilingual KZ+RU+EN audio onto one language and break
        # Kazakh segments.
        if options.language and options.language != "mixed":
            data.append(("language", options.language))
        if options.hotwords:
            # Whisper accepts a free-form ``prompt`` string. Joining
            # hotwords as a comma-separated list biases decoding toward
            # those spellings — same trick as the local initial_prompt.
            data.append(("prompt", ", ".join(options.hotwords)))

        with open(audio_path, "rb") as f:
            files = {
                "file": (
                    os.path.basename(audio_path), f,
                    _guess_content_type(audio_path),
                ),
            }
            try:
                r = requests.post(
                    _API_URL,
                    headers=self._headers,
                    data=data,
                    files=files,
                    timeout=60 * 30,
                )
            except requests.RequestException as e:
                raise ProviderError(
                    f"Сеть не отвечает при загрузке аудио: {e}"
                ) from e

        if r.status_code == 401:
            raise ProviderError(
                "Groq отклонил ключ (401). Проверь API-ключ в "
                "Настройках → Облако."
            )
        if r.status_code == 429:
            raise ProviderError(
                "Groq вернул 429 (rate limit / квота исчерпана). "
                "Подожди минуту или проверь биллинг."
            )
        if not r.ok:
            raise ProviderError(
                f"Groq вернул ошибку ({r.status_code}): "
                f"{r.text[:300]}"
            )

        try:
            payload = r.json()
        except ValueError as e:
            raise ProviderError(
                f"Неожиданный ответ Groq: {r.text[:300]}"
            ) from e

        if on_status:
            on_status("Готово.")
        if on_progress:
            on_progress(100.0)

        segments = _to_segments(payload)
        return TranscriptionResult(
            segments=segments,
            language=payload.get("language"),
            raw=payload,
        )

    @staticmethod
    def _check_cancel(cancel_event) -> None:
        if cancel_event is not None and cancel_event.is_set():
            from transcriber import TranscriptionCancelled
            raise TranscriptionCancelled()


# ---------------------------- helpers ---------------------------------


def _guess_content_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {
        ".mp3":  "audio/mpeg",
        ".wav":  "audio/wav",
        ".m4a":  "audio/mp4",
        ".flac": "audio/flac",
        ".ogg":  "audio/ogg",
        ".webm": "audio/webm",
    }.get(ext, "application/octet-stream")


def _to_segments(payload: dict) -> list[dict]:
    """Convert verbose_json response → internal segment shape.

    Handles three shapes Groq may return depending on what
    ``timestamp_granularities[]`` was requested:

    1. ``segments[]`` only — plain segment-level output, returned as-is.
    2. ``segments[]`` with words[] embedded inside each segment — used
       as-is too (we trust the API's grouping).
    3. ``segments[]`` PLUS a top-level ``words[]`` — the canonical shape
       when both granularities are requested. We distribute each word
       to its owning segment by midpoint time-overlap, then expose them
       on ``segment["words"]`` for downstream consumption by
       :mod:`transcriber.speaker_aligner`.

    Falls back to a single segment carrying the flat ``text`` field if
    the response is in ``json`` mode by accident. Returns ``[]`` for
    truly empty payloads.
    """
    segs = payload.get("segments")
    if isinstance(segs, list) and segs:
        out: list[dict] = []
        # Pass 1: copy segment-level fields. If a segment already carries
        # its own ``words`` array, keep it normalized; otherwise leave it
        # absent so Pass 2 (top-level distribution) can populate it.
        any_segment_has_words = False
        for s in segs:
            row: dict = {
                "start": float(s.get("start", 0.0)),
                "end": float(s.get("end", 0.0)),
                "text": (s.get("text") or "").strip(),
            }
            embedded = s.get("words")
            if isinstance(embedded, list) and embedded:
                any_segment_has_words = True
                row["words"] = [
                    {
                        "start": float(w.get("start", 0.0)),
                        "end": float(w.get("end", 0.0)),
                        "word": w.get("word") or "",
                    }
                    for w in embedded
                ]
            out.append(row)

        # Pass 2: if no segment carried embedded words but the payload has a
        # top-level words[], distribute them by midpoint. Skip distribution
        # entirely if the segments already had their own words — mixing the
        # two sources would double-count.
        if not any_segment_has_words:
            top_words = payload.get("words")
            if isinstance(top_words, list) and top_words:
                # Initialize empty buckets only when we have words to fill.
                for row in out:
                    row["words"] = []
                # Each word lands in the FIRST segment whose end-time is at
                # or past the word's midpoint. Words past the last segment
                # are dropped — Groq has been observed to emit phantom words
                # past the audio end; better silent skip than crash.
                for w in top_words:
                    try:
                        w_start = float(w["start"])
                        w_end = float(w["end"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    w_text = w.get("word") or ""
                    mid = (w_start + w_end) / 2.0
                    placed = False
                    for row in out:
                        if mid <= row["end"]:
                            row["words"].append({
                                "start": w_start,
                                "end": w_end,
                                "word": w_text,
                            })
                            placed = True
                            break
                    # Silently drop unplaced words (see comment above).
                    _ = placed
                # Strip empty words[] keys so downstream callers can use the
                # idiomatic ``if seg.get("words")`` check without false
                # positives from empty lists.
                for row in out:
                    if not row["words"]:
                        del row["words"]

        return out

    text = (payload.get("text") or "").strip()
    return [{"start": 0.0, "end": 0.0, "text": text}] if text else []
