"""Cloud transcription provider registry.

A simple name→class map. The Settings dialog renders these as the choice
list; ``transcriber.py`` looks up the active provider by name. Adding a
new provider = one import + one entry here.
"""

from __future__ import annotations

from .assemblyai import AssemblyAIProvider
from .base import (
    ProviderError,
    TranscriptionOptions,
    TranscriptionProvider,
    TranscriptionResult,
)

# Display name shown in the dropdown → provider class.
# Order is preserved by Python 3.7+ dict semantics; first entry is the
# default selection on a fresh install.
PROVIDERS: dict[str, type[TranscriptionProvider]] = {
    "AssemblyAI": AssemblyAIProvider,
}


def get_provider(name: str, api_key: str) -> TranscriptionProvider:
    """Build a provider instance by display name. Raises ProviderError."""
    cls = PROVIDERS.get(name)
    if cls is None:
        raise ProviderError(
            f"Неизвестный провайдер: {name!r}. Доступны: "
            f"{', '.join(PROVIDERS.keys())}"
        )
    return cls(api_key)


__all__ = [
    "PROVIDERS",
    "ProviderError",
    "TranscriptionOptions",
    "TranscriptionProvider",
    "TranscriptionResult",
    "get_provider",
]
