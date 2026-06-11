# Provider Dedup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lift the transport duplication shared by the 4 cloud STT providers into one `providers/_common.py` module, per the approved spec `docs/superpowers/specs/2026-06-11-provider-dedup-design.md`.

**Architecture:** New package-private `providers/_common.py` holds cancel checks, MIME guessing, key checks, the HTTP error idiom (`request`), JSON guards, the parameterized poll loop (`PollSpec` + `poll`), streaming upload and best-effort remote cancel. Provider modules keep ONLY domain logic (payload builders, response adapters, workflow orchestration). `providers/base.py` is untouched.

**Tech Stack:** Python 3.10+, `requests`, pytest with `unittest.mock.patch`, ruff.

**Two serial PRs.** PR-2 starts only after PR-1 is squash-merged into main (no stacking — orphaned-branch lesson).

---

## Execution notes (read first)

- Run Python as `py -3` — plain `python` is shadowed by a foreign venv on this machine (`py -3 -m pytest`, `py -3 -m ruff check .`).
- Commit messages: inline ASCII only (PowerShell 5.1 mangles embedded quotes/Cyrillic in native args). Longer bodies → temp file + `git commit -F`.
- Stage specific files only (`git add <paths>`), never `-A` — the user may switch branches in this working tree mid-run.
- Subagents: do NOT switch branches or checkout main; work only on the branch named in the task.
- Test baseline before this work: ≈773 passed, 2 skipped. Every task ends green + ruff-clean.
- Line references to provider sources are against main @ `9d31d61`.

---

# PR-1 — `refactor(providers): lift identical helpers to _common`

Branch: `refactor/provider-common-helpers`, created from `docs/provider-dedup-spec` (carries the spec + this plan, tree-split precedent: docs ride the first PR).

```powershell
git checkout docs/provider-dedup-spec
git checkout -b refactor/provider-common-helpers
```

### Task 1: `_common.py` skeleton — `check_cancel`, `guess_content_type`, `require_key`

**Files:**
- Create: `providers/_common.py`
- Create: `tests/test_providers_common.py`

- [ ] **Step 1.1: Write the failing tests**

Create `tests/test_providers_common.py`:

```python
"""Direct units for providers._common — shared transport machinery.

HTTP is patched at the ONE canonical target: ``providers._common.requests``.
The per-provider test files keep their behavioral assertions and act as
integration coverage on top of these units.
"""
from __future__ import annotations

import threading

import pytest

from providers._common import (
    check_cancel,
    guess_content_type,
    require_key,
)
from providers.base import ProviderError


# ── check_cancel ──────────────────────────────────────────────────────


def test_check_cancel_none_event_is_noop():
    check_cancel(None)  # must not raise


def test_check_cancel_unset_event_is_noop():
    check_cancel(threading.Event())


def test_check_cancel_set_event_raises_transcription_cancelled():
    from transcriber import TranscriptionCancelled

    ev = threading.Event()
    ev.set()
    with pytest.raises(TranscriptionCancelled):
        check_cancel(ev)


# ── guess_content_type ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("ext", "mime"),
    [
        (".mp3", "audio/mpeg"),
        (".wav", "audio/wav"),
        (".m4a", "audio/mp4"),
        (".flac", "audio/flac"),
        (".ogg", "audio/ogg"),
        (".webm", "audio/webm"),
        (".xyz", "application/octet-stream"),
    ],
)
def test_guess_content_type(ext, mime):
    assert guess_content_type(f"C:/audio/file{ext}") == mime


def test_guess_content_type_is_case_insensitive():
    assert guess_content_type("C:/audio/FILE.MP3") == "audio/mpeg"


# ── require_key ───────────────────────────────────────────────────────


def test_require_key_strips_and_returns():
    assert require_key("  abc  ", "AssemblyAI") == "abc"


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_require_key_empty_raises_with_provider_name(bad):
    with pytest.raises(ProviderError, match="API-ключ Gladia не задан"):
        require_key(bad, "Gladia")
```

- [ ] **Step 1.2: Run to verify failure**

Run: `py -3 -m pytest tests/test_providers_common.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'providers._common'`

- [ ] **Step 1.3: Implement**

Create `providers/_common.py`:

```python
"""Shared transport machinery for cloud transcription providers.

Everything here is plumbing that must behave identically across the four
providers: cancel checks, MIME guessing, key checks, the HTTP error idiom,
the completion poll loop, streaming upload, best-effort remote cancel.
Domain logic (payload building, response mapping, workflow order) stays in
the provider modules.

Test contract: HTTP is patched at ONE canonical target —
``providers._common.requests.<verb>`` — instead of per-provider modules.
"""

from __future__ import annotations

import logging
import os

import requests

from .base import ProviderError

_logger = logging.getLogger(__name__)

#: Upload chunk size for streaming bodies. 5 MB: small enough for snappy
#: cancel polling, big enough that per-chunk overhead is negligible.
UPLOAD_CHUNK = 5 * 1024 * 1024


def check_cancel(cancel_event) -> None:
    """Raise TranscriptionCancelled when the user pressed Стоп.

    Imported lazily to keep the provider package free of any direct
    dependency on the transcriber module — the exception class is the
    only piece of contract we need here.
    """
    if cancel_event is not None and cancel_event.is_set():
        from transcriber import TranscriptionCancelled
        raise TranscriptionCancelled()


def guess_content_type(path: str) -> str:
    """Map the source extension to an audio MIME type providers accept."""
    ext = os.path.splitext(path)[1].lower()
    return {
        ".mp3":  "audio/mpeg",
        ".wav":  "audio/wav",
        ".m4a":  "audio/mp4",
        ".flac": "audio/flac",
        ".ogg":  "audio/ogg",
        ".webm": "audio/webm",
    }.get(ext, "application/octet-stream")


def require_key(api_key: str | None, provider: str) -> str:
    """Validate-and-strip the API key at provider construction time."""
    if not api_key or not api_key.strip():
        raise ProviderError(
            f"API-ключ {provider} не задан. Открой Настройки → Облако и "
            "вставь ключ."
        )
    return api_key.strip()
```

- [ ] **Step 1.4: Run to verify pass**

Run: `py -3 -m pytest tests/test_providers_common.py -v`
Expected: all PASS

- [ ] **Step 1.5: Commit**

```powershell
git add providers/_common.py tests/test_providers_common.py
git commit -m "refactor(providers): add _common with cancel/MIME/key helpers"
```

### Task 2: Rewire all 4 providers to the Task-1 helpers

**Files:**
- Modify: `providers/assemblyai.py` (drop `_check_cancel` :351-358; `__init__` :58-65)
- Modify: `providers/deepgram.py` (drop `_check_cancel` :175-179, `_guess_content_type` :185-195; `__init__` :52-58)
- Modify: `providers/gladia.py` (drop `_check_cancel` :284-288, `_guess_content_type` :294-303; `__init__` :50-57)
- Modify: `providers/speechmatics.py` (drop `_check_cancel` :262-266, `_guess_content_type` :272-281; `__init__` :44-51)

No new tests — existing provider tests pin behavior; no patch target moves (these helpers make no HTTP calls).

- [ ] **Step 2.1: AssemblyAI**

