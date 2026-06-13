# Hermes Webhook — Settings UI Toggle (design)

**Date:** 2026-06-13
**Status:** approved (brainstorming), pre-plan
**Depends on:** #146 (Hermes outbound webhook backend — `integrations/hermes/`, emit wiring, config keys). Already in `main`.

## 1. Problem

The Hermes `audio.transcribed` webhook shipped in #146 is **config/env-only**: it
reads `hermes_webhook_*` keys from `config.json` (or `AUDIO_TRANSCRIBER_HERMES_WEBHOOK_*`
env vars). It ships **disabled by default** (`hermes_webhook_enabled: false`) and has
**no GUI affordance**. A GUI user therefore cannot turn it on, and because the emit
path early-returns silently when disabled (`transcription_mixin.py` →
`if not hermes_cfg.enabled: return`, no log line), the feature reads as "not working"
with no error. The user's real configs (`~/.audio-transcriber/config.json`, dated
before #146) contain none of the keys, so nothing is ever sent.

Root cause is a config/UX gap, **not** a bug in the webhook client (which is correct
and unit-tested). This spec adds the missing GUI surface.

## 2. Goal / Non-goals

**Goal:** a Settings UI that lets the user enable the webhook, set URL + secret, and
verify delivery — without hand-editing `config.json`.

**Non-goals:**
- No change to the webhook client (`integrations/hermes/client.py`) or the
  emit-after-transcription wiring — both already work.
- No GUI for `timeout_seconds` / `routing_hint` — they stay config-only expert knobs
  (same posture as `dedup_fuzzy_*`).
