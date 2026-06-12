"""Best-effort signed webhook client for Hermes Agent integration.

Design invariants (spec §2, §9.2):
- The secret NEVER appears in logs, error messages, or result objects.
- Webhook delivery is best-effort: failures never raise to the caller.
- The body bytes are built ONCE and the SAME bytes are used for both the
  HMAC signature and the POST body (spec §3 compatibility requirement).
- ``requests.RequestException`` is the narrow catch class (house idiom;
  see providers/_common.py for the pattern).

Import contract: ``import requests`` at module top — requests is a pinned dep.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass

import requests

from integrations.hermes.schema import build_audio_transcribed_event

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HermesWebhookConfig:
    """Immutable configuration for the Hermes outbound webhook."""

    enabled: bool = False
    url: str = "http://localhost:8644/webhooks/audio-transcribed"
    secret: str = ""
    timeout_seconds: float = 10.0
    routing_hint: str = "obsidian_inbox"


@dataclass(frozen=True)
class HermesWebhookResult:
    """Outcome of a single webhook delivery attempt."""

    enabled: bool
    sent: bool
    status_code: int | None = None
    error: str | None = None


# ── Serialization + signing ──────────────────────────────────────────


def serialize_payload(payload: dict) -> bytes:
    """Return deterministic UTF-8 JSON bytes for POST body and HMAC.

    Keys are sorted, separators are compact, Unicode is preserved as-is.
    Build once; pass the SAME bytes to both sign_body() and requests.post().
    """
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sign_body(secret: str, body: bytes) -> str:
    """Return hex HMAC-SHA256 signature over the exact body bytes."""
    return hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()


# ── HTTP delivery ────────────────────────────────────────────────────


def post_event(payload: dict, config: HermesWebhookConfig) -> HermesWebhookResult:
    """POST payload to the configured Hermes webhook URL.

    Returns a HermesWebhookResult regardless of outcome — never raises.
    The secret is used only for signing and is never included in any
    returned or logged string.
    """
    if not config.enabled:
        return HermesWebhookResult(enabled=False, sent=False)

    if not config.url:
        return HermesWebhookResult(
            enabled=True,
            sent=False,
            error="Hermes webhook URL is not configured",
        )

    if not config.secret:
        return HermesWebhookResult(
            enabled=True,
            sent=False,
            error="Hermes webhook secret is not configured",
        )

    # Build bytes once; sign and POST from the same object.
    body = serialize_payload(payload)
    signature = sign_body(config.secret, body)

    # X-Request-ID: deterministic prefix over first 24 hex chars of body hash.
    body_hash = hashlib.sha256(body).hexdigest()
    request_id = f"audio-transcriber:{body_hash[:24]}"

    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature": signature,
        "X-Request-ID": request_id,
    }

    try:
        resp = requests.post(
            config.url,
            data=body,
            headers=headers,
            timeout=config.timeout_seconds,
        )
    except requests.RequestException as exc:
        # Log at WARNING so the operator can see delivery failures without
        # cluttering the transcript result. The secret is not in exc's str().
        _logger.warning("Hermes webhook delivery failed: %s", exc)
        return HermesWebhookResult(
            enabled=True,
            sent=False,
            error=f"Request failed: {exc}",
        )

    if resp.ok:
        _logger.debug(
            "Hermes webhook delivered (HTTP %d) to %s",
            resp.status_code,
            config.url,
        )
        return HermesWebhookResult(
            enabled=True,
            sent=True,
            status_code=resp.status_code,
        )

    _logger.warning(
        "Hermes webhook returned non-2xx (HTTP %d) from %s",
        resp.status_code,
        config.url,
    )
    return HermesWebhookResult(
        enabled=True,
        sent=False,
        status_code=resp.status_code,
        error=f"HTTP {resp.status_code}",
    )


# ── Convenience composer ─────────────────────────────────────────────


def emit_audio_transcribed_event(
    *,
    config: HermesWebhookConfig,
    transcript_text: str,
    audio_path: str | None = None,
    history_folder: str | None = None,
    provider: str | None = None,
    language: str | None = None,
    segments: list | None = None,
    summary: str | None = None,
    tasks: list | None = None,
    ideas: list | None = None,
    decisions: list | None = None,
    protocol: str | None = None,
) -> HermesWebhookResult:
    """Build an ``audio.transcribed`` payload and POST it to Hermes.

    Convenience wrapper: build → post → return result. Never raises.
    routing_hint is taken from config.routing_hint so the caller does not
    need to thread it separately.
    """
    payload = build_audio_transcribed_event(
        transcript_text=transcript_text,
        audio_path=audio_path,
        history_folder=history_folder,
        provider=provider,
        language=language,
        segments=segments,
        routing_hint=config.routing_hint,
        summary=summary,
        tasks=tasks,
        ideas=ideas,
        decisions=decisions,
        protocol=protocol,
    )
    return post_event(payload, config)