Add import `from ._common import check_cancel, require_key`. Replace `__init__` body:

```python
    def __init__(self, api_key: str):
        self._api_key = require_key(api_key, "AssemblyAI")
        self._headers = {"authorization": self._api_key}
```

Delete the `_check_cancel` staticmethod (incl. its comment); replace every `self._check_cancel(cancel_event)` call (5 sites: `transcribe` ×2 — :101/:109, `_upload._gen` ×1 — :151, `_poll` ×2 — :275/:327) with `check_cancel(cancel_event)`.

- [ ] **Step 2.2: Deepgram**

Add import `from ._common import check_cancel, guess_content_type, require_key`. Replace `__init__` body with `self._api_key = require_key(api_key, "Deepgram")`. Delete `_check_cancel` staticmethod and module-level `_guess_content_type`; replace call sites (`self._check_cancel(...)` → `check_cancel(...)`, `_guess_content_type(audio_path)` → `guess_content_type(audio_path)`).

- [ ] **Step 2.3: Gladia**

Same pattern: import `check_cancel, guess_content_type, require_key`; `__init__` → `self._api_key = require_key(api_key, "Gladia")` + keep `self._headers = {"x-gladia-key": self._api_key}`; delete local `_check_cancel`/`_guess_content_type`; replace call sites.

- [ ] **Step 2.4: Speechmatics**

Same pattern: `self._api_key = require_key(api_key, "Speechmatics")` + keep `self._headers = {"Authorization": f"Bearer {self._api_key}"}`; delete local `_check_cancel`/`_guess_content_type`; replace call sites.

- [ ] **Step 2.5: Run the provider suite**

Run: `py -3 -m pytest tests/test_providers_assemblyai.py tests/test_providers_deepgram.py tests/test_providers_gladia.py tests/test_providers_speechmatics.py tests/test_providers_validate.py tests/test_providers_poll_json_guard.py tests/test_providers_base.py -v`
Expected: all PASS (empty-key messages byte-identical; ruff will flag any now-unused imports — remove them).

- [ ] **Step 2.6: Ruff + commit**

Run: `py -3 -m ruff check .` → clean (drop unused `os` imports only if ruff says so — `os` stays used everywhere).

```powershell
git add providers/assemblyai.py providers/deepgram.py providers/gladia.py providers/speechmatics.py
git commit -m "refactor(providers): use _common cancel/MIME/key helpers in all 4 providers"
```

### Task 3: `cancel_remote` → `_common` + thin wrappers

**Files:**
- Modify: `providers/_common.py` (append)
- Modify: `providers/assemblyai.py` (`_cancel_remote` :331-349)
- Modify: `providers/speechmatics.py` (`_cancel_remote` :250-260 — kills its bare `except Exception: pass`)
- Modify: `tests/test_providers_common.py` (append)
- Modify: `tests/test_providers_assemblyai.py` (:134-156 — re-target 2 delete patches + caplog logger)

- [ ] **Step 3.1: Write the failing tests**

Append to `tests/test_providers_common.py`:

```python
# ── cancel_remote ─────────────────────────────────────────────────────


def test_cancel_remote_network_error_logged_not_raised(caplog):
    import logging
    from unittest.mock import patch

    import requests

    from providers._common import cancel_remote

    with patch(
        "providers._common.requests.delete",
        side_effect=requests.ConnectionError("boom"),
    ), caplog.at_level(logging.WARNING, logger="providers._common"):
        cancel_remote("https://api.example/jobs/42", {"h": "1"}, provider="X")
    assert any("cancel-DELETE failed" in r.message for r in caplog.records)
    assert any("jobs/42" in r.message for r in caplog.records)


def test_cancel_remote_success_no_log(caplog):
    from unittest.mock import MagicMock, patch

    from providers._common import cancel_remote

    with patch(
        "providers._common.requests.delete",
        return_value=MagicMock(ok=True, status_code=200),
    ):
        with caplog.at_level("WARNING", logger="providers._common"):
            cancel_remote("https://api.example/jobs/42", {}, provider="X")
    assert caplog.records == []
```

(Move the `from unittest.mock import ...` / `import requests` / `import logging` lines to the file top with the other imports — shown inline here only for self-containment.)

- [ ] **Step 3.2: Run to verify failure**

Run: `py -3 -m pytest tests/test_providers_common.py -k cancel_remote -v`
Expected: FAIL — `ImportError: cannot import name 'cancel_remote'`

- [ ] **Step 3.3: Implement in `_common.py`**

```python
def cancel_remote(url: str, headers: dict, *, provider: str) -> None:
    """Best-effort DELETE of a remote job on local cancel/failure.

    Network/auth failures are logged but not raised — by the time we call
    this, the user has already cancelled and the UI has moved on. Repeated
    failures mean we're being billed for stuck jobs, so the warning level
    surfaces the issue in app.log.
    """
    try:
        requests.delete(url, headers=headers, timeout=10)
    except requests.RequestException as e:
        _logger.warning(
            "%s cancel-DELETE failed for %s (job may stay billable): %s",
            provider, url, e,
        )
```

- [ ] **Step 3.4: Rewire the two providers**

`providers/assemblyai.py` — extend the `_common` import with `cancel_remote`, replace the whole `_cancel_remote` method:

```python
    def _cancel_remote(self, transcript_id: str) -> None:
        """Best-effort server-side cancel so the user isn't billed for a
        run we already gave up on (details in _common.cancel_remote)."""
        cancel_remote(
            f"{_API_BASE}/transcript/{transcript_id}",
            self._headers,
            provider=self.display_name,
        )
```

Then delete the now-unused `import logging` + `_logger` lines from `assemblyai.py`.

`providers/speechmatics.py` — same, replacing the bare-except version:

```python
    def _cancel_remote(self, job_id: str) -> None:
        """Best-effort server-side cancel (details in _common.cancel_remote)."""
        cancel_remote(
            f"{_API_BASE}/jobs/{job_id}",
            self._headers,
            provider=self.display_name,
        )
```

- [ ] **Step 3.5: Re-target the 2 AssemblyAI cancel tests**

In `tests/test_providers_assemblyai.py` (:141-144 and :153-154): replace patch target `"providers.assemblyai.requests.delete"` → `"providers._common.requests.delete"` (2 sites) and `logger="providers.assemblyai"` → `logger="providers._common"` (2 sites). Assertions stay: the shared warning logs the full URL, which contains `transcript-123`.

- [ ] **Step 3.6: Run, ruff, commit**

Run: `py -3 -m pytest tests/test_providers_common.py tests/test_providers_assemblyai.py tests/test_providers_speechmatics.py -v` → PASS; `py -3 -m ruff check .` → clean.

```powershell
git add providers/_common.py providers/assemblyai.py providers/speechmatics.py tests/test_providers_common.py tests/test_providers_assemblyai.py
git commit -m "refactor(providers): shared best-effort cancel_remote (narrows SM bare except)"
```

### Task 4: `validate_via_get` + rewire 4 `validate_key`

**Files:**
- Modify: `providers/_common.py` (append)
- Modify: `providers/{assemblyai,deepgram,gladia,speechmatics}.py` (`validate_key` bodies :67-86 / :60-80 / :59-78 / :53-72)
- Modify: `tests/test_providers_common.py` (append)
- Modify: `tests/test_providers_validate.py` (re-target 3 parametrize lists)