- No Hermes-side setup automation (that stays in docs, per #146 §10).

## 3. Placement

New free function `build_hermes_section(dialog, parent)` in
`ui/dialogs/settings_builder.py`, invoked from `ui/dialogs/settings.py` immediately
after `build_dedup_section`, in the **«Интеграции»** tab at `row=5`.

This is a UI-only increment over an already-shipped capability — it does not violate
the "UI affordance + capability in the same PR" rule, because the capability landed in
#146.

## 4. Layout

Mirrors the Trello section (two fields + shared status), composed from the existing
`api_key_row` helper plus a plain URL entry:

```
┌ Hermes Agent (вебхук) ───────────────────────────┐
│ ☐ Отправлять расшифровки в Hermes                 │
│ URL вебхука    [http://localhost:8644/webhooks/…] │
│ Секрет (HMAC)  [•••••••••]  👁  [ Проверить ]      │
│                ✓ Доставлено (HTTP 200)            │
│ ℹ Событие audio.transcribed уходит автоматически  │
│   после успешной транскрипции.                    │
└───────────────────────────────────────────────────┘
```

Row plan inside the section card (inner frame, column 1 weighted):
- row 0: enable checkbox (created directly, mirrors `build_dedup_section`)
- row 1: `label("URL вебхука")` + `text_entry(textvariable=url_var)` (columnspan 1→3)
- row 2: `api_key_row(..., row=2)` — masked secret + eye-toggle + «Проверить»
- row 3: status badge (owned by `api_key_row`)
- row 4: `label(...)` help line

## 5. State + config mapping

Three dialog-local UI proxies (same pattern as `_dedup_enabled_var`,
`_meetings_path_var` — created in the builder, live on the dialog, persisted
immediately; `config.json` is the source of truth):

| Widget | Var (on dialog) | Config key | Default |
|---|---|---|---|
| Enable checkbox | `_hermes_webhook_enabled_var` (`BooleanVar`) | `hermes_webhook_enabled` | `False` (opt-in) |
| URL entry | `_hermes_webhook_url_var` (`StringVar`) | `hermes_webhook_url` | `http://localhost:8644/webhooks/audio-transcribed` |
| Secret (masked) | `_hermes_webhook_secret_var` (`StringVar`) | `hermes_webhook_secret` | `""` |

Initial values read from `dialog._parent._config` with the defaults above. The enable
checkbox default is `bool(config.get("hermes_webhook_enabled", False))` — note **False**,
unlike dedup's `True`.

## 6. Persistence

A single `_persist_hermes()` closure in the builder (mirrors dedup's `_on_toggled`)
writes all three keys to `dialog._parent._config` and calls `save_config`:

```python
cfg = dialog._parent._config
cfg["hermes_webhook_enabled"] = bool(enabled_var.get())
cfg["hermes_webhook_url"] = url_var.get().strip()
cfg["hermes_webhook_secret"] = secret_var.get()
save_config(cfg)
```

Triggers (so nothing is lost if the user skips «Проверить»):
- checkbox `command=_persist_hermes`
- `<FocusOut>` on the URL entry and on the secret entry (`refs["entry"]`)
- «Проверить» success path (`on_key_persisted` also calls `_persist_hermes`)

`transcription_mixin._emit_hermes_event` reads the same live `self._config` object via
`get_hermes_webhook_config(self._config)`, so the next transcription picks up the new
values immediately; `save_config` persists them for next launch.

## 7. «Проверить» button (test delivery)

Implemented via `api_key_row`'s `on_validate` (the helper runs it in a daemon thread and
marshals UI updates through `parent.after(0, ...)` — Tk thread contract satisfied; no new
threading code). It builds an enabled `HermesWebhookConfig` from the current URL + secret
and calls the existing `emit_audio_transcribed_event` with a clearly-marked test
transcript:

```python
def _test(secret: str) -> dict:
    from integrations.hermes.client import (
        HermesWebhookConfig, emit_audio_transcribed_event,
    )
    cfg = HermesWebhookConfig(
        enabled=True,
        url=url_var.get().strip(),
        secret=secret,
        timeout_seconds=float(dialog._parent._config.get("hermes_webhook_timeout_seconds", 10) or 10),
        routing_hint=dialog._parent._config.get("hermes_webhook_routing_hint") or "obsidian_inbox",
    )
    result = emit_audio_transcribed_event(
        config=cfg,
        transcript_text="[ТЕСТ] Проверка связи audio-transcriber → Hermes",
        provider="(test)",
    )
    if not result.sent:
        raise RuntimeError(result.error or f"HTTP {result.status_code}")
    return {"status_code": result.status_code}
```

`format_success = lambda info: f"✓ Доставлено (HTTP {info['status_code']})"`. On failure,
`api_key_row` paints `✗ {error}` (red, truncated). `api_key_row` already blocks an empty
secret with «Введите API ключ»; an empty URL surfaces as the client's own error result.

**Accepted trade-off:** a successful test creates one `[ТЕСТ]` entry on the Hermes side
(routed per `routing_hint`, e.g. into the Obsidian inbox), which the user deletes manually.
This is the only way to validate the full chain (reachability + HMAC + route).

## 8. Error handling

The webhook client never raises to the caller; the test surfaces failures via the status
badge; enabling/saving cannot crash; default is off. The emit-after-transcription path is
untouched.

## 9. Testing

`tests/test_settings_hermes_section.py` — source-text locks only (importing `ui.*` loads
sounddevice/PortAudio, which Linux CI lacks; encoding pinned to UTF-8). Mirrors
`tests/test_settings_dedup_section.py`:

- `def build_hermes_section` present in `settings_builder.py`
- section block binds the three config keys (`hermes_webhook_enabled`,
  `hermes_webhook_url`, `hermes_webhook_secret`) and calls `save_config`
- enable default is `get("hermes_webhook_enabled", False)`
- section uses `api_key_row` for the secret field
- `settings.py` wires `build_hermes_section` on the Интеграции tab

GUI threading is intentionally not unit-tested (per #146 §9.5 "unit-test the client, not
GUI threading"); the client is already covered by `tests/test_hermes_webhook_client.py`.

Gate before commit: `py -3 -m pytest` green + `py -3 -m ruff check .` clean.

## 10. Invariants respected

- `test_widget_tree_split` lock: free function in the builder, no `def _build_` on the
  dialog class, no `from ui.dialogs.settings import` / module-level `ui.app` in the builder.
- No naked hex in CTk styles — all colours from `theme`.
- Fields labelled with `label(...)`, not placeholder text (CTkEntry hides
  `placeholder_text` when a `textvariable` is set).
- `encoding="utf-8"` on all file reads in tests.
- Russian UI strings; English code/comments.
- Invariant #2 (no local CUDA/whisper/pyannote): N/A — no inference code.

## 11. Acceptance criteria

1. «Интеграции» tab shows a «Hermes Agent (вебхук)» section with an enable checkbox,
   URL field, masked secret field, «Проверить» button, and a status badge.
2. Toggling the checkbox / editing URL or secret persists to `config.json` immediately.
3. With a reachable Hermes endpoint and matching secret, «Проверить» shows
   `✓ Доставлено (HTTP 2xx)`; with a wrong URL/secret it shows `✗ …`.
4. After enabling + configuring in the GUI, a real transcription delivers an
   `audio.transcribed` event (no restart needed).
5. `pytest` + `ruff` green; widget-tree-split locks still pass.
