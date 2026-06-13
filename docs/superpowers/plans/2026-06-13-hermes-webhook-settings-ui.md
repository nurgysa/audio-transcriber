# Hermes Webhook Settings UI Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GUI section to Settings → «Интеграции» that enables and configures the #146 Hermes webhook (enable checkbox + URL + masked secret + a «Проверить» test-delivery button), so users no longer have to hand-edit `config.json`.

**Architecture:** UI-only increment over the already-shipped backend (`integrations/hermes/`). A new free function `build_hermes_section(dialog, parent)` in `ui/dialogs/settings_builder.py`, wired from `ui/dialogs/settings.py`. Mirrors the dedup checkbox (`build_dedup_section`, #143) for the toggle and the shared `api_key_row` helper (used by Linear/Glide/Trello) for the masked secret + test button. State is dialog-local vars persisted immediately to `dialog._parent._config` via `save_config` (the live object `transcription_mixin._emit_hermes_event` reads).

**Tech Stack:** Python 3.10+, CustomTkinter, pytest. Run Python as `py -3` (the `python` on PATH is a shadowing Hermes venv without pytest/ruff).

**Spec:** `docs/superpowers/specs/2026-06-13-hermes-webhook-settings-ui-design.md`

**Conventions:** Russian UI strings, English code/comments. Tests are source-text checks only (importing `ui.*` loads sounddevice/PortAudio, absent on Linux CI). Always `encoding="utf-8"` on file reads. Branch `feat/hermes-webhook-settings-ui` already exists and is checked out; the spec is already committed there.

---

### Task 1: Source-text lock tests (red first)

Mirrors `tests/test_settings_dedup_section.py`. The webhook client behavior is already covered by `tests/test_hermes_webhook_client.py`; these tests pin the new Settings GUI surface.

**Files:**
- Create: `tests/test_settings_hermes_section.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Hermes webhook section in Settings (spec 2026-06-13).

Source-text checks — no ui imports on Linux CI (sounddevice/PortAudio).
The webhook client itself is covered by tests/test_hermes_webhook_client.py;
these pin the Settings GUI surface (enable + URL + masked secret + test).
"""
from pathlib import Path

BUILDER = Path("ui/dialogs/settings_builder.py").read_text(encoding="utf-8")
SETTINGS = Path("ui/dialogs/settings.py").read_text(encoding="utf-8")


def _section_block() -> str:
    start = BUILDER.index("def build_hermes_section")
    nxt = BUILDER.find("\ndef ", start + 1)
    return BUILDER[start:nxt if nxt != -1 else len(BUILDER)]


def test_builder_has_hermes_section():
    assert "def build_hermes_section" in BUILDER


def test_hermes_section_binds_three_config_keys_and_saves():
    block = _section_block()
    assert "CTkCheckBox" in block
    assert '"hermes_webhook_enabled"' in block
    assert '"hermes_webhook_url"' in block
    assert '"hermes_webhook_secret"' in block
    assert "save_config" in block


def test_hermes_enabled_default_is_false_opt_in():
    # Webhook is opt-in: a missing key means OFF (unlike dedup, which is ON).
    assert 'get("hermes_webhook_enabled", False)' in _section_block()


def test_hermes_secret_uses_api_key_row():
    # Secret is masked + validated through the shared api_key_row helper.
    assert "api_key_row" in _section_block()


def test_hermes_test_button_calls_webhook_client():
    # «Проверить» delivers a real (marked) event via the shipped client.
    block = _section_block()
    assert "on_validate" in block
    assert "emit_audio_transcribed_event" in block


def test_settings_wires_hermes_section_on_integrations_tab():
    assert "build_hermes_section" in SETTINGS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_settings_hermes_section.py -v`
Expected: every test FAILs/ERRORs — `build_hermes_section` is absent, so `_section_block()` raises `ValueError: substring not found` and the presence/wiring asserts fail.

No commit (red state — the codebase rule is green-before-commit).

---

### Task 2: Implement `build_hermes_section`

**Files:**
- Modify: `ui/dialogs/settings_builder.py` (add `text_entry` to the `ui.widgets` import; append the new builder function after `build_dedup_section`, which ends at line ~463)

- [ ] **Step 1: Add `text_entry` to the widgets import**

Find the existing import block (lines ~39-46):

```python
from ui.widgets import (
    api_key_row,
    card,
    label,
    option_menu,
    primary_button,
    tonal_button,
)
```

Replace with (adds `text_entry`, kept isort-sorted):

```python
from ui.widgets import (
    api_key_row,
    card,
    label,
    option_menu,
    primary_button,
    text_entry,
    tonal_button,
)
```

- [ ] **Step 2: Append the builder function**

Add at the end of `ui/dialogs/settings_builder.py` (after `build_dedup_section`):

```python
def build_hermes_section(dialog, parent) -> None:
    """Hermes Agent webhook: enable + URL + secret + test delivery (spec 2026-06-13).

    GUI surface for the #146 webhook (integrations/hermes/). The capability
    (client + emit-after-transcription) already ships; this section just lets
    the user enable and configure it from the GUI instead of editing
    config.json. timeout_seconds / routing_hint stay config-only expert knobs.

    Persistence mirrors build_dedup_section: dialog-local vars, immediate
    save_config to dialog._parent._config (the live object _emit_hermes_event
    reads via get_hermes_webhook_config). Saved on toggle, on field FocusOut,
    and on a successful «Проверить». Webhook is opt-in — default OFF.
    """
    section = section_card(dialog, parent, "Hermes Agent (вебхук)", row=5)

    cfg = dialog._parent._config
    dialog._hermes_webhook_enabled_var = ctk.BooleanVar(
        value=bool(cfg.get("hermes_webhook_enabled", False)),
    )
    dialog._hermes_webhook_url_var = ctk.StringVar(
        value=cfg.get("hermes_webhook_url")
        or "http://localhost:8644/webhooks/audio-transcribed",
    )
    dialog._hermes_webhook_secret_var = ctk.StringVar(
        value=cfg.get("hermes_webhook_secret", ""),
    )

    def _persist_hermes(*_event) -> None:
        # *_event swallows the Tk event object passed by <FocusOut> binds;
        # the checkbox command and validate callback pass nothing.
        c = dialog._parent._config
        c["hermes_webhook_enabled"] = bool(dialog._hermes_webhook_enabled_var.get())
        c["hermes_webhook_url"] = dialog._hermes_webhook_url_var.get().strip()
        c["hermes_webhook_secret"] = dialog._hermes_webhook_secret_var.get()
        save_config(c)

    # row 0 — enable checkbox (persists immediately, like dedup)
    ctk.CTkCheckBox(
        section,
        text="Отправлять расшифровки в Hermes",
        variable=dialog._hermes_webhook_enabled_var,
        command=_persist_hermes,
        font=ctk.CTkFont(family=FONT, size=13),
        text_color=TEXT_PRIMARY, fg_color=BLUE, hover_color=BLUE_DIM,
        border_color=BORDER, corner_radius=4,
        checkbox_height=20, checkbox_width=20,
    ).grid(row=0, column=0, columnspan=4, padx=4, pady=(2, 8), sticky="w")

    # row 1 — URL (plain, non-secret). Labelled (not placeholder-only:
    # CTkEntry hides placeholder_text once a textvariable is set).
    label(section, "URL вебхука").grid(
        row=1, column=0, padx=(4, 8), pady=6, sticky="w",
    )
    url_entry = text_entry(
        section,
        textvariable=dialog._hermes_webhook_url_var,
        placeholder="http://localhost:8644/webhooks/audio-transcribed",
    )
    url_entry.grid(row=1, column=1, columnspan=3, padx=4, pady=6, sticky="ew")
    url_entry.bind("<FocusOut>", _persist_hermes)

    # rows 2-3 — secret (masked) + eye-toggle + «Проверить» + status.
    def _test(secret: str) -> dict:
        # Build an enabled config from the live URL + the entered secret and
        # POST one marked test event through the shipped client. Runs on
        # api_key_row's worker thread; api_key_row marshals UI updates.
        from integrations.hermes.client import (
            HermesWebhookConfig,
            emit_audio_transcribed_event,
        )
        c = dialog._parent._config
        hermes_cfg = HermesWebhookConfig(
            enabled=True,
            url=dialog._hermes_webhook_url_var.get().strip(),
            secret=secret,
            timeout_seconds=float(c.get("hermes_webhook_timeout_seconds", 10) or 10),
            routing_hint=c.get("hermes_webhook_routing_hint") or "obsidian_inbox",
        )
        result = emit_audio_transcribed_event(
            config=hermes_cfg,
            transcript_text="[ТЕСТ] Проверка связи audio-transcriber → Hermes",
            provider="(test)",
        )
        if not result.sent:
            # api_key_row paints the raised message as «✗ …» (red).
            raise RuntimeError(result.error or f"HTTP {result.status_code}")
        return {"status_code": result.status_code}

    refs = api_key_row(
        section,
        label_text="Секрет (HMAC)",
        key_var=dialog._hermes_webhook_secret_var,
        placeholder="(HMAC secret)",
        on_validate=_test,
        on_key_persisted=lambda _secret, _info: _persist_hermes(),
        format_success=lambda info: f"✓ Доставлено (HTTP {info['status_code']})",
        row=2,
    )
    refs["entry"].bind("<FocusOut>", _persist_hermes)
    dialog._hermes_status = refs["status"]

    # row 4 — help line
    label(
        section,
        "ℹ Событие audio.transcribed уходит автоматически после успешной "
        "транскрипции. Маршрут настраивается на стороне Hermes (см. docs).",
        anchor="w",
    ).grid(row=4, column=0, columnspan=4, padx=4, pady=(2, 6), sticky="w")
```

- [ ] **Step 3: Run the section + default tests to verify they pass**

Run: `py -3 -m pytest tests/test_settings_hermes_section.py -v`
Expected: all PASS **except** `test_settings_wires_hermes_section_on_integrations_tab` (still FAIL — not wired yet in Task 3).

- [ ] **Step 4: Lint the changed file**

Run: `py -3 -m ruff check ui/dialogs/settings_builder.py`
Expected: clean (no output / "All checks passed!"). If isort flags the import order, accept its fix.

No commit yet — the wiring test is still red.

---

### Task 3: Wire the section into the Settings dialog

**Files:**
- Modify: `ui/dialogs/settings.py:163` (after the `build_dedup_section` call in the «Интеграции» tab block)

- [ ] **Step 1: Add the wiring call**

Find (lines ~158-163):

```python
        # Tab 2 «Интеграции» — LLM-side optional extras
        settings_builder.build_openrouter_section(self, scroll_integrations)
        settings_builder.build_linear_section(self, scroll_integrations)
        settings_builder.build_glide_section(self, scroll_integrations)
        settings_builder.build_trello_section(self, scroll_integrations)
        settings_builder.build_dedup_section(self, scroll_integrations)
```

Append one line:

```python
        # Tab 2 «Интеграции» — LLM-side optional extras
        settings_builder.build_openrouter_section(self, scroll_integrations)
        settings_builder.build_linear_section(self, scroll_integrations)
        settings_builder.build_glide_section(self, scroll_integrations)
        settings_builder.build_trello_section(self, scroll_integrations)
        settings_builder.build_dedup_section(self, scroll_integrations)
        settings_builder.build_hermes_section(self, scroll_integrations)
```

- [ ] **Step 2: Run the section tests to verify all pass**

Run: `py -3 -m pytest tests/test_settings_hermes_section.py -v`
Expected: all 6 PASS.

- [ ] **Step 3: Run the widget-tree-split locks (must still pass)**

Run: `py -3 -m pytest tests/test_widget_tree_split.py -v`
Expected: all PASS (the new code is a free builder function — no `def _build_` on the class, no back-import of `ui.dialogs.settings`).

- [ ] **Step 4: Commit the green feature (tests + builder + wiring together)**

```bash
git add tests/test_settings_hermes_section.py ui/dialogs/settings_builder.py ui/dialogs/settings.py
git commit -F- <<'EOF'
feat(settings): Hermes webhook toggle in Интеграции tab

Adds build_hermes_section: enable checkbox + URL + masked secret (via
api_key_row) + «Проверить» test-delivery button, wired into the
Интеграции tab after dedup. Persists hermes_webhook_{enabled,url,secret}
to the live config on toggle / field FocusOut / successful test. UI-only
surface over the #146 backend; webhook stays opt-in (default OFF).
timeout_seconds / routing_hint remain config-only expert knobs.

Source-text lock tests mirror test_settings_dedup_section.py.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 4: Full verification + manual GUI smoke

- [ ] **Step 1: Full test suite**

Run: `py -3 -m pytest -q`
Expected: green (baseline grows by +6 from the new file). If the summary line is swallowed by the PS console, re-run with `--junitxml=.cache/junit_hermes.xml` and read the XML.

- [ ] **Step 2: Full lint**

Run: `py -3 -m ruff check .`
Expected: clean. If anything in the two modified files is flagged, fix inline and re-run; if a fix changes code, amend or add a follow-up commit.

- [ ] **Step 3: Manual GUI smoke (human-run — structural tests can't catch CTk layout/threading)**

Optional local sink to exercise «Проверить» end-to-end (returns 200 to any POST on the default port/path):

```python
# save as .cache/hermes_sink.py, run: py -3 .cache/hermes_sink.py
from http.server import BaseHTTPRequestHandler, HTTPServer


class Sink(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        print("got", self.headers.get("X-Webhook-Signature"), body[:120])
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")


HTTPServer(("127.0.0.1", 8644), Sink).serve_forever()
```

Then run the app from the **main repo** (not a worktree — gitignored config/history don't follow worktrees):

Run: `py -3 app.py`

Checklist:
1. Open «Настройки» → tab «Интеграции» → a «Hermes Agent (вебхук)» card appears below «Дубли задач».
2. Tick «Отправлять расшифровки в Hermes», type a secret, leave URL at default. Tab out of each field.
3. Close + reopen Settings → the checkbox stays ticked and the secret is present (persisted to `config.json`).
4. With the sink running, click «Проверить» → status shows `✓ Доставлено (HTTP 200)`; the sink prints the signature + body. Stop the sink, click again → `✗ …` (connection refused).
5. Secret field is masked (`•`); the 👁 button reveals it.

- [ ] **Step 4: (if smoke required code changes) commit the fixes**

```bash
git add -p
git commit -F- <<'EOF'
fix(settings): <what the smoke surfaced>

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

## Notes for the executor

- **Do not** add `hermes_webhook_*` to `config.example.json` — #146 already did (lines 27-31). Verify, don't duplicate.
- **Do not** touch `integrations/hermes/client.py` or `transcription_mixin._emit_hermes_event` — they already work; this is UI-only.
- The `_test` import of `integrations.hermes.client` is **lazy (inside the function)** by design — keeps the builder import-discipline lock green and avoids pulling `requests` onto the dialog-construction path.
- Stage specific files (never `git add -A`): the user runs parallel git work in this same tree, and `.cache/` + `scripts/smoke_dedup_live.py` are untracked-by-design.
- After all tasks: use `superpowers:finishing-a-development-branch` to decide merge/PR.
```