- [ ] **Step 4.1: Write the failing tests**

Append to `tests/test_providers_common.py` (imports to file top):

```python
# ── validate_via_get ──────────────────────────────────────────────────


def test_validate_via_get_2xx_returns_empty_dict():
    r = MagicMock(status_code=200, text="{}")
    with patch("providers._common.requests.get", return_value=r) as g:
        out = validate_via_get(
            "https://api.example/check", headers={"a": "b"}, provider="X",
            params={"limit": 1},
        )
    assert out == {}
    assert g.call_args.kwargs.get("timeout") == 15
    assert g.call_args.kwargs.get("params") == {"limit": 1}


@pytest.mark.parametrize("code", [401, 403])
def test_validate_via_get_rejected_key_is_russian(code):
    r = MagicMock(status_code=code, text="unauthorized")
    with patch("providers._common.requests.get", return_value=r):
        with pytest.raises(ProviderError, match="X отклонил ключ"):
            validate_via_get("u", headers={}, provider="X")


def test_validate_via_get_http_error_truncates_to_300():
    r = MagicMock(status_code=500, text="y" * 1000)
    with patch("providers._common.requests.get", return_value=r):
        with pytest.raises(
            ProviderError, match="проверка ключа не удалась"
        ) as ei:
            validate_via_get("u", headers={}, provider="X")
    assert "y" * 300 in str(ei.value)
    assert "y" * 301 not in str(ei.value)


def test_validate_via_get_network_failure():
    with patch(
        "providers._common.requests.get",
        side_effect=requests.RequestException("boom"),
    ):
        with pytest.raises(
            ProviderError, match="Сеть не отвечает при проверке ключа"
        ):
            validate_via_get("u", headers={}, provider="X")
```

- [ ] **Step 4.2: Run to verify failure**

Run: `py -3 -m pytest tests/test_providers_common.py -k validate_via_get -v`
Expected: FAIL — `ImportError`

- [ ] **Step 4.3: Implement in `_common.py`**

```python
def validate_via_get(url: str, *, headers: dict, provider: str,
                     params: dict | None = None) -> dict:
    """Shared body for provider ``validate_key`` overrides.

    Cheapest authenticated GET; 2xx proves the key is live. Self-contained
    (does not route through ``request()``) — its >=400 template differs
    and the base-class default-refuse contract from #133 stays in base.py.
    """
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
    except requests.RequestException as e:
        raise ProviderError(f"Сеть не отвечает при проверке ключа: {e}") from e
    if r.status_code in (401, 403):
        raise ProviderError(
            f"{provider} отклонил ключ (401). Проверь API-ключ в "
            "Настройках → Облако."
        )
    if r.status_code >= 400:
        raise ProviderError(
            f"{provider}: проверка ключа не удалась ({r.status_code}): "
            f"{r.text[:300]}"
        )
    return {}
```

- [ ] **Step 4.4: Rewire the 4 providers**

`assemblyai.py` (extend `_common` import with `validate_via_get`):

```python
    def validate_key(self) -> dict:
        """Cheap auth check: GET /transcript?limit=1 — 2xx means the key is live."""
        return validate_via_get(
            f"{_API_BASE}/transcript", headers=self._headers,
            provider=self.display_name, params={"limit": 1},
        )
```

`deepgram.py` (no `self._headers` attr — build inline, as today):

```python
    def validate_key(self) -> dict:
        """Cheap auth check: GET /v1/auth/token — 2xx means the key is live."""
        return validate_via_get(
            "https://api.deepgram.com/v1/auth/token",
            headers={"Authorization": f"Token {self._api_key}"},
            provider=self.display_name,
        )
```

`gladia.py`:

```python
    def validate_key(self) -> dict:
        """Cheap auth check: GET /pre-recorded?limit=1 — 2xx means the key is live."""
        return validate_via_get(
            f"{_API_BASE}/pre-recorded", headers=self._headers,
            provider=self.display_name, params={"limit": 1},
        )
```

`speechmatics.py`:

```python
    def validate_key(self) -> dict:
        """Cheap auth check: GET /jobs/?limit=1 — 2xx means the key is live."""
        return validate_via_get(
            f"{_API_BASE}/jobs/", headers=self._headers,
            provider=self.display_name, params={"limit": 1},
        )
```

- [ ] **Step 4.5: Re-target `tests/test_providers_validate.py`**

In all 3 `@pytest.mark.parametrize` lists (:45-53, :65-73, :81-89), replace every module string `"providers.assemblyai"` / `"providers.deepgram"` / `"providers.gladia"` / `"providers.speechmatics"` with `"providers._common"`. The first list keeps its `url_part` третий элемент unchanged. `test_base_default_refuses_with_provider_error` stays as-is (base.py untouched).

- [ ] **Step 4.6: Run, ruff, commit**

Run: `py -3 -m pytest tests/test_providers_common.py tests/test_providers_validate.py -v` → PASS. Note: `test_validate_via_get_http_error_truncates_to_300` pins the [:200]→[:300] unification (spec behavior change #3). `py -3 -m ruff check .` → clean.

```powershell
git add providers/_common.py providers/assemblyai.py providers/deepgram.py providers/gladia.py providers/speechmatics.py tests/test_providers_common.py tests/test_providers_validate.py
git commit -m "refactor(providers): shared validate_via_get behind the 4 validate_key overrides"
```

### Task 5: `file_stream` + rewire AAI `_upload` / DG `transcribe` generators

**Files:**
- Modify: `providers/_common.py` (append)
- Modify: `providers/assemblyai.py` (`_upload` :137-189 — generator part; `_UPLOAD_CHUNK` :41)
- Modify: `providers/deepgram.py` (`transcribe` :115-130 — generator part; `_UPLOAD_CHUNK` :38)
- Modify: `tests/test_providers_common.py` (append)

- [ ] **Step 5.1: Write the failing tests**

Append to `tests/test_providers_common.py`:

```python
# ── file_stream ───────────────────────────────────────────────────────


def test_file_stream_yields_all_bytes_and_band_progress(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"0123456789")  # 10 bytes
    calls: list[float] = []
    chunks = list(
        file_stream(
            str(f), cancel_event=None, on_progress=calls.append, chunk_size=4,
        )
    )
    assert b"".join(chunks) == b"0123456789"
    # 4/10, 8/10, 10/10 of the default 70 % band
    assert calls == pytest.approx([28.0, 56.0, 70.0])


def test_file_stream_no_progress_callback_ok(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"xy")
    assert b"".join(file_stream(str(f), cancel_event=None, on_progress=None)) == b"xy"


def test_file_stream_cancel_mid_stream(tmp_path):
    from transcriber import TranscriptionCancelled

    f = tmp_path / "a.bin"
    f.write_bytes(b"x" * 10)
    ev = threading.Event()
    gen = file_stream(str(f), cancel_event=ev, on_progress=None, chunk_size=4)
    assert next(gen) == b"xxxx"
    ev.set()
    with pytest.raises(TranscriptionCancelled):
        next(gen)
```

- [ ] **Step 5.2: Run to verify failure**

Run: `py -3 -m pytest tests/test_providers_common.py -k file_stream -v`
Expected: FAIL — `ImportError`

- [ ] **Step 5.3: Implement in `_common.py`**

```python
def file_stream(path: str, *, cancel_event, on_progress,
                band: float = 70.0, chunk_size: int = UPLOAD_CHUNK):
    """Chunked file reader for streaming upload bodies.

    Yields ``chunk_size`` blocks, checking the cancel event between reads
    and reporting progress 0..``band`` % — the remaining band belongs to
    the caller's processing phase (mirrors the local progress contract).
    """
    size = os.path.getsize(path)
    sent = 0
    with open(path, "rb") as f:
        while True:
            check_cancel(cancel_event)
            chunk = f.read(chunk_size)
            if not chunk:
                return
            sent += len(chunk)
            if on_progress and size > 0:
                on_progress(min(sent / size, 1.0) * band)
            yield chunk
```

- [ ] **Step 5.4: Rewire AssemblyAI `_upload`**

Extend the `_common` import with `file_stream`; delete module constant `_UPLOAD_CHUNK` (:38-41 incl. comment) and inside `_upload` delete the `size`/`sent` locals and the whole nested `_gen()` (:144-160), replacing the requests call's `data=` argument:

```python
        try:
            r = requests.post(
                f"{_API_BASE}/upload",
                headers=self._headers,
                data=file_stream(
                    audio_path, cancel_event=cancel_event,
                    on_progress=on_progress,
                ),
                timeout=60 * 30,  # 30 min absolute upload cap
            )
```

(The surrounding try/except + 401/ok/json handling stays put — it moves in PR-2.)

- [ ] **Step 5.5: Rewire Deepgram `transcribe`**

Delete module constant `_UPLOAD_CHUNK` (:36-38 incl. comment); in `transcribe` delete the `size`/`sent` locals and nested `_gen()` (:115-130), replacing the `data=` argument:

```python
            r = requests.post(
                _API_URL,
                params=params,
                headers=headers,
                data=file_stream(
                    audio_path, cancel_event=cancel_event,
                    on_progress=on_progress,
                ),
                timeout=60 * 30,
            )
```

- [ ] **Step 5.6: Run, ruff, commit**

Run: `py -3 -m pytest tests/test_providers_common.py tests/test_providers_assemblyai.py tests/test_providers_deepgram.py -v` → PASS (upload tests still patch `providers.assemblyai.requests.post` — the POST hasn't moved yet). `py -3 -m ruff check .` → clean.

```powershell
git add providers/_common.py providers/assemblyai.py providers/deepgram.py tests/test_providers_common.py
git commit -m "refactor(providers): shared file_stream for AAI/DG streaming uploads"
```

### Task 6: PR-1 finalize

- [ ] **Step 6.1: Full gate**

Run: `py -3 -m pytest` → ≈788 passed / 2 skipped (773 + ~15 new units), 0 failed. Run: `py -3 -m ruff check .` → clean.

- [ ] **Step 6.2: Push + PR**

```powershell
git push -u origin refactor/provider-common-helpers
```

Write the PR body to `%TEMP%\pr1-body.md` (`## Summary` — what moved + the two PR-1 behavior changes: validate truncation [:200]→[:300], SM cancel narrow-except+log; `## Test plan` — checkboxes: full suite green locally, ruff clean, validate tests re-targeted to `providers._common`, no live smoke needed in PR-1) and:

```powershell
gh pr create --head refactor/provider-common-helpers --title "refactor(providers): lift identical helpers to _common (dedup PR-1)" --body-file "$env:TEMP\pr1-body.md"
```

- [ ] **Step 6.3: STOP — user merge gate**

Wait for the user to review and squash-merge PR-1 into main. Do not start PR-2 before that.

---

# PR-2 — `refactor(providers): unify HTTP transport + poll loop`

Branch from FRESH main after PR-1 merges:

```powershell
git checkout main
git pull
git checkout -b refactor/provider-transport-poll
```

### Task 7: `request()` — the shared HTTP error idiom

**Files:**
- Modify: `providers/_common.py` (append)
- Modify: `tests/test_providers_common.py` (append)

- [ ] **Step 7.1: Write the failing tests**

Append to `tests/test_providers_common.py` (add `request` to the `_common` import at file top):

```python
# ── request ───────────────────────────────────────────────────────────


def test_request_dispatches_via_named_verb_for_patchability():
    r = MagicMock(ok=True, status_code=200)
    with patch("providers._common.requests.post", return_value=r) as p:
        out = request(
            "post", "https://api.example/u", provider="X",
            action_ru="загрузке аудио", action_en="upload",
            timeout=30, json={"a": 1},
        )
    assert out is r
    assert p.call_args.kwargs["timeout"] == 30
    assert p.call_args.kwargs["json"] == {"a": 1}


def test_request_network_error_uses_action_ru():
    with patch(
        "providers._common.requests.get",
        side_effect=requests.RequestException("boom"),
    ):
        with pytest.raises(
            ProviderError, match="Сеть не отвечает при опросе"
        ):
            request("get", "u", provider="X", action_ru="опросе",
                    action_en="poll", timeout=30)


@pytest.mark.parametrize("code", [401, 403])
def test_request_key_rejection_is_russian(code):
    r = MagicMock(ok=False, status_code=code, text="no")
    with patch("providers._common.requests.get", return_value=r):
        with pytest.raises(
            ProviderError, match=r"X отклонил ключ \(401\)"
        ):
            request("get", "u", provider="X", action_ru="опросе",
                    action_en="poll", timeout=30)


def test_request_non_ok_uses_action_en_and_truncates():
    r = MagicMock(ok=False, status_code=500, text="z" * 1000)
    with patch("providers._common.requests.post", return_value=r):
        with pytest.raises(
            ProviderError, match=r"X upload failed \(500\)"
        ) as ei:
            request("post", "u", provider="X", action_ru="загрузке аудио",
                    action_en="upload", timeout=30)
    assert "z" * 300 in str(ei.value)
    assert "z" * 301 not in str(ei.value)
```

- [ ] **Step 7.2: Run to verify failure**

Run: `py -3 -m pytest tests/test_providers_common.py -k "request_" -v`
Expected: FAIL — `ImportError`

- [ ] **Step 7.3: Implement in `_common.py`**

```python
def request(method: str, url: str, *, provider: str, action_ru: str,
            action_en: str, timeout: float, **kwargs) -> requests.Response:
    """One HTTP round-trip with the shared error idiom.

    ``action_ru`` is prepositional-case Russian for the network-failure
    message («загрузке аудио» → «Сеть не отвечает при загрузке аудио»);
    ``action_en`` labels HTTP failures («upload» → «X upload failed (N)»).

    Dispatches via ``getattr(requests, method)`` — NOT requests.request —
    so tests can keep patching per-verb mocks
    (``providers._common.requests.post`` / ``.get``) independently.
    """
    func = getattr(requests, method)
    try:
        r = func(url, timeout=timeout, **kwargs)
    except requests.RequestException as e:
        raise ProviderError(f"Сеть не отвечает при {action_ru}: {e}") from e
    if r.status_code in (401, 403):
        # "(401)" stays hardcoded — matches the #133 validate_key precedent
        # and the existing test match patterns.
        raise ProviderError(
            f"{provider} отклонил ключ (401). Проверь API-ключ в "
            "Настройках → Облако."
        )
    if not r.ok:
        raise ProviderError(
            f"{provider} {action_en} failed ({r.status_code}): "
            f"{r.text[:300]}"
        )
    return r
```

- [ ] **Step 7.4: Run, ruff, commit**

Run: `py -3 -m pytest tests/test_providers_common.py -v` → PASS; ruff clean.

```powershell
git add providers/_common.py tests/test_providers_common.py
git commit -m "refactor(providers): shared request() HTTP error idiom"
```

### Task 8: `parse_json` + `extract_json_key`

**Files:**
- Modify: `providers/_common.py` (append)
- Modify: `tests/test_providers_common.py` (append)

- [ ] **Step 8.1: Write the failing tests**

Extend the `providers._common` import at the top of `tests/test_providers_common.py` with `parse_json, extract_json_key`, then append:

```python
# ── parse_json / extract_json_key ─────────────────────────────────────


def test_parse_json_ok():
    r = MagicMock()
    r.json.return_value = {"a": 1}
    assert parse_json(r, provider="X") == {"a": 1}


def test_parse_json_invalid_with_context():
    r = MagicMock(text="<html>oops</html>")
    r.json.side_effect = ValueError("no json")
    with pytest.raises(
        ProviderError, match="Неожиданный ответ X на upload: <html>oops"
    ):
        parse_json(r, provider="X", context="upload")


def test_parse_json_invalid_without_context():
    r = MagicMock(text="<html>oops</html>")
    r.json.side_effect = ValueError("no json")
    with pytest.raises(ProviderError, match="Неожиданный ответ X: <html>oops"):
        parse_json(r, provider="X")


def test_extract_json_key_ok():
    r = MagicMock()
    r.json.return_value = {"upload_url": "https://cdn/u1"}
    assert extract_json_key(
        r, "upload_url", provider="X", context="upload"
    ) == "https://cdn/u1"


def test_extract_json_key_missing_key():
    r = MagicMock(text='{"other": 1}')
    r.json.return_value = {"other": 1}
    with pytest.raises(ProviderError, match="Неожиданный ответ X на submit"):
        extract_json_key(r, "id", provider="X", context="submit")
```

- [ ] **Step 8.2: Run to verify failure**

Run: `py -3 -m pytest tests/test_providers_common.py -k "parse_json or extract_json" -v` → FAIL (ImportError)

- [ ] **Step 8.3: Implement in `_common.py`**

```python
def parse_json(resp: requests.Response, *, provider: str,
               context: str | None = None) -> dict:
    """Decode a JSON body or raise the shared «Неожиданный ответ» error."""
    try:
        return resp.json()
    except ValueError as e:
        where = f" на {context}" if context else ""
        raise ProviderError(
            f"Неожиданный ответ {provider}{where}: {resp.text[:300]}"
        ) from e


def extract_json_key(resp: requests.Response, key: str, *, provider: str,
                     context: str):
    """parse_json + required-key lookup, same error message on miss."""
    payload = parse_json(resp, provider=provider, context=context)
    try:
        return payload[key]
    except KeyError as e:
        raise ProviderError(
            f"Неожиданный ответ {provider} на {context}: {resp.text[:300]}"
        ) from e
```

- [ ] **Step 8.4: Run, ruff, commit**

```powershell
git add providers/_common.py tests/test_providers_common.py
git commit -m "refactor(providers): shared JSON guards (parse_json, extract_json_key)"
```

### Task 9: `PollSpec` + `poll()`

**Files:**
- Modify: `providers/_common.py` (append; add `import time`, `from collections.abc import Callable`, `from dataclasses import dataclass`)
- Modify: `tests/test_providers_common.py` (append)

- [ ] **Step 9.1: Write the failing tests**

Extend the `providers._common` import at the top of `tests/test_providers_common.py` with `poll`, then append:

```python
# ── poll ──────────────────────────────────────────────────────────────


def _json_resp(payload):
    r = MagicMock(ok=True, status_code=200, text="")
    r.json.return_value = payload
    return r


def _spec(**over):
    from providers._common import PollSpec

    kw = dict(
        url="https://api.example/job/1",
        headers={"h": "1"},
        provider="X",
        interval_s=3.0,
        extract_status=lambda p: p.get("status"),
        done_statuses=frozenset({"completed"}),
        error_statuses=frozenset({"error"}),
        extract_error=lambda p: p.get("error", "<no detail>"),
        pretty={"queued": "В очереди X...", "processing": "Обработка X..."},
    )
    kw.update(over)
    return PollSpec(**kw)


def test_poll_returns_payload_on_done():
    done = {"status": "completed", "text": "hi"}
    with patch("providers._common.requests.get", return_value=_json_resp(done)):
        assert poll(_spec(), None, None) == done


def test_poll_error_status_raises_with_detail():
    bad = {"status": "error", "error": "quota exceeded"}
    with patch("providers._common.requests.get", return_value=_json_resp(bad)):
        with pytest.raises(
            ProviderError, match="X вернул ошибку: quota exceeded"
        ):
            poll(_spec(), None, None)


def test_poll_pretty_status_dedup_and_fallback():
    seq = [
        _json_resp({"status": "queued"}),
        _json_resp({"status": "queued"}),
        _json_resp({"status": "processing"}),
        _json_resp({"status": "completed"}),
    ]
    seen: list[str] = []
    with patch("providers._common.requests.get", side_effect=seq), \
         patch("providers._common.time.sleep"):
        poll(_spec(), seen.append, None)
    # one line per DISTINCT status; unmapped statuses fall back to "X: <s>"
    assert seen == ["В очереди X...", "Обработка X...", "X: completed"]


def test_poll_deadline_raises_before_get():
    with patch(
        "providers._common.time.monotonic", side_effect=[0.0, 90 * 60 + 1.0]
    ), patch("providers._common.requests.get") as g:
        with pytest.raises(
            ProviderError, match="X не вернул результат за 90 минут"
        ):
            poll(_spec(), None, None)
    g.assert_not_called()


def test_poll_non_json_raises_providererror():
    r = MagicMock(ok=True, status_code=200, text="<html>502 Bad Gateway</html>")
    r.json.side_effect = ValueError("no json")
    with patch("providers._common.requests.get", return_value=r):
        with pytest.raises(
            ProviderError, match="X вернул не-JSON ответ при опросе"
        ):
            poll(_spec(), None, None)


def test_poll_cancel_between_polls_raises():
    from transcriber import TranscriptionCancelled

    ev = threading.Event()
    with patch(
        "providers._common.requests.get",
        return_value=_json_resp({"status": "queued"}),
    ), patch(
        "providers._common.time.sleep", side_effect=lambda _s: ev.set()
    ):
        with pytest.raises(TranscriptionCancelled):
            poll(_spec(), None, ev)
```

- [ ] **Step 9.2: Run to verify failure**

Run: `py -3 -m pytest tests/test_providers_common.py -k poll -v` → FAIL (ImportError)

- [ ] **Step 9.3: Implement in `_common.py`**

```python
@dataclass
class PollSpec:
    """Per-provider knobs for the shared completion-poll loop.

    The callables keep response-shape knowledge in the provider module
    (e.g. Speechmatics nests status under ``payload["job"]``); the loop
    machinery — deadline, JSON guard, pretty-status dedup, sliced sleep —
    lives once, in ``poll()``.
    """

    url: str
    headers: dict
    provider: str                      # display name for messages
    interval_s: float                  # AAI/Gladia 3.0; Speechmatics 5.0
    extract_status: Callable[[dict], str | None]
    done_statuses: frozenset
    error_statuses: frozenset
    extract_error: Callable[[dict], str]
    pretty: dict                       # status → Russian status line
    max_wait_s: float = 90 * 60        # generous safety net


def poll(spec: PollSpec, on_status=None, cancel_event=None) -> dict:
    """Block until the remote job reaches a terminal status.

    Behaviour-compatible with the three per-provider loops it replaced:
    0.25 s sleep slices for cancel responsiveness, status lines emitted
    once per distinct status, hard deadline with a Russian timeout message.
    Returns the final payload.
    """
    start = time.monotonic()
    last_status = ""
    while True:
        check_cancel(cancel_event)
        if time.monotonic() - start > spec.max_wait_s:
            raise ProviderError(
                f"{spec.provider} не вернул результат за "
                f"{int(spec.max_wait_s / 60)} минут. Возможно, сервис "
                f"перегружен — попробуй позже."
            )

        r = request(
            "get", spec.url, provider=spec.provider,
            action_ru="опросе", action_en="poll",
            timeout=30, headers=spec.headers,
        )
        try:
            payload = r.json()
        except ValueError as e:
            raise ProviderError(
                f"{spec.provider} вернул не-JSON ответ при опросе "
                f"({r.status_code}): {r.text[:300]}"
            ) from e

        status = spec.extract_status(payload)
        if status != last_status and on_status is not None:
            on_status(spec.pretty.get(status, f"{spec.provider}: {status}"))
            last_status = status

        if status in spec.done_statuses:
            return payload
        if status in spec.error_statuses:
            raise ProviderError(
                f"{spec.provider} вернул ошибку: {spec.extract_error(payload)}"
            )

        slept = 0.0
        while slept < spec.interval_s:
            check_cancel(cancel_event)
            time.sleep(0.25)
            slept += 0.25
```

- [ ] **Step 9.4: Run, ruff, commit**

```powershell
git add providers/_common.py tests/test_providers_common.py
git commit -m "refactor(providers): shared PollSpec poll loop"
```

### Task 10: Rewire AssemblyAI to the transport layer

**Files:**
- Modify: `providers/assemblyai.py`
- Modify: `tests/test_providers_assemblyai.py` (re-target 11 remaining `requests` patches + 1 `time.sleep` patch :301)
- Modify: `tests/test_providers_poll_json_guard.py` (:31 — AAI site)

- [ ] **Step 10.1: Rewire the module**

Imports become (drop `import time`, `import requests`):

```python
from __future__ import annotations

import os

from ._common import (
    PollSpec,
    cancel_remote,
    check_cancel,
    extract_json_key,
    file_stream,
    poll,
    request,
    validate_via_get,
)
from .base import (
    ProviderError,
    TranscriptionOptions,
    TranscriptionProvider,
    TranscriptionResult,
)
```

Replace `_upload` entirely (docstring kept, transport swapped):

```python
    def _upload(self, audio_path: str, on_progress, cancel_event) -> str:
        """Stream-upload the file. AssemblyAI accepts raw bytes (no multipart).

        Chunked via file_stream to give the cancel poll a chance and to
        feed the 0..70 % progress band (70..100 belongs to the remote
        processing phase, mirroring the local progress contract).
        """
        r = request(
            "post",
            f"{_API_BASE}/upload",
            provider=self.display_name,
            action_ru="загрузке аудио",
            action_en="upload",
            timeout=60 * 30,  # 30 min absolute upload cap
            headers=self._headers,
            data=file_stream(
                audio_path, cancel_event=cancel_event, on_progress=on_progress,
            ),
        )
        return extract_json_key(
            r, "upload_url", provider=self.display_name, context="upload",
        )
```

In `_submit`, keep the whole `body` construction (:199-242) byte-identical, replace everything from `try:` to the end of the method with:

```python
        r = request(
            "post",
            f"{_API_BASE}/transcript",
            provider=self.display_name,
            action_ru="постановке задачи",
            action_en="submit",
            timeout=30,
            headers={**self._headers, "content-type": "application/json"},
            json=body,
        )
        return extract_json_key(
            r, "id", provider=self.display_name, context="submit",
        )
```

Replace `_poll` entirely:

```python
    def _poll(self, transcript_id: str, on_status, cancel_event) -> dict:
        """Block until job finishes — shared loop, AssemblyAI knobs."""
        spec = PollSpec(
            url=f"{_API_BASE}/transcript/{transcript_id}",
            headers=self._headers,
            provider=self.display_name,
            interval_s=_POLL_INTERVAL_S,
            extract_status=lambda p: p.get("status"),
            done_statuses=frozenset({"completed"}),
            error_statuses=frozenset({"error"}),
            extract_error=lambda p: p.get("error", "<no detail>"),
            pretty={
                "queued": "В очереди AssemblyAI...",
                "processing": "Обработка на серверах AssemblyAI...",
            },
        )
        return poll(spec, on_status=on_status, cancel_event=cancel_event)
```

`transcribe()` and `_to_segments` stay untouched. Delete the now-dead module constants ONLY if unused (`_POLL_INTERVAL_S` stays — used by the spec; `_MAX_WAIT_S` becomes unused → delete it and its comment; PollSpec default covers it).

- [ ] **Step 10.2: Re-target the AAI tests**

In `tests/test_providers_assemblyai.py`: replace ALL remaining `"providers.assemblyai.requests.` → `"providers._common.requests.` (11 sites — the 2 delete sites were done in PR-1) and `"providers.assemblyai.time.sleep"` → `"providers._common.time.sleep"` (:301). In `tests/test_providers_poll_json_guard.py` :31: `"providers.assemblyai.requests.get"` → `"providers._common.requests.get"`.

- [ ] **Step 10.3: Run, ruff, commit**

Run: `py -3 -m pytest tests/test_providers_assemblyai.py tests/test_providers_poll_json_guard.py -v` → PASS. If a 401-path test now sees «отклонил ключ» where it asserted «poll failed» — that is spec behavior change #1/#2; update the match to «отклонил ключ» in the same commit. `py -3 -m ruff check .` → clean.

```powershell
git add providers/assemblyai.py tests/test_providers_assemblyai.py tests/test_providers_poll_json_guard.py
git commit -m "refactor(providers): assemblyai on shared transport + poll"
```

### Task 11: Rewire Deepgram

**Files:**
- Modify: `providers/deepgram.py`
- Modify: `tests/test_providers_deepgram.py` (re-target 3 patch sites)

- [ ] **Step 11.1: Rewire the module**

Imports become (drop `import requests`):

```python
from __future__ import annotations

import os

from ._common import (
    check_cancel,
    file_stream,
    guess_content_type,
    parse_json,
    request,
    require_key,
    validate_via_get,
)
from .base import (
    ProviderError,
    TranscriptionOptions,
    TranscriptionProvider,
    TranscriptionResult,
)
```

Replace `transcribe()` from the `params = _build_params(options)` line down to (excluding) `segments = _to_segments(...)` with:

```python
        r = request(
            "post",
            _API_URL,
            provider=self.display_name,
            action_ru="загрузке аудио",
            action_en="transcribe",
            timeout=60 * 30,
            params=_build_params(options),
            headers={
                "Authorization": f"Token {self._api_key}",
                "Content-Type": guess_content_type(audio_path),
            },
            data=file_stream(
                audio_path, cancel_event=cancel_event, on_progress=on_progress,
            ),
        )
        payload = parse_json(r, provider=self.display_name)

        if on_status:
            on_status("Готово.")
        if on_progress:
            on_progress(100.0)
```

The mixed-guard, isfile-check and the head of `transcribe` stay byte-identical; `_build_params` / `_extract_language` / `_to_segments` untouched.

- [ ] **Step 11.2: Re-target the DG tests**

Replace 3× `"providers.deepgram.requests.` → `"providers._common.requests.` in `tests/test_providers_deepgram.py`. Spec behavior change #4: the non-ok message is now «Deepgram transcribe failed (N)» — if any DG test matched the old «Deepgram вернул ошибку», update its match (grep showed no test pins it; verify while editing).

- [ ] **Step 11.3: Run, ruff, commit**

Run: `py -3 -m pytest tests/test_providers_deepgram.py -v` → PASS; ruff clean.

```powershell
git add providers/deepgram.py tests/test_providers_deepgram.py
git commit -m "refactor(providers): deepgram on shared transport"
```

### Task 12: Rewire Gladia

**Files:**
- Modify: `providers/gladia.py`
- Modify: `tests/test_providers_gladia.py` (re-target 7 patch sites)
- Modify: `tests/test_providers_poll_json_guard.py` (:39 — Gladia site)

- [ ] **Step 12.1: Rewire the module**

Imports become (drop `import time`, `import requests`):

```python
from __future__ import annotations

import os

from ._common import (
    PollSpec,
    check_cancel,
    extract_json_key,
    guess_content_type,
    poll,
    request,
    require_key,
    validate_via_get,
)
from .base import (
    ProviderError,
    TranscriptionOptions,
    TranscriptionProvider,
    TranscriptionResult,
)
```

Replace `_upload` body after its docstring (file handle must stay open during the call, so `request()` is invoked inside the `with`):

```python
        if on_progress:
            on_progress(5.0)
        with open(path, "rb") as f:
            files = {
                "audio": (
                    os.path.basename(path), f, guess_content_type(path),
                )
            }
            r = request(
                "post",
                f"{_API_BASE}/upload",
                provider=self.display_name,
                action_ru="загрузке аудио",
                action_en="upload",
                timeout=60 * 30,
                headers=self._headers,
                files=files,
            )
        if on_progress:
            on_progress(50.0)
        return extract_json_key(
            r, "audio_url", provider=self.display_name, context="upload",
        )
```

In `_submit`, keep the `body` construction (:174-202) byte-identical, replace from `try:` down:

```python
        r = request(
            "post",
            f"{_API_BASE}/pre-recorded",
            provider=self.display_name,
            action_ru="постановке задачи",
            action_en="submit",
            timeout=30,
            headers={**self._headers, "content-type": "application/json"},
            json=body,
        )
        return extract_json_key(
            r, "result_url", provider=self.display_name, context="submit",
        )
```

Replace `_poll` entirely:

```python
    def _poll(self, result_url: str, on_status, cancel_event) -> dict:
        """Block until the job finishes — shared loop, Gladia knobs."""
        spec = PollSpec(
            url=result_url,
            headers=self._headers,
            provider=self.display_name,
            interval_s=_POLL_INTERVAL_S,
            extract_status=lambda p: p.get("status"),
            done_statuses=frozenset({"done"}),
            error_statuses=frozenset({"error"}),
            extract_error=lambda p: (
                p.get("error_code") or p.get("error") or "<no detail>"
            ),
            pretty={
                "queued": "В очереди Gladia...",
                "processing": "Обработка на серверах Gladia...",
            },
        )
        return poll(spec, on_status=on_status, cancel_event=cancel_event)
```

Delete the now-unused `_MAX_WAIT_S` constant; `_POLL_INTERVAL_S` stays.

- [ ] **Step 12.2: Re-target the Gladia tests**

Replace 7× `"providers.gladia.requests.` → `"providers._common.requests.` in `tests/test_providers_gladia.py`; in `tests/test_providers_poll_json_guard.py` :39 same replacement. Also re-target any `providers.gladia.time.sleep` patches if present (grep first — none known).

- [ ] **Step 12.3: Run, ruff, commit**

Run: `py -3 -m pytest tests/test_providers_gladia.py tests/test_providers_poll_json_guard.py -v` → PASS; ruff clean.

```powershell
git add providers/gladia.py tests/test_providers_gladia.py tests/test_providers_poll_json_guard.py
git commit -m "refactor(providers): gladia on shared transport + poll"
```

### Task 13: Rewire Speechmatics

**Files:**
- Modify: `providers/speechmatics.py`
- Modify: `tests/test_providers_speechmatics.py` (re-target 8 patch sites)
- Modify: `tests/test_providers_poll_json_guard.py` (:47 — SM site)

- [ ] **Step 13.1: Rewire the module**

Imports become (drop `import time`, `import requests`; keep `import json`, `import os`):

```python
from __future__ import annotations

import json
import os

from ._common import (
    PollSpec,
    cancel_remote,
    check_cancel,
    extract_json_key,
    guess_content_type,
    parse_json,
    poll,
    request,
    require_key,
    validate_via_get,
)
from .base import (
    ProviderError,
    TranscriptionOptions,
    TranscriptionProvider,
    TranscriptionResult,
)
```

Replace `_submit_job` body after the docstring:

```python
        config = _build_config(options)
        with open(path, "rb") as f:
            files = {
                "data_file": (
                    os.path.basename(path), f, guess_content_type(path),
                ),
                "config": (None, json.dumps(config), "application/json"),
            }
            r = request(
                "post",
                f"{_API_BASE}/jobs/",
                provider=self.display_name,
                action_ru="загрузке аудио",
                action_en="submit",
                timeout=60 * 30,
                headers=self._headers,
                files=files,
            )
        return extract_json_key(
            r, "id", provider=self.display_name, context="submit",
        )
```

Replace `_wait_for_job` entirely (returns None — callers ignore the payload):

```python
    def _wait_for_job(self, job_id: str, on_status, cancel_event) -> None:
        """Poll /v2/jobs/{id} until done — shared loop, Speechmatics knobs."""
        spec = PollSpec(
            url=f"{_API_BASE}/jobs/{job_id}",
            headers=self._headers,
            provider=self.display_name,
            interval_s=_POLL_INTERVAL_S,
            extract_status=lambda p: (
                (p.get("job") or {}).get("status") or p.get("status")
            ),
            done_statuses=frozenset({"done"}),
            error_statuses=frozenset({"rejected", "deleted", "expired"}),
            extract_error=lambda p: (
                (p.get("job") or {}).get("errors") or "<no detail>"
            ),
            pretty={
                "running": "Обработка на серверах Speechmatics...",
                "queued": "В очереди Speechmatics...",
            },
        )
        poll(spec, on_status=on_status, cancel_event=cancel_event)
```

Replace `_fetch_transcript` entirely:

```python
    def _fetch_transcript(self, job_id: str) -> dict:
        """GET /v2/jobs/{id}/transcript?format=json-v2 — word-level result."""
        r = request(
            "get",
            f"{_API_BASE}/jobs/{job_id}/transcript",
            provider=self.display_name,
            action_ru="получении транскрипта",
            action_en="transcript fetch",
            timeout=60,
            params={"format": "json-v2"},
            headers=self._headers,
        )
        return parse_json(r, provider=self.display_name, context="transcript")
```

Delete the now-unused `_MAX_WAIT_S`; `_POLL_INTERVAL_S = 5.0` stays.

- [ ] **Step 13.2: Re-target the SM tests**

Replace 8× `"providers.speechmatics.requests.` → `"providers._common.requests.` in `tests/test_providers_speechmatics.py`; in `tests/test_providers_poll_json_guard.py` :47 same. Re-target any `providers.speechmatics.time.sleep` patches if present (grep — none known).

- [ ] **Step 13.3: Run, ruff, commit**

Run: `py -3 -m pytest tests/test_providers_speechmatics.py tests/test_providers_poll_json_guard.py -v` → PASS; ruff clean.

```powershell
git add providers/speechmatics.py tests/test_providers_speechmatics.py tests/test_providers_poll_json_guard.py
git commit -m "refactor(providers): speechmatics on shared transport + poll"
```

### Task 14: Absence guard + zero-stale-patch verification

**Files:**
- Create: `tests/test_provider_transport_guard.py`

- [ ] **Step 14.1: Write the guard test (it must pass immediately)**

```python
"""Provider modules must not re-grow transport plumbing (audit Variant 3).

After the _common lift, ALL HTTP calls, sleep/deadline machinery and the
requests-error idiom live in providers/_common.py. If any forbidden
substring reappears in a provider module, the dedup is regressing — move
the new code into _common instead. Same spirit as test_widget_tree_split.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_PROVIDER_DIR = Path(__file__).resolve().parent.parent / "providers"
_MODULES = ["assemblyai.py", "deepgram.py", "gladia.py", "speechmatics.py"]
_FORBIDDEN = [
    "requests.get(",
    "requests.post(",
    "requests.delete(",
    "requests.request(",
    "except requests.RequestException",
    "time.sleep(",
    "time.monotonic(",
]


@pytest.mark.parametrize("module", _MODULES)
def test_no_transport_plumbing_in_provider_modules(module):
    src = (_PROVIDER_DIR / module).read_text(encoding="utf-8")
    hits = [s for s in _FORBIDDEN if s in src]
    assert not hits, (
        f"{module} re-grew transport plumbing {hits} — "
        f"it belongs in providers/_common.py"
    )
```

Run: `py -3 -m pytest tests/test_provider_transport_guard.py -v` → 4 PASS.

- [ ] **Step 14.2: Verify zero stale patch targets**

```powershell
git grep -nE "providers\.(assemblyai|deepgram|gladia|speechmatics)\.(requests|time)" -- tests
```

Expected: NO output. Any hit = a missed re-target; fix it before committing.

- [ ] **Step 14.3: Commit**

```powershell
git add tests/test_provider_transport_guard.py
git commit -m "test: guard provider modules against transport-plumbing regrowth"
```

### Task 15: Docs drift — CLAUDE.md providers row

**Files:**
- Modify: `CLAUDE.md` («Where things live» table, «Cloud transcription providers» row)

- [ ] **Step 15.1: Edit the row**

Append to the row text: `Shared transport plumbing (HTTP error idiom, PollSpec poll loop, file streaming, validate/cancel helpers) lives in providers/_common.py — tests patch HTTP at providers._common.requests (one canonical target).`

- [ ] **Step 15.2: Commit**

```powershell
git add CLAUDE.md
git commit -m "docs: note providers/_common transport layer in CLAUDE.md"
```

### Task 16: Full gate + live AssemblyAI smoke + PR-2

- [ ] **Step 16.1: Full gate**

Run: `py -3 -m pytest` → ≈806 passed / 2 skipped, 0 failed. Run: `py -3 -m ruff check .` → clean.

- [ ] **Step 16.2: Live smoke (AssemblyAI only — the one live key)**

Write to `%TEMP%\smoke_provider_dedup.py` (key read in-process, never printed — #130/#133 pattern):

```python
"""Live AssemblyAI smoke after provider-dedup PR-2.

Proves: validate_key (good + garbage) and the full upload->submit->poll
transport path against the real API. A synthesized tone may transcribe to
empty text — that is fine; the transport contract is what's under test.
"""
import json
import math
import os
import struct
import sys
import tempfile
import wave

sys.path.insert(0, r"C:\Users\nurgisa\Documents\audio-transcriber")

with open(
    os.path.expanduser("~/.audio-transcriber/config.json"), encoding="utf-8"
) as f:
    key = json.load(f)["cloud_api_keys"]["AssemblyAI"]

from providers import ProviderError, get_provider  # noqa: E402

info = get_provider("AssemblyAI", key).validate_key()
print("validate(good): PASS", info)

try:
    get_provider("AssemblyAI", "garbage-key-123").validate_key()
    sys.exit("validate(garbage): FAIL - did not raise")
except ProviderError as e:
    assert "отклонил ключ" in str(e), str(e)
    print("validate(garbage): PASS")

wav_path = os.path.join(tempfile.gettempdir(), "smoke_tone.wav")
with wave.open(wav_path, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(16000)
    w.writeframes(b"".join(
        struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * t / 16000)))
        for t in range(16000 * 2)
    ))

from cli.core import run_transcribe  # noqa: E402

out = run_transcribe(
    wav_path, provider="AssemblyAI", api_key=key, language=None, diarize=False,
)
print("transcribe: PASS -", repr(out.text[:80]), "| lang:", out.language)
print("ALL SMOKE PASS")
```

Run: `py -3 $env:TEMP\smoke_provider_dedup.py`
Expected: three PASS lines + `ALL SMOKE PASS`. On `KeyError: 'AssemblyAI'` — inspect `cloud_api_keys` keys in the config and adjust the lookup, do NOT print values.

- [ ] **Step 16.3: Push + PR**

```powershell
git push -u origin refactor/provider-transport-poll
```

PR body via `%TEMP%\pr2-body.md`: `## Summary` (transport+poll unification, LOC delta, behavior changes #1/#2/#4 from the spec, link to the spec file) + `## Test plan` (full suite green, ruff clean, guard test added, stale-patch grep = 0 hits, live AAI smoke 3×PASS, caveat: Deepgram/Gladia/Speechmatics remain mock-pinned — no live keys, same as #133).

```powershell
gh pr create --head refactor/provider-transport-poll --title "refactor(providers): unify HTTP transport + poll loop (dedup PR-2)" --body-file "$env:TEMP\pr2-body.md"
```

- [ ] **Step 16.4: STOP — user merge gate.**
